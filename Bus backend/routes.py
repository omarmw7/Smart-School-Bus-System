"""تسجيل مسارات (Blueprints) الخادم في تطبيق Flask."""
from attendance import bp as attendance_bp
from gps import bp as gps_bp
from parents import bp as parents_bp


def register_blueprints(app):
    for blueprint in (gps_bp, attendance_bp, parents_bp):
        app.register_blueprint(blueprint)
