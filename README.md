# Face Recognition Attendance System

<div dir="rtl">

نظام حضور وانصراف بالتعرف على الوجه: يسجّل حضور الموظف تلقائياً من الكاميرا، ويحسب التأخير والغياب حسب ساعات الدوام والإجازات، مع طلبات الإجازة ولوحات وتقارير.

</div>

A Streamlit app that records attendance with face recognition. It checks people in from the webcam, classifies each day as present / late / absent from the configured working hours, and adds leave requests, dashboards and CSV reports.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?logo=opencv&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)

## Features

| Tab | What it does |
|---|---|
| Face Recognition Attendance | Live webcam recognition (`face_recognition` + OpenCV); a recognised face is checked in once per day with a spoken greeting |
| Add User | Register a person with a photo |
| Daily Attendance | Manual check-in with a chosen status |
| Monthly / Late Attendance | Monthly view and late arrivals by period, with a chart |
| Employee Dashboard | Per-person and team attendance breakdown |
| Leave Requests | Submit and approve leave |
| Working Hours | Start time, grace period, absence threshold, weekends and public holidays |
| Reports | Export attendance to CSV |

Days with no check-in on working days are counted as absences; weekends and holidays are skipped.

## Run it

```bash
pip install -r requirements.txt   # face_recognition needs dlib (CMake + a C++ compiler)
streamlit run app.py
```

Data is stored locally in `attendance.db` and photos in `student_images/`; both are created on first run and are not part of the repository.

## Fixes in this version

- A status chosen by hand in *Daily Attendance* was overwritten by the computed one. It is now kept.
- Records without a check-in time crashed the status calculation.
- Photos of users with Arabic names were all saved as `jpg`, so each new user overwrote the previous one. Such names now get a unique file name.
- Added `requirements.txt`; the sample database and personal photos are excluded.

## Author

**Renad Madi** — [GitHub](https://github.com/RENAD-MADI)
