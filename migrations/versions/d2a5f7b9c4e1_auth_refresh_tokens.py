"""add_auth_refresh_tokens

Revision ID: d2a5f7b9c4e1
Revises: b6f9a7d0c1e3
Create Date: 2026-06-14 00:20:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d2a5f7b9c4e1"
down_revision = "b6f9a7d0c1e3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["replaced_by_token_id"], ["auth_refresh_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_refresh_tokens")),
        sa.UniqueConstraint("jti", name=op.f("uq_auth_refresh_tokens_jti")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_auth_refresh_tokens_created_at"), "auth_refresh_tokens", ["created_at"])
    op.create_index(op.f("ix_auth_refresh_tokens_jti"), "auth_refresh_tokens", ["jti"], unique=True)
    op.create_index(op.f("ix_auth_refresh_tokens_token_hash"), "auth_refresh_tokens", ["token_hash"], unique=True)
    op.create_index(op.f("ix_auth_refresh_tokens_user_id"), "auth_refresh_tokens", ["user_id"])
    op.create_index("idx_auth_refresh_tokens_user_active", "auth_refresh_tokens", ["user_id", "revoked_at", "expires_at"])


def downgrade():
    op.drop_index("idx_auth_refresh_tokens_user_active", table_name="auth_refresh_tokens")
    op.drop_index(op.f("ix_auth_refresh_tokens_user_id"), table_name="auth_refresh_tokens")
    op.drop_index(op.f("ix_auth_refresh_tokens_token_hash"), table_name="auth_refresh_tokens")
    op.drop_index(op.f("ix_auth_refresh_tokens_jti"), table_name="auth_refresh_tokens")
    op.drop_index(op.f("ix_auth_refresh_tokens_created_at"), table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
