"""create comments

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-20 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('comments',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('task_id', sa.BigInteger(), nullable=False),
    sa.Column('author_id', sa.BigInteger(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_comments_author_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_comments_task_id_tasks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comments'))
    )
    op.create_index('ix_comments_task_id_created_at', 'comments', ['task_id', 'created_at', 'id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_comments_task_id_created_at', table_name='comments')
    op.drop_table('comments')
