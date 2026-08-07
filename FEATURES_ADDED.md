# 🚀 BMS COLLEGE ERP — THREE-FEATURE ENHANCEMENT DOCUMENTATION

This document details the 3 newly added features integrated into the BMS College ERP system without disrupting any existing database schemas or core functionalities.

---

## 📊 FEATURE 1 — ANALYTICS DASHBOARD (Chart.js)

### Overview
A comprehensive visual intelligence portal rendering 5 real-time analytical charts from operational ERP tables using Chart.js.

### Routes & Endpoint Specifications
- **Page Route**: `GET /analytics`
  - **Allowed Roles**: `admin`, `HR`, `Principal`, `HOD`, `HOD - BCA Dept`
  - **Template**: `templates/analytics.html`
- **Data Endpoint**: `GET /api/analytics/data`
  - **Response**: JSON payload containing aggregated labels and values for 5 charts.

### Rendered Charts
1. **Attendance Trend**: Line chart tracking daily check-ins for the last 30 days.
2. **Leave Status Breakdown**: Doughnut chart showing counts of Pending, Approved, and Rejected requests.
3. **Expense by Category**: Bar chart showing total expense claim sums grouped by category (Travel, WiFi, Supplies).
4. **Department Payroll Expenditure**: Bar chart showing total liquid salary allocation grouped by academic department.
5. **Monthly Performance Ratings**: Bar chart displaying institutional average KPI ratings per evaluation month.

### How to Test
1. Log in as `admin` (Password: `admin123`).
2. Click **Analytics Dashboard** in the left sidebar or visit `http://127.0.0.1:5000/analytics`.
3. Click any **Download CSV** button to download data exports.

---

## 🤖 FEATURE 2 — GEMINI AI ASSISTANT (Whitelisted Intent Engine)

### Overview
A natural-language chat interface for college executives grounded strictly in real database data using a safe, whitelisted tool architecture to prevent arbitrary SQL execution.

### Routes & Endpoint Specifications
- **Page Route**: `GET /assistant`
  - **Allowed Roles**: `admin`, `HR`, `Principal`, `HOD`, `HOD - BCA Dept`
  - **Template**: `templates/assistant.html`
- **Query Endpoint**: `POST /api/assistant/ask`
  - **Request**: `{"question": "How many staff are on leave this week?"}`
  - **Response**: `{"answer": "...", "tool_used": "count_leaves", "data": {...}}`

### Whitelisted Tool Functions
- `count_leaves`: Aggregates leave requests for the current week.
- `pending_expenses`: Summarizes pending reimbursement claims (with threshold filtering).
- `staff_by_department`: Calculates headcount across all departments.
- `total_payroll`: Computes total monthly liquid payroll outflow.
- `today_attendance`: Summarizes today's campus office vs WFH check-ins.
- `performance_summary`: Calculates average institutional KPI evaluation ratings.

### Environment Variable & Security
- **Variable**: `GEMINI_API_KEY` (documented in `.env.example`).
- If unconfigured, the assistant defaults to structured, whitelisted DB summaries.
- All AI queries and tool invocations are logged to `AuditLog`.

### How to Test
1. Log in as `admin`.
2. Click **Gemini AI Assistant** in the left sidebar or visit `http://127.0.0.1:5000/assistant`.
3. Click sample prompt pills or type questions like *"How many staff are on leave this week?"* or *"What is total monthly payroll?"*.

---

## 🔲 FEATURE 3 — QR-CODE STAFF ATTENDANCE

### Overview
A contactless check-in system allowing staff members to scan a daily date-signed QR code from campus displays or kiosks.

### Routes & Endpoint Specifications
- **QR Display Route**: `GET /attendance/qr`
  - **Allowed Roles**: `admin`, `HR`, `Principal`, `HOD`, `HOD - BCA Dept`
  - **Template**: `templates/qr_attendance.html`
  - Generates a daily HMAC-SHA256 date-signed token and renders a base64 QR Code PNG.
- **Check-in Route**: `GET /attendance/checkin?token=<daily_token>`
  - **Allowed Roles**: All authenticated staff users (`Faculty`, `HOD`, `HR`, `Admin`).
  - Validates token against current date.
  - Prevents duplicate check-ins on the same day.
  - Creates a new `Attendance` record (`work_mode='Office'`).

### How to Test
1. Log in as `admin` and open `http://127.0.0.1:5000/attendance/qr`.
2. Click **Test Check-in Now** (or open the encoded check-in URL).
3. Verify that a success alert appears and the new attendance record is displayed in `/attendance`.
4. Attempting to click check-in a second time displays **"Already checked in for today!"**.

---

## 📋 VERIFICATION CHECKLIST

- [x] All 29 Jinja2 HTML templates parse with 0 syntax errors.
- [x] All 61 Flask endpoints pass full execution tests with 0 server crashes.
- [x] Sidebar links added for Analytics, AI Assistant, and QR Attendance.
- [x] `requirements.txt` updated with `google-generativeai`.
- [x] `.env.example` created documenting `GEMINI_API_KEY`.
- [x] Full backups created in `backups/`.
