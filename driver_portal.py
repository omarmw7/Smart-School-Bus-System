import streamlit as st
from supabase import create_client
import time

def run():
    # Database Connection
    URL = "YOUR_SUPABASE_URL"
    KEY = "YOUR_SUPABASE_ANON_KEY"
    supabase = create_client(URL, KEY)

    BUS_ID = 1  # Bus ID assigned to this specific driver session

    st.title(f"🚌 لوحة تحكم السائق - الحافلة رقم {BUS_ID}")
    st.markdown("---")

    # Fetch students assigned to this bus
    students_response = supabase.table("students").select("*").eq("bus_id", BUS_ID).execute()
    all_bus_students = students_response.data if students_response.data else []

    total_students = len(all_bus_students)
    in_bus_students = [s for s in all_bus_students if s['status'] == 'in_bus']
    count_inside = len(in_bus_students)

    # Metrics Display
    col1, col2 = st.columns(2)
    with col1:
        st.metric(label="إجمالي طلاب الباص", value=total_students)
    with col2:
        st.metric(label="الطلاب المتواجدون بالداخل حالياً", value=count_inside)

    st.markdown("### 📋 قائمة الطلاب المتواجدين في الباص الآن:")
    if in_bus_students:
        for s in in_bus_students:
            st.success(f"✅ **{s['name']}** (رقم البصمة: {s['fingerprint_id']}) - صعد الحافلة")
    else:
        st.info("لا يوجد طلاب داخل الحافلة حالياً.")

    st.markdown("---")

    # Trip completion & safety check
    st.subheader("🏁 إنهاء الرحلة والفحص النهائي")
    if st.button("تأكيد إفراغ الباص وإنهاء الرحلة", type="primary"):
        if count_inside == 0:
            st.success("🎉 ممتاز! تم التأكد من خلو الباص تماماً من الطلاب. الرحلة آمنة ومنتهية.")
            supabase.table("buses").update({"trip_status": "idle"}).eq("bus_id", BUS_ID).execute()
        else:
            st.error(f"⚠️ تنبيه خطير! لا يزال هناك ({count_inside}) طالب مسجلين داخل الباص! تفقد المقاعد الخلفية فوراً.")

    # Auto-refresh to get real-time fingerprint updates from database
    time.sleep(5)
    st.rerun()
