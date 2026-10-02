from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app import shipments as shipment_module
from app import weather_routes as wr

NOW = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)


def road(line):
    km = wr._route_length(line)
    return {"geometry": line, "distance_km": km, "duration_minutes": max(1, round(km)), "source": "TEST ROAD"}


def scenario():
    original = road([[8 + i / 10, 49] for i in range(41)])
    zones = [{"id": "first", "lon": 9.45, "lat": 49, "radius_km": 14},
             {"id": "second", "lon": 10.2, "lat": 49.14, "radius_km": 14}]
    return original, zones


class Router:
    def __init__(self, blocked_trials=0):
        self.calls = 0
        self.blocked_trials = blocked_trials
        self.lock = Lock()

    def via(self, a, b, via):
        with self.lock:
            self.calls += 1
            blocked = self.calls <= self.blocked_trials
        points = [a, b] if blocked else [a, *via, b]
        return road([[p[1], p[0]] for p in points])


def search(router, original, zones, tomtom=None):
    return wr.closest_clear_detour(SimpleNamespace(routing=router, tomtom=tomtom),
                                   (49, 8), (49, 12), original, zones, NOW, {})


def test_third_candidate_clears_both_storms_and_preserves_clear_road():
    original, zones = scenario()
    router = Router(blocked_trials=2)
    result = search(router, original, zones)
    assert router.calls >= 3
    assert result is not None
    assert not wr.crossed_zones(result["geometry"], zones, wr.CLEARANCE_KM)
    assert result["geometry"][0] == original["geometry"][0]
    assert result["geometry"][-1] == original["geometry"][-1]
    assert result["weather_detour"]["divert_at"] != original["geometry"][0]
    assert result["weather_detour"]["rejoin_at"] != original["geometry"][-1]
    assert result["weather_search"]["zones_checked"] == 2


def test_exhausted_search_returns_no_route_without_dropping_a_zone():
    original, zones = scenario()
    router = Router(blocked_trials=999)
    assert search(router, original, zones) is None
    assert router.calls > 2
    assert [z["id"] for z in zones] == ["first", "second"]


def test_endpoint_inside_storm_cannot_be_routed_out_as_clear():
    original, zones = scenario()
    zones.append({"id": "origin", "lon": 8, "lat": 49, "radius_km": 5})
    router = Router()
    assert search(router, original, zones) is None
    assert router.calls == 0


def test_unsafe_tomtom_response_does_not_prevent_fallback_search():
    original, zones = scenario()
    requests = []
    def unsafe(a, b, via, depart, truck, avoid_areas):
        requests.append([z["id"] for z in avoid_areas])
        return road([[a[1], a[0]], [b[1], b[0]]])
    router = Router()
    result = search(router, original, zones, SimpleNamespace(key="test", route_via=unsafe))
    assert result and not wr.crossed_zones(result["geometry"], zones, wr.CLEARANCE_KM)
    assert router.calls > 0
    assert all(ids == ["first", "second"] for ids in requests)


def test_segment_circle_interval_uses_real_segment_intersection():
    zone = {"lon": 8, "lat": 49, "radius_km": 5}
    assert wr._zone_interval([[9, 49], [10, 49]], zone, 5) is None
    interval = wr._zone_interval([[7, 49], [9, 49]], zone, 5)
    assert interval[1] - interval[0] == pytest.approx(10, abs=.1)


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.setattr(shipment_module, "STORE_DIR", str(tmp_path))
    monkeypatch.setattr(shipment_module, "STORE", str(tmp_path / "shipments.json"))
    start = datetime.now(timezone.utc) + timedelta(hours=2)
    option = {"route_id": "A-B:normal", "quote_id": "q1", "revision": 4, "path": ["A", "B"],
              "depart_at": start.isoformat(), "eta": (start + timedelta(hours=4)).isoformat(),
              "avoidance_status": "NO_CLEAR_DETOUR", "geometry": [[8, 49], [12, 49]],
              "risk": {"deadline_ok": True, "level": "HIGH"}, "total_minutes": 240, "components": {},
              "steps": [{"type": "drive", "start": start.isoformat()}],
              "cost": {"transport_eur": 500, "fuel_l": 100, "distance_km": 300, "cost_per_kg": 1}}
    ops = SimpleNamespace(data={"revision": 4})
    ships = shipment_module.Shipments({"operations": ops})
    ships.data = {"S1": {"id": "S1", "origin": "A", "destination": "B", "status": "PLANNED",
                        "route": ["A", "B"], "planned_departure": start.isoformat(), "current_eta": option["eta"],
                        "required_delivery": None, "weight_kg": 500, "created_at": start.isoformat(),
                        "options": [deepcopy(option)], "accepted_plan": deepcopy(option)}}
    return ships, ops, option


def test_hold_is_persistent_blocks_dispatch_and_requires_clear_approval(saved, monkeypatch):
    ships, ops, old = saved
    ships.hold("S1", 0, "Both corridors affected by weather")
    held = ships.data["S1"]
    assert held["hold"]["plan"] == old
    assert held["accepted_plan"] == old
    assert held["status"] == "ON HOLD"
    assert not shipment_module._advance_time_status(held, datetime.now(timezone.utc) + timedelta(days=20))
    assert shipment_module.Shipments(ships.ctx).get("S1")["hold"]["reason"] == "Both corridors affected by weather"
    with pytest.raises(ValueError, match="on hold"):
        ships.set_status("S1", "IN TRANSIT")
    with pytest.raises(ValueError, match="weather zone"):
        ships.schedule("S1", 0, force=True, quote_id="q1")
    clear = {**deepcopy(old), "avoidance_status": "CLEAR", "route_id": "A-B:clear", "quote_id": "q2"}
    monkeypatch.setattr(shipment_module, "plan", lambda *args: [deepcopy(clear)])
    ships.replan("S1")
    assert held["status"] == "ON HOLD"
    result, warning = ships.schedule("S1", 0, quote_id="q2")
    assert warning is None
    assert result["status"] == "SCHEDULED"
    assert "hold" not in result
    assert result["accepted_plan"]["avoidance_status"] == "CLEAR"


def test_manager_hold_endpoint_records_selected_route_and_reason(saved, monkeypatch):
    from app import main
    ships, ops, old = saved
    recorded = []
    def put(collection, record):
        recorded.append((collection, record))
        return record
    ops.put = put
    monkeypatch.setattr(main, "S", {"ships": ships, "operations": ops})
    monkeypatch.setattr(main, "_audit", lambda *args: None)
    client = TestClient(main.app)
    response = client.post("/api/decisions", json={"shipment_id": "S1", "action": "hold", "option": 0,
                          "revision": 4, "quote_id": "q1", "reason": "No verified clear route"})
    assert response.status_code == 200, response.text
    assert ships.data["S1"]["status"] == "ON HOLD"
    assert recorded[0][1]["reviewed_path"] == ["A", "B"]
    assert recorded[0][1]["action"] == "hold"


def test_expired_departure_is_moved_forward_on_hold_review(saved, monkeypatch):
    ships, ops, old = saved
    ships.hold("S1", 0, "Waiting for storm to pass")
    ships.data["S1"]["planned_departure"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    monkeypatch.setattr(shipment_module, "plan", lambda *args: [deepcopy(old)])
    ships.replan("S1")
    assert datetime.fromisoformat(ships.data["S1"]["planned_departure"]) > datetime.now(timezone.utc)
    assert ships.data["S1"]["status"] == "ON HOLD"
    assert ships.data["S1"]["accepted_plan"] == old

def test_traffic_sections_are_filtered_without_quadratic_geometry_scan(monkeypatch):
    original, zones = scenario()
    original['traffic_sections'] = [
        {'geometry': original['geometry'][:3], 'description': 'upstream'},
        {'geometry': original['geometry'][12:24], 'description': 'replaced'},
    ]
    def no_scan(*args):
        raise AssertionError('Per-point full-road scans must not run')
    monkeypatch.setattr(wr, '_distance_to_line', no_scan)
    result = search(Router(), original, zones)
    assert result is not None
    assert [s['description'] for s in result['traffic_sections']] == ['upstream']
    assert not wr.crossed_zones(result['geometry'], zones, wr.CLEARANCE_KM)


def test_search_budget_never_returns_an_unverified_route(monkeypatch):
    original, zones = scenario()
    monkeypatch.setattr(wr, 'SEARCH_BUDGET_SECONDS', 0)
    router = Router()
    assert search(router, original, zones) is None
    assert router.calls == 0


def test_provider_outage_does_not_repeat_timeout_for_each_detour(monkeypatch):
    import httpx
    from app.live import TomTom, DEFAULT_TRUCK
    provider = TomTom()
    provider.key = 'test'
    calls = []
    def timeout(*args, **kwargs):
        calls.append(True)
        raise httpx.ReadTimeout('test outage')
    monkeypatch.setattr(provider.client, 'post', timeout)
    _, zones = scenario()
    departure = datetime.now(timezone.utc) + timedelta(hours=1)
    try:
        assert provider.route_via((49,8),(49,12),[],departure,DEFAULT_TRUCK,zones) is None
        assert provider.route_via((49,8),(49,12),[(50,10)],departure,DEFAULT_TRUCK,zones) is None
        assert len(calls) == 1
    finally:
        provider.client.close()
