"""إعدادات التطبيق: كلها تُقرأ من متغيرات البيئة (على Render من تبويب Environment، محلياً من .env)."""
import os

from dotenv import load_dotenv

load_dotenv()

# --- قيم ثابتة يستخدمها السيرفر وأجهزة الباص ---
ACTIONS = ("board", "exit")                      # صعود / نزول
STATE_AT_HOME = "at_home"
STATE_ON_BUS = "on_bus"
STATE_AT_SCHOOL = "at_school"


class Config:

    # Supabase: مفتاح service_role / secret على السيرفر فقط
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

    # مفتاح مشترك يرسله Raspberry Pi في الهيدر X-API-Key
    DEVICE_API_KEY = os.getenv("DEVICE_API_KEY")

    # مفتاح توقيع جلسات لوحة الإدارة
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "UTC")

    # إحداثيات المدرسة (نقطة النهاية للمسار، ولاحقاً لتنبيه الاقتراب)
    SCHOOL_LAT = float(os.getenv("SCHOOL_LAT")) if os.getenv("SCHOOL_LAT") else None
    SCHOOL_LNG = float(os.getenv("SCHOOL_LNG")) if os.getenv("SCHOOL_LNG") else None

    REQUIRED = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "DEVICE_API_KEY", "SECRET_KEY")

    # حدود التحقق من البيانات
    MAX_SPEED_KMH = 200
    MAX_FUTURE_SKEW_SECONDS = 300       # أقصى فرق مقبول لوقت مستقبلي من الجهاز
    ATTENDANCE_DEBOUNCE_SECONDS = 10    # تجاهل نفس الحركة المكررة (بصمة مزدوجة)
    STALE_LOCATION_SECONDS = 120        # بعدها يُعتبر موقع الباص قديمًا
    MAX_ABSENCE_DAYS = 30
    # مفاتيح Web Push (VAPID): تُولَّد مرة واحدة، والخاص منها سري
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")

    # خدمة OSRM لرسم المسار على الطرق. فارغة = خطوط مستقيمة فقط.
    # العام مجاني للتجربة ولا يُنصح به للاستخدام الكثيف؛ للعرض النهائي استضف OSRM أو استخدم خدمة مدفوعة.
    OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")

    APPROACH_RADIUS_M = 300             # تنبيه ولي الأمر عند دخول الحافلة هذه المسافة من البيت
    APPROACH_COOLDOWN_SECONDS = 7200    # لا يكرر تنبيه "قربت من البيت" لنفس الطالب خلال ساعتين
