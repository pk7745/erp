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

# --- DB CONFIG (v30 forces a clean, working schema) ---
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v30.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20)) 
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    salary = db.Column(db.Integer, default=50000)
    address = db.Column(db.String(255), default="Not Set")
    # Relationships
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

# --- ROUTES ---

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
    u = User.query.get(session['user_id'])
    notifs = Notification.query.order_by(Notification.timestamp.desc()).all() if session['role'] == 'HR' else []
    off = Attendance.query.filter_by(user_id=u.id, work_mode='Office').count()
    wfh = Attendance.query.filter_by(user_id=u.id, work_mode='WFH').count()
    return render_template('dashboard.html', user=u, notifications=notifs, office_days=off, wfh_days=wfh)

@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: return redirect(url_for('login'))
    local_tz = pytz.timezone('Asia/Kolkata')
    today = datetime.now(local_tz).strftime("%Y-%m-%d")
    if request.method == 'POST':
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        now_time = datetime.now(local_tz).strftime("%I:%M %p")
        if not att:
            db.session.add(Attendance(user_id=session['user_id'], date=today, check_in=now_time, work_mode=request.form.get('work_mode')))
        else:
            att.check_out = now_time
        db.session.commit()
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history)

# --- LEAVE ROUTE (Sync Guaranteed) ---
@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    LIMIT = 2
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    month = now.strftime("%Y-%m")
    
    # Logic: Only count approved/pending leaves against the limit
    taken = Leave.query.filter(Leave.user_id == session['user_id'], Leave.date.like(f"{month}%"), Leave.status != 'Rejected').count()
    left = max(0, LIMIT - taken)

    if request.method == 'POST' and left > 0:
        db.session.add(Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form.get('reason', 'None')))
        db.session.add(Notification(message=f"New Leave Request: {session['name']}"))
        db.session.commit()
        flash('Leave Applied!', 'success')
        return redirect(url_for('leave'))

    # Fetching list: HR sees all, Employee sees only theirs
    leaves_list = Leave.query.all() if session['role'] == 'HR' else Leave.query.filter_by(user_id=session['user_id']).all()
    
    return render_template('leave.html', leaves=leaves_list, leave_limit=LIMIT, leaves_taken=taken, leaves_left=left)

@app.route('/approve_leave/<int:id>/<status>')
def approve_leave(id, status):
    if session.get('role') == 'HR':
        l = Leave.query.get(id)
        # Strict Requirement: HR can only approve Employees, not themselves
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
        u = User(username=request.form['username'], password=generate_password_hash(request.form['password']), role='Employee', full_name=request.form['full_name'], email=request.form['email'], salary=int(request.form['salary'] or 0), address=request.form['address'])
        db.session.add(u)
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
    return redirect(url_for('dashboard'))

@app.route('/download_report/<rtype>')
def download_report(rtype):
    # Simplified placeholder for PDF generation to prevent crashes
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Nexus Report", ln=True, align='C')
    pdf_output = pdf.output(dest='S')
    return send_file(io.BytesIO(pdf_output), as_attachment=True, download_name=f"{rtype}.pdf", mimetype='application/pdf')

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

# --- DB INIT ---
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            hr = User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='pavan kumar', email='pk@nexus.com', salary=95000)
            e1 = User(username='emp1', password=generate_password_hash('pass123'), role='Employee', full_name='John Dsouza')
            e2 = User(username='emp2', password=generate_password_hash('pass123'), role='Employee', full_name='Kartik Sharma')
            e3 = User(username='emp3', password=generate_password_hash('pass123'), role='Employee', full_name='Pranav Avadhani')
            e4 = User(username='emp4', password=generate_password_hash('pass123'), role='Employee', full_name='Parthiv Reddy')
            db.session.add_all([hr, e1, e2, e3, e4])
            db.session.commit()

init_db()

if __name__ == '__main__':
    app.run()
