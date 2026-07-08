"""add fcm_token to users

Revision ID: a1b2c3d4e5f6
Revises: 95ee7b734bdf
Create Date: 2026-07-09 03:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '95ee7b734bdf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable fcm_token column to users table."""
    op.add_column(
        "users",
        sa.Column("fcm_token", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Remove fcm_token column from users table."""
    op.drop_column("users", "fcm_token")
