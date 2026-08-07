import sqlite3
import psycopg2
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

class DataMigrator:
    def __init__(self):
        self.base_dir = r"C:\Users\pky45\.gemini\antigravity\scratch\erp"
        self.sqlite_db = os.path.join(self.base_dir, "data", "bms_college_v30.db")
        self.log_file = os.path.join(self.base_dir, "migration_log.txt")
        self.errors = []
        self.stats = {}
        
    def log(self, message):
        """Log all operations"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        print(log_entry)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception:
            pass
    
    def connect_sqlite(self):
        """Connect to SQLite"""
        try:
            if not os.path.exists(self.sqlite_db):
                self.log(f"❌ SQLite file missing at {self.sqlite_db}")
                return False
            self.sqlite_conn = sqlite3.connect(self.sqlite_db)
            self.sqlite_cursor = self.sqlite_conn.cursor()
            self.log("✅ Connected to SQLite database")
            return True
        except Exception as e:
            self.log(f"❌ SQLite connection failed: {e}")
            return False

    def get_all_tables(self):
        """Get all table names from SQLite"""
        try:
            self.sqlite_cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence';"
            )
            tables = [row[0] for row in self.sqlite_cursor.fetchall()]
            self.log(f"📊 Found {len(tables)} tables: {tables}")
            return tables
        except Exception as e:
            self.log(f"❌ Error reading tables: {e}")
            return []

    def get_table_data(self, table_name):
        """Get all data from SQLite table"""
        try:
            self.sqlite_cursor.execute(f'SELECT * FROM "{table_name}";')
            rows = self.sqlite_cursor.fetchall()
            columns = [description[0] for description in self.sqlite_cursor.description]
            self.log(f"  Reading {table_name}: {len(rows)} records")
            return columns, rows
        except Exception as e:
            self.log(f"❌ Error reading data from {table_name}: {e}")
            return [], []

    def create_tables_in_target(self):
        """Create all tables in target database using SQLAlchemy models"""
        try:
            self.log("🔧 Creating tables via SQLAlchemy models...")
            sys.path.insert(0, self.base_dir)
            from app import app, db
            
            with app.app_context():
                db.create_all()
                self.log("✅ All tables initialized in database context")
                return True
        except Exception as e:
            self.log(f"❌ Error creating tables: {e}")
            self.errors.append(str(e))
            return False

    def migrate_table_data(self, table_name, columns, rows):
        """Migrate data using SQLAlchemy engine execute or raw SQL connection"""
        try:
            if not rows:
                self.log(f"  ⚠️  {table_name}: No data to migrate")
                self.stats[table_name] = 0
                return True
            
            from app import app, db
            with app.app_context():
                # Clear existing data in target table to allow idempotent migration
                table_name_quoted = f'"{table_name}"'
                try:
                    db.session.execute(db.text(f"DELETE FROM {table_name_quoted}"))
                    db.session.commit()
                except Exception as del_err:
                    db.session.rollback()

                placeholders = ",".join([f":col_{i}" for i in range(len(columns))])
                col_names = ",".join([f'"{col}"' for col in columns])
                insert_sql = db.text(f"INSERT INTO {table_name_quoted} ({col_names}) VALUES ({placeholders})")
                
                migrated_count = 0
                for row_idx, row in enumerate(rows):
                    param_dict = {f"col_{i}": row[i] for i in range(len(row))}
                    try:
                        db.session.execute(insert_sql, param_dict)
                        migrated_count += 1
                    except Exception as row_err:
                        self.log(f"  ⚠️ Row {row_idx+1} in {table_name} error: {row_err}")
                        self.errors.append(f"{table_name} row {row_idx+1}: {row_err}")
                
                db.session.commit()
                self.stats[table_name] = migrated_count
                self.log(f"✅ {table_name}: {migrated_count}/{len(rows)} records migrated successfully")
                return True
        except Exception as e:
            self.log(f"❌ Error migrating table {table_name}: {e}")
            self.errors.append(f"{table_name}: {e}")
            return False

    def verify_migration(self):
        """Verify data integrity between SQLite and target database"""
        self.log("\n🔍 VERIFYING MIGRATION INTEGRITY...\n")
        try:
            tables = self.get_all_tables()
            from app import app, db
            
            all_matched = True
            with app.app_context():
                for table in tables:
                    self.sqlite_cursor.execute(f'SELECT COUNT(*) FROM "{table}";')
                    sqlite_count = self.sqlite_cursor.fetchone()[0]
                    
                    target_res = db.session.execute(db.text(f'SELECT COUNT(*) FROM "{table}"')).fetchone()
                    target_count = target_res[0] if target_res else 0
                    
                    if sqlite_count == target_count:
                        self.log(f"✅ {table:20} | SQLite: {sqlite_count:4} | Target DB: {target_count:4} (VERIFIED)")
                    else:
                        self.log(f"❌ {table:20} | SQLite: {sqlite_count:4} | Target DB: {target_count:4} (MISMATCH!)")
                        self.errors.append(f"{table}: Count mismatch! SQLite={sqlite_count}, Target={target_count}")
                        all_matched = False
            return all_matched
        except Exception as e:
            self.log(f"❌ Verification failed: {e}")
            return False

    def run_migration(self):
        """Execute complete migration pipeline"""
        self.log("\n" + "="*80)
        self.log("🚀 STARTING DATA MIGRATION PIPELINE")
        self.log("="*80 + "\n")
        
        if not self.connect_sqlite():
            return False
        
        tables = self.get_all_tables()
        if not tables:
            return False
        
        if not self.create_tables_in_target():
            return False
        
        self.log("\n📦 MIGRATING TABLE DATA...\n")
        for table in tables:
            columns, rows = self.get_table_data(table)
            if columns:
                self.migrate_table_data(table, columns, rows)
        
        passed = self.verify_migration()
        
        self.log("\n" + "="*80)
        self.log("📊 MIGRATION SUMMARY")
        self.log("="*80)
        total_migrated = sum(self.stats.values())
        self.log(f"✅ TOTAL RECORDS MIGRATED: {total_migrated}")
        
        if self.errors:
            self.log(f"⚠️ {len(self.errors)} WARNINGS/ERRORS ENCOUNTERED:")
            for err in self.errors:
                self.log(f"  - {err}")
        else:
            self.log("✅ ZERO ERRORS - MIGRATION 100% PERFECT!")
        
        self.log(f"VERIFICATION STATUS: {'✅ PASSED' if passed else '❌ FAILED'}")
        self.log("="*80 + "\n")
        
        self.sqlite_conn.close()
        return passed

if __name__ == "__main__":
    migrator = DataMigrator()
    success = migrator.run_migration()
    sys.exit(0 if success else 1)
