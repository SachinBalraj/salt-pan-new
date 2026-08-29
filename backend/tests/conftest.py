import os
import tempfile

# Environment must be configured before the app package is imported.
_TMP = tempfile.mkdtemp(prefix="saltpan_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test_salt_pan.db"
os.environ["DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["MODELS_DIR"] = os.path.join(_TMP, "models")
os.environ["AUTO_SEED"] = "false"
os.environ["WEATHER_PROVIDER"] = "mock"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _db_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def seeded_client():
    settings = get_settings()
    db = SessionLocal()
    from app.services.seeding import seed_all

    seed_all(db)
    db.close()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sample_dataset_path():
    settings = get_settings()
    import datetime as dt

    from app.services.data_generator import dataset_to_file, generate_dataset

    path = settings.samples_path / "test_dataset.csv"
    if not path.exists():
        df = generate_dataset(start=dt.date(2022, 1, 1), end=dt.date(2023, 6, 30),
                              pan_ids=["PAN-1", "PAN-2"], seed=7)
        dataset_to_file(df, path)
    return path