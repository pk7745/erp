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
# Note: incremented version to v112 to ensure schema synchronization on Render
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v112.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Helper for IST Time
def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata'))

# --- MODELS (ALL FEATURES RESTORED) ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='Employee') # HR, Accountant, Employee
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    salary = db.Column(db.Integer, default=50000)
    address = db.Column(db.String(200))
    tasks = db.relationship('Task', backref='user', lazy=True)
    attendance = db.relationship('Attendance', backref='user', lazy=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False) 
    timestamp = db.Column(db.DateTime, default=get_ist_time)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(20))
    check_in = db.Column(db.String(20))
    check_out = db.Column(db.String(20))
    work_mode = db.Column(db.String(20))

class ExpenseClaim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category = db.Column(db.String(50))
    amount = db.Column(db.Float)
    status = db.Column(db.String(20), default='Pending')
    description = db.Column(db.String(255))
    rel_user = db.relationship('User', backref='claims')

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100))
    is_done = db.Column(db.Boolean, default=False)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=get_ist_time)

class ActivityReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=get_ist_time)

# --- ROUTES ---

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
    unread_chats = Message.query.filter_by(receiver_id=user.id, is_read=False).count()
    notifs = Notification.query.order_by(Notification.timestamp.desc()).all() if session['role'] in ['HR', 'Accountant'] else []
    tasks = Task.query.filter_by(user_id=user.id).all()
    off = Attendance.query.filter_by(user_id=user.id, work_mode='Office').count()
    wfh = Attendance.query.filter_by(user_id=user.id, work_mode='WFH').count()
    return render_template('dashboard.html', user=user, notifications=notifs, office_days=off, wfh_days=wfh, tasks=tasks, unread_chats=unread_chats)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        user.full_name = request.form.get('full_name')
        user.email = request.form.get('email')
        user.address = request.form.get('address')
        if request.form.get('password'):
            user.password = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash('Profile Updated Successfully!', 'success')
    return render_template('profile.html', user=user)

@app.route('/chat', methods=['GET', 'POST'])
@app.route('/chat/<int:receiver_id>', methods=['GET', 'POST'])
def chat(receiver_id=None):
    if 'user_id' not in session: return redirect(url_for('login'))
    curr_id = session['user_id']
    if request.method == 'POST':
        msg = Message(sender_id=curr_id, receiver_id=request.form['receiver_id'], content=request.form['content'])
        db.session.add(msg); db.session.commit()
        return redirect(url_for('chat', receiver_id=request.form['receiver_id']))
    
    # HR can see everyone, Employees only see HR
    contacts = User.query.filter(User.id != curr_id).all() if session['role'] == 'HR' else User.query.filter_by(role='HR').all()
    messages = []
    if receiver_id:
        unread = Message.query.filter_by(sender_id=receiver_id, receiver_id=curr_id, is_read=False).all()
        for m in unread: m.is_read = True; db.session.commit()
        messages = Message.query.filter(((Message.sender_id == curr_id) & (Message.receiver_id == receiver_id)) | ((Message.sender_id == receiver_id) & (Message.receiver_id == curr_id))).order_by(Message.timestamp.asc()).all()
    return render_template('chat.html', contacts=contacts, messages=messages, receiver_id=receiver_id)

@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: return redirect(url_for('login'))
    today = get_ist_time().strftime("%Y-%m-%d")
    if request.method == 'POST':
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        t_now = get_ist_time().strftime("%I:%M %p")
        if not att:
            db.session.add(Attendance(user_id=session['user_id'], date=today, check_in=t_now, work_mode=request.form['work_mode']))
        else: att.check_out = t_now
        db.session.commit()
    # HR sees full log, Employees see personal log
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history)

@app.route('/staff_directory')
def staff_directory():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('staff_directory.html', employees=User.query.all())

@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        db.session.add(ExpenseClaim(user_id=session['user_id'], category=request.form['category'], amount=float(request.form['amount']), description=request.form['desc']))
        db.session.commit()
    # Accountant and HR see all claims
    claims = ExpenseClaim.query.all() if session['role'] in ['HR', 'Accountant'] else ExpenseClaim.query.filter_by(user_id=session['user_id']).all()
    return render_template('expenses.html', claims=claims)

@app.route('/generate_payslip/<int:uid>')
def generate_payslip(uid):
    user = User.query.get(uid)
    days = Attendance.query.filter(Attendance.user_id == uid, Attendance.date.like(f"{get_ist_time().strftime('%Y-%m')}%")).count()
    pay = round((user.salary / 30) * days, 2)
    pdf = FPDF()
    pdf.add_page(); pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="NEXUS ENTERPRISE PAYSLIP", ln=True, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, txt=f"Employee: {user.full_name} | Days: {days} | Net Pay: Rs.{pay}", ln=True)
    return send_file(io.BytesIO(pdf.output(dest='S').encode('latin-1')), as_attachment=True, download_name=f"payslip_{user.username}.pdf")

@app.route('/download_report/<rtype>')
def download_report(rtype):
    user = User.query.get(session['user_id'])
    pdf = FPDF()
    pdf.add_page(); pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt=f"NEXUS {rtype.upper()} REPORT", ln=True, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, txt=f"Generated for: {user.full_name} | Date: {get_ist_time().strftime('%Y-%m-%d')}", ln=True)
    return send_file(io.BytesIO(pdf.output(dest='S').encode('latin-1')), as_attachment=True, download_name=f"{rtype}_report.pdf")

@app.route('/performance')
def performance():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('performance.html', user=user)

@app.route('/submit_report', methods=['POST'])
def submit_report():
    db.session.add(ActivityReport(user_id=session['user_id'], content=request.form['content']))
    db.session.commit()
    flash('Activity report submitted!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/clear_notifications')
def clear_notifications():
    if session.get('role') == 'HR': Notification.query.delete(); db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user:
            db.session.add(Notification(message=f"RESET REQUEST: {user.full_name} ({user.username})"))
            db.session.commit()
            flash('Request sent to HR.', 'success')
    return render_template('forgot_password.html')

@app.route('/api/stats')
def get_stats():
    u_id = session.get('user_id')
    off = Attendance.query.filter_by(user_id=u_id, work_mode='Office').count()
    wfh = Attendance.query.filter_by(user_id=u_id, work_mode='WFH').count()
    return jsonify({'office': off, 'wfh': wfh})

@app.route('/add_task', methods=['POST'])
def add_task():
    db.session.add(Task(user_id=session['user_id'], title=request.form['title'])); db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/toggle_task/<int:id>')
def toggle_task(id):
    t = Task.query.get(id); t.is_done = not t.is_done; db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

# --- DB INIT ---
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='System Admin'))
        db.session.commit()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
