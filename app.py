import os
import io
import pytz
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "nexus_enterprise_v105_ultra"

# Database Configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v103.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Helper for IST Time
def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata'))

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
    # Relationships
    leaves = db.relationship('Leave', backref='user', lazy=True)
    attendance = db.relationship('Attendance', backref='user', lazy=True)
    tasks = db.relationship('Task', backref='user', lazy=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(20))
    check_in = db.Column(db.String(20))
    check_out = db.Column(db.String(20))
    work_mode = db.Column(db.String(20))

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(20))
    reason = db.Column(db.String(255), default="No reason provided")
    status = db.Column(db.String(20), default='Pending')

class ActivityReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=get_ist_time)
    rel_user = db.relationship('User', backref='activity_reports', lazy=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=get_ist_time)

# --- NEW MODELS ---

class PerformanceKPI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    month = db.Column(db.String(20))
    rating = db.Column(db.Integer)
    feedback = db.Column(db.String(255))
    rel_user = db.relationship('User', backref='kpis', lazy=True)

class ExpenseClaim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category = db.Column(db.String(50))
    amount = db.Column(db.Float)
    status = db.Column(db.String(20), default='Pending')
    description = db.Column(db.String(255))
    rel_user = db.relationship('User', backref='claims', lazy=True)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100))
    is_done = db.Column(db.Boolean, default=False)

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
    tasks = Task.query.filter_by(user_id=user.id).all()
    off = Attendance.query.filter_by(user_id=user.id, work_mode='Office').count()
    wfh = Attendance.query.filter_by(user_id=user.id, work_mode='WFH').count()
    return render_template('dashboard.html', user=user, notifications=notifs, office_days=off, wfh_days=wfh, tasks=tasks)

@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: return redirect(url_for('login'))
    now = get_ist_time()
    today = now.strftime("%Y-%m-%d")
    if request.method == 'POST':
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        time_now = now.strftime("%I:%M %p")
        if not att:
            db.session.add(Attendance(user_id=session['user_id'], date=today, check_in=time_now, work_mode=request.form.get('work_mode')))
            db.session.add(Notification(message=f"CLOCK IN: {session['name']}"))
        else:
            att.check_out = time_now
            db.session.add(Notification(message=f"CLOCK OUT: {session['name']}"))
        db.session.commit()
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history)

@app.route('/staff_directory')
def staff_directory():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('staff_directory.html', employees=User.query.all())

# 1. API for the Chart in your dashboard
@app.route('/api/stats')
def get_stats():
    if 'user_id' not in session: return jsonify({'office': 0, 'wfh': 0})
    u_id = session['user_id']
    off = Attendance.query.filter_by(user_id=u_id, work_mode='Office').count()
    wfh = Attendance.query.filter_by(user_id=u_id, work_mode='WFH').count()
    return jsonify({'office': off, 'wfh': wfh})

# 2. To clear the HR Activity Feed
@app.route('/clear_notifications')
def clear_notifications():
    if session.get('role') == 'HR':
        Notification.query.delete()
        db.session.commit()
    return redirect(url_for('dashboard'))

# 3. To submit the Activity Report (Matches your form)
@app.route('/submit_report', methods=['POST'])
def submit_report():
    if 'user_id' not in session: return redirect(url_for('login'))
    report = ActivityReport(user_id=session['user_id'], content=request.form['content'])
    db.session.add(report)
    db.session.commit()
    flash('Report submitted successfully!', 'success')
    return redirect(url_for('dashboard'))

# 4. To export PDF data (Matches your buttons)
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
            pdf.cell(0, 10, txt=f"Date: {r.date} | Name: {r.user.full_name} | Mode: {r.work_mode}", ln=True)
    else:
        data = ActivityReport.query.all()
        for r in data:
            pdf.cell(0, 10, txt=f"User: {r.rel_user.full_name} | Content: {r.content[:50]}...", ln=True)
            
    out = pdf.output(dest='S').encode('latin-1')
    return send_file(io.BytesIO(out), as_attachment=True, download_name=f"{rtype}_report.pdf")

# --- New Feature Routes ---

@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        claim = ExpenseClaim(user_id=session['user_id'], category=request.form['category'], 
                             amount=float(request.form['amount']), description=request.form['desc'])
        db.session.add(claim)
        db.session.add(Notification(message=f"CLAIM: {session['name']} (₹{request.form['amount']})"))
        db.session.commit()
        flash('Expense claim submitted!', 'success')
    claims = ExpenseClaim.query.all() if session['role'] == 'HR' else ExpenseClaim.query.filter_by(user_id=session['user_id']).all()
    return render_template('expenses.html', claims=claims)

@app.route('/performance', methods=['GET', 'POST'])
def performance():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST' and session['role'] == 'HR':
        kpi = PerformanceKPI(user_id=request.form['u_id'], month=request.form['month'], 
                             rating=int(request.form['rating']), feedback=request.form['feedback'])
        db.session.add(kpi)
        db.session.commit()
    ratings = PerformanceKPI.query.filter_by(user_id=session['user_id']).all()
    all_users = User.query.all() if session['role'] == 'HR' else []
    return render_template('performance.html', ratings=ratings, users=all_users)

@app.route('/add_task', methods=['POST'])
def add_task():
    if 'user_id' in session:
        db.session.add(Task(user_id=session['user_id'], title=request.form['title']))
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/toggle_task/<int:id>')
def toggle_task(id):
    task = Task.query.get(id)
    if task and task.user_id == session['user_id']:
        task.is_done = not task.is_done
        db.session.commit()
    return redirect(url_for('dashboard'))

# (Original Routes below: Payroll, Leave, Activity, etc., preserved exactly)
@app.route('/generate_payslip/<int:uid>')
def generate_payslip(uid):
    user = User.query.get(uid)
    month_prefix = get_ist_time().strftime("%Y-%m")
    days_worked = Attendance.query.filter(Attendance.user_id == uid, Attendance.date.like(f"{month_prefix}%")).count()
    final_pay = round((user.salary / 30) * days_worked, 2)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt=f"NEXUS PAYSLIP - {user.full_name}", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, txt=f"Days Present: {days_worked}", ln=True)
    pdf.cell(0, 10, txt=f"Calculated Salary: Rs. {final_pay}", ln=True)
    out = pdf.output(dest='S').encode('latin-1')
    return send_file(io.BytesIO(out), as_attachment=True, download_name=f"payslip_{user.username}.pdf")

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        db.session.add(Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form['reason']))
        db.session.commit()
    leaves = Leave.query.all() if session['role'] == 'HR' else Leave.query.filter_by(user_id=session['user_id']).all()
    return render_template('leave.html', leaves=leaves)

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') == 'HR':
        new_u = User(username=request.form['username'], password=generate_password_hash(request.form['password']), 
                     role='Employee', full_name=request.form['full_name'], email=request.form['email'], 
                     salary=int(request.form['salary']), address=request.form['address'])
        db.session.add(new_u)
        db.session.commit()
    return redirect(url_for('staff_directory'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password=generate_password_hash('admin123'), role='HR', 
                     full_name='Pavan Kumar', email='pk@nexus.com', salary=95000, address="HQ")
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run()


