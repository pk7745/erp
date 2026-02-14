import os
import io
import csv
import pytz
import shutil
import math
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "bms_college_ultimate_v200"

# ==========================================
# 1. RAILWAY DATABASE PERSISTENCE LOGIC
# ==========================================
basedir = os.path.abspath(os.path.dirname(__file__))
data_dir = "/app/data" 
db_name = 'bms_college_v2.db'

if not os.path.exists(data_dir):
    data_dir = os.path.join(basedir, 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

destination_db = os.path.join(data_dir, db_name)
source_db = os.path.join(basedir, db_name)

if not os.path.exists(destination_db) and os.path.exists(source_db):
    shutil.copyfile(source_db, destination_db)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + destination_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
from sqlalchemy import text

def migrate_db():
    with app.app_context():
        try:
            # Check if 'lat' exists in Attendance, if not, add columns
            db.session.execute(text("ALTER TABLE attendance ADD COLUMN lat FLOAT"))
            db.session.execute(text("ALTER TABLE attendance ADD COLUMN lon FLOAT"))
            db.session.commit()
            print("Database migration successful: added lat/lon columns.")
        except Exception as e:
            # If columns already exist, this will fail silently which is fine
            db.session.rollback()
            print(f"Migration skipped or already done: {e}")

# Call migration
migrate_db()

def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata'))

# ==========================================
# 2. DATABASE MODELS (ALL 12 MODELS PRESERVED)
# ==========================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='Faculty') 
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    salary = db.Column(db.Integer, default=50000)
    status = db.Column(db.String(50), default='Active')
    address = db.Column(db.String(200))
    dob = db.Column(db.String(20), default="1995-01-01") 
    join_date = db.Column(db.String(20), default="2023-01-01")
    caste = db.Column(db.String(50), default='General')
    religion = db.Column(db.String(50), default='Not Specified')
    
    tasks = db.relationship('Task', backref='user', lazy=True)
    attendance = db.relationship('Attendance', backref='user', lazy=True)
    leaves = db.relationship('Leave', backref='user', lazy=True)
    claims = db.relationship('ExpenseClaim', backref='rel_user', lazy=True)
    kpis = db.relationship('PerformanceKPI', backref='user', lazy=True)
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender_info', lazy=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False) 
    timestamp = db.Column(db.DateTime, default=get_ist_time)
    is_group = db.Column(db.Boolean, default=False)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.String(20))
    check_in = db.Column(db.String(20))
    check_out = db.Column(db.String(20))
    work_mode = db.Column(db.String(20))
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.String(20))
    reason = db.Column(db.String(255))
    status = db.Column(db.String(50), default='Pending') 
    rejection_reason = db.Column(db.String(255))
    
class ExpenseClaim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    category = db.Column(db.String(50))
    amount = db.Column(db.Float)
    status = db.Column(db.String(20), default='Pending')
    description = db.Column(db.String(255))
    payment_date = db.Column(db.String(50))
    processed_by = db.Column(db.String(100))

class PerformanceKPI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    month = db.Column(db.String(20))
    rating = db.Column(db.Integer)
    feedback = db.Column(db.String(255))

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    title = db.Column(db.String(100))
    is_done = db.Column(db.Boolean, default=False)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=get_ist_time)

class ActivityReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=get_ist_time)

class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_name = db.Column(db.String(100))
    created_by = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=get_ist_time)

class SalaryUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    new_salary = db.Column(db.Integer)
    status = db.Column(db.String(50), default='Pending Admin Approval')
    user = db.relationship('User', backref=db.backref('salary_updates', lazy=True))

class PayrollStructure(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    hra_percent = db.Column(db.Float, default=40.0)
    da_percent = db.Column(db.Float, default=10.0)
    ta_fixed = db.Column(db.Integer, default=2000)
    epf_percent = db.Column(db.Float, default=12.0)

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ==========================================
# 4. ALL ORIGINAL ROUTES + NEW UPDATES
# ==========================================

@app.route('/')
def home():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('home.html')

@app.route('/about')
def about():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('about.html', user=user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['role'] = user.role 
            session['name'] = user.full_name
            return redirect(url_for('dashboard'))
        flash('Invalid Username or Password.', 'danger')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))

    # --- 1. SAFE DATE LOGIC ---
    today_ist = get_ist_time()
    today_md = today_ist.strftime("%m-%d")
    
    is_birthday = False
    if user.dob and len(str(user.dob)) >= 10:
        is_birthday = (str(user.dob)[5:10] == today_md)

    is_anniversary = False
    if user.join_date and len(str(user.join_date)) >= 10:
        is_anniversary = (str(user.join_date)[5:10] == today_md)

    # --- 2. ATTENDANCE & TASKS (Ensuring Integers) ---
    office_days = Attendance.query.filter_by(user_id=user.id, work_mode='Office').count() or 0
    wfh_days = Attendance.query.filter_by(user_id=user.id, work_mode='WFH').count() or 0
    
    unread_chats = Message.query.filter_by(receiver_id=user.id, is_read=False).count() or 0
    tasks = Task.query.filter_by(user_id=user.id).all() or []

    # --- 3. NOTIFICATIONS (Hardened against NoneType) ---
    privileged_roles = ['HR', 'Accountant', 'Principal', 'HOD - BCA Dept']
    notifs = []
    
    if session.get('role') in privileged_roles:
        try:
            all_notifs = Notification.query.order_by(Notification.timestamp.desc()).limit(20).all()
            if session.get('role') == 'Accountant':
                excluded = ["CLOCK-IN", "CLOCK-OUT", "MEETING", "RECORDING", "TASK", "REPORT"]
                # Safeguard: Ensure n.message exists before checking keywords
                notifs = [n for n in all_notifs if n.message and not any(word in n.message for word in excluded)]
            else:
                notifs = all_notifs
        except Exception as e:
            print(f"Notification Error: {e}")
            notifs = []

    return render_template('dashboard.html', 
                           user=user, 
                           notifications=notifs, 
                           office_days=office_days, 
                           wfh_days=wfh_days, 
                           tasks=tasks, 
                           unread_chats=unread_chats, 
                           is_birthday=is_birthday, 
                           is_anniversary=is_anniversary)

@app.route('/generate_id')
def generate_id():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('id_card.html', user=user, now=get_ist_time().strftime("%Y"))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    basic = user.salary
    hra, da, ta = int(basic * 0.4), int(basic * 0.1), 2000
    gross = basic + hra + da + ta
    epf, pt = int((basic + da) * 0.12), 200
    net = gross - (epf + pt)
    payroll_data = {'hra': hra, 'da': da, 'ta': ta, 'gross': gross, 'epf': epf, 'pt': pt, 'net': net}
    if request.method == 'POST':
        user.full_name = request.form.get('full_name')
        user.email = request.form.get('email')
        user.address = request.form.get('address')
        if request.form.get('caste'): user.caste = request.form.get('caste')
        if request.form.get('religion'): user.religion = request.form.get('religion')
        new_pass = request.form.get('password')
        if new_pass: user.password = generate_password_hash(new_pass)
        db.session.commit()
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user, payroll=payroll_data)

@app.route('/finance')
def finance_tab():
    if session.get('role') != 'Accountant': return redirect(url_for('dashboard'))
    pending = ExpenseClaim.query.filter_by(status='Approved by HR').all()
    return render_template('finance.html', pending=pending)

@app.route('/download_salary_certificate')
def download_salary_certificate():
    if 'user_id' not in session: return redirect(url_for('login'))
    u = User.query.get(session['user_id'])
    pdf = FPDF()
    pdf.add_page()
    pdf.set_fill_color(0, 51, 102); pdf.ellipse(10, 10, 20, 20, 'F')
    pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", 'B', 15); pdf.text(16, 24, "B")
    pdf.set_text_color(0, 51, 102); pdf.set_font("Arial", 'B', 14)
    pdf.cell(190, 10, "BMS COLLEGE OF COMMERCE AND MANAGEMENT", ln=True, align='C')
    pdf.ln(20)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", 'B', 18); pdf.cell(190, 10, "SALARY CERTIFICATE", ln=True, align='C')
    pdf.ln(10)
    gross_val = u.salary + int(u.salary*0.4) + int(u.salary*0.1) + 2000
    pdf.set_font("Arial", '', 12)
    pdf.multi_cell(0, 10, f"Date: {get_ist_time().strftime('%d-%m-%Y')}\n\nTo Whom It May Concern,\n\nThis is to certify that {u.full_name} is a permanent staff member at BMS College of Commerce and Management as a {u.role}. Their current monthly gross compensation is INR {gross_val}.\n\nThis certificate is issued at the request of the faculty for official purposes.")
    pdf.ln(10); current_y = pdf.get_y()
    pdf.set_draw_color(0, 51, 102); pdf.set_line_width(0.8); pdf.ellipse(25, current_y + 10, 30, 30, 'D') 
    pdf.set_font("Arial", 'B', 7); pdf.set_text_color(0, 51, 102); pdf.text(28, current_y + 24, "BMS COLLEGE"); pdf.text(32, current_y + 27, "OFFICIAL SEAL")
    pdf.set_xy(130, current_y + 10); pdf.set_font("Courier", 'BI', 12); pdf.set_text_color(0, 0, 128); pdf.cell(50, 10, "ADMIN_BMS_COLLEGE", ln=True, align='C')
    pdf.line(135, pdf.get_y(), 175, pdf.get_y()); pdf.set_xy(130, pdf.get_y()); pdf.set_font("Arial", 'B', 11); pdf.set_text_color(0, 0, 0); pdf.cell(50, 8, "Principal / Auth Signatory", ln=True, align='C')
    return send_file(io.BytesIO(pdf.output(dest='S').encode('latin-1')), as_attachment=True, download_name=f"Salary_Certificate_{u.username}.pdf")

@app.route('/staff_directory')
def staff_directory():
    if 'user_id' not in session: return redirect(url_for('login'))
    curr_user = User.query.get(session['user_id'])
    employees = User.query.all() if curr_user.role in ['HR', 'Accountant', 'Principal'] else [curr_user]
    return render_template('staff_directory.html', employees=employees, SalaryUpdate=SalaryUpdate)

@app.route('/create_meeting', methods=['POST'])
def create_meeting():
    if 'user_id' not in session: return redirect(url_for('login'))
    room = request.form.get('room_name').replace(" ", "-")
    db.session.add(Meeting(room_name=room, created_by=session['name']))
    db.session.add(Notification(message=f"MEETING: {session['name']} started a meeting: {room}"))
    db.session.commit()
    return redirect(url_for('dashboard', join_meet=room))

@app.route('/notify_recording/<room_name>')
def notify_recording(room_name):
    if 'user_id' not in session: return jsonify({"status": "error"})
    db.session.add(Notification(message=f"RECORDING: {session['name']} started recording: {room_name}"))
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') in ['HR', 'Principal']:
        new_user = User(
            username=request.form['username'],
            password=generate_password_hash(request.form['password']),
            full_name=request.form['full_name'],
            email=request.form['email'],
            salary=int(request.form['salary']),
            address=request.form['address'],
            role='Faculty', 
            dob=request.form.get('dob', '1995-01-01'),
            join_date=request.form.get('join_date', '2023-01-01'),
            caste=request.form.get('caste'),
            religion=request.form.get('religion')
        )
        db.session.add(new_user)
        db.session.commit()
        flash('Employee Added Successfully.', 'success')
    return redirect(url_for('staff_directory'))

@app.route('/api/notifications')
def get_notifications():
    role = session.get('role')
    if role in ['Principal', 'HR']:
        all_notifs = Notification.query.order_by(Notification.timestamp.desc()).limit(10).all()
    elif role == 'Accountant':
        all_notifs = Notification.query.filter(Notification.message.contains('SALARY')).limit(10).all()
    else: return jsonify([])
    return jsonify([{'id': n.id, 'msg': n.message, 'time': n.timestamp.strftime('%I:%M %p')} for n in all_notifs])

@app.route('/edit_salary/<int:uid>', methods=['POST'])
def edit_salary(uid):
    if session.get('role') == 'HR':
        emp = User.query.get(uid)
        old_sal = emp.salary
        emp.salary = int(request.form['new_salary'])
        db.session.add(Notification(message=f"SALARY CHANGE: {emp.full_name} updated from ₹{old_sal} to ₹{emp.salary}"))
        db.session.commit()
    return redirect(url_for('staff_directory'))

@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: return redirect(url_for('login'))
    today = get_ist_time().strftime("%Y-%m-%d")
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        lat = float(request.form.get('lat', 0))
        lon = float(request.form.get('lon', 0))
        mode = request.form['work_mode']
        
        # Geofence check for Office mode (Campus coordinates)
        if mode == 'Office' and calculate_distance(lat, lon, 12.9616, 77.5736) > 300:
            flash("Verification Failed: You are too far from campus.", "error")
            return redirect(url_for('attendance'))

        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        t_now = get_ist_time().strftime("%I:%M %p")
        if not att:
            db.session.add(Attendance(user_id=session['user_id'], date=today, check_in=t_now, work_mode=mode, lat=lat, lon=lon))
            db.session.add(Notification(message=f"ATTENDANCE: {user.full_name} CLOCKED-IN"))
        else:
            att.check_out = t_now
            db.session.add(Notification(message=f"ATTENDANCE: {user.full_name} CLOCKED-OUT"))
        db.session.commit()
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history)

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    limit, taken = 20, Leave.query.filter_by(user_id=session['user_id'], status='Approved').count()
    if request.method == 'POST':
        if user.role == 'Principal': initial_status = 'Approved'
        elif user.role == 'Faculty': initial_status = 'Pending HOD'
        else: initial_status = 'Pending Principal'
        db.session.add(Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form['reason'], status=initial_status))
        db.session.add(Notification(message=f"LEAVE REQUEST: {user.full_name}"))
        db.session.commit()
    if user.role == 'Principal': leaves = Leave.query.filter(Leave.status.in_(['Pending Principal', 'Approved', 'Rejected'])).all()
    elif user.role == 'HOD - BCA Dept': leaves = Leave.query.filter((Leave.status == 'Pending HOD') | (Leave.user_id == user.id)).all()
    elif user.role == 'HR': leaves = Leave.query.all()
    else: leaves = Leave.query.filter_by(user_id=session['user_id']).all()
    return render_template('leave.html', leaves=leaves, leaves_taken=taken, leaves_left=(limit-taken), leave_limit=limit)

@app.route('/approve_leave/<int:id>/<action>')
def approve_leave(id, action):
    leave_req = Leave.query.get(id)
    role = session.get('role')
    if action == 'approve':
        if role == 'HOD - BCA Dept' and leave_req.status == 'Pending HOD':
            leave_req.status = 'Pending Principal'
        elif role == 'Principal' and leave_req.status == 'Pending Principal':
            leave_req.status = 'Approved'
    elif action == 'reject':
        leave_req.status, leave_req.rejection_reason = 'Rejected', request.args.get('reason', 'No reason provided')
    db.session.commit()
    return redirect(url_for('leave'))

@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        amt = float(request.form['amount'])
        db.session.add(ExpenseClaim(user_id=session['user_id'], category=request.form['category'], amount=amt, description=request.form['desc']))
        db.session.add(Notification(message=f"EXPENSE: {user.full_name} claimed INR {amt}"))
        db.session.commit()
    claims = ExpenseClaim.query.all() if session['role'] in ['HR', 'Accountant'] else ExpenseClaim.query.filter_by(user_id=session['user_id']).all()
    return render_template('expenses.html', claims=claims)

@app.route('/approve_expense/<int:id>/<action>')
def approve_expense(id, action):
    claim = ExpenseClaim.query.get(id)
    if action == 'hr_approve' and session['role'] == 'HR': claim.status = 'Approved by HR'
    elif action == 'acc_approve' and session['role'] == 'Accountant':
        claim.status, claim.payment_date, claim.processed_by = 'Finalized', get_ist_time().strftime("%d-%m-%Y"), session['name']
    elif action == 'reject': claim.status = 'Rejected'
    db.session.commit()
    return redirect(url_for('expenses'))

@app.route('/chat', methods=['GET', 'POST'])
@app.route('/chat/<int:receiver_id>', methods=['GET', 'POST'])
def chat(receiver_id=None):
    if 'user_id' not in session: return redirect(url_for('login'))
    curr_id = session['user_id']
    if request.method == 'POST':
        rid = receiver_id or request.form.get('receiver_id')
        msg_text = request.form.get('content')
        if rid and msg_text:
            new_msg = Message(sender_id=curr_id, receiver_id=int(rid), content=msg_text.strip())
            db.session.add(new_msg)
            db.session.commit()
            return redirect(url_for('chat', receiver_id=rid))
    contacts = User.query.filter(User.id != curr_id).all()
    messages = []
    if receiver_id:
        Message.query.filter_by(sender_id=receiver_id, receiver_id=curr_id, is_read=False).update({Message.is_read: True})
        db.session.commit()
        messages = Message.query.filter(((Message.sender_id == curr_id) & (Message.receiver_id == receiver_id)) | ((Message.sender_id == receiver_id) & (Message.receiver_id == curr_id))).order_by(Message.timestamp.asc()).all()
    return render_template('chat.html', contacts=contacts, messages=messages, receiver_id=receiver_id)

@app.route('/api/chat/messages')
def get_lounge_messages():
    msgs = Message.query.filter_by(is_group=True).order_by(Message.timestamp.desc()).limit(50).all()
    return jsonify([{'user': m.sender_info.full_name, 'text': m.content} for m in reversed(msgs)])

@app.route('/api/chat/send', methods=['POST'])
def send_lounge_msg():
    db.session.add(Message(sender_id=session['user_id'], content=request.json['text'], is_group=True))
    db.session.commit()
    return jsonify({"status": "sent"})

@app.route('/performance', methods=['GET', 'POST'])
def performance():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST' and session['role'] == 'HR':
        db.session.add(PerformanceKPI(user_id=request.form['u_id'], month=request.form['month'], rating=request.form['rating'], feedback=request.form['feedback']))
        db.session.commit()
    ratings = PerformanceKPI.query.all() if session['role'] == 'HR' else PerformanceKPI.query.filter_by(user_id=session['user_id']).all()
    users = User.query.all() if session['role'] == 'HR' else []
    return render_template('performance.html', ratings=ratings, users=users)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user:
            db.session.add(Notification(message=f"PASSWORD RESET REQUEST: {user.username}"))
            db.session.commit()
            flash('HR notified.', 'success')
        else: flash('Invalid user', 'error')
    return render_template('forgot_password.html')

@app.route('/export_csv/<rtype>')
def export_csv(rtype):
    if 'user_id' not in session: return redirect(url_for('login'))
    output = io.StringIO()
    writer = csv.writer(output)
    if rtype == 'attendance':
        writer.writerow(['Faculty Name', 'Date', 'Work Mode', 'Check-In', 'Check-Out'])
        for rec in Attendance.query.all():
            writer.writerow([rec.user.full_name if rec.user else "Unknown", rec.date, rec.work_mode, rec.check_in, rec.check_out])
    elif rtype == 'expenses':
        writer.writerow(['Faculty Name', 'Category', 'Amount', 'Status', 'Date'])
        for c in ExpenseClaim.query.all():
            writer.writerow([c.rel_user.full_name if c.rel_user else "Unknown", c.category, c.amount, c.status, c.payment_date])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={rtype}_report.csv"})

@app.route('/generate_payslip/<int:uid>')
def generate_payslip(uid):
    u = User.query.get(uid)
    basic = u.salary
    hra, da, ta = int(basic * 0.40), int(basic * 0.10), 2000
    gross = basic + hra + da + ta
    epf, pt = int((basic + da) * 0.12), 200
    net = gross - (epf + pt)
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 18)
    pdf.cell(200, 15, txt="BMS COLLEGE OF COMMERCE & MANAGEMENT", ln=True, align='C')
    pdf.cell(200, 10, txt=f"PAYSLIP FOR: {u.full_name.upper()}", ln=True, align='C')
    pdf.ln(10); pdf.set_font("Arial", '', 10)
    pdf.cell(60, 10, "Basic Salary", 1); pdf.cell(35, 10, f"INR {basic}", 1, 1, 'R')
    pdf.cell(60, 10, "Net Take-Home", 1); pdf.cell(35, 10, f"INR {net}", 1, 1, 'R')
    return send_file(io.BytesIO(pdf.output(dest='S').encode('latin-1')), as_attachment=True, download_name=f"payslip_{u.username}.pdf")

@app.route('/send_payslip_email/<int:uid>')
def send_payslip_email(uid):
    u = User.query.get(uid)
    db.session.add(Notification(message=f"SYSTEM: Digital Payslip emailed to {u.email}"))
    db.session.commit()
    return jsonify({"message": f"Digital payslip sent to {u.email} successfully!"})

@app.route('/submit_report', methods=['POST'])
def submit_report():
    db.session.add(ActivityReport(user_id=session['user_id'], content=request.form['content']))
    db.session.add(Notification(message=f"REPORT: {session['name']} submitted a report"))
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/add_task', methods=['POST'])
def add_task():
    db.session.add(Task(user_id=session['user_id'], title=request.form['title']))
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/toggle_task/<int:id>')
def toggle_task(id):
    t = Task.query.get(id)
    if t: t.is_done = not t.is_done
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/download_report/<rtype>')
def download_report(rtype):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 16); pdf.cell(200, 10, txt=f"BMS COLLEGE {rtype.upper()} REPORT", ln=True, align='C')
    return send_file(io.BytesIO(pdf.output(dest='S').encode('latin-1')), as_attachment=True, download_name=f"{rtype}.pdf")

@app.route('/clear_notifications')
def clear_notifications():
    Notification.query.delete(); db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/api/stats')
def get_stats():
    u_id = session.get('user_id')
    off = Attendance.query.filter_by(user_id=u_id, work_mode='Office').count() 
    wfh = Attendance.query.filter_by(user_id=u_id, work_mode='WFH').count()
    return jsonify({'office': off, 'wfh': wfh})

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/principal_request_salary/<int:uid>', methods=['POST'])
def principal_request_salary(uid):
    if session.get('role') != 'Principal': return "Unauthorized", 403
    new_val = int(request.form.get('new_salary'))
    existing = SalaryUpdate.query.filter_by(user_id=uid).first()
    if existing: existing.new_salary, existing.status = new_val, 'Pending Admin Approval'
    else: db.session.add(SalaryUpdate(user_id=uid, new_salary=new_val))
    db.session.commit()
    return redirect(url_for('staff_directory'))

@app.route('/admin_verify_salary/<int:req_id>')
def admin_verify_salary(req_id):
    if session.get('role') != 'HR': return "Unauthorized", 403
    req = SalaryUpdate.query.get(req_id)
    req.status = 'Pending Accountant Configuration'
    db.session.commit()
    return redirect(url_for('staff_directory'))

@app.route('/finalize_payroll_config', methods=['POST'])
def finalize_payroll_config():
    if session.get('role') != 'Accountant': return "Unauthorized", 403
    uid = request.form.get('user_id')
    u = User.query.get(uid)
    struct = PayrollStructure.query.filter_by(user_id=uid).first() or PayrollStructure(user_id=uid)
    struct.hra_percent = float(request.form.get('hra_pc', 40.0))
    struct.da_percent = float(request.form.get('da_pc', 10.0))
    struct.epf_percent = float(request.form.get('epf_pc', 12.0))
    struct.ta_fixed = int(request.form.get('ta_fixed', 2000))
    req = SalaryUpdate.query.filter_by(user_id=uid).first()
    if req: u.salary = req.new_salary; db.session.delete(req)
    db.session.add(struct); db.session.commit()
    return redirect(url_for('staff_directory'))

@app.route('/admin_verify_docs/<int:uid>')
def admin_verify_docs(uid):
    if session.get('role') != 'HR': return "Unauthorized", 403
    user = User.query.get(uid)
    if user: user.status = 'Pending Payroll Config'; db.session.commit()
    return redirect(url_for('staff_directory'))

# ==========================================
# 5. FULL SEEDING (INCLUDING ALL FACULTY)
# ==========================================

def seed_database():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='System Admin', email='hr@bmsccm.edu', dob='1985-10-25', join_date='2018-05-10', caste='General', religion='Hindu'))
    if not User.query.filter_by(username='acc1').first():
        db.session.add(User(username='acc1', password=generate_password_hash('pay123'), role='Accountant', full_name='Rajesh Finance', email='accounts@bmsccm.edu', dob='1990-03-12', join_date='2020-11-20', caste='General', religion='Hindu'))
    
    faculties = [
        ('balram', 'Balram M N', 'Faculty', 'balram@bmsccm.edu', 'General', 'Hindu', '1982-04-15', '2015-06-01'),
        ('kiran', 'Kiran Kumar M N', 'HOD - BCA Dept', 'kiran.hod@bmsccm.edu', 'General', 'Hindu', '1978-11-20', '2010-01-15'),
        ('shrinkala', 'Miss. Shrinkala', 'Faculty', 'shrinkala@bmsccm.edu', 'General', 'Hindu', '1992-08-30', '2021-09-10'),
        ('shivani', 'Mrs. Shivani', 'Faculty', 'shivani@bmsccm.edu', 'General', 'Hindu', '1988-03-05', '2019-02-14'),
        ('ramkishore', 'Mr. Ramkishore', 'Faculty', 'ramkishore@bmsccm.edu', 'General', 'Hindu', '1985-12-12', '2017-07-20'),
        ('prathiba', 'Mrs. Prathiba Singh', 'Faculty', 'prathiba@bmsccm.edu', 'General', 'Hindu', '1990-05-25', '2022-11-01'),
        ('newfac', 'New Faculty', 'Faculty', 'new@bmsccm.edu', 'General', 'Not Specified', '1998-01-01', '2025-01-01'),
        ('pankaj', 'Mr. Pankaj Choudhry', 'Principal', 'principal@bmsccm.edu', 'General', 'Hindu', '1975-09-10', '2005-08-15')
    ]
    for u, f, r, e, c, rel, d, j in faculties:
        if not User.query.filter_by(username=u).first():
            db.session.add(User(username=u, password=generate_password_hash('bms123'), role=r, full_name=f, salary=50000, email=e, dob=d, join_date=j, caste=c, religion=rel))
    db.session.commit()

with app.app_context():
    seed_database()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)



