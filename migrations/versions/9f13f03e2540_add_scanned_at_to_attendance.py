"""Add scanned_at to attendance

Revision ID: 9f13f03e2540
Revises: fd8243580b31
Create Date: 2025-09-06 09:21:26.802280

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f13f03e2540'
down_revision = 'fd8243580b31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        # Add column with default for existing rows
        batch_op.add_column(
            sa.Column('scanned_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
        )


def downgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_column('scanned_at')

    # ### end Alembic commands ###
