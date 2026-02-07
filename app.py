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
# v26 ensures all features (Attendance, Reports, Leaves) have the correct columns
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v26.db')
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
            session.clear()
            session.update({'user_id': user.id, 'role': user.role, 'name': user.full_name})
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials', 'error')
    return render_template('login.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        user = User.query.filter_by(username=username).first()
        if user:
            db.session.add(Notification(message=f"PASSWORD RESET REQUEST: '{username}'"))
            db.session.commit()
            flash('HR has been notified.', 'success')
            return redirect(url_for('login'))
        flash('Username not found.', 'error')
    return render_template('forgot_password.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_obj = User.query.get(session['user_id'])
    
    # Calculate Office vs WFH days for the stats cards
    office_days = Attendance.query.filter_by(user_id=user_obj.id, work_mode='Office').count()
    wfh_days = Attendance.query.filter_by(user_id=user_obj.id, work_mode='WFH').count()
    
    notifications = Notification.query.order_by(Notification.timestamp.desc()).all() if session['role'] == 'HR' else []
    
    return render_template('dashboard.html', 
                           user=user_obj, 
                           notifications=notifications, 
                           office_days=office_days, 
                           wfh_days=wfh_days)

@app.route('/clear_notifications')
def clear_notifications():
    if session.get('role') == 'HR':
        Notification.query.delete()
        db.session.commit()
        flash('All notifications cleared', 'success')
    return redirect(url_for('dashboard'))
    
@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: return redirect(url_for('login'))
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
    return render_template('attendance.html', history=history, user=User.query.get(session['user_id']))

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    # 1. Logic for the current user
    user_obj = User.query.get(session['user_id'])
    LEAVE_LIMIT = 2 # Monthly limit
    
    local_tz = pytz.timezone('Asia/Kolkata')
    current_month = datetime.now(local_tz).strftime("%Y-%m")
    
    # 2. Calculate leave stats
    leaves_taken = Leave.query.filter(
        Leave.user_id == session['user_id'], 
        Leave.date.like(f"{current_month}%"), 
        Leave.status != 'Rejected'
    ).count()
    
    leaves_left = max(0, LEAVE_LIMIT - leaves_taken)

    # 3. Handle Form Submission
    if request.method == 'POST':
        if leaves_left > 0:
            new_leave = Leave(
                user_id=session['user_id'], 
                date=request.form.get('date'), 
                reason=request.form.get('reason', 'N/A')
            )
            db.session.add(new_leave)
            db.session.add(Notification(message=f"LEAVE REQUEST: {session['name']}"))
            db.session.commit()
            flash('Leave application submitted!', 'success')
            return redirect(url_for('leave'))
        else:
            flash('Monthly leave limit reached!', 'error')

    # 4. Fetch the log (HR sees all, Employees see only theirs)
    if session['role'] == 'HR':
        leaves = Leave.query.all()
    else:
        leaves = Leave.query.filter_by(user_id=session['user_id']).all()
    
    # 5. SYNC CHECK: This return statement sends ALL variables the HTML asks for
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

@app.route('/submit_report', methods=['POST'])
def submit_report():
    if 'user_id' not in session: return redirect(url_for('login'))
    report = ActivityReport(user_id=session['user_id'], content=request.form['content'])
    db.session.add(report)
    db.session.add(Notification(message=f"REPORT: {session['name']}"))
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/download_report/<rtype>')
def download_report(rtype):
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Nexus {rtype.upper()} Report", ln=True, align='C')
    
    data = Attendance.query.all() if rtype == 'attendance' else ActivityReport.query.all()
    # Simplified PDF generation logic for reliability
    for item in data:
        pdf.cell(200, 10, txt=f"Entry: {item.user.full_name}", ln=True)
            
    pdf_output = pdf.output(dest='S')
    return send_file(io.BytesIO(pdf_output), as_attachment=True, download_name=f"{rtype}.pdf", mimetype='application/pdf')

@app.route('/staff_directory')
def staff_directory():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('staff_directory.html', employees=User.query.all())

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') == 'HR':
        username = request.form['username']
        # Check if username already exists to prevent crash
        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return redirect(url_for('staff_directory'))
            
        new_emp = User(
            username=username,
            password=generate_password_hash(request.form['password']),
            role='Employee',
            full_name=request.form['full_name'],
            email=request.form['email'],
            salary=int(request.form['salary']),
            address=request.form['address'],
            dept_id=1
        )
        db.session.add(new_emp)
        db.session.commit()
        flash(f"Employee {username} added successfully!", "success")
    return redirect(url_for('staff_directory'))

@app.route('/remove_employee/<int:uid>')
def remove_employee(uid):
    if session.get('role') == 'HR':
        user_to_del = User.query.get(uid)
        if user_to_del and user_to_del.role != 'HR':
            db.session.delete(user_to_del)
            db.session.commit()
            flash("Employee removed from directory.", "success")
    return redirect(url_for('staff_directory'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            dept = Department(name="General")
            db.session.add(dept)
            db.session.commit()
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



