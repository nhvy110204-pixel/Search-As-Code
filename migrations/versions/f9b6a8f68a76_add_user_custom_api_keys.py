"""add_user_custom_api_keys

Revision ID: f9b6a8f68a76
Revises: fc49b22aec3b
Create Date: 2026-06-21 09:45:40.597578
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9b6a8f68a76'
down_revision = 'fc49b22aec3b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('encrypted_custom_api_keys', sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'encrypted_custom_api_keys')
