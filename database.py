"""
Database models + session setup, using SQLAlchemy + SQLite.

SQLite chosen for v1: zero setup (one file on disk), fine for a single
backend process. Swapping to Postgres later is a one-line change to
DATABASE_URL, not a rewrite — the models/queries stay the same.
"""

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    event,
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./factory.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Return a raw SQLite connection to the platform database with foreign keys enforced."""
    if db_path is None:
        db_path = os.getenv("PLATFORM_DB_PATH", "platform.db")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def utcnow() -> datetime:
    return datetime.now(UTC)


class TelemetryReading(Base):
    """One row per tick, per machine. Fields common to every machine are
    real columns; sub-facility-specific fields (temperature vs torque vs
    viscosity) go in `extra`, since forcing them into fixed columns would
    mean a different schema per sub-facility."""

    __tablename__ = "telemetry_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utcnow, index=True)

    machine_id = Column(String, index=True)
    sub_facility = Column(String, index=True)
    machine_state = Column(String)
    phase = Column(String, nullable=True)  # QC has no phase
    starved = Column(Boolean, default=False)
    current_unit_id = Column(String, nullable=True)

    vibration = Column(Float, nullable=True)
    vibration_wear_level = Column(Float, nullable=True)
    good_count = Column(Integer, nullable=True)
    reject_count = Column(Integer, nullable=True)

    extra = Column(
        JSON
    )  # e.g. {"mold_temperature_setpoint": 65.0, "mold_temperature_actual": 64.2}


class Unit(Base):
    __tablename__ = "units"

    unit_id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=utcnow)
    status = Column(String, default="in_progress")  # in_progress / passed / failed


class StageEvent(Base):
    """One row per machine a unit passed through — mirrors Unit.history
    entries from the simulator."""

    __tablename__ = "stage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    unit_id = Column(String, index=True)
    sub_facility = Column(String, index=True)
    machine_id = Column(String, index=True)
    entered_at = Column(DateTime, nullable=True)
    exited_at = Column(DateTime, nullable=True)
    outcome = Column(String)  # "ok" or "flagged"
    anomaly_score = Column(Float)
    readings = Column(JSON)


class QCResult(Base):
    __tablename__ = "qc_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    unit_id = Column(String, index=True)
    machine_id = Column(String)
    tested_at = Column(DateTime, default=utcnow, index=True)
    outcome = Column(String)  # "pass" or "fail"
    probability = Column(Float)
    defect_type = Column(String, nullable=True)
    attributed_stage = Column(String, nullable=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
