"""المصادقة: مفتاح الأجهزة (Raspberry Pi) ورمز ولي الأمر."""
import hmac
from functools import wraps

from flask import current_app, g, request

from extensions import first_row, get_supabase
from utils import ApiError


def require_device_key(view):
    """يسمح فقط للأجهزة التي ترسل الهيدر X-API-Key الصحيح."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-API-Key", "")
        expected = current_app.config["DEVICE_API_KEY"]
        # المقارنة بزمن ثابت تمنع تخمين المفتاح من فروق الزمن
        if not hmac.compare_digest(provided.encode(), expected.encode()):
            raise ApiError("مفتاح الجهاز غير صالح.", 401, "invalid_api_key")
        return view(*args, **kwargs)

    return wrapper


def require_parent_token(view):
    """يحدد الطالب من الرمز السري في الهيدر X-Parent-Token ويضعه في g.student."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Parent-Token", "").strip()
        if not token:
            raise ApiError("رمز ولي الأمر مطلوب.", 401, "missing_token")
        student = first_row(
            get_supabase()
            .table("students")
            .select("student_id,name,bus_id,current_state,state_updated_at")
            .eq("parent_token", token)
            .limit(1)
            .execute()
        )
        if student is None:
            raise ApiError("رمز ولي الأمر غير صالح.", 401, "invalid_token")
        g.student = student
        return view(*args, **kwargs)

    return wrapper
