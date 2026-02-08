import os
import io
import pytz
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "nexus_sync_2026_final"

# Database Configuration - Using v101 to ensure 'reason' column exists
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v101.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='Employee')
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    salary = db.Column(db.Integer, default=50000)
    address = db.Column(db.String(200))
    leaves = db.relationship('Leave', backref='user', lazy=True)
    attendance = db.relationship('Attendance', backref='user', lazy=True)

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(20))
    reason = db.Column(db.String(255), default="No reason provided")
    status = db.Column(db.String(20), default='Pending')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(20))
    check_in = db.Column(db.String(20))
    check_out = db.Column(db.String(20))
    work_mode = db.Column(db.String(20))

class ActivityReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationship for PDF export
    rel_user = db.relationship('User', backref='activity_reports', lazy=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- Routes ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            session['role'] = user.role
            session['name'] = user.full_name
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials', 'error')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    notifs = Notification.query.order_by(Notification.timestamp.desc()).all() if session['role'] == 'HR' else []
    off = Attendance.query.filter_by(user_id=user.id, work_mode='Office').count()
    wfh = Attendance.query.filter_by(user_id=user.id, work_mode='WFH').count()
    return render_template('dashboard.html', user=user, notifications=notifs, office_days=off, wfh_days=wfh)

@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: return redirect(url_for('login'))
    tz = pytz.timezone('Asia/Kolkata')
    today = datetime.now(tz).strftime("%Y-%m-%d")
    if request.method == 'POST':
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        time_now = datetime.now(tz).strftime("%I:%M %p")
        if not att:
            db.session.add(Attendance(user_id=session['user_id'], date=today, check_in=time_now, work_mode=request.form.get('work_mode')))
            db.session.add(Notification(message=f"CLOCK IN: {session['name']}"))
        else:
            att.check_out = time_now
            db.session.add(Notification(message=f"CLOCK OUT: {session['name']}"))
        db.session.commit()
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history)

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    tz = pytz.timezone('Asia/Kolkata')
    month = datetime.now(tz).strftime("%Y-%m")
    taken = Leave.query.filter(Leave.user_id == session['user_id'], Leave.date.like(f"{month}%"), Leave.status != 'Rejected').count()
    left = max(0, 2 - taken)
    if request.method == 'POST' and left > 0:
        db.session.add(Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form.get('reason', 'N/A')))
        db.session.add(Notification(message=f"LEAVE REQUEST: {session['name']}"))
        db.session.commit()
        flash('Leave applied successfully!', 'success')
        return redirect(url_for('leave'))
    leaves = Leave.query.all() if session['role'] == 'HR' else Leave.query.filter_by(user_id=session['user_id']).all()
    return render_template('leave.html', leaves=leaves, leave_limit=2, leaves_taken=taken, leaves_left=left)

@app.route('/approve_leave/<int:id>/<status>')
def approve_leave(id, status):
    if session.get('role') == 'HR':
        l = Leave.query.get(id)
        # FEATURE: HR cannot approve/reject their own leave
        if l and l.user.role != 'HR':
            l.status = status
            db.session.commit()
    return redirect(url_for('leave'))

@app.route('/staff_directory')
def staff_directory():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('staff_directory.html', employees=User.query.all())

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') == 'HR':
        new_u = User(
            username=request.form['username'], 
            password=generate_password_hash(request.form['password']), 
            role='Employee', 
            full_name=request.form['full_name'], 
            email=request.form['email'], 
            salary=int(request.form['salary']), 
            address=request.form['address']
        )
        db.session.add(new_u)
        db.session.commit()
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
    flash('Report submitted!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/download_report/<rtype>')
def download_report(rtype):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt=f"Nexus Enterprise - {rtype.upper()} Report", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=10)
    
    if rtype == 'attendance':
        data = Attendance.query.all()
        for r in data:
            pdf.cell(0, 10, txt=f"Date: {r.date} | Name: {r.user.full_name} | Mode: {r.work_mode} | In: {r.check_in} | Out: {r.check_out}", ln=True)
    else:
        data = ActivityReport.query.all()
        for r in data:
            pdf.cell(0, 10, txt=f"Date: {r.timestamp.strftime('%Y-%m-%d')} | Name: {r.rel_user.full_name}", ln=True)
            pdf.multi_cell(0, 10, txt=f"Content: {r.content}")
            pdf.ln(2)
            
    out = pdf.output(dest='S').encode('latin-1')
    return send_file(io.BytesIO(out), as_attachment=True, download_name=f"{rtype}_report.pdf", mimetype='application/pdf')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        db.session.add(Notification(message=f"RESET REQUEST: {request.form['username']}"))
        db.session.commit()
        flash('HR Notified!', 'success')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- DB Setup ---
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='pavan kumar', email='pk@nexus.com', salary=95000, address="HQ")
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run()
