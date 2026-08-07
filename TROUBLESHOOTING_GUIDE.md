# TROUBLESHOOTING GUIDE - BMS COLLEGE ERP

Quick solutions for common issues during development or deployment.

---

## ❓ Frequently Encountered Issues

### 1. `psycopg2.OperationalError: could not connect to server`
- **Cause**: Incorrect database connection credentials or PostgreSQL service is stopped.
- **Solution**: Verify `DATABASE_URL` in `.env` or Vercel Environment Variables. Ensure PostgreSQL container or service is active.

### 2. `sqlalchemy.exc.OperationalError: table user has no column named ...`
- **Cause**: Schema mismatch between SQLite and target database.
- **Solution**: Run `python migrate_sqlite_to_postgresql.py` which executes `db.create_all()` via SQLAlchemy models to automatically harmonize schema.

### 3. Vercel Deployment Returns 500 Error
- **Cause**: Missing environment variable (`DATABASE_URL` or `SECRET_KEY`).
- **Solution**: Check Vercel project logs (`vercel logs [deployment-url]`) and add missing variables in Vercel Dashboard Settings.
