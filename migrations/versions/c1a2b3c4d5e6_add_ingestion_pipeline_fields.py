"""add_ingestion_pipeline_fields

Revision ID: c1a2b3c4d5e6
Revises: b6f9a7d0c1e3
Create Date: 2026-06-14 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c1a2b3c4d5e6"
down_revision = "b6f9a7d0c1e3"
branch_labels = None
depends_on = None


def _create_index_if_not_exists(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    unique_sql = "UNIQUE " if unique else ""
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    op.execute(f'CREATE {unique_sql}INDEX IF NOT EXISTS "{name}" ON "{table}" ({quoted_columns})')


def _drop_index_if_exists(name: str) -> None:
    op.execute(f'DROP INDEX IF EXISTS "{name}"')


def upgrade():
    # Document model updates
    op.add_column("documents", sa.Column("file_content", postgresql.BYTEA(), nullable=True, comment="Nội dung file gốc lưu trong PostgreSQL BYTEA (max 100MB)"))
    op.add_column("documents", sa.Column("is_compressed", sa.Boolean(), nullable=False, server_default=sa.text("false"), comment="Đánh dấu nếu file_content đã được nén gzip"))
    op.add_column("documents", sa.Column("markdown_content", sa.Text(), nullable=True, comment="Nội dung markdown sau khi parse từ file gốc"))
    op.add_column("documents", sa.Column("storage_size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="Kích thước storage thực tế để tracking quota"))
    op.add_column("documents", sa.Column("has_partial_failures", sa.Boolean(), nullable=False, server_default=sa.text("false"), comment="Đánh dấu nếu có chunk embedding thất bại"))
    op.add_column("documents", sa.Column("pipeline_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb"), comment="Checkpoint state để resume pipeline từ step bị crash"))
    op.add_column("documents", sa.Column("processing_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'::jsonb"), comment="Metadata cho document-level như global_summary, token counts, cost tracking"))
    
    # Update blake3_hash column length from 32 to 64
    op.alter_column("documents", "blake3_hash", existing_type=sa.String(32), type_=sa.String(64), nullable=False)
    
    # Drop old index and create new unique index
    _drop_index_if_exists("idx_documents_project_hash")
    _create_index_if_not_exists("idx_documents_project_hash_unique", "documents", ["project_id", "blake3_hash"], unique=True)
    
    # Update status column length for new enum value
    op.alter_column("documents", "status", existing_type=sa.String(20), type_=sa.String(30), nullable=False)
    
    # DocumentChunk model updates
    op.add_column("document_chunks", sa.Column("enriched_content", sa.Text(), nullable=True, comment="Nội dung sau khi enrich với title + global summary"))
    op.add_column("document_chunks", sa.Column("embed_status", sa.String(20), nullable=False, server_default=sa.text("'pending'"), comment="pending, done, failed"))
    op.add_column("document_chunks", sa.Column("chunk_source", sa.String(50), nullable=False, server_default=sa.text("'auto'"), comment="auto vs existing (cho chunk dedup)"))
    
    # Update chunk_hash column length from 64 to 64 (already correct, but ensure index is unique)
    _drop_index_if_exists("idx_chunks_document_hash")
    _drop_index_if_exists("ix_document_chunks_chunk_hash")
    _create_index_if_not_exists("idx_chunks_hash_unique", "document_chunks", ["chunk_hash"], unique=True)
    
    # Create DocumentChunkLink table
    op.create_table(
        "document_chunk_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunk_links")),
    )
    
    _create_index_if_not_exists("idx_doc_chunk_link_unique", "document_chunk_links", ["document_id", "chunk_id"], unique=True)
    _create_index_if_not_exists("ix_document_chunk_links_document_id", "document_chunk_links", ["document_id"])
    _create_index_if_not_exists("ix_document_chunk_links_chunk_id", "document_chunk_links", ["chunk_id"])
    
    # IngestionTask model updates
    op.add_column("ingestion_tasks", sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="Số lần retry task"))
    op.add_column("ingestion_tasks", sa.Column("last_error_step", sa.String(50), nullable=True, comment="Step cuối cùng gặp lỗi"))
    op.add_column("ingestion_tasks", sa.Column("worker_id", sa.String(100), nullable=True, comment="ID của worker đang xử lý task"))


def downgrade():
    # IngestionTask model rollback
    op.drop_column("ingestion_tasks", "worker_id")
    op.drop_column("ingestion_tasks", "last_error_step")
    op.drop_column("ingestion_tasks", "attempts")
    
    # DocumentChunkLink table rollback
    _drop_index_if_exists("ix_document_chunk_links_chunk_id")
    _drop_index_if_exists("ix_document_chunk_links_document_id")
    _drop_index_if_exists("idx_doc_chunk_link_unique")
    op.drop_table("document_chunk_links")
    
    # DocumentChunk model rollback
    op.drop_column("document_chunks", "chunk_source")
    op.drop_column("document_chunks", "embed_status")
    op.drop_column("document_chunks", "enriched_content")
    
    # Restore old indexes
    _drop_index_if_exists("idx_chunks_hash_unique")
    _create_index_if_not_exists("idx_chunks_document_hash", "document_chunks", ["document_id", "chunk_hash"], unique=True)
    _create_index_if_not_exists("ix_document_chunks_chunk_hash", "document_chunks", ["chunk_hash"])
    
    # Document model rollback
    op.alter_column("documents", "status", existing_type=sa.String(30), type_=sa.String(20), nullable=False)
    
    _drop_index_if_exists("idx_documents_project_hash_unique")
    _create_index_if_not_exists("idx_documents_project_hash", "documents", ["project_id", "blake3_hash"])
    
    op.alter_column("documents", "blake3_hash", existing_type=sa.String(64), type_=sa.String(32), nullable=False)
    
    op.drop_column("documents", "pipeline_state")
    op.drop_column("documents", "processing_metadata")
    op.drop_column("documents", "has_partial_failures")
    op.drop_column("documents", "storage_size_bytes")
    op.drop_column("documents", "markdown_content")
    op.drop_column("documents", "is_compressed")
    op.drop_column("documents", "file_content")
