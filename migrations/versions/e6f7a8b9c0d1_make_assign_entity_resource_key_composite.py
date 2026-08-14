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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("assign_entity_resource"):
        return
    primary_key = inspector.get_pk_constraint("assign_entity_resource")
    if primary_key.get("constrained_columns") == [
        "resource",
        "dataset",
        "organisation",
    ]:
        return

    op.create_table(
        "assign_entity_resource_new",
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
    op.execute("""
        INSERT INTO assign_entity_resource_new
            (resource, dataset, organisation, status, actor_username, updated_at)
        SELECT resource, '', '', status, actor_username, updated_at
        FROM assign_entity_resource
        """)
    op.drop_table("assign_entity_resource")
    op.rename_table("assign_entity_resource_new", "assign_entity_resource")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("assign_entity_resource"):
        return
    primary_key = inspector.get_pk_constraint("assign_entity_resource")
    if primary_key.get("constrained_columns") == ["resource"]:
        return

    op.create_table(
        "assign_entity_resource_old",
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
    op.execute("""
        INSERT INTO assign_entity_resource_old
            (resource, status, actor_username, updated_at)
        SELECT resource, status, actor_username, updated_at
        FROM assign_entity_resource
        WHERE dataset = '' AND organisation = ''
        """)
    op.drop_table("assign_entity_resource")
    op.rename_table("assign_entity_resource_old", "assign_entity_resource")
