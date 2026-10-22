"""0002_plant_members

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22 18:00:00.000000

Adds plant_members table to record plant ownership and roles for multi-tenant self-service plants.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plant_members",
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="owner", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plant_id", "user_id"),
    )
    op.create_index("idx_plant_members_user_id", "plant_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_plant_members_user_id", table_name="plant_members")
    op.drop_table("plant_members")
