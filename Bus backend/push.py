"""إشعارات المتصفح (Web Push): تحفظ الاشتراكات وترسل الإشعار حتى لو الصفحة مسكّرة.

يحتاج المفاتيح: VAPID_PUBLIC_KEY و VAPID_PRIVATE_KEY و VAPID_SUBJECT، ومكتبة pywebpush.
إذا لم تتوفر، الموقع يعمل كالمعتاد بدون إشعارات المتصفح.
"""
import json
import logging
import threading

from extensions import get_supabase

try:
    from pywebpush import WebPushException, webpush
except ImportError:  # المكتبة غير مثبتة: نتجاهل الإرسال فقط
    webpush = None

    class WebPushException(Exception):
        response = None

log = logging.getLogger(__name__)


def save_subscription(db, *, audience, student_id, subscription):
    """يحفظ اشتراك المتصفح (أو يحدّثه إذا كان موجوداً)."""
    endpoint = subscription["endpoint"]
    keys = subscription["keys"]
    row = {"audience": audience, "student_id": student_id, "endpoint": endpoint,
           "p256dh": keys["p256dh"], "auth": keys["auth"]}
    existing = db.table("push_subscriptions").select("subscription_id").eq("endpoint", endpoint).limit(1).execute().data
    if existing:
        db.table("push_subscriptions").update(row).eq("endpoint", endpoint).execute()
    else:
        db.table("push_subscriptions").insert(row).execute()


def send_to_subscribers(app, notification):
    """يرسل الإشعار لكل المشتركين المعنيين، في خيط منفصل حتى لا يتأخر الرد."""
    if webpush is None or not app.config.get("VAPID_PRIVATE_KEY"):
        return
    threading.Thread(target=_send, args=(app, dict(notification)), daemon=True).start()


def _send(app, notification):
    with app.app_context():
        db = get_supabase()
        query = (db.table("push_subscriptions")
                 .select("subscription_id,endpoint,p256dh,auth")
                 .eq("audience", notification["audience"]))
        if notification.get("student_id") is not None:
            query = query.eq("student_id", notification["student_id"])
        url = "/parent" if notification["audience"] == "parent" else "/notifications"
        payload = json.dumps({"title": "مسار", "body": notification["message"], "url": url},
                             ensure_ascii=False)
        for sub in query.execute().data:
            try:
                webpush(
                    subscription_info={"endpoint": sub["endpoint"],
                                       "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                    data=payload,
                    vapid_private_key=app.config["VAPID_PRIVATE_KEY"],
                    vapid_claims={"sub": app.config["VAPID_SUBJECT"]},
                    timeout=10,
                )
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):  # المتصفح ألغى الاشتراك
                    db.table("push_subscriptions").delete().eq("subscription_id", sub["subscription_id"]).execute()
                else:
                    log.warning("Web Push failed: %s", exc)
            except Exception:
                log.exception("Web Push error")
