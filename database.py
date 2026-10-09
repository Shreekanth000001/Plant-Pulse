"""
Database models + session setup, using SQLAlchemy + SQLite.

SQLite chosen for v1: zero setup (one file on disk), fine for a single
backend process. Swapping to Postgres later is a one-line change to
DATABASE_URL, not a rewrite — the models/queries stay the same.
"""

from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, JSON, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./factory.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    phase = Column(String, nullable=True)   # QC has no phase
    starved = Column(Boolean, default=False)
    current_unit_id = Column(String, nullable=True)

    vibration = Column(Float, nullable=True)
    vibration_wear_level = Column(Float, nullable=True)
    good_count = Column(Integer, nullable=True)
    reject_count = Column(Integer, nullable=True)

    extra = Column(JSON)  # e.g. {"mold_temperature_setpoint": 65.0, "mold_temperature_actual": 64.2}


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