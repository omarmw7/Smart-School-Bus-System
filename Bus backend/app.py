"""نقطة تشغيل السيرفر: python app.py  أو  gunicorn app:app  (على Render)

كل شي من نفس التطبيق:
  /api/gps, /api/attendance, /api/parents/...   -> الأجهزة وبوابة الأهل (API)
  /parent                                        -> صفحة ولي الأمر
  /login, /, /students, /drivers, /attendance     -> لوحة الإدارة
  /health                                        -> فحص الحالة
"""
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from admin import bp as admin_bp
from config import Config
from routes import register_blueprints
from utils import ApiError


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)

    missing = [key for key in config.REQUIRED if not app.config.get(key)]
    if missing:
        names = {"SECRET_KEY": "FLASK_SECRET_KEY"}  # اسم متغير البيئة الفعلي
        raise RuntimeError("متغيرات بيئة ناقصة: " + ", ".join(names.get(k, k) for k in missing))

    register_blueprints(app)
    app.register_blueprint(admin_bp)

    @app.get("/health")
    def health():
        return jsonify(ok=True)

    @app.get("/api/push/vapid-public-key")
    def vapid_public_key():
        return jsonify(public_key=app.config.get("VAPID_PUBLIC_KEY"))

    @app.get("/sw.js")
    def service_worker():
        """ملف الـ Service Worker يجب أن يكون في الجذر ليغطي كل الموقع."""
        response = app.send_static_file("sw.js")
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/driver")
    def driver_screen():
        """شاشة السائق (تعمل على شاشة الرازبري بوضع kiosk)."""
        return app.send_static_file("driver.html")

    @app.get("/parent")
    def parent_portal():
        """بوابة ولي الأمر (صفحة واحدة تستدعي /api/parents من نفس الخادم)."""
        return app.send_static_file("parent.html")

    def wants_json():
        return request.path.startswith("/api/")

    # أخطاء الـ API: JSON بنفس الشكل {ok, error, message}
    @app.errorhandler(ApiError)
    def handle_api_error(error):
        if not wants_json():
            return error.message, error.status
        return jsonify(ok=False, error=error.code, message=error.message), error.status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if not wants_json():
            return error.description, error.code
        code = error.name.lower().replace(" ", "_")
        return jsonify(ok=False, error=code, message=error.description), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        app.logger.exception("خطأ غير متوقع")
        if not wants_json():
            return "حدث خطأ غير متوقع.", 500
        return jsonify(ok=False, error="server_error", message="حدث خطأ غير متوقع."), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
