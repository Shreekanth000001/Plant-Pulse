import asyncio
import hashlib
import logging
import sqlite3
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from plant_definitions import PlantDefinition
from scripts.generate_mosquitto_auth import hash_password_pbkdf2

logger = logging.getLogger("ingest-engine")

KNOWN_STATUSES = frozenset(
    {"RUNNING", "IDLE", "STANDBY", "FAULT", "OFFLINE", "TESTING"}
)


def extract_machine_state_record(
    plant_id: str,
    machine_code: str,
    status: Any,
    sub_status: Any,
    device_ts_iso: str,
    now_iso: str,
) -> tuple[str, str, str, str | None, str, str] | None:
    """Shared function to extract and validate machine state tuple from telemetry or state payloads.

    Unknown status values are stored, logged as a warning, and never fail the batch.
    """
    if status is None or status == "":
        return None

    status_str = str(status).strip()
    if status_str.upper() not in KNOWN_STATUSES:
        logger.warning(
            "Unknown status '%s' for plant '%s', machine '%s'",
            status_str,
            plant_id,
            machine_code,
        )

    sub_status_str = str(sub_status).strip() if sub_status is not None else None
    return (
        plant_id,
        machine_code,
        status_str,
        sub_status_str,
        device_ts_iso,
        now_iso,
    )


def sync_plant_definitions(
    conn: sqlite3.Connection,
    plants: dict[str, PlantDefinition],
) -> None:
    """Upsert plant, area, machine, and signal records into the database."""
    cursor = conn.cursor()
    for plant in plants.values():
        viewer_token_hash = (
            hashlib.sha256(plant.viewer_token.encode("utf-8")).hexdigest()
            if plant.viewer_token
            else None
        )
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

                # First pass: insert all signals with setpoint_signal_code = None
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

                # Second pass: update setpoint_signal_code references
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
    conn.commit()


class IngestEngine:
    """Buffered batch ingestion engine for PlantPulse telemetry values.

    Implements:
    - In-memory bounded queue (asyncio.Queue) with drop counter.
    - Off-event-loop batch writes via asyncio.to_thread with SQLite WAL & synchronous=NORMAL.
    - Late-data window validation (MAX_LATE_SECONDS) and future-timestamp rejection (> 300s).
    - Database UNIQUE constraint deduplication with INSERT OR IGNORE.
    - Graceful shutdown draining all buffered queue records.
    """

    def __init__(
        self,
        db_path: Path | str,
        plants: dict[str, PlantDefinition] | None = None,
        max_queue_size: int = 10000,
        flush_interval_seconds: float = 0.5,
        batch_size: int = 100,
        max_late_seconds: int = 21600,
    ) -> None:
        db_str = str(db_path)
        if db_str.startswith("sqlite:///"):
            db_str = db_str.removeprefix("sqlite:///")

        self._db_file = db_str
        self._plants = plants or {}
        self._max_queue_size = max_queue_size
        self._flush_interval = flush_interval_seconds
        self._batch_size = batch_size
        self._max_late_seconds = max_late_seconds

        self._queue: asyncio.Queue[tuple[list[tuple], tuple | None]] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._dropped_total = 0
        self._last_drop_log_time = 0.0

        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._stopping = False
        self._lock = threading.Lock()

        # Open SQLite connection
        self._conn = sqlite3.connect(self._db_file, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._conn.execute("PRAGMA foreign_keys=ON;")

    @property
    def dropped_total(self) -> int:
        """Total number of messages dropped due to queue saturation."""
        return self._dropped_total

    def update_plant(self, plant: PlantDefinition) -> None:
        """Update or register a plant definition in the in-memory plant set."""
        self._plants[plant.plant_id] = plant

    def remove_plant(self, plant_id: str) -> None:
        """Remove a plant definition from the in-memory plant set."""
        self._plants.pop(plant_id, None)

    async def start(self) -> None:
        """Start the background ingestion batch worker."""
        if self._running:
            return
        self._running = True
        self._stopping = False
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Gracefully stop accepting new messages, drain the queue, and commit."""
        self._stopping = True
        self._running = False

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        # Drain and flush all remaining items in queue
        await self.flush()

        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def _validate_envelope(
        self,
        topic: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> tuple[bool, str, list[tuple]]:
        """Validate envelope against Section 4.2 / 4.4 rules and extract narrow rows."""
        # 1. Schema version
        if payload.get("schema_version") != "1.0":
            return False, "INVALID_SCHEMA_VERSION", []

        # 2. Topic extraction
        parts = topic.split("/")
        if (
            len(parts) != 5
            or parts[0] != "plants"
            or parts[2] != "assets"
            or parts[4] not in ("telemetry", "state")
        ):
            return False, "INVALID_TOPIC_SHAPE", []

        topic_plant_id = parts[1]
        topic_machine_code = parts[3]
        topic_kind = parts[4]

        plant_id = payload.get("plant_id")
        asset_id = payload.get("asset_id")

        # 3. Tenant mismatch
        if plant_id != topic_plant_id:
            return False, "TENANT_MISMATCH", []

        if asset_id != topic_machine_code:
            return False, "UNKNOWN_ASSET", []

        # 4. Unknown asset or plant check if registry loaded
        valid_signal_codes: set[str] | None = None
        if self._plants:
            plant_def = self._plants.get(plant_id)
            if not plant_def:
                return False, "UNKNOWN_PLANT", []

            machine_found = False
            for area in plant_def.areas:
                for machine in area.machines:
                    if machine.machine_code == asset_id:
                        machine_found = True
                        valid_signal_codes = {s.signal_code for s in machine.signals}
                        break
                if machine_found:
                    break

            if not machine_found:
                return False, "UNKNOWN_ASSET", []

        # 5. Timestamp validation
        device_ts_raw = payload.get("device_timestamp")
        if not device_ts_raw:
            return False, "MISSING_TIMESTAMP", []

        try:
            device_ts = datetime.fromisoformat(str(device_ts_raw))
        except (ValueError, TypeError):
            return False, "INVALID_TIMESTAMP_FORMAT", []

        if device_ts.tzinfo is None:
            device_ts = device_ts.replace(tzinfo=UTC)
        else:
            device_ts = device_ts.astimezone(UTC)

        # Future data rejection: device_ts > now + 300s
        if device_ts > now + timedelta(seconds=300):
            return False, "FUTURE_TIMESTAMP_REJECTED", []

        # Late data rejection: device_ts < now - MAX_LATE_SECONDS
        if device_ts < now - timedelta(seconds=self._max_late_seconds):
            return False, "LATE_TIMESTAMP_REJECTED", []

        # 6. Message ID validation
        message_id = payload.get("message_id")
        if not message_id:
            return False, "MISSING_MESSAGE_ID", []

        payload_body = payload.get("payload") or {}
        device_ts_iso = device_ts.isoformat()
        received_at_iso = now.isoformat()

        metric_rows: list[tuple] = []
        if topic_kind == "telemetry":
            metrics = payload_body.get("metrics") or {}
            for sig_code, val in metrics.items():
                if (
                    valid_signal_codes is not None
                    and sig_code not in valid_signal_codes
                ):
                    continue

                value_num: float | None = None
                value_text: str | None = None

                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    value_num = float(val)
                elif isinstance(val, bool):
                    value_num = 1.0 if val else 0.0
                else:
                    value_text = str(val)

                metric_rows.append(
                    (
                        plant_id,
                        asset_id,
                        sig_code,
                        device_ts_iso,
                        received_at_iso,
                        message_id,
                        value_num,
                        value_text,
                    )
                )

        return True, "OK", metric_rows

    async def enqueue(self, topic: str, payload: dict[str, Any]) -> bool:
        """Validate envelope and enqueue rows for batch commit."""
        if self._stopping:
            return False

        now = datetime.now(UTC)
        is_valid, reason, metric_rows = self._validate_envelope(topic, payload, now)
        if not is_valid:
            logger.warning("Ingest rejected message on topic %s: %s", topic, reason)
            return False

        payload_body = payload.get("payload") or {}
        raw_status = payload_body.get("status")
        raw_sub_status = payload_body.get("sub_status")

        device_ts_raw = payload.get("device_timestamp")
        device_ts = datetime.fromisoformat(str(device_ts_raw))
        if device_ts.tzinfo is None:
            device_ts = device_ts.replace(tzinfo=UTC)
        else:
            device_ts = device_ts.astimezone(UTC)

        state_row = extract_machine_state_record(
            plant_id=payload.get("plant_id", ""),
            machine_code=payload.get("asset_id", ""),
            status=raw_status,
            sub_status=raw_sub_status,
            device_ts_iso=device_ts.isoformat(),
            now_iso=now.isoformat(),
        )

        if not metric_rows and state_row is None:
            logger.warning(
                "Ingest discarded message on topic %s: no metrics and no state",
                topic,
            )
            return False

        if self._queue.full():
            self._dropped_total += 1
            now_sec = time.monotonic()
            if now_sec - self._last_drop_log_time >= 5.0:
                logger.warning(
                    "Ingest queue full (maxsize=%d). Dropped %d messages so far.",
                    self._max_queue_size,
                    self._dropped_total,
                )
                self._last_drop_log_time = now_sec
            return False

        self._queue.put_nowait((metric_rows, state_row))
        return True

    async def handle_telemetry(
        self,
        payload: dict[str, Any],
        plant_id: str,
        machine_code: str,
    ) -> bool:
        """Handler signature compatible with TopicRouter."""
        topic = f"plants/{plant_id}/assets/{machine_code}/telemetry"
        return await self.enqueue(topic, payload)

    async def handle_state(
        self,
        payload: dict[str, Any],
        plant_id: str,
        machine_code: str,
    ) -> bool:
        """Handler signature compatible with TopicRouter."""
        topic = f"plants/{plant_id}/assets/{machine_code}/state"
        return await self.enqueue(topic, payload)

    def _commit_batch_sync(
        self,
        metric_rows: Sequence[tuple],
        state_rows: Sequence[tuple],
    ) -> int:
        """Synchronously commit batch of narrow rows and machine states in the same transaction."""
        if not metric_rows and not state_rows:
            return 0
        with self._lock:
            if not self._conn:
                return 0
            cursor = self._conn.cursor()
            if metric_rows:
                sql = """
                INSERT OR IGNORE INTO telemetry_values (
                    plant_id, machine_code, signal_code,
                    device_timestamp, received_at, message_id,
                    value_num, value_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """
                try:
                    cursor.executemany(sql, metric_rows)
                except sqlite3.IntegrityError as exc:
                    if "FOREIGN KEY" in str(exc):
                        for row in metric_rows:
                            try:
                                cursor.execute(sql, row)
                            except sqlite3.IntegrityError:
                                pass
                    else:
                        raise

            if state_rows:
                state_sql = """
                INSERT INTO machine_states (
                    plant_id, machine_code, state,
                    sub_state, last_seen_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (plant_id, machine_code) DO UPDATE SET
                    state = excluded.state,
                    sub_state = excluded.sub_state,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                WHERE excluded.last_seen_at > machine_states.last_seen_at;
                """
                try:
                    cursor.executemany(state_sql, state_rows)
                except sqlite3.IntegrityError as exc:
                    if "FOREIGN KEY" in str(exc):
                        for s_row in state_rows:
                            try:
                                cursor.execute(state_sql, s_row)
                            except sqlite3.IntegrityError:
                                pass
                    else:
                        raise

            self._conn.commit()
            return len(metric_rows) + len(state_rows)

    async def flush(self) -> int:
        """Flush and commit all queued items immediately off the event loop."""
        items: list[tuple[list[tuple], tuple | None]] = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                items.append(item)
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        if not items:
            return 0

        metric_rows: list[tuple] = []
        state_rows: list[tuple] = []
        for m_rows, s_row in items:
            if m_rows:
                metric_rows.extend(m_rows)
            if s_row is not None:
                state_rows.append(s_row)

        return await asyncio.to_thread(self._commit_batch_sync, metric_rows, state_rows)

    async def _worker_loop(self) -> None:
        """Background worker aggregating batches on batch_size or flush_interval."""
        while self._running:
            batch_metric_rows: list[tuple] = []
            batch_state_rows: list[tuple] = []
            deadline = asyncio.get_running_loop().time() + self._flush_interval

            while (
                len(batch_metric_rows) < self._batch_size
                and len(batch_state_rows) < self._batch_size
            ):
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break

                try:
                    m_rows, s_row = await asyncio.wait_for(
                        self._queue.get(), timeout=timeout
                    )
                    if m_rows:
                        batch_metric_rows.extend(m_rows)
                    if s_row is not None:
                        batch_state_rows.append(s_row)
                    self._queue.task_done()
                except TimeoutError:
                    break
                except asyncio.CancelledError:
                    if batch_metric_rows or batch_state_rows:
                        await asyncio.to_thread(
                            self._commit_batch_sync,
                            batch_metric_rows,
                            batch_state_rows,
                        )
                    raise

            if batch_metric_rows or batch_state_rows:
                await asyncio.to_thread(
                    self._commit_batch_sync,
                    batch_metric_rows,
                    batch_state_rows,
                )
