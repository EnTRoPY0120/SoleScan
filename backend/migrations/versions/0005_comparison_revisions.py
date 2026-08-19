"""Persist immutable single-retailer comparison revisions."""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("searches")}
    with op.batch_alter_table("searches") as batch:
        if "source_search_id" not in existing:
            batch.add_column(sa.Column("source_search_id", sa.String(36), nullable=True))
        if "rechecked_retailer_id" not in existing:
            batch.add_column(sa.Column("rechecked_retailer_id", sa.String(40), nullable=True))
        if "verification_attempt" not in existing:
            batch.add_column(sa.Column("verification_attempt", sa.Integer(), nullable=False, server_default="0"))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("searches")}
    if "ix_searches_source_search_id" not in indexes:
        op.create_index("ix_searches_source_search_id", "searches", ["source_search_id"])


def downgrade():
    op.drop_index("ix_searches_source_search_id", table_name="searches")
    with op.batch_alter_table("searches") as batch:
        batch.drop_column("verification_attempt")
        batch.drop_column("rechecked_retailer_id")
        batch.drop_column("source_search_id")
