"""تسجيل بصمة طالب في الحساس. شغّله على الرازبري:

    python3 enroll_fingerprint.py 12        # يسجّل البصمة في الموقع 12 (= fingerprint_id للطالب)
    python3 enroll_fingerprint.py --count   # يعرض عدد البصمات المسجّلة

الرقم لازم يكون نفس fingerprint_id الموجود للطالب في لوحة الإدارة.
"""
import os
import sys

from fingerprint import FingerprintReader


def main():
    port = os.getenv("FINGERPRINT_PORT", "/dev/ttyUSB0")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    reader = FingerprintReader(port=port)
    if sys.argv[1] == "--count":
        print("عدد البصمات المسجّلة:", reader.template_count())
        return
    try:
        position = int(sys.argv[1])
    except ValueError:
        sys.exit("الرقم لازم يكون عدد صحيح، مثال: 12")
    if position < 0:
        sys.exit("الرقم لازم يكون 0 أو أكبر.")
    reader.enroll(position)
    print(f"تم تسجيل البصمة في الموقع {position}.")


if __name__ == "__main__":
    main()
