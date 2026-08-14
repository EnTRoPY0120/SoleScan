"""Persist collection diagnostics and wall-clock source cooldowns."""

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("adapter_runs")}
    with op.batch_alter_table("adapter_runs") as batch:
        if "reason_code" not in existing:
            batch.add_column(sa.Column("reason_code", sa.String(60), nullable=True))
        if "http_status" not in existing:
            batch.add_column(sa.Column("http_status", sa.Integer(), nullable=True))
        if "retry_count" not in existing:
            batch.add_column(sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
        if "circuit_state" not in existing:
            batch.add_column(sa.Column("circuit_state", sa.String(20), nullable=False, server_default="closed"))
        if "source_url" not in existing:
            batch.add_column(sa.Column("source_url", sa.Text(), nullable=True))

    # Older app versions created this table opportunistically through
    # metadata.create_all(), even though Alembic did not own it. Its monotonic
    # timestamps are meaningless after restart, so discard them while adopting
    # the table into the migration history.
    if "source_health" in sa.inspect(op.get_bind()).get_table_names():
        with op.batch_alter_table("source_health") as batch:
            batch.alter_column(
                "cooldown_until", existing_type=sa.String(40), nullable=True,
            )
        op.execute(sa.text("UPDATE source_health SET cooldown_until = NULL"))
        with op.batch_alter_table("source_health") as batch:
            batch.alter_column(
                "cooldown_until", existing_type=sa.String(40),
                type_=sa.DateTime(timezone=True), nullable=True,
            )
    else:
        op.create_table(
            "source_health",
            sa.Column("host", sa.String(120), primary_key=True),
            sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reason_code", sa.String(40), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    op.drop_table("source_health")
    with op.batch_alter_table("adapter_runs") as batch:
        batch.drop_column("source_url")
        batch.drop_column("circuit_state")
        batch.drop_column("retry_count")
        batch.drop_column("http_status")
        batch.drop_column("reason_code")
