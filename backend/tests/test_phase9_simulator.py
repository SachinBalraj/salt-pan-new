"""Phase 9: what-if rain simulator — POST /api/pans/{pan_id}/simulate-rain."""
from app.services.simulator import rain_risk_score, risk_to_text

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _make_pan(client, code, twin_state=None, area_m2=500.0):
    body = {
        "pan_id": code,
        "name": "Simulator Pan",
        "location": "Testville",
        "area_m2": area_m2,
        "latitude": 12.0,
        "longitude": 75.0,
    }
    if twin_state is not None:
        body["twin_state"] = twin_state
    r = client.post("/api/pans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------- endpoint
def test_simulate_rain_matches_expected_physics(client):
    """Published example: 245 g/L at 8 cm, 20 mm event => 196 g/L at 10 cm."""
    be = round(245.0 / 9.5, 4)  # brine density (Bé) consistent with 245 g/L
    pan = _make_pan(client, "SIM-1",
                    {"water_depth_cm": 8.0, "brine_density_be": be,
                     "salt_thickness_mm": 6.0, "days_since_last_rain": 5})

    r = client.post(f"/api/pans/{pan['id']}/simulate-rain", json={"rainfall_mm": 20})
    assert r.status_code == 200, r.text
    out = r.json()

    assert out["pan_id"] == "SIM-1"
    assert out["current_salinity_g_l"] == 245.0
    assert out["current_depth_cm"] == 8.0
    assert out["current_volume_m3"] == 40.0          # 8cm / 100 * 500 m²
    assert out["rainfall_mm"] == 20.0
    assert out["rain_volume_m3"] == 10.0             # 20mm / 1000 * 500 m²
    assert out["predicted_depth_after_rain_cm"] == 10.0
    assert out["predicted_salinity_after_rain_g_l"] == 196.0   # 245 * 8 / 10
    assert out["risk_before"] == "LOW"
    assert out["risk_after"] == "HIGH"               # 20mm on an 8cm pan is damaging
    assert out["predicted_harvest_delay_hours"] > 0
    assert out["recommended_action"] == "store_brine"    # concentrated, not ready
    assert out["recommendation"]


def test_simulate_rain_works_for_an_empty_pan(client):
    """No twin state registered: the simulator still answers (no models needed)."""
    pan = _make_pan(client, "SIM-2", area_m2=1000.0)
    assert pan["twin_state"]["water_depth_cm"] == 12.0
    r = client.post(f"/api/pans/{pan['id']}/simulate-rain", json={"rainfall_mm": 10})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["current_depth_cm"] == 12.0
    assert round(out["current_salinity_g_l"], 1) == round(21.0 * 9.5, 1)
    assert out["predicted_depth_after_rain_cm"] == 13.0
    assert out["risk_after"] in ("LOW", "MEDIUM", "HIGH")


def test_simulate_rain_rejections(client):
    missing = client.post("/api/pans/999999/simulate-rain", json={"rainfall_mm": 20})
    assert missing.status_code == 404

    pan = _make_pan(client, "SIM-3")
    for bad in ({"rainfall_mm": 0.0}, {"rainfall_mm": -5}, {"rainfall_mm": 350}):
        assert client.post(f"/api/pans/{pan['id']}/simulate-rain", json=bad).status_code == 422
    assert client.post(f"/api/pans/{pan['id']}/simulate-rain", json={"rainfall_mm": "x"}).status_code == 422


def test_risk_rises_monotonically_with_event_size(client):
    pan = _make_pan(client, "SIM-4")   # default 12cm, 21Bé (~199.5 g/L)
    r = client.post(f"/api/pans/{pan['id']}/simulate-rain", json={"rainfall_mm": 0.5})
    base = r.json()
    levels = [base["risk_after"]]
    rains = [10, 25, 50, 100]
    for mm in rains:
        out = client.post(f"/api/pans/{pan['id']}/simulate-rain",
                          json={"rainfall_mm": mm}).json()
        levels.append(out["risk_after"])
        assert out["predicted_depth_after_rain_cm"] == 12.0 + mm / 10.0
    as_nums = [RISK_ORDER[x] for x in levels]
    assert as_nums == sorted(as_nums)
    assert RISK_ORDER[base["risk_after"]] == 0            # trivial rain ~ no risk
    assert levels[-1] == "HIGH"                           # 100mm floods any pan


def test_deep_damage_contrast(client):
    """Same event on a deeper, more dilute pan is categorically less risky."""
    shallow = _make_pan(client, "SIM-5A", {"water_depth_cm": 8.0,
                                           "brine_density_be": round(26.0, 3)})
    deep = _make_pan(client, "SIM-5B", {"water_depth_cm": 24.0,
                                        "brine_density_be": round(20.0, 3)})
    a = client.post(f"/api/pans/{shallow['id']}/simulate-rain", json={"rainfall_mm": 30}).json()
    b = client.post(f"/api/pans/{deep['id']}/simulate-rain", json={"rainfall_mm": 30}).json()
    assert RISK_ORDER[a["risk_after"]] > RISK_ORDER[b["risk_after"]]
    # the shallow pan loses a bigger share of its concentration to the storm
    drop_a = 1 - a["predicted_salinity_after_rain_g_l"] / a["current_salinity_g_l"]
    drop_b = 1 - b["predicted_salinity_after_rain_g_l"] / b["current_salinity_g_l"]
    assert drop_a > drop_b


def test_simulate_rain_does_not_mutate_twin(client):
    pan = _make_pan(client, "SIM-6", {"water_depth_cm": 10.0,
                                      "brine_density_be": round(24.0, 3),
                                      "salt_thickness_mm": 5.0})
    before = client.get(f"/api/pans/{pan['id']}/twin").json()["state"]
    client.post(f"/api/pans/{pan['id']}/simulate-rain", json={"rainfall_mm": 80})
    after = client.get(f"/api/pans/{pan['id']}/twin").json()["state"]
    for k in ("water_depth_cm", "brine_density_be", "salt_thickness_mm"):
        assert after[k] == before[k]


# ------------------------------------------------------------------ unit level
def test_rain_risk_score_invariants():
    assert 0.0 <= rain_risk_score(245, 8, 12, 20) <= 1.0
    assert risk_to_text(rain_risk_score(245, 8, 12, 0.0)) == "LOW"
    assert risk_to_text(rain_risk_score(245, 8, 12, 20.0)) == "HIGH"
    # a shallow concentrated pan loses more than a deep dilute one
    shallow = rain_risk_score(260, 8, 12, 40)
    deep = rain_risk_score(260, 24, 12, 40)
    assert shallow > deep
    # monotonic in event size
    scores = [rain_risk_score(245, 8, 12, r) for r in (0, 5, 20, 60, 100)]
    assert scores == sorted(scores)