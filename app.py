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
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v16.db')
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
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session.update({'user_id': user.id, 'role': user.role, 'name': user.full_name})
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_obj = User.query.get(session['user_id'])
    off_days = Attendance.query.filter_by(user_id=user_obj.id, work_mode='Office').count()
    home_days = Attendance.query.filter_by(user_id=user_obj.id, work_mode='WFH').count()
    
    # HR gets all notifications, Employees get none
    notifications = Notification.query.order_by(Notification.timestamp.desc()).all() if session['role'] == 'HR' else []
    
    # Reports sorted by local time logic
    all_reports = ActivityReport.query.order_by(ActivityReport.timestamp.desc()).all() if session['role'] == 'HR' else ActivityReport.query.filter_by(user_id=user_obj.id).order_by(ActivityReport.timestamp.desc()).all()
    
    return render_template('dashboard.html', user=user_obj, office_days=off_days, wfh_days=home_days, notifications=notifications, reports=all_reports)

@app.route('/clear_notifications')
def clear_notifications():
    if session.get('role') == 'HR':
        Notification.query.delete()
        db.session.commit()
        flash('All notifications cleared', 'success')
    return redirect(url_for('dashboard'))

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    
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
        if leaves_left <= 0:
            flash(f'Monthly leave limit of {LEAVE_LIMIT} days reached!', 'error')
        else:
            new_leave = Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form['reason'])
            db.session.add(new_leave)
            # Notify HR about Leave
            db.session.add(Notification(message=f"LEAVE REQUEST: {session['name']} for {request.form['date']}"))
            db.session.commit()
            flash('Leave Application Submitted', 'success')
            return redirect(url_for('leave'))
    
    leaves = Leave.query.all() if session['role'] == 'HR' else Leave.query.filter_by(user_id=session['user_id']).all()
    return render_template('leave.html', leaves=leaves, leave_limit=LEAVE_LIMIT, leaves_taken=leaves_taken, leaves_left=leaves_left)

@app.route('/approve_leave/<int:id>/<status>')
def approve_leave(id, status):
    if session.get('role') == 'HR':
        req = Leave.query.get(id)
        req.status = status
        db.session.add(Notification(message=f"LEAVE {status.upper()}: Request for {req.user.full_name} updated."))
        db.session.commit()
        flash(f'Leave {status}', 'success')
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
            # HR Notification: Clock In
            db.session.add(Notification(message=f"CLOCK IN: {session['name']} at {time_now} ({mode})"))
        else:
            att.check_out = time_now
            # HR Notification: Clock Out
            db.session.add(Notification(message=f"CLOCK OUT: {session['name']} at {time_now}"))
        db.session.commit()
    
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history, user=user_obj)

@app.route('/submit_report', methods=['POST'])
def submit_report():
    if 'user_id' not in session: return redirect(url_for('login'))
    local_tz = pytz.timezone('Asia/Kolkata')
    local_now = datetime.now(local_tz)
    
    report = ActivityReport(user_id=session['user_id'], content=request.form['content'], timestamp=local_now)
    db.session.add(report)
    # HR Notification: Report Submission
    db.session.add(Notification(message=f"REPORT SUBMITTED: {session['name']} posted an update."))
    db.session.commit()
    flash('Report Submitted', 'success')
    return redirect(url_for('dashboard'))

@app.route('/download_report/<rtype>')
def download_report(rtype):
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt=f"Nexus ERP {rtype.upper()} Report", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=10)
    
    if rtype == 'attendance':
        data = Attendance.query.all() if user.role == 'HR' else Attendance.query.filter_by(user_id=user.id).all()
        for r in data:
            pdf.cell(0, 10, txt=f"{r.date} | {r.user.full_name} | {r.work_mode} | In: {r.check_in} | Out: {r.check_out or '--'}", ln=True)
    else:
        data = ActivityReport.query.all() if user.role == 'HR' else ActivityReport.query.filter_by(user_id=user.id).all()
        for r in data:
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(0, 8, txt=f"{r.user.full_name} - {r.timestamp.strftime('%Y-%m-%d %H:%M')}", ln=True)
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 8, txt=str(r.content))
            pdf.ln(4)
            
    pdf_output = pdf.output(dest='S')
    if isinstance(pdf_output, str): pdf_output = pdf_output.encode('latin-1', 'replace')
    return send_file(io.BytesIO(pdf_output), as_attachment=True, download_name=f"{rtype}_report.pdf", mimetype='application/pdf')

@app.route('/staff_directory')
def staff_directory():
    if 'user_id' not in session: return redirect(url_for('login'))
    users = User.query.all()
    return render_template('staff_directory.html', employees=users)

@app.route('/hr/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') == 'HR':
        new_user = User(
            username=request.form['username'],
            password=generate_password_hash(request.form['password']),
            role='Employee',
            full_name=request.form['full_name'],
            email=request.form['email'],
            salary=request.form['salary'],
            address=request.form['address'],
            dept_id=1
        )
        db.session.add(new_user)
        db.session.commit()
        flash('Employee Added Successfully!', 'success')
    return redirect(url_for('staff_directory'))

@app.route('/remove_employee/<int:uid>')
def remove_employee(uid):
    if session.get('role') == 'HR':
        User.query.filter_by(id=uid).delete()
        db.session.commit()
        flash('Employee Removed.', 'success')
    return redirect(url_for('staff_directory'))

def init_db():
    with app.app_context():
        db.create_all()
        if not Department.query.first():
            db.session.add(Department(name="General Operations"))
            db.session.commit()
        if not User.query.filter_by(username='admin').first():
            hr = User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='pavan kumar', email='pk@nexus.com', salary=95000, address="123 HR Tower, Mumbai", dept_id=1)
            db.session.add(hr)
            db.session.commit()

init_db()

if __name__ == '__main__':
    app.run(debug=True)
