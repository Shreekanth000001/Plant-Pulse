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
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import aiomqtt
import jwt
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
from starlette.types import Message, Receive, Scope, Send

from admin_auth import (
    AdminUser,
    ClerkUser,
    _decode_clerk_jwt,
    get_client_ip,
    require_plant_access,
    require_platform_admin,
    verify_admin_token,
    verify_admin_user,
    verify_clerk_user,
    viewer_rate_limiter,
)
from db import ensure_partitions, get_database_url, get_db_connection
from ingest import IngestEngine, sync_plant_definitions
from plant_definitions import (
    AdminCredentialRotateResponse,
    AdminDeviceCredential,
    AdminPlantCreatedResponse,
    AdminPlantDetail,
    AdminPlantSummary,
    AreaDefinition,
    MachineDefinition,
    MyPlantSummary,
    PlantDefinition,
    PlantSummary,
    PublicPlantDefinition,
    SignalDefinition,
    ViewerTokenRotateResponse,
    load_plants,
    load_plants_from_db,
)
from retention import (
    RetentionWorker,
    get_retention_days,
    get_retention_interval_seconds,
    is_retention_worker_enabled,
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
    request: Request,
    plant_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Verify bearer token for plant-scoped endpoints if plant has a viewer token configured.
    Enforces per-IP sliding-window lockout rate limiting on protected plants.
    """
    viewer_tracker.record_poll()
    ip = get_client_ip(request)

    # 1. Lockout check runs before header parsing and token comparison
    if viewer_rate_limiter.is_locked_out(ip):
        retry_after = viewer_rate_limiter.retry_after(ip)
        raise HTTPException(
            status_code=429,
            detail="Too many failed authentication attempts. Locked out.",
            headers={"Retry-After": str(retry_after)},
        )

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

    # 2. Header format validation - malformed headers count as failures
    if not authorization or not authorization.startswith("Bearer "):
        viewer_rate_limiter.record_failure(ip)
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization[7:].strip()
    if not token:
        viewer_rate_limiter.record_failure(ip)
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 3. Constant-time viewer token verification
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if hmac.compare_digest(token_hash, expected_hash):
        viewer_rate_limiter.record_success(ip)
        return

    # 4. Static ADMIN_TOKEN verification (platform_admin)
    admin_token = os.getenv("ADMIN_TOKEN")
    if admin_token and secrets.compare_digest(
        token.encode("utf-8"), admin_token.encode("utf-8")
    ):
        viewer_rate_limiter.record_success(ip)
        return

    # 5. Clerk JWT verification (platform_admin or plant owner in plant_members)
    try:
        payload = _decode_clerk_jwt(token)
    except (jwt.PyJWTError, ValueError):
        payload = None

    if payload:
        meta = payload.get("metadata")
        if not isinstance(meta, dict):
            meta = payload.get("public_metadata")
        if not isinstance(meta, dict):
            meta = {}
        role = meta.get("role") or payload.get("role")
        user_id = payload.get("sub", "")

        # platform_admin can view all plants
        if role == "platform_admin":
            viewer_rate_limiter.record_success(ip)
            return

        # Owner check against plant_members table
        if user_id:
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT 1 FROM plant_members WHERE plant_id = %s AND user_id = %s AND role = 'owner';",
                    (plant_id, user_id),
                )
                if cur.fetchone():
                    viewer_rate_limiter.record_success(ip)
                    return
            finally:
                conn.close()

    viewer_rate_limiter.record_failure(ip)
    raise HTTPException(status_code=401, detail="Unauthorized")


class ConnectionManager:
    """Tracks connected clients and fans out messages partitioned by plant."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}

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
active_machine_units: dict[tuple[str, str], str] = {}
active_units: dict[str, dict[str, Any]] = {}


def _store_platform_unit_in_progress(plant_id: str, unit_id: str) -> None:
    if plant_id not in plants_registry:
        return
    try:
        conn = get_db_connection()
        with conn:
            conn.execute(
                "INSERT INTO units (plant_id, unit_id, status) VALUES (%s, %s, 'in_progress') ON CONFLICT DO NOTHING;",
                (plant_id, unit_id),
            )
    except Exception:
        log.exception("Failed to store in-progress unit in database for %s", unit_id)
    finally:
        conn.close()


def _store_platform_stage_event(plant_id: str, payload: dict, inner: dict) -> None:
    if plant_id not in plants_registry:
        return
    try:
        conn = get_db_connection()
        unit_id = inner["unit_id"]
        machine_code = (
            inner.get("machine_code")
            or inner.get("machine_id")
            or payload.get("asset_id")
            or "hm_01"
        )
        message_id = payload.get("message_id") or str(uuid.uuid4())
        is_starved = bool(inner.get("is_starved"))
        entered_at = inner.get("entered_at")
        exited_at = inner.get("exited_at")
        outcome = inner.get("outcome") or "ok"
        anomaly_score = float(inner.get("anomaly_score") or 0.0)
        readings_json = json.dumps(
            inner.get("sensor_snapshot") or inner.get("readings") or {}
        )

        with conn:
            conn.execute(
                "INSERT INTO units (plant_id, unit_id, status) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING;",
                (plant_id, unit_id, "in_progress"),
            )
            conn.execute(
                """
                INSERT INTO stage_events (
                    plant_id, unit_id, machine_code, message_id, is_starved,
                    entered_at, exited_at, outcome, anomaly_score, readings
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (plant_id, message_id) DO NOTHING;
                """,
                (
                    plant_id,
                    unit_id,
                    machine_code,
                    message_id,
                    is_starved,
                    entered_at,
                    exited_at,
                    outcome,
                    anomaly_score,
                    readings_json,
                ),
            )
    except Exception:
        log.exception(
            "Failed to store stage_event in database for unit %s",
            inner.get("unit_id"),
        )
    finally:
        conn.close()


def _store_platform_qc_result(
    plant_id: str, machine_code: str, payload: dict, inner: dict
) -> None:
    if plant_id not in plants_registry:
        return
    try:
        conn = get_db_connection()
        unit_id = inner["unit_id"]
        message_id = payload.get("message_id") or str(uuid.uuid4())
        outcome = inner.get("outcome") or "pass"
        status = "passed" if outcome in ("pass", "passed") else "failed"
        probability = float(inner.get("probability") or 1.0)
        defect_type = inner.get("defect_type")
        attributed_stage = inner.get("attributed_stage")
        tested_at = datetime.now(UTC).isoformat()

        with conn:
            conn.execute(
                "INSERT INTO units (plant_id, unit_id, status) VALUES (%s, %s, %s) "
                "ON CONFLICT (plant_id, unit_id) DO UPDATE SET status = excluded.status, updated_at = CURRENT_TIMESTAMP;",
                (plant_id, unit_id, status),
            )
            conn.execute(
                """
                INSERT INTO qc_results (
                    plant_id, unit_id, machine_code, message_id, tested_at,
                    outcome, probability, defect_type, attributed_stage
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (plant_id, message_id) DO NOTHING;
                """,
                (
                    plant_id,
                    unit_id,
                    machine_code,
                    message_id,
                    tested_at,
                    outcome,
                    probability,
                    defect_type,
                    attributed_stage,
                ),
            )
    except Exception:
        log.exception(
            "Failed to store qc_result in database for unit %s", inner.get("unit_id")
        )
    finally:
        conn.close()


@topic_router.on("telemetry")
async def handle_plant_telemetry(
    payload: dict, plant_id: str, machine_code: str
) -> None:
    inner = (
        payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    )
    if isinstance(inner, dict):
        curr_unit_id = (
            inner.get("current_unit_id")
            or inner.get("current_unit")
            or payload.get("current_unit_id")
            or payload.get("current_unit")
        )
        if curr_unit_id:
            old_unit_id = active_machine_units.get((plant_id, machine_code))
            if old_unit_id and old_unit_id != curr_unit_id:
                active_units.pop(old_unit_id, None)
            active_machine_units[(plant_id, machine_code)] = curr_unit_id
            active_units[curr_unit_id] = {
                "plant_id": plant_id,
                "machine_code": machine_code,
                "seen_at": datetime.now(UTC).isoformat(),
            }
            await asyncio.to_thread(
                _store_platform_unit_in_progress, plant_id, curr_unit_id
            )
        else:
            old_unit_id = active_machine_units.pop((plant_id, machine_code), None)
            if old_unit_id:
                active_units.pop(old_unit_id, None)

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
    inner = (
        payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    )
    if isinstance(inner, dict) and "unit_id" in inner:
        await asyncio.to_thread(_store_platform_stage_event, plant_id, payload, inner)

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
    inner = (
        payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    )
    if isinstance(inner, dict) and "unit_id" in inner:
        machine_code = (
            inner.get("machine_code")
            or inner.get("machine_id")
            or payload.get("asset_id")
            or "qc_01"
        )
        if machine_code and machine_code.lower() == "qc":
            machine_code = "qc_01"
        await asyncio.to_thread(
            _store_platform_qc_result, plant_id, machine_code, payload, inner
        )

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

    has_ws_viewers = any(len(clients) > 0 for clients in mgr._rooms.values())
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
                log.info(
                    "Subscribed to plants/# on %s:%d",
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
                finally:
                    active_mqtt_client = None

        except (aiomqtt.MqttError, OSError) as exc:
            active_mqtt_client = None
            log.error("MQTT error: %s. Reconnecting in %ds...", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_S)


def init_platform_db(database_url: str | None = None) -> None:
    """Ensure platform database schema exists via Alembic migrations and pre-create partitions."""
    from alembic import command
    from alembic.config import Config

    if isinstance(database_url, str) and database_url.startswith(
        ("postgresql://", "postgres://")
    ):
        url = database_url
    else:
        url = get_database_url()

    repo_root = Path(__file__).resolve().parent
    ini_path = repo_root / "alembic.ini"
    unpooled = os.getenv("DATABASE_URL_UNPOOLED")
    alembic_url = unpooled if unpooled else url
    if alembic_url.startswith("postgresql://") and not alembic_url.startswith(
        "postgresql+psycopg://"
    ):
        alembic_url = alembic_url.replace("postgresql://", "postgresql+psycopg://", 1)

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(repo_root / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", alembic_url)
    command.upgrade(alembic_cfg, "head")

    if database_url is not None:
        with get_db_connection(url) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM plants;")
                cur.execute("DELETE FROM telemetry_values;")
            conn.commit()

    ensure_partitions()


def seed_plants_if_empty(conn: Any, plants_dir: Path) -> bool:
    """Seed plants from plants_dir into database only if plants table is empty.

    Returns True if seeded, False if skipped. Never writes back to plants_dir.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM plants;")
    row = cursor.fetchone()
    count = row["cnt"] if isinstance(row, dict) else row[0]
    if count == 0 and plants_dir.exists():
        loaded = load_plants(plants_dir)
        sync_plant_definitions(conn, loaded)
        return True
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ingest_engine
    init_platform_db()

    conn = get_db_connection()
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

    ingest_engine = IngestEngine(plants=plants_registry)
    await ingest_engine.start()

    task = asyncio.create_task(mqtt_listener(), name="mqtt-listener")
    heartbeat_task = asyncio.create_task(heartbeat_emitter(), name="heartbeat-emitter")

    async def partition_maintenance_worker():
        while True:
            try:
                await asyncio.sleep(86400)
                await asyncio.to_thread(ensure_partitions)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Daily partition maintenance failed")

    part_task = asyncio.create_task(
        partition_maintenance_worker(), name="partition-worker"
    )

    retention_worker: RetentionWorker | None = None
    if is_retention_worker_enabled():
        retention_worker = RetentionWorker(
            retention_days=get_retention_days(),
            interval_seconds=get_retention_interval_seconds(),
        )
        retention_worker.start()

    try:
        yield
    finally:
        if retention_worker:
            await retention_worker.stop()
        part_task.cancel()
        heartbeat_task.cancel()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await part_task
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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

MAX_ADMIN_BODY_BYTES = 1_048_576  # 1 MB


class AdminPayloadTooLarge(BaseException):
    pass


class AdminBodyLimitMiddleware:
    """Pure ASGI middleware enforcing a strict 1 MB body limit on POST/PUT requests under /api/admin.

    Wraps the ASGI receive() callable and counts bytes as they arrive. If the bytes read exceed 1 MB,
    it returns 413 Payload Too Large immediately without buffering the rest of the payload, without
    touching request._body, and without executing the route handler or validation.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            method = scope.get("method", "").upper()
            if method in ("POST", "PUT") and path.startswith(("/api/admin", "/api/me")):
                bytes_read = 0

                async def limited_receive() -> Message:
                    nonlocal bytes_read
                    message = await receive()
                    if message["type"] == "http.request":
                        body = message.get("body", b"")
                        bytes_read += len(body)
                        if bytes_read > MAX_ADMIN_BODY_BYTES:
                            raise AdminPayloadTooLarge()
                    return message

                try:
                    await self.app(scope, limited_receive, send)
                except AdminPayloadTooLarge:
                    await self._send_413(send)
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_413(send: Send) -> None:
        payload = b'{"detail":"Payload Too Large: request body exceeds 1 MB limit"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"connection", b"close"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": payload,
                "more_body": False,
            }
        )


app.add_middleware(AdminBodyLimitMiddleware)


@app.middleware("http")
async def track_viewer_activity(request: Request, call_next):
    if (
        request.url.path.startswith("/api/")
        and not request.url.path.startswith("/api/admin")
        and not request.url.path.startswith("/api/me")
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

    conn = get_db_connection()
    try:
        try:
            machines_rows = conn.execute(
                """
                SELECT m.machine_code, m.area_code, m.name, m.machine_type, m.display_order,
                       s.state, s.sub_state, s.last_seen_at
                FROM machines m
                LEFT JOIN machine_states s
                  ON m.plant_id = s.plant_id AND m.machine_code = s.machine_code
                WHERE m.plant_id = %s
                ORDER BY m.display_order
                """,
                (plant_id,),
            ).fetchall()
        except Exception:  # noqa: BLE001
            return []

        telemetry_rows = conn.execute(
            """
            WITH ranked_telemetry AS (
                SELECT machine_code, signal_code, device_timestamp, value_num, value_text,
                       ROW_NUMBER() OVER (
                           PARTITION BY machine_code, signal_code
                           ORDER BY device_timestamp DESC, received_at DESC
                       ) as rn
                FROM telemetry_values
                WHERE plant_id = %s
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

        # Fetch latest in-progress units for machines if any
        latest_unit_rows = conn.execute(
            """
            WITH ranked_stages AS (
                SELECT se.machine_code, se.unit_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY se.machine_code
                           ORDER BY se.entered_at DESC
                       ) as rn
                FROM stage_events se
                JOIN units u ON se.plant_id = u.plant_id AND se.unit_id = u.unit_id
                WHERE se.plant_id = %s AND u.status = 'in_progress'
            )
            SELECT machine_code, unit_id
            FROM ranked_stages
            WHERE rn = 1
            """,
            (plant_id,),
        ).fetchall()
        db_unit_by_machine = {
            r["machine_code"]: r["unit_id"] for r in latest_unit_rows
        }

        result = []
        for mr in machines_rows:
            m_code = mr["machine_code"]
            curr_unit = active_machine_units.get(
                (plant_id, m_code)
            ) or db_unit_by_machine.get(m_code)
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
                    "current_unit_id": curr_unit,
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

    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                to_char(date_bin(MAKE_INTERVAL(secs => %s), device_timestamp, '1970-01-01 00:00:00+00'::timestamptz) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS timestamp,
                ROUND(AVG(value_num)::numeric, 2)::float AS avg,
                ROUND(MIN(value_num)::numeric, 2)::float AS min,
                ROUND(MAX(value_num)::numeric, 2)::float AS max,
                COUNT(value_num) AS count
            FROM telemetry_values
            WHERE plant_id = %s
              AND machine_code = %s
              AND signal_code = %s
              AND value_num IS NOT NULL
              AND device_timestamp >= %s
              AND device_timestamp <= %s
            GROUP BY 1
            ORDER BY 1 ASC
            """,
            (
                bucket_sec,
                plant_id,
                machine_code,
                signal_code,
                start_iso,
                end_iso,
            ),
        )
        rows = cur.fetchall()

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


@app.get(
    "/api/plants/{plant_id}/units",
    dependencies=[Depends(verify_plant_viewer)],
)
def get_plant_recent_units(plant_id: str, limit: int = 20) -> list[dict]:
    """Most recently created units for a plant, newest first — feeds the unit-lookup
    page's 'recent units' list."""
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")
    limit = max(1, min(limit, 100))
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT unit_id, status, created_at FROM units WHERE plant_id = %s ORDER BY created_at DESC LIMIT %s;",
            (plant_id, limit),
        )
        p_rows = cur.fetchall()
        if p_rows:
            return [
                {
                    "unit_id": r["unit_id"],
                    "status": r["status"],
                    "created_at": (
                        r["created_at"].isoformat()
                        if hasattr(r["created_at"], "isoformat")
                        else str(r["created_at"])
                    ),
                }
                for r in p_rows
            ]
    except Exception:
        log.exception(
            "Failed to query recent units from database for plant %s", plant_id
        )
    finally:
        conn.close()

    return []


@app.get(
    "/api/plants/{plant_id}/units/{unit_id}",
    dependencies=[Depends(verify_plant_viewer)],
)
def get_plant_unit_history(plant_id: str, unit_id: str) -> dict:
    """Full traceable journey for one unit within a plant — every stage it passed
    through, plus its QC verdict if tested. This is the payoff of the
    whole traceability design: a real answer to 'why did this fail?'"""
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT unit_id, status, created_at FROM units WHERE plant_id = %s AND unit_id = %s LIMIT 1;",
            (plant_id, unit_id),
        )
        p_unit = cur.fetchone()
        if p_unit:
            cur.execute(
                """
                SELECT s.machine_code, s.outcome, s.anomaly_score, s.readings,
                       s.entered_at, s.exited_at, coalesce(m.area_code, 'housing') as sub_facility
                FROM stage_events s
                LEFT JOIN machines m ON s.plant_id = m.plant_id AND s.machine_code = m.machine_code
                WHERE s.plant_id = %s AND s.unit_id = %s
                ORDER BY s.entered_at;
                """,
                (plant_id, unit_id),
            )
            p_stages = cur.fetchall()
            cur.execute(
                """
                SELECT outcome, probability, defect_type, attributed_stage, tested_at
                FROM qc_results WHERE plant_id = %s AND unit_id = %s LIMIT 1;
                """,
                (plant_id, unit_id),
            )
            p_qc = cur.fetchone()
            return {
                "unit_id": p_unit["unit_id"],
                "status": p_unit["status"],
                "created_at": (
                    p_unit["created_at"].isoformat()
                    if hasattr(p_unit["created_at"], "isoformat")
                    else str(p_unit["created_at"])
                ),
                "stages": [
                    {
                        "sub_facility": (
                            s["sub_facility"]
                            or {
                                "hm": "housing",
                                "cs": "casting",
                                "am": "assembly",
                                "qc": "qc",
                            }.get(s["machine_code"].split("_")[0], "housing")
                        ),
                        "machine_id": s["machine_code"],
                        "outcome": s["outcome"],
                        "anomaly_score": s["anomaly_score"],
                        "readings": (
                            json.loads(s["readings"])
                            if isinstance(s["readings"], str)
                            else (s["readings"] or {})
                        ),
                        "entered_at": (
                            s["entered_at"].isoformat()
                            if hasattr(s["entered_at"], "isoformat")
                            else s["entered_at"]
                        ),
                        "exited_at": (
                            s["exited_at"].isoformat()
                            if hasattr(s["exited_at"], "isoformat")
                            else s["exited_at"]
                        ),
                    }
                    for s in p_stages
                ],
                "qc_result": None
                if not p_qc
                else {
                    "outcome": p_qc["outcome"],
                    "probability": p_qc["probability"],
                    "defect_type": p_qc["defect_type"],
                    "attributed_stage": p_qc["attributed_stage"],
                    "tested_at": (
                        p_qc["tested_at"].isoformat()
                        if hasattr(p_qc["tested_at"], "isoformat")
                        else p_qc["tested_at"]
                    ),
                },
            }
    except Exception:
        log.exception(
            "Failed to query unit history from database for plant %s unit %s",
            plant_id,
            unit_id,
        )
    finally:
        conn.close()

    # If the unit is currently active on the manufacturing floor
    # but has not yet completed its first stage event:
    active_info = active_units.get(unit_id)
    if active_info and active_info.get("plant_id") == plant_id:
        return {
            "unit_id": unit_id,
            "status": "in_progress",
            "created_at": active_info.get("seen_at", datetime.now(UTC).isoformat()),
            "stages": [],
            "qc_result": None,
        }

    raise HTTPException(status_code=404, detail="Unit not found")


@app.get(
    "/api/plants/{plant_id}/stats/defect-rate-by-hour",
    dependencies=[Depends(verify_plant_viewer)],
)
def plant_defect_rate_by_hour(plant_id: str) -> list[dict]:
    """Defect rate grouped by hour-of-day for a plant."""
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")

    buckets: dict[str, dict[str, int]] = {}
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT to_char(tested_at, 'HH24') as hour, outcome FROM qc_results WHERE plant_id = %s;",
            (plant_id,),
        )
        p_rows = cur.fetchall()
        for row in p_rows:
            hour = row["hour"] or "00"
            outcome = row["outcome"]
            b = buckets.setdefault(hour, {"total": 0, "failed": 0})
            b["total"] += 1
            if outcome in ("fail", "failed"):
                b["failed"] += 1
    except Exception:
        log.exception(
            "Failed to query defect-rate-by-hour from database for plant %s",
            plant_id,
        )
    finally:
        conn.close()

    return [
        {
            "hour": hour,
            "total_tested": b["total"],
            "failed": b["failed"],
            "defect_rate": (round(b["failed"] / b["total"], 3) if b["total"] else 0),
        }
        for hour, b in sorted(buckets.items())
    ]


@app.get(
    "/api/plants/{plant_id}/stats/defect-rate-by-stage",
    dependencies=[Depends(verify_plant_viewer)],
)
def plant_defect_rate_by_stage(plant_id: str) -> list[dict]:
    """Of all failures for a plant, which stage gets attributed most often."""
    plant = plants_registry.get(plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{plant_id}' not found")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT attributed_stage, count(*) as cnt FROM qc_results WHERE plant_id = %s AND outcome IN ('fail', 'failed') AND attributed_stage IS NOT NULL GROUP BY attributed_stage;",
            (plant_id,),
        )
        p_rows = cur.fetchall()
        if p_rows:
            return [
                {"stage": row["attributed_stage"], "failures": row["cnt"]}
                for row in p_rows
            ]
    except Exception:
        log.exception(
            "Failed to query defect-rate-by-stage from database for plant %s",
            plant_id,
        )
    finally:
        conn.close()

    return []


admin_router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_token)],
)


@admin_router.get("/health")
def admin_health(
    current_user: Annotated[AdminUser, Depends(verify_admin_user)],
) -> dict:
    return {"status": "ok"}


@admin_router.get("/plants", response_model=list[AdminPlantSummary])
def admin_list_plants(
    current_user: Annotated[AdminUser, Depends(verify_admin_user)],
) -> list[AdminPlantSummary]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, timezone, viewer_token_hash FROM plants ORDER BY id;"
        )
        rows = cur.fetchall()
        if current_user.role == "plant_manager":
            rows = [row for row in rows if row["id"] == current_user.plant_id]
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
    conn: Any,
    plant_id: str,
    machine_code: str | None = None,
    signal_code: str | None = None,
    batch_size: int = 5000,
) -> int:
    """Delete telemetry_values for a plant/machine/signal in batches to avoid write lock starvation."""
    total_deleted = 0
    cur = conn.cursor()

    where_clauses = ["plant_id = %s"]
    params: list[Any] = [plant_id]
    if machine_code is not None:
        where_clauses.append("machine_code = %s")
        params.append(machine_code)
    if signal_code is not None:
        where_clauses.append("signal_code = %s")
        params.append(signal_code)

    where_sql = " AND ".join(where_clauses)
    delete_sql = f"""
    DELETE FROM telemetry_values
    WHERE (device_timestamp, plant_id, message_id, signal_code) IN (
        SELECT device_timestamp, plant_id, message_id, signal_code FROM telemetry_values
        WHERE {where_sql}
        LIMIT %s
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
    conn: Any,
    plant: PlantDefinition,
    touch_credentials: bool = True,
) -> list[AdminDeviceCredential]:
    """Upsert plant, areas, machines, signals, and optionally credentials into database."""
    cursor = conn.cursor()
    if plant.viewer_token:
        viewer_token_hash = hashlib.sha256(
            plant.viewer_token.encode("utf-8")
        ).hexdigest()
    elif plant.viewer_token_hash:
        viewer_token_hash = plant.viewer_token_hash
    else:
        cursor.execute(
            "SELECT viewer_token_hash FROM plants WHERE id = %s;", (plant.plant_id,)
        )
        row = cursor.fetchone()
        viewer_token_hash = row["viewer_token_hash"] if row else None

    cursor.execute(
        """
        INSERT INTO plants (id, name, timezone, viewer_token_hash)
        VALUES (%s, %s, %s, %s)
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
                    VALUES (%s, %s, %s, %s, true)
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
                VALUES (%s, %s, %s, %s, true)
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
            VALUES (%s, %s, %s, %s)
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
                VALUES (%s, %s, %s, %s, %s, %s)
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
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s)
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
                        SET setpoint_signal_code = %s
                        WHERE plant_id = %s AND machine_code = %s AND signal_code = %s
                        """,
                        (
                            sig.setpoint_signal_code,
                            plant.plant_id,
                            machine.machine_code,
                            sig.signal_code,
                        ),
                    )
    return generated_creds


def _fetch_admin_plant_detail(conn: Any, plant_id: str) -> AdminPlantDetail:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, timezone, viewer_token_hash FROM plants WHERE id = %s;",
        (plant_id,),
    )
    p_row = cur.fetchone()
    if not p_row:
        raise HTTPException(
            status_code=404,
            detail=f"Plant '{plant_id}' not found",
        )

    cur.execute(
        "SELECT area_code, name, display_order FROM areas WHERE plant_id = %s ORDER BY display_order, area_code;",
        (plant_id,),
    )
    area_rows = cur.fetchall()
    areas: list[AreaDefinition] = []
    for a_row in area_rows:
        a_code = a_row["area_code"]
        cur.execute(
            "SELECT machine_code, name, machine_type, display_order FROM machines WHERE plant_id = %s AND area_code = %s ORDER BY display_order, machine_code;",
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
                WHERE plant_id = %s AND machine_code = %s
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
        "SELECT username FROM plant_credentials WHERE plant_id = %s ORDER BY username;",
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
def admin_get_plant_detail(
    plant_id: str,
    current_user: Annotated[AdminUser, Depends(verify_admin_user)],
) -> AdminPlantDetail:
    require_plant_access(plant_id, current_user)
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
    plant: PlantDefinition,
    response: Response,
    current_user: Annotated[AdminUser, Depends(require_platform_admin)],
) -> AdminPlantCreatedResponse:
    response.headers["Cache-Control"] = "no-store"
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM plants WHERE id = %s;", (plant.plant_id,))
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
    current_user: Annotated[AdminUser, Depends(verify_admin_user)] = None,
) -> AdminPlantDetail:
    if confirm_removals and current_user.role != "platform_admin":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: confirm_removals requires platform_admin role",
        )
    require_plant_access(plant_id, current_user)
    if plant.plant_id != plant_id:
        raise HTTPException(
            status_code=400,
            detail=f"Plant ID in path '{plant_id}' does not match body '{plant.plant_id}'",
        )

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM plants WHERE id = %s;", (plant_id,))
        if not cur.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Plant '{plant_id}' not found",
            )

        cur.execute("SELECT area_code FROM areas WHERE plant_id = %s;", (plant_id,))
        existing_areas = {r["area_code"] for r in cur.fetchall()}

        cur.execute(
            "SELECT machine_code FROM machines WHERE plant_id = %s;", (plant_id,)
        )
        existing_machines = {r["machine_code"] for r in cur.fetchall()}

        cur.execute(
            "SELECT machine_code, signal_code FROM signals WHERE plant_id = %s;",
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
                    "DELETE FROM signals WHERE plant_id = %s AND machine_code = %s AND signal_code = %s;",
                    (plant_id, m_code, s_code),
                )
            for m_code in removed_machines:
                cur.execute(
                    "DELETE FROM machines WHERE plant_id = %s AND machine_code = %s;",
                    (plant_id, m_code),
                )
            for a_code in removed_areas:
                cur.execute(
                    "DELETE FROM areas WHERE plant_id = %s AND area_code = %s;",
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
                "SELECT viewer_token_hash FROM plants WHERE id = %s;", (plant_id,)
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
    plant_id: str,
    response: Response,
    current_user: Annotated[AdminUser, Depends(require_platform_admin)],
) -> AdminCredentialRotateResponse:
    response.headers["Cache-Control"] = "no-store"
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM plants WHERE id = %s;", (plant_id,))
        if not cur.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Plant '{plant_id}' not found",
            )

        cur.execute(
            "SELECT username, client_id FROM plant_credentials WHERE plant_id = %s ORDER BY username LIMIT 1;",
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
            VALUES (%s, %s, %s, %s, true)
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


async def _purge_plant_data_and_reload(conn: Any, plant_id: str) -> bool:
    cur = conn.cursor()
    plants_registry.pop(plant_id, None)
    if ingest_engine:
        ingest_engine.remove_plant(plant_id)
    plant_queue_depths.pop(plant_id, None)
    ticket_store.revoke_plant(plant_id)

    await manager.close_room(plant_id, code=4404, reason="Plant deleted")

    await asyncio.to_thread(_batched_delete_telemetry, conn, plant_id)

    cur.execute("DELETE FROM plant_credentials WHERE plant_id = %s;", (plant_id,))
    cur.execute("DELETE FROM plants WHERE id = %s;", (plant_id,))
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
    return broker_reloaded


@admin_router.delete("/plants/{plant_id}")
async def admin_delete_plant(
    plant_id: str,
    current_user: Annotated[AdminUser, Depends(require_platform_admin)],
) -> dict:
    if plant_id in SYSTEM_PLANT_IDS:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot delete system plant '{plant_id}'",
        )

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM plants WHERE id = %s;", (plant_id,))
        if not cur.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Plant '{plant_id}' not found",
            )

        broker_reloaded = await _purge_plant_data_and_reload(conn, plant_id)
        return {
            "status": "deleted",
            "plant_id": plant_id,
            "broker_reloaded": broker_reloaded,
        }
    finally:
        conn.close()


MAX_PLANTS_PER_USER: int = 3
MAX_PLANTS_TOTAL: int = 25
RESERVED_PLANT_IDS: frozenset[str] = frozenset(
    {
        "plant_demo_membrane",
        "plant_water_district_9",
        "admin",
        "me",
        "demo",
        "system",
        "test",
    }
)

me_router = APIRouter(prefix="/api/me", tags=["me"])


@me_router.get(
    "/plants",
    response_model=list[MyPlantSummary],
    response_model_exclude_none=True,
)
def me_list_plants(
    response: Response,
    current_user: Annotated[ClerkUser, Depends(verify_clerk_user)],
) -> list[MyPlantSummary]:
    response.headers["Cache-Control"] = "no-store"
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.id as plant_id, p.name, p.timezone,
                   (p.viewer_token_hash IS NOT NULL) as has_viewer_token,
                   pm.role, pm.created_at
            FROM plant_members pm
            JOIN plants p ON p.id = pm.plant_id
            WHERE pm.user_id = %s
            ORDER BY pm.created_at ASC;
            """,
            (current_user.user_id,),
        )
        rows = cur.fetchall()
        return [
            MyPlantSummary(
                plant_id=row["plant_id"],
                name=row["name"],
                timezone=row["timezone"],
                has_viewer_token=bool(row["has_viewer_token"]),
                role=row["role"],
                created_at=(
                    row["created_at"].isoformat()
                    if hasattr(row["created_at"], "isoformat")
                    else (
                        str(row["created_at"])
                        if row["created_at"] is not None
                        else None
                    )
                ),
            )
            for row in rows
        ]
    finally:
        conn.close()


@me_router.post(
    "/plants",
    response_model=AdminPlantCreatedResponse,
    response_model_exclude_none=True,
    status_code=201,
)
async def me_create_plant(
    plant: PlantDefinition,
    response: Response,
    current_user: Annotated[ClerkUser, Depends(verify_clerk_user)],
) -> AdminPlantCreatedResponse:
    response.headers["Cache-Control"] = "no-store"

    # Reserved ID check
    if plant.plant_id.lower() in RESERVED_PLANT_IDS:
        raise HTTPException(
            status_code=409,
            detail=f"Plant ID '{plant.plant_id}' is reserved",
        )

    conn = get_db_connection()
    try:
        cur = conn.cursor()

        # Global cap check (25 total plants)
        cur.execute("SELECT count(*) as cnt FROM plants;")
        total_plants = cur.fetchone()["cnt"]
        if total_plants >= MAX_PLANTS_TOTAL:
            raise HTTPException(
                status_code=409,
                detail=f"Global plant capacity reached ({MAX_PLANTS_TOTAL})",
            )

        # Per-user quota check (3 plants per user)
        cur.execute(
            "SELECT count(*) as cnt FROM plant_members WHERE user_id = %s;",
            (current_user.user_id,),
        )
        user_plants = cur.fetchone()["cnt"]
        if user_plants >= MAX_PLANTS_PER_USER:
            raise HTTPException(
                status_code=409,
                detail=f"User plant limit reached ({MAX_PLANTS_PER_USER})",
            )

        # Collision check
        cur.execute("SELECT 1 FROM plants WHERE id = %s;", (plant.plant_id,))
        if cur.fetchone():
            raise HTTPException(
                status_code=409,
                detail=f"Plant '{plant.plant_id}' already exists",
            )

        # New plants are private: generate viewer token and return once
        generated_viewer_token = secrets.token_urlsafe(32)
        plant.viewer_token = generated_viewer_token
        plant.viewer_token_hash = hashlib.sha256(
            generated_viewer_token.encode("utf-8")
        ).hexdigest()

        # Sync plant topology and device credentials into DB
        generated_creds = _sync_single_plant(conn, plant, touch_credentials=True)

        # Record ownership in plant_members
        cur.execute(
            """
            INSERT INTO plant_members (user_id, plant_id, role)
            VALUES (%s, %s, 'owner')
            ON CONFLICT (plant_id, user_id) DO NOTHING;
            """,
            (current_user.user_id, plant.plant_id),
        )
        conn.commit()

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
            one_time_viewer_token=generated_viewer_token,
            viewer_token=generated_viewer_token,
        )
    finally:
        conn.close()


def _require_plant_ownership(plant_id: str, current_user: ClerkUser) -> None:
    """Verifies that current_user is either platform_admin or an owner of plant_id in plant_members.
    Raises 404 if the plant does not exist or user is not authorized.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM plants WHERE id = %s;", (plant_id,))
        if not cur.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Plant '{plant_id}' not found",
            )
        if current_user.role == "platform_admin":
            return
        cur.execute(
            "SELECT 1 FROM plant_members WHERE plant_id = %s AND user_id = %s AND role = 'owner';",
            (plant_id, current_user.user_id),
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Plant '{plant_id}' not found",
            )
    finally:
        conn.close()


@me_router.get(
    "/plants/{plant_id}",
    response_model=AdminPlantDetail,
    response_model_exclude_none=True,
)
def me_get_plant_detail(
    plant_id: str,
    response: Response,
    current_user: Annotated[ClerkUser, Depends(verify_clerk_user)],
) -> AdminPlantDetail:
    response.headers["Cache-Control"] = "no-store"
    _require_plant_ownership(plant_id, current_user)
    conn = get_db_connection()
    try:
        return _fetch_admin_plant_detail(conn, plant_id)
    finally:
        conn.close()


@me_router.delete("/plants/{plant_id}")
async def me_delete_plant(
    plant_id: str,
    response: Response,
    current_user: Annotated[ClerkUser, Depends(verify_clerk_user)],
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    # Demo and system plants can never be deleted here
    if plant_id in RESERVED_PLANT_IDS or plant_id in SYSTEM_PLANT_IDS:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot delete system or demo plant '{plant_id}'",
        )
    _require_plant_ownership(plant_id, current_user)

    conn = get_db_connection()
    try:
        broker_reloaded = await _purge_plant_data_and_reload(conn, plant_id)
        return {
            "status": "deleted",
            "plant_id": plant_id,
            "broker_reloaded": broker_reloaded,
        }
    finally:
        conn.close()


@me_router.post(
    "/plants/{plant_id}/credentials/rotate",
    response_model=AdminCredentialRotateResponse,
    response_model_exclude_none=True,
)
async def me_rotate_plant_credentials(
    plant_id: str,
    response: Response,
    current_user: Annotated[ClerkUser, Depends(verify_clerk_user)],
) -> AdminCredentialRotateResponse:
    response.headers["Cache-Control"] = "no-store"
    _require_plant_ownership(plant_id, current_user)

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT username, client_id FROM plant_credentials WHERE plant_id = %s ORDER BY username LIMIT 1;",
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
            VALUES (%s, %s, %s, %s, true)
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


@me_router.post(
    "/plants/{plant_id}/viewer-token/rotate",
    response_model=ViewerTokenRotateResponse,
    response_model_exclude_none=True,
)
async def me_rotate_viewer_token(
    plant_id: str,
    response: Response,
    current_user: Annotated[ClerkUser, Depends(verify_clerk_user)],
) -> ViewerTokenRotateResponse:
    response.headers["Cache-Control"] = "no-store"
    _require_plant_ownership(plant_id, current_user)

    new_viewer_token = secrets.token_urlsafe(32)
    new_viewer_hash = hashlib.sha256(new_viewer_token.encode("utf-8")).hexdigest()

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE plants SET viewer_token_hash = %s WHERE id = %s;",
            (new_viewer_hash, plant_id),
        )
        conn.commit()

        if plant_id in plants_registry:
            plants_registry[plant_id].viewer_token = new_viewer_token
            plants_registry[plant_id].viewer_token_hash = new_viewer_hash

        ticket_store.revoke_plant(plant_id)
        await manager.close_room(plant_id, code=4401, reason="Viewer token rotated")

        return ViewerTokenRotateResponse(
            plant_id=plant_id,
            viewer_token=new_viewer_token,
        )
    finally:
        conn.close()


app.include_router(me_router)


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
