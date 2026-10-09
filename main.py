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
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiomqtt
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import (
    init_db, SessionLocal, get_session,
    TelemetryReading, Unit, StageEvent, QCResult,
)

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = "factory/#"
RECONNECT_MAX_S = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("factory-backend")

class ConnectionManager:
    """Same pattern as the earlier FastAPI/WebSocket prototype — tracks
    connected clients, fans out messages to all of them concurrently."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

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
            except Exception:
                self.disconnect(ws)

        await asyncio.gather(*(_send(ws) for ws in clients))


manager = ConnectionManager()

# Queue sizes between stages, e.g. {"casting": 2, "assembly": 0, "qc": 1}.
# Deliberately in-memory, not a database table: it's a "what is true right
# now" value that the publisher refreshes every tick, so storing history of
# it would add rows nobody queries.
latest_queue_depths: dict = {}


# Fields that are "common" columns on TelemetryReading — everything else
# in a telemetry payload goes into the `extra` JSON column.
COMMON_TELEMETRY_FIELDS = {
    "machine_id", "name", "machine_state", "phase", "starved", "current_unit",
    "vibration", "vibration_wear_level", "good_count", "reject_count",
}


def _store_telemetry(db, sub_facility: str, payload: dict) -> None:
    excluded = COMMON_TELEMETRY_FIELDS | {"last_result", "stage_event"}
    extra = {k: v for k, v in payload.items() if k not in excluded}
    reading = TelemetryReading(
        timestamp=datetime.now(timezone.utc),
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
        return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc) if epoch_seconds else None

    db.add(StageEvent(
        unit_id=unit_id,
        sub_facility=payload["sub_facility"],
        machine_id=payload["machine_id"],
        entered_at=_to_dt(payload.get("entered_at")),
        exited_at=_to_dt(payload.get("exited_at")),
        outcome=payload.get("outcome"),
        anomaly_score=payload.get("anomaly_score"),
        readings=payload.get("readings"),
    ))


def _store_qc_result(db, machine_id: str, payload: dict) -> None:
    unit_id = payload["unit_id"]

    existing = db.get(Unit, unit_id)
    if not existing:
        db.add(Unit(unit_id=unit_id, status=payload["outcome"]))
    else:
        existing.status = "passed" if payload["outcome"] == "pass" else "failed"

    db.add(QCResult(
        unit_id=unit_id,
        machine_id=machine_id,
        tested_at=datetime.now(timezone.utc),
        outcome=payload["outcome"],
        probability=payload.get("probability"),
        defect_type=payload.get("defect_type"),
        attributed_stage=payload.get("attributed_stage"),
    ))


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


async def mqtt_listener() -> None:
    delay = 1
    while True:
        try:
            async with aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT) as client:
                await client.subscribe(MQTT_TOPIC, qos=1)
                log.info("Subscribed to %s on %s:%d", MQTT_TOPIC, MQTT_HOST, MQTT_PORT)
                delay = 1

                async for message in client.messages:
                    try:
                        payload = json.loads(message.payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        log.warning("Discarding malformed payload on %s", message.topic)
                        continue

                    handle_message(str(message.topic), payload)

                    # Broadcast every message to connected dashboards,
                    # tagged with its topic so the frontend can tell a
                    # telemetry tick apart from a stage_event or result.
                    await manager.broadcast(json.dumps({
                        "topic": str(message.topic),
                        "payload": payload,
                    }))

        except aiomqtt.MqttError as exc:
            log.error("MQTT error: %s. Reconnecting in %ds...", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(mqtt_listener(), name="mqtt-listener")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


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
def latest_machine_status(db: Session = Depends(get_session)) -> list[dict]:
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
def recent_units(limit: int = 20, db: Session = Depends(get_session)) -> list[dict]:
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
def unit_history(unit_id: str, db: Session = Depends(get_session)) -> dict:
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
        "qc_result": None if not qc else {
            "outcome": qc.outcome,
            "probability": qc.probability,
            "defect_type": qc.defect_type,
            "attributed_stage": qc.attributed_stage,
            "tested_at": qc.tested_at.isoformat() if qc.tested_at else None,
        },
    }


@app.get("/api/stats/defect-rate-by-hour")
def defect_rate_by_hour(db: Session = Depends(get_session)) -> list[dict]:
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
def defect_rate_by_stage(db: Session = Depends(get_session)) -> list[dict]:
    """Of all failures, which stage gets attributed most often — points
    at where the process is actually struggling."""
    rows = (
        db.query(QCResult.attributed_stage, func.count(QCResult.id))
        .filter(QCResult.outcome == "fail")
        .group_by(QCResult.attributed_stage)
        .all()
    )
    return [{"stage": stage, "failures": count} for stage, count in rows]