"""updated_fields_in_payroll

Revision ID: 05e416c0edea
Revises: b5a3b8c7b8af
Create Date: 2026-06-24 09:02:40.402195

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05e416c0edea'
down_revision: Union[str, None] = 'b5a3b8c7b8af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('payroll', sa.Column('overtime_pay', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('payroll', sa.Column('total_leave_days', sa.Integer(), nullable=True))
    op.add_column('payroll', sa.Column('lop_days', sa.Integer(), nullable=True))
    op.add_column('payroll', sa.Column('lop_deduction', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('payroll', sa.Column('advance_deduction', sa.Numeric(precision=10, scale=2), nullable=True)) 
    op.add_column('user_profiles', sa.Column('basic_salary', sa.Numeric(precision=10, scale=2), nullable=True))

    op.create_table(
        'advance_salary_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('amount_requested', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('target_repayment_month', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.execute("UPDATE payroll SET overtime_pay = 0.00 WHERE overtime_pay IS NULL")
    op.execute("UPDATE payroll SET total_leave_days = 0 WHERE total_leave_days IS NULL")
    op.execute("UPDATE payroll SET lop_days = 0 WHERE lop_days IS NULL")
    op.execute("UPDATE payroll SET lop_deduction = 0.00 WHERE lop_deduction IS NULL")
    op.execute("UPDATE payroll SET advance_deduction = 0.00 WHERE advance_deduction IS NULL") 
    op.execute("UPDATE user_profiles SET basic_salary = 0.00 WHERE basic_salary IS NULL")

    op.alter_column('payroll', 'overtime_pay', nullable=False)
    op.alter_column('payroll', 'total_leave_days', nullable=False)
    op.alter_column('payroll', 'lop_days', nullable=False)
    op.alter_column('payroll', 'lop_deduction', nullable=False)
    op.alter_column('payroll', 'advance_deduction', nullable=False) 
    op.alter_column('user_profiles', 'basic_salary', nullable=False)


def downgrade() -> None:
    op.drop_table('advance_salary_requests')
    op.drop_column('user_profiles', 'basic_salary')
    op.drop_column('payroll', 'advance_deduction')
    op.drop_column('payroll', 'lop_deduction')
    op.drop_column('payroll', 'lop_days')
    op.drop_column('payroll', 'total_leave_days')
    op.drop_column('payroll', 'overtime_pay')