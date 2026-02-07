from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import io
import os
import pytz 
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "nexus_enterprise_ultimate_2026"

# --- Database Config ---
basedir = os.path.abspath(os.path.dirname(__file__))
# Using v31 to ensure a fresh start on deployment
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v31.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20)) 
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    salary = db.Column(db.Integer, default=50000)
    address = db.Column(db.String(255), default="Not Set")
    leaves = db.relationship('Leave', backref='user', lazy=True)
    attendance = db.relationship('Attendance', backref='user', lazy=True)

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.String(20))
    reason = db.Column(db.String(255), default="No reason provided") 
    status = db.Column(db.String(20), default='Pending')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.String(20))
    check_in = db.Column(db.String(20))
    check_out = db.Column(db.String(20))
    work_mode = db.Column(db.String(20))

class ActivityReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- Routes ---

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session.clear()
            session.update({'user_id': user.id, 'role': user.role, 'name': user.full_name})
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials', 'error')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_obj = User.query.get(session['user_id'])
    
    # Safety check: if user was deleted but session remains
    if not user_obj:
        session.clear()
        return redirect(url_for('login'))

    notifs = Notification.query.order_by(Notification.timestamp.desc()).all() if session['role'] == 'HR' else []
    
    # Stats logic with error handling
    try:
        off_d = Attendance.query.filter_by(user_id=user_obj.id, work_mode='Office').count()
        wfh_d = Attendance.query.filter_by(user_id=user_obj.id, work_mode='WFH').count()
    except:
        off_d, wfh_d = 0, 0

    return render_template('dashboard.html', user=user_obj, notifications=notifs, office_days=off_d, wfh_days=wfh_d)

@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: return redirect(url_for('login'))
    tz = pytz.timezone('Asia/Kolkata')
    today = datetime.now(tz).strftime("%Y-%m-%d")
    
    if request.method == 'POST':
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        now_str = datetime.now(tz).strftime("%I:%M %p")
        if not att:
            # Check In
            db.session.add(Attendance(user_id=session['user_id'], date=today, check_in=now_str, work_mode=request.form.get('work_mode')))
            db.session.add(Notification(message=f"CLOCK IN: {session['name']}"))
        else:
            # Check Out
            att.check_out = now_str
            db.session.add(Notification(message=f"CLOCK OUT: {session['name']}"))
        db.session.commit()
    
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history)

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    LIMIT = 2
    tz = pytz.timezone('Asia/Kolkata')
    curr_month = datetime.now(tz).strftime("%Y-%m")
    
    # Calculate taken leaves (excluding rejected)
    taken = Leave.query.filter(Leave.user_id == session['user_id'], Leave.date.like(f"{curr_month}%"), Leave.status != 'Rejected').count()
    left = max(0, LIMIT - taken)

    if request.method == 'POST':
        if left > 0:
            db.session.add(Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form.get('reason', 'N/A')))
            db.session.add(Notification(message=f"LEAVE REQUEST: {session['name']}"))
            db.session.commit()
            flash('Leave Applied', 'success')
        else:
            flash('Limit Reached', 'error')
        return redirect(url_for('leave'))
        
    leaves = Leave.query.all() if session['role'] == 'HR' else Leave.query.filter_by(user_id=session['user_id']).all()
    return render_template('leave.html', leaves=leaves, leave_limit=LIMIT, leaves_taken=taken, leaves_left=left)

@app.route('/approve_leave/<int:id>/<status>')
def approve_leave(id, status):
    if session.get('role') == 'HR':
        l = Leave.query.get(id)
        # Requirement: HR cannot approve their own leaves
        if l and l.user.role != 'HR':
            l.status = status
            db.session.add(Notification(message=f"LEAVE {status.upper()}: {l.user.full_name}"))
            db.session.commit()
    return redirect(url_for('leave'))

@app.route('/staff_directory')
def staff_directory():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('staff_directory.html', employees=User.query.all())

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') == 'HR':
        try:
            new_user = User(
                username=request.form['username'], 
                password=generate_password_hash(request.form['password']), 
                role='Employee', 
                full_name=request.form['full_name'], 
                email=request.form['email'], 
                salary=int(request.form['salary']), 
                address=request.form['address']
            )
            db.session.add(new_user)
            db.session.commit()
        except:
            flash('Error adding employee. Username might exist.', 'error')
    return redirect(url_for('staff_directory'))

@app.route('/remove_employee/<int:uid>')
def remove_employee(uid):
    if session.get('role') == 'HR':
        u = User.query.get(uid)
        if u and u.role != 'HR':
            db.session.delete(u)
            db.session.commit()
    return redirect(url_for('staff_directory'))

@app.route('/submit_report', methods=['POST'])
def submit_report():
    if 'user_id' not in session: return redirect(url_for('login'))
    db.session.add(ActivityReport(user_id=session['user_id'], content=request.form['content']))
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/download_report/<rtype>')
def download_report(rtype):
    if 'user_id' not in session: return redirect(url_for('login'))
    # PDF Logic
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Nexus {rtype.upper()} Report", ln=True, align='C')
    pdf.ln(10)
    
    # Fetch Data safely
    data = []
    if rtype == 'attendance':
        items = Attendance.query.all()
        for i in items:
            data.append(f"{i.date} | {i.user.full_name} | {i.work_mode}")
    else:
        items = ActivityReport.query.all()
        for i in items:
            data.append(f"{i.timestamp.strftime('%Y-%m-%d')} | {i.user.full_name}")

    for line in data:
        pdf.cell(0, 10, txt=line, ln=True)
        
    out = pdf.output(dest='S')
    return send_file(io.BytesIO(out), as_attachment=True, download_name=f"{rtype}.pdf", mimetype='application/pdf')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        db.session.add(Notification(message=f"RESET REQUEST: {request.form['username']}"))
        db.session.commit()
        flash('HR has been notified.', 'success')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/clear_notifications')
def clear_notifications():
    if session.get('role') == 'HR':
        Notification.query.delete()
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- DB INITIALIZATION (Safe Mode) ---
def init_db():
    try:
        with app.app_context():
            db.create_all()
            if not User.query.filter_by(username='admin').first():
                hr = User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='pavan kumar', email='pk@nexus.com', salary=95000, address="Head Office")
                e1 = User(username='emp1', password=generate_password_hash('pass123'), role='Employee', full_name='John Dsouza', email='john@nexus.com', salary=50000)
                e2 = User(username='emp2', password=generate_password_hash('pass123'), role='Employee', full_name='Kartik Sharma', email='k@nexus.com', salary=50000)
                e3 = User(username='emp3', password=generate_password_hash('pass123'), role='Employee', full_name='Pranav Avadhani', email='p@nexus.com', salary=50000)
                e4 = User(username='emp4', password=generate_password_hash('pass123'), role='Employee', full_name='Parthiv Reddy', email='pr@nexus.com', salary=50000)
                db.session.add_all([hr, e1, e2, e3, e4])
                db.session.commit()
            print("Database initialized successfully!")
    except Exception as e:
        print(f"DB Init Skipped (Build Phase): {e}")

# Only run init_db if this file is run directly, NOT during build
if __name__ == '__main__':
    init_db()
    app.run()
else:
    # If running via Gunicorn, we still need to init DB, but safely
    init_db()
