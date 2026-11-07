"""نقطة تشغيل السيرفر: python app.py  أو  flask --app app run"""
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from config import Config
from routes import register_blueprints
from utils import ApiError


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)

    missing = [key for key in config.REQUIRED if not app.config.get(key)]
    if missing:
        raise RuntimeError("متغيرات بيئة ناقصة في ملف .env: " + ", ".join(missing))

    register_blueprints(app)

    @app.get("/health")
    def health():
        return jsonify(ok=True)

    # كل الردود JSON بنفس الشكل: {ok, error, message}
    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(ok=False, error=error.code, message=error.message), error.status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        code = error.name.lower().replace(" ", "_")
        return jsonify(ok=False, error=code, message=error.description), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        app.logger.exception("خطأ غير متوقع")
        return jsonify(ok=False, error="server_error", message="حدث خطأ غير متوقع."), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
