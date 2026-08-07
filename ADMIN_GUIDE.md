# ADMIN GUIDE - BMS COLLEGE ERP

Guide for System Administrators managing the BMS College ERP application and PostgreSQL database.

---

## 🛠️ System Administration Tasks

### 1. Running Database Migrations
To migrate SQLite data to a new PostgreSQL instance:
```bash
# 1. Update DATABASE_URL in .env
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# 2. Run migration script
python migrate_sqlite_to_postgresql.py

# 3. Verify integrity
python verify_data_integrity.py
```

### 2. Backups & Snapshots
To manually generate a full backup of the codebase and SQLite database:
```bash
python generate_analysis.py
```
Backups are archived automatically in the `backups/` directory.

### 3. Reviewing Audit Logs
Log in as Principal or Admin and navigate to `/audit_logs` to view system activity logs, user logins, and administrative modifications.
