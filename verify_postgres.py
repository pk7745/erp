import psycopg2, sys
sys.stdout.reconfigure(encoding='utf-8')

uri = 'postgresql://postgres:BmsErp2026!@db.kjgxfdccvsecsyzcmost.supabase.co:5432/postgres'
conn = psycopg2.connect(uri)
cur = conn.cursor()

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
tables = [row[0] for row in cur.fetchall()]
print(f"🐘 Live Supabase PostgreSQL Tables ({len(tables)} total):")
for t in sorted(tables):
    print(f"  - {t}")

cur.execute('SELECT username, role FROM "user"')
users = cur.fetchall()
print("\n👥 Registered Users in PostgreSQL:")
for u in users:
    print(f"  - Username: {u[0]}, Role: {u[1]}")

conn.close()
