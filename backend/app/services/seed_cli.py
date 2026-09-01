"""Reproducible Phase-14 demo seed CLI.

Wipes all application data and re-creates the full demo deterministically,
without any physical sensor hardware or a weather API key.

Usage:
    .venv/bin/python -m app.services.seed_cli [--keep-dataset]

The dataset CSV under `settings.samples_path` is cached between runs so the
physics/data-generator stays byte-identical (reproducible); pass
`--keep-dataset` to keep that cache, or delete it to regenerate.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import delete

from app.database import Base, SessionLocal, engine
from app.models import (
    DataSet,
    DigitalTwinState,
    HarvestOutcome,
    ModelVersion,
    OperationEvent,
    Pan,
    Prediction,
    Recommendation,
    SensorReading,
    WeatherReading,
)
from app.services.seeding import seed_all

# Deletion order respects foreign keys (leaf tables before pans).
_DELETE_ORDER = [
    SensorReading,
    WeatherReading,
    OperationEvent,
    HarvestOutcome,
    Recommendation,
    Prediction,
    DigitalTwinState,
    ModelVersion,
    DataSet,
    Pan,
]


def reseed_demo() -> dict:
    Base.metadata.create_all(bind=engine)  # no-op when Alembic already built tables
    db = SessionLocal()
    try:
        for model in _DELETE_ORDER:
            db.execute(delete(model))
        db.commit()
        result = seed_all(db)
        db.commit()
        return result
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Re-seed the Salt Pan DSS demo data.")
    parser.add_argument("--keep-dataset", action="store_true",
                        help="Do not clear the cached generated sample dataset CSV.")
    args = parser.parse_args(argv)

    if not args.keep_dataset:
        from app.config import get_settings

        sample = get_settings().samples_path / "salt_pan_dataset.csv"
        if sample.exists():
            sample.unlink()
            print(f"removed cached dataset: {sample}")

    result = reseed_demo()
    if result.get("already_seeded"):
        print("already seeded (nothing to do)")
        return 0
    print("Demo seeded reproducibly:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
