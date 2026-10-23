import os
import threading
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()
_partition_lock = threading.Lock()
_known_partitions: set[str] = set()


class PooledConnectionWrapper:
    """Wrapper around a pooled psycopg connection.

    Supports both context-manager syntax (`with get_db_connection() as conn:`)
    and explicit checkout/close (`conn = get_db_connection() ... conn.close()`).
    """

    def __init__(self, pool: ConnectionPool, conn: Any) -> None:
        self._pool = pool
        self._conn = conn
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def close(self) -> None:
        if not self._closed and self._pool is not None:
            self._closed = True
            try:
                from psycopg.pq import TransactionStatus

                if (
                    hasattr(self._conn, "info")
                    and self._conn.info.transaction_status != TransactionStatus.IDLE
                ):
                    self._conn.rollback()
            except Exception:  # noqa: BLE001, S110
                pass
            try:
                self._pool.putconn(self._conn)
            except Exception:  # noqa: BLE001, S110
                pass

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            try:
                self._conn.rollback()
            except Exception:  # noqa: BLE001, S110
                pass
        else:
            try:
                self._conn.commit()
            except Exception:  # noqa: BLE001, S110
                pass
        self.close()


def get_database_url() -> str:
    """Return the database URL from DATABASE_URL env var or default local test postgres."""
    return os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/plantpulse_test"
    )


def get_pool(database_url: str | None = None) -> ConnectionPool:
    """Get or create a ConnectionPool for the specified database URL."""
    url = database_url or get_database_url()
    # Normalize if a file path or non-postgres URL was passed for legacy compatibility
    if not url.startswith(("postgresql://", "postgres://")):
        url = get_database_url()

    with _pools_lock:
        pool = _pools.get(url)
        connect_timeout = float(os.getenv("DB_CONNECT_TIMEOUT", "15.0"))
        if pool is None or pool.closed:
            pool = ConnectionPool(
                conninfo=url,
                kwargs={"prepare_threshold": None, "row_factory": dict_row},
                check=ConnectionPool.check_connection,
                min_size=1,
                max_size=20,
                timeout=connect_timeout,
                max_idle=float(os.getenv("DB_MAX_IDLE", "300.0")),
                max_lifetime=float(os.getenv("DB_MAX_LIFETIME", "1800.0")),
                open=True,
            )
            _pools[url] = pool
        return pool


def close_pools() -> None:
    """Close all open connection pools."""
    with _pools_lock:
        for pool in _pools.values():
            try:
                pool.close()
            except Exception:  # noqa: BLE001, S110
                pass
        _pools.clear()


def get_db_connection(db_target: Any = None) -> PooledConnectionWrapper:
    """Return a pooled PostgreSQL connection with prepare_threshold=None and dict_row.

    Every call checks out its own connection; no sharing across threads.
    """
    url: str | None = None
    if isinstance(db_target, str) and db_target.startswith(
        ("postgresql://", "postgres://")
    ):
        url = db_target

    pool = get_pool(url)
    connect_timeout = float(os.getenv("DB_CONNECT_TIMEOUT", "15.0"))
    try:
        conn = pool.getconn(timeout=connect_timeout)
    except Exception as exc:
        if os.getenv("CI"):
            raise RuntimeError(f"Database connection failed in CI: {exc}") from exc
        raise

    return PooledConnectionWrapper(pool, conn)


def forget_partition(part_name: str) -> None:
    """Remove a dropped partition name from the in-memory cache."""
    with _partition_lock:
        _known_partitions.discard(part_name)


def ensure_partitions(
    conn: Any = None, days_behind: int = 1, days_ahead: int = 7
) -> list[str]:
    """Pre-create daily partitions for [today - days_behind .. today + days_ahead]."""
    today = datetime.now(UTC).date()
    created = []
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        cur = conn.cursor()
        for i in range(-days_behind, days_ahead + 1):
            d = today + timedelta(days=i)
            part_name = f"telemetry_values_p{d.strftime('%Y_%m_%d')}"
            start_str = d.strftime("%Y-%m-%d 00:00:00+00")
            end_str = (d + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00+00")
            sql = f"""
            CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF telemetry_values
            FOR VALUES FROM ('{start_str}') TO ('{end_str}');
            """
            cur.execute(sql)
            created.append(part_name)
            _known_partitions.add(part_name)
        conn.commit()
    finally:
        if should_close:
            conn.close()
    return created


def ensure_partition_for_timestamp(conn: Any, dt: datetime) -> str:
    """Ensure a partition exists for the given datetime under a lock."""
    d = dt.astimezone(UTC).date() if dt.tzinfo else dt.date()
    part_name = f"telemetry_values_p{d.strftime('%Y_%m_%d')}"
    if part_name in _known_partitions:
        return part_name

    with _partition_lock:
        if part_name in _known_partitions:
            return part_name
        start_str = d.strftime("%Y-%m-%d 00:00:00+00")
        end_str = (d + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00+00")
        cur = conn.cursor()
        sql = f"""
        CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF telemetry_values
        FOR VALUES FROM ('{start_str}') TO ('{end_str}');
        """
        cur.execute(sql)
        conn.commit()
        _known_partitions.add(part_name)
    return part_name
