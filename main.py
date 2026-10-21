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
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import aiomqtt
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from admin_auth import verify_admin_token
from database import (
    QCResult,
    SessionLocal,
    StageEvent,
    TelemetryReading,
    Unit,
    get_db_connection,
    get_session,
    init_db,
)
from ingest import IngestEngine, sync_plant_definitions
from plant_definitions import (
    AdminCredentialRotateResponse,
    AdminDeviceCredential,
    AdminPlantCreatedResponse,
    AdminPlantDetail,
    AdminPlantSummary,
    AreaDefinition,
    MachineDefinition,
    PlantDefinition,
    PlantSummary,
    PublicPlantDefinition,
    SignalDefinition,
    load_plants,
    load_plants_from_db,
)
from scripts.generate_mosquitto_auth import (
    hash_password_pbkdf2,
    sync_broker_auth_from_db,
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
SYSTEM_PLANT_IDS: frozenset[str] = frozenset({"plant_demo_membrane"})
MOSQUITTO_AUTH_DIR = Path(os.getenv("MOSQUITTO_AUTH_DIR", "/mosquitto/auth"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("factory-backend")
DbSession = Annotated[Session, Depends(get_session)]


class RedactSensitiveFilter(logging.Filter):
    """Logging filter that removes sensitive tickets and bearer tokens from logs."""

    _TICKET_RE = re.compile(r"ticket=[^\s&'\"]+", re.IGNORECASE)
    _BEARER_RE = re.compile(r"Bearer\s+[^\s&'\"]+", re.IGNORECASE)

    def _sanitize(self, text: str) -> str:
        text = self._TICKET_RE.sub("ticket=[REDACTED]", text)
        text = self._BEARER_RE.sub("Bearer [REDACTED]", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)
        if hasattr(record, "message") and isinstance(record.message, str):
            record.message = self._sanitize(record.message)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    self._sanitize(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (self._sanitize(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
        return True


sensitive_filter = RedactSensitiveFilter()
for _name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "factory-backend"):
    logging.getLogger(_name).addFilter(sensitive_filter)


class TicketStore:
    """In-memory single-use ticket store for WebSocket connections.

    Purges expired tickets on issue and enforces a capacity cap.
    """

    def __init__(
        self,
        max_capacity: int = 1000,
        ttl_seconds: float = 30.0,
        clock: Any = None,
    ) -> None:
        self.max_capacity = max_capacity
        self.ttl_seconds = ttl_seconds
        self.clock = clock or time.time
        self._tickets: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def purge_expired(self, now: float | None = None) -> None:
        current_time = self.clock() if now is None else now
        expired = [
            t for t, rec in self._tickets.items() if rec["expires_at"] < current_time
        ]
        for t in expired:
            del self._tickets[t]

    def issue(self, plant_id: str) -> str:
        with self._lock:
            now = self.clock()
            self.purge_expired(now)
            if len(self._tickets) >= self.max_capacity:
                raise HTTPException(status_code=429, detail="Ticket capacity exceeded")
            ticket = secrets.token_urlsafe(32)
            self._tickets[ticket] = {
                "plant_id": plant_id,
                "expires_at": now + self.ttl_seconds,
            }
            return ticket

    def validate_and_consume(self, plant_id: str, ticket: str | None) -> bool:
        if not ticket:
            return False
        with self._lock:
            record = self._tickets.pop(ticket, None)
            if not record:
                return False
            now = self.clock()
            if record["expires_at"] < now:
                return False
            return record["plant_id"] == plant_id

    def revoke_plant(self, plant_id: str) -> None:
        with self._lock:
            to_del = [
                t for t, rec in self._tickets.items() if rec.get("plant_id") == plant_id
            ]
            for t in to_del:
                del self._tickets[t]


ticket_store = TicketStore(max_capacity=1000, ttl_seconds=30.0)


class ViewerTracker:
    """Tracks active REST polling requests across all plants within a sliding time window."""

    def __init__(
        self,
        window_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.window_seconds = window_seconds
        self.clock = clock
        self._last_poll_at: float | None = None

    def record_poll(self) -> None:
        self._last_poll_at = self.clock()

    def has_recent_poll(self) -> bool:
        if self._last_poll_at is None:
            return False
        return (self.clock() - self._last_poll_at) <= self.window_seconds


viewer_tracker = ViewerTracker(window_seconds=15.0)


def verify_plant_viewer(
    plant_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Verify bearer token for plant-scoped endpoints if plant has a viewer token configured."""
    viewer_tracker.record_poll()
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")

    expected_hash = (
        plant.viewer_token_hash
        if plant.viewer_token_hash
        else (
            hashlib.sha256(plant.viewer_token.encode("utf-8")).hexdigest()
            if plant.viewer_token
            else None
        )
    )
    if not expected_hash:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(token_hash, expected_hash):
        raise HTTPException(status_code=401, detail="Unauthorized")


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

    async def close_room(
        self, plant_id: str, code: int = 4404, reason: str = "Plant deleted"
    ) -> None:
        clients = list(self._rooms.pop(plant_id, set()))
        for ws in clients:
            try:
                await ws.close(code=code, reason=reason)
            except (RuntimeError, OSError, ConnectionError, WebSocketDisconnect):
                pass


manager = ConnectionManager()
plants_registry: dict[str, PlantDefinition] = {}
ingest_engine: IngestEngine | None = None
topic_router = TopicRouter()

# Queue sizes between stages, e.g. {"casting": 2, "assembly": 0, "qc": 1}.
# Deliberately in-memory, not a database table: it's a "what is true right
# now" value that the publisher refreshes every tick, so storing history of
# it would add rows nobody queries.
latest_queue_depths: dict = {}
plant_queue_depths: dict[str, dict[str, int]] = {}


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
        plant_queue_depths[DEMO_PLANT_ID] = dict(payload)
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
    if ingest_engine:
        await ingest_engine.handle_state(payload, plant_id, machine_code)
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
    depths = (
        payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    )
    if isinstance(depths, dict):
        plant_queue_depths[plant_id] = dict(depths)
        if plant_id == DEMO_PLANT_ID:
            latest_queue_depths.clear()
            latest_queue_depths.update(depths)
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
    tracker: ViewerTracker | None = None,
) -> bool:
    """Emits a watchdog heartbeat ping if there is at least one active viewer of ANY plant
    (WebSocket room members across all plants, legacy clients, or recent REST polling requests within a 15-second window)."""
    mgr = conn_mgr or manager
    trk = tracker or viewer_tracker

    has_ws_viewers = (
        any(len(clients) > 0 for clients in mgr._rooms.values())
        or len(mgr._clients) > 0
    )
    has_rest_viewers = trk.has_recent_poll()

    if not has_ws_viewers and not has_rest_viewers:
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
    tracker: ViewerTracker | None = None,
) -> None:
    """Background task emitting heartbeats every interval seconds while any plant viewers exist."""
    while True:
        try:
            await emit_heartbeat_tick(
                conn_mgr=conn_mgr,
                publish_fn=publish_fn,
                plant_id=plant_id,
                tracker=tracker,
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
            conn = get_db_connection(str(db_file))
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


def seed_plants_if_empty(conn: sqlite3.Connection, plants_dir: Path) -> bool:
    """Seed plants from plants_dir into platform.db only if plants table is empty.

    Returns True if seeded, False if skipped. Never writes back to plants_dir.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM plants;")
    count = cursor.fetchone()[0]
    if count == 0 and plants_dir.exists():
        loaded = load_plants(plants_dir)
        sync_plant_definitions(conn, loaded)
        return True
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ingest_engine
    init_db()
    init_platform_db(PLATFORM_DB_PATH)

    conn = get_db_connection(PLATFORM_DB_PATH)
    try:
        seed_plants_if_empty(conn, PLANTS_DIR)
        loaded = load_plants_from_db(conn)
        plants_registry.clear()
        plants_registry.update(loaded)
        if MOSQUITTO_AUTH_DIR.exists():
            backend_user, backend_password = get_mqtt_credentials()
            await asyncio.to_thread(
                sync_broker_auth_from_db,
                conn,
                MOSQUITTO_AUTH_DIR,
                backend_user=backend_user or "backend_service",
                backend_password=backend_password or "backend_secret",
                reload=True,
            )
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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def track_viewer_activity(request: Request, call_next):
    if request.url.path.startswith("/api/") and not request.url.path.startswith(
        "/api/admin"
    ):
        viewer_tracker.record_poll()
    return await call_next(request)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/plants", response_model=list[PlantSummary])
def list_plants() -> list[PlantSummary]:
    return [p.to_summary() for p in plants_registry.values()]


@app.get(
    "/api/plants/{plant_id}/definition",
    response_model=PublicPlantDefinition,
    dependencies=[Depends(verify_plant_viewer)],
)
def get_plant_definition(plant_id: str) -> PublicPlantDefinition:
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")
    return plant.to_public()


@app.post(
    "/api/plants/{plant_id}/ws-ticket",
    dependencies=[Depends(verify_plant_viewer)],
)
def create_ws_ticket(plant_id: str) -> dict:
    ticket = ticket_store.issue(plant_id)
    return {"ticket": ticket, "expires_in": 30}


@app.get(
    "/api/plants/{plant_id}/machines/latest",
    dependencies=[Depends(verify_plant_viewer)],
)
def get_latest_plant_machines(plant_id: str) -> list[dict]:
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")

    if not Path(PLATFORM_DB_PATH).exists():
        return []

    conn = get_db_connection(PLATFORM_DB_PATH)
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
                    "state": mr["state"] or "OFFLINE",
                    "sub_state": mr["sub_state"],
                    "last_seen_at": mr["last_seen_at"],
                    "signals": signals_by_machine.get(m_code, {}),
                }
            )
        return result
    finally:
        conn.close()


@app.get(
    "/api/plants/{plant_id}/queue-depths",
    dependencies=[Depends(verify_plant_viewer)],
)
def get_plant_queue_depths(plant_id: str) -> dict:
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")
    if "product_traceability" not in plant.enabled_modules:
        raise HTTPException(
            status_code=404,
            detail=f"Product traceability module not enabled for plant '{plant_id}'",
        )
    return dict(plant_queue_depths.get(plant_id, {}))


@app.get(
    "/api/plants/{plant_id}/machines/{machine_code}/signals/{signal_code}/history",
    dependencies=[Depends(verify_plant_viewer)],
)
def get_signal_history(
    plant_id: str,
    machine_code: str,
    signal_code: str,
    start: str | None = None,
    end: str | None = None,
    points: int = 300,
) -> dict:
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")

    machine = None
    for area in plant.areas:
        for m in area.machines:
            if m.machine_code == machine_code:
                machine = m
                break
        if machine:
            break
    if not machine:
        raise HTTPException(
            status_code=404,
            detail=f"Machine '{machine_code}' not found in plant '{plant_id}'",
        )

    signal = None
    for s in machine.signals:
        if s.signal_code == signal_code:
            signal = s
            break
    if not signal:
        raise HTTPException(
            status_code=404,
            detail=f"Signal '{signal_code}' not found for machine '{machine_code}'",
        )

    if signal.data_type not in ("float", "int"):
        raise HTTPException(
            status_code=400,
            detail=f"Signal '{signal_code}' has non-numeric data type '{signal.data_type}' and cannot be graphed",
        )

    def _parse_ts(raw: str | None, default: datetime) -> datetime:
        if not raw:
            return default
        try:
            clean = raw.strip()
            if " " in clean and not clean.endswith("Z"):
                parts = clean.rsplit(" ", 1)
                if len(parts) == 2 and (":" in parts[1] or len(parts[1]) in (2, 4)):
                    clean = f"{parts[0]}+{parts[1]}"
            clean = clean.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail="Invalid timestamp format"
            ) from exc

    now_utc = datetime.now(UTC)
    end_dt = _parse_ts(end, now_utc)
    start_dt = _parse_ts(start, end_dt - timedelta(hours=1))

    if start_dt > end_dt:
        raise HTTPException(
            status_code=400, detail="start timestamp must be earlier than end timestamp"
        )

    duration_seconds = int((end_dt - start_dt).total_seconds())
    if duration_seconds < 10:
        raise HTTPException(
            status_code=400, detail="Time range must be at least 10 seconds"
        )
    if duration_seconds > 86400:
        raise HTTPException(
            status_code=400,
            detail="Time range exceeds maximum limit of 24 hours",
        )

    clamped_points = min(max(points, 10), 500)
    bucket_sec = max(1, math.ceil(duration_seconds / (clamped_points - 1)))

    if not Path(PLATFORM_DB_PATH).exists():
        return {
            "plant_id": plant_id,
            "machine_code": machine_code,
            "signal_code": signal_code,
            "unit": signal.unit or "",
            "start": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bucket_seconds": bucket_sec,
            "total_points": 0,
            "data": [],
        }

    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    conn = get_db_connection(PLATFORM_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m-%dT%H:%M:%SZ', datetime((CAST(strftime('%s', device_timestamp) AS INTEGER) / :bucket_sec) * :bucket_sec, 'unixepoch')) AS timestamp,
                ROUND(AVG(value_num), 2) AS avg,
                ROUND(MIN(value_num), 2) AS min,
                ROUND(MAX(value_num), 2) AS max,
                COUNT(value_num) AS count
            FROM telemetry_values
            WHERE plant_id = :plant_id
              AND machine_code = :machine_code
              AND signal_code = :signal_code
              AND value_num IS NOT NULL
              AND device_timestamp >= :start_iso
              AND device_timestamp <= :end_iso
            GROUP BY (CAST(strftime('%s', device_timestamp) AS INTEGER) / :bucket_sec)
            ORDER BY timestamp ASC
            """,
            {
                "plant_id": plant_id,
                "machine_code": machine_code,
                "signal_code": signal_code,
                "bucket_sec": bucket_sec,
                "start_iso": start_iso,
                "end_iso": end_iso,
            },
        ).fetchall()

        data = [
            {
                "timestamp": r["timestamp"],
                "avg": r["avg"],
                "min": r["min"],
                "max": r["max"],
                "count": r["count"],
            }
            for r in rows
        ]

        return {
            "plant_id": plant_id,
            "machine_code": machine_code,
            "signal_code": signal_code,
            "unit": signal.unit or "",
            "start": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bucket_seconds": bucket_sec,
            "total_points": len(data),
            "data": data,
        }
    finally:
        conn.close()


@app.websocket("/ws/{plant_id}/telemetry")
async def plant_telemetry_ws(
    ws: WebSocket, plant_id: str, ticket: str | None = None
) -> None:
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")

    if (
        plant.viewer_token or plant.viewer_token_hash
    ) and not ticket_store.validate_and_consume(plant_id, ticket):
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


admin_router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_token)],
)


@admin_router.get("/health")
def admin_health() -> dict:
    return {"status": "ok"}


@admin_router.get("/plants", response_model=list[AdminPlantSummary])
def admin_list_plants() -> list[AdminPlantSummary]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, timezone, viewer_token_hash FROM plants ORDER BY id;"
        )
        rows = cur.fetchall()
        return [
            AdminPlantSummary(
                plant_id=row["id"],
                name=row["name"],
                timezone=row["timezone"],
                has_viewer_token=bool(row["viewer_token_hash"]),
            )
            for row in rows
        ]
    finally:
        conn.close()


def _batched_delete_telemetry(
    conn: sqlite3.Connection,
    plant_id: str,
    machine_code: str | None = None,
    signal_code: str | None = None,
    batch_size: int = 5000,
) -> int:
    """Delete telemetry_values for a plant/machine/signal in batches to avoid write lock starvation."""
    total_deleted = 0
    cur = conn.cursor()

    where_clauses = ["plant_id = ?"]
    params: list[Any] = [plant_id]
    if machine_code is not None:
        where_clauses.append("machine_code = ?")
        params.append(machine_code)
    if signal_code is not None:
        where_clauses.append("signal_code = ?")
        params.append(signal_code)

    where_sql = " AND ".join(where_clauses)
    delete_sql = f"""
    DELETE FROM telemetry_values
    WHERE rowid IN (
        SELECT rowid FROM telemetry_values
        WHERE {where_sql}
        LIMIT ?
    )
    """
    while True:
        cur.execute(delete_sql, params + [batch_size])
        count = cur.rowcount
        conn.commit()
        total_deleted += count
        if count < batch_size:
            break
        time.sleep(0.005)

    return total_deleted


def _sync_single_plant(
    conn: sqlite3.Connection,
    plant: PlantDefinition,
    touch_credentials: bool = True,
) -> list[AdminDeviceCredential]:
    """Upsert plant, areas, machines, signals, and optionally credentials into platform.db."""
    cursor = conn.cursor()
    if plant.viewer_token:
        viewer_token_hash = hashlib.sha256(
            plant.viewer_token.encode("utf-8")
        ).hexdigest()
    elif plant.viewer_token_hash:
        viewer_token_hash = plant.viewer_token_hash
    else:
        cursor.execute(
            "SELECT viewer_token_hash FROM plants WHERE id = ?;", (plant.plant_id,)
        )
        row = cursor.fetchone()
        viewer_token_hash = row["viewer_token_hash"] if row else None

    cursor.execute(
        """
        INSERT INTO plants (id, name, timezone, viewer_token_hash)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            name = excluded.name,
            timezone = excluded.timezone,
            viewer_token_hash = excluded.viewer_token_hash
        """,
        (
            plant.plant_id,
            plant.name,
            plant.timezone,
            viewer_token_hash,
        ),
    )

    generated_creds: list[AdminDeviceCredential] = []
    if touch_credentials:
        if plant.mqtt_credentials:
            for cred in plant.mqtt_credentials:
                pwd = cred.password
                p_hash = pwd if pwd.startswith("$7$") else hash_password_pbkdf2(pwd)
                cursor.execute(
                    """
                    INSERT INTO plant_credentials (plant_id, username, client_id, password_hash, is_active)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT (plant_id, username) DO UPDATE SET
                        client_id = excluded.client_id,
                        password_hash = excluded.password_hash,
                        is_active = excluded.is_active
                    """,
                    (
                        plant.plant_id,
                        cred.username,
                        cred.client_id,
                        p_hash,
                    ),
                )
        else:
            gen_user = f"device_{plant.plant_id}"
            gen_pass = secrets.token_urlsafe(32)
            gen_hash = hash_password_pbkdf2(gen_pass)
            gen_client = f"client_{plant.plant_id}"
            cursor.execute(
                """
                INSERT INTO plant_credentials (plant_id, username, client_id, password_hash, is_active)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT (plant_id, username) DO UPDATE SET
                    client_id = excluded.client_id,
                    password_hash = excluded.password_hash,
                    is_active = excluded.is_active
                """,
                (
                    plant.plant_id,
                    gen_user,
                    gen_client,
                    gen_hash,
                ),
            )
            generated_creds.append(
                AdminDeviceCredential(username=gen_user, password=gen_pass)
            )

    for area in plant.areas:
        cursor.execute(
            """
            INSERT INTO areas (plant_id, area_code, name, display_order)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (plant_id, area_code) DO UPDATE SET
                name = excluded.name,
                display_order = excluded.display_order
            """,
            (plant.plant_id, area.area_code, area.name, area.display_order),
        )

        for machine in area.machines:
            cursor.execute(
                """
                INSERT INTO machines (plant_id, machine_code, area_code, name, machine_type, display_order)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (plant_id, machine_code) DO UPDATE SET
                    area_code = excluded.area_code,
                    name = excluded.name,
                    machine_type = excluded.machine_type,
                    display_order = excluded.display_order
                """,
                (
                    plant.plant_id,
                    machine.machine_code,
                    area.area_code,
                    machine.name,
                    machine.machine_type,
                    machine.display_order,
                ),
            )

            for sig in machine.signals:
                cursor.execute(
                    """
                    INSERT INTO signals (
                        plant_id, machine_code, signal_code, name, unit, data_type,
                        is_setpoint, setpoint_signal_code, normal_min, normal_max,
                        warn_min, warn_max, alarm_min, alarm_max, display_order
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (plant_id, machine_code, signal_code) DO UPDATE SET
                        name = excluded.name,
                        unit = excluded.unit,
                        data_type = excluded.data_type,
                        is_setpoint = excluded.is_setpoint,
                        normal_min = excluded.normal_min,
                        normal_max = excluded.normal_max,
                        warn_min = excluded.warn_min,
                        warn_max = excluded.warn_max,
                        alarm_min = excluded.alarm_min,
                        alarm_max = excluded.alarm_max,
                        display_order = excluded.display_order
                    """,
                    (
                        plant.plant_id,
                        machine.machine_code,
                        sig.signal_code,
                        sig.name,
                        sig.unit,
                        sig.data_type,
                        sig.is_setpoint,
                        sig.normal_min,
                        sig.normal_max,
                        sig.warn_min,
                        sig.warn_max,
                        sig.alarm_min,
                        sig.alarm_max,
                        sig.display_order,
                    ),
                )

            for sig in machine.signals:
                if sig.setpoint_signal_code:
                    cursor.execute(
                        """
                        UPDATE signals
                        SET setpoint_signal_code = ?
                        WHERE plant_id = ? AND machine_code = ? AND signal_code = ?
                        """,
                        (
                            sig.setpoint_signal_code,
                            plant.plant_id,
                            machine.machine_code,
                            sig.signal_code,
                        ),
                    )
    return generated_creds


def _fetch_admin_plant_detail(
    conn: sqlite3.Connection, plant_id: str
) -> AdminPlantDetail:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, timezone, viewer_token_hash FROM plants WHERE id = ?;",
        (plant_id,),
    )
    p_row = cur.fetchone()
    if not p_row:
        raise HTTPException(
            status_code=404,
            detail=f"Plant '{plant_id}' not found",
        )

    cur.execute(
        "SELECT area_code, name, display_order FROM areas WHERE plant_id = ? ORDER BY display_order, area_code;",
        (plant_id,),
    )
    area_rows = cur.fetchall()
    areas: list[AreaDefinition] = []
    for a_row in area_rows:
        a_code = a_row["area_code"]
        cur.execute(
            "SELECT machine_code, name, machine_type, display_order FROM machines WHERE plant_id = ? AND area_code = ? ORDER BY display_order, machine_code;",
            (plant_id, a_code),
        )
        machine_rows = cur.fetchall()
        machines: list[MachineDefinition] = []
        for m_row in machine_rows:
            m_code = m_row["machine_code"]
            cur.execute(
                """
                SELECT signal_code, name, unit, data_type, is_setpoint, setpoint_signal_code,
                       normal_min, normal_max, warn_min, warn_max, alarm_min, alarm_max, display_order
                FROM signals
                WHERE plant_id = ? AND machine_code = ?
                ORDER BY display_order, signal_code;
                """,
                (plant_id, m_code),
            )
            signal_rows = cur.fetchall()
            signals = [
                SignalDefinition(
                    signal_code=s["signal_code"],
                    name=s["name"],
                    unit=s["unit"] or "",
                    data_type=s["data_type"],
                    is_setpoint=bool(s["is_setpoint"]),
                    setpoint_signal_code=s["setpoint_signal_code"],
                    normal_min=s["normal_min"],
                    normal_max=s["normal_max"],
                    warn_min=s["warn_min"],
                    warn_max=s["warn_max"],
                    alarm_min=s["alarm_min"],
                    alarm_max=s["alarm_max"],
                    display_order=s["display_order"],
                )
                for s in signal_rows
            ]
            machines.append(
                MachineDefinition(
                    machine_code=m_code,
                    name=m_row["name"],
                    machine_type=m_row["machine_type"],
                    display_order=m_row["display_order"],
                    signals=signals,
                )
            )
        areas.append(
            AreaDefinition(
                area_code=a_code,
                name=a_row["name"],
                display_order=a_row["display_order"],
                machines=machines,
            )
        )

    cur.execute(
        "SELECT username FROM plant_credentials WHERE plant_id = ? ORDER BY username;",
        (plant_id,),
    )
    cred_rows = cur.fetchall()
    device_usernames = [c["username"] for c in cred_rows]

    return AdminPlantDetail(
        plant_id=p_row["id"],
        name=p_row["name"],
        timezone=p_row["timezone"],
        has_viewer_token=bool(p_row["viewer_token_hash"]),
        device_usernames=device_usernames,
        areas=areas,
    )


@admin_router.get("/plants/{plant_id}", response_model=AdminPlantDetail)
def admin_get_plant_detail(plant_id: str) -> AdminPlantDetail:
    conn = get_db_connection()
    try:
        return _fetch_admin_plant_detail(conn, plant_id)
    finally:
        conn.close()


@admin_router.post(
    "/plants",
    response_model=AdminPlantCreatedResponse,
    response_model_exclude_none=True,
    status_code=201,
)
async def admin_create_plant(
    plant: PlantDefinition, response: Response
) -> AdminPlantCreatedResponse:
    response.headers["Cache-Control"] = "no-store"
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM plants WHERE id = ?;", (plant.plant_id,))
        if cur.fetchone():
            raise HTTPException(
                status_code=409,
                detail=f"Plant '{plant.plant_id}' already exists",
            )

        generated_creds = _sync_single_plant(conn, plant, touch_credentials=True)
        conn.commit()

        if plant.viewer_token and not plant.viewer_token_hash:
            plant.viewer_token_hash = hashlib.sha256(
                plant.viewer_token.encode("utf-8")
            ).hexdigest()
        plants_registry[plant.plant_id] = plant
        if ingest_engine:
            ingest_engine.update_plant(plant)

        broker_reloaded = False
        if MOSQUITTO_AUTH_DIR.exists():
            backend_user, backend_password = get_mqtt_credentials()
            broker_reloaded = await asyncio.to_thread(
                sync_broker_auth_from_db,
                conn,
                MOSQUITTO_AUTH_DIR,
                backend_user=backend_user or "backend_service",
                backend_password=backend_password or "backend_secret",
                reload=True,
            )

        detail = _fetch_admin_plant_detail(conn, plant.plant_id)
        creds_return = generated_creds if generated_creds else None
        return AdminPlantCreatedResponse(
            **detail.model_dump(),
            one_time_device_credentials=creds_return,
            broker_reloaded=broker_reloaded,
        )
    finally:
        conn.close()


@admin_router.put(
    "/plants/{plant_id}",
    response_model=AdminPlantDetail,
)
async def admin_update_plant(
    plant_id: str,
    plant: PlantDefinition,
    confirm_removals: bool = False,
) -> AdminPlantDetail:
    if plant.plant_id != plant_id:
        raise HTTPException(
            status_code=400,
            detail=f"Plant ID in path '{plant_id}' does not match body '{plant.plant_id}'",
        )

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM plants WHERE id = ?;", (plant_id,))
        if not cur.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Plant '{plant_id}' not found",
            )

        cur.execute("SELECT area_code FROM areas WHERE plant_id = ?;", (plant_id,))
        existing_areas = {r["area_code"] for r in cur.fetchall()}

        cur.execute(
            "SELECT machine_code FROM machines WHERE plant_id = ?;", (plant_id,)
        )
        existing_machines = {r["machine_code"] for r in cur.fetchall()}

        cur.execute(
            "SELECT machine_code, signal_code FROM signals WHERE plant_id = ?;",
            (plant_id,),
        )
        existing_signals = {
            (r["machine_code"], r["signal_code"]) for r in cur.fetchall()
        }

        new_areas = {a.area_code for a in plant.areas}
        new_machines = {m.machine_code for a in plant.areas for m in a.machines}
        new_signals = {
            (m.machine_code, s.signal_code)
            for a in plant.areas
            for m in a.machines
            for s in m.signals
        }

        removed_areas = sorted(existing_areas - new_areas)
        removed_machines = sorted(existing_machines - new_machines)
        removed_signals = sorted(existing_signals - new_signals)

        if removed_areas or removed_machines or removed_signals:
            if not confirm_removals:
                removals_summary = []
                if removed_areas:
                    removals_summary.append(f"areas: {removed_areas}")
                if removed_machines:
                    removals_summary.append(f"machines: {removed_machines}")
                if removed_signals:
                    removals_summary.append(
                        f"signals: {[f'{m}:{s}' for m, s in removed_signals]}"
                    )
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Updating plant would remove existing components ({', '.join(removals_summary)}). "
                        "Pass ?confirm_removals=true to proceed."
                    ),
                )

            for m_code, s_code in removed_signals:
                if m_code not in removed_machines:
                    await asyncio.to_thread(
                        _batched_delete_telemetry, conn, plant_id, m_code, s_code
                    )
            for m_code in removed_machines:
                await asyncio.to_thread(
                    _batched_delete_telemetry, conn, plant_id, m_code
                )

            for m_code, s_code in removed_signals:
                cur.execute(
                    "DELETE FROM signals WHERE plant_id = ? AND machine_code = ? AND signal_code = ?;",
                    (plant_id, m_code, s_code),
                )
            for m_code in removed_machines:
                cur.execute(
                    "DELETE FROM machines WHERE plant_id = ? AND machine_code = ?;",
                    (plant_id, m_code),
                )
            for a_code in removed_areas:
                cur.execute(
                    "DELETE FROM areas WHERE plant_id = ? AND area_code = ?;",
                    (plant_id, a_code),
                )
            conn.commit()

        _sync_single_plant(conn, plant, touch_credentials=False)
        conn.commit()

        if plant.viewer_token:
            plant.viewer_token_hash = hashlib.sha256(
                plant.viewer_token.encode("utf-8")
            ).hexdigest()
        elif not plant.viewer_token_hash:
            cur.execute(
                "SELECT viewer_token_hash FROM plants WHERE id = ?;", (plant_id,)
            )
            v_row = cur.fetchone()
            plant.viewer_token_hash = v_row["viewer_token_hash"] if v_row else None

        plants_registry[plant.plant_id] = plant
        if ingest_engine:
            ingest_engine.update_plant(plant)

        return _fetch_admin_plant_detail(conn, plant.plant_id)
    finally:
        conn.close()


@admin_router.post(
    "/plants/{plant_id}/credentials/rotate",
    response_model=AdminCredentialRotateResponse,
)
async def admin_rotate_plant_credentials(
    plant_id: str, response: Response
) -> AdminCredentialRotateResponse:
    response.headers["Cache-Control"] = "no-store"
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM plants WHERE id = ?;", (plant_id,))
        if not cur.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Plant '{plant_id}' not found",
            )

        cur.execute(
            "SELECT username, client_id FROM plant_credentials WHERE plant_id = ? ORDER BY username LIMIT 1;",
            (plant_id,),
        )
        row = cur.fetchone()
        if row:
            username = row["username"]
            client_id = row["client_id"]
        else:
            username = f"device_{plant_id}"
            client_id = f"client_{plant_id}"

        new_password = secrets.token_urlsafe(32)
        new_hash = hash_password_pbkdf2(new_password)

        cur.execute(
            """
            INSERT INTO plant_credentials (plant_id, username, client_id, password_hash, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT (plant_id, username) DO UPDATE SET
                client_id = excluded.client_id,
                password_hash = excluded.password_hash,
                is_active = excluded.is_active;
            """,
            (plant_id, username, client_id, new_hash),
        )
        conn.commit()

        broker_reloaded = False
        if MOSQUITTO_AUTH_DIR.exists():
            backend_user, backend_password = get_mqtt_credentials()
            broker_reloaded = await asyncio.to_thread(
                sync_broker_auth_from_db,
                conn,
                MOSQUITTO_AUTH_DIR,
                backend_user=backend_user or "backend_service",
                backend_password=backend_password or "backend_secret",
                reload=True,
            )

        return AdminCredentialRotateResponse(
            plant_id=plant_id,
            username=username,
            password=new_password,
            broker_reloaded=broker_reloaded,
        )
    finally:
        conn.close()


@admin_router.delete("/plants/{plant_id}")
async def admin_delete_plant(plant_id: str) -> dict:
    if plant_id in SYSTEM_PLANT_IDS:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot delete system plant '{plant_id}'",
        )

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM plants WHERE id = ?;", (plant_id,))
        if not cur.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Plant '{plant_id}' not found",
            )

        plants_registry.pop(plant_id, None)
        if ingest_engine:
            ingest_engine.remove_plant(plant_id)
        plant_queue_depths.pop(plant_id, None)
        ticket_store.revoke_plant(plant_id)

        await manager.close_room(plant_id, code=4404, reason="Plant deleted")

        await asyncio.to_thread(_batched_delete_telemetry, conn, plant_id)

        cur.execute("DELETE FROM plant_credentials WHERE plant_id = ?;", (plant_id,))
        cur.execute("DELETE FROM plants WHERE id = ?;", (plant_id,))
        conn.commit()

        broker_reloaded = False
        if MOSQUITTO_AUTH_DIR.exists():
            backend_user, backend_password = get_mqtt_credentials()
            broker_reloaded = await asyncio.to_thread(
                sync_broker_auth_from_db,
                conn,
                MOSQUITTO_AUTH_DIR,
                backend_user=backend_user or "backend_service",
                backend_password=backend_password or "backend_secret",
                reload=True,
            )

        return {
            "status": "deleted",
            "plant_id": plant_id,
            "broker_reloaded": broker_reloaded,
        }
    finally:
        conn.close()


def build_app(mount_admin: bool | None = None) -> FastAPI:
    if mount_admin is None:
        mount_admin = os.getenv("MOUNT_ADMIN_ENDPOINTS", "false").lower() in (
            "true",
            "1",
            "yes",
        )

    has_admin = any(
        getattr(r, "original_router", None) is admin_router for r in app.router.routes
    )
    if mount_admin and not has_admin:
        app.include_router(admin_router)
    elif not mount_admin and has_admin:
        app.router.routes = [
            r
            for r in app.router.routes
            if getattr(r, "original_router", None) is not admin_router
        ]
    return app


build_app()
