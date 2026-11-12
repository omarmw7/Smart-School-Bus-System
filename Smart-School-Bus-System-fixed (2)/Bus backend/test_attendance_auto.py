"""وضع auto: الجهاز يرسل البصمة فقط والسيرفر يحدد صعود أو نزول (بدون Supabase حقيقي)."""
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
from test_api import FakeSupabase  # noqa: E402

DEVICE = {"X-API-Key": "device-key"}


class TestConfig(Config):
    OSRM_URL = ""


@pytest.fixture()
def fake():
    f = FakeSupabase()
    f.store["buses"][0].update(trip_status="on_route", trip_direction="to_home")
    f.store["students"][0]["current_state"] = "at_home"
    extensions._client = f
    return f


@pytest.fixture()
def client(fake):
    return create_app(TestConfig).test_client()


def _tap(client, when_offset, **extra):
    when = (datetime.now(timezone.utc) + timedelta(seconds=when_offset)).isoformat()
    return client.post("/api/attendance", headers=DEVICE,
                       json={"bus_id": 1, "fingerprint_id": 12, "timestamp": when, **extra})


def test_auto_boards_student_who_is_at_home(client, fake):
    r = _tap(client, 0)
    assert r.status_code == 201 and r.get_json()["action"] == "board"
    assert fake.store["students"][0]["current_state"] == "on_bus"


def test_auto_exits_student_on_bus_at_home_on_return_trip(client, fake):
    fake.store["students"][0]["current_state"] = "on_bus"
    r = _tap(client, 60)
    body = r.get_json()
    assert body["action"] == "exit"
    assert body["state"] == "at_home"
    assert fake.store["attendance_logs"][-1]["destination"] == "home"


def test_auto_exits_at_school_on_morning_trip(client, fake):
    fake.store["buses"][0]["trip_direction"] = "to_school"
    fake.store["students"][0]["current_state"] = "on_bus"
    r = _tap(client, 60)
    assert r.get_json()["state"] == "at_school"
    assert fake.store["attendance_logs"][-1]["destination"] == "school"


def test_explicit_action_still_works(client, fake):
    r = _tap(client, 0, action="board")
    assert r.status_code == 201 and r.get_json()["action"] == "board"
