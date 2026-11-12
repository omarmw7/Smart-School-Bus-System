"""اختبارات ترتيب المسار على الطرق (OSRM trip) والرجوع للترتيب المستقيم."""
import os
import sys
from datetime import date

os.environ.update(SUPABASE_URL="http://fake", SUPABASE_SERVICE_KEY="fake",
                  DEVICE_API_KEY="device-key", FLASK_SECRET_KEY="test-secret", OSRM_URL="")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402
import requests  # noqa: E402

import extensions  # noqa: E402
import route_planner  # noqa: E402
from route_planner import compute_route, road_trip  # noqa: E402
from test_api import FakeSupabase  # noqa: E402

START = (25.10, 55.20)
A = (25.20, 55.30)   # طالب 1
B = (25.21, 55.31)   # طالب 2
SCHOOL = (25.30, 55.40)


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture(autouse=True)
def clear_cache():
    route_planner._trip_cache.clear()
    yield
    route_planner._trip_cache.clear()


def _trip_body(waypoint_indices, legs):
    return {
        "code": "Ok",
        "waypoints": [{"waypoint_index": i} for i in waypoint_indices],
        "trips": [{
            "geometry": {"coordinates": [[55.2, 25.1], [55.3, 25.2], [55.4, 25.3]]},
            "legs": [{"distance": d} for d in legs],
        }],
    }


def test_road_trip_reorders_stops_and_returns_geometry_and_distances(monkeypatch):
    # المدخل: [البداية, A, B, المدرسة]. OSRM يقول: البداية، ثم B، ثم A، ثم المدرسة
    body = _trip_body([0, 2, 1, 3], legs=[1000, 500, 800])
    monkeypatch.setattr(route_planner.requests, "get", lambda *a, **k: FakeResponse(200, body))
    order, geometry, legs = road_trip([START, A, B, SCHOOL], "https://osrm.example")
    assert order == [1, 0]                       # B أولاً ثم A
    assert geometry == [[25.1, 55.2], [25.2, 55.3], [25.3, 55.4]]
    assert legs == [1000, 500, 800]


def test_road_trip_falls_back_on_error_or_timeout(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("slow")
    monkeypatch.setattr(route_planner.requests, "get", boom)
    assert road_trip([START, A, B, SCHOOL], "https://osrm.example") is None


def test_road_trip_falls_back_on_bad_answer(monkeypatch):
    monkeypatch.setattr(route_planner.requests, "get",
                        lambda *a, **k: FakeResponse(200, {"code": "NoTrips"}))
    assert road_trip([START, A, B, SCHOOL], "https://osrm.example") is None


def test_road_trip_disabled_without_url_or_too_few_points(monkeypatch):
    def should_not_call(*a, **k):
        raise AssertionError("must not call OSRM")
    monkeypatch.setattr(route_planner.requests, "get", should_not_call)
    assert road_trip([START, A, B, SCHOOL], "") is None
    assert road_trip([START, SCHOOL], "https://osrm.example") is None


def _db():
    f = FakeSupabase()
    f.store["buses"][0].update(current_lat=None, current_lng=None, trip_status="idle", trip_direction=None)
    f.store["students"] = [
        {"student_id": 1, "name": "أحمد", "bus_id": 1, "status": "active", "current_state": "at_home",
         "home_lat": A[0], "home_lng": A[1]},
        {"student_id": 2, "name": "سارة", "bus_id": 1, "status": "active", "current_state": "at_home",
         "home_lat": B[0], "home_lng": B[1]},
    ]
    f.store["absence_requests"] = []
    return f


def test_compute_route_uses_osrm_order_when_available(monkeypatch):
    body = _trip_body([0, 2, 1, 3], legs=[1000, 500, 800])
    monkeypatch.setattr(route_planner.requests, "get", lambda *a, **k: FakeResponse(200, body))
    route = compute_route(_db(), 1, date(2026, 11, 12), SCHOOL, osrm_url="https://osrm.example")
    assert route["routing"] == "road"
    assert [s["name"] for s in route["stops"]] == ["سارة", "أحمد"]
    assert route["stops"][0]["distance_from_previous_m"] == 1000
    assert route["distance_to_school_m"] == 800
    assert route["total_distance_m"] == 2300
    assert route["geometry"] is not None


def test_compute_route_falls_back_to_straight_when_osrm_down(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("slow")
    monkeypatch.setattr(route_planner.requests, "get", boom)
    route = compute_route(_db(), 1, date(2026, 11, 12), SCHOOL, osrm_url="https://osrm.example")
    assert route["routing"] == "straight" and route["geometry"] is None
    assert len(route["stops"]) == 2
