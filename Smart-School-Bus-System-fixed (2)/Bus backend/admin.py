"""لوحة الإدارة (Admin portal) كـ Blueprint داخل نفس تطبيق Flask.

المسارات في الجذر: /login ، / ، /students ، /drivers ، /attendance ...
"""
import logging
import math
import os
import secrets
from collections import Counter
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash

from extensions import get_supabase
from push import save_subscription

bp = Blueprint("admin", __name__)
log = logging.getLogger(__name__)

try:
    TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "UTC"))
except Exception:
    log.warning("Invalid APP_TIMEZONE, falling back to UTC")
    TIMEZONE = ZoneInfo("UTC")

STUDENT_STATUSES = ("active", "inactive")
TRIP_STATUSES = ("idle", "on_route", "finished")


# ---------- CSRF ----------
@bp.context_processor
def inject_csrf_token():
    def csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)
        return session["_csrf_token"]
    return {"csrf_token": csrf_token,
            "school_coords": [current_app.config.get("SCHOOL_LAT"), current_app.config.get("SCHOOL_LNG")]}


@bp.before_request
def verify_csrf_token():
    """كل طلب POST يجب أن يحمل csrf_token المطابق لجلسة المستخدم."""
    if request.method != "POST":
        return
    expected = session.get("_csrf_token", "")
    sent = request.form.get("csrf_token", "")
    if not expected or not secrets.compare_digest(sent, expected):
        abort(400, description="انتهت صلاحية الصفحة. حدّثها وأعد المحاولة.")


# ---------- helpers ----------
def db(table):
    return get_supabase().table(table)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


def get_or_404(table, key, value):
    rows = db(table).select("*").eq(key, value).limit(1).execute().data
    if not rows:
        abort(404)
    return rows[0]


def bus_map():
    return {b["bus_id"]: b for b in db("buses").select("*").order("bus_id").execute().data}


def validate_student(form, student_id=None):
    name = form.get("name", "").strip()
    phone = form.get("parent_phone", "").strip()
    status = form.get("status", "active")
    try:
        fingerprint_id = int(form.get("fingerprint_id", ""))
        bus_id = int(form.get("bus_id", ""))
    except ValueError:
        return None, "رقم البصمة ورقم الحافلة يجب أن يكونا أرقامًا."
    if not name or not phone:
        return None, "الاسم ورقم هاتف ولي الأمر مطلوبان."
    if status not in STUDENT_STATUSES:
        status = "active"
    if bus_id not in bus_map():
        return None, "الحافلة المختارة غير موجودة."
    home_lat, home_lng = None, None
    lat_raw, lng_raw = form.get("home_lat", "").strip(), form.get("home_lng", "").strip()
    if lat_raw or lng_raw:  # موقع البيت اختياري، ولكن إذا أُدخل يجب أن يكون كاملاً وصحيحاً
        try:
            home_lat, home_lng = float(lat_raw), float(lng_raw)
        except ValueError:
            return None, "إحداثيات البيت يجب أن تكون أرقامًا."
        if not (math.isfinite(home_lat) and math.isfinite(home_lng)
                and -90 <= home_lat <= 90 and -180 <= home_lng <= 180):
            return None, "إحداثيات البيت خارج النطاق."
    clash = db("students").select("student_id").eq("fingerprint_id", fingerprint_id).execute().data
    if any(r["student_id"] != student_id for r in clash):
        return None, "رقم البصمة مستخدم لطالب آخر."
    return {"name": name, "fingerprint_id": fingerprint_id, "parent_phone": phone,
            "bus_id": bus_id, "status": status,
            "home_lat": home_lat, "home_lng": home_lng}, None


def validate_bus(form):
    driver = form.get("driver_name", "").strip()
    status = form.get("trip_status", "idle")
    if not driver:
        return None, "اسم السائق مطلوب."
    if status not in TRIP_STATUSES:
        status = "idle"
    return {"driver_name": driver, "trip_status": status}, None


# ---------- auth ----------
def login_helper(message, code=401):
    return render_template("login_failed.html", error=message), code


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email:
            return login_helper("يرجى إدخال البريد الإلكتروني.", 400)
        if not password:
            return login_helper("يرجى إدخال كلمة المرور.", 400)

        rows = db("admins").select("*").eq("email", email).limit(1).execute().data
        if not rows or not check_password_hash(rows[0]["password_hash"], password):
            return login_helper("البريد الإلكتروني أو كلمة المرور غير صحيحة.")

        session.clear()  # يبطل أي جلسة قديمة (ومعها رمز CSRF القديم)
        session["user_id"] = rows[0]["admin_id"]
        session["username"] = rows[0].get("name") or rows[0]["email"]
        return redirect("/")

    if session.get("user_id"):
        return redirect("/")
    return render_template("login.html")


@bp.route("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------- dashboard ----------
@bp.route("/")
@login_required
def index():
    buses = bus_map()
    recent = db("students").select("*").order("created_at", desc=True).limit(5).execute().data
    total_students = db("students").select("student_id", count="exact").limit(1).execute().count
    start_of_day = datetime.now(TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    logs_today = (db("attendance_logs").select("log_id", count="exact")
                  .gte("timestamp", start_of_day).limit(1).execute().count)
    stats = {
        "students": total_students,
        "buses": len(buses),
        "on_route": sum(1 for b in buses.values() if b["trip_status"] == "on_route"),
        "logs_today": logs_today,
    }
    return render_template("index.html", stats=stats, students=recent,
                           buses=buses, bus_list=list(buses.values()))


# ---------- students ----------
@bp.route("/students")
@login_required
def students():
    q = request.args.get("q", "").strip()
    query = db("students").select("*")
    if q:
        query = query.ilike("name", f"%{q}%")
    rows = query.order("student_id").execute().data
    return render_template("students.html", students=rows, buses=bus_map(), q=q)


@bp.route("/students/new", methods=["GET", "POST"])
@login_required
def new_student():
    buses = list(bus_map().values())
    if request.method == "POST":
        data, error = validate_student(request.form)
        if not error:
            try:
                db("students").insert(data).execute()
                flash("تمت إضافة الطالب.", "success")
                return redirect("/students")
            except Exception:
                current_app.logger.exception("insert student failed")
                error = "تعذّر حفظ الطالب. حاول مرة أخرى."
        flash(error, "error")
        return render_template("student_form.html", student=request.form.to_dict(), buses=buses)
    return render_template("student_form.html", student={"status": "active"}, buses=buses)


@bp.route("/students/<int:student_id>")
@login_required
def student_detail(student_id):
    student = get_or_404("students", "student_id", student_id)
    bus = bus_map().get(student["bus_id"])
    logs = (db("attendance_logs").select("*").eq("student_id", student_id)
            .order("timestamp", desc=True).limit(50).execute().data)
    return render_template("student_detail.html", student=student, bus=bus, logs=logs)


@bp.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def edit_student(student_id):
    student = get_or_404("students", "student_id", student_id)
    buses = list(bus_map().values())
    if request.method == "POST":
        data, error = validate_student(request.form, student_id)
        if not error:
            try:
                db("students").update(data).eq("student_id", student_id).execute()
                flash("تم حفظ التعديلات.", "success")
                return redirect(f"/students/{student_id}")
            except Exception:
                current_app.logger.exception("update student failed")
                error = "تعذّر حفظ التعديلات. حاول مرة أخرى."
        flash(error, "error")
        student = {**student, **request.form.to_dict()}
    return render_template("student_form.html", student=student, buses=buses)


@bp.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    get_or_404("students", "student_id", student_id)
    try:
        db("students").delete().eq("student_id", student_id).execute()
        flash("تم حذف الطالب.", "success")
    except Exception:
        current_app.logger.exception("delete student failed")
        flash("تعذّر حذف الطالب. قد توجد سجلات حضور مرتبطة به.", "error")
        return redirect(f"/students/{student_id}")
    return redirect("/students")


# ---------- drivers / buses ----------
@bp.route("/drivers")
@login_required
def drivers():
    buses = list(bus_map().values())
    counts = Counter(s["bus_id"] for s in db("students").select("bus_id").execute().data)
    return render_template("drivers.html", buses=buses, counts=counts)


@bp.route("/drivers/new", methods=["GET", "POST"])
@login_required
def new_driver():
    if request.method == "POST":
        data, error = validate_bus(request.form)
        if not error:
            try:
                db("buses").insert(data).execute()
                flash("تمت إضافة السائق والحافلة.", "success")
                return redirect("/drivers")
            except Exception:
                current_app.logger.exception("insert bus failed")
                error = "تعذّر الحفظ. حاول مرة أخرى."
        flash(error, "error")
        return render_template("driver_form.html", bus=request.form.to_dict())
    return render_template("driver_form.html", bus={"trip_status": "idle"})


@bp.route("/drivers/<int:bus_id>/edit", methods=["GET", "POST"])
@login_required
def edit_driver(bus_id):
    bus = get_or_404("buses", "bus_id", bus_id)
    if request.method == "POST":
        data, error = validate_bus(request.form)
        if not error:
            try:
                db("buses").update(data).eq("bus_id", bus_id).execute()
                flash("تم حفظ التعديلات.", "success")
                return redirect("/drivers")
            except Exception:
                current_app.logger.exception("update bus failed")
                error = "تعذّر حفظ التعديلات. حاول مرة أخرى."
        flash(error, "error")
        bus = {**bus, **request.form.to_dict()}
    return render_template("driver_form.html", bus=bus)


@bp.route("/drivers/<int:bus_id>/delete", methods=["POST"])
@login_required
def delete_driver(bus_id):
    get_or_404("buses", "bus_id", bus_id)
    assigned = db("students").select("student_id").eq("bus_id", bus_id).limit(1).execute().data
    if assigned:
        flash("لا يمكن حذف حافلة لديها طلاب. انقل الطلاب إلى حافلة أخرى أولًا.", "error")
        return redirect("/drivers")
    try:
        db("buses").delete().eq("bus_id", bus_id).execute()
        flash("تم حذف الحافلة.", "success")
    except Exception:
        current_app.logger.exception("delete bus failed")
        flash("تعذّر حذف الحافلة.", "error")
    return redirect("/drivers")


# ---------- attendance ----------
@bp.route("/attendance")
@login_required
def attendance():
    logs = db("attendance_logs").select("*").order("timestamp", desc=True).limit(200).execute().data
    names = {s["student_id"]: s["name"] for s in db("students").select("student_id,name").execute().data}
    return render_template("attendance.html", logs=logs, names=names)


# ---------- notifications ----------
def _admin_notifications(limit):
    return (db("notifications").select("notification_id,kind,message,bus_id,created_at")
            .eq("audience", "admin").order("notification_id", desc=True).limit(limit).execute().data)


@bp.route("/notifications")
@login_required
def notifications():
    return render_template("notifications.html", notes=_admin_notifications(100))


@bp.route("/notifications/push-subscribe", methods=["POST"])
@login_required
def notifications_push_subscribe():
    endpoint = request.form.get("endpoint", "")
    p256dh, auth = request.form.get("p256dh", ""), request.form.get("auth", "")
    if not endpoint.startswith("https://") or not p256dh or not auth:
        return jsonify(ok=False, message="اشتراك الإشعارات غير صالح."), 400
    save_subscription(get_supabase(), audience="admin", student_id=None,
                      subscription={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}})
    return jsonify(ok=True), 201


@bp.route("/notifications/feed")
@login_required
def notifications_feed():
    """يستدعيه المتصفح كل 20 ثانية لإظهار الإشعارات الجديدة."""
    return jsonify(ok=True, notifications=_admin_notifications(30))
