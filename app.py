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
# v22 ensures the 'reason' column is created and all 5 users are added fresh
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v22.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Models ---
class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    users = db.relationship('User', backref='dept', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20)) 
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    salary = db.Column(db.Integer, default=50000)
    address = db.Column(db.String(255), default="Not Set")
    dept_id = db.Column(db.Integer, db.ForeignKey('department.id'))

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.String(20))
    reason = db.Column(db.String(255)) 
    status = db.Column(db.String(20), default='Pending')
    user = db.relationship('User', backref=db.backref('leaves', lazy=True))

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.String(20))
    check_in = db.Column(db.String(20))
    check_out = db.Column(db.String(20))
    work_mode = db.Column(db.String(20)) 
    user = db.relationship('User', backref=db.backref('attendance_records', lazy=True))

class ActivityReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('reports', lazy=True))

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
        try:
            user = User.query.filter_by(username=request.form['username']).first()
            if user and check_password_hash(user.password, request.form['password']):
                session.update({'user_id': user.id, 'role': user.role, 'name': user.full_name})
                return redirect(url_for('dashboard'))
            flash('Invalid Credentials', 'error')
        except Exception as e:
            return f"Database Error: {str(e)}"
    return render_template('login.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        user = User.query.filter_by(username=username).first()
        if user:
            db.session.add(Notification(message=f"PASSWORD RESET REQUEST: '{username}'"))
            db.session.commit()
            flash('Request sent to HR.', 'success')
            return redirect(url_for('login'))
        flash('Username not found.', 'error')
    return render_template('forgot_password.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_obj = User.query.get(session['user_id'])
    if not user_obj: return redirect(url_for('logout'))
    
    notifications = Notification.query.order_by(Notification.timestamp.desc()).all() if session['role'] == 'HR' else []
    all_reports = ActivityReport.query.order_by(ActivityReport.timestamp.desc()).all() if session['role'] == 'HR' else ActivityReport.query.filter_by(user_id=user_obj.id).order_by(ActivityReport.timestamp.desc()).all()
    return render_template('dashboard.html', user=user_obj, notifications=notifications, reports=all_reports)

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # 1. Define variables clearly for the template
    LEAVE_LIMIT = 2 
    local_tz = pytz.timezone('Asia/Kolkata')
    current_month = datetime.now(local_tz).strftime("%Y-%m")
    
    leaves_taken = Leave.query.filter(
        Leave.user_id == session['user_id'], 
        Leave.date.like(f"{current_month}%"), 
        Leave.status != 'Rejected'
    ).count()
    
    leaves_left = max(0, LEAVE_LIMIT - leaves_taken)

    if request.method == 'POST':
        if leaves_left > 0:
            # 2. Match the name="reason" from your HTML
            reason_text = request.form.get('reason', 'N/A')
            new_leave = Leave(user_id=session['user_id'], date=request.form['date'], reason=reason_text)
            db.session.add(new_leave)
            db.session.add(Notification(message=f"LEAVE REQUEST: {session['name']} for {request.form['date']}"))
            db.session.commit()
            flash('Application Submitted!', 'success')
            return redirect(url_for('leave'))
        else:
            flash('Limit reached!', 'error')
    
    # 3. Fetch data for log
    leaves = Leave.query.all() if session['role'] == 'HR' else Leave.query.filter_by(user_id=session['user_id']).all()
    
    # 4. Return ALL variables the HTML asks for
    return render_template('leave.html', 
                           leaves=leaves, 
                           leave_limit=LEAVE_LIMIT, 
                           leaves_taken=leaves_taken, 
                           leaves_left=leaves_left)

@app.route('/approve_leave/<int:id>/<status>')
def approve_leave(id, status):
    if session.get('role') == 'HR':
        req = Leave.query.get(id)
        if req:
            req.status = status
            db.session.add(Notification(message=f"LEAVE {status.upper()}: {req.user.full_name}"))
            db.session.commit()
    return redirect(url_for('leave'))

@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_obj = User.query.get(session['user_id'])
    local_tz = pytz.timezone('Asia/Kolkata') 
    now = datetime.now(local_tz)
    today = now.strftime("%Y-%m-%d")

    if request.method == 'POST':
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        time_now = now.strftime("%I:%M %p") 
        if not att:
            mode = request.form.get('work_mode')
            db.session.add(Attendance(user_id=session['user_id'], date=today, check_in=time_now, work_mode=mode))
            db.session.add(Notification(message=f"CLOCK IN: {session['name']} ({mode})"))
        else:
            att.check_out = time_now
            db.session.add(Notification(message=f"CLOCK OUT: {session['name']}"))
        db.session.commit()
    
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history, user=user_obj)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

def init_db():
    with app.app_context():
        db.create_all()
        if not Department.query.first():
            db.session.add(Department(name="General Operations"))
            db.session.commit()

        if not User.query.filter_by(username='admin').first():
            hr = User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='pavan kumar', email='pk@nexus.com', salary=95000, address="123 HR Tower", dept_id=1)
            e1 = User(username='emp1', password=generate_password_hash('pass123'), role='Employee', full_name='John Dsouza', email='john@nexus.com', salary=55000, address="New Delhi", dept_id=1)
            e2 = User(username='emp2', password=generate_password_hash('pass123'), role='Employee', full_name='Kartik Sharma', email='kar@nexus.com', salary=62000, address="Bangalore", dept_id=1)
            e3 = User(username='emp3', password=generate_password_hash('pass123'), role='Employee', full_name='Pranav Avadhani', email='pr@nexus.com', salary=48000, address="Gurgaon", dept_id=1)
            e4 = User(username='emp4', password=generate_password_hash('pass123'), role='Employee', full_name='Parthiv Reddy', email='red@nexus.com', salary=51000, address="Kochi", dept_id=1)
            db.session.add_all([hr, e1, e2, e3, e4])
            db.session.commit()

init_db()

if __name__ == '__main__':
    app.run()
