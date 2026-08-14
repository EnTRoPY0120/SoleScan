"""Initial searches, adapter runs, and cached offers."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("searches", sa.Column("id", sa.String(36), primary_key=True), sa.Column("cache_key", sa.String(64), nullable=False), sa.Column("request_json", sa.Text(), nullable=False), sa.Column("state", sa.String(20), nullable=False), sa.Column("cached", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_searches_cache_key", "searches", ["cache_key"])
    op.create_table("adapter_runs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("search_id", sa.String(36), nullable=False), sa.Column("retailer_id", sa.String(40), nullable=False), sa.Column("state", sa.String(20), nullable=False), sa.Column("offer_count", sa.Integer(), nullable=False), sa.Column("error", sa.Text(), nullable=True), sa.Column("elapsed_ms", sa.Integer(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_adapter_runs_search_id", "adapter_runs", ["search_id"])
    op.create_index("ix_adapter_runs_retailer_id", "adapter_runs", ["retailer_id"])
    op.create_table("offers", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("search_id", sa.String(36), nullable=False), sa.Column("retailer_id", sa.String(40), nullable=False), sa.Column("offer_json", sa.Text(), nullable=False), sa.Column("weak", sa.Boolean(), nullable=False), sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_offers_search_id", "offers", ["search_id"])
    op.create_index("ix_offers_retailer_id", "offers", ["retailer_id"])

def downgrade():
    op.drop_table("offers")
    op.drop_table("adapter_runs")
    op.drop_table("searches")

