"""phase_10_recommendation_consequence_if_waited

Revision ID: c1f0d2e3b4a5
Revises: a1b2c3d4e5f6
Create Date: 2026-08-29 20:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c1f0d2e3b4a5'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recommendations', sa.Column('consequence_if_waited',
                                               sa.Text(), nullable=False,
                                               server_default=''))


def downgrade() -> None:
    op.drop_column('recommendations', 'consequence_if_waited')