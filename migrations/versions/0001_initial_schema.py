"""0001_initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-10-18 13:00:00.000000

Initial multi-plant platform database schema:
12 tables with composite primary/foreign keys, integer primary key autoincrements,
and idempotency unique constraints as specified in Section 3.2.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Plants
    op.create_table(
        "plants",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "timezone", sa.String(length=64), server_default="UTC", nullable=False
        ),
        sa.Column("viewer_token_hash", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
    )

    # 2. Plant Credentials
    op.create_table(
        "plant_credentials",
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plant_id", "username"),
    )
    op.create_index("idx_credentials_username", "plant_credentials", ["username"])

    # 3. Areas
    op.create_table(
        "areas",
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("area_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plant_id", "area_code"),
    )
    op.create_index("idx_areas_order", "areas", ["plant_id", "display_order"])

    # 4. Machines
    op.create_table(
        "machines",
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("machine_code", sa.String(length=64), nullable=False),
        sa.Column("area_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "machine_type",
            sa.String(length=64),
            server_default="standard",
            nullable=False,
        ),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plant_id", "area_code"],
            ["areas.plant_id", "areas.area_code"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("plant_id", "machine_code"),
    )
    op.create_index("idx_machines_area", "machines", ["plant_id", "area_code"])

    # 5. Signals
    op.create_table(
        "signals",
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("machine_code", sa.String(length=64), nullable=False),
        sa.Column("signal_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=32), server_default="", nullable=False),
        sa.Column(
            "data_type", sa.String(length=32), server_default="float", nullable=False
        ),
        sa.Column(
            "is_setpoint", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("setpoint_signal_code", sa.String(length=64), nullable=True),
        sa.Column("normal_min", sa.Float(), nullable=True),
        sa.Column("normal_max", sa.Float(), nullable=True),
        sa.Column("warn_min", sa.Float(), nullable=True),
        sa.Column("warn_max", sa.Float(), nullable=True),
        sa.Column("alarm_min", sa.Float(), nullable=True),
        sa.Column("alarm_max", sa.Float(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plant_id", "machine_code"],
            ["machines.plant_id", "machines.machine_code"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plant_id", "machine_code", "setpoint_signal_code"],
            ["signals.plant_id", "signals.machine_code", "signals.signal_code"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("plant_id", "machine_code", "signal_code"),
    )
    op.create_index(
        "idx_signals_order", "signals", ["plant_id", "machine_code", "display_order"]
    )

    # 6. Machine States
    op.create_table(
        "machine_states",
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("machine_code", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="IDLE", nullable=False),
        sa.Column("sub_state", sa.String(length=64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plant_id", "machine_code"],
            ["machines.plant_id", "machines.machine_code"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("plant_id", "machine_code"),
    )

    # 7. Telemetry Values (partitioned daily by device_timestamp)
    op.create_table(
        "telemetry_values",
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("machine_code", sa.String(length=64), nullable=False),
        sa.Column("signal_code", sa.String(length=64), nullable=False),
        sa.Column("device_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_text", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint(
            "device_timestamp", "plant_id", "message_id", "signal_code"
        ),
        sa.ForeignKeyConstraint(
            ["plant_id", "machine_code"],
            ["machines.plant_id", "machines.machine_code"],
            ondelete="CASCADE",
        ),
        postgresql_partition_by="RANGE (device_timestamp)",
    )
    op.create_index(
        "idx_telemetry_series",
        "telemetry_values",
        ["plant_id", "machine_code", "signal_code", sa.text("device_timestamp DESC")],
    )
    op.create_index("idx_telemetry_retention", "telemetry_values", ["received_at"])

    # 8. Alarm Rules
    op.create_table(
        "alarm_rules",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("machine_code", sa.String(length=64), nullable=False),
        sa.Column("signal_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("threshold_low", sa.Float(), nullable=True),
        sa.Column("threshold_high", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plant_id", "machine_code", "signal_code"],
            ["signals.plant_id", "signals.machine_code", "signals.signal_code"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_alarm_rules_signal",
        "alarm_rules",
        ["plant_id", "machine_code", "signal_code"],
    )

    # 9. Active Alarms
    op.create_table(
        "active_alarms",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("machine_code", sa.String(length=64), nullable=False),
        sa.Column("signal_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default="ACTIVE", nullable=False
        ),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plant_id", "machine_code", "signal_code"],
            ["signals.plant_id", "signals.machine_code", "signals.signal_code"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_active_alarms_plant", "active_alarms", ["plant_id", "status"])

    # 10. Units (product_traceability)
    op.create_table(
        "units",
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("unit_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="in_progress", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plant_id", "unit_id"),
    )
    op.create_index(
        "idx_units_created", "units", ["plant_id", sa.text("created_at DESC")]
    )

    # 11. Stage Events (product_traceability)
    op.create_table(
        "stage_events",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("unit_id", sa.String(length=128), nullable=False),
        sa.Column("machine_code", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column(
            "is_starved", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("anomaly_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("readings", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plant_id", "unit_id"],
            ["units.plant_id", "units.unit_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plant_id", "machine_code"],
            ["machines.plant_id", "machines.machine_code"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "plant_id", "message_id", name="uq_stage_event_idempotency"
        ),
    )
    op.create_index(
        "idx_stage_events_lookup", "stage_events", ["plant_id", "unit_id", "entered_at"]
    )

    # 12. QC Results (quality_inspection)
    op.create_table(
        "qc_results",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("unit_id", sa.String(length=128), nullable=False),
        sa.Column("machine_code", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column(
            "tested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("defect_type", sa.String(length=128), nullable=True),
        sa.Column("attributed_stage", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plant_id", "unit_id"],
            ["units.plant_id", "units.unit_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plant_id", "machine_code"],
            ["machines.plant_id", "machines.machine_code"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("plant_id", "message_id", name="uq_qc_results_idempotency"),
    )
    op.create_index("idx_qc_results_lookup", "qc_results", ["plant_id", "unit_id"])
    op.create_index(
        "idx_qc_results_time", "qc_results", ["plant_id", sa.text("tested_at DESC")]
    )


def downgrade() -> None:
    op.drop_table("qc_results")
    op.drop_table("stage_events")
    op.drop_table("units")
    op.drop_table("active_alarms")
    op.drop_table("alarm_rules")
    op.drop_table("telemetry_values")
    op.drop_table("machine_states")
    op.drop_table("signals")
    op.drop_table("machines")
    op.drop_table("areas")
    op.drop_table("plant_credentials")
    op.drop_table("plants")
