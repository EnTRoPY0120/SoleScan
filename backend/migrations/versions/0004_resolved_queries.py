"""Persist transparent typo-resolved search identity."""

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("searches")}
    if "resolved_query" not in existing:
        with op.batch_alter_table("searches") as batch:
            batch.add_column(sa.Column("resolved_query", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("searches") as batch:
        batch.drop_column("resolved_query")
