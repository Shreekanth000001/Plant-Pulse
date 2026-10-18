"""
FastAPI backend — MQTT ingestion + persistence + live WebSocket +
historical/aggregate REST queries.

Subscribes to everything under factory/#, stores each message, and
broadcasts it to any connected WebSocket client. REST endpoints serve
the aggregate/lookup queries a dashboard needs.

Run:
    uvicorn main:app --host 0.0.0.0 --port 8000

Config (environment variables):
    MQTT_HOST=localhost  MQTT_PORT=1883
"""

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import aiomqtt
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import (
    QCResult,
    SessionLocal,
    StageEvent,
    TelemetryReading,
    Unit,
    get_session,
    init_db,
)
from ingest import IngestEngine, sync_plant_definitions
from plant_definitions import (
    PlantDefinition,
    PlantSummary,
    PublicPlantDefinition,
    load_plants,
)
from topic_router import TopicRouter

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_TOPIC = "factory/#"
RECONNECT_MAX_S = 30


def get_mqtt_credentials() -> tuple[str | None, str | None]:
    return os.getenv("MQTT_USER", MQTT_USER), os.getenv("MQTT_PASSWORD", MQTT_PASSWORD)


PLATFORM_DB_PATH = os.getenv("PLATFORM_DB_PATH", "platform.db")
PLANTS_DIR = Path(os.getenv("PLANTS_DIR", Path(__file__).resolve().parent / "plants"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("factory-backend")
DbSession = Annotated[Session, Depends(get_session)]


class ConnectionManager:
    """Tracks connected clients and fans out messages.
    Supports both legacy global clients and plant-partitioned rooms."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        log.info("WebSocket client connected (%d total)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        log.info("WebSocket client disconnected (%d total)", len(self._clients))

    async def broadcast(self, message: str) -> None:
        if not self._clients:
            return
        clients = list(self._clients)

        async def _send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_text(message), timeout=2.0)
            except Exception:  # noqa: BLE001
                self.disconnect(ws)

        await asyncio.gather(*(_send(ws) for ws in clients))

    async def connect_plant(self, plant_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if plant_id not in self._rooms:
            self._rooms[plant_id] = set()
        self._rooms[plant_id].add(ws)
        log.info(
            "WebSocket client connected to plant %s (%d total in room)",
            plant_id,
            len(self._rooms[plant_id]),
        )

    def disconnect_plant(self, plant_id: str, ws: WebSocket) -> None:
        if plant_id in self._rooms:
            self._rooms[plant_id].discard(ws)
            if not self._rooms[plant_id]:
                del self._rooms[plant_id]
        log.info("WebSocket client disconnected from plant %s", plant_id)

    async def broadcast_to_plant(self, plant_id: str, message: str) -> None:
        clients = list(self._rooms.get(plant_id, set()))
        if not clients:
            return

        async def _send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_text(message), timeout=2.0)
            except Exception:  # noqa: BLE001
                self.disconnect_plant(plant_id, ws)

        await asyncio.gather(*(_send(ws) for ws in clients))


manager = ConnectionManager()
plants_registry: dict[str, PlantDefinition] = {}
ingest_engine: IngestEngine | None = None
topic_router = TopicRouter()

# Queue sizes between stages, e.g. {"casting": 2, "assembly": 0, "qc": 1}.
# Deliberately in-memory, not a database table: it's a "what is true right
# now" value that the publisher refreshes every tick, so storing history of
# it would add rows nobody queries.
latest_queue_depths: dict = {}


# Fields that are "common" columns on TelemetryReading — everything else
# in a telemetry payload goes into the `extra` JSON column.
COMMON_TELEMETRY_FIELDS = {
    "machine_id",
    "name",
    "machine_state",
    "phase",
    "starved",
    "current_unit",
    "vibration",
    "vibration_wear_level",
    "good_count",
    "reject_count",
}


def _store_telemetry(db, sub_facility: str, payload: dict) -> None:
    excluded = COMMON_TELEMETRY_FIELDS | {"last_result", "stage_event"}
    extra = {k: v for k, v in payload.items() if k not in excluded}
    reading = TelemetryReading(
        timestamp=datetime.now(UTC),
        machine_id=payload["machine_id"],
        sub_facility=sub_facility,
        machine_state=payload.get("machine_state"),
        phase=payload.get("phase"),
        starved=payload.get("starved", False),
        current_unit_id=payload.get("current_unit"),
        vibration=payload.get("vibration"),
        vibration_wear_level=payload.get("vibration_wear_level"),
        good_count=payload.get("good_count"),
        reject_count=payload.get("reject_count"),
        extra=extra,
    )
    db.add(reading)


def _store_stage_event(db, payload: dict) -> None:
    unit_id = payload["unit_id"]

    # First time we've seen this unit — Housing's stage_event is always
    # the first one to arrive for any given unit.
    if not db.get(Unit, unit_id):
        db.add(Unit(unit_id=unit_id, status="in_progress"))

    def _to_dt(epoch_seconds):
        return datetime.fromtimestamp(epoch_seconds, tz=UTC) if epoch_seconds else None

    db.add(
        StageEvent(
            unit_id=unit_id,
            sub_facility=payload["sub_facility"],
            machine_id=payload["machine_id"],
            entered_at=_to_dt(payload.get("entered_at")),
            exited_at=_to_dt(payload.get("exited_at")),
            outcome=payload.get("outcome"),
            anomaly_score=payload.get("anomaly_score"),
            readings=payload.get("readings"),
        )
    )


def _store_qc_result(db, machine_id: str, payload: dict) -> None:
    unit_id = payload["unit_id"]

    existing = db.get(Unit, unit_id)
    if not existing:
        db.add(Unit(unit_id=unit_id, status=payload["outcome"]))
    else:
        existing.status = "passed" if payload["outcome"] == "pass" else "failed"

    db.add(
        QCResult(
            unit_id=unit_id,
            machine_id=machine_id,
            tested_at=datetime.now(UTC),
            outcome=payload["outcome"],
            probability=payload.get("probability"),
            defect_type=payload.get("defect_type"),
            attributed_stage=payload.get("attributed_stage"),
        )
    )


def handle_message(topic: str, payload: dict) -> None:
    """topic examples:
    factory/housing/hm_01/telemetry
    factory/housing/hm_01/stage_event
    factory/qc/qc_01/telemetry
    factory/qc/qc_01/result
    factory/queue_depths
    """
    if topic == "factory/queue_depths":
        latest_queue_depths.clear()
        latest_queue_depths.update(payload)
        return

    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != "factory":
        log.warning("Unexpected topic shape, skipping: %s", topic)
        return

    _, sub_facility, machine_id, kind = parts

    db = SessionLocal()
    try:
        if kind == "telemetry":
            _store_telemetry(db, sub_facility, payload)
        elif kind == "stage_event":
            _store_stage_event(db, payload)
        elif kind == "result":
            _store_qc_result(db, machine_id, payload)
        else:
            log.warning("Unknown message kind '%s' on topic %s", kind, topic)
            return
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Failed to store message from topic %s", topic)
    finally:
        db.close()


@topic_router.on("telemetry")
async def handle_plant_telemetry(
    payload: dict, plant_id: str, machine_code: str
) -> None:
    if ingest_engine:
        await ingest_engine.handle_telemetry(payload, plant_id, machine_code)
    await manager.broadcast_to_plant(
        plant_id,
        json.dumps(
            {
                "topic": f"plants/{plant_id}/assets/{machine_code}/telemetry",
                "payload": payload,
            }
        ),
    )


@topic_router.on("state")
async def handle_plant_state(payload: dict, plant_id: str, machine_code: str) -> None:
    await manager.broadcast_to_plant(
        plant_id,
        json.dumps(
            {
                "topic": f"plants/{plant_id}/assets/{machine_code}/state",
                "payload": payload,
            }
        ),
    )


@topic_router.on("stage_event")
async def handle_plant_stage_event(payload: dict, plant_id: str) -> None:
    await manager.broadcast_to_plant(
        plant_id,
        json.dumps(
            {
                "topic": f"plants/{plant_id}/modules/traceability/stage_event",
                "payload": payload,
            }
        ),
    )


@topic_router.on("queue_depths")
async def handle_plant_queue_depths(payload: dict, plant_id: str) -> None:
    await manager.broadcast_to_plant(
        plant_id,
        json.dumps(
            {
                "topic": f"plants/{plant_id}/modules/traceability/queue_depths",
                "payload": payload,
            }
        ),
    )


@topic_router.on("qc_result")
async def handle_plant_qc_result(payload: dict, plant_id: str) -> None:
    await manager.broadcast_to_plant(
        plant_id,
        json.dumps(
            {
                "topic": f"plants/{plant_id}/modules/quality/qc_result",
                "payload": payload,
            }
        ),
    )


@topic_router.on("heartbeat")
async def handle_plant_heartbeat(payload: dict, plant_id: str) -> None:
    await manager.broadcast_to_plant(
        plant_id,
        json.dumps(
            {
                "topic": f"plants/{plant_id}/control/heartbeat",
                "payload": payload,
            }
        ),
    )


DEMO_PLANT_ID = "plant_demo_membrane"
active_mqtt_client: aiomqtt.Client | None = None


async def emit_heartbeat_tick(
    conn_mgr: ConnectionManager | None = None,
    publish_fn: Any | None = None,
    plant_id: str = DEMO_PLANT_ID,
) -> bool:
    """Emits a heartbeat ping if the specified plant has active viewers connected."""
    mgr = conn_mgr or manager
    viewers = len(mgr._rooms.get(plant_id, set()))
    if viewers <= 0:
        return False

    payload = json.dumps({"timestamp": datetime.now(UTC).isoformat()})
    topic = f"plants/{plant_id}/control/heartbeat"

    if publish_fn is not None:
        res = publish_fn(topic, payload)
        if asyncio.iscoroutine(res):
            await res
        return True

    if active_mqtt_client is not None:
        try:
            await active_mqtt_client.publish(topic, payload.encode("utf-8"), qos=1)
            return True
        except Exception:
            log.exception("Failed to publish heartbeat to %s", topic)
            return False

    return False


async def heartbeat_emitter(
    conn_mgr: ConnectionManager | None = None,
    publish_fn: Any | None = None,
    interval: float = 5.0,
    plant_id: str = DEMO_PLANT_ID,
) -> None:
    """Background task emitting heartbeats every interval seconds while demo viewers exist."""
    while True:
        try:
            await emit_heartbeat_tick(
                conn_mgr=conn_mgr, publish_fn=publish_fn, plant_id=plant_id
            )
        except Exception:
            log.exception("Error in heartbeat emitter tick")
        await asyncio.sleep(interval)


async def mqtt_listener() -> None:
    global active_mqtt_client
    delay = 1
    while True:
        try:
            username, password = get_mqtt_credentials()
            async with aiomqtt.Client(
                hostname=MQTT_HOST,
                port=MQTT_PORT,
                username=username,
                password=password,
            ) as client:
                active_mqtt_client = client
                await client.subscribe("plants/#", qos=1)
                await client.subscribe(MQTT_TOPIC, qos=1)
                log.info(
                    "Subscribed to plants/# and %s on %s:%d",
                    MQTT_TOPIC,
                    MQTT_HOST,
                    MQTT_PORT,
                )
                delay = 1

                try:
                    async for message in client.messages:
                        topic_str = str(message.topic)
                        try:
                            payload = json.loads(message.payload.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            log.warning(
                                "Discarding malformed payload on %s", message.topic
                            )
                            continue

                        if topic_str.startswith("plants/"):
                            await topic_router.dispatch(topic_str, payload)
                        elif topic_str.startswith("factory/"):
                            handle_message(topic_str, payload)
                            await manager.broadcast(
                                json.dumps(
                                    {
                                        "topic": topic_str,
                                        "payload": payload,
                                    }
                                )
                            )
                finally:
                    active_mqtt_client = None

        except (aiomqtt.MqttError, OSError) as exc:
            active_mqtt_client = None
            log.error("MQTT error: %s. Reconnecting in %ds...", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_S)


def init_platform_db(db_path: Path | str = PLATFORM_DB_PATH) -> None:
    """Ensure platform database schema exists via Alembic migrations."""
    db_file = Path(db_path)
    if db_file.exists():
        try:
            conn = sqlite3.connect(str(db_file))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='machines';"
            )
            has_table = cursor.fetchone() is not None
            conn.close()
            if has_table:
                return
        except sqlite3.Error:
            pass

    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parent
    ini_path = repo_root / "alembic.ini"
    if ini_path.exists():
        alembic_cfg = Config(str(ini_path))
        alembic_cfg.set_main_option("script_location", str(repo_root / "migrations"))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file.resolve()}")
        command.upgrade(alembic_cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ingest_engine
    init_db()
    init_platform_db(PLATFORM_DB_PATH)

    if PLANTS_DIR.exists():
        loaded = load_plants(PLANTS_DIR)
        plants_registry.clear()
        plants_registry.update(loaded)

        conn = sqlite3.connect(PLATFORM_DB_PATH)
        try:
            conn.execute("PRAGMA foreign_keys=ON;")
            sync_plant_definitions(conn, plants_registry)
        finally:
            conn.close()

    ingest_engine = IngestEngine(db_path=PLATFORM_DB_PATH, plants=plants_registry)
    await ingest_engine.start()

    task = asyncio.create_task(mqtt_listener(), name="mqtt-listener")
    heartbeat_task = asyncio.create_task(heartbeat_emitter(), name="heartbeat-emitter")
    try:
        yield
    finally:
        heartbeat_task.cancel()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if ingest_engine:
            await ingest_engine.stop()


app = FastAPI(title="Factory Telemetry API", lifespan=lifespan)

# Browsers block a page on one origin (localhost:3000, the Next.js dev
# server) from calling an API on another (localhost:8000) unless the API
# explicitly allows it. Add your deployed frontend's URL here later.
# (WebSockets aren't subject to this check, only fetch/XHR requests.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/plants", response_model=list[PlantSummary])
def list_plants() -> list[PlantSummary]:
    return [p.to_summary() for p in plants_registry.values()]


@app.get("/api/plants/{plant_id}/definition", response_model=PublicPlantDefinition)
def get_plant_definition(plant_id: str) -> PublicPlantDefinition:
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")
    return plant.to_public()


@app.get("/api/plants/{plant_id}/machines/latest")
def get_latest_plant_machines(plant_id: str) -> list[dict]:
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")

    if not Path(PLATFORM_DB_PATH).exists():
        return []

    conn = sqlite3.connect(PLATFORM_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        try:
            machines_rows = conn.execute(
                """
                SELECT m.machine_code, m.area_code, m.name, m.machine_type, m.display_order,
                       s.state, s.sub_state, s.last_seen_at
                FROM machines m
                LEFT JOIN machine_states s
                  ON m.plant_id = s.plant_id AND m.machine_code = s.machine_code
                WHERE m.plant_id = ?
                ORDER BY m.display_order
                """,
                (plant_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        telemetry_rows = conn.execute(
            """
            WITH ranked_telemetry AS (
                SELECT machine_code, signal_code, device_timestamp, value_num, value_text,
                       ROW_NUMBER() OVER (
                           PARTITION BY machine_code, signal_code
                           ORDER BY device_timestamp DESC, id DESC
                       ) as rn
                FROM telemetry_values
                WHERE plant_id = ?
            )
            SELECT machine_code, signal_code, device_timestamp, value_num, value_text
            FROM ranked_telemetry
            WHERE rn = 1
            """,
            (plant_id,),
        ).fetchall()

        signals_by_machine: dict[str, dict] = {}
        for tr in telemetry_rows:
            m_code = tr["machine_code"]
            if m_code not in signals_by_machine:
                signals_by_machine[m_code] = {}
            signals_by_machine[m_code][tr["signal_code"]] = {
                "value": tr["value_num"]
                if tr["value_num"] is not None
                else tr["value_text"],
                "value_num": tr["value_num"],
                "value_text": tr["value_text"],
                "device_timestamp": tr["device_timestamp"],
            }

        result = []
        for mr in machines_rows:
            m_code = mr["machine_code"]
            result.append(
                {
                    "machine_code": m_code,
                    "area_code": mr["area_code"],
                    "name": mr["name"],
                    "machine_type": mr["machine_type"],
                    "state": mr["state"] or "IDLE",
                    "sub_state": mr["sub_state"],
                    "last_seen_at": mr["last_seen_at"],
                    "signals": signals_by_machine.get(m_code, {}),
                }
            )
        return result
    finally:
        conn.close()


@app.websocket("/ws/{plant_id}/telemetry")
async def plant_telemetry_ws(ws: WebSocket, plant_id: str) -> None:
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")

    if plant.viewer_token is not None:
        await ws.accept()
        await ws.close(code=4401, reason="Unauthorized")
        return

    await manager.connect_plant(plant_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_plant(plant_id, ws)


@app.websocket("/ws/telemetry")
async def telemetry_ws(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # broadcast-only; read just to detect disconnects
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


@app.get("/api/machines/latest")
def latest_machine_status(db: DbSession) -> list[dict]:
    """Most recent telemetry row for every machine — what a dashboard
    would load on first render, before live WebSocket updates take over."""
    subquery = (
        db.query(
            TelemetryReading.machine_id,
            func.max(TelemetryReading.id).label("latest_id"),
        )
        .group_by(TelemetryReading.machine_id)
        .subquery()
    )
    rows = (
        db.query(TelemetryReading)
        .join(subquery, TelemetryReading.id == subquery.c.latest_id)
        .all()
    )
    return [
        {
            "machine_id": r.machine_id,
            "sub_facility": r.sub_facility,
            "machine_state": r.machine_state,
            "phase": r.phase,
            "starved": r.starved,
            "current_unit_id": r.current_unit_id,
            "vibration": r.vibration,
            "good_count": r.good_count,
            "reject_count": r.reject_count,
            "extra": r.extra,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]


@app.get("/api/queue-depths")
def queue_depths() -> dict:
    """How many units are waiting in front of each stage right now.
    Live updates also arrive over the WebSocket with topic
    'factory/queue_depths'; this endpoint is for the first page load."""
    return dict(latest_queue_depths)


@app.get("/api/units")
def recent_units(db: DbSession, limit: int = 20) -> list[dict]:
    """Most recently created units, newest first — feeds the unit-lookup
    page's 'recent units' list."""
    limit = max(1, min(limit, 100))
    rows = db.query(Unit).order_by(Unit.created_at.desc()).limit(limit).all()
    return [
        {
            "unit_id": u.unit_id,
            "status": u.status,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]


@app.get("/api/units/{unit_id}")
def unit_history(db: DbSession, unit_id: str) -> dict:
    """Full traceable journey for one unit — every stage it passed
    through, plus its QC verdict if tested. This is the payoff of the
    whole traceability design: a real answer to 'why did this fail?'"""
    unit = db.get(Unit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    stages = (
        db.query(StageEvent)
        .filter(StageEvent.unit_id == unit_id)
        .order_by(StageEvent.entered_at)
        .all()
    )
    qc = db.query(QCResult).filter(QCResult.unit_id == unit_id).first()

    return {
        "unit_id": unit.unit_id,
        "status": unit.status,
        "created_at": unit.created_at.isoformat() if unit.created_at else None,
        "stages": [
            {
                "sub_facility": s.sub_facility,
                "machine_id": s.machine_id,
                "outcome": s.outcome,
                "anomaly_score": s.anomaly_score,
                "readings": s.readings,
                "entered_at": s.entered_at.isoformat() if s.entered_at else None,
                "exited_at": s.exited_at.isoformat() if s.exited_at else None,
            }
            for s in stages
        ],
        "qc_result": None
        if not qc
        else {
            "outcome": qc.outcome,
            "probability": qc.probability,
            "defect_type": qc.defect_type,
            "attributed_stage": qc.attributed_stage,
            "tested_at": qc.tested_at.isoformat() if qc.tested_at else None,
        },
    }


@app.get("/api/stats/defect-rate-by-hour")
def defect_rate_by_hour(db: DbSession) -> list[dict]:
    """Defect rate grouped by hour-of-day — this is the metric that
    makes the shift-change bias in defect_model.py visible in real data."""
    # Pull hour+outcome pairs and aggregate in Python — simpler and more
    # portable than a dialect-specific conditional-sum SQL expression,
    # and this table will never be large enough for that to matter.
    hour_expr = func.strftime("%H", QCResult.tested_at)
    results = db.query(hour_expr.label("hour"), QCResult.outcome).all()
    buckets: dict[str, dict[str, int]] = {}
    for hour, outcome in results:
        b = buckets.setdefault(hour, {"total": 0, "failed": 0})
        b["total"] += 1
        if outcome == "fail":
            b["failed"] += 1

    return [
        {
            "hour": hour,
            "total_tested": b["total"],
            "failed": b["failed"],
            "defect_rate": round(b["failed"] / b["total"], 3) if b["total"] else 0,
        }
        for hour, b in sorted(buckets.items())
    ]


@app.get("/api/stats/defect-rate-by-stage")
def defect_rate_by_stage(db: DbSession) -> list[dict]:
    """Of all failures, which stage gets attributed most often — points
    at where the process is actually struggling."""
    rows = (
        db.query(QCResult.attributed_stage, func.count(QCResult.id))
        .filter(QCResult.outcome == "fail")
        .group_by(QCResult.attributed_stage)
        .all()
    )
    return [{"stage": stage, "failures": count} for stage, count in rows]
