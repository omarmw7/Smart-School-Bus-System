"""استقبال إحداثيات GPS من Raspberry Pi."""
from flask import Blueprint, current_app, jsonify

from auth import require_device_key
from extensions import get_supabase
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

    return jsonify(ok=True, bus_id=bus_id, recorded_at=recorded_at), 201
