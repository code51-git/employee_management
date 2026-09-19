"""add status to attendance

Revision ID: 44a87467d6a5
Revises: b64f562f0aed
Create Date: 2026-09-19 ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '44a87467d6a5'
down_revision: Union[str, None] = 'b64f562f0aed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    attendance_status = postgresql.ENUM(
        'PRESENT', 'HALF_DAY', 'ABSENT',
        name='attendance_status'
    )
    attendance_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'attendance',
        sa.Column(
            'status',
            postgresql.ENUM('PRESENT', 'HALF_DAY', 'ABSENT', name='attendance_status', create_type=False),
            nullable=False,
            server_default='PRESENT'
        )
    )

    op.alter_column('attendance', 'status', server_default=None)


def downgrade() -> None:
    op.drop_column('attendance', 'status')
    postgresql.ENUM(name='attendance_status').drop(op.get_bind(), checkfirst=True)