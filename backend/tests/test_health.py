def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


def test_system_status(client):
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    assert "pans" in body
    assert "model_kinds" in body