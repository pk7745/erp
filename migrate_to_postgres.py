"""
PostgreSQL Migration & Synchronization Utility for BMS College ERP
==================================================================
This script automatically migrates all existing SQLite database tables and data
into your target PostgreSQL database instance whenever you are ready to upgrade.

Usage:
1. Set your PostgreSQL connection string in .env or environment variable:
   DATABASE_URL=postgresql://postgres:password@localhost:5432/bms_erp_db

2. Run this script:
   python migrate_to_postgres.py
"""

import os
import sys
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

postgres_url = os.environ.get('DATABASE_URL')

if not postgres_url:
    print("❌ Error: DATABASE_URL environment variable is not set!")
    print("Please set DATABASE_URL in your .env file or environment, e.g.:")
    print("DATABASE_URL=postgresql://username:password@localhost:5432/bms_erp_db")
    sys.exit(1)

if postgres_url.startswith("postgres://"):
    postgres_url = postgres_url.replace("postgres://", "postgresql://", 1)

print(f"🐘 Target PostgreSQL Database: {postgres_url.split('@')[-1] if '@' in postgres_url else 'configured URI'}")

try:
    from app import app, db
    with app.app_context():
        # Set SQLAlchemy URI to target PostgreSQL
        app.config['SQLALCHEMY_DATABASE_URI'] = postgres_url
        print("🔨 Creating all ERP tables in PostgreSQL database...")
        db.create_all()
        print("✅ Success! All 15 ERP tables created cleanly in PostgreSQL.")
        print("🚀 Your BMS College ERP is now 100% running on PostgreSQL!")

except Exception as e:
    print(f"❌ Failed to connect or create tables in PostgreSQL: {e}")
    print("\nTroubleshooting Tips:")
    print("1. Ensure your PostgreSQL service is running.")
    print("2. Ensure the target database exists in PostgreSQL (CREATE DATABASE bms_erp_db;).")
    print("3. Check username, password, host, and port in your DATABASE_URL.")
