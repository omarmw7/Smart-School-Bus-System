import streamlit as st
from supabase import create_client
import pandas as pd

# ==========================================
# 1. SUPABASE DATABASE CONNECTION SETUP
# ==========================================
# Replace these placeholders with your actual Supabase Project URL and Anon Key
URL = "YOUR_SUPABASE_URL"
KEY = "YOUR_SUPABASE_ANON_KEY"
supabase = create_client(URL, KEY)

# Configure the Streamlit page layout and title
st.set_page_config(page_title="Admin Panel - School Bus System", layout="wide")
st.title("🛡️ Admin Panel - Smart School Bus System")

# Define the main navigation tabs for the admin dashboard
tab1, tab2, tab3, tab4 = st.tabs([
    "➕ Add New Student", 
    "📋 Manage Students", 
    "📊 Attendance Logs", 
    "📍 Live Tracking"
])

# ==========================================
# TAB 1: ADD NEW STUDENT & LINK FINGERPRINT
# ==========================================
with tab1:
    st.subheader("Register a New Student and Link Fingerprint ID")
    
    # Form container to handle input submission cleanly
    with st.form("add_student_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            name = st.text_input("Full Name")
            parent_phone = st.text_input("Parent Phone Number (for notifications)")
            
        with col2:
            # This ID corresponds directly to the template ID stored locally inside the bus fingerprint sensor
            fingerprint_id = st.number_input("Fingerprint ID", min_value=1, step=1)
            bus_id = st.number_input("Assigned Bus ID", min_value=1, step=1)
        
        submitted = st.form_submit_button("Save Student to Central Database")
        
        # Action triggered upon clicking the submit button
        if submitted:
            if name and parent_phone:
                student_data = {
                    "name": name,
                    "fingerprint_id": fingerprint_id,
                    "parent_phone": parent_phone,
                    "bus_id": bus_id,
                    "status": "out_of_bus"  # Default initial status
                }
                try:
                    # Insert record into the 'students' table on Supabase
                    supabase.table("students").insert(student_data).execute()
                    st.success(f"Student {name} successfully registered with Fingerprint ID ({fingerprint_id})!")
                except Exception as e:
                    st.error(f"Error: Fingerprint ID might already be assigned to another student. Details: {e}")
            else:
                st.warning("Please fill in all required fields.")

# ==========================================
# TAB 2: MANAGE STUDENTS (VIEW & DELETE)
# ==========================================
with tab2:
    st.subheader("📋 Registered Students Directory")
    
    # Fetch all student records from the database
    response = supabase.table("students").select("*").execute()
    students_list = response.data
    
    if students_list:
        for s in students_list:
            col_info, col_status, col_del = st.columns([3, 1, 1])
            
            with col_info:
                st.write(f"👤 **{s['name']}** | 🆔 Fingerprint: `{s['fingerprint_id']}` | 🚌 Bus: `{s['bus_id']}`")
                st.caption(f"Parent Phone: {s['parent_phone']}")
                
            with col_status:
                # Display real-time boarding status badge
                if s['status'] == 'in_bus':
                    st.success("In Bus")
                else:
                    st.info("Out of Bus")
                    
            with col_del:
                # Delete button with a unique key per student
                if st.button("Delete", key=f"del_{s['student_id']}"):
                    supabase.table("students").delete().eq("student_id", s['student_id']).execute()
                    st.success(f"Student {s['name']} deleted.")
                    st.rerun()  # Refresh the page to update the list
            st.divider()
    else:
        st.info("No students registered yet. Use the first tab to add students.")

# ==========================================
# TAB 3: ATTENDANCE LOGS & HISTORY
# ==========================================
with tab3:
    st.subheader("📊 Recent Check-In / Check-Out Activity")
    
    # Fetch recent logs joined with student names, ordered by timestamp descending
    logs_response = supabase.table("attendance_logs").select("*, students(name)").order("timestamp", desc=True).limit(20).execute()
    logs_data = logs_response.data
    
    if logs_data:
        formatted_logs = []
        for log in logs_data:
            # Handle nested student data safely
            student_name = log.get('students', {}).get('name', 'Unknown') if log.get('students') else 'Unknown'
            formatted_logs.append({
                "Student Name": student_name,
                "Bus ID": log['bus_id'],
                "Action": "Check-In (Boarded)" if log['action'] == 'CHECK_IN' else "Check-Out (Exited)",
                "Timestamp": log['timestamp']
            })
        # Render clean table using Pandas DataFrame
        st.dataframe(pd.DataFrame(formatted_logs), use_container_width=True)
    else:
        st.info("No attendance logs recorded yet.")

# ==========================================
# TAB 4: LIVE GPS TRACKING
# ==========================================
with tab4:
    st.subheader("📍 Real-Time School Bus Tracking Map")
    
    # Fetch current coordinates and bus states from the 'buses' table
    buses_data = supabase.table("buses").select("*").execute().data
    
    if buses_data:
        df = pd.DataFrame(buses_data)
        
        # Verify coordinate columns exist and drop rows with missing GPS data
        if 'current_lat' in df.columns and 'current_lng' in df.columns:
            map_df = df.dropna(subset=['current_lat', 'current_lng'])
            if not map_df.empty:
                # Streamlit map expects 'latitude' and 'longitude' column names
                map_df = map_df.rename(columns={'current_lat': 'latitude', 'current_lng': 'longitude'})
                st.map(map_df, latitude='latitude', longitude='longitude', zoom=12)
            else:
                st.warning("No active GPS coordinates available for buses right now.")
        
        st.markdown("### Connected Buses Status Table:")
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No buses registered in the 'buses' table.")
