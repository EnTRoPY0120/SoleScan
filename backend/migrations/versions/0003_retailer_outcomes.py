"""Persist precise retailer outcomes and sanitized failure diagnostics."""

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("adapter_runs")}
    with op.batch_alter_table("adapter_runs") as batch:
        if "outcome" not in existing:
            batch.add_column(sa.Column("outcome", sa.String(40), nullable=True))
        if "diagnostics_json" not in existing:
            batch.add_column(sa.Column("diagnostics_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("adapter_runs") as batch:
        batch.drop_column("diagnostics_json")
        batch.drop_column("outcome")
