import streamlit as st
from supabase import create_client
import pandas as pd

def run():
    # Database Connection
    URL = "YOUR_SUPABASE_URL"
    KEY = "YOUR_SUPABASE_ANON_KEY"
    supabase = create_client(URL, KEY)

    st.title("🛡️ لوحة تحكم الإدارة - نظام الباص المدرسي الذكي")
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "➕ إضافة طالب جديد", 
        "📋 إدارة الطلاب", 
        "📊 سجل الحركات", 
        "📍 التتبع الحي (Live Tracking)"
    ])

    # --- TAB 1: ADD STUDENT ---
    with tab1:
        st.subheader("تسجيل طالب جديد وربطه برقم البصمة")
        with st.form("add_student_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("اسم الطالب بالكامل")
                parent_phone = st.text_input("رقم هاتف ولي الأمر")
            with col2:
                fingerprint_id = st.number_input("رقم بصمة الإصبع (Fingerprint ID)", min_value=1, step=1)
                bus_id = st.number_input("رقم الحافلة المخصصة", min_value=1, step=1)
            
            submitted = st.form_submit_button("حفظ الطالب في النظام")
            if submitted:
                if name and parent_phone:
                    data = {
                        "name": name,
                        "fingerprint_id": fingerprint_id,
                        "parent_phone": parent_phone,
                        "bus_id": bus_id,
                        "status": "out_of_bus"
                    }
                    try:
                        supabase.table("students").insert(data).execute()
                        st.success(f"تم تسجيل الطالب {name} وربطه بالبصمة ({fingerprint_id}) بنجاح!")
                    except Exception as e:
                        st.error(f"خطأ: ربما رقم البصمة مستخدم مسبقاً. التفاصيل: {e}")
                else:
                    st.warning("الرجاء تعبئة جميع الحقول المطلوبة.")

    # --- TAB 2: MANAGE STUDENTS ---
    with tab2:
        st.subheader("📋 قائمة الطلاب المسجلين")
        students_list = supabase.table("students").select("*").execute().data
        if students_list:
            for s in students_list:
                col_info, col_status, col_del = st.columns([3, 1, 1])
                with col_info:
                    st.write(f"👤 **{s['name']}** | 🆔 بصمة: `{s['fingerprint_id']}` | 🚌 باص: `{s['bus_id']}`")
                with col_status:
                    if s['status'] == 'in_bus':
                        st.success("داخل الباص")
                    else:
                        st.info("خارج الباص")
                with col_del:
                    if st.button("حذف", key=f"admin_del_{s['student_id']}"):
                        supabase.table("students").delete().eq("student_id", s['student_id']).execute()
                        st.success("تم الحذف.")
                        st.rerun()
                st.divider()
        else:
            st.info("لا يوجد طلاب مسجلين حتى الآن.")

    # --- TAB 3: ATTENDANCE LOGS ---
    with tab3:
        st.subheader("📊 أحدث حركات الصعود والنزول")
        logs_data = supabase.table("attendance_logs").select("*, students(name)").order("timestamp", desc=True).limit(20).execute().data
        if logs_data:
            formatted_logs = []
            for log in logs_data:
                student_name = log.get('students', {}).get('name', 'غير معروف') if log.get('students') else 'غير معروف'
                formatted_logs.append({
                    "اسم الطالب": student_name,
                    "رقم الباص": log['bus_id'],
                    "الحركة": "صعود (CHECK_IN)" if log['action'] == 'CHECK_IN' else "نزول (CHECK_OUT)",
                    "الوقت": log['timestamp']
                })
            st.dataframe(pd.DataFrame(formatted_logs), use_container_width=True)
        else:
            st.info("لا توجد سجلات حتى الآن.")

    # --- TAB 4: LIVE TRACKING ---
    with tab4:
        st.subheader("📍 خريطة التتبع الحي للحافلات المدرسية")
        buses_data = supabase.table("buses").select("*").execute().data
        if buses_data:
            df = pd.DataFrame(buses_data)
            if 'current_lat' in df.columns and 'current_lng' in df.columns:
                map_df = df.dropna(subset=['current_lat', 'current_lng'])
                if not map_df.empty:
                    map_df = map_df.rename(columns={'current_lat': 'latitude', 'current_lng': 'longitude'})
                    st.map(map_df, latitude='latitude', longitude='longitude', zoom=12)
                else:
                    st.warning("لا توجد إحداثيات GPS مسجلة للباصات حالياً.")
            st.dataframe(df, use_container_width=True)
        else:
            st.info("لا توجد حافلات مسجلة.")
