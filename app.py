import os
import io
import pytz
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "nexus_final_v103_secure"

# Database Configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v103.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Helper for IST Time
def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata'))

# --- Models (Untouched) ---
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
    timestamp = db.Column(db.DateTime, default=get_ist_time)
    rel_user = db.relationship('User', backref='activity_reports', lazy=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=get_ist_time)

class PerformanceKPI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    month = db.Column(db.String(20))
    rating = db.Column(db.Integer)  # Scale 1-10
    feedback = db.Column(db.String(255))

class ExpenseClaim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category = db.Column(db.String(50))
    amount = db.Column(db.Float)
    status = db.Column(db.String(20), default='Pending') # Pending, Approved, Rejected
    description = db.Column(db.String(255))

class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100)) # e.g., MacBook Pro
    serial = db.Column(db.String(100), unique=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100))
    is_done = db.Column(db.Boolean, default=False)

# --- New Advanced Routes ---

@app.route('/api/stats')
def get_stats():
    if 'user_id' not in session: return jsonify({})
    u_id = session['user_id']
    off = Attendance.query.filter_by(user_id=u_id, work_mode='Office').count()
    wfh = Attendance.query.filter_by(user_id=u_id, work_mode='WFH').count()
    return jsonify({'office': off, 'wfh': wfh})

@app.route('/generate_payslip/<int:uid>')
def generate_payslip(uid):
    user = User.query.get(uid)
    month_prefix = get_ist_time().strftime("%Y-%m")
    days_worked = Attendance.query.filter(Attendance.user_id == uid, Attendance.date.like(f"{month_prefix}%")).count()
    final_pay = round((user.salary / 30) * days_worked, 2)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(200, 20, txt="NEXUS ENTERPRISE - PAYSLIP", ln=True, align='C')
    pdf.set_font("Arial", size=12)
    pdf.ln(10)
    pdf.cell(0, 10, txt=f"Employee: {user.full_name}", ln=True)
    pdf.cell(0, 10, txt=f"Days Present: {days_worked}", ln=True)
    pdf.cell(0, 10, txt=f"Total Pay: Rs. {final_pay}", ln=True)
    
    out = pdf.output(dest='S').encode('latin-1')
    return send_file(io.BytesIO(out), as_attachment=True, download_name=f"payslip_{user.username}.pdf", mimetype='application/pdf')

# --- Original Routes ---

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

@app.route('/clear_notifications')
def clear_notifications():
    if session.get('role') == 'HR':
        Notification.query.delete()
        db.session.commit()
        flash('Activity feed cleared.', 'success')
    return redirect(url_for('dashboard'))

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

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    month_prefix = get_ist_time().strftime("%Y-%m")
    taken = Leave.query.filter(Leave.user_id == session['user_id'], Leave.date.like(f"{month_prefix}%"), Leave.status != 'Rejected').count()
    limit = 2
    left = max(0, limit - taken)
    if request.method == 'POST' and left > 0:
        db.session.add(Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form.get('reason', 'N/A')))
        db.session.add(Notification(message=f"LEAVE REQUEST: {session['name']}"))
        db.session.commit()
        flash('Leave applied successfully!', 'success')
        return redirect(url_for('leave'))
    leaves = Leave.query.all() if session['role'] == 'HR' else Leave.query.filter_by(user_id=session['user_id']).all()
    return render_template('leave.html', leaves=leaves, leave_limit=limit, leaves_taken=taken, leaves_left=left)

@app.route('/approve_leave/<int:id>/<status>')
def approve_leave(id, status):
    if session.get('role') == 'HR':
        l = Leave.query.get(id)
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

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='pavan kumar', email='pk@nexus.com', salary=95000, address="HQ")
        db.session.add(admin)
        e1 = User(username='emp1', password=generate_password_hash('pass123'), role='Employee', full_name='John Dsouza', email='john@nexus.com', salary=50000, address="Bangalore")
        e2 = User(username='emp2', password=generate_password_hash('pass123'), role='Employee', full_name='Kartik Sharma', email='k@nexus.com', salary=52000, address="Mumbai")
        db.session.add_all([e1, e2])
        db.session.commit()

@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        claim = ExpenseClaim(user_id=session['user_id'], category=request.form['category'], 
                             amount=float(request.form['amount']), description=request.form['desc'])
        db.session.add(claim)
        db.session.add(Notification(message=f"EXPENSE CLAIM: {session['name']} - ₹{request.form['amount']}"))
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

@app.route('/toggle_task/<int:id>')
def toggle_task(id):
    task = Task.query.get(id)
    if task:
        task.is_done = not task.is_done
        db.session.commit()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run()

