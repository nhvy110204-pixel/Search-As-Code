"""add_chat_stream_runs

Revision ID: 8f4b8f0f3c2a
Revises: d1eecc23602f
Create Date: 2026-06-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "8f4b8f0f3c2a"
down_revision = "d1eecc23602f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_stream_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_request_id", sa.String(128), nullable=True),
        sa.Column("user_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(30), server_default=sa.text("'started'"), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("time_to_first_delta_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_stream_runs")),
    )
    op.create_index(op.f("ix_chat_stream_runs_user_id"), "chat_stream_runs", ["user_id"])
    op.create_index(op.f("ix_chat_stream_runs_session_id"), "chat_stream_runs", ["session_id"])
    op.create_index("idx_chat_stream_runs_user_created", "chat_stream_runs", ["user_id", "created_at"])
    op.create_index("idx_chat_stream_runs_user_status_created", "chat_stream_runs", ["user_id", "status", "created_at"])
    op.create_index(
        "uq_chat_stream_runs_user_client_request",
        "chat_stream_runs",
        ["user_id", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("client_request_id IS NOT NULL AND is_deleted = false"),
    )


def downgrade():
    op.drop_index("uq_chat_stream_runs_user_client_request", table_name="chat_stream_runs")
    op.drop_index("idx_chat_stream_runs_user_status_created", table_name="chat_stream_runs")
    op.drop_index("idx_chat_stream_runs_user_created", table_name="chat_stream_runs")
    op.drop_index(op.f("ix_chat_stream_runs_session_id"), table_name="chat_stream_runs")
    op.drop_index(op.f("ix_chat_stream_runs_user_id"), table_name="chat_stream_runs")
    op.drop_table("chat_stream_runs")
