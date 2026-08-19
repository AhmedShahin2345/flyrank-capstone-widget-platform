"""Add indexes used by tenant lookup and dashboard time-series queries."""

from alembic import op

revision = "0002_add_query_indexes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_submissions_created_at", "submissions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_submissions_created_at", table_name="submissions")
    op.drop_index("ix_users_tenant_id", table_name="users")
