"""Tests for database resilience: sslmode support and stale connection replacement."""

import os

import psycopg
from psycopg_pool import ConnectionPool

from db import close_pools, get_db_connection, get_pool


def test_sslmode_in_database_url():
    """DATABASE_URL containing sslmode connects or parses correctly without error."""
    base_url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/plantpulse_test"
    )
    test_url = f"{base_url}{'&' if '?' in base_url else '?'}sslmode=prefer"
    pool = get_pool(test_url)
    assert pool is not None
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 as alive;")
        row = cur.fetchone()
        assert row["alive"] == 1


def test_pool_configured_with_health_check_callback():
    """The default connection pool in db.py must have check=ConnectionPool.check_connection configured."""
    close_pools()
    pool = get_pool()
    # pool._check must be ConnectionPool.check_connection
    assert pool._check is not None, (
        "ConnectionPool must have a check callback configured to replace stale connections"
    )
    assert pool._check == ConnectionPool.check_connection, (
        "ConnectionPool check callback must be ConnectionPool.check_connection"
    )


def test_pool_health_check_replaces_terminated_connection():
    """When a pooled connection's backend is terminated via pg_terminate_backend,
    the pool automatically health-checks and replaces the stale connection so the next call succeeds.
    """
    close_pools()
    # Use max_size=1 pool to guarantee the exact same connection slot is reused
    url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/plantpulse_test"
    )
    pool = get_pool(url)

    conn1 = pool.getconn()
    backend_pid = conn1.info.backend_pid
    assert backend_pid > 0

    # From an independent connection, terminate that backend PID
    admin_conn = psycopg.connect(url, autocommit=True)
    admin_conn.execute("SELECT pg_terminate_backend(%s);", (backend_pid,))
    admin_conn.close()

    # Return the terminated connection to the pool
    pool.putconn(conn1)

    # Next getconn() MUST health-check and discard the terminated backend, returning a working connection
    conn2 = pool.getconn()
    try:
        cur = conn2.execute("SELECT 1 as alive;")
        res = cur.fetchone()
        val = res["alive"] if isinstance(res, dict) else res[0]
        assert val == 1
    finally:
        pool.putconn(conn2)


def test_get_db_connection_replaces_terminated_backend():
    """When backends are terminated via pg_terminate_backend,
    the next get_db_connection() call used by API endpoints succeeds cleanly.
    """
    close_pools()
    url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/plantpulse_test"
    )
    conn1 = get_db_connection(url)
    backend_pid = conn1.info.backend_pid
    conn1.close()

    # Terminate that backend from PostgreSQL
    admin_conn = psycopg.connect(url, autocommit=True)
    admin_conn.execute("SELECT pg_terminate_backend(%s);", (backend_pid,))
    admin_conn.close()

    # Next call (as made by API endpoints) must health-check and succeed
    conn2 = get_db_connection(url)
    try:
        cur = conn2.execute("SELECT 1 as alive;")
        res = cur.fetchone()
        assert res["alive"] == 1
    finally:
        conn2.close()
