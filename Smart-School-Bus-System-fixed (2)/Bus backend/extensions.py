"""عميل Supabase المشترك (يُنشأ مرة واحدة عند أول استخدام)."""
from flask import current_app
from supabase import Client, create_client

_client = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            current_app.config["SUPABASE_URL"],
            current_app.config["SUPABASE_SERVICE_KEY"],
        )
    return _client


def first_row(response):
    """يرجع أول صف من نتيجة الاستعلام أو None إن لم يوجد."""
    return response.data[0] if response.data else None
