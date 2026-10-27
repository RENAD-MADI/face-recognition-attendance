import streamlit as st
import pandas as pd
import datetime
import cv2
import numpy as np
import face_recognition
import os
import plotly.express as px
import pyttsx3
import json
import sqlite3
from datetime import datetime, date, time, timedelta
from threading import Thread
from werkzeug.utils import secure_filename

# Set Streamlit's configuration
st.set_page_config(
    page_title="Attendance Management System - Data Corp",
    page_icon="❤️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Constants and File Paths
THRESHOLD = 0.6
STUDENT_IMAGES_PATH = 'student_images'
DATABASE_FILE = 'attendance.db'

# Ensure directories exist
os.makedirs(STUDENT_IMAGES_PATH, exist_ok=True)

# Initialize Database
def initialize_database():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # Create employees table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        image_path TEXT
    )
    ''')

    # Create attendance table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_name TEXT NOT NULL,
        check_in_time TEXT,
        date TEXT NOT NULL,
        status TEXT
    )
    ''')

    # Create leave_requests table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS leave_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_name TEXT NOT NULL,
        reason TEXT,
        days INTEGER,
        status TEXT,
        approver TEXT
    )
    ''')

    # Create configurations table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS configurations (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')

    conn.commit()
    conn.close()

# Load Configuration
def load_config():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT key, value FROM configurations')
    rows = cursor.fetchall()
    config_data = {}
    if rows:
        for key, value in rows:
            config_data[key] = json.loads(value)
    else:
        # Set default configuration
        config_data = {
            'attendance_time': '09:00',
            'grace_period_minutes': 15,
            'absent_threshold_minutes': 60,
            'weekends': [5, 6],  # Saturday and Sunday
            'official_holidays': []  # List of dates in 'YYYY-MM-DD' format
        }
        save_config(config_data)
    conn.close()
    return config_data

def save_config(config_data):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    for key, value in config_data.items():
        cursor.execute('REPLACE INTO configurations (key, value) VALUES (?, ?)', (key, json.dumps(value)))
    conn.commit()
    conn.close()

# Load Employee Names
def load_employee_names():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM employees')
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

# Load Attendance Data from SQLite
def load_attendance_data():
    conn = sqlite3.connect(DATABASE_FILE)
    attendance_df = pd.read_sql_query('SELECT * FROM attendance', conn)
    conn.close()
    

    if attendance_df.empty:
        return pd.DataFrame(columns=["Employee", "Time", "Date", "Status"])
    else:
        # Standardize column names to lowercase for consistent processing
        attendance_df.columns = [col.lower() for col in attendance_df.columns]
        
        # Check if 'date' column exists
        if 'date' not in attendance_df.columns:
            st.error("The 'attendance' table does not contain a 'date' column.")
            return pd.DataFrame(columns=["Employee", "Time", "Date", "Status"])
        
        # Rename columns
        attendance_df.rename(columns={
            'employee_name': 'Employee',
            'check_in_time': 'Time',
            'date': 'Date',
            'status': 'Status'
        }, inplace=True)
        
        # Convert 'Date' and 'Time' columns to appropriate datetime types
        attendance_df['Date'] = pd.to_datetime(attendance_df['Date']).dt.date
        attendance_df['Time'] = pd.to_datetime(attendance_df['Time'], format='%H:%M', errors='coerce').dt.time
        
        # Process attendance data to set Status
        attendance_df = process_attendance_data(attendance_df)
        return attendance_df

def process_attendance_data(attendance_df):
    """Process attendance DataFrame to determine Status for each record,
    considering working hours settings like attendance time, grace period, 
    weekends, and holidays."""

    # Load configuration from session state
    config_data = st.session_state.config_data

    attendance_time = datetime.strptime(config_data['attendance_time'], '%H:%M').time()
    grace_period_minutes = config_data['grace_period_minutes']
    absent_threshold_minutes = config_data['absent_threshold_minutes']
    weekends = config_data['weekends']
    official_holidays = [
        datetime.strptime(date_str, '%Y-%m-%d').date()
        for date_str in config_data['official_holidays']
    ]

    # Get all employees
    all_employees = load_employee_names()

    if attendance_df.empty:
        # Return an empty DataFrame with the correct columns
        return pd.DataFrame(columns=["Employee", "Time", "Date", "Status"])
    
    # Ensure the Date column is treated as a date object
    attendance_df['Date'] = pd.to_datetime(attendance_df['Date']).dt.date

    # Process attendance for each employee on each date
    processed_records = []
    date_range = pd.date_range(start=attendance_df['Date'].min(), end=datetime.today().date()).date
    for date_obj in date_range:
        if date_obj.weekday() in weekends or date_obj in official_holidays:
            # Skip non-working days
            continue

        # Attendance records for this date
        day_records = attendance_df[attendance_df['Date'] == date_obj]
        present_employees = day_records['Employee'].tolist()

        for employee in all_employees:
            if employee in present_employees:
                record = day_records[day_records['Employee'] == employee].iloc[0]
                check_in_time = record['Time'] if pd.notna(record['Time']) else None
                manual_status = record.get('Status')

                if isinstance(manual_status, str) and manual_status:
                    # Status chosen by hand in the Daily Attendance tab wins over the computed one.
                    status = manual_status
                elif check_in_time is None:
                    status = 'Absent'
                else:
                    # Calculate lateness
                    attendance_datetime = datetime.combine(date_obj, attendance_time)
                    check_in_datetime = datetime.combine(date_obj, check_in_time)
                    minutes_late = (check_in_datetime - attendance_datetime).total_seconds() / 60

                    if minutes_late <= grace_period_minutes:
                        status = 'Present'
                    elif minutes_late <= absent_threshold_minutes:
                        status = 'Late'
                    else:
                        status = 'Absent'
            else:
                status = 'Absent'
                check_in_time = None

            # Append the record
            processed_records.append({
                'Employee': employee,
                'Time': check_in_time.strftime('%H:%M') if check_in_time else None,
                'Date': date_obj,
                'Status': status
            })

    # Convert processed records to a DataFrame with specified columns
    processed_df = pd.DataFrame(processed_records, columns=["Employee", "Time", "Date", "Status"])
    return processed_df


# Load Leave Data from SQLite
def load_leave_data():
    conn = sqlite3.connect(DATABASE_FILE)
    leave_df = pd.read_sql_query('SELECT * FROM leave_requests', conn)
    conn.close()
    return leave_df

# Save Leave Request to SQLite
def add_leave_request(employee, reason, days):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO leave_requests (employee_name, reason, days, status, approver) VALUES (?, ?, ?, ?, ?)',
                   (employee, reason, days, 'Pending', ''))
    conn.commit()
    conn.close()

# Approve Leave Request
def approve_leave(leave_id, approver):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE leave_requests SET status=?, approver=? WHERE id=?',
                   ('Approved', approver, leave_id))
    conn.commit()
    conn.close()

# Helper function to filter late attendance by date range
def filter_late_data(attendance_df, time_range):
    # Ensure 'Date' column is in datetime format
    attendance_df['Date'] = pd.to_datetime(attendance_df['Date'], errors='coerce')

    today = pd.Timestamp(datetime.today().date())

    if time_range == "Today":
        return attendance_df[attendance_df["Date"] == today]
    elif time_range == "This Month":
        # Filter by the current month and year
        return attendance_df[
            attendance_df["Date"].dt.to_period('M') == today.to_period('M')
        ]
    elif time_range == "Past 3 Months":
        start_date = today - pd.DateOffset(months=3)
        return attendance_df[
            (attendance_df["Date"] >= start_date) & (attendance_df["Date"] <= today)
        ]
    elif time_range == "Past 6 Months":
        start_date = today - pd.DateOffset(months=6)
        return attendance_df[
            (attendance_df["Date"] >= start_date) & (attendance_df["Date"] <= today)
        ]
    elif time_range == "This Year":
        start_date = today.replace(month=1, day=1)
        return attendance_df[
            (attendance_df["Date"] >= start_date) & (attendance_df["Date"] <= today)
        ]

# Face Recognition Helper Functions
def resize_image(img, scale_percent):
    width = int(img.shape[1] * scale_percent / 100)
    height = int(img.shape[0] * scale_percent / 100)
    return cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)

def load_student_images():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT name, image_path FROM employees')
    employees = cursor.fetchall()
    conn.close()
    images, names = [], []
    for name, image_path in employees:
        # Load image from image_path
        if os.path.exists(image_path):
            try:
                img = face_recognition.load_image_file(image_path)
                if img is not None:
                    images.append(img)
                    names.append(name)
                else:
                    st.warning(f"Failed to load image for {name}.")
            except Exception as e:
                st.warning(f"Could not open image for {name}: {e}")
        else:
            st.warning(f"Image file not found for {name} at {image_path}.")
    return images, names

def encode_images(images):
    encoded_images = []
    for img in images:
        try:
            if img.dtype != np.uint8:
                st.warning("Image type is not 8-bit. Skipping...")
                continue
            if len(img.shape) != 3 or img.shape[2] != 3:
                st.warning("Image is not RGB. Skipping...")
                continue
            resized_img = resize_image(img, 50)
            resized_img = np.ascontiguousarray(resized_img, dtype=np.uint8)
            encodings = face_recognition.face_encodings(resized_img)
            if encodings:
                encoded_images.append(encodings[0])
            else:
                st.warning("No face detected in one of the images.")
        except Exception as e:
            st.error(f"Error processing image: {e}")
    if not encoded_images:
        st.error("No faces were encoded. Please check the images in the 'student_images' directory.")
    return encoded_images

def mark_attendance(name):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime('%H:%M')
    # Check if the employee has already marked attendance for today
    cursor.execute('SELECT * FROM attendance WHERE employee_name=? AND date=?', (name, date_str))
    data = cursor.fetchone()
    if data is None:
        cursor.execute('INSERT INTO attendance (employee_name, check_in_time, date) VALUES (?, ?, ?)', (name, time_str, date_str))
        conn.commit()
        conn.close()
        Thread(target=greet_user, args=(name,)).start()
    else:
        conn.close()

def greet_user(name):
    """Use text-to-speech to greet the user."""
    engine = pyttsx3.init()
    engine.say(f'Welcome back, {name}')
    engine.runAndWait()
    engine.stop()

def start_video():
    """Capture video frames and perform face recognition."""
    if not st.session_state.encoded_images:
        st.error("No known face encodings. Please add users in the 'Add User' tab.")
        return

    video_capture = cv2.VideoCapture(0)
    frame_placeholder = st.empty()
    stop_button = st.button("Stop Attendance")

    while True:
        ret, frame = video_capture.read()
        if not ret or frame is None:
            st.error("Failed to access the camera or no frame captured.")
            break

        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
        rgb_small_frame = np.ascontiguousarray(rgb_small_frame, dtype=np.uint8)

        try:
            face_locations = face_recognition.face_locations(rgb_small_frame)
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)
        except Exception as e:
            st.error(f"Error during face detection: {e}")
            break

        for face_encoding, face_location in zip(face_encodings, face_locations):
            face_distances = face_recognition.face_distance(
                st.session_state.encoded_images, face_encoding)
            if len(face_distances) > 0:
                best_match_index = np.argmin(face_distances)
                matches = face_recognition.compare_faces(
                    [st.session_state.encoded_images[best_match_index]], face_encoding, tolerance=THRESHOLD)
                top, right, bottom, left = [v * 4 for v in face_location]

                if matches[0]:
                    name = st.session_state.student_names[best_match_index]
                    Thread(target=mark_attendance, args=(name,)).start()
                    color = (0, 255, 0)  # Green
                else:
                    name = "Unknown"
                    color = (0, 0, 255)  # Red

                # Draw rectangle and name on the original frame
                cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                cv2.putText(frame, name, (left + 6, bottom - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            else:
                st.warning("No known faces to compare with.")

        # Display the frame in Streamlit
        frame_placeholder.image(frame, channels="BGR")

        if stop_button:
            break

    video_capture.release()
    cv2.destroyAllWindows()

# Initialize Database and Session State
initialize_database()

if 'config_data' not in st.session_state:
    st.session_state.config_data = load_config()

if 'student_images' not in st.session_state:
    st.session_state.student_images, st.session_state.student_names = load_student_images()
    st.session_state.encoded_images = encode_images(st.session_state.student_images)

# Title
st.title("Attendance Management System - Data Corp")
st.write("Track and manage employee attendance efficiently.")

# Create Tabs
tabs = st.tabs([
    "Home", "Face Recognition Attendance", "Add User", "Daily Attendance", "Monthly Attendance",
    "Late Attendance", "Employee Dashboard",
    "Leave Requests", "Working Hours", "Reports"
])

# Home Tab
with tabs[0]:
    st.header("🏠 Home")
    st.write("Welcome to the Attendance Management System.")
    st.image(
        "https://st2.depositphotos.com/34031690/46736/v/450/depositphotos_467366440-stock-illustration-flat-isometric-vector-illustration-isolated.jpg", 
        width=600  # Set the width you prefer, e.g., 600 pixels
    )
    st.write("""
        This system allows you to take attendance using face recognition technology.
        You can also add new users to the system.
    """)

# Face Recognition Attendance Tab
with tabs[1]:
    st.header("📷 Face Recognition Attendance")
    st.write("Use this tab to take attendance using face recognition.")
    if st.button("Start Face Recognition Attendance"):
        start_video()

# Add User Tab
with tabs[2]:
    st.header("👥 Add User")
    st.write("Use this tab to add new users to the system.")

    # Add New User Section
    st.subheader("Add New User")
    new_username = st.text_input("New User Name", "")
    uploaded_image = st.file_uploader("Upload Image", type=["jpg", "jpeg", "png"])

    if st.button("Add User"):
        if new_username and uploaded_image:
            # secure_filename drops non-Latin characters (e.g. Arabic names), so fall back to a unique name.
            filename = secure_filename(f"{new_username}.jpg")
            if filename in ("", "jpg", ".jpg"):
                filename = f"user_{int(datetime.now().timestamp())}.jpg"
            image_path = os.path.join(STUDENT_IMAGES_PATH, filename)
            with open(image_path, "wb") as f:
                f.write(uploaded_image.getbuffer())
            # Insert employee into database
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            try:
                cursor.execute('INSERT INTO employees (name, image_path) VALUES (?, ?)', (new_username, image_path))
                conn.commit()
                conn.close()
                st.success(f"User {new_username} added successfully!")
                # Reload student data
                st.session_state.student_images, st.session_state.student_names = load_student_images()
                st.session_state.encoded_images = encode_images(st.session_state.student_images)
            except sqlite3.IntegrityError:
                conn.close()
                st.error(f"User {new_username} already exists.")
        else:
            st.error("Please enter a name and upload an image.")

# Daily Attendance Tab
with tabs[3]:
    st.header("📅 Daily Attendance")

    # Get the list of employees
    employees = load_employee_names()

    if employees:
        selected_employee = st.selectbox("Select Employee", employees, key="daily_attendance_employee")
        status = st.radio("Select Status", ["Present", "Absent", "Late"], index=0, key="daily_attendance_status")
        checkin_time = st.time_input("Check-in Time", datetime.now().time(), key="daily_attendance_checkin")

        if st.button("Submit Attendance", key="daily_attendance_submit"):
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = checkin_time.strftime('%H:%M')

            # Add the record if it doesn't exist
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM attendance WHERE employee_name=? AND date=?', (selected_employee, date_str))
            data = cursor.fetchone()
            if data is None:
                cursor.execute('INSERT INTO attendance (employee_name, check_in_time, date, status) VALUES (?, ?, ?, ?)',
                               (selected_employee, time_str, date_str, status))
                conn.commit()
                conn.close()
                st.success(f"Attendance for {selected_employee} recorded successfully!")
            else:
                conn.close()
                st.warning(f"{selected_employee} has already been marked present today.")

    else:
        st.write("No employees found. Please add users in the 'Add User' tab.")

    # Display Today's Attendance
    st.subheader("Today's Attendance")

    # Load attendance data
    attendance_df = load_attendance_data()

    # Filter records for today
    today_date = datetime.today().date()
    today_records = attendance_df[attendance_df['Date'] == today_date]

    if not today_records.empty:
        # Display only relevant columns
        today_records = today_records[["Employee", "Time", "Status"]]
        st.dataframe(today_records, use_container_width=True)
    else:
        st.info("No attendance records found for today.")

# Monthly Attendance Tab
with tabs[4]:
    st.header("📆 Monthly Attendance Overview")
    st.write("View attendance summary by month.")
    attendance_df = load_attendance_data()
    attendance_df["Date"] = pd.to_datetime(attendance_df["Date"])

    if not attendance_df.empty:
        attendance_df["Month_Year"] = attendance_df["Date"].dt.strftime("%B %Y")
        selected_month = st.selectbox(
            "Select Month", attendance_df["Month_Year"].unique()
        )
        monthly_data = attendance_df[attendance_df["Month_Year"] == selected_month]
        st.dataframe(monthly_data)
    else:
        st.write("No attendance records available.")

# Late Attendance Tab
with tabs[5]:
    st.header("⏰ Late Attendance")

    # Load Attendance Data
    attendance_df = load_attendance_data()

    # Filter Attendance Data for "Late" Status
    late_data = attendance_df[attendance_df["Status"] == "Late"]

    # Dropdown Menu for Time Range Selection
    time_range = st.selectbox(
        "Select Time Range",
        ["Today", "This Month", "Past 3 Months", "Past 6 Months", "This Year"],
        index=1  # Default selection is "This Month"
    )

    # Filter Late Attendance Data Based on Selected Time Range
    filtered_late_data = filter_late_data(late_data, time_range)

    if filtered_late_data is not None and not filtered_late_data.empty:
        # Display the Filtered Late Attendance Data
        st.subheader(f"Late Attendance Records - {time_range}")
        st.dataframe(filtered_late_data)

        # Group Late Attendance by Employee for Visualization
        late_counts = filtered_late_data.groupby("Employee").size()
        late_counts = late_counts.reset_index(name='Late_Count')

        # Column Chart - Late Attendance per Employee (Using Plotly)
        st.subheader(f"Column Chart - Late Attendance per Employee ({time_range})")
        fig = px.bar(
            late_counts,
            x='Employee',
            y='Late_Count',
            labels={"Employee": "Employee", "Late_Count": "Late Count"},
            title=f"Late Attendance - {time_range}",
            text_auto=True
        )
        st.plotly_chart(fig)
    else:
        st.write(f"No late attendance records found for {time_range}.")

# Employee Dashboard Tab
with tabs[6]:
    st.header("📊 Employee Dashboard")

    attendance_df = load_attendance_data()
    employees = load_employee_names()

    if len(employees) > 0:
        # Select Employee
        selected_employee = st.selectbox("Select Employee", employees, key="dashboard_employee")
        emp_data = attendance_df[attendance_df["Employee"] == selected_employee]

        if not emp_data.empty:
            # Individual Employee Metrics and Chart
            days_present = emp_data[emp_data["Status"] == "Present"].shape[0]
            days_late = emp_data[emp_data["Status"] == "Late"].shape[0]
            days_absent = emp_data[emp_data["Status"] == "Absent"].shape[0]
            total_days = emp_data.shape[0]
            st.metric(f"{selected_employee}'s Attendance", f"{days_present + days_late}/{total_days} Days")

            # Bar Chart for Individual Employee Attendance
            st.subheader(f"{selected_employee} - Attendance Distribution")
            status_counts = emp_data["Status"].value_counts()
            st.bar_chart(status_counts)
        else:
            st.write(f"No attendance records found for {selected_employee}.")

        st.markdown("---")

        # All Employees - Attendance Overview
        st.header("📊 All Employees - Attendance Overview")

        # Group by Employee and Status with missing statuses filled as 0
        status_by_employee = (
            attendance_df.groupby(["Employee", "Status"]).size().unstack(fill_value=0)
        ).reset_index()

        # Ensure all status columns are present
        expected_statuses = {"Present", "Absent", "Late"}
        for status in expected_statuses - set(status_by_employee.columns):
            status_by_employee[status] = 0

        st.write("Attendance Overview for All Employees:")
        st.dataframe(status_by_employee)

        # Check if the DataFrame has the expected columns and is not empty
        if not status_by_employee.empty:
            # Create a stacked bar chart using Plotly with custom colors
            fig = px.bar(
                status_by_employee,
                x='Employee',
                y=["Present", "Absent", "Late"],
                title="All Employees - Attendance Overview",
                labels={"value": "Count", "Employee": "Employee"},
                barmode="stack",
                color_discrete_map={
                    "Present": "#66ff66",  # Light green
                    "Absent": "#636EFA",   # Default Plotly blue
                    "Late": "#ff0000"      # Red
                },
                text_auto=True  # Optional: Adds labels on bars
            )

            # Display the chart in Streamlit
            st.plotly_chart(fig)
        else:
            st.write("No sufficient attendance data available to generate the chart.")

        # Optional: Show Raw Attendance Data
        if st.checkbox("Show Raw Attendance Data"):
            st.dataframe(attendance_df)
    else:
        st.write("No attendance records available.")

# Leave Requests Tab
with tabs[7]:
    st.header("📋 Leave Requests")

    # Get the list of employees from the database
    employees = load_employee_names()

    if employees:
        # Leave Request Form
        employee_name = st.selectbox("Select Employee", employees, key="leave_employee")
        leave_reason = st.text_input("Reason for Leave")
        leave_days = st.number_input("Number of Days", min_value=1, max_value=30, value=1)

        if st.button("Submit Leave Request"):
            if leave_reason:
                add_leave_request(employee_name, leave_reason, leave_days)
                st.success("Leave request submitted successfully!")
            else:
                st.error("Please enter a reason for leave.")

        # Display and Approve Leave Requests
        st.subheader("Pending Leave Requests")
        leave_data = load_leave_data()
        pending_requests = leave_data[leave_data["status"] == "Pending"]

        if not pending_requests.empty:
            for index, row in pending_requests.iterrows():
                st.write(f"**{row['employee_name']}** requested leave for **{row['days']} days** due to **{row['reason']}**.")
                approver_name = st.text_input(f"Approver for {row['employee_name']}", key=f"approver_{row['id']}")

                if st.button(f"Approve Leave for {row['employee_name']}", key=f"approve_{row['id']}"):
                    if approver_name:
                        approve_leave(row['id'], approver_name)
                        st.success(f"Leave approved for {row['employee_name']} by {approver_name}!")
                    else:
                        st.error("Please enter the approver's name.")
        else:
            st.write("No pending leave requests.")
    else:
        st.write("No employees found. Please add users in the 'Add User' tab.")

# Working Hours Tab
with tabs[8]:
    st.header("⏰ Working Hours Settings")

    # Load current configuration
    config_data = st.session_state.config_data

    # Attendance Settings
    st.subheader("Attendance Settings")
    attendance_time = st.time_input(
        "Attendance Time", 
        datetime.strptime(config_data['attendance_time'], '%H:%M').time()
    )
    grace_period_minutes = st.number_input(
        "Grace Period for Lateness (minutes)", 
        min_value=0, max_value=120, value=config_data.get('grace_period_minutes', 15)
    )
    absent_threshold_minutes = st.number_input(
        "Absent Threshold (minutes after attendance time)", 
        min_value=0, max_value=480, value=config_data.get('absent_threshold_minutes', 60)
    )

    # Weekend Settings
    st.subheader("Weekend Settings")
    weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekend_days = st.multiselect(
        "Select Weekend Days",
        weekdays,
        default=[weekdays[i] for i in config_data.get('weekends', [5, 6])]
    )

    # Official Holidays
    st.subheader("Official Holidays")
    official_holidays = st.date_input(
        "Select Official Holidays",
        value=[
            datetime.strptime(date_str, '%Y-%m-%d').date()
            for date_str in config_data.get('official_holidays', [])
        ],
        key='official_holidays',
    )

    # Ensure official_holidays is always a list
    if isinstance(official_holidays, (tuple, list)):
        official_holidays = list(official_holidays)
    else:
        official_holidays = [official_holidays]

    if st.button("Save Settings"):
        # Update configuration data
        config_data['attendance_time'] = attendance_time.strftime('%H:%M')
        config_data['grace_period_minutes'] = grace_period_minutes
        config_data['absent_threshold_minutes'] = absent_threshold_minutes
        config_data['weekends'] = [weekdays.index(day) for day in weekend_days]

        # Convert official holidays to list of strings in 'YYYY-MM-DD' format
        config_data['official_holidays'] = [
            date.strftime('%Y-%m-%d') for date in official_holidays
        ]

        # Save updated configuration
        save_config(config_data)
        st.session_state.config_data = config_data
        st.success("Settings saved successfully.")


# Reports Tab
with tabs[9]:
    st.header("📑 Attendance Reports")
    report_type = st.selectbox("Select Report Type", ["Daily", "Monthly", "Yearly"])

    if st.button("Generate Report"):
        report_df = load_attendance_data()
        if not report_df.empty:
            st.dataframe(report_df)
            st.download_button(
                "Download Report",
                report_df.to_csv(index=False),
                f"{report_type}_attendance_report.csv"
            )
        else:
            st.write("No attendance records available to generate reports.")


st.markdown("---")
st.write("Developed by Data Corp © 2024")
