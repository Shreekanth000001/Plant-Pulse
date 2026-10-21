import os
import sqlite3
from pathlib import Path


def get_db_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Return a raw SQLite connection to the platform database with foreign keys enforced.

    Always opens a new connection per call; no shared connection across threads.
    """
    if db_path is None:
        db_path = os.getenv("PLATFORM_DB_PATH", "platform.db")
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn
