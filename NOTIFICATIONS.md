# BMS College ERP — Centralized Email Notification Engine

## Overview & Architecture

The BMS College ERP features a **centralized, event-driven Email Notification Engine**. Instead of scattering SMTP email code across routes, all system events call a single function:

```python
notify(event, user, context=None)
```

### Core Architecture Principles:
1. **Single Entry Point**: All institutional alerts flow through `notify(event, user, context)`.
2. **Reusable Infrastructure**: Uses Flask-Mail with Gmail SMTP (`smtp.gmail.com:587`, TLS) using `MAIL_USERNAME` and `MAIL_PASSWORD` (16-character Gmail App Password).
3. **PDF Attachment Support**: Supports generated PDF attachments (e.g., official monthly payslips).
4. **Fail-Safe Guarantee**: If an email send fails (invalid email, network error, or missing credentials), the engine logs the attempt to `NotificationLog` in **Supabase PostgreSQL** and **NEVER crashes** salary runs, logins, leave approvals, or task assignments.
5. **Auditable History**: Every dispatch attempt is logged to `notification_log` and mirrored to `audit_log`.

---

## The 8-Event Routing Map

| # | Event Key | Trigger Location | Attachment | Event Context & Data |
|---|---|---|---|---|
| 1 | `salary_credited` | `/edit_salary/<uid>` or bulk payroll run | 📄 Payslip PDF | Month, Net Amount, Salary details |
| 2 | `payslip_delivery` | `/send_payslip_email/<uid>` | 📄 Payslip PDF | Month, Verification Code |
| 3 | `leave_decision` | `/leave/action/<id>/<action>` | — | Status (Approved/Rejected), Rejection Reason, Date |
| 4 | `expense_decision` | `/approve_expense/<id>/<action>` | — | Status, Claim Amount, Category |
| 5 | `task_assigned` | `/assign_task` | — | Task Title, Assigner Name, Due Status |
| 6 | `new_device_login` | `/login` (Unrecognized Device) | — | IP Address, Browser / User Agent, Timestamp |
| 7 | `missing_checkout` | `/attendance/daily_close` | — | Attendance Date |
| 8 | `monthly_attendance_summary` | `/attendance/monthly_summary` | — | Month, Present Days, Late Arrivals, Unrecorded Check-outs |
| * | `selftest` | `/notifications/selftest` | — | Live System Diagnostic Test |

---

## Technical & Cost Justification (Email-First Architecture)

- **Cost**: **100% Free** via standard institutional Gmail SMTP.
- **Production Readiness**: Requires no third-party Meta Business verification (WhatsApp API) or DLT registration (SMS Gateways).
- **Zero Friction**: Delivers directly to all registered staff email addresses without mandatory opt-in messages.

---

## Developer Self-Test & Diagnostic Tool

Admin and HR users can access the **Notification Diagnostic Hub** at:
**[http://127.0.0.1:9000/notifications/selftest](http://127.0.0.1:9000/notifications/selftest)**

### Self-Test Steps:
1. Log in as Admin (`admin` / `bms123`).
2. Navigate to **Notification Hub** in the left sidebar under *Administrative*.
3. Enter your developer Gmail address under **Developer Test Recipient Credentials** and click **Save Recipient Credentials**.
4. Click **`⚡ Run Live Self-Test`**.
5. Check your Gmail inbox (and Spam/Promotions folder) for the test email.
6. Observe the live audit table showing `SENT` status and dispatch details.

---

## Verification & Test Checklist

- [x] **Database Migration**: `notification_log` table created in Supabase PostgreSQL.
- [x] **Email Dispatch**: Verified Flask-Mail integration.
- [x] **Fail-Safe Check**: Invalid email logs `FAILED` and does not crash Flask app.
- [x] **Self-Test Hub**: Live route `/notifications/selftest` operational.
- [x] **Event 1 (Salary Credited)**: Triggers email with Payslip PDF attachment.
- [x] **Event 2 (Payslip Delivery)**: Reuses `generate_payslip` logic.
- [x] **Event 3 (Leave Decision)**: Sends approval/rejection with reason.
- [x] **Event 4 (Expense Decision)**: Sends status update with amount & category.
- [x] **Event 5 (Task Assigned)**: Sends task title and assigner name.
- [x] **Event 6 (New Device Login)**: Triggers security alert on unrecognized device.
- [x] **Event 7 (Missing Check-Out)**: Triggers evening check-out nudge.
- [x] **Event 8 (Monthly Attendance Summary)**: Dispatches monthly metrics summary.
