import sys
from werkzeug.security import generate_password_hash
from app import app, db, User

sys_stdout_reconfig = getattr(sys.stdout, 'reconfigure', None)
if sys_stdout_reconfig: sys.stdout.reconfigure(encoding='utf-8')

new_hashed_pw = generate_password_hash('bms123')

with app.app_context():
    users = User.query.all()
    print(f"Found {len(users)} users in database. Updating all passwords to 'bms123' while preserving names...")
    
    for u in users:
        u.password = new_hashed_pw
        print(f" - [{u.username}] Full Name: {u.full_name} | Role: {u.role} -> Password updated to 'bms123'")
        
    db.session.commit()
    print("\nSUCCESS: All user passwords updated to 'bms123' in database with zero alteration to names, roles, or codes!")
