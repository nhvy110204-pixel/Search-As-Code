"""sync_models_schema

Revision ID: b6f9a7d0c1e3
Revises: 8f4b8f0f3c2a
Create Date: 2026-06-14 00:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b6f9a7d0c1e3"
down_revision = "8f4b8f0f3c2a"
branch_labels = None
depends_on = None


def _create_index_if_not_exists(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    unique_sql = "UNIQUE " if unique else ""
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    op.execute(f'CREATE {unique_sql}INDEX IF NOT EXISTS "{name}" ON "{table}" ({quoted_columns})')


def _drop_index_if_exists(name: str) -> None:
    op.execute(f'DROP INDEX IF EXISTS "{name}"')


def upgrade():
    op.add_column("documents", sa.Column("blake3_hash", sa.String(32), nullable=True))
    op.execute("UPDATE documents SET blake3_hash = md5(id::text) WHERE blake3_hash IS NULL")
    op.alter_column("documents", "blake3_hash", existing_type=sa.String(32), nullable=False)

    op.create_table(
        "ingestion_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(30), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("progress", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("chunking_strategy", sa.String(50), server_default=sa.text("'structural_markdown'"), nullable=False),
        sa.Column("embedding_model", sa.String(100), server_default=sa.text("'bge-small-en-v1.5'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_tasks")),
    )

    _drop_index_if_exists("ix_projects_owner_status")
    _drop_index_if_exists("ix_documents_project_status")
    _drop_index_if_exists("ix_documents_user_status")
    _drop_index_if_exists("ix_document_chunks_document_id")
    _drop_index_if_exists("ix_tasks_user_status")
    _drop_index_if_exists("ix_tasks_status_created")
    _drop_index_if_exists("ix_session_inputs_session_status")
    _drop_index_if_exists("ix_session_inputs_user_created")

    _create_index_if_not_exists("idx_projects_owner_status", "projects", ["owner_user_id", "status"])
    _create_index_if_not_exists("ix_projects_owner_user_id", "projects", ["owner_user_id"])

    _create_index_if_not_exists("idx_documents_project_status", "documents", ["project_id", "status"])
    _create_index_if_not_exists("idx_documents_user_status", "documents", ["user_id", "status"])
    _create_index_if_not_exists("idx_documents_project_hash", "documents", ["project_id", "blake3_hash"])
    _create_index_if_not_exists("ix_documents_user_id", "documents", ["user_id"])
    _create_index_if_not_exists("ix_documents_project_id", "documents", ["project_id"])
    _create_index_if_not_exists("ix_documents_blake3_hash", "documents", ["blake3_hash"])

    _create_index_if_not_exists("idx_chunks_document_id", "document_chunks", ["document_id"])
    _create_index_if_not_exists("ix_document_chunks_chunk_hash", "document_chunks", ["chunk_hash"])
    _create_index_if_not_exists("ix_document_chunks_embedding_id", "document_chunks", ["embedding_id"])
    _create_index_if_not_exists("ix_document_chunks_created_at", "document_chunks", ["created_at"])

    _create_index_if_not_exists("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    _create_index_if_not_exists("ix_chat_sessions_project_id", "chat_sessions", ["project_id"])
    _create_index_if_not_exists("ix_chat_sessions_created_at", "chat_sessions", ["created_at"])
    _create_index_if_not_exists("ix_chat_messages_created_at", "chat_messages", ["created_at"])

    _create_index_if_not_exists("ix_user_api_keys_created_at", "user_api_keys", ["created_at"])
    _create_index_if_not_exists("idx_tasks_user_status", "sac_tasks", ["user_id", "status"])
    _create_index_if_not_exists("idx_tasks_status_created", "sac_tasks", ["status", "created_at"])
    _create_index_if_not_exists("ix_sac_tasks_user_id", "sac_tasks", ["user_id"])
    _create_index_if_not_exists("ix_sac_tasks_project_id", "sac_tasks", ["project_id"])
    _create_index_if_not_exists("ix_sac_tasks_api_key_id", "sac_tasks", ["api_key_id"])
    _create_index_if_not_exists("ix_sac_tasks_created_at", "sac_tasks", ["created_at"])

    _create_index_if_not_exists("ix_task_artifacts_task_id", "task_artifacts", ["task_id"])
    _create_index_if_not_exists("ix_task_artifacts_created_at", "task_artifacts", ["created_at"])
    _create_index_if_not_exists("ix_message_feedbacks_created_at", "message_feedbacks", ["created_at"])

    _create_index_if_not_exists("ix_traces_user_id", "traces", ["user_id"])
    _create_index_if_not_exists("ix_traces_created_at", "traces", ["created_at"])
    _create_index_if_not_exists("ix_spans_trace_id", "spans", ["trace_id"])
    _create_index_if_not_exists("ix_spans_created_at", "spans", ["created_at"])

    _create_index_if_not_exists("ix_user_memories_user_id", "user_memories", ["user_id"])
    _create_index_if_not_exists("ix_user_memories_embedding_id", "user_memories", ["embedding_id"])
    _create_index_if_not_exists("ix_user_memories_created_at", "user_memories", ["created_at"])
    _create_index_if_not_exists("ix_user_preferences_created_at", "user_preferences", ["created_at"])

    _create_index_if_not_exists("idx_session_inputs_session_status", "session_inputs", ["session_id", "status"])
    _create_index_if_not_exists("idx_session_inputs_user_created", "session_inputs", ["user_id", "created_at"])
    _create_index_if_not_exists("ix_session_inputs_session_id", "session_inputs", ["session_id"])
    _create_index_if_not_exists("ix_session_inputs_user_id", "session_inputs", ["user_id"])
    _create_index_if_not_exists("ix_session_inputs_created_at", "session_inputs", ["created_at"])

    _create_index_if_not_exists("ix_ingestion_tasks_document_id", "ingestion_tasks", ["document_id"])
    _create_index_if_not_exists("ix_ingestion_tasks_project_id", "ingestion_tasks", ["project_id"])
    _create_index_if_not_exists("ix_ingestion_tasks_user_id", "ingestion_tasks", ["user_id"])
    _create_index_if_not_exists("ix_ingestion_tasks_created_at", "ingestion_tasks", ["created_at"])
    _create_index_if_not_exists("ix_chat_stream_runs_created_at", "chat_stream_runs", ["created_at"])


def downgrade():
    for index_name in (
        "ix_chat_stream_runs_created_at",
        "ix_ingestion_tasks_created_at",
        "ix_ingestion_tasks_user_id",
        "ix_ingestion_tasks_project_id",
        "ix_ingestion_tasks_document_id",
        "ix_session_inputs_created_at",
        "ix_session_inputs_user_id",
        "ix_session_inputs_session_id",
        "idx_session_inputs_user_created",
        "idx_session_inputs_session_status",
        "ix_user_preferences_created_at",
        "ix_user_memories_created_at",
        "ix_user_memories_embedding_id",
        "ix_user_memories_user_id",
        "ix_spans_created_at",
        "ix_spans_trace_id",
        "ix_traces_created_at",
        "ix_traces_user_id",
        "ix_message_feedbacks_created_at",
        "ix_task_artifacts_created_at",
        "ix_task_artifacts_task_id",
        "ix_sac_tasks_created_at",
        "ix_sac_tasks_api_key_id",
        "ix_sac_tasks_project_id",
        "ix_sac_tasks_user_id",
        "idx_tasks_status_created",
        "idx_tasks_user_status",
        "ix_user_api_keys_created_at",
        "ix_chat_messages_created_at",
        "ix_chat_sessions_created_at",
        "ix_chat_sessions_project_id",
        "ix_chat_sessions_user_id",
        "ix_document_chunks_created_at",
        "ix_document_chunks_embedding_id",
        "ix_document_chunks_chunk_hash",
        "idx_chunks_document_id",
        "ix_documents_blake3_hash",
        "ix_documents_project_id",
        "ix_documents_user_id",
        "idx_documents_project_hash",
        "idx_documents_user_status",
        "idx_documents_project_status",
        "ix_projects_owner_user_id",
        "idx_projects_owner_status",
    ):
        _drop_index_if_exists(index_name)

    op.drop_table("ingestion_tasks")
    op.drop_column("documents", "blake3_hash")

    _create_index_if_not_exists("ix_projects_owner_status", "projects", ["owner_user_id", "status"])
    _create_index_if_not_exists("ix_documents_project_status", "documents", ["project_id", "status"])
    _create_index_if_not_exists("ix_documents_user_status", "documents", ["user_id", "status"])
    _create_index_if_not_exists("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    _create_index_if_not_exists("ix_tasks_user_status", "sac_tasks", ["user_id", "status"])
    _create_index_if_not_exists("ix_tasks_status_created", "sac_tasks", ["status", "created_at"])
    _create_index_if_not_exists("ix_session_inputs_session_status", "session_inputs", ["session_id", "status"])
    _create_index_if_not_exists("ix_session_inputs_user_created", "session_inputs", ["user_id", "created_at"])
