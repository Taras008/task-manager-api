"""task search and filter indexes

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate не бачить extension і opclass — пишемо вручну.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        'ix_tasks_title_trgm', 'tasks', ['title'],
        postgresql_using='gin', postgresql_ops={'title': 'gin_trgm_ops'},
    )
    op.create_index(
        'ix_tasks_description_trgm', 'tasks', ['description'],
        postgresql_using='gin', postgresql_ops={'description': 'gin_trgm_ops'},
    )
    op.create_index('ix_tasks_status', 'tasks', ['status'], unique=False)
    op.create_index('ix_tasks_created_at', 'tasks', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_tasks_created_at', table_name='tasks')
    op.drop_index('ix_tasks_status', table_name='tasks')
    op.drop_index('ix_tasks_description_trgm', table_name='tasks')
    op.drop_index('ix_tasks_title_trgm', table_name='tasks')
    # Extension pg_trgm навмисно не видаляємо: він може використовуватись деінде.
