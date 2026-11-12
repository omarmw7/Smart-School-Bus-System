"""مسار الحافلة الديناميكي (تقرؤه شاشة السائق عبر جهاز الرازبري)."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from auth import require_device_key
from extensions import get_supabase
from route_planner import compute_route

bp = Blueprint("buses", __name__, url_prefix="/api")


@bp.get("/buses/<int:bus_id>/route")
@require_device_key
def bus_route(bus_id):
    school = None
    lat, lng = current_app.config.get("SCHOOL_LAT"), current_app.config.get("SCHOOL_LNG")
    if lat is not None and lng is not None:
        school = (lat, lng)
    today = datetime.now(timezone.utc).date()
    return jsonify(ok=True, **compute_route(get_supabase(), bus_id, today, school,
                                            osrm_url=current_app.config.get("OSRM_URL")))


@bp.get("/buses/<int:bus_id>/events")
@require_device_key
def bus_events(bus_id):
    """حركات الصعود والنزول للحافلة. بدون after: آخر 20 حركة. مع after: الحركات الأحدث من هذا الرقم."""
    db = get_supabase()
    after = request.args.get("after", type=int)
    query = (db.table("attendance_logs")
             .select("log_id,student_id,action,destination,timestamp")
             .eq("bus_id", bus_id))
    if after is None:
        rows = query.order("log_id", desc=True).limit(20).execute().data
        rows.reverse()
    else:
        rows = query.gte("log_id", after + 1).order("log_id").limit(50).execute().data
    names = {s["student_id"]: s["name"]
             for s in db.table("students").select("student_id,name").execute().data}
    events = [{
        "log_id": r["log_id"],
        "student_name": names.get(r["student_id"], "طالب محذوف"),
        "action": r["action"],
        "destination": r.get("destination"),
        "timestamp": r["timestamp"],
    } for r in rows]
    return jsonify(ok=True, events=events)
