"""عميل Raspberry Pi: يرسل GPS كل بضع ثوانٍ (في خيط منفصل) ويسجل صعود/نزول الطلاب بالبصمة.

المتغيرات (على الرازبري، لا في ملف مرفوع):
  DEVICE_API_KEY     (مطلوب)  نفس القيمة في Render
  SERVER_URL         عنوان السيرفر العام، مثال: https://smart-school-bus.onrender.com
  BUS_ID             رقم الحافلة (افتراضي 1)
  USE_FINGERPRINT    1 لتشغيل حساس R307، وغير ذلك يستخدم الكيبورد للتجربة
  FINGERPRINT_PORT   منفذ الحساس (افتراضي /dev/ttyUSB0)

التشغيل:   python3 pi_client.py
"""
import os
import sys
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SERVER_URL = os.getenv("SERVER_URL", "http://localhost:5000").rstrip("/")
API_KEY = os.getenv("DEVICE_API_KEY")
BUS_ID = int(os.getenv("BUS_ID", "1"))
GPS_INTERVAL = 5  # ثوانٍ
USE_FINGERPRINT = os.getenv("USE_FINGERPRINT") == "1"
FINGERPRINT_PORT = os.getenv("FINGERPRINT_PORT", "/dev/ttyUSB0")
VALID_ACTIONS = ("board", "exit")
VALID_DESTINATIONS = ("school", "home")

if not API_KEY:
    sys.exit("ضع DEVICE_API_KEY في متغيرات البيئة قبل التشغيل.")

session = requests.Session()
session.headers["X-API-Key"] = API_KEY
# إعادة المحاولة تلقائياً عند أخطاء الشبكة وأخطاء السيرفر المؤقتة
retry = HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=1, status_forcelist=(502, 503, 504), allowed_methods=("POST",)))
session.mount("https://", retry)
session.mount("http://", retry)


# ---------- GPS ----------
def read_gps():
    """اقرأ الموقع من وحدة GPS عبر gpsd."""
    import gpsd
    gpsd.connect()
    packet = gpsd.get_current()
    if packet.mode < 2:          # لا يوجد fix بعد
        return None
    return {"latitude": packet.lat, "longitude": packet.lon,
            "speed": packet.hspeed * 3.6}   # م/ث -> كم/ساعة


def send_gps(fix):
    payload = {"bus_id": BUS_ID, **fix}
    r = session.post(f"{SERVER_URL}/api/gps", json=payload, timeout=5)
    r.raise_for_status()


def gps_loop():
    while True:
        try:
            fix = read_gps()
            if fix:
                send_gps(fix)
        except requests.RequestException as exc:
            print("تعذّر إرسال GPS:", exc, flush=True)
        except Exception as exc:  # gpsd غير شغّال أو خطأ في القراءة: لا نوقف البرنامج
            print("تعذّرت قراءة GPS:", exc, flush=True)
        time.sleep(GPS_INTERVAL)


# ---------- البصمة ----------
_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        from fingerprint import FingerprintReader
        _reader = FingerprintReader(port=FINGERPRINT_PORT)
    return _reader


def read_fingerprint():
    """ينتظر لمسة بصمة ويرجّع (fingerprint_id, action, destination).

    action و destination = None يعني: السيرفر يحدد الصعود أو النزول من حالة الطالب.
    إذا الإصبع غير معروف يرجّع None.
    """
    if USE_FINGERPRINT:
        reader = _get_reader()
        position = reader.wait_for_match()
        reader.wait_for_finger_removed()
        if position is None:
            print("بصمة غير معروفة.", flush=True)
            return None
        return position, "auto", None

    # وضع التجربة بالكيبورد: "3" (تلقائي) أو "3 board" أو "3 exit home"
    line = input("بصمة> ").strip().split()
    if not line:
        return None
    try:
        fingerprint_id = int(line[0])
    except ValueError:
        print("اكتب رقم البصمة أولاً، مثال: 3")
        return None
    if len(line) == 1:
        return fingerprint_id, "auto", None
    action = line[1]
    destination = line[2] if len(line) > 2 else "school"
    if action not in VALID_ACTIONS or destination not in VALID_DESTINATIONS:
        print("الإجراء board أو exit، والوجهة school أو home")
        return None
    return fingerprint_id, action, destination


def send_attendance(fingerprint_id, action, destination=None):
    """يرسل لمسة بصمة للسيرفر. يرجّع الرد (فيه student_name) أو None عند الرفض."""
    payload = {"fingerprint_id": fingerprint_id, "bus_id": BUS_ID, "action": action}
    if destination:
        payload["destination"] = destination
    try:
        r = session.post(f"{SERVER_URL}/api/attendance", timeout=5, json=payload)
    except requests.RequestException as exc:
        print("تعذّر الإرسال، أعد اللمسة:", exc, flush=True)
        return None
    if not r.ok:
        try:
            print("رفض السيرفر:", r.json().get("message", r.text), flush=True)
        except ValueError:
            print("رفض السيرفر:", r.text, flush=True)
        return None
    return r.json()


# ---------- التشغيل ----------
if __name__ == "__main__":
    threading.Thread(target=gps_loop, daemon=True).start()
    print(f"الحافلة {BUS_ID} متصلة بـ {SERVER_URL}", flush=True)
    while True:
        try:
            tap = read_fingerprint()
        except (EOFError, KeyboardInterrupt):
            print("\nإيقاف.")
            break
        except Exception as exc:  # الحساس غير موصول: ننتظر ونحاول مرة ثانية
            print("خطأ في قراءة البصمة:", exc, flush=True)
            time.sleep(5)
            continue
        if not tap:
            continue
        fingerprint_id, action, destination = tap
        result = send_attendance(fingerprint_id, action, destination)
        if result:
            if result.get("duplicate"):
                print("لمسة مكررة، تم تجاهلها.", flush=True)
            else:
                print(f"تم: {result.get('student_name')} -> {result.get('state')}", flush=True)
                if result.get("warning"):
                    print("تنبيه:", result["warning"], flush=True)
