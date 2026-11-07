"""تسجيل صعود ونزول الطلاب (بصمة) وتحديث حالتهم."""
from flask import Blueprint, current_app, jsonify

from auth import require_device_key
from config import ACTIONS, STATE_AT_HOME, STATE_AT_SCHOOL, STATE_ON_BUS
from extensions import first_row, get_supabase
from utils import ApiError, get_choice, get_int, get_timestamp, json_body, parse_db_time

bp = Blueprint("attendance", __name__, url_prefix="/api")


def _find_student(db, data):
    """يبحث عن الطالب بـ student_id أو fingerprint_id."""
    if data.get("student_id") is not None:
        column, value = "student_id", get_int(data, "student_id", minimum=1)
    elif data.get("fingerprint_id") is not None:
        column, value = "fingerprint_id", get_int(data, "fingerprint_id", minimum=0)
    else:
        raise ApiError("أرسل student_id أو fingerprint_id.", 400, "missing_field")

    student = first_row(
        db.table("students").select("student_id,name,bus_id").eq(column, value).limit(1).execute()
    )
    if student is None:
        raise ApiError("الطالب غير موجود.", 404, "student_not_found")
    return student


@bp.post("/attendance")
@require_device_key
def record_attendance():
    data = json_body()
    action = get_choice(data, "action", ACTIONS)                 # board | exit
    destination = get_choice(data, "destination", ("school", "home"),
                             required=False, default="school")  # يُستخدم مع exit فقط
    bus_id = get_int(data, "bus_id", minimum=1)
    when = get_timestamp(data)

    db = get_supabase()
    student = _find_student(db, data)
    bus = first_row(
        db.table("buses").select("bus_id,current_lat,current_lng").eq("bus_id", bus_id).limit(1).execute()
    )
    if bus is None:
        raise ApiError(f"الحافلة رقم {bus_id} غير موجودة.", 404, "bus_not_found")

    # منع التسجيل المزدوج الناتج عن لمس البصمة مرتين
    last = first_row(
        db.table("attendance_logs").select("action,timestamp")
        .eq("student_id", student["student_id"]).order("timestamp", desc=True).limit(1).execute()
    )
    if last and last["action"] == action:
        elapsed = (when - parse_db_time(last["timestamp"])).total_seconds()
        if 0 <= elapsed < current_app.config["ATTENDANCE_DEBOUNCE_SECONDS"]:
            return jsonify(ok=True, duplicate=True, student_name=student["name"]), 200

    # الموقع المسجّل مع الحدث هو آخر موقع معروف للباص
    db.table("attendance_logs").insert({
        "student_id": student["student_id"],
        "bus_id": bus_id,
        "action": action,
        "location_lat": bus.get("current_lat"),
        "location_lng": bus.get("current_lng"),
        "timestamp": when.isoformat(),
    }).execute()

    if action == "board":
        new_state = STATE_ON_BUS
    else:
        new_state = STATE_AT_HOME if destination == "home" else STATE_AT_SCHOOL
    db.table("students").update({
        "current_state": new_state,
        "state_updated_at": when.isoformat(),
    }).eq("student_id", student["student_id"]).execute()

    response = {
        "ok": True,
        "student_id": student["student_id"],
        "student_name": student["name"],
        "action": action,
        "state": new_state,
        "recorded_at": when.isoformat(),
    }
    if student["bus_id"] != bus_id:
        response["warning"] = "الطالب مسجّل على حافلة أخرى."
    return jsonify(response), 201
