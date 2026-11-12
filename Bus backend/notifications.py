"""الإشعارات داخل الموقع: تُخزَّن في جدول notifications وتعرضها لوحة الإدارة وصفحة الأهل."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app

from push import send_to_subscribers
from utils import parse_db_time


def create_notification(db, *, audience, kind, message, bus_id=None, student_id=None):
    row = db.table("notifications").insert({
        "audience": audience,
        "kind": kind,
        "message": message,
        "bus_id": bus_id,
        "student_id": student_id,
    }).execute().data[0]
    send_to_subscribers(current_app._get_current_object(), row)


def recently_notified(db, *, audience, kind, seconds, bus_id=None, student_id=None):
    """هل أُرسل نفس النوع (لنفس الحافلة أو نفس الطالب) خلال المدة المحددة؟"""
    query = db.table("notifications").select("created_at").eq("audience", audience).eq("kind", kind)
    if bus_id is not None:
        query = query.eq("bus_id", bus_id)
    if student_id is not None:
        query = query.eq("student_id", student_id)
    rows = query.order("created_at", desc=True).limit(1).execute().data
    if not rows:
        return False
    age = (datetime.now(timezone.utc) - parse_db_time(rows[0]["created_at"])).total_seconds()
    return age < seconds


def local_time(when):
    """وقت محلي بصيغة HH:MM حسب APP_TIMEZONE (مثلاً الإمارات)."""
    try:
        zone = ZoneInfo(current_app.config.get("APP_TIMEZONE", "UTC"))
    except Exception:
        zone = ZoneInfo("UTC")
    return when.astimezone(zone).strftime("%H:%M")
