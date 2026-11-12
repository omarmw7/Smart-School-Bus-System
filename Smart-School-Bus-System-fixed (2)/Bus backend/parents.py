"""بوابة أولياء الأمور: حالة الطالب، موقع الباص، وطلبات الغياب."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, jsonify

from auth import require_parent_token
from extensions import first_row, get_supabase
from push import save_subscription
from utils import ApiError, get_choice, get_date, get_text, json_body, parse_db_time

bp = Blueprint("parents", __name__, url_prefix="/api/parents")

REQUEST_COLUMNS = "request_id,request_type,start_date,end_date,reason,status,created_at"


@bp.get("/status")
@require_parent_token
def child_status():
    """حالة الطالب الحالية + موقع حافلته + آخر حركة."""
    db = get_supabase()
    student = g.student

    bus = first_row(
        db.table("buses")
        .select("bus_id,driver_name,trip_status,current_lat,current_lng,current_speed,last_updated")
        .eq("bus_id", student["bus_id"]).limit(1).execute()
    )
    last_event = first_row(
        db.table("attendance_logs").select("action,bus_id,timestamp")
        .eq("student_id", student["student_id"]).order("timestamp", desc=True).limit(1).execute()
    )

    bus_info = None
    if bus:
        updated = parse_db_time(bus["last_updated"]) if bus.get("last_updated") else None
        age = (datetime.now(timezone.utc) - updated).total_seconds() if updated else None
        bus_info = {
            "bus_id": bus["bus_id"],
            "driver_name": bus["driver_name"],
            "trip_status": bus["trip_status"],
            "latitude": bus["current_lat"],
            "longitude": bus["current_lng"],
            "speed": bus["current_speed"],
            "last_updated": bus["last_updated"],
            # الواجهة تعرض تنبيهًا إذا كان الموقع قديمًا
            "is_stale": age is None or age > current_app.config["STALE_LOCATION_SECONDS"],
        }

    return jsonify(
        ok=True,
        student={
            "name": student["name"],
            "state": student["current_state"],
            "state_updated_at": student["state_updated_at"],
        },
        bus=bus_info,
        last_event=last_event,
    )


@bp.post("/absence-requests")
@require_parent_token
def create_absence_request():
    """طلب غياب (absent) أو عدم استخدام الباص (no_bus) ليوم أو عدة أيام."""
    data = json_body()
    request_type = get_choice(data, "type", ("absent", "no_bus"))
    start = get_date(data, "start_date")
    end = get_date(data, "end_date", required=False, default=start)
    reason = get_text(data, "reason", max_length=500)

    earliest = datetime.now(timezone.utc).date() - timedelta(days=1)  # هامش لفروق التوقيت
    if start < earliest:
        raise ApiError("لا يمكن تقديم طلب لتاريخ سابق.", 400, "invalid_field")
    if end < start:
        raise ApiError("تاريخ النهاية يجب ألا يسبق تاريخ البداية.", 400, "invalid_field")
    if (end - start).days > current_app.config["MAX_ABSENCE_DAYS"]:
        raise ApiError(f"أقصى مدة للطلب {current_app.config['MAX_ABSENCE_DAYS']} يومًا.", 400, "invalid_field")

    db = get_supabase()
    student_id = g.student["student_id"]

    # لا يُسمح بطلب يتداخل مع فترة طلب قائم (قيد الانتظار أو مقبول)
    overlap = first_row(
        db.table("absence_requests").select("request_id")
        .eq("student_id", student_id)
        .in_("status", ["pending", "approved"])
        .lte("start_date", end.isoformat())
        .gte("end_date", start.isoformat())
        .limit(1).execute()
    )
    if overlap:
        raise ApiError("يوجد طلب قائم يتداخل مع هذه الفترة.", 409, "duplicate_request")

    created = db.table("absence_requests").insert({
        "student_id": student_id,
        "request_type": request_type,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "reason": reason,
        "status": "pending",
    }).execute().data[0]
    return jsonify(ok=True, request=created), 201


@bp.get("/absence-requests")
@require_parent_token
def list_absence_requests():
    rows = (
        get_supabase().table("absence_requests").select(REQUEST_COLUMNS)
        .eq("student_id", g.student["student_id"]).order("created_at", desc=True).limit(50)
        .execute().data
    )
    return jsonify(ok=True, requests=rows)


@bp.post("/push-subscription")
@require_parent_token
def save_push_subscription():
    """يحفظ اشتراك إشعارات المتصفح لولي الأمر (مرتبط بطالبه فقط)."""
    data = json_body()
    sub = data.get("endpoint")
    keys = data.get("keys") or {}
    if not isinstance(sub, str) or not sub.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise ApiError("اشتراك الإشعارات غير صالح.", 400, "invalid_subscription")
    save_subscription(get_supabase(), audience="parent", student_id=g.student["student_id"],
                      subscription={"endpoint": sub, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}})
    return jsonify(ok=True), 201


@bp.get("/notifications")
@require_parent_token
def list_notifications():
    """آخر إشعارات الصعود والنزول لهذا الطالب فقط."""
    rows = (
        get_supabase().table("notifications").select("notification_id,kind,message,created_at")
        .eq("audience", "parent").eq("student_id", g.student["student_id"])
        .order("notification_id", desc=True).limit(30).execute().data
    )
    return jsonify(ok=True, notifications=rows)


@bp.delete("/absence-requests/<int:request_id>")
@require_parent_token
def cancel_absence_request(request_id):
    """إلغاء طلب لم تتم مراجعته بعد."""
    db = get_supabase()
    row = first_row(
        db.table("absence_requests").select("request_id,status")
        .eq("request_id", request_id).eq("student_id", g.student["student_id"]).limit(1).execute()
    )
    if row is None:
        raise ApiError("الطلب غير موجود.", 404, "request_not_found")
    if row["status"] != "pending":
        raise ApiError("لا يمكن إلغاء طلب تمت مراجعته.", 409, "not_cancellable")
    db.table("absence_requests").update({"status": "cancelled"}).eq("request_id", request_id).execute()
    return jsonify(ok=True, request_id=request_id, status="cancelled")
