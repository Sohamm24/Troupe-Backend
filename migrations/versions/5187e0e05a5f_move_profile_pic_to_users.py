"""move_profile_pic_to_users

Revision ID: 5187e0e05a5f
Revises: e6c23e34add2
Create Date: 2026-07-15 01:27:18.590684

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5187e0e05a5f'
down_revision: Union[str, Sequence[str], None] = 'e6c23e34add2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add column to users first
    op.add_column('users', sa.Column('profile_pic', sa.String(), nullable=True))
    # Copy data from organizer_profiles to users
    op.execute(
        "UPDATE users SET profile_pic = organizer_profiles.profile_pic "
        "FROM organizer_profiles WHERE users.user_id = organizer_profiles.user_id"
    )
    # Drop column from organizer_profiles
    op.drop_column('organizer_profiles', 'profile_pic')


def downgrade() -> None:
    """Downgrade schema."""
    # Add column back to organizer_profiles
    op.add_column('organizer_profiles', sa.Column('profile_pic', sa.VARCHAR(), autoincrement=False, nullable=True))
    # Copy data back from users to organizer_profiles
    op.execute(
        "UPDATE organizer_profiles SET profile_pic = users.profile_pic "
        "FROM users WHERE organizer_profiles.user_id = users.user_id"
    )
    # Drop column from users
    op.drop_column('users', 'profile_pic')
