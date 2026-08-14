"""make assign entity resource key composite

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-14 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("assign_entity_resource")
    op.create_table(
        "assign_entity_resource",
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("organisation", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("actor_username", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'processed')",
            name="ck_assign_entity_resource_status",
        ),
        sa.PrimaryKeyConstraint("resource", "dataset", "organisation"),
    )


def downgrade():
    op.drop_table("assign_entity_resource")
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
