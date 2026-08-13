"""add assign entity resource status

Revision ID: d5e6f7a8b9c0
Revises: c1d2e3f4a5b6
Create Date: 2026-08-12 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assign_entity_resource",
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("actor_username", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'processed')",
            name="ck_assign_entity_resource_status",
        ),
        sa.PrimaryKeyConstraint("resource"),
    )


def downgrade():
    op.drop_table("assign_entity_resource")
