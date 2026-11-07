#!/usr/bin/env bash
# أمثلة اختبار بـ curl. عدّل القيم الثلاث التالية:
SERVER=http://localhost:5000
KEY=put-a-long-random-key-here        # DEVICE_API_KEY
TOKEN=parent-token-from-students-table # عمود parent_token للطالب

# 1) إرسال موقع GPS من الباص
curl -X POST $SERVER/api/gps -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"bus_id": 1, "latitude": 25.2048, "longitude": 55.2708, "speed": 42.5}'

# 2) صعود طالب بالبصمة
curl -X POST $SERVER/api/attendance -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"fingerprint_id": 12, "bus_id": 1, "action": "board"}'

# 3) نزول طالب عند المنزل
curl -X POST $SERVER/api/attendance -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"fingerprint_id": 12, "bus_id": 1, "action": "exit", "destination": "home"}'

# 4) ولي الأمر: حالة الطالب وموقع الباص
curl $SERVER/api/parents/status -H "X-Parent-Token: $TOKEN"

# 5) ولي الأمر: طلب غياب
curl -X POST $SERVER/api/parents/absence-requests -H "X-Parent-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type": "absent", "start_date": "2026-11-10", "end_date": "2026-11-11", "reason": "مرض"}'

# 6) ولي الأمر: عرض الطلبات / إلغاء طلب
curl $SERVER/api/parents/absence-requests -H "X-Parent-Token: $TOKEN"
curl -X DELETE $SERVER/api/parents/absence-requests/1 -H "X-Parent-Token: $TOKEN"
