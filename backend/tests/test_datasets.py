import io

from app.ml.features import REQUIRED_RAW_COLUMNS


def _upload(client, filename="pans.csv", content=None):
    content = content or "pan_id,date,temperature_c\nPAN-1,2023-04-01,32.5\n"
    files = {"file": (filename, io.BytesIO(content.encode()))}
    return client.post("/api/datasets/upload", files=files)


def test_upload_valid_and_list(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        files = {"file": ("test_dataset.csv", fh, "text/csv")}
        r = client.post("/api/datasets/upload", files=files)
    assert r.status_code == 201, r.text
    ds = r.json()
    assert ds["status"] == "valid"
    assert ds["rows_count"] == 0 or ds["rows_count"] > 0
    assert all(c in ds["columns"] for c in REQUIRED_RAW_COLUMNS)

    r = client.get("/api/datasets")
    assert r.status_code == 200
    assert any(d["id"] == ds["id"] for d in r.json())


def test_upload_missing_columns_is_invalid(client):
    r = _upload(client)
    assert r.status_code == 201
    assert r.json()["status"] == "invalid"
    report = r.json()["validation_report"]
    assert not report["valid"]
    assert any("brine_density_be" in e for e in report["errors"])


def test_upload_garbage_rejected(client):
    r = _upload(client, content="this is; not, a ,csv")
    assert r.status_code in (400, 201)


def test_preview_and_validate(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        r = client.post("/api/datasets/upload", files={"file": ("ds2.csv", fh, "text/csv")})
    ds_id = r.json()["id"]

    p = client.get(f"/api/datasets/{ds_id}/preview?n=5")
    assert p.status_code == 200
    assert len(p.json()["rows"]) == 5

    v = client.post(f"/api/datasets/{ds_id}/validate")
    assert v.status_code == 200
    assert v.json()["status"] == "valid"


def test_promote(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        r = client.post("/api/datasets/upload", files={"file": ("ds3.csv", fh, "text/csv")})
    ds_id = r.json()["id"]
    pr = client.post(f"/api/datasets/{ds_id}/promote")
    assert pr.status_code == 200
    assert pr.json()["status"] == "promoted"