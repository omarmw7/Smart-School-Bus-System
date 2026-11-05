import streamlit as st

# Page Configuration
st.set_page_config(
    page_title="نظام الباص المدرسي الذكي", 
    page_icon="🚌", 
    layout="wide"
)

# Sidebar Navigation for Portals
st.sidebar.title("🚍 نظام الباص المدرسي")
st.sidebar.markdown("---")

portal = st.sidebar.selectbox(
    "اختر البوابة (Portal):", 
    ["اختر البوابة...", "🛡️ لوحة تحكم الإدارة (Admin Panel)", "🚌 شاشة السائق (Driver Dashboard)"]
)

st.sidebar.markdown("---")
st.sidebar.info("النظام مرتبط بقاعدة بيانات سحابية مركزية (Supabase) لتحديث الحالات لحظياً.")

# Routing logic based on selection
if portal == "🛡️ لوحة تحكم الإدارة (Admin Panel)":
    import admin_portal
    admin_portal.run()

elif portal == "🚌 شاشة السائق (Driver Dashboard)":
    import driver_portal
    driver_portal.run()

else:
    # Landing / Welcome Page
    st.title("Welcome to the Smart School Bus System 🏫🚌")
    st.markdown("""
    ### نظرة عامة على النظام:
    هذا التطبيق الموحد يخدم جهتين أساسيتين في منظومة النقل المدرسي:
    1. **لوحة تحكم الإدارة:** مخصصة لإدارة الطلاب، ربط أرقام البصمات (Fingerprint IDs)، مراقبة السجلات، والتتبع الحي للحافلات.
    2. **شاشة السائق:** مخصصة لمتابعة حالة الطلاب المتواجدين داخل الباص لحظياً وعدّدهم، مع نظام حماية نهائي لتفادي نسيان أي طالب.
    
    > **الرجاء اختيار البوابة المطلوبة من القائمة الجانبية للبدء.**
    """)
