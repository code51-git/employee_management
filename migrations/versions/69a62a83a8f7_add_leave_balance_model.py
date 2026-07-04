"""add_leave_balance_model

Revision ID: 69a62a83a8f7
Revises: 07bde74a444c
Create Date: 2026-06-25 06:15:45.123389

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69a62a83a8f7'
down_revision: Union[str, None] = '07bde74a444c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
