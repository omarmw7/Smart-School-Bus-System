"""حساب مسار الاستلام: ترتيب بيوت الطلاب المتوقعين للركوب، ثم المدرسة.

الترتيب والمسار على الطرق من OSRM (خدمة trip). إذا تعذّرت، نرجع للترتيب بالمسافة المستقيمة
والخطوط المستقيمة، والشاشة تعرض أي نوع معروض.
"""
import math
import time

import requests

from extensions import first_row
from utils import ApiError

EARTH_RADIUS_M = 6371000
OSRM_TIMEOUT_S = 4
OSRM_MAX_WAYPOINTS = 50
CACHE_TTL_S = 60
_trip_cache = {}  # المفتاح: النقاط مقرّبة لحوالي 100 متر -> (وقت الحفظ، النتيجة)


def haversine_m(lat1, lng1, lat2, lng2):
    """المسافة بالمتر بين نقطتين على سطح الأرض."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _path_length(points):
    return sum(haversine_m(*points[i], *points[i + 1]) for i in range(len(points) - 1))


def order_stops(start, stops, end):
    """ترتيب احتياطي بالمسافة المستقيمة: أقرب جار ثم تحسين 2-opt، بين بداية ونهاية ثابتتين."""
    remaining = list(stops)
    order = []
    current = start
    while remaining:
        nxt = min(remaining, key=lambda s: haversine_m(current[0], current[1], s["lat"], s["lng"]))
        remaining.remove(nxt)
        order.append(nxt)
        current = (nxt["lat"], nxt["lng"])

    def points(seq):
        return [start] + [(s["lat"], s["lng"]) for s in seq] + [end]

    improved = True
    while improved:
        improved = False
        best = _path_length(points(order))
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                candidate = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                length = _path_length(points(candidate))
                if length + 1e-6 < best:
                    order, best, improved = candidate, length, True
    return order


def road_trip(points, osrm_url):
    """يرتب النقاط على الطرق عبر OSRM.

    points: [البداية، المحطات بترتيبها الأصلي..., المدرسة].
    يرجّع None عند أي فشل، وإلا (order, geometry, legs):
      order:    فهارس المحطات (من 0) بالترتيب الجديد
      geometry: [[lat, lng], ...] خط المسار على الطرق
      legs:     مسافة كل مقطع بالمتر (عدد المقاطع = عدد النقاط - 1)
    """
    if not osrm_url or not (3 <= len(points) <= OSRM_MAX_WAYPOINTS):
        return None
    key = tuple((round(lat, 3), round(lng, 3)) for lat, lng in points)
    cached = _trip_cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
        return cached[1]

    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)  # OSRM يستخدم lng,lat
    result = None
    try:
        response = requests.get(
            f"{osrm_url.rstrip('/')}/trip/v1/driving/{coords}",
            params={"source": "first", "destination": "last", "roundtrip": "false",
                    "overview": "full", "geometries": "geojson"},
            timeout=OSRM_TIMEOUT_S,
        )
        body = response.json()
        if response.status_code == 200 and body.get("code") == "Ok":
            trip = body["trips"][0]
            waypoints = body["waypoints"]
            middle = sorted(range(1, len(points) - 1), key=lambda i: waypoints[i]["waypoint_index"])
            order = [i - 1 for i in middle]
            geometry = [[lat, lng] for lng, lat in trip["geometry"]["coordinates"]]
            legs = [round(leg["distance"]) for leg in trip["legs"]]
            if len(order) == len(points) - 2 and len(legs) == len(points) - 1:
                result = (order, geometry, legs)
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        result = None

    if len(_trip_cache) > 200:
        _trip_cache.clear()
    _trip_cache[key] = (time.monotonic(), result)
    return result


def compute_route(db, bus_id, today, school, osrm_url=None):
    """يرجّع المسار الحالي للحافلة. school = (lat, lng) أو None إن لم تُضبط.

    osrm_url: إن وُجد يُرتَّب المسار ويُرسم على الطرق، وإلا بالترتيب المستقيم.
    """
    if school is None:
        raise ApiError("إحداثيات المدرسة غير مضبوطة على السيرفر (SCHOOL_LAT, SCHOOL_LNG).",
                       503, "school_not_configured")

    bus = first_row(
        db.table("buses").select("bus_id,current_lat,current_lng,trip_status,trip_direction")
        .eq("bus_id", bus_id).limit(1).execute()
    )
    if bus is None:
        raise ApiError(f"الحافلة رقم {bus_id} غير موجودة.", 404, "bus_not_found")

    students = (
        db.table("students").select("student_id,name,home_lat,home_lng,current_state,status")
        .eq("bus_id", bus_id).eq("status", "active").execute().data
    )
    # من غاب أو لا يستخدم الباص اليوم (طلب معتمد أو قيد الانتظار) ما يدخل المسار
    excluded_ids = {
        row["student_id"] for row in
        db.table("absence_requests").select("student_id")
        .in_("status", ["pending", "approved"])
        .lte("start_date", today.isoformat()).gte("end_date", today.isoformat())
        .execute().data
    }

    stops, without_location = [], []
    for s in students:
        if s["current_state"] != "at_home" or s["student_id"] in excluded_ids:
            continue  # ركب الباص أو نزل أو غائب
        if s.get("home_lat") is None or s.get("home_lng") is None:
            without_location.append({"student_id": s["student_id"], "name": s["name"]})
            continue
        stops.append({"student_id": s["student_id"], "name": s["name"],
                      "lat": s["home_lat"], "lng": s["home_lng"]})

    # الانطلاق من موقع الحافلة الحالي، وإن لم يتوفر فمن المدرسة
    if bus.get("current_lat") is not None and bus.get("current_lng") is not None:
        start = (bus["current_lat"], bus["current_lng"])
    else:
        start = school

    # الترتيب: OSRM أولاً، وإن تعذّر فبالمسافة المستقيمة
    ordered = order_stops(start, stops, school)
    routing, geometry = "straight", None
    road = road_trip([start] + [(s["lat"], s["lng"]) for s in stops] + [school], osrm_url)
    if road:
        order, geometry, legs = road
        ordered = [stops[i] for i in order]
        routing = "road"
    else:
        points = [start] + [(s["lat"], s["lng"]) for s in ordered] + [school]
        legs = [round(haversine_m(*points[i], *points[i + 1])) for i in range(len(points) - 1)]
        geometry = None

    awaiting_state = "at_school" if bus.get("trip_direction") == "to_home" else "at_home"
    to_board = [s for s in students if s["current_state"] == awaiting_state
                and s["student_id"] not in excluded_ids]
    on_board = [s for s in students if s["current_state"] == "on_bus"]

    route_stops = [{
        "order": index + 1,
        "student_id": s["student_id"],
        "name": s["name"],
        "latitude": s["lat"],
        "longitude": s["lng"],
        "distance_from_previous_m": legs[index],
    } for index, s in enumerate(ordered)]

    return {
        "bus_id": bus_id,
        "trip_status": bus["trip_status"],
        "trip_direction": bus.get("trip_direction"),
        "routing": routing,
        "geometry": geometry,
        "counts": {"to_board": len(to_board), "on_bus": len(on_board)},
        "roster": [{"name": s["name"], "state": s["current_state"]} for s in students],
        "start": {"latitude": start[0], "longitude": start[1]},
        "stops": route_stops,
        "school": {"latitude": school[0], "longitude": school[1]},
        "distance_to_school_m": legs[-1],
        "total_distance_m": sum(legs),
        "without_location": without_location,
    }
