"""Initial widget platform schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table(
        "widgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("widget_type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("button_text", sa.String(60), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("allowed_origins", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    )
    op.create_index("ix_widgets_tenant_id", "widgets", ["tenant_id"])
    op.create_table(
        "submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("widget_id", sa.String(36), sa.ForeignKey("widgets.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("geo", sa.JSON()),
        sa.Column("notification_status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.UniqueConstraint("widget_id", "idempotency_key", name="uq_submission_widget_key"),
    )
    op.create_index("ix_submissions_tenant_id", "submissions", ["tenant_id"])
    op.create_index("ix_submissions_widget_id", "submissions", ["widget_id"])
    op.create_table(
        "post_processing_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "submission_id",
            sa.String(36),
            sa.ForeignKey("submissions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    )
    op.create_index(
        "ix_post_processing_jobs_submission_id", "post_processing_jobs", ["submission_id"]
    )
    op.create_index("ix_post_processing_jobs_status", "post_processing_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("post_processing_jobs")
    op.drop_table("submissions")
    op.drop_table("widgets")
    op.drop_table("users")
