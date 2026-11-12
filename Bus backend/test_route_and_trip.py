"""اختبارات المسار الديناميكي ونهاية الرحلة (بدون Supabase حقيقي).

التشغيل من مجلد "Bus backend":  python -m pytest test_route_and_trip.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.update(SUPABASE_URL="http://fake", SUPABASE_SERVICE_KEY="fake",
                  DEVICE_API_KEY="device-key", FLASK_SECRET_KEY="test-secret", OSRM_URL="")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

import extensions  # noqa: E402
from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from route_planner import haversine_m, order_stops  # noqa: E402
from test_api import FakeSupabase  # noqa: E402

DEVICE = {"X-API-Key": "device-key"}
SCHOOL = (25.30, 55.40)


class TestConfig(Config):
    OSRM_URL = ""
    SCHOOL_LAT = SCHOOL[0]
    SCHOOL_LNG = SCHOOL[1]


class NoSchoolConfig(Config):
    OSRM_URL = ""
    SCHOOL_LAT = None
    SCHOOL_LNG = None


def _student(student_id, name, fingerprint_id, state="at_home", lat=None, lng=None):
    return {"student_id": student_id, "name": name, "fingerprint_id": fingerprint_id,
            "parent_phone": "0500000000", "bus_id": 1, "status": "active",
            "parent_token": f"tok-{student_id}", "current_state": state,
            "state_updated_at": None, "home_lat": lat, "home_lng": lng,
            "created_at": "2026-11-01T00:00:00+00:00"}


@pytest.fixture()
def fake():
    f = FakeSupabase()
    f.store["students"] = [
        _student(7, "سالم", 12, lat=25.20, lng=55.30),                 # ينتظر الباص
        _student(8, "ليلى", 13, lat=25.25, lng=55.35),                 # ينتظر الباص
        _student(9, "زيد", 14, lat=25.22, lng=55.33),                  # غائب اليوم
        _student(10, "نور", 15, state="on_bus", lat=25.21, lng=55.31),  # صعد الباص
        _student(11, "عمر", 16, lat=None, lng=None),                    # بدون موقع بيت
    ]
    f.store["absence_requests"] = [{
        "request_id": 1, "student_id": 9, "request_type": "absent", "status": "approved",
        "start_date": datetime.now(timezone.utc).date().isoformat(),
        "end_date": (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat(),
    }]
    extensions._client = f
    return f


@pytest.fixture()
def client(fake):
    return create_app(TestConfig).test_client()


def test_order_stops_is_no_worse_than_input_order():
    stops = [{"lat": 25.0, "lng": 55.0}, {"lat": 25.3, "lng": 55.3},
             {"lat": 25.1, "lng": 55.1}, {"lat": 25.4, "lng": 55.4}]
    start, end = (24.9, 54.9), (25.5, 55.5)

    def length(seq):
        pts = [start] + [(s["lat"], s["lng"]) for s in seq] + [end]
        return sum(haversine_m(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1))

    best = order_stops(start, stops, end)
    assert length(best) <= length(stops) + 1e-6
    assert sorted(s["lat"] for s in best) == sorted(s["lat"] for s in stops)


def test_route_excludes_boarded_and_absent_and_no_location(client):
    r = client.get("/api/buses/1/route", headers=DEVICE)
    assert r.status_code == 200
    body = r.get_json()
    names = [s["name"] for s in body["stops"]]
    assert sorted(names) == ["سالم", "ليلى"]          # نور صعدت، زيد غائب، عمر بلا موقع
    assert body["without_location"] == [{"student_id": 11, "name": "عمر"}]
    assert [s["order"] for s in body["stops"]] == [1, 2]
    assert body["total_distance_m"] > body["distance_to_school_m"] > 0


def test_route_requires_device_key(client):
    assert client.get("/api/buses/1/route").status_code == 401


def test_route_unknown_bus(client):
    assert client.get("/api/buses/99/route", headers=DEVICE).status_code == 404


def test_route_needs_school_config(fake):
    client = create_app(NoSchoolConfig).test_client()
    r = client.get("/api/buses/1/route", headers=DEVICE)
    assert r.status_code == 503 and r.get_json()["error"] == "school_not_configured"


def test_trip_starts_on_first_boarding_and_finishes_after_last_exit(client, fake):
    assert fake.store["buses"][0]["trip_status"] == "idle"

    board = client.post("/api/attendance", headers=DEVICE,
                        json={"bus_id": 1, "fingerprint_id": 12, "action": "board"})
    assert board.status_code == 201
    assert fake.store["buses"][0]["trip_status"] == "on_route"

    # نور ما زالت على الباص، فالرحلة ما تنتهي بعد
    first = client.post("/api/attendance", headers=DEVICE,
                        json={"bus_id": 1, "fingerprint_id": 12, "action": "exit", "destination": "school",
                              "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()})
    assert first.status_code == 201
    assert "trip_finished" not in first.get_json()
    assert fake.store["buses"][0]["trip_status"] == "on_route"

    # آخر راكب ينزل (نور لا تزال on_bus، فنعلّمها نزلت أولاً)
    fake.store["students"][3]["current_state"] = "at_home"
    last = client.post("/api/attendance", headers=DEVICE,
                       json={"bus_id": 1, "fingerprint_id": 15, "action": "board"})
    assert last.status_code == 201
    fake.store["students"][3]["current_state"] = "on_bus"
    done = client.post("/api/attendance", headers=DEVICE,
                       json={"bus_id": 1, "fingerprint_id": 15, "action": "exit", "destination": "home",
                             "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()})
    assert done.status_code == 201
    assert done.get_json().get("trip_finished") is True
    assert fake.store["buses"][0]["trip_status"] == "finished"
