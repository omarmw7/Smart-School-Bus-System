"""قارئ البصمة R307 عبر مكتبة pyfingerprint (يعمل على الرازبري فقط).

رقم البصمة اللي يرجعه الحساس هو نفس fingerprint_id المحفوظ لكل طالب في لوحة الإدارة.
"""
import time

SENSOR_TIMEOUT_NOTE = "تأكد من توصيل الحساس وأن المنفذ صحيح (مثلاً /dev/ttyUSB0)."


class FingerprintReader:
    def __init__(self, port="/dev/ttyUSB0", baud=57600, password=0x00000000):
        from pyfingerprint.pyfingerprint import PyFingerprint  # استيراد متأخر: ما يلزم إلا على الرازبري
        try:
            self.sensor = PyFingerprint(port, baud, 0xFFFFFFFF, password)
        except Exception as exc:
            raise RuntimeError(f"تعذّر فتح الحساس: {exc}. {SENSOR_TIMEOUT_NOTE}") from exc
        if not self.sensor.verifyPassword():
            raise RuntimeError("كلمة مرور الحساس غير صحيحة.")

    def wait_for_match(self):
        """ينتظر إصبعاً على الحساس. يرجّع رقم البصمة المسجّلة، أو None إذا الإصبع غير معروف."""
        while not self.sensor.readImage():
            time.sleep(0.1)
        self.sensor.convertImage(0x01)
        position, _score = self.sensor.searchTemplate()
        return position if position >= 0 else None

    def wait_for_finger_removed(self):
        """ينتظر رفع الإصبع، حتى لا تُحسب اللمسة الواحدة مرتين."""
        while self.sensor.readImage():
            time.sleep(0.1)

    def enroll(self, position):
        """يسجّل بصمة جديدة في الموقع المحدد (يستبدل أي بصمة قديمة هناك)."""
        print("ضع الإصبع على الحساس...", flush=True)
        while not self.sensor.readImage():
            time.sleep(0.1)
        self.sensor.convertImage(0x01)
        print("ارفع الإصبع...", flush=True)
        self.wait_for_finger_removed()
        print("ضع نفس الإصبع مرة ثانية...", flush=True)
        while not self.sensor.readImage():
            time.sleep(0.1)
        self.sensor.convertImage(0x02)
        if self.sensor.compareCharacteristics() == 0:
            raise RuntimeError("البصمتان مختلفتان. أعد المحاولة.")
        self.sensor.createTemplate()
        self.sensor.storeTemplate(position)
        return position

    def template_count(self):
        return self.sensor.getTemplateCount()
