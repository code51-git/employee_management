"""add_expanded_hr_profile_fields

Revision ID: bbe73eea1326
Revises: 1019e77f041e
Create Date: 2026-06-23 09:17:37.417734

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bbe73eea1326'
down_revision: Union[str, None] = '1019e77f041e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_profiles', sa.Column('employee_id', sa.String(length=50), nullable=True))
    
    op.execute("UPDATE user_profiles SET employee_id = 'TEMP-' || id WHERE employee_id IS NULL")
    
    op.alter_column('user_profiles', 'employee_id', nullable=False)
    
    op.add_column('user_profiles', sa.Column('employee_type', sa.String(length=50), server_default='Full-Time', nullable=False))
    
    op.add_column('user_profiles', sa.Column('company_email', sa.String(length=255), nullable=True))
    op.add_column('user_profiles', sa.Column('whatsapp_number', sa.String(length=20), nullable=True))
    op.add_column('user_profiles', sa.Column('address', sa.Text(), nullable=True))
    op.add_column('user_profiles', sa.Column('total_industry_experience', sa.Float(), nullable=True))
    op.add_column('user_profiles', sa.Column('document_url', sa.String(length=512), nullable=True))
    op.add_column('user_profiles', sa.Column('total_experience_start_date', sa.Date(), nullable=True))
    
    op.create_index(op.f('ix_user_profiles_employee_id'), 'user_profiles', ['employee_id'], unique=True)
    op.create_unique_constraint('uq_user_profiles_company_email', 'user_profiles', ['company_email'])


def downgrade() -> None:
    op.drop_constraint('uq_user_profiles_company_email', 'user_profiles', type_='unique')
    op.drop_index(op.f('ix_user_profiles_employee_id'), table_name='user_profiles')
    op.drop_column('user_profiles', 'total_experience_start_date')
    op.drop_column('user_profiles', 'document_url')
    op.drop_column('user_profiles', 'total_industry_experience')
    op.drop_column('user_profiles', 'address')
    op.drop_column('user_profiles', 'whatsapp_number')
    op.drop_column('user_profiles', 'company_email')
    op.drop_column('user_profiles', 'employee_type')
    op.drop_column('user_profiles', 'employee_id')
    # ### end Alembic commands ###
