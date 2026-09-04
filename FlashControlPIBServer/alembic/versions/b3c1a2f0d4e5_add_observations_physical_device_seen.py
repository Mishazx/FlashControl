"""add observations physical_device + seen_at index

Revision ID: b3c1a2f0d4e5
Revises: 2a9ae8467581
Create Date: 2026-09-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3c1a2f0d4e5'
down_revision: Union[str, Sequence[str], None] = '2a9ae8467581'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'ix_observations_physical_device_seen',
        'observations',
        ['physical_device_id', 'observed_at_utc'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_observations_physical_device_seen', table_name='observations')
