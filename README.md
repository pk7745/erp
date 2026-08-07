<div align="center">

# 🎓 BMS College ERP — Enterprise Academic & Operational Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Framework-Flask_3.1.3-black.svg?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-Supabase_PostgreSQL-336791.svg?logo=postgresql&logoColor=white)](https://supabase.com/)
[![AI Engine](https://img.shields.io/badge/AI-Google_Gemini-8E44AD.svg?logo=google&logoColor=white)](https://deepmind.google/technologies/gemini/)
[![Deployment](https://img.shields.io/badge/Deployment-Render_%2F_Vercel-success.svg?logo=render&logoColor=white)](https://render.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

*A full-stack, enterprise-grade college administration platform built for **BMS College of Commerce & Management (Basavanagudi Campus)**. Featuring Cloud PostgreSQL, Smart Anti-Spoofing Attendance with GPS Geofencing, AI OCR Document Ingestion, Centralized 8-Event Email Dispatch, Master Workforce Control, and a Secure-by-Design Gemini AI Operations Assistant.*

---

[Key Features](#-key-features) •
[System Architecture](#-system-architecture) •
[RBAC Matrix](#-role-based-access-control-rbac-matrix) •
[Notification Engine](#-centralized-email-notification-engine-8-events) •
[AI Assistant](#-gemini-operational-ai-assistant-secure-by-design) •
[Installation & Setup](#-local-setup--installation) •
[Deployment Guide](#-production-deployment-guide)

</div>

---

## 🌟 Executive Vision & Key Innovations

The **BMS College ERP** is designed to replace fragmented legacy college software with a single unified, secure, high-performance platform.

```
                  ┌───────────────────────────────────────────────────────────┐
                  │          BMS COLLEGE ERP CENTRAL ENGINE                   │
                  │   (Flask 3.1.3 + Supabase Cloud PostgreSQL DB)            │
                  └─────────────┬───────────────────────────────┬─────────────┘
                                │                               │
     ┌──────────────────────────┴──────────────┐   ┌────────────┴───────────────────────────┐
     │  🛡️ Anti-Spoofing Attendance            │   │  🤖 Secure Operational AI Assistant   │
     │  • Basavanagudi GPS Geofence (1000m)    │   │  • Whitelisted Read-Only Functions    │
     │  • 30s HMAC Rotating QR Kiosk           │   │  • 3-Tier Security Role Gate          │
     │  • Signed Hardware Device Binding       │   │  • Zero Direct SQL / No DB Access     │
     └─────────────────────────────────────────┘   └────────────────────────────────────────┘
                                │                               │
     ┌──────────────────────────┴──────────────┐   ┌────────────┴───────────────────────────┐
     │  📧 Centralized Email Engine (8 Events) │   │  👑 Master Workforce Directory         │
     │  • Auto-Generated Payslip PDFs          │   │  • Full Personnel Records & Demographics│
     │  • Fail-Safe PostgreSQL Audit Log       │   │  • Live Edit Modal (PostgreSQL Save)  │
     └─────────────────────────────────────────┘   └────────────────────────────────────────┘
```

---

## 🚀 Key Features

### 1. 📍 Smart Attendance Engine (Anti-Spoofing & Geofencing)
- **Basavanagudi Campus GPS Perimeter**: Mandatory GPS verification requiring staff to clock in within **1000m radius** of BMSCCM Basavanagudi Campus (`12.9515° N, 77.5762° E`).
- **30-Second Rotating HMAC QR Tokens**: Dynamic QR kiosk (`/qr_attendance`) generating auto-refreshing TOTP/HMAC QR codes to defeat off-site screenshot sharing.
- **Hardware Device Binding**: Tracks signed device cookies and hardware hashes in `RegisteredDevice` table; flags unrecognized devices for HR review.
- **Working-Hours Intelligence**: Calculates work hours (09:00 AM – 05:00 PM), 10-minute grace period, late arrivals, early departures, and overtime hours.

### 2. 👑 Master Workforce Directory (Exclusive Admin Section)
- **Dedicated Route**: **[`/admin/staff_master`](http://127.0.0.1:9000/admin/staff_master)** (Restricted strictly to `HR`, `Accountant`, `admin`).
- **Complete Personnel View**: Displays Name, Role, Username, Email, Phone, Address, Department, Dept ID, DOB, Joining Date, Caste, Religion, Status, and Net Payroll.
- **Master Live Profile Edit**: Interactive modal allowing Admin to update any staff member's complete profile directly in PostgreSQL.

### 3. 📁 AI-Powered Digital Vault & OCR Scanner
- **Restricted Route**: **[`/digital_vault`](http://127.0.0.1:9000/digital_vault)** (Admin Department Only).
- **AI OCR Document Scanner**: Uses `pytesseract` and image fallback parsing to extract names, emails, phones, departments, and salaries from uploaded ID card or document images.
- **Instant "➕ Add Employee" Modal**: Pre-fills extracted credentials into an interactive modal so Admin can register new staff to PostgreSQL in 1 click.

### 4. 📧 Centralized Email Notification Engine (8 Core Events)
- **Single Dispatch Engine**: `notify(event, user, context)` powered by Flask-Mail and Gmail SMTP.
- **PDF Payslip Attachments**: Automatically generates and attaches official PDF payslips.
- **Fail-Safe Guarantee**: Dispatch errors log as `FAILED` in `notification_log` without crashing application routes.
- **Diagnostic Self-Test Hub**: Live diagnostic test page at **`/notifications/selftest`**.

### 5. 🤖 Operational AI Assistant (Gemini, Secure by Design)
- **Whitelisted Function Router**: Gemini model selects from whitelisted Python functions only (never writes SQL or touches DB directly).
- **3-Tier Access Model**:
  - **Tier 1 (All Staff)**: Presence, check-in times, lecture schedules, class rooms, headcount.
  - **Tier 2 (Management Only)**: Leave reasons, late arrivals, overtime, notification logs.
  - **Tier 3 (FORBIDDEN BY DESIGN)**: Salary, PF, Tax, DOB, address, and personal markers are absent from the whitelist menu. Refused politely.
- **Audit Logging**: Every AI query, selected tool, user role, and status recorded in `AuditLog`.

---

## 🔐 Role-Based Access Control (RBAC) Matrix

| Portal Feature / Route | Faculty Member | HOD | Principal | Accountant | System Admin / HR |
|---|:---:|:---:|:---:|:---:|:---:|
| **Personal Dashboard & Profile** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **GPS / QR Attendance Clock-In** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **View Individual Payroll** | ✅ (Own) | ✅ (Own) | ✅ (Own) | ✅ (All) | ✅ (All) |
| **Leave Request Submission** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Leave Approval System** | ❌ | ✅ (Dept) | ✅ (All) | ❌ | ✅ (All) |
| **Add New Employee** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Digital Document Vault & OCR** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Master Workforce Directory** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Notification Hub & Diagnostics** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **AI Operations Assistant** | Tier 1 | Tier 1+2 | Tier 1+2 | Tier 1+2 | Tier 1+2 |

---

## 📧 Centralized Email Notification Engine (8 Events)

| # | Event Key | Trigger Location | Attachment | Event Email Content & Context |
|---|---|---|---|---|
| 1 | `salary_credited` | `/edit_salary/<uid>` / Payroll | 📄 Payslip PDF | Salary credited notice with net amount & month |
| 2 | `payslip_delivery` | `/send_payslip_email/<uid>` | 📄 Payslip PDF | Digital payslip delivery with verification code |
| 3 | `leave_decision` | `/leave/action/<id>/<action>` | — | Leave Approval / Rejection update with reason |
| 4 | `expense_decision` | `/approve_expense/<id>/<action>` | — | Expense Claim Approval / Rejection update with amount |
| 5 | `task_assigned` | `/assign_task` | — | New institutional task assignment notice with assigner name |
| 6 | `new_device_login` | `/login` (New Device) | — | Security Alert with IP address, browser & timestamp |
| 7 | `missing_checkout` | `/attendance/daily_close` | — | Evening check-out reminder nudge |
| 8 | `monthly_attendance_summary` | `/attendance/monthly_summary` | — | Monthly attendance statement (days present, lates, missing outs) |

---

## 🤖 Gemini Operational AI Assistant (Secure by Design)

```
                            ┌────────────────────────────────────────┐
                            │   User Question (Natural Language)     │
                            └───────────────────┬────────────────────┘
                                                │
                                ┌───────────────┴───────────────┐
                                │   Tier 3 Forbidden Keyword    │
                                │         Detection Gate        │
                                └───────┬───────────────┬───────┘
                     Contains Forbidden │               │ Allowed Query
                     (Salary, DOB, etc.)│               │
                                        ▼               ▼
                        ┌───────────────────┐   ┌───────────────────────────┐
                        │ 🔒 POLITE DENIAL  │   │  Gemini Whitelist Router  │
                        │  (No DB Execution)│   │  (Selects Python Tool)    │
                        └───────────────────┘   └───────────────┬───────────┘
                                                                │
                                                ┌───────────────┴───────────┐
                                                │  Python Whitelist Engine  │
                                                │  (Role Gate & Resolver)   │
                                                └───────────────┬───────────┘
                                                                │
                                                ┌───────────────┴───────────┐
                                                │  Execute Read-Only Query  │
                                                │  & Log to AuditLog        │
                                                └───────────────────────────┘
```

---

## 🛠️ Tech Stack & Dependencies

- **Backend**: Python 3.10+, Flask 3.1.3, Flask-SQLAlchemy 3.1.1, Flask-Login, Flask-SocketIO, Flask-Mail.
- **Database**: Supabase Cloud PostgreSQL (`psycopg2-binary`) with local SQLite fallback.
- **AI & Computer Vision**: Google Gemini API (`google-generativeai`), Tesseract OCR (`pytesseract`), Pillow (`PIL`).
- **PDF & Barcode Generation**: FPDF (`fpdf`), QR Code (`qrcode`).
- **Frontend**: Vanilla HTML5, Modern CSS Glassmorphic Design System (`professional-office-portal.css`), JavaScript (ES6+), FontAwesome 6, Socket.IO Client.

---

## 💻 Local Setup & Installation

### Prerequisites
- Python 3.10 or higher installed.
- Git installed.
- Tesseract OCR (Optional, for document vault scanning).

### Step-by-Step Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/pk7745/erp.git
   cd erp
   ```

2. **Create and Activate Virtual Environment**:
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables (`.env`)**:
   Create a `.env` file in the root directory:
   ```env
   SECRET_KEY=bms_erp_secret_key_2026
   PORT=9000

   # Supabase Cloud PostgreSQL URL
   DATABASE_URL=postgresql://postgres:BmsErp2026!@db.kjgxfdccvsecsyzcmost.supabase.co:5432/postgres

   # Gmail SMTP Email Dispatch Credentials
   MAIL_USERNAME=your_gmail@gmail.com
   MAIL_PASSWORD=your_16_char_gmail_app_password

   # Google Gemini AI API Key (Optional)
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

5. **Run the Application**:
   ```bash
   python app.py
   ```

6. **Access the Portal**:
   Open **`http://127.0.0.1:9000`** in your web browser.

---

## 🌐 Production Deployment Guide

### Deploying on Render (Recommended)

1. Log in to **[Render Dashboard](https://dashboard.render.com)**.
2. Click **New +** → **Web Service** and connect repository **`pk7745/erp`**.
3. Configure settings:
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
4. Add Environment Variables (`DATABASE_URL`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `GEMINI_API_KEY`).
5. Click **Deploy Web Service**.

### Deploying on Vercel

1. Import repository **`pk7745/erp`** into **[Vercel Dashboard](https://vercel.com)**.
2. The included `vercel.json` will automatically configure WSGI routing.
3. Set environment variables under Project Settings and click **Deploy**.

---

## 📄 License & Credits

Developed with ❤️ for **BMS College of Commerce & Management (Basavanagudi Campus)**.
Released under the [MIT License](LICENSE).
