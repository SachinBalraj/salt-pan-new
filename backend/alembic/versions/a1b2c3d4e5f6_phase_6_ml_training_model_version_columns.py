"""phase_6_ml_training_model_version_columns

Revision ID: a1b2c3d4e5f6
Revises: 60c7818b02fe
Create Date: 2026-08-29 19:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '60c7818b02fe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('model_versions', sa.Column('algorithm', sa.String(length=64),
                                              nullable=False, server_default=''))
    op.add_column('model_versions', sa.Column('target_column', sa.String(length=64),
                                              nullable=False, server_default=''))
    op.add_column('model_versions', sa.Column('test_rows', sa.Integer(),
                                              nullable=False, server_default='0'))
    op.add_column('model_versions', sa.Column('split_json',
                                              sa.JSON(), nullable=True))
    op.add_column('model_versions', sa.Column('training_errors_json',
                                              sa.JSON(), nullable=True))
    op.add_column('model_versions', sa.Column('dataset_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('model_versions', 'dataset_id')
    op.drop_column('model_versions', 'training_errors_json')
    op.drop_column('model_versions', 'split_json')
    op.drop_column('model_versions', 'test_rows')
    op.drop_column('model_versions', 'target_column')
    op.drop_column('model_versions', 'algorithm')