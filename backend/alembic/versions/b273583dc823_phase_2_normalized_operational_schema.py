"""phase 2 - normalized operational schema

Revision ID: b273583dc823
Revises: 06ec381186dc
Create Date: 2026-08-29 11:35:57.716334

Replaces the phase-1 demo tables with the normalized operational schema
(pans, sensors, weather readings, digital twin states, model versions,
predictions, recommendations, operation events, harvest outcomes).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

revision = 'b273583dc823'
down_revision = '06ec381186dc'
branch_labels = None
depends_on = None


def _drop_legacy_tables() -> None:
    # Child tables first, respecting legacy foreign keys.
    op.drop_table('outcomes')
    op.drop_table('recommendations')
    op.drop_table('predictions')
    op.drop_table('twin_snapshots')
    op.drop_table('weather_forecasts')
    op.drop_table('ml_models')
    op.drop_table('salt_pans')


def _create_operational_tables() -> None:
    op.create_table('model_versions',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('model_name', sa.String(length=255), nullable=False),
                    sa.Column('model_type', sa.String(length=64), nullable=False),
                    sa.Column('version', sa.Integer(), nullable=False),
                    sa.Column('model_path', sa.String(length=1024), nullable=False),
                    sa.Column('trained_at', sa.DateTime(), nullable=False),
                    sa.Column('training_rows', sa.Integer(), nullable=False),
                    sa.Column('training_start_date', sa.String(length=32), nullable=True),
                    sa.Column('training_end_date', sa.String(length=32), nullable=True),
                    sa.Column('metrics_json', sa.JSON(), nullable=False),
                    sa.Column('feature_names_json', sa.JSON(), nullable=False),
                    sa.Column('uses_proxy_labels', sa.Boolean(), nullable=False),
                    sa.Column('active', sa.Boolean(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.PrimaryKeyConstraint('id'))
    op.create_table('pans',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('pan_code', sa.String(length=64), nullable=False),
                    sa.Column('name', sa.String(length=255), nullable=False),
                    sa.Column('latitude', sa.Float(), nullable=True),
                    sa.Column('longitude', sa.Float(), nullable=True),
                    sa.Column('area_m2', sa.Float(), nullable=False),
                    sa.Column('safe_depth_cm', sa.Float(), nullable=False),
                    sa.Column('safe_storage_available', sa.Boolean(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_pans_pan_code'), 'pans', ['pan_code'], unique=True)

    op.create_table('digital_twin_states',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('pan_id', sa.Integer(), nullable=False),
                    sa.Column('timestamp', sa.DateTime(), nullable=False),
                    sa.Column('brine_volume_m3', sa.Float(), nullable=False),
                    sa.Column('estimated_salt_mass_kg', sa.Float(), nullable=False),
                    sa.Column('evaporation_mm_day', sa.Float(), nullable=False),
                    sa.Column('predicted_rain_volume_m3', sa.Float(), nullable=False),
                    sa.Column('predicted_depth_after_rain_cm', sa.Float(), nullable=False),
                    sa.Column('predicted_salinity_after_rain_g_l', sa.Float(), nullable=False),
                    sa.Column('harvest_readiness', sa.Float(), nullable=False),
                    sa.Column('climate_risk', sa.Float(), nullable=False),
                    sa.Column('overflow_risk', sa.Float(), nullable=False),
                    sa.Column('state_json', sa.JSON(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['pans.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_digital_twin_states_pan_id'), 'digital_twin_states',
                    ['pan_id'], unique=False)

    op.create_table('sensor_readings',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('pan_id', sa.Integer(), nullable=False),
                    sa.Column('timestamp', sa.DateTime(), nullable=False),
                    sa.Column('salinity_g_l', sa.Float(), nullable=False),
                    sa.Column('ec_ms_cm', sa.Float(), nullable=False),
                    sa.Column('water_depth_cm', sa.Float(), nullable=False),
                    sa.Column('brine_temperature_c', sa.Float(), nullable=False),
                    sa.Column('air_temperature_c', sa.Float(), nullable=False),
                    sa.Column('humidity_pct', sa.Float(), nullable=False),
                    sa.Column('sensor_quality', sa.Float(), nullable=False),
                    sa.Column('source', sa.String(length=64), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['pans.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_sensor_readings_pan_id'), 'sensor_readings',
                    ['pan_id'], unique=False)

    op.create_table('weather_readings',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('pan_id', sa.Integer(), nullable=True),
                    sa.Column('forecast_generated_at', sa.DateTime(), nullable=False),
                    sa.Column('forecast_for', sa.Date(), nullable=True),
                    sa.Column('forecast_rain_mm', sa.Float(), nullable=False),
                    sa.Column('rain_probability_pct', sa.Float(), nullable=False),
                    sa.Column('actual_rainfall_mm', sa.Float(), nullable=True),
                    sa.Column('temperature_c', sa.Float(), nullable=False),
                    sa.Column('humidity_pct', sa.Float(), nullable=False),
                    sa.Column('wind_speed_ms', sa.Float(), nullable=False),
                    sa.Column('solar_radiation_wm2', sa.Float(), nullable=False),
                    sa.Column('cloud_cover_pct', sa.Float(), nullable=False),
                    sa.Column('source', sa.String(length=64), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['pans.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_weather_readings_pan_id'), 'weather_readings',
                    ['pan_id'], unique=False)

    op.create_table('predictions',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('pan_id', sa.Integer(), nullable=False),
                    sa.Column('timestamp', sa.DateTime(), nullable=False),
                    sa.Column('model_version_id', sa.Integer(), nullable=True),
                    sa.Column('risk_level', sa.String(length=16), nullable=False),
                    sa.Column('risk_probability', sa.Float(), nullable=False),
                    sa.Column('harvest_ready', sa.Boolean(), nullable=False),
                    sa.Column('harvest_probability', sa.Float(), nullable=False),
                    sa.Column('predicted_harvest_hours', sa.Float(), nullable=True),
                    sa.Column('predicted_yield_kg', sa.Float(), nullable=False),
                    sa.Column('confidence_pct', sa.Float(), nullable=False),
                    sa.Column('input_snapshot_json', sa.JSON(), nullable=False),
                    sa.Column('shap_values_json', sa.JSON(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['pans.id']),
                    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_predictions_pan_id'), 'predictions', ['pan_id'], unique=False)

    op.create_table('recommendations',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('recommendation_code', sa.String(length=64), nullable=False),
                    sa.Column('pan_id', sa.Integer(), nullable=False),
                    sa.Column('prediction_id', sa.Integer(), nullable=True),
                    sa.Column('timestamp', sa.DateTime(), nullable=False),
                    sa.Column('recommended_action', sa.String(length=64), nullable=False),
                    sa.Column('action_deadline', sa.DateTime(), nullable=True),
                    sa.Column('reason_1', sa.Text(), nullable=False),
                    sa.Column('reason_2', sa.Text(), nullable=False),
                    sa.Column('reason_3', sa.Text(), nullable=False),
                    sa.Column('instruction_1', sa.Text(), nullable=False),
                    sa.Column('instruction_2', sa.Text(), nullable=False),
                    sa.Column('instruction_3', sa.Text(), nullable=False),
                    sa.Column('confidence_pct', sa.Float(), nullable=False),
                    sa.Column('status', sa.String(length=32), nullable=False),
                    sa.Column('operator_accepted', sa.Boolean(), nullable=True),
                    sa.Column('operator_response_at', sa.DateTime(), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['pans.id']),
                    sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_recommendations_recommendation_code'),
                    'recommendations', ['recommendation_code'], unique=True)
    op.create_index(op.f('ix_recommendations_pan_id'), 'recommendations',
                    ['pan_id'], unique=False)

    op.create_table('operation_events',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('pan_id', sa.Integer(), nullable=False),
                    sa.Column('recommendation_id', sa.Integer(), nullable=True),
                    sa.Column('event_timestamp', sa.DateTime(), nullable=False),
                    sa.Column('event_type', sa.String(length=64), nullable=False),
                    sa.Column('source_pan_id', sa.Integer(), nullable=True),
                    sa.Column('destination_pan_id', sa.Integer(), nullable=True),
                    sa.Column('transferred_volume_l', sa.Float(), nullable=True),
                    sa.Column('pump_duration_min', sa.Float(), nullable=True),
                    sa.Column('drained_volume_l', sa.Float(), nullable=True),
                    sa.Column('protection_applied', sa.Boolean(), nullable=False),
                    sa.Column('operator_notes', sa.Text(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['pans.id']),
                    sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id']),
                    sa.ForeignKeyConstraint(['source_pan_id'], ['pans.id']),
                    sa.ForeignKeyConstraint(['destination_pan_id'], ['pans.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_operation_events_pan_id'), 'operation_events',
                    ['pan_id'], unique=False)

    op.create_table('harvest_outcomes',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('pan_id', sa.Integer(), nullable=False),
                    sa.Column('recommendation_id', sa.Integer(), nullable=True),
                    sa.Column('harvest_date', sa.String(length=32), nullable=False),
                    sa.Column('actual_yield_kg', sa.Float(), nullable=True),
                    sa.Column('salt_purity_pct', sa.Float(), nullable=True),
                    sa.Column('actual_rainfall_mm', sa.Float(), nullable=True),
                    sa.Column('rain_damage', sa.Boolean(), nullable=True),
                    sa.Column('yield_loss_pct', sa.Float(), nullable=True),
                    sa.Column('outcome_notes', sa.Text(), nullable=False),
                    sa.Column('details_json', sa.JSON(), nullable=False),
                    sa.Column('prediction_id', sa.Integer(), nullable=True),
                    sa.Column('verified', sa.Boolean(), nullable=False),
                    sa.Column('verified_at', sa.DateTime(), nullable=True),
                    sa.Column('feedback_ingested', sa.Boolean(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['pans.id']),
                    sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id']),
                    sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_harvest_outcomes_pan_id'), 'harvest_outcomes',
                    ['pan_id'], unique=False)


def upgrade() -> None:
    _drop_legacy_tables()
    _create_operational_tables()


def _drop_operational_tables() -> None:
    op.drop_table('harvest_outcomes')
    op.drop_table('operation_events')
    op.drop_table('recommendations')
    op.drop_table('predictions')
    op.drop_table('weather_readings')
    op.drop_table('sensor_readings')
    op.drop_table('digital_twin_states')
    op.drop_table('pans')
    op.drop_table('model_versions')


def _create_legacy_tables() -> None:
    op.create_table('ml_models',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('name', sa.VARCHAR(length=255), nullable=False),
                    sa.Column('kind', sa.VARCHAR(length=64), nullable=False),
                    sa.Column('version', sa.Integer(), nullable=False),
                    sa.Column('status', sa.VARCHAR(length=32), nullable=False),
                    sa.Column('artifact_path', sa.VARCHAR(length=1024), nullable=False),
                    sa.Column('feature_names', sqlite.JSON(), nullable=False),
                    sa.Column('metrics', sqlite.JSON(), nullable=False),
                    sa.Column('rows_trained', sa.Integer(), nullable=False),
                    sa.Column('dataset_id', sa.Integer(), nullable=True),
                    sa.Column('created_at', sa.DATETIME(), nullable=False),
                    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_table('salt_pans',
                    sa.Column('id', sa.INTEGER(), nullable=False),
                    sa.Column('pan_id', sa.VARCHAR(length=64), nullable=False),
                    sa.Column('name', sa.VARCHAR(length=255), nullable=False),
                    sa.Column('location', sa.VARCHAR(length=255), nullable=False),
                    sa.Column('latitude', sa.FLOAT(), nullable=True),
                    sa.Column('longitude', sa.FLOAT(), nullable=True),
                    sa.Column('area_m2', sa.FLOAT(), nullable=False),
                    sa.Column('status', sa.VARCHAR(length=32), nullable=False),
                    sa.Column('twin_state', sqlite.JSON(), nullable=False),
                    sa.Column('created_at', sa.DATETIME(), nullable=False),
                    sa.Column('updated_at', sa.DATETIME(), nullable=False),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_salt_pans_pan_id'), 'salt_pans', ['pan_id'], unique=1)

    op.create_table('twin_snapshots',
                    sa.Column('id', sa.INTEGER(), nullable=False),
                    sa.Column('pan_id', sa.INTEGER(), nullable=False),
                    sa.Column('snapshot_date', sa.VARCHAR(length=32), nullable=False),
                    sa.Column('source', sa.VARCHAR(length=64), nullable=False),
                    sa.Column('state', sqlite.JSON(), nullable=False),
                    sa.Column('created_at', sa.DATETIME(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['salt_pans.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_twin_snapshots_pan_id'), 'twin_snapshots',
                    ['pan_id'], unique=False)

    op.create_table('weather_forecasts',
                    sa.Column('id', sa.INTEGER(), nullable=False),
                    sa.Column('pan_id', sa.INTEGER(), nullable=True),
                    sa.Column('source', sa.VARCHAR(length=32), nullable=False),
                    sa.Column('generated_at', sa.DATETIME(), nullable=False),
                    sa.Column('data', sqlite.JSON(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['salt_pans.id']),
                    sa.PrimaryKeyConstraint('id'))

    op.create_table('predictions',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('pan_id', sa.Integer(), nullable=False),
                    sa.Column('model_id', sa.Integer(), nullable=True),
                    sa.Column('prediction_type', sa.VARCHAR(length=64), nullable=False),
                    sa.Column('scenario', sa.VARCHAR(length=64), nullable=False),
                    sa.Column('score', sa.FLOAT(), nullable=False),
                    sa.Column('horizon_days', sa.Integer(), nullable=False),
                    sa.Column('prediction_date', sa.VARCHAR(length=32), nullable=False),
                    sa.Column('forecast_date', sa.VARCHAR(length=32), nullable=False),
                    sa.Column('features', sqlite.JSON(), nullable=False),
                    sa.Column('shap_values', sqlite.JSON(), nullable=False),
                    sa.Column('series', sqlite.JSON(), nullable=False),
                    sa.Column('created_at', sa.DATETIME(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['salt_pans.id']),
                    sa.ForeignKeyConstraint(['model_id'], ['ml_models.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_predictions_pan_id'), 'predictions', ['pan_id'], unique=False)

    op.create_table('recommendations',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('pan_id', sa.Integer(), nullable=False),
                    sa.Column('prediction_id', sa.Integer(), nullable=True),
                    sa.Column('recommendation_type', sa.VARCHAR(length=64), nullable=False),
                    sa.Column('title', sa.VARCHAR(length=255), nullable=False),
                    sa.Column('message', sa.TEXT(), nullable=False),
                    sa.Column('rationale', sa.TEXT(), nullable=False),
                    sa.Column('expected_benefit', sa.VARCHAR(length=512), nullable=False),
                    sa.Column('risk_level', sa.VARCHAR(length=32), nullable=False),
                    sa.Column('status', sa.VARCHAR(length=32), nullable=False),
                    sa.Column('farmer_notes', sa.TEXT(), nullable=False),
                    sa.Column('created_at', sa.DATETIME(), nullable=False),
                    sa.Column('responded_at', sa.DATETIME(), nullable=True),
                    sa.ForeignKeyConstraint(['pan_id'], ['salt_pans.id']),
                    sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_recommendations_pan_id'), 'recommendations',
                    ['pan_id'], unique=False)

    op.create_table('outcomes',
                    sa.Column('id', sa.INTEGER(), nullable=False),
                    sa.Column('pan_id', sa.INTEGER(), nullable=False),
                    sa.Column('prediction_id', sa.INTEGER(), nullable=True),
                    sa.Column('recommendation_id', sa.INTEGER(), nullable=True),
                    sa.Column('outcome_date', sa.VARCHAR(length=32), nullable=False),
                    sa.Column('actual_rainfall_mm', sa.FLOAT(), nullable=False),
                    sa.Column('risk_occurred', sa.BOOLEAN(), nullable=False),
                    sa.Column('action_taken', sa.VARCHAR(length=128), nullable=False),
                    sa.Column('harvest_date', sa.VARCHAR(length=32), nullable=True),
                    sa.Column('harvest_delayed_days', sa.INTEGER(), nullable=True),
                    sa.Column('actual_yield_kg', sa.FLOAT(), nullable=True),
                    sa.Column('brine_density_be', sa.FLOAT(), nullable=True),
                    sa.Column('salt_thickness_mm', sa.FLOAT(), nullable=True),
                    sa.Column('verified', sa.BOOLEAN(), nullable=False),
                    sa.Column('verified_at', sa.DATETIME(), nullable=True),
                    sa.Column('notes', sa.TEXT(), nullable=False),
                    sa.Column('feedback_ingested', sa.BOOLEAN(), nullable=False),
                    sa.Column('created_at', sa.DATETIME(), nullable=False),
                    sa.ForeignKeyConstraint(['pan_id'], ['salt_pans.id']),
                    sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id']),
                    sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id']),
                    sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_outcomes_pan_id'), 'outcomes', ['pan_id'], unique=False)


def downgrade() -> None:
    _drop_operational_tables()
    _create_legacy_tables()