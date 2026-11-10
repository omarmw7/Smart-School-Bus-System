"""اختبارات تعمل بدون Supabase حقيقي.

التشغيل من مجلد "Bus backend":  python -m pytest test_api.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.update(SUPABASE_URL="http://fake", SUPABASE_SERVICE_KEY="fake", DEVICE_API_KEY="device-key")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

import extensions  # noqa: E402
from app import create_app  # noqa: E402
from config import Config  # noqa: E402


def _match(row, filters):
    for key, op, value in filters:
        cell = row.get(key)
        if op == "eq" and cell != value:
            return False
        if op == "neq" and cell == value:
            return False
        if op == "in" and cell not in value:
            return False
        if op == "lte" and not (cell is not None and cell <= value):
            return False
        if op == "gte" and not (cell is not None and cell >= value):
            return False
    return True


class FakeQuery:
    """نسخة مبسطة من سلسلة استعلامات supabase-py."""

    def __init__(self, store, name):
        self.rows = store.setdefault(name, [])
        self.filters, self.op, self.payload, self._order, self._limit = [], "select", None, None, None

    def select(self, *a, **k): return self
    def insert(self, payload): self.op, self.payload = "insert", payload; return self
    def update(self, payload): self.op, self.payload = "update", payload; return self
    def eq(self, key, value): self.filters.append((key, "eq", value)); return self
    def neq(self, key, value): self.filters.append((key, "neq", value)); return self
    def in_(self, key, values): self.filters.append((key, "in", values)); return self
    def lte(self, key, value): self.filters.append((key, "lte", value)); return self
    def gte(self, key, value): self.filters.append((key, "gte", value)); return self
    def order(self, col, desc=False): self._order = (col, desc); return self
    def limit(self, n): self._limit = n; return self

    def execute(self):
        match = [r for r in self.rows if _match(r, self.filters)]
        if self.op == "insert":
            row = dict(self.payload)
            row.setdefault("request_id", len(self.rows) + 1)
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())  # قيمة افتراضية في Postgres
            self.rows.append(row)
            return type("R", (), {"data": [row]})()
        if self.op == "update":
            for r in match:
                r.update(self.payload)
            return type("R", (), {"data": match})()
        if self._order:
            match.sort(key=lambda r: r[self._order[0]], reverse=self._order[1])
        return type("R", (), {"data": match[: self._limit] if self._limit else match})()


class FakeSupabase:
    def __init__(self):
        self.store = {
            "buses": [{"bus_id": 1, "driver_name": "أحمد", "trip_status": "idle", "current_lat": None,
                       "current_lng": None, "current_speed": 0, "last_updated": None}],
            "students": [{"student_id": 7, "name": "سالم", "fingerprint_id": 12, "bus_id": 1,
                          "parent_token": "tok-7", "current_state": "at_home", "state_updated_at": None}],
        }

    def table(self, name):
        return FakeQuery(self.store, name)


@pytest.fixture()
def env():
    fake = FakeSupabase()
    extensions._client = fake
    app = create_app(Config)
    return app.test_client(), fake


DEVICE = {"X-API-Key": "device-key"}
PARENT = {"X-Parent-Token": "tok-7"}


def test_gps_requires_key(env):
    client, _ = env
    assert client.post("/api/gps", json={}).status_code == 401


def test_gps_updates_bus_and_history(env):
    client, fake = env
    r = client.post("/api/gps", headers=DEVICE, json={"bus_id": 1, "latitude": 25.2, "longitude": 55.3, "speed": 40})
    assert r.status_code == 201
    assert fake.store["buses"][0]["current_lat"] == 25.2
    assert len(fake.store["bus_locations"]) == 1


@pytest.mark.parametrize("body,status", [
    ({"bus_id": 1, "latitude": 95, "longitude": 0}, 400),
    ({"bus_id": 1, "latitude": "x", "longitude": 0}, 400),
    ({"bus_id": 99, "latitude": 1, "longitude": 1}, 404),
    ({"latitude": 1, "longitude": 1}, 400),
])
def test_gps_validation(env, body, status):
    client, _ = env
    assert client.post("/api/gps", headers=DEVICE, json=body).status_code == status


def test_infinity_is_rejected_not_server_error(env):
    client, _ = env
    r = client.post("/api/gps", headers=DEVICE, data='{"bus_id": Infinity, "latitude": 1, "longitude": 1}',
                    content_type="application/json")
    assert r.status_code == 400 and r.get_json()["error"] == "invalid_field"


def test_attendance_flow(env):
    client, fake = env
    client.post("/api/gps", headers=DEVICE, json={"bus_id": 1, "latitude": 25.2, "longitude": 55.3})
    r = client.post("/api/attendance", headers=DEVICE, json={"fingerprint_id": 12, "bus_id": 1, "action": "board"})
    assert r.status_code == 201 and r.get_json()["state"] == "on_bus"
    assert fake.store["attendance_logs"][0]["location_lat"] == 25.2
    # بصمة مكررة خلال ثوانٍ: لا تسجيل جديد
    dup = client.post("/api/attendance", headers=DEVICE, json={"student_id": 7, "bus_id": 1, "action": "board"})
    assert dup.get_json()["duplicate"] is True and len(fake.store["attendance_logs"]) == 1
    # النزول عند المنزل
    r = client.post("/api/attendance", headers=DEVICE,
                    json={"student_id": 7, "bus_id": 1, "action": "exit", "destination": "home"})
    assert r.get_json()["state"] == "at_home" and fake.store["students"][0]["current_state"] == "at_home"


def test_attendance_unknown_student_and_bad_action(env):
    client, _ = env
    assert client.post("/api/attendance", headers=DEVICE,
                       json={"fingerprint_id": 999, "bus_id": 1, "action": "board"}).status_code == 404
    assert client.post("/api/attendance", headers=DEVICE,
                       json={"fingerprint_id": 12, "bus_id": 1, "action": "fly"}).status_code == 400


def test_board_twice_is_rejected_after_debounce_window(env):
    client, fake = env
    client.post("/api/attendance", headers=DEVICE, json={"fingerprint_id": 12, "bus_id": 1, "action": "board"})
    later = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    r = client.post("/api/attendance", headers=DEVICE,
                    json={"fingerprint_id": 12, "bus_id": 1, "action": "board", "timestamp": later})
    assert r.status_code == 409 and r.get_json()["error"] == "invalid_sequence"
    assert len(fake.store["attendance_logs"]) == 1


def test_late_offline_event_does_not_overwrite_newer_state(env):
    client, fake = env
    now = datetime.now(timezone.utc)
    client.post("/api/attendance", headers=DEVICE, json={
        "fingerprint_id": 12, "bus_id": 1, "action": "board", "timestamp": now.isoformat()})
    old = (now - timedelta(hours=1)).isoformat()
    r = client.post("/api/attendance", headers=DEVICE, json={
        "fingerprint_id": 12, "bus_id": 1, "action": "exit", "destination": "home", "timestamp": old})
    assert r.status_code == 201
    assert r.get_json()["state"] == "on_bus"
    assert fake.store["students"][0]["current_state"] == "on_bus"
    assert len(fake.store["attendance_logs"]) == 2  # الحدث مسجَّل، لكن الحالة لم تتغير


def test_parent_status_and_token(env):
    client, _ = env
    assert client.get("/api/parents/status").status_code == 401
    assert client.get("/api/parents/status", headers={"X-Parent-Token": "bad"}).status_code == 401
    client.post("/api/gps", headers=DEVICE, json={"bus_id": 1, "latitude": 25.2, "longitude": 55.3})
    body = client.get("/api/parents/status", headers=PARENT).get_json()
    assert body["student"]["name"] == "سالم" and body["bus"]["latitude"] == 25.2
    assert body["bus"]["is_stale"] is False and "parent_token" not in str(body)


def test_absence_requests(env):
    client, _ = env
    day = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    payload = {"type": "absent", "start_date": day, "reason": "مرض"}
    r = client.post("/api/parents/absence-requests", headers=PARENT, json=payload)
    assert r.status_code == 201
    assert client.post("/api/parents/absence-requests", headers=PARENT, json=payload).status_code == 409
    assert client.post("/api/parents/absence-requests", headers=PARENT,
                       json={"type": "absent", "start_date": "2020-01-01"}).status_code == 400
    assert len(client.get("/api/parents/absence-requests", headers=PARENT).get_json()["requests"]) == 1
    rid = r.get_json()["request"]["request_id"]
    assert client.delete(f"/api/parents/absence-requests/{rid}", headers=PARENT).status_code == 200
    assert client.delete(f"/api/parents/absence-requests/{rid}", headers=PARENT).status_code == 409


def test_overlapping_absence_range_is_rejected(env):
    client, _ = env
    d = (datetime.now(timezone.utc) + timedelta(days=3)).date()
    ok = client.post("/api/parents/absence-requests", headers=PARENT, json={
        "type": "absent", "start_date": d.isoformat(), "end_date": (d + timedelta(days=3)).isoformat()})
    assert ok.status_code == 201
    overlap = client.post("/api/parents/absence-requests", headers=PARENT, json={
        "type": "no_bus", "start_date": (d + timedelta(days=2)).isoformat(),
        "end_date": (d + timedelta(days=5)).isoformat()})
    assert overlap.status_code == 409
    separate = client.post("/api/parents/absence-requests", headers=PARENT, json={
        "type": "absent", "start_date": (d + timedelta(days=10)).isoformat()})
    assert separate.status_code == 201
