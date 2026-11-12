"""اختبارات قارئ البصمة بحساس وهمي يحاكي واجهة pyfingerprint (بدون أجهزة)."""
import os
import sys
import types

os.environ.update(SUPABASE_URL="http://fake", SUPABASE_SERVICE_KEY="fake",
                  DEVICE_API_KEY="device-key", FLASK_SECRET_KEY="test-secret")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

import fingerprint  # noqa: E402


class FakeSensor:
    """يعطي الصور بالترتيب: كل readImage ترجع True عند وجود إصبع."""

    def __init__(self, fingers=(), matches=None, compare_score=50):
        self.fingers = list(fingers)     # قائمة قيم readImage
        self.matches = matches or {}     # الصورة -> رقم البصمة
        self.compare_score = compare_score
        self.stored = {}
        self.converted = []

    def verifyPassword(self):
        return True

    def readImage(self):
        if not self.fingers:  # نص السيناريو انتهى: نفشل بدل ما ننتظر للأبد
            raise AssertionError("الحساس الوهمي ما عنده قراءات إضافية")
        return self.fingers.pop(0)

    def convertImage(self, slot):
        self.converted.append(slot)

    def searchTemplate(self):
        return (self.matches.get("current", -1), 90)

    def compareCharacteristics(self):
        return self.compare_score

    def createTemplate(self):
        pass

    def storeTemplate(self, position):
        self.stored[position] = True
        return position

    def getTemplateCount(self):
        return len(self.stored)


@pytest.fixture()
def reader_factory(monkeypatch):
    holder = {}

    def make(sensor):
        module = types.ModuleType("pyfingerprint.pyfingerprint")
        module.PyFingerprint = lambda *a, **k: sensor
        pkg = types.ModuleType("pyfingerprint")
        monkeypatch.setitem(sys.modules, "pyfingerprint", pkg)
        monkeypatch.setitem(sys.modules, "pyfingerprint.pyfingerprint", module)
        monkeypatch.setattr(fingerprint.time, "sleep", lambda s: None)
        holder["sensor"] = sensor
        return fingerprint.FingerprintReader()

    return make


def test_wait_for_match_returns_registered_position(reader_factory):
    sensor = FakeSensor(fingers=[False, True], matches={"current": 12})
    reader = reader_factory(sensor)
    assert reader.wait_for_match() == 12
    assert sensor.converted == [0x01]


def test_unknown_finger_returns_none(reader_factory):
    sensor = FakeSensor(fingers=[True], matches={})
    assert reader_factory(sensor).wait_for_match() is None


def test_enroll_stores_template_when_two_scans_match(reader_factory):
    sensor = FakeSensor(fingers=[True, False, True], compare_score=80)
    reader = reader_factory(sensor)
    assert reader.enroll(7) == 7
    assert sensor.stored == {7: True}
    assert sensor.converted == [0x01, 0x02]


def test_enroll_refuses_mismatched_scans(reader_factory):
    sensor = FakeSensor(fingers=[True, False, True], compare_score=0)
    with pytest.raises(RuntimeError):
        reader_factory(sensor).enroll(7)
    assert sensor.stored == {}
