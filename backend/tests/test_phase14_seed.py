"""Phase 14: reproducible demo-data seed tests.

The auto-seed (seed_all) must produce a rich demo on a fresh database without
any physical sensors or a weather API key: three pans (incl. the compact
PAN-03 example), 30 days of hourly sensor readings, weather observations with
rainfall events, operation events, harvest outcomes, and the published PAN-03
"Harvest now" scenario (245 g/L, 8 cm, 34 °C, 20 mm rain, 78 %, predicted
196 g/L, Risk High, Readiness Ready).
"""
from app.models import (DigitalTwinState, HarvestOutcome, OperationEvent, Pan,
                        Prediction, Recommendation, SensorReading, WeatherReading)
from app.services.digital_twin import twin_summary
from app.services.seeding import seed_all


def _seed_fresh(db):
    for table in (SensorReading, WeatherReading, OperationEvent, HarvestOutcome,
                  Recommendation, Prediction, DigitalTwinState, Pan):
        db.query(table).delete()
    db.commit()
    return seed_all(db)


def test_seed_creates_three_demo_pans_including_pan03(db):
    result = _seed_fresh(db)
    assert result["pans"] == 3
    codes = {p.pan_code for p in db.query(Pan).all()}
    assert {"PAN-1", "PAN-2", "PAN-03"} <= codes

    pan03 = db.query(Pan).filter(Pan.pan_code == "PAN-03").one()
    assert pan03.area_m2 == 500.0


def test_seed_writes_30_days_of_hourly_sensors(db):
    _seed_fresh(db)
    for pan in db.query(Pan).all():
        readings = (db.query(SensorReading)
                    .filter(SensorReading.pan_id == pan.id).all())
        assert len(readings) >= 30 * 24, pan.pan_code
        timestamps = sorted(r.timestamp for r in readings)
        span = (timestamps[-1] - timestamps[0]).days
        assert span >= 29, pan.pan_code
        # at least 20 distinct hours per day => genuine hourly cadence
        hours = {t.hour for t in timestamps}
        assert len(hours) >= 20, pan.pan_code


def test_seed_writes_weather_observations_with_rainfall_events(db):
    _seed_fresh(db)
    for pan in db.query(Pan).all():
        obs = (db.query(WeatherReading)
               .filter(WeatherReading.pan_id == pan.id,
                       WeatherReading.source == "observation").all())
        assert len(obs) >= 28, pan.pan_code
        rainy = [o for o in obs if (o.actual_rainfall_mm or 0) > 0]
        assert len(rainy) >= 2, pan.pan_code


def test_seed_writes_operations_and_harvest_outcomes(db):
    _seed_fresh(db)
    for pan in db.query(Pan).all():
        ops = (db.query(OperationEvent)
               .filter(OperationEvent.pan_id == pan.id).all())
        outcomes = (db.query(HarvestOutcome)
                    .filter(HarvestOutcome.pan_id == pan.id).all())
        assert len(ops) >= 1, pan.pan_code
        assert len(outcomes) >= 1, pan.pan_code


def test_pan03_example_values_via_twin_summary(db):
    _seed_fresh(db)
    pan03 = db.query(Pan).filter(Pan.pan_code == "PAN-03").one()
    summary = twin_summary(db, pan03)

    assert summary["salinity_g_l"] == 245.0
    assert summary["water_depth_cm"] == 8.0
    assert summary["brine_temperature_c"] == 34.0
    assert summary["forecast_rainfall_mm"] == 20.0
    assert summary["rain_probability_pct"] == 78.0
    assert summary["predicted_salinity_after_rain_g_l"] == 196.0
    # Readiness "Ready" and Risk "High" thresholds used by the dashboard.
    assert summary["harvest_readiness"] >= 0.55
    assert summary["climate_risk"] >= 0.65


def test_pan03_has_harvest_now_recommendation(db):
    _seed_fresh(db)
    pan03 = db.query(Pan).filter(Pan.pan_code == "PAN-03").one()
    recs = (db.query(Recommendation)
            .filter(Recommendation.pan_id == pan03.id,
                    Recommendation.recommended_action == "harvest_now").all())
    assert len(recs) >= 1
