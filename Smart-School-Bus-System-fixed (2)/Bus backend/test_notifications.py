"""اختبارات الإشعارات: الاقتراب من البيت، صعود/نزول، نهاية الرحلة (بدون Supabase حقيقي)."""
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
HOME = (25.2000, 55.3000)
FAR = (25.2300, 55.3300)     # حوالي 4 كم من البيت
NEAR = (25.2015, 55.3000)    # حوالي 170 متر من البيت
NEARER = (25.2018, 55.3000)  # ما زال داخل الـ 300 متر


class TestConfig(Config):
    OSRM_URL = ""
    SCHOOL_LAT = 25.30
    SCHOOL_LNG = 55.40


@pytest.fixture()
def fake():
    f = FakeSupabase()
    f.store["buses"][0].update(trip_status="idle", current_lat=None, current_lng=None)
    f.store["students"] = [
        {"student_id": 7, "name": "سالم", "fingerprint_id": 12, "bus_id": 1, "status": "active",
         "parent_token": "tok-7", "current_state": "at_home", "state_updated_at": None,
         "home_lat": HOME[0], "home_lng": HOME[1], "created_at": "2026-11-01T00:00:00+00:00"},
        {"student_id": 8, "name": "ليلى", "fingerprint_id": 13, "bus_id": 1, "status": "active",
         "parent_token": "tok-8", "current_state": "at_home", "state_updated_at": None,
         "home_lat": 25.25, "home_lng": 55.35, "created_at": "2026-11-01T00:00:00+00:00"},
    ]
    f.store["absence_requests"] = []
    f.store["notifications"] = []
    extensions._client = f
    return f


@pytest.fixture()
def client(fake):
    return create_app(TestConfig).test_client()


def _gps(client, point):
    r = client.post("/api/gps", headers=DEVICE,
                    json={"bus_id": 1, "latitude": point[0], "longitude": point[1]})
    assert r.status_code == 201, r.get_json()


def _near_home(fake):
    return [n for n in fake.store["notifications"] if n["kind"] == "near_home"]


def test_parent_gets_alert_when_bus_enters_home_zone_once(client, fake):
    _gps(client, FAR)
    assert _near_home(fake) == []
    _gps(client, NEAR)  # دخلت منطقة البيت الآن
    alerts = _near_home(fake)
    assert len(alerts) == 1
    assert alerts[0]["audience"] == "parent" and alerts[0]["student_id"] == 7
    _gps(client, NEARER)  # ما زالت داخل المنطقة: ما نكرر
    assert len(_near_home(fake)) == 1


def test_no_alert_for_student_who_already_boarded(client, fake):
    fake.store["students"][0]["current_state"] = "on_bus"
    _gps(client, FAR)
    _gps(client, NEAR)
    assert _near_home(fake) == []


def test_no_alert_for_absent_student(client, fake):
    today = datetime.now(timezone.utc).date().isoformat()
    fake.store["absence_requests"] = [{"request_id": 1, "student_id": 7, "status": "approved",
                                       "start_date": today, "end_date": today}]
    _gps(client, FAR)
    _gps(client, NEAR)
    assert _near_home(fake) == []


def test_no_alert_when_trip_finished(client, fake):
    fake.store["buses"][0]["trip_status"] = "finished"
    _gps(client, FAR)
    _gps(client, NEAR)
    assert _near_home(fake) == []


def test_parent_sees_only_own_notifications(client, fake):
    fake.store["notifications"] = [
        {"notification_id": 1, "audience": "parent", "kind": "boarded", "message": "سالم",
         "student_id": 7, "bus_id": 1, "created_at": "2026-11-12T06:00:00+00:00"},
        {"notification_id": 2, "audience": "parent", "kind": "boarded", "message": "ليلى",
         "student_id": 8, "bus_id": 1, "created_at": "2026-11-12T06:01:00+00:00"},
        {"notification_id": 3, "audience": "admin", "kind": "trip_finished", "message": "admin",
         "student_id": None, "bus_id": 1, "created_at": "2026-11-12T06:02:00+00:00"},
    ]
    r = client.get("/api/parents/notifications", headers={"X-Parent-Token": "tok-7"})
    assert r.status_code == 200
    assert [n["message"] for n in r.get_json()["notifications"]] == ["سالم"]


def test_board_and_exit_create_parent_alerts_and_trip_end_alerts_admin(client, fake):
    fake.store["students"][0]["current_state"] = "at_home"
    client.post("/api/attendance", headers=DEVICE,
                json={"bus_id": 1, "fingerprint_id": 12, "action": "board"})
    client.post("/api/attendance", headers=DEVICE,
                json={"bus_id": 1, "fingerprint_id": 12, "action": "exit", "destination": "home",
                      "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()})
    kinds = [(n["audience"], n["kind"]) for n in fake.store["notifications"]]
    assert ("parent", "boarded") in kinds
    assert ("parent", "exited") in kinds
    assert ("admin", "trip_finished") in kinds
    exited = next(n for n in fake.store["notifications"] if n["kind"] == "exited")
    assert "عند البيت" in exited["message"] and exited["student_id"] == 7


def test_return_trip_alerts_student_on_bus_when_bus_nears_home(client, fake):
    fake.store["buses"][0].update(trip_status="on_route", trip_direction="to_home")
    fake.store["students"][0]["current_state"] = "on_bus"
    fake.store["students"][1]["current_state"] = "at_school"  # ليلى ما زالت في المدرسة
    _gps(client, FAR)
    _gps(client, NEAR)
    arriving = [n for n in fake.store["notifications"] if n["kind"] == "arriving_home"]
    assert len(arriving) == 1 and arriving[0]["student_id"] == 7
    assert "على وشك النزول" in arriving[0]["message"]
    assert _near_home(fake) == []  # لا تنبيه "جاهز للصعود" في رحلة العودة


def test_morning_pickup_does_not_alert_students_on_bus(client, fake):
    fake.store["buses"][0].update(trip_status="on_route", trip_direction="to_school")
    fake.store["students"][0]["current_state"] = "on_bus"  # صعد الصباح ويمر بجانب بيته
    _gps(client, FAR)
    _gps(client, NEAR)
    assert fake.store["notifications"] == []


def test_afternoon_boarding_sets_return_direction_and_message(client, fake):
    fake.store["buses"][0].update(trip_status="finished", trip_direction=None)
    fake.store["students"][0]["current_state"] = "at_school"
    r = client.post("/api/attendance", headers=DEVICE,
                    json={"bus_id": 1, "fingerprint_id": 12, "action": "board"})
    assert r.status_code == 201
    assert fake.store["buses"][0]["trip_status"] == "on_route"
    assert fake.store["buses"][0]["trip_direction"] == "to_home"
    boarded = [n for n in fake.store["notifications"] if n["kind"] == "boarded"]
    assert boarded and "من المدرسة" in boarded[0]["message"]


def test_morning_first_boarding_sets_to_school_direction(client, fake):
    fake.store["students"][0]["current_state"] = "at_home"
    client.post("/api/attendance", headers=DEVICE,
                json={"bus_id": 1, "fingerprint_id": 12, "action": "board"})
    assert fake.store["buses"][0]["trip_direction"] == "to_school"


def test_parent_push_subscription_is_saved_for_own_student(client, fake):
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "P", "auth": "A"}}
    r = client.post("/api/parents/push-subscription", headers={"X-Parent-Token": "tok-7"}, json=sub)
    assert r.status_code == 201
    saved = fake.store["push_subscriptions"]
    assert len(saved) == 1 and saved[0]["audience"] == "parent" and saved[0]["student_id"] == 7
    # إعادة الاشتراك لنفس الجهاز تحدّث السجل ولا تكرره
    client.post("/api/parents/push-subscription", headers={"X-Parent-Token": "tok-7"}, json=sub)
    assert len(fake.store["push_subscriptions"]) == 1


def test_push_subscription_rejects_bad_payload(client, fake):
    r = client.post("/api/parents/push-subscription", headers={"X-Parent-Token": "tok-7"},
                    json={"endpoint": "http://insecure", "keys": {}})
    assert r.status_code == 400


def test_vapid_public_key_endpoint_and_service_worker(client, fake):
    assert client.get("/api/push/vapid-public-key").get_json() == {"public_key": None}
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["Service-Worker-Allowed"] == "/"


def test_driver_screen_served_and_route_has_roster(client, fake):
    assert client.get("/driver").status_code == 200
    fake.store["buses"][0].update(trip_status="on_route", trip_direction="to_school")
    body = client.get("/api/buses/1/route", headers=DEVICE).get_json()
    assert body["trip_direction"] == "to_school"
    assert {"name": "سالم", "state": "at_home"} in body["roster"]


def test_route_counts_for_driver_going_to_school(client, fake):
    fake.store["buses"][0].update(trip_status="idle", trip_direction=None)
    fake.store["students"][0]["current_state"] = "at_home"   # سالم ينتظر الصعود
    fake.store["students"][1]["current_state"] = "at_home"   # ليلى تنتظر
    body = client.get("/api/buses/1/route", headers=DEVICE).get_json()
    assert body["counts"] == {"to_board": 2, "on_bus": 0}


def test_route_counts_for_driver_returning_home(client, fake):
    fake.store["buses"][0].update(trip_status="on_route", trip_direction="to_home")
    fake.store["students"][0]["current_state"] = "on_bus"
    fake.store["students"][1]["current_state"] = "at_school"  # تنتظر الصعود في المدرسة
    body = client.get("/api/buses/1/route", headers=DEVICE).get_json()
    assert body["counts"] == {"to_board": 1, "on_bus": 1}


def test_events_feed_returns_latest_then_only_new(client, fake):
    fake.store["students"][0]["current_state"] = "at_home"
    client.post("/api/attendance", headers=DEVICE, json={"bus_id": 1, "fingerprint_id": 12, "action": "board"})
    client.post("/api/attendance", headers=DEVICE,
                json={"bus_id": 1, "fingerprint_id": 12, "action": "exit", "destination": "home",
                      "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()})
    first = client.get("/api/buses/1/events", headers=DEVICE).get_json()["events"]
    assert [e["action"] for e in first] == ["board", "exit"]
    assert first[0]["student_name"] == "سالم"
    assert first[1]["destination"] == "home"
    last_id = first[-1]["log_id"]
    assert client.get(f"/api/buses/1/events?after={last_id}", headers=DEVICE).get_json()["events"] == []
    fake.store["students"][1]["current_state"] = "at_home"
    client.post("/api/attendance", headers=DEVICE, json={"bus_id": 1, "fingerprint_id": 13, "action": "board"})
    newer = client.get(f"/api/buses/1/events?after={last_id}", headers=DEVICE).get_json()["events"]
    assert len(newer) == 1 and newer[0]["student_name"] == "ليلى"


def test_events_require_device_key(client, fake):
    assert client.get("/api/buses/1/events").status_code == 401
