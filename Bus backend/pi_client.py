"""عميل Raspberry Pi: يرسل الـ GPS كل بضع ثوانٍ ويسجل صعود/نزول الطلاب.

المتغيرات: SERVER_URL, DEVICE_API_KEY, BUS_ID
التشغيل:   python pi_client.py
"""
import os
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SERVER_URL = os.getenv("SERVER_URL", "http://192.168.1.10:5000")
API_KEY = os.environ["DEVICE_API_KEY"]
BUS_ID = int(os.getenv("BUS_ID", "1"))
GPS_INTERVAL = 5  # ثوانٍ

session = requests.Session()
session.headers["X-API-Key"] = API_KEY
# إعادة المحاولة تلقائيًا عند أخطاء الشبكة وأخطاء السيرفر المؤقتة
session.mount("http://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=1, status_forcelist=(502, 503, 504), allowed_methods=("POST",))))


def read_gps():
    """اقرأ الموقع من وحدة GPS عبر gpsd. عدّل هذه الدالة حسب جهازك."""
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


def send_attendance(fingerprint_id, action, destination="school"):
    """action: board | exit ، destination: school | home (مع exit فقط)."""
    r = session.post(f"{SERVER_URL}/api/attendance", timeout=5, json={
        "fingerprint_id": fingerprint_id, "bus_id": BUS_ID,
        "action": action, "destination": destination})
    if not r.ok:
        print("رفض السيرفر:", r.json().get("message"))
        return None
    return r.json()   # يحتوي student_name لعرضه أو نطقه عند الصعود


if __name__ == "__main__":
    while True:
        try:
            fix = read_gps()
            if fix:
                send_gps(fix)
        except requests.RequestException as exc:
            print("تعذّر الإرسال:", exc)
        time.sleep(GPS_INTERVAL)
