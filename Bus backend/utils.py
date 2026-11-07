"""أخطاء API ودوال التحقق من المدخلات."""
import math
from datetime import date, datetime, timezone

from flask import current_app, request


class ApiError(Exception):
    """خطأ متوقع يُحوَّل إلى رد JSON برمز حالة مناسب."""

    def __init__(self, message, status=400, code="bad_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("يجب إرسال جسم JSON صالح.", 400, "invalid_json")
    return data


def _missing(field):
    return ApiError(f"الحقل '{field}' مطلوب.", 400, "missing_field")


def _invalid(field, hint="قيمة غير صالحة"):
    return ApiError(f"الحقل '{field}': {hint}.", 400, "invalid_field")


def _number(data, field, kind, minimum, maximum, required, default):
    value = data.get(field)
    if value is None:
        if required:
            raise _missing(field)
        return default
    if isinstance(value, bool):
        raise _invalid(field, "يجب أن يكون رقمًا")
    try:
        converted = kind(value)
    except (TypeError, ValueError):
        raise _invalid(field, "يجب أن يكون رقمًا")
    if kind is int and isinstance(value, float) and not value.is_integer():
        raise _invalid(field, "يجب أن يكون عددًا صحيحًا")
    if kind is float and (math.isnan(converted) or math.isinf(converted)):
        raise _invalid(field, "يجب أن يكون رقمًا")
    if minimum is not None and converted < minimum:
        raise _invalid(field, f"أقل قيمة مسموحة {minimum}")
    if maximum is not None and converted > maximum:
        raise _invalid(field, f"أكبر قيمة مسموحة {maximum}")
    return converted


def get_int(data, field, *, minimum=None, maximum=None, required=True, default=None):
    return _number(data, field, int, minimum, maximum, required, default)


def get_float(data, field, *, minimum=None, maximum=None, required=True, default=None):
    return _number(data, field, float, minimum, maximum, required, default)


def get_choice(data, field, choices, *, required=True, default=None):
    value = data.get(field)
    if value is None:
        if required:
            raise _missing(field)
        return default
    if value not in choices:
        raise _invalid(field, "القيم المسموحة: " + "، ".join(choices))
    return value


def get_text(data, field, *, max_length=500, required=False):
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise _missing(field)
        return None
    if not isinstance(value, str):
        raise _invalid(field, "يجب أن يكون نصًا")
    value = value.strip()
    if len(value) > max_length:
        raise _invalid(field, f"الحد الأقصى {max_length} حرفًا")
    return value


def get_date(data, field, *, required=True, default=None):
    raw = data.get(field)
    if raw is None:
        if required:
            raise _missing(field)
        return default
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        raise _invalid(field, "يجب أن يكون تاريخًا بصيغة YYYY-MM-DD")


def parse_db_time(value):
    """يحوّل نصًا قادمًا من Supabase إلى datetime بتوقيت UTC."""
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def get_timestamp(data, field="timestamp"):
    """وقت الحدث: من الجهاز إن أرسله (مفيد عند انقطاع الإنترنت) وإلا وقت السيرفر."""
    now = datetime.now(timezone.utc)
    raw = data.get(field)
    if raw is None:
        return now
    if not isinstance(raw, str):
        raise _invalid(field, "يجب أن يكون وقتًا بصيغة ISO 8601")
    try:
        ts = parse_db_time(raw)
    except ValueError:
        raise _invalid(field, "يجب أن يكون وقتًا بصيغة ISO 8601")
    if (ts - now).total_seconds() > current_app.config["MAX_FUTURE_SKEW_SECONDS"]:
        raise _invalid(field, "الوقت المرسل في المستقبل")
    return ts
