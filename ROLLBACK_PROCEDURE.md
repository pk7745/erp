# ROLLBACK PROCEDURE - BMS COLLEGE ERP

Step-by-step instructions to restore the ERP application to its previous state in the event of an emergency.

---

## 🔄 Instant Rollback Steps

### Step 1: Revert Vercel Deployment (If Deployed)
```bash
# Rollback Vercel to previous deployment
vercel rollback
```

### Step 2: Restore Source Code & SQLite Database Backup
```bash
# Navigate to backups folder
cd backups/

# Identify the latest backup directory
ls -la erp-original-*

# Restore database file
cp bms_college_v30_original_*.db ../data/bms_college_v30.db
```

### Step 3: Re-verify Application Functionality
```bash
python verify_data_integrity.py
python test_all_features.py
```
All system services will be fully operational at pre-transformation state.
