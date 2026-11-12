"""استقبال إحداثيات GPS من Raspberry Pi."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from auth import require_device_key
from extensions import first_row, get_supabase
from notifications import create_notification, recently_notified
from route_planner import haversine_m
from utils import ApiError, get_float, get_int, get_timestamp, json_body

bp = Blueprint("gps", __name__, url_prefix="/api")


@bp.post("/gps")
@require_device_key
def update_gps():
    data = json_body()
    bus_id = get_int(data, "bus_id", minimum=1)
    latitude = get_float(data, "latitude", minimum=-90, maximum=90)
    longitude = get_float(data, "longitude", minimum=-180, maximum=180)
    speed = get_float(data, "speed", minimum=0, maximum=current_app.config["MAX_SPEED_KMH"],
                      required=False, default=0.0)  # كم/ساعة
    recorded_at = get_timestamp(data).isoformat()

    db = get_supabase()
    # الموقع السابق قبل التحديث (نحتاجه لمعرفة إن كانت الحافلة دخلت منطقة المدرسة الآن)
    previous = first_row(
        db.table("buses").select("bus_id,current_lat,current_lng,trip_status,trip_direction")
        .eq("bus_id", bus_id).limit(1).execute()
    )
    if previous is None:
        raise ApiError(f"الحافلة رقم {bus_id} غير موجودة.", 404, "bus_not_found")
    previous = {  # نسخة ثابتة قبل التحديث
        "trip_status": previous.get("trip_status"),
        "trip_direction": previous.get("trip_direction"),
        "current_lat": previous.get("current_lat"),
        "current_lng": previous.get("current_lng"),
    }

    # 1) تحديث الموقع الحي في جدول buses (تقرؤه لوحة التحكم وبوابة الأهل)
    updated = (
        db.table("buses")
        .update({
            "current_lat": latitude,
            "current_lng": longitude,
            "current_speed": speed,
            "last_updated": recorded_at,
        })
        .eq("bus_id", bus_id)
        .execute()
        .data
    )
    if not updated:
        raise ApiError(f"الحافلة رقم {bus_id} غير موجودة.", 404, "bus_not_found")

    # 2) حفظ نقطة في سجل المسار bus_locations
    db.table("bus_locations").insert({
        "bus_id": bus_id,
        "latitude": latitude,
        "longitude": longitude,
        "speed": speed,
        "recorded_at": recorded_at,
    }).execute()

    _check_home_proximity(db, previous, bus_id, latitude, longitude)

    return jsonify(ok=True, bus_id=bus_id, recorded_at=recorded_at), 201


def _check_home_proximity(db, previous, bus_id, latitude, longitude):
    """تنبيه ولي الأمر لما الحافلة تدخل منطقة بيته (ضمن APPROACH_RADIUS_M):

    - الصباح (الرحلة للمدرسة): ينبّه الطالب الذي ما زال في البيت "جاهز للصعود".
    - العودة (الرحلة للبيت): ينبّه الطالب الذي على الحافلة "على وشك النزول".
    """
    status = previous.get("trip_status")
    if status == "finished":
        return
    if status == "on_route":
        direction = previous.get("trip_direction")
    else:  # idle: لم يبدأ أحد الصعود بعد، فهي الرحلة الصباحية
        direction = "to_school"
    if direction == "to_school":
        wanted_state, kind = "at_home", "near_home"
    elif direction == "to_home":
        wanted_state, kind = "on_bus", "arriving_home"
    else:
        return
    if previous.get("current_lat") is None or previous.get("current_lng") is None:
        return  # لا يوجد موقع سابق نقارن به
    radius = current_app.config["APPROACH_RADIUS_M"]
    cooldown = current_app.config["APPROACH_COOLDOWN_SECONDS"]

    today = datetime.now(timezone.utc).date().isoformat()
    absent_ids = {
        row["student_id"] for row in
        db.table("absence_requests").select("student_id")
        .in_("status", ["pending", "approved"])
        .lte("start_date", today).gte("end_date", today).execute().data
    }
    students = (
        db.table("students").select("student_id,name,home_lat,home_lng")
        .eq("bus_id", bus_id).eq("status", "active").eq("current_state", wanted_state)
        .execute().data
    )
    for student in students:
        if student["student_id"] in absent_ids:
            continue
        if student.get("home_lat") is None or student.get("home_lng") is None:
            continue
        home = (student["home_lat"], student["home_lng"])
        now_inside = haversine_m(latitude, longitude, *home) <= radius
        was_inside = haversine_m(previous["current_lat"], previous["current_lng"], *home) <= radius
        if not now_inside or was_inside:
            continue
        if recently_notified(db, audience="parent", kind=kind, student_id=student["student_id"],
                             seconds=cooldown):
            continue
        if kind == "near_home":
            text = f"الحافلة {bus_id} قربت من بيتكم. {student['name']} جاهز للصعود."
        else:
            text = f"الحافلة {bus_id} قربت من بيتكم. {student['name']} على وشك النزول."
        create_notification(db, audience="parent", kind=kind, bus_id=bus_id,
                            student_id=student["student_id"], message=text)
