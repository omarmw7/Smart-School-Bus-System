"""تسجيل صعود ونزول الطلاب (بصمة) وتحديث حالتهم."""
from flask import Blueprint, current_app, jsonify

from auth import require_device_key
from config import ACTIONS, STATE_AT_HOME, STATE_AT_SCHOOL, STATE_ON_BUS
from extensions import first_row, get_supabase
from notifications import create_notification, local_time
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
        db.table("students").select("student_id,name,bus_id,current_state").eq(column, value).limit(1).execute()
    )
    if student is None:
        raise ApiError("الطالب غير موجود.", 404, "student_not_found")
    return student


@bp.post("/attendance")
@require_device_key
def record_attendance():
    data = json_body()
    # auto: الجهاز يرسل البصمة فقط، والسيرفر يحدد الإجراء من حالة الطالب
    requested_action = get_choice(data, "action", ACTIONS + ("auto",), required=False, default="auto")
    requested_destination = get_choice(data, "destination", ("school", "home"),
                                       required=False, default=None)
    bus_id = get_int(data, "bus_id", minimum=1)
    when = get_timestamp(data)

    db = get_supabase()
    student = _find_student(db, data)
    bus = first_row(
        db.table("buses").select("bus_id,current_lat,current_lng,trip_status,trip_direction").eq("bus_id", bus_id).limit(1).execute()
    )
    if bus is None:
        raise ApiError(f"الحافلة رقم {bus_id} غير موجودة.", 404, "bus_not_found")

    if requested_action == "auto":
        # إذا الطالب على الحافلة فهو ينزل، وإلا فهو يصعد
        action = "exit" if student["current_state"] == STATE_ON_BUS else "board"
    else:
        action = requested_action
    if action == "exit":
        # الوجهة: المعطاة صراحة، وإلا حسب اتجاه الرحلة (عودة = البيت، غير ذلك = المدرسة)
        destination = requested_destination or (
            "home" if bus.get("trip_direction") == "to_home" else "school")
    else:
        destination = None

    # منع التسجيل المزدوج الناتج عن لمس البصمة مرتين
    last = first_row(
        db.table("attendance_logs").select("action,timestamp")
        .eq("student_id", student["student_id"]).order("timestamp", desc=True).limit(1).execute()
    )
    if last and last["action"] == action:
        elapsed = (when - parse_db_time(last["timestamp"])).total_seconds()
        if 0 <= elapsed < current_app.config["ATTENDANCE_DEBOUNCE_SECONDS"]:
            return jsonify(ok=True, duplicate=True, student_name=student["name"]), 200

    # الحالة الحالية للطالب ووقت آخر تغيير لها
    status_row = first_row(
        db.table("students").select("current_state,state_updated_at")
        .eq("student_id", student["student_id"]).limit(1).execute()
    )
    current_state = status_row["current_state"] if status_row else STATE_AT_HOME
    state_updated = (parse_db_time(status_row["state_updated_at"])
                     if status_row and status_row.get("state_updated_at") else None)

    # الحدث المتأخر (وصل بعد انقطاع الإنترنت) لا يغيّر الحالة إذا كانت هناك حالة أحدث
    is_newest = state_updated is None or when >= state_updated
    warnings = []

    if is_newest and action == "board" and current_state == STATE_ON_BUS:
        raise ApiError("الطالب على الحافلة بالفعل.", 409, "invalid_sequence")
    if is_newest and action == "exit" and current_state != STATE_ON_BUS:
        # لا نرفض النزول: الواقع أهم من السجل، لكن نلفت النظر إلى أن الصعود غير مسجّل
        warnings.append("لم يُسجَّل صعود سابق لهذا الطالب.")

    if student["bus_id"] != bus_id:
        warnings.append("الطالب مسجّل على حافلة أخرى.")

    # الموقع المسجّل مع الحدث هو آخر موقع معروف للباص
    db.table("attendance_logs").insert({
        "student_id": student["student_id"],
        "bus_id": bus_id,
        "action": action,
        "location_lat": bus.get("current_lat"),
        "location_lng": bus.get("current_lng"),
        "destination": destination if action == "exit" else None,
        "timestamp": when.isoformat(),
    }).execute()

    if not is_newest:
        warnings.append("حدث متأخر: لم يُغيّر الحالة الحالية للطالب.")
        new_state = current_state
    else:
        if action == "board":
            new_state = STATE_ON_BUS
        else:
            new_state = STATE_AT_HOME if destination == "home" else STATE_AT_SCHOOL
        db.table("students").update({
            "current_state": new_state,
            "state_updated_at": when.isoformat(),
        }).eq("student_id", student["student_id"]).execute()

    # بداية الرحلة: أول صعود يشغّل الرحلة إن لم تكن قيد التشغيل
    # نهاية الرحلة: آخر نزول (لا يوجد أحد على الحافلة بعد الآن)
    trip_finished = False
    if is_newest and action == "board" and bus.get("trip_status") != "on_route":
        # إذا الراكب كان في المدرسة فالرحلة عودة للبيت، وإلا فهي الرحلة الصباحية للمدرسة
        direction = "to_home" if current_state == STATE_AT_SCHOOL else "to_school"
        db.table("buses").update({"trip_status": "on_route", "trip_direction": direction}) \
            .eq("bus_id", bus_id).execute()
    if is_newest and action == "exit" and bus.get("trip_status") == "on_route":
        still_on_board = (
            db.table("students").select("student_id")
            .eq("bus_id", bus_id).eq("current_state", STATE_ON_BUS).limit(1).execute().data
        )
        if not still_on_board:
            db.table("buses").update({"trip_status": "finished"}).eq("bus_id", bus_id).execute()
            trip_finished = True
            create_notification(db, audience="admin", kind="trip_finished", bus_id=bus_id,
                                message=f"انتهت رحلة الحافلة {bus_id}: نزل جميع الطلاب.")

    # إشعار ولي الأمر بالصعود والنزول
    if is_newest:
        time_text = local_time(when)
        if action == "board" and current_state == STATE_AT_SCHOOL:
            text = f"{student['name']} ركب الحافلة {bus_id} من المدرسة الساعة {time_text}."
            kind = "boarded"
        elif action == "board":
            text = f"{student['name']} صعد الحافلة {bus_id} الساعة {time_text}."
            kind = "boarded"
        elif destination == "home":
            text = f"{student['name']} نزل من الحافلة عند البيت الساعة {time_text}."
            kind = "exited"
        else:
            text = f"{student['name']} وصل المدرسة ونزل من الحافلة الساعة {time_text}."
            kind = "exited"
        create_notification(db, audience="parent", kind=kind, message=text,
                            bus_id=bus_id, student_id=student["student_id"])

    response = {
        "ok": True,
        "student_id": student["student_id"],
        "student_name": student["name"],
        "action": action,
        "state": new_state,
        "recorded_at": when.isoformat(),
    }
    if trip_finished:
        response["trip_finished"] = True
    if warnings:
        response["warning"] = " ".join(warnings)
    return jsonify(response), 201
