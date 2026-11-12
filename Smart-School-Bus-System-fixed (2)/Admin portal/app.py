import os
import secrets
from collections import Counter
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, session
from flask_session import Session
from supabase import create_client
from werkzeug.security import check_password_hash

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
try:
    TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "UTC"))
except Exception:
    app.logger.warning("Invalid APP_TIMEZONE, falling back to UTC")
    TIMEZONE = ZoneInfo("UTC")

STUDENT_STATUSES = ("active", "inactive")
TRIP_STATUSES = ("idle", "on_route", "finished")


# ---------- CSRF ----------
@app.context_processor
def inject_csrf_token():
    def csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)
        return session["_csrf_token"]
    return {"csrf_token": csrf_token}


@app.before_request
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
    return supabase.table(table)


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
    clash = db("students").select("student_id").eq("fingerprint_id", fingerprint_id).execute().data
    if any(r["student_id"] != student_id for r in clash):
        return None, "رقم البصمة مستخدم لطالب آخر."
    return {"name": name, "fingerprint_id": fingerprint_id, "parent_phone": phone,
            "bus_id": bus_id, "status": status}, None


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


@app.route("/login", methods=["GET", "POST"])
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


@app.route("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------- dashboard ----------
@app.route("/")
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
@app.route("/students")
@login_required
def students():
    q = request.args.get("q", "").strip()
    query = db("students").select("*")
    if q:
        query = query.ilike("name", f"%{q}%")
    rows = query.order("student_id").execute().data
    return render_template("students.html", students=rows, buses=bus_map(), q=q)


@app.route("/students/new", methods=["GET", "POST"])
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
                app.logger.exception("insert student failed")
                error = "تعذّر حفظ الطالب. حاول مرة أخرى."
        flash(error, "error")
        return render_template("student_form.html", student=request.form.to_dict(), buses=buses)
    return render_template("student_form.html", student={"status": "active"}, buses=buses)


@app.route("/students/<int:student_id>")
@login_required
def student_detail(student_id):
    student = get_or_404("students", "student_id", student_id)
    bus = bus_map().get(student["bus_id"])
    logs = (db("attendance_logs").select("*").eq("student_id", student_id)
            .order("timestamp", desc=True).limit(50).execute().data)
    return render_template("student_detail.html", student=student, bus=bus, logs=logs)


@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
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
                app.logger.exception("update student failed")
                error = "تعذّر حفظ التعديلات. حاول مرة أخرى."
        flash(error, "error")
        student = {**student, **request.form.to_dict()}
    return render_template("student_form.html", student=student, buses=buses)


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    get_or_404("students", "student_id", student_id)
    try:
        db("students").delete().eq("student_id", student_id).execute()
        flash("تم حذف الطالب.", "success")
    except Exception:
        app.logger.exception("delete student failed")
        flash("تعذّر حذف الطالب. قد توجد سجلات حضور مرتبطة به.", "error")
        return redirect(f"/students/{student_id}")
    return redirect("/students")


# ---------- drivers / buses ----------
@app.route("/drivers")
@login_required
def drivers():
    buses = list(bus_map().values())
    counts = Counter(s["bus_id"] for s in db("students").select("bus_id").execute().data)
    return render_template("drivers.html", buses=buses, counts=counts)


@app.route("/drivers/new", methods=["GET", "POST"])
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
                app.logger.exception("insert bus failed")
                error = "تعذّر الحفظ. حاول مرة أخرى."
        flash(error, "error")
        return render_template("driver_form.html", bus=request.form.to_dict())
    return render_template("driver_form.html", bus={"trip_status": "idle"})


@app.route("/drivers/<int:bus_id>/edit", methods=["GET", "POST"])
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
                app.logger.exception("update bus failed")
                error = "تعذّر حفظ التعديلات. حاول مرة أخرى."
        flash(error, "error")
        bus = {**bus, **request.form.to_dict()}
    return render_template("driver_form.html", bus=bus)


@app.route("/drivers/<int:bus_id>/delete", methods=["POST"])
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
        app.logger.exception("delete bus failed")
        flash("تعذّر حذف الحافلة.", "error")
    return redirect("/drivers")


# ---------- attendance ----------
@app.route("/attendance")
@login_required
def attendance():
    logs = db("attendance_logs").select("*").order("timestamp", desc=True).limit(200).execute().data
    names = {s["student_id"]: s["name"] for s in db("students").select("student_id,name").execute().data}
    return render_template("attendance.html", logs=logs, names=names)


if __name__ == "__main__":
    app.run(debug=True)
