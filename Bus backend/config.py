"""إعدادات التطبيق: كلها تُقرأ من متغيرات البيئة (ملف .env)."""
import os

from dotenv import load_dotenv

load_dotenv()

# --- قيم ثابتة يستخدمها السيرفر وأجهزة الباص ---
ACTIONS = ("board", "exit")                      # صعود / نزول
STATE_AT_HOME = "at_home"
STATE_ON_BUS = "on_bus"
STATE_AT_SCHOOL = "at_school"


class Config:

    # Supabase: استخدم مفتاح service_role / secret على السيرفر فقط
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

    # مفتاح مشترك يرسله Raspberry Pi في الهيدر X-API-Key
    DEVICE_API_KEY = os.getenv("DEVICE_API_KEY")

    REQUIRED = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "DEVICE_API_KEY")

    # حدود التحقق من البيانات
    MAX_SPEED_KMH = 200
    MAX_FUTURE_SKEW_SECONDS = 300       # أقصى فرق مقبول لوقت مستقبلي من الجهاز
    ATTENDANCE_DEBOUNCE_SECONDS = 10    # تجاهل نفس الحركة المكررة (بصمة مزدوجة)
    STALE_LOCATION_SECONDS = 120        # بعدها يُعتبر موقع الباص قديمًا
    MAX_ABSENCE_DAYS = 30
