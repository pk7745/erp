# 🎓 BMS College ERP — Complete Technical & Operational Documentation

> **Platform:** BMS College of Commerce & Management (BMSCCM), Basavanagudi Campus, Bengaluru  
> **Repository:** [https://github.com/pk7745/erp.git](https://github.com/pk7745/erp.git)  
> **Active Branch:** `main`  
> **Release Version:** 2.4.0 (Authoritative Timetable, Faculty Schedules & Shared Overview Release)  
> **Framework:** Flask 3.1.3 • Python 3.10+ • SQLAlchemy • SocketIO • Flask-Mail  
> **Database:** Dual-Engine Architecture (PostgreSQL on Supabase Cloud with automatic SQLite fallback)

---

## 📑 Table of Contents

1. [Executive Summary & System Architecture](#1-executive-summary--system-architecture)
2. [Technology Stack & Environment Setup](#2-technology-stack--environment-setup)
3. [Database Architecture & Data Models](#3-database-architecture--data-models)
4. [User Accounts & Default Access Credentials](#4-user-accounts--default-access-credentials)
5. [Role-Based Access Control (RBAC) Matrix](#5-role-based-access-control-rbac-matrix)
6. [Module Deep Dives](#6-module-deep-dives)
   - 6.1 [Academic Attendance & Class Session Lifecycle](#61-academic-attendance--class-session-lifecycle)
   - 6.2 [Authoritative Timetable & Shared Overview](#62-authoritative-timetable--shared-overview)
   - 6.3 [Smart Staff Attendance (Anti-Spoofing & Geofencing)](#63-smart-staff-attendance-anti-spoofing--geofencing)
   - 6.4 [Centralized Email Notification Engine (8 Events)](#64-centralized-email-notification-engine-8-events)
   - 6.5 [Secure Operational AI Assistant (Gemini Router)](#65-secure-operational-ai-assistant-gemini-router)
   - 6.6 [Digital Vault & OCR Document Ingestion](#66-digital-vault--ocr-document-ingestion)
   - 6.7 [Master Workforce Directory](#67-master-workforce-directory)
7. [Comprehensive Endpoint / Route Reference](#7-comprehensive-endpoint--route-reference)
8. [Automated Test Suites & Quality Assurance](#8-automated-test-suites--quality-assurance)
9. [Deployment & Production Runbook](#9-deployment--production-runbook)

---

## 1. Executive Summary & System Architecture

The **BMS College ERP** is an enterprise-grade institution management platform developed for BMS College of Commerce and Management. The system integrates academic course management, student lecture attendance, staff biometrics/geofencing, human resources payroll, expense claims, institutional notifications, and AI operations into a unified portal.

### Architectural Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CLIENT BROWSERS & MOBILE                         │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTPS / WSS
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                    FLASK 3.1.3 APPLICATION LAYER (app.py)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Authentication & RBAC Filter (Flask-Login + Session Guard)                │
│ • Real-time Websocket Notifications (Flask-SocketIO)                        │
│ • RESTful API & Jinja2 Template Engine (Tailwind/Modern UI)                │
├───────────────────┬─────────────────────────┬───────────────────────────────┤
│ Academic Engine   │ Staff Operations Engine │ AI Operations Engine          │
│ • Student Roster  │ • GPS Geofence (1000m)  │ • Gemini Router Engine        │
│ • Class Sessions  │ • 30s HMAC QR Kiosk     │ • 3-Tier Security Filter      │
│ • Audit History   │ • Device Binding Guard  │ • Whitelisted Read Functions  │
│ • Timetable Sync  │ • Payroll & PDF Payslip │ • Zero Direct SQL Execution   │
└───────────────────┴────────────┬────────────┴───────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────────┐
│                    DUAL-ENGINE DATABASE ABSTRACTION                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Primary Target : Cloud PostgreSQL (Supabase Hosted)                         │
│ Failover Engine: SQLite 3 (instance/college_erp.db - Auto-recovery)         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack & Environment Setup

| Layer | Component | Specification |
|---|---|---|
| **Language** | Python | 3.10 / 3.11 / 3.12 / 3.14 compatible |
| **Web Framework** | Flask | 3.1.3 |
| **ORM / Database** | Flask-SQLAlchemy | 3.1.1 (SQLAlchemy 2.0 compatible) |
| **Database Engines** | PostgreSQL / SQLite | PostgreSQL on Supabase (`db.kjgxfdccvsecsyzcmost.supabase.co`) with fallback to local SQLite |
| **Realtime WebSockets** | Flask-SocketIO | Event-driven notifications |
| **Security & Auth** | Werkzeug / Flask-Login | PBKDF2:SHA256 password hashing, signed cookies, device hash verification |
| **AI LLM Engine** | Google Gemini | Secure operational function router with 3-tier RBAC (`assistant_engine.py`) |
| **OCR & Vision** | Pytesseract / PIL | Automated text parsing from uploaded faculty ID cards & credentials |
| **PDF Generation** | FPDF2 | Automated generation of monthly employee salary slips |
| **Mail Dispatch** | Flask-Mail | SMTP with HTML templates and PDF attachment support |

### Key Environment Variables (`.env`)

```ini
SECRET_KEY=bms-super-secret-production-key-2026
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.kjgxfdccvsecsyzcmost.supabase.co:5432/postgres
GEMINI_API_KEY=AIzaSy...
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=notifications@bmsccm.edu.in
MAIL_PASSWORD=app-specific-password
MAIL_DEFAULT_SENDER=BMS College ERP <notifications@bmsccm.edu.in>
CAMPUS_LAT=12.9515
CAMPUS_LNG=77.5762
CAMPUS_GEOFENCE_RADIUS=1000
```

---

## 3. Database Architecture & Data Models

### 3.1 Core Entity Relationships

```mermaid
erDiagram
    USER ||--o{ TIMETABLE : "assigned to"
    USER ||--o{ CLASS_SESSION : "conducts"
    TIMETABLE ||--o{ CLASS_SESSION : "schedules"
    CLASS_SESSION ||--o{ STUDENT_ATTENDANCE : "records"
    STUDENT ||--o{ STUDENT_ATTENDANCE : "has attendance"
    CLASS_SESSION ||--o{ STUDENT_ATTENDANCE_AUDIT : "tracked in"
    USER ||--o{ ATTENDANCE : "staff check-in"
    USER ||--o{ REGISTERED_DEVICE : "owns"
    USER ||--o{ LEAVE : "submits"
    USER ||--o{ EXPENSE_CLAIM : "submits"
    USER ||--o{ AUDIT_LOG : "triggers"
```

### 3.2 Schema Specifications

#### 1. `User` (`user`)
Stores all institutional personnel records:
- `id`: Integer, Primary Key
- `username`: String(80), Unique
- `password`: String(255), PBKDF2 hash
- `role`: String(50) — `Principal`, `HOD - BCA Dept`, `Faculty`, `HR`, `Accountant`
- `department`: String(100) — `Computer Science`, `Commerce`, `Administration`, `HR`
- `full_name`, `email`, `phone`, `designation`, `date_of_joining`, `date_of_birth`
- `base_salary`, `hourly_rate`, `status` (`Active`, `On Leave`, `Inactive`)
- `caste`, `religion`, `address`, `emergency_contact`

#### 2. `Student` (`student`)
Authoritative roster for BCA students:
- `id`: Integer, Primary Key
- `uucms_id`: String(50), Unique (e.g. `U03MB22S0001`)
- `name`: String(100)
- `course`: String(50), Default `'BCA'`
- `semester`: String(20), Default `'Sem V'`
- `section`: String(20), Default `'A'`
- `roll_no`: String(50)
- `status`: String(20), Default `'Active'`

#### 3. `Timetable` (`timetable`)
Weekly master lecture allocation slots:
- `id`: Integer, Primary Key
- `user_id`: Integer, Foreign Key -> `user.id`
- `day`: String(20) (`Monday` to `Saturday`)
- `time_slot`: String(50) (e.g. `'08:00 AM-10:00 AM'`, `'12:30 PM-01:30 PM'`)
- `subject`: String(100)
- `course`: String(50), Default `'BCA'`
- `semester`: String(20), Default `'Sem V'`
- `section`: String(20), Default `'A'`
- `room_no`: String(50)
- `status`: String(20), Default `'pending'` (`held`, `missed`, `pending`)

#### 4. `ClassSession` (`class_session`)
Represents an executed or active classroom session:
- `id`: Integer, Primary Key
- `timetable_id`: Integer, Foreign Key -> `timetable.id`, Indexed
- `date`: Date, Indexed
- `time_slot`: String(50)
- `course`, `semester`, `section`, `scheduled_subject`, `actual_subject`
- `scheduled_faculty_id`: Integer, Foreign Key -> `user.id`
- `actual_faculty_id`: Integer, Foreign Key -> `user.id`
- `room_no`: String(50)
- `status`: String(20) (`SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`)
- `remarks`: String(255)
- `version`: Integer, Default 1 (Optimistic locking for concurrency control)
- `created_at`, `updated_at`: DateTime

#### 5. `StudentAttendance` (`student_attendance`)
Individual student attendance roll entry for a class session:
- `id`: Integer, Primary Key
- `class_session_id`: Integer, Foreign Key -> `class_session.id` (CASCADE delete)
- `student_id`: Integer, Foreign Key -> `student.id`
- `status`: String(20) (`Present`, `Absent`, `Late`, `Excused`)
- `remarks`: String(255)
- `marked_at`: DateTime
- `marked_by_id`: Integer, Foreign Key -> `user.id`

#### 6. `StudentAttendanceAudit` (`student_attendance_audit`)
Immutable record of modifications to attendance:
- `id`: Integer, Primary Key
- `class_session_id`: Integer, Foreign Key -> `class_session.id`
- `student_id`: Integer, Foreign Key -> `student.id`
- `old_status`, `new_status`: String(20)
- `changed_by_id`: Integer, Foreign Key -> `user.id`
- `reason`: String(255)
- `created_at`: DateTime

#### 7. `Attendance` (`attendance`)
Staff clock-in records:
- `id`: Integer, Primary Key
- `user_id`: Integer, Foreign Key -> `user.id`
- `date`: Date
- `punch_in`: DateTime
- `punch_out`: DateTime
- `punch_in_method`: String(50) (`QR Kiosk`, `GPS Mobile`, `Manual Override`)
- `lat`, `lng`: Float
- `status`: String(20) (`Present`, `Late`, `Half Day`, `Absent`)
- `overtime_hours`: Float

---

## 4. User Accounts & Default Access Credentials

Default login credentials seeded across departments:

| Username | Password | Full Name | Primary Role | Department | Key Responsibilities |
|---|---|---|---|---|---|
| `admin` | `bms123` | System Admin | `HR` / Admin | Administration | System oversight, Workforce Master, OCR Vault, Notifications |
| `pankaj` | `bms123` | Dr. Pankaj Choudhry | `Principal` | Executive | Institution-wide analytics, all faculty timetables, executive approvals |
| `kiran` | `bms123` | Dr.Kiran Kumar M N | `HOD - BCA Dept` | Computer Applications | HOD oversight, Core CS Sem I–IV classes (0 Sem V allocations) |
| `balram` | `bms123` | Mr. Balaram M | `Faculty` | Commerce / Computer Apps | Web Programming, student attendance marking |
| `shivani` | `bms123` | Ms. Shivani Shikha | `Faculty` | Commerce / Computer Apps | Web Programming Lab, Software Engineering |
| `shrinkala`| `bms123` | Ms. Shrinkhala Kumari | `Faculty` | Management / Computer Apps| Cryptography & Network Security |
| `bhoomika` | `bms123` | Ms. Bhoomika Hegde | `Faculty` | Computer Applications | Data Analytics (Theory & Labs) |
| `gururaj` | `bms123` | Mr. Gururaj | `Faculty` | Computer Applications | Quantitative Techniques |
| `ramkishore`| `bms123`| Mr. Ramkishore | `Faculty` | Commerce | General English & English (Sem II & IV only) |
| `prathiba` | `bms123` | Mrs. Prathiba Singh | `Faculty` | Management | Management faculty |
| `newfac` | `bms123` | New Faculty | `Faculty` | Commerce | CRT Program (Add-on) Coordinator |
| `acc1` | `bms123` | Rajesh Finance | `Accountant` | Accounts | Payroll processing, expense claims, tax deductions |

---

## 5. Role-Based Access Control (RBAC) Matrix

| Portal Route / Capability | Faculty | HOD | Principal | Accountant | Admin (`admin` / `HR`) |
|---|:---:|:---:|:---:|:---:|:---:|
| Personal Dashboard (`/dashboard`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Personal Weekly Schedule (`/timetable`) | ✅ (Own) | ✅ (Dept) | ✅ (All) | ❌ | ❌ |
| **College Timetable Overview (`/timetable/overview`)** | ✅ | ✅ | ✅ | ❌ | **❌ (HTTP 403 Forbidden)** |
| Student Attendance History (`/academic/history`) | ✅ (Own) | ✅ (Dept) | ✅ (All) | ❌ | ❌ |
| Take / Edit Student Attendance (`/academic/take_attendance`) | ✅ | ✅ | ✅ | ❌ | ❌ |
| QR Attendance Kiosk (`/qr_attendance`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Master Workforce Directory (`/admin/staff_master`) | ❌ | ❌ | ❌ | ✅ | ✅ |
| Digital Vault & OCR Ingestion (`/digital_vault`) | ❌ | ❌ | ❌ | ✅ | ✅ |
| Notification Test Hub (`/notifications/selftest`) | ❌ | ❌ | ❌ | ✅ | ✅ |
| AI Assistant — Tier 1 (Schedule/Presence) | ✅ | ✅ | ✅ | ✅ | ✅ |
| AI Assistant — Tier 2 (Leaves/Overtime) | ❌ | ✅ | ✅ | ✅ | ✅ |
| AI Assistant — Tier 3 (Salary/PII Data) | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ **(Forbidden by Design)** |

---

## 6. Module Deep Dives

### 6.1 Academic Attendance & Class Session Lifecycle

The academic attendance system operates in a rigorous 3-step stateful workflow:

```
┌─────────────────────────────────┐
│ 1. INITIALIZE SESSION           │
│ Faculty clicks scheduled slot   │ ──► Creates ClassSession record
│ on /timetable                   │     (Status: IN_PROGRESS)
└─────────────────────────────────┘
                 │
┌────────────────▼────────────────┐
│ 2. MARK STUDENT ATTENDANCE      │
│ Faculty marks Present / Absent  │ ──► Bulk saves StudentAttendance rows
│ or uses "Mark All Present"      │     Linked to ClassSession ID
└─────────────────────────────────┘
                 │
┌────────────────▼────────────────┐
│ 3. FINALIZE SESSION             │
│ Review counts & submit remarks  │ ──► Sets ClassSession to COMPLETED
│ Lock for edits (Audit enabled)  │     Sets Timetable.status to 'held'
└─────────────────────────────────┘
```

- **Optimistic Concurrency Control:** Uses the `version` field in `ClassSession` to prevent concurrent edits from conflicting.
- **Audit Trails:** Edits made after completion automatically log who changed which student's attendance from what status to what status, with mandatory reason tracking.
- **Attendance History:** Searchable, filterable by date, faculty, course, and section at `/academic/history`.

---

### 6.2 Authoritative Timetable & Shared Overview

#### Authoritative BCA Semester V Schedule (AY 2026–27)
Derived authoritatively from official institutional source documents:

| Day | Time Slot | Subject | Faculty | Room | Type |
|---|---|---|---|---|---|
| **Monday** | 08:00 AM – 10:00 AM | Web Programming Lab | Ms. Shivani Shikha | Room 101 | 2-Hour Practical Lab |
| | 10:30 AM – 11:30 AM | Cryptography & Network Security | Ms. Shrinkhala Kumari | Room 101 | Theory Lecture |
| | 11:30 AM – 12:30 PM | Software Engineering | Ms. Shivani Shikha | Room 203 | Theory Lecture |
| | 12:30 PM – 01:30 PM | Web Programming | Mr. Balaram M | Room 203 | Theory Lecture (ID=31 in-place) |
| | 02:00 PM – 05:00 PM | CRT Program (Add-on) | Institutional Coordinator | GF Lab | 3-Hour Add-on Block |
| **Tuesday** | 09:00 AM – 10:00 AM | Software Engineering | Ms. Shivani Shikha | Room 102 | Theory Lecture |
| | 10:30 AM – 11:30 AM | Cryptography & Network Security | Ms. Shrinkhala Kumari | Room 103 | Theory Lecture |
| | 11:30 AM – 12:30 PM | Web Programming | Mr. Balaram M | Room 103 | Theory Lecture |
| **Wednesday** | 09:00 AM – 10:00 AM | Web Programming | Mr. Balaram M | Room 103 | Theory Lecture |
| | 10:30 AM – 11:30 AM | Software Engineering | Ms. Shivani Shikha | Room 101 | Theory Lecture |
| | 11:30 AM – 12:30 PM | Cryptography & Network Security | Ms. Shrinkhala Kumari | Room 303 | Theory Lecture |
| | 12:30 PM – 01:30 PM | Quantitative Techniques | Mr. Gururaj | Room 101 | Theory Lecture |
| | 02:00 PM – 03:00 PM | Quantitative Techniques | Mr. Gururaj | Room 105 | Theory Lecture |
| **Thursday** | 08:00 AM – 10:00 AM | Data Analytics | Ms. Bhoomika | Room 305 | 2-Hour Practical Lab |
| | 10:30 AM – 11:30 AM | Web Programming Lab | Ms. Shivani Shikha | Room 101 | Practical Lab |
| | 11:30 AM – 12:30 PM | Software Engineering | Ms. Shivani Shikha | Room 103 | Theory Lecture |
| **Friday** | 08:00 AM – 10:00 AM | Data Analytics | Ms. Bhoomika | Room 303 | 2-Hour Practical Lab |
| | 10:30 AM – 11:30 AM | Cryptography & Network Security | Ms. Shrinkhala Kumari | Room 303 | Theory Lecture |
| **Saturday** | 08:00 AM – 10:00 AM | Data Analytics | Ms. Bhoomika | Room 101 | 2-Hour Practical Lab |
| | 10:30 AM – 12:30 PM | CRT Program (Add-on) | Institutional Coordinator | Room 101 | 2-Hour Add-on Block |

#### Teaching Allocations for Other Faculty
- **Dr. Kiran Kumar M N:** Strictly **0 Semester V allocations**. Allocated exclusively to:
  - Sem I: *C Programming*
  - Sem II: *Data Structures and Algorithms*
  - Sem III: *Database Management System*
  - Sem IV: *Design and Analysis of Algorithms*
- **Mr. Ramkishore:** Assigned exclusively to *English* courses (Sem II General English, Sem IV English).

#### Foreign Key Preservation for Row 31
`ClassSession` records reference `Timetable.id = 31` (Mr. Balaram M's Monday Web Programming class). The synchronization engine (`sync_authoritative_timetable()`) updates row 31 in-place rather than deleting it, guaranteeing zero foreign-key constraint violations and preserving all historical attendance data.

#### College Timetable Overview (`/timetable/overview`)
- **Accessibility:** Accessible to all faculty, HODs, and Principal across all departments.
- **Admin Exclusion:** Strictly forbidden to `admin` or users with `role = 'admin'` via server-side HTTP `403 Forbidden` (`abort(403)`) and concealed in navigation menus.
- **Visual Distinction:** Multi-hour laboratory sessions and the CRT Program (Add-on) feature distinctive amber and blue badges.

---

### 6.3 Smart Staff Attendance (Anti-Spoofing & Geofencing)

1. **Basavanagudi GPS Geofence:**
   - Coordinates: `12.9515° N, 77.5762° E`
   - Allowed Radius: 1000 meters
   - Haversine formula calculation executed on clock-in payload. Clock-ins outside the perimeter are rejected with an out-of-bounds warning.
2. **Rotating HMAC QR Kiosk (`/qr_attendance`):**
   - Kiosk refreshes dynamic QR codes every 30 seconds using time-bound HMAC tokens.
   - Prevents off-site screenshot sharing.
3. **Hardware Device Binding:**
   - Client browser generates a cryptographic device fingerprint hash (`user_agent + ip_address`).
   - Stored in `RegisteredDevice`. Unrecognized devices prompt an email security notification (Event 2C).
4. **Shift Analytics:**
   - Standard working hours: 09:00 AM to 05:00 PM (8-hour shift).
   - 10-minute grace period (up to 09:10 AM).
   - Automatic calculation of late minutes, early departures, and overtime hours.

---

### 6.4 Centralized Email Notification Engine (8 Events)

Powered by `notify(event, user, context)` with fail-safe error isolation:

| Event ID | Name | Trigger Condition | Recipient | Attachments |
|---|---|---|---|---|
| `EVENT_1` | Attendance Alert | Check-in after 09:10 AM | Staff Member | — |
| `EVENT_2A`| Leave Submission | New leave application created | HOD / Principal | — |
| `EVENT_2B`| Leave Decision | Approved or Rejected | Staff Member | — |
| `EVENT_2C`| Unrecognized Device | Login from new hardware hash | Staff Member | — |
| `EVENT_3` | Monthly Payslip | Generated by Accountant | Staff Member | PDF Payslip |
| `EVENT_4` | Timetable Change | Faculty reassigned or slot edited | Affected Faculty | — |
| `EVENT_5` | Expense Claim | New reimbursement filed | Accountant | — |
| `EVENT_6` | System Audit | Security or DB configuration event | System Admin | — |

Diagnostic testing available at `/notifications/selftest`.

---

### 6.5 Secure Operational AI Assistant (Gemini Router)

Implemented in `assistant_engine.py`:
- **Architecture:** The Gemini model is strictly a **function router**. It chooses from a deterministic whitelist of Python routines; it does **not** generate SQL and has **zero direct access** to raw database connections.
- **3-Tier RBAC Gate:**
  - **Tier 1 (All Staff):** Lecture schedules, room lookups, personal punch times, campus headcount.
  - **Tier 2 (Management Only - HOD/Principal/Admin):** Department leave summaries, staff late counts, overtime statistics.
  - **Tier 3 (Strictly Forbidden by Design):** Base salaries, PF/tax deductions, date of birth, home addresses, caste, or religious information. Inquiries are politely declined.
- **Audit Logging:** Every query, selected tool, caller ID, and timestamp is logged in `AuditLog`.

---

### 6.6 Digital Vault & OCR Document Ingestion

Located at `/digital_vault` (Admin/Accountant access only):
- **Tesseract OCR Parsing:** Scans uploaded faculty ID cards, degree certificates, and identification docs.
- **Regex Extraction:** Automatically parses Full Name, Email, Phone Number, Department, and Date of Joining.
- **One-Click Staff Onboarding:** Extracted parameters pre-populate the "Add Employee" registration modal.

---

### 6.7 Master Workforce Directory

Located at `/admin/staff_master`:
- Institutional registry displaying comprehensive demographic and payroll records for all employees.
- Interactive modal for live updates directly committing to PostgreSQL/SQLite.
- Quick exports to CSV and PDF rosters.

---

## 7. Comprehensive Endpoint / Route Reference

Below is the verified registry of active routes:

### Authentication & Core
- `GET /` — Landing page / redirect
- `GET, POST /login` — Staff & Admin authentication
- `GET /logout` — Session termination
- `GET /dashboard` — Role-customized analytics dashboard
- `GET, POST /profile` — Personal profile view & credential update
- `GET, POST /forgot_password` — Account recovery

### Timetable & Academic Scheduling
- `GET /timetable` — Personal weekly teaching schedule
- `POST /timetable/manage` — Add / modify lecture slot
- `GET /timetable/overview` — **College Timetable Overview** (Read-only, Admin 403 Forbidden)
- `GET /academic/history` — Student attendance historical sessions
- `GET, POST /academic/session/<int:session_id>` — View session details / export
- `GET, POST /academic/take_attendance/<int:session_id>` — Conduct student roll-call
- `GET, POST /academic/edit_attendance/<int:session_id>` — Edit completed attendance (Audited)

### Attendance & Kiosk Operations
- `GET, POST /attendance` — Personal punch history & manual clock-in
- `GET /qr_attendance` — 30-second HMAC dynamic QR clock-in kiosk
- `POST /api/qr_clockin` — Endpoint for mobile scanning of kiosk QR token
- `GET /admin/devices` — Registered hardware devices list & trust toggle

### HR, Leaves & Claims
- `GET, POST /leave` — Leave application & approvals
- `GET /leave_calendar` — Departmental leave calendar view
- `GET, POST /expenses` — Expense reimbursement claims
- `GET /payslip/download/<int:payslip_id>` — PDF payslip download

### Administration, Vault & Tools
- `GET, POST /admin/staff_master` — Master workforce personnel management
- `GET, POST /digital_vault` — AI OCR document scanner & vault
- `GET, POST /assistant` — Secure Gemini Operational AI Assistant
- `GET /notifications/selftest` — Email notification diagnostic runner
- `GET /audit_logs` — Institutional system audit logs

---

## 8. Automated Test Suites & Quality Assurance

The codebase includes comprehensive automated regression test suites:

### 1. Authoritative Timetable Test Suite
**File:** `test_authoritative_timetable.py`  
**Command:** `python test_authoritative_timetable.py`  
- Validates all 20 Semester V slots match the authoritative source schedule.
- Asserts preservation of `Timetable.id = 31` foreign-key linkage with `ClassSession`.
- Verifies CRT Program (Add-on) slots (GF Lab 3h and Room 101 2h).
- Validates Dr. Kiran Kumar M N has 0 Sem V allocations and standardized titles.
- Validates Mr. Ramkishore is assigned only English courses.
- Asserts `/timetable/overview` returns **HTTP 403 Forbidden** for admin.
- Asserts `/timetable/overview` returns **HTTP 200 OK** for faculty (both with and without Sem V allocations).
- Asserts anonymous visitors are redirected to `/login` (HTTP 302).

### 2. Academic Attendance Workflow Test Suite
**File:** `test_academic_attendance_workflow.py`  
**Command:** `python test_academic_attendance_workflow.py`  
- Runs 20 end-to-end integration tests covering session creation, bulk marking, audit trails, and student statistics.

### 3. Academic Models Test Suite
**File:** `test_academic_models.py`  
**Command:** `python test_academic_models.py`  
- 10 unit tests validating cascade deletes, database constraints, and relationships.

### 4. Full Endpoint & Feature Verification
**File:** `test_all_features.py`  
**Command:** `python test_all_features.py`  
- Iterates over all 85 registered Flask routes and tests them under authenticated and unauthenticated sessions, ensuring 0 crashes.

### Running All Tests at Once:
```powershell
python test_authoritative_timetable.py
python test_academic_attendance_workflow.py
python test_academic_models.py
python test_all_features.py
```

---

## 9. Deployment & Production Runbook

### 9.1 Local Development

1. **Clone the repository:**
   ```bash
   git clone https://github.com/pk7745/erp.git
   cd erp
   ```
2. **Activate Python virtual environment:**
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Initialize database & launch server:**
   ```bash
   python app.py
   ```
   *The server starts at `http://127.0.0.1:9000` (or `http://127.0.0.1:5000`). Database seeding and timetable synchronization run automatically on start.*

### 9.2 Production Deployment (Render / Vercel / Cloud Linux)

1. **Procfile:**
   ```procfile
   web: gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT app:app
   ```
2. **Render Configuration (`render.yaml`):**
   ```yaml
   services:
     - type: web
       name: bms-college-erp
       env: python
       buildCommand: pip install -r requirements.txt
       startCommand: gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT app:app
       envVars:
         - key: PYTHON_VERSION
           value: 3.10.12
   ```
3. **Database Health Note:**
   - The app dynamically tests the Supabase PostgreSQL connection string. If cloud network latency or credentials time out, it gracefully falls back to the local SQLite database without downtime.
