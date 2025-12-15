# frontend.py (Complete Updated File)

import streamlit as st
import requests
import pandas as pd
from typing import Optional, List, Dict, Any
import os
import sqlite3

FASTAPI_URL = "http://127.0.0.1:8000"

st.set_page_config(layout="wide", page_title="UniReg System", initial_sidebar_state="expanded")

if "is_logged_in" not in st.session_state:
    st.session_state.update({"is_logged_in": False, "role": None, "username": None, "ai_chat": [], "page": "Dashboard"})

DATABASE_FILE = os.getenv("DATABASE_FILE", "university.db")

# --- Helper Functions ---

def logout():
    st.session_state.update({"is_logged_in": False, "role": None, "username": None, "ai_chat": [], "page": "Dashboard"})
    st.rerun()

def clean_schedule_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        st.session_state['current_credits'] = 0
        st.session_state['is_currently_enrolled'] = False
        return df

    # Replace all NaN values with a default value BEFORE casting integers
    df = df.fillna({
        'day': '0',
        'start_hr': 0, 
        'start_min': 0, 
        'end_hr': 0, 
        'end_min': 0,
        'building': 'TBD',
        'room_number': 'TBD'
    })

    # Now cast integer columns
    for col in ['start_hr', 'start_min', 'end_hr', 'end_min']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    
    # Generate Time and Location strings
    df['Time'] = df.apply(lambda row: f"{row['day']} {row['start_hr']:02d}:{row['start_min']:02d}-{row['end_hr']:02d}:{row['end_min']:02d}" if row['day'] != '0' else 'TBD', axis=1)
    df['Location'] = df.apply(lambda row: f"{row['building']} {row['room_number']}", axis=1)
    df['Grade'] = df['grade'].fillna('N/A')
    
    # Calculate current credits for Fall 2025 (only for courses without a final grade)
    current_sem_courses = df[(df['semester'] == 'Fall') & (df['year'] == 2025) & (df['grade'].isnull())]
    st.session_state['current_credits'] = current_sem_courses['credits'].sum()
    st.session_state['is_currently_enrolled'] = not current_sem_courses.empty

    display_cols = ['title', 'course_id', 'sec_id', 'semester', 'year', 'credits', 'Time', 'Location', 'Grade']
    display_names = ['Course Title', 'ID', 'Sec', 'Semester', 'Year', 'Credits', 'Schedule', 'Location', 'Grade']
    
    df_display = df[display_cols]
    df_display.columns = display_names
    return df_display


def update_password_form():
    st.subheader("🔒 Update Password")
    st.markdown("Use this form to change your password.")
    with st.form("update_password_form"):
        old_password = st.text_input("Old Password", type="password")
        new_password = st.text_input("New Password", type="password")
        confirm_password = st.text_input("Confirm New Password", type="password")
        submitted = st.form_submit_button("Change Password")
        
        if submitted:
            if new_password != confirm_password:
                st.error("New passwords do not match.")
            elif not old_password or not new_password:
                st.error("All password fields are required.")
            else:
                try:
                    res = requests.post(f"{FASTAPI_URL}/update_password",
                                        json={"username": st.session_state['username'],
                                              "old_password": old_password,
                                              "new_password": new_password}).json()
                    if res.get("status") == "success":
                        st.success(res.get("message"))
                    else:
                        st.error(res.get("detail") or res.get("message", "Password update failed."))
                except requests.exceptions.ConnectionError:
                    st.warning("Cannot connect to backend to update password.")


def create_sidebar_navigation():
    with st.sidebar:
        st.title("UniReg System")
        if st.session_state["is_logged_in"]:
            st.markdown(f"**User:** **`{st.session_state['username']}`**")
            st.markdown(f"**Role:** :blue[{st.session_state['role'].upper()}]")
            
            st.divider()
            if st.button("🔑 Change Password", use_container_width=True):
                st.session_state['page'] = 'UpdatePassword' 

            st.divider()
            if st.button("🚪 Logout", use_container_width=True):
                logout()
        else:
            st.markdown("Please **Login** or **Register** to access the system.")
            st.divider()
            return st.radio("Go to", ["Login", "Register"], key="initial_nav")
    return None


def ai_chat_interface():
    st.header("🧠 University AI Assistant (Gemini)")
    st.caption("Ask me anything about the university database. Powered by Google Gemini.")
    st.divider()
    
    # Display chat history
    for message in st.session_state["ai_chat"]:
        if message.get("user"):
            with st.chat_message("user"):
                st.write(message["user"])
        with st.chat_message("assistant"):
            st.markdown(message.get("ai", ""))
            if message.get("sql") and message["sql"] != "N/A":
                with st.expander("🛠️ Generated SQL Query"):
                    st.code(message["sql"], language="sql")
    
    # Handle new user input
    if user_input := st.chat_input("Enter your question here..."):
        st.session_state["ai_chat"].append({"user": user_input, "ai": "Processing...", "sql": "N/A"})
        st.rerun()
    
    # Process the 'Processing...' message
    if st.session_state["ai_chat"] and st.session_state["ai_chat"][-1]["ai"] == "Processing...":
        try:
            current_query = st.session_state["ai_chat"][-1]["user"]
            res = requests.post(f"{FASTAPI_URL}/ai_query",
                                json={"username": st.session_state["username"],
                                      "role": st.session_state["role"],
                                      "query": current_query}).json()
            
            st.session_state["ai_chat"][-1]["ai"] = res.get("response", "Error: No response from server.")
            st.session_state["ai_chat"][-1]["sql"] = res.get("sql_query", "N/A")
            
            if res.get("status") == "fail":
                 st.session_state["ai_chat"][-1]["ai"] = f"**Query Failed:** {res.get('response', 'Unknown error.')}"

            st.rerun()
        except requests.exceptions.ConnectionError:
            st.session_state["ai_chat"][-1]["ai"] = "Backend not ready or connection failed."
            st.session_state["ai_chat"][-1]["sql"] = "N/A"
            st.warning("Cannot connect to backend for AI query.")


def remove_user(username: str):
    """Handles the user removal process via the backend API."""
    if st.session_state['username'] == username:
        st.error("You cannot remove your own account!")
        return

    try:
        # Calls the general user removal endpoint
        res = requests.post(f"{FASTAPI_URL}/user/remove", json={"username": username}).json()
        if res.get("status") == "success":
            st.success(res.get("message"))
        else:
            st.error(res.get("detail") or res.get("message", "User removal failed."))
    except requests.exceptions.ConnectionError:
        st.warning("Cannot connect to backend to remove user.")
    except Exception as e:
        st.error(f"An unexpected error occurred during removal: {e}")
    st.rerun() # Rerun to refresh the data after a change


def drop_course_api(student_id: str, course_id: str, sec_id: str, semester: str, year: int):
    """Handles the course withdrawal process."""
    drop_data = {
        "student_id": student_id,
        "course_id": course_id,
        "sec_id": sec_id,
        "semester": semester,
        "year": year
    }
    try:
        res = requests.post(f"{FASTAPI_URL}/drop", json=drop_data).json()
        if res.get("status") == "success":
            st.toast(res.get("message"), icon="✅")
        else:
            st.error(res.get("detail") or res.get("message", "Course drop failed."))
    except requests.exceptions.ConnectionError:
        st.warning("Cannot connect to backend to drop course.")
    except Exception as e:
        st.error(f"An unexpected error occurred during drop: {e}")
    st.rerun() # Rerun to refresh the schedule


# --- Role Dashboards ---

def admin_page():
    st.header(f"👑 Admin Dashboard - {st.session_state['username']}")
    tab_summary, tab_approval, tab_courses, tab_students, tab_instructors, tab_all_users, tab_ai, tab_password = st.tabs([
        "📊 Summary", 
        "✅ Approvals", 
        "📚 Courses & Schedule",
        "🧑‍🎓 Students", 
        "🧑‍🏫 Instructors", 
        "👤 All Users", 
        "🤖 AI Assistant", 
        "🔒 Update Password"
    ])

    # Fetch data safely
    try:
        user_res = requests.get(f"{FASTAPI_URL}/users").json()
        student_data = requests.get(f"{FASTAPI_URL}/data/students").json()
        instructor_data = requests.get(f"{FASTAPI_URL}/data/instructors").json()
        summary_data = requests.get(f"{FASTAPI_URL}/data/summary").json()
        all_courses = requests.get(f"{FASTAPI_URL}/data/courses").json()
        all_sections = requests.get(f"{FASTAPI_URL}/data/sections").json()
        all_instructors = requests.get(f"{FASTAPI_URL}/data/instructors").json()
    except requests.exceptions.ConnectionError:
        st.warning("Cannot connect to backend.")
        user_res, summary_data, student_data, instructor_data = [], {}, [], []
        all_courses, all_sections, all_instructors = [], [], []
    except Exception as e:
        st.error(f"Error fetching admin data: {e}")
        user_res, summary_data, student_data, instructor_data = [], {}, [], []
        all_courses, all_sections, all_instructors = [], [], []


    # --- Summary Tab ---
    with tab_summary:
        st.subheader("System Overview")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Students", summary_data.get('total_students', '...'))
        col2.metric("Teachers", summary_data.get('total_teachers', '...'))
        col3.metric("Courses Offered (Fall 2025)", summary_data.get('total_courses_offered', '...'))
        col4.metric("Pending Approvals", summary_data.get('pending_approvals', '...'))

    # --- Approvals Tab ---
    with tab_approval:
        st.subheader("Pending User Approvals")
        
        # Filter pending users (exclude admins)
        pending_users = [u for u in user_res if u.get('approved') == 0 and u.get('role') != 'admin']
        
        if pending_users:
            for user in pending_users:
                col1, col2, col3 = st.columns([3, 1, 1])
                
                # Username + role
                with col1:
                    st.write(f"**{user['username']}** :orange[{user['role']}]")
                
                # Approve button
                with col2:
                    if st.button(f"Approve", key=f"approve_{user['username']}"):
                        try:
                            r = requests.post(
                                f"{FASTAPI_URL}/approve", json={"username": user['username']}
                            ).json()
                            st.toast(r.get("message"), icon="✅")
                            st.rerun()
                        except requests.exceptions.ConnectionError:
                            st.warning("Cannot connect to backend to approve.")
                        except Exception as e:
                            st.error(f"Error during approval: {e}")
                
                # Reject button
                with col3:
                    if st.button(f"Reject", key=f"reject_{user['username']}"):
                        try:
                            r = requests.post(
                                f"{FASTAPI_URL}/reject", json={"username": user['username']}
                            ).json()
                            st.toast(r.get("message"), icon="⚠️")
                            st.rerun()
                        except requests.exceptions.ConnectionError:
                            st.warning("Cannot connect to backend to reject.")
                        except Exception as e:
                            st.error(f"Error during rejection: {e}")
        
        else:
            st.info("No pending users!")
        
    # --- Courses & Schedule Tab ---
    with tab_courses:
        st.subheader("University Course and Section Management (Fall 2025)")
        
        tab_course_list, tab_course_add, tab_section_add, tab_course_crud = st.tabs(["List Courses", "Add New Course", "Schedule New Section", "Update Course Details"])

        # List Courses Tab
        with tab_course_list:
            if all_courses:
                df_courses = pd.DataFrame(all_courses)
                st.markdown("##### All Courses in Catalog")
                st.dataframe(df_courses, use_container_width=True, hide_index=True)
            else:
                st.info("No courses in the catalog.")
            
            st.divider()
            st.markdown("##### Fall 2025 Scheduled Sections")
            
            # --- START OF DEFINITIVE FIX ---
            if all_sections and isinstance(all_sections, list) and all_sections[0] is not None:
                df_sections = pd.DataFrame(all_sections) # This is line 278, now protected
                # Combine teacher ID and name
                df_sections['Instructor'] = df_sections.apply(
                    lambda row: f"{row['teacher_name']} ({row['teacher_id']})" if row['teacher_name'] else 'TBD (Unassigned)', axis=1
                )
                
                # Format time_slot_id for display
                df_sections['Schedule ID'] = df_sections['time_slot_id'].fillna('(No Time Slot)')
                
                st.dataframe(df_sections[['course_id', 'title', 'sec_id', 'building', 'room_number', 'Schedule ID', 'capacity', 'Instructor']], 
                             use_container_width=True, hide_index=True)
            else:
                # If data is empty or malformed, display info message
                st.info("No sections scheduled for Fall 2025.")
        # Add New Course Tab (existing)
        # with tab_course_add:
        #     st.markdown("### Add Course to Catalog")
        #     with st.form("add_course_form"):
        #         col1, col2 = st.columns(2)
        #         course_id = col1.text_input("Course ID (e.g., CS-101)")
        #         title = col2.text_input("Title (e.g., Intro to Computer Science)")
                
        #         col3, col4 = st.columns(2)
        #         dept_name = col3.text_input("Department (e.g., CS, Physics) - Must Exist in DB", value="CS")
        #         credits = col4.number_input("Credits (1-4)", min_value=1, max_value=4, value=3)
                
        #         submitted = st.form_submit_button("Add Course")
        #         if submitted:
        #             try:
        #                 res = requests.post(f"{FASTAPI_URL}/admin/course/add", json={
        #                     "course_id": course_id, "title": title, "dept_name": dept_name, "credits": credits
        #                 }).json()
        #                 if res.get("status") == "success":
        #                     st.success(res.get("message"))
        #                     st.rerun()
        #                 else:
        #                     st.error(res.get("detail") or "Failed to add course.")
        #             except requests.exceptions.ConnectionError:
        #                 st.error("Cannot connect to backend.")
        with tab_course_add:
            st.markdown("### Add Course to Catalog")

            # Fetch Department List from Backend
            def get_departments():
                try:
                    res = requests.get(f"{FASTAPI_URL}/departments").json()
                    if res.get("status") == "success":
                        return res.get("departments", [])
                except:
                    return []


            dept_list = get_departments()
            if not dept_list:
                dept_list = ["No Departments Found"]

            with st.form("add_course_form"):
                col1, col2 = st.columns(2)
                course_id = col1.text_input("Course ID (e.g., CS-101)")
                title = col2.text_input("Title (e.g., Intro to Computer Science)")

                col3, col4 = st.columns(2)
                dept_name = col3.selectbox("Department", dept_list)
                credits = col4.number_input("Credits (1-4)", min_value=1, max_value=4, value=3)

                submitted = st.form_submit_button("Add Course")
                if submitted:
                    try:
                        res = requests.post(
                            f"{FASTAPI_URL}/admin/course/add",
                            json={
                                "course_id": course_id,
                                "title": title,
                                "dept_name": dept_name,
                                "credits": credits
                            }
                        ).json()

                        if res.get("status") == "success":
                            st.success(res.get("message"))
                            st.rerun()
                        else:
                            st.error(res.get("detail") or "Failed to add course.")

                    except requests.exceptions.ConnectionError:
                        st.error("Cannot connect to backend.")

        # Schedule New Section Tab (existing)
        with tab_section_add:
            st.markdown("### Schedule a New Section (Fall 2025)")
            instructor_ids = [i['ID']+'-'+i['name'] for i in all_instructors]
            conn = sqlite3.connect(DATABASE_FILE)
            rows = conn.execute("SELECT day, start_hr, start_min, end_hr, end_min FROM time_slot").fetchall()
            time_slot_ids = []
            for day, sh, sm, eh, em in rows:
                start_time = f"{sh:02d}:{sm:02d}"
                end_time = f"{eh:02d}:{em:02d}"
                time_slot_ids.append(f"{day} | {start_time} → {end_time}")
            # Fetch building names
            try:
                conn = sqlite3.connect(DATABASE_FILE)
                buildings = [row[0] for row in conn.execute("SELECT DISTINCT building FROM classroom").fetchall()]
            except:
                buildings = []

            # Function to fetch rooms for a selected building
            def get_rooms(building):
                try:
                    conn = sqlite3.connect(DATABASE_FILE)
                    return [row[0] for row in conn.execute(
                        "SELECT room_number FROM classroom WHERE building = ?", (building,)
                    ).fetchall()]
                except:
                    return []

            with st.form("add_section_form"):
                col1, col2 = st.columns(2)

                # COURSE ID SELECTOR
                available_course_ids = [c['course_id'] for c in all_courses]
                if not available_course_ids:
                    st.warning("Please add courses to the catalog first.")
                    course_id_select = col1.selectbox("Course ID", ["<None>"])
                else:
                    course_id_select = col1.selectbox("Course ID", available_course_ids)

                sec_id = col2.text_input("Section ID (e.g., 1)")

                # ----------------------------------------------------
                # BUILDING DROPDOWN
                # ----------------------------------------------------
                col3, col4 = st.columns(2)

                if buildings:
                    selected_building = col3.selectbox("Building", buildings)
                else:
                    selected_building = col3.selectbox("Building", ["<None>"])

                # ----------------------------------------------------
                # ROOM NUMBER DROPDOWN (filtered by building)
                # ----------------------------------------------------
                rooms_for_building = get_rooms(selected_building) if selected_building != "<None>" else []

                if rooms_for_building:
                    room_number = col4.selectbox("Room Number", rooms_for_building)
                else:
                    room_number = col4.selectbox("Room Number", ["<None>"])

                # ----------------------------------------------------
                # CAPACITY + TIME SLOT
                # ----------------------------------------------------
                col5, col6 = st.columns(2)
                capacity = col5.number_input("Capacity", min_value=1, value=30)
                time_slot_id = col6.selectbox("Time Slot ID", ["(TBD / Online)"] + time_slot_ids)

                teacher_id = st.selectbox("Assign Instructor (Optional)", ["(Unassigned)"] + instructor_ids)

                submitted = st.form_submit_button("Schedule Section")

                # SUBMISSION HANDLER
                if submitted and course_id_select != "<None>":
                    teacher_final = teacher_id if teacher_id != "(Unassigned)" else None
                    time_slot_final = time_slot_id if time_slot_id != "(TBD / Online)" else None
                    
                    section_data = {
                        "course_id": course_id_select,
                        "sec_id": sec_id,
                        "semester": "Fall",
                        "year": 2025,
                        "building": selected_building,
                        "room_number": room_number,
                        "capacity": capacity,
                        "time_slot_id": time_slot_final,
                        "teacher_id": teacher_final
                    }

                    try:
                        res = requests.post(f"{FASTAPI_URL}/admin/section/add", json=section_data).json()
                        
                        if res.get("status") == "success":
                            st.success(res.get("message"))
                            st.rerun()
                        else:
                            st.error(res.get("detail") or "Failed to schedule section.")
                            
                    except requests.exceptions.ConnectionError:
                        st.error("Cannot connect to backend.")
                    except Exception as e:
                        st.error(f"An unexpected error occurred: {e}")

                elif submitted:
                    st.warning("Please select a valid Course ID.")

        # NEW: Course Update/Delete Tab
        with tab_course_crud:
            st.markdown("### Update Existing Course")
            
            course_ids = [c['course_id'] for c in all_courses]
            if not course_ids:
                st.info("No courses available to modify.")
            else:
                selected_id = st.selectbox("Select Course ID to Modify", course_ids, key="course_crud_select")
                
                if selected_id:
                    current_course = next((c for c in all_courses if c['course_id'] == selected_id), {})
                    
                    st.divider()
                    st.markdown("##### Update Details")
                    with st.form("update_course_form"):
                        col1, col2 = st.columns(2)
                        upd_title = col1.text_input("Title", value=current_course.get('title'), key="upd_title")
                        upd_dept = col2.text_input("Department", value=current_course.get('dept_name'), key="upd_dept")
                        upd_credits = st.number_input("Credits (1-4)", min_value=1, max_value=4, value=current_course.get('credits'), key="upd_credits")
                        
                        update_submitted = st.form_submit_button("Update Course")
                        
                        if update_submitted:
                            try:
                                res = requests.post(f"{FASTAPI_URL}/admin/course/update", json={
                                    "course_id": selected_id, "title": upd_title, "dept_name": upd_dept, "credits": upd_credits
                                }).json()
                                if res.get("status") == "success":
                                    st.success(res.get("message"))
                                    st.rerun()
                                else:
                                    st.error(res.get("detail") or "Failed to update course.")
                            except requests.exceptions.ConnectionError:
                                st.error("Cannot connect to backend.")

                    st.divider()
                    # st.markdown("##### Delete Course")
                    # if st.button(f"⚠️ Delete {selected_id} Permanently", key="delete_course_btn", type="primary"):
                    #     try:
                    #         res = requests.post(f"{FASTAPI_URL}/admin/course/delete", json={"course_id": selected_id}).json()
                    #         if res.get("status") == "success":
                    #             st.success(res.get("message"))
                    #             st.rerun()
                    #         else:
                    #             st.error(res.get("detail") or "Failed to delete course.")
                    #     except requests.exceptions.ConnectionError:
                    #         st.error("Cannot connect to backend.")


    # --- Students Tab ---
    with tab_students:
        st.subheader("All Student Details")
        if student_data:
            df_students = pd.DataFrame(student_data).rename(columns={'ID': 'Username'})
            df_students['Status'] = df_students['approved'].apply(lambda x: '✅ Active' if x == 1 else '❌ Inactive')
            st.dataframe(df_students[['Username', 'name', 'dept_name', 'tot_cred', 'Status']], 
                         hide_index=True, use_container_width=True)
            
            st.divider()
            
            # NEW: Student Update/Delete Controls
            st.markdown("### Update Student Records")
            student_ids = df_students['Username'].tolist()
            selected_student_id = st.selectbox("Select Student ID to Modify", student_ids, key="student_crud_select")

            if selected_student_id:
                current_student = df_students[df_students['Username'] == selected_student_id].iloc[0].to_dict()
                
                st.markdown("##### Update Details")
                with st.form("update_student_form"):
                    col1, col2 = st.columns(2)
                    upd_name = col1.text_input("Name", value=current_student.get('name'), key="s_upd_name")
                    upd_dept = col2.text_input("Department", value=current_student.get('dept_name'), key="s_upd_dept")
                    upd_credits = st.number_input("Total Credits", min_value=0, value=current_student.get('tot_cred'), key="s_upd_credits")
                    
                    update_submitted = st.form_submit_button("Update Student")
                    
                    if update_submitted:
                        try:
                            res = requests.post(f"{FASTAPI_URL}/admin/student/update", json={
                                "id": selected_student_id, "name": upd_name, "dept_name": upd_dept, "tot_cred": upd_credits
                            }).json()
                            if res.get("status") == "success":
                                st.success(res.get("message"))
                                st.rerun()
                            else:
                                st.error(res.get("detail") or "Failed to update student.")
                        except requests.exceptions.ConnectionError:
                            st.error("Cannot connect to backend.")

                st.divider()
                # st.markdown("##### Delete Student")
                # if st.button(f"⚠️ Delete {selected_student_id} Permanently", key="delete_student_btn", type="primary"):
                #     try:
                #         res = requests.post(f"{FASTAPI_URL}/admin/student/delete", json={"username": selected_student_id}).json()
                #         if res.get("status") == "success":
                #             st.success(res.get("message"))
                #             st.rerun()
                #         else:
                #             st.error(res.get("detail") or "Failed to delete student.")
                #     except requests.exceptions.ConnectionError:
                #         st.error("Cannot connect to backend.")
        else:
             st.info("No student records found.")


    # --- Instructors Tab ---
    with tab_instructors:
        st.subheader("All Instructor Details")
        if instructor_data:
            df_instructors = pd.DataFrame(instructor_data).rename(columns={'ID': 'Username'})
            df_instructors['Status'] = df_instructors['approved'].apply(lambda x: '✅ Active' if x == 1 else '❌ Inactive')
            st.dataframe(df_instructors[['Username', 'name', 'dept_name', 'salary', 'Status']], 
                         hide_index=True, use_container_width=True)

            st.divider()
            
            # NEW: Instructor Update/Delete Controls
            st.markdown("### Update Instructor Records")
            instructor_ids = df_instructors['Username'].tolist()
            selected_instructor_id = st.selectbox("Select Instructor ID to Modify", instructor_ids, key="instructor_crud_select")

            if selected_instructor_id:
                current_instructor = df_instructors[df_instructors['Username'] == selected_instructor_id].iloc[0].to_dict()
                
                st.markdown("##### Update Details")
                with st.form("update_instructor_form"):
                    col1, col2 = st.columns(2)
                    upd_name = col1.text_input("Name", value=current_instructor.get('name'), key="i_upd_name")
                    upd_dept = col2.text_input("Department", value=current_instructor.get('dept_name'), key="i_upd_dept")
                    upd_salary = st.number_input("Salary", min_value=29000.0, value=current_instructor.get('salary'), key="i_upd_salary")
                    
                    update_submitted = st.form_submit_button("Update Instructor")
                    
                    if update_submitted:
                        try:
                            res = requests.post(f"{FASTAPI_URL}/admin/instructor/update", json={
                                "id": selected_instructor_id, "name": upd_name, "dept_name": upd_dept, "salary": upd_salary
                            }).json()
                            if res.get("status") == "success":
                                st.success(res.get("message"))
                                st.rerun()
                            else:
                                st.error(res.get("detail") or "Failed to update instructor.")
                        except requests.exceptions.ConnectionError:
                            st.error("Cannot connect to backend.")

                st.divider()
                # st.markdown("##### Delete Instructor")
                # if st.button(f"⚠️ Delete {selected_instructor_id} Permanently", key="delete_instructor_btn", type="primary"):
                #     try:
                #         res = requests.post(f"{FASTAPI_URL}/admin/instructor/delete", json={"username": selected_instructor_id}).json()
                #         if res.get("status") == "success":
                #             st.success(res.get("message"))
                #             st.rerun()
                #         else:
                #             st.error(res.get("detail") or "Failed to delete instructor.")
                #     except requests.exceptions.ConnectionError:
                #         st.error("Cannot connect to backend.")
        else:
            st.info("No instructor records found.")


    # --- All Users Tab ---
    with tab_all_users:
        st.subheader("All System Users (Login Credentials)")
        if user_res:
            df_users = pd.DataFrame(user_res).rename(columns={'username': 'Username'})
            df_users['Status'] = df_users['approved'].apply(lambda x: '✅ Approved' if x == 1 else '❌ Inactive')
            st.dataframe(df_users[['Username', 'role', 'Status']], hide_index=True, use_container_width=True)
        else:
            st.info("No login credentials found.")
            
    with tab_ai:
        ai_chat_interface()
        
    with tab_password:
        update_password_form()


def student_page():
    st.header(f"🧑‍🎓 Student Dashboard - {st.session_state['username']}")
    tab_info, tab_enroll, tab_ai, tab_password = st.tabs(["📋 My Info", "📝 Enroll Courses", "🤖 AI Assistant", "🔒 Update Password"])
    student_id = st.session_state["username"]

    with tab_info:
        info_res = {}
        course_res = []
        try:
            info_res = requests.get(f"{FASTAPI_URL}/student/{student_id}").json()
            course_res = requests.get(f"{FASTAPI_URL}/student/{student_id}/courses").json()
            
            # FIX: Conditional check for course_res before DataFrame creation
            if course_res:
                df = pd.DataFrame(course_res)
                df_display = clean_schedule_df(df) # This populates current_credits and prepares the display DF
            else:
                df_display = pd.DataFrame()
            
            if not isinstance(info_res, dict) or 'detail' in info_res:
                st.error(f"Error fetching student info: {info_res.get('detail', 'Student not found in DB.')}")
                return

            st.subheader("Academic Profile")
            col1, col2, col3 = st.columns(3)
            col1.metric("Name", info_res.get('name', 'N/A'))
            col2.metric("Department", info_res.get('dept_name', 'N/A'))
            col3.metric("Total Credits Earned", info_res.get('tot_cred', 0))

            st.divider()
            st.subheader("Course History and Current Schedule")

            if not df_display.empty:
                st.caption(f"Currently registered in **{st.session_state.get('current_credits', 0)}** credits for Fall 2025.")
                
                # Identify current courses (Fall 2025, no grade)
                current_courses = df[
                    (df['semester'] == 'Fall') & 
                    (df['year'] == 2025) & 
                    (df['grade'].isnull())
                ]
                
                # Display Current Courses with Drop Buttons
                if not current_courses.empty:
                    st.markdown("##### Current Enrollments (Fall 2025)")
                    for index, row in current_courses.iterrows():
                        # Use data from the full DataFrame (df) for the drop API call
                        col_info, col_btn = st.columns([5, 1])
                        with col_info:
                            time_str = f"{row['day']} {row['start_hr']:02d}:{row['start_min']:02d}-{row['end_hr']:02d}:{row['end_min']:02d}" if row['day'] != '0' else 'TBD'
                            location_str = f"{row['building']} {row['room_number']}"
                            st.write(f"**{row['title']}** ({row['course_id']}-{row['sec_id']}) | **{row['credits']}** credits | Schedule: **{time_str}** | Location: {location_str}")
                        with col_btn:
                            if st.button("Drop", key=f"drop_{row['course_id']}_{row['sec_id']}", type="secondary"):
                                drop_course_api(student_id, row['course_id'], row['sec_id'], row['semester'], row['year'])
                    st.divider()

                # Display Past Courses
                past_courses_display = df_display[df_display['Grade'] != 'N/A']
                if not past_courses_display.empty:
                    st.markdown("##### Completed Course History")
                    st.dataframe(past_courses_display, use_container_width=True, hide_index=True)
                elif current_courses.empty:
                     st.info("No course history or current enrollment found.")

            else:
                st.info("No course history found.")
                
        except requests.exceptions.ConnectionError:
            st.warning("Cannot connect to backend.")
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")

    with tab_enroll:
        st.subheader("Enroll in a Course (Fall 2025)")
        st.info(f"Credit Limit for Fall 2025: **12 credits**. Currently registered: **{st.session_state.get('current_credits', 0)}** credits.")
        
        with st.form("enrollment_form"):
            col1, col2 = st.columns(2)
            course_id = col1.text_input("Course ID (e.g., CS-101)")
            sec_id = col2.text_input("Section ID (e.g., 1)")
            
            semester_col, year_col = st.columns(2)
            semester = semester_col.selectbox("Semester", ("Fall", "Winter", "Spring", "Summer"), index=0)
            year = year_col.number_input("Year", min_value=2000, max_value=2100, value=2025)
            
            submitted = st.form_submit_button("Enroll")
            
            if submitted:
                enrollment_data = {
                    "student_id": student_id,
                    "course_id": course_id.strip(),
                    "sec_id": sec_id.strip(),
                    "semester": semester,
                    "year": year
                }
                
                try:
                    res = requests.post(f"{FASTAPI_URL}/enroll", json=enrollment_data).json()
                    
                    if res.get("status") == "success":
                        st.success(res.get("message"))
                        st.rerun()
                    else:
                        st.error(res.get("detail") or res.get("message", "Enrollment failed."))
                        
                except requests.exceptions.ConnectionError:
                    st.warning("Cannot connect to backend.")
                except Exception as e:
                    st.error(f"An error occurred during enrollment: {e}")

    with tab_ai:
        ai_chat_interface()

    with tab_password:
        update_password_form()


def teacher_page():
    st.header(f"🧑‍🏫 Teacher Dashboard - {st.session_state['username']}")
    tab_summary, tab_schedule, tab_ai, tab_password = st.tabs(
    ["📊 My Summary", "📅 My Schedule", "🤖 AI Assistant", "🔒 Update Password"]
)

    teacher_id = st.session_state["username"]

    with tab_summary:
        st.subheader("Fall 2025 Teaching Summary")
        summary_res = {}
        try:
            summary_res = requests.get(f"{FASTAPI_URL}/teacher/{teacher_id}/summary").json()
        except requests.exceptions.ConnectionError:
            st.warning("Cannot connect to backend.")

        col1, col2 = st.columns(2)
        col1.metric("Sections Taught", summary_res.get('sections_taught_fall_2025', '...'))
        col2.metric("Unique Students Taught", summary_res.get('total_students_taught_fall_2025', '...'))
        
        st.divider()
        st.info("Additional functionality (e.g., viewing class rosters, grading) would go here.")

    with tab_ai:
        ai_chat_interface()
        
    with tab_password:
        update_password_form()

    with tab_schedule:
         st.subheader("📅 My Teaching Schedule (Fall 2025)")
         try:
            sched = requests.get(f"{FASTAPI_URL}/teacher/{teacher_id}/schedule").json()
 
            if isinstance(sched, dict) and sched.get("detail"):
                st.error(sched["detail"])
            elif not sched:
                st.info("No sections assigned to you for Fall 2025 yet.")
            else:
                # Clean display
             import pandas as pd
             df = pd.DataFrame(sched)

            # Optional: drop time_slot_id if you don't want to show it
            # df = df.drop(columns=["time_slot_id"], errors="ignore")

            # Reorder columns
            desired_cols = [
                "day", "start_time", "end_time",
                "course_id", "sec_id", "title",
                "building", "room_number",
                "semester", "year"
            ]
            df = df[[c for c in desired_cols if c in df.columns]]

            st.dataframe(df, use_container_width=True)
            
         except requests.exceptions.ConnectionError:
                st.warning("Cannot connect to backend.")

# --- Authentication Pages ---

def login_page():
    st.title("User Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

        if submitted:
            try:
                res = requests.post(f"{FASTAPI_URL}/login", json={"username": username, "password": password}).json()
                
                if res.get("status") == "success":
                    st.session_state["is_logged_in"] = True
                    st.session_state["role"] = res["role"]
                    st.session_state["username"] = username
                    st.success(f"Login successful as {res['role'].upper()}!")
                    st.rerun()
                else:
                    st.error(res.get("message") or "Login failed.")
            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to the backend server. Please ensure the FastAPI server is running.")

def register_page():
    st.title("New User Registration")

    st.success("✅ Students can login immediately after registering.")
    st.warning("⏳ Instructors must wait for Admin approval before they can login.")

    # Role selector OUTSIDE the form so the page reruns and shows correct fields
    role = st.selectbox("Register As", ("student", "teacher"), index=0, key="reg_role")

    with st.form("register_form"):
        # Common fields
        username = st.text_input("Username")
        full_name = st.text_input("Full Name")

        col1, col2 = st.columns(2)
        email = col1.text_input("Email")
        phone = col2.text_input("Phone Number")

        col3, col4 = st.columns(2)
        city = col3.text_input("City")
        zip_code = col4.text_input("ZIP")

        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")

        st.markdown("---")
        st.subheader("Role Specific Details")

        # Role-specific fields
        major = None
        level_of_study = None
        ssn = None
        experience = None

        if role == "student":
            major = st.text_input("Major")
            level_of_study = st.selectbox("Grad / Undergrad", ("undergrad", "grad"), index=0)
        else:
            ssn = st.text_input("SSN")
            experience = st.number_input("Years of Experience", min_value=0, max_value=60, value=0, step=1)

        submitted = st.form_submit_button("Register")

        if submitted:
            # Basic validation
            if not username or not full_name or not email or not phone or not city or not zip_code:
                st.error("Please fill all required fields.")
                return
            if password != confirm_password:
                st.error("Passwords do not match.")
                return
            if len(password) < 6:
                st.error("Password must be at least 6 characters.")
                return

            if role == "student" and (not major or not level_of_study):
                st.error("Please provide Major and Grad/Undergrad.")
                return
            if role == "teacher" and (not ssn or experience is None):
                st.error("Please provide SSN and Years of Experience.")
                return

            payload = {
                "username": username.strip(),
                "full_name": full_name.strip(),
                "password": password,
                "email": email.strip(),
                "phone": phone.strip(),
                "city": city.strip(),
                "zip": zip_code.strip(),
                "role": role,
                "major": (major.strip() if isinstance(major, str) else None),
                "level_of_study": level_of_study,
                "ssn": (ssn.strip() if isinstance(ssn, str) else None),
                "experience": int(experience) if experience is not None else None,
            }

            try:
                res = requests.post(f"{FASTAPI_URL}/register", json=payload).json()
                if res.get("status") == "success":
                    st.success(res.get("message", "Registered."))
                else:
                    st.error(res.get("detail") or res.get("message") or "Registration failed.")
            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to the backend server.")


def update_password_page():

    st.header("🔒 Update Password")
    update_password_form()
    if st.button("⬅️ Back to Dashboard"):
        st.session_state['page'] = 'Dashboard'
        st.rerun()

# --- Main App Loop ---

def main_app_loop():
    initial_nav = create_sidebar_navigation()
    
    if st.session_state["is_logged_in"]:
        current_page = st.session_state.get('page', 'Dashboard')
        
        if current_page == 'UpdatePassword':
            update_password_page()
            return
            
        role = st.session_state["role"]
        if role == "admin":
            admin_page()
        elif role == "student":
            student_page()
        elif role == "teacher":
            teacher_page()
    else:
        if initial_nav == "Register":
            register_page()
        else:
            login_page()

if __name__ == "__main__":
    main_app_loop()