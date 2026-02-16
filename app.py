import eventlet
eventlet.monkey_patch()

import os
import io
import pytesseract
from PIL import Image
import csv
import pytz
import shutil
import math
import qrcode  # Ensure you run 'pip install qrcode'
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from fpdf import FPDF
from flask_socketio import SocketIO, emit
from flask_mail import Mail, Message as MailMessage
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURATION ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD') 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')
app.config['UPLOAD_FOLDER'] = 'static/uploads/profiles'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}
app.secret_key = "bms_college_ultimate_v200"

# Create upload directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
mail = Mail(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def send_notification_email(receiver_email, sender_name):
    if not receiver_email: return
    try:
        msg = MailMessage("New Private Message: BMS Connect", recipients=[receiver_email])
        msg.body = f"Hello Principal,\n\nYou have received a new private message from {sender_name} on the BMS Connect Staff Portal."
        mail.send(msg)
    except Exception as e:
        print(f"SMTP Error: {e}")

# ==========================================
# 1. DATABASE SETUP
# ==========================================
basedir = os.path.abspath(os.path.dirname(__file__))
data_dir = "/app/data" 
db_name = 'bms_college_v15.db'

if not os.path.exists(data_dir):
    data_dir = os.path.join(basedir, 'data')
    if not os.path.exists(data_dir): os.makedirs(data_dir)

destination_db = os.path.join(data_dir, db_name)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + destination_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

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
    profile_pic = db.Column(db.String(200), default='default.png')# NEW FIELD
    department = db.Column(db.String(100), nullable=True)
    dept_id = db.Column(db.String(50), nullable=True)
    
    tasks = db.relationship('Task', backref='user', lazy=True)
    attendance = db.relationship('Attendance', backref='user', lazy=True)
    leaves = db.relationship('Leave', backref='user', lazy=True)
    claims = db.relationship('ExpenseClaim', backref='rel_user', lazy=True)
    kpis = db.relationship('PerformanceKPI', backref='user', lazy=True)
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender_info', lazy=True)

class Broadcast(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    active = db.Column(db.Boolean, default=True)
    author = db.Column(db.String(100)) # e.g., "Principal"

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
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id')) # The recipient
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id')) # The sender (Principal/HOD)
    status = db.Column(db.String(50), default="Pending")         # Track progress
    reply = db.Column(db.Text)                                   # For employee responses

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=get_ist_time)

class ActivityReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    staff_name = db.Column(db.String(100))
    report_to = db.Column(db.String(50)) # Stores 'Principal' or 'HOD'
    topic = db.Column(db.String(200))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

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

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(100))  # The Admin who performed the action
    action = db.Column(db.String(255))     # e.g., "Updated Salary", "Deleted Staff"
    target_user = db.Column(db.String(100)) # The staff member affected
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

def log_action(action_text, target="System"):
    new_log = AuditLog(
        user_name=session.get('name', 'Unknown'),
        action=action_text,
        target_user=target
    )
    db.session.add(new_log)
    db.session.commit()

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

@app.route('/about/admissions')
def admissions():
    return render_template('admissions.html')

@app.route('/about/courses')
def courses():
    return render_template('courses.html')

@app.route('/about/placements')
def placements():
    return render_template('placements.html')

@app.route('/about/campus-life')
def campus_life():
    return render_template('campus_life.html')

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

@app.route('/my_profile')
def my_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Fetch the logged-in user's full data
    user = User.query.get(session['user_id'])
    return render_template('my_profile.html', user=user)
    
@app.route('/audit_logs')
def view_audit_logs():
    # SECURITY: Only allow Principal to see the 'Black Box'
    if session.get('role') != 'Principal':
        flash("Access Denied: You do not have permission to view system logs.", "error")
        return redirect(url_for('dashboard'))
    
    # Fetch all logs, newest first
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    return render_template('audit_logs.html', logs=logs)

@app.route('/activity')
def activity_room():
    # Fetch tasks assigned TO the user
    my_tasks = Task.query.filter_by(assigned_to=session['user_id']).all()
    
    # If Principal/HOD, fetch tasks they ASSIGNED to others
    assigned_by_me = []
    if session['role'] in ['Principal', 'HOD']:
        assigned_by_me = Task.query.filter_by(assigned_by=session['user_id']).all()
        
    # Stats for the Growth Chart (Example logic)
    # Count completed tasks over the last 7 days
    growth_data = [2, 5, 3, 8, 6, 9, 12] # Replace with DB query logic
    
    return render_template('activity.html', 
                           my_tasks=my_tasks, 
                           assigned_by_me=assigned_by_me,
                           growth_data=growth_data)

@app.route('/assign_task', methods=['POST'])
def assign_task():
    new_task = Task(
        title=request.form['title'],
        assigned_to=request.form['staff_id'], # Selected from dropdown
        assigned_by=session['user_id'],
        status="Pending"
    )
    # Trigger the sidebar badge for the recipient
    db.session.add(Notification(user_id=request.form['staff_id'], msg="New Task Assigned!"))
    db.session.add(new_task)
    db.session.commit()
    flash("Task Delegated Successfully", "success")
    return redirect(url_for('activity_room'))
    
@app.route('/leave_calendar')
def leave_calendar():
    if session.get('role') not in ['Principal', 'HR']:
        return redirect(url_for('dashboard'))
    
    approved_leaves = Leave.query.filter_by(status='Approved').all()
    
    # SAFETY CHECK: Ensure every leave object has a 'day' and a 'role'
    for leave in approved_leaves:
        # 1. Convert string dates to Python date objects if necessary
        if isinstance(leave.start_date, str):
            leave.start_date = datetime.strptime(leave.start_date, '%Y-%m-%d')
        if isinstance(leave.end_date, str):
            leave.end_date = datetime.strptime(leave.end_date, '%Y-%m-%d')
        
        # 2. Add a default 'role' if your database table doesn't have one
        if not hasattr(leave, 'role') or leave.role is None:
            leave.role = "Faculty"  # Defaulting to Faculty to prevent crash

    return render_template('leave_calendar.html', leaves=approved_leaves)

@app.route('/digital_vault')
def digital_vault():
    if session.get('role') not in ['HR', 'Principal']:
        return redirect(url_for('dashboard'))
    return render_template('digital_vault.html')

@app.route('/scan_and_import', methods=['POST'])
def scan_and_import():
    if 'doc_image' not in request.files:
        return jsonify({"error": "No image uploaded"}), 400
    
    # 1. AI OCR Extraction
    file = request.files['doc_image']
    image = Image.open(file.stream)
    extracted_text = pytesseract.image_to_string(image)
    
    # 2. Simple logic to "guess" the name (first non-empty line)
    lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
    guessed_name = lines[0] if lines else "Unknown Staff"
    
    # 3. Create Staff Profile Automatically
    new_staff = User(
        name=guessed_name,
        role="Faculty", # Default role
        status="Pending Verification"
    )
    db.session.add(new_staff)
    db.session.commit()
    
    # 4. Log the action for the Principal
    log_action(f"AI Auto-Imported new staff: {guessed_name}", target="Digital Vault")
    
    return jsonify({
        "success": True,
        "extracted_name": guessed_name,
        "full_text": extracted_text
    })
    
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

    # --- 2. ATTENDANCE & TASKS ---
    office_days = Attendance.query.filter_by(user_id=user.id, work_mode='Office').count() or 0
    wfh_days = Attendance.query.filter_by(user_id=user.id, work_mode='WFH').count() or 0
    
    unread_chats = Message.query.filter_by(receiver_id=user.id, is_read=False).count() or 0
    tasks = Task.query.filter_by(user_id=user.id).all() or []

    # --- NEW: FETCH RECENT MEETINGS ---
    # We fetch the last 5 meetings so staff can see what is happening
    active_meetings = Meeting.query.order_by(Meeting.id.desc()).limit(5).all() or []

    # --- 3. NOTIFICATIONS ---
    privileged_roles = ['HR', 'Accountant', 'Principal', 'HOD - BCA Dept']
    notifs = []
    
    if session.get('role') in privileged_roles:
        try:
            all_notifs = Notification.query.order_by(Notification.timestamp.desc()).limit(20).all()
            if session.get('role') == 'Accountant':
                excluded = ["CLOCK-IN", "CLOCK-OUT", "MEETING", "RECORDING", "TASK", "REPORT"]
                notifs = [n for n in all_notifs if n.message and not any(word in n.message for word in excluded)]
            else:
                notifs = all_notifs
        except Exception as e:
            print(f"Notification Error: {e}")
            notifs = []

    pending_count = Task.query.filter_by(assigned_to=session['user_id'], is_done=False).count()
    # Added 'meetings' to the return template
    return render_template('dashboard.html', 
                           user=user, 
                           notifications=notifs, 
                           office_days=office_days, 
                           wfh_days=wfh_days, 
                           tasks=tasks, 
                           unread_chats=unread_chats, 
                           is_birthday=is_birthday, 
                           is_anniversary=is_anniversary,
                           meetings=active_meetings) # <--- Added this)

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
            religion=request.form.get('religion'),
            dept=request.form.get('dept'),       # New Field
            dept_id=request.form.get('dept_id'),
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
        log_action("Updated Salary", target=staff_member.name)
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
    log_action("Approved Leave Request", target=leave_request.user_name)
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
    
    # 1. MARK MESSAGES AS READ
    if receiver_id:
        # If I am viewing messages from 'receiver_id', mark them as read
        unread_messages = Message.query.filter_by(
            sender_id=receiver_id, 
            receiver_id=curr_id, 
            is_read=False
        ).all()
        for msg in unread_messages:
            msg.is_read = True
        db.session.commit()

    # 2. HANDLE NEW MESSAGE SENDING
    if request.method == 'POST' and receiver_id:
        content = request.form.get('content')
        if content:
            # Fetch target user to check if they are the Principal
            target_user = User.query.get(receiver_id)
            
            new_msg = Message(
                sender_id=curr_id, 
                receiver_id=receiver_id, 
                content=content, 
                is_group=False,
                timestamp=get_ist_time(),
                is_read=False # Default to unread
            )
            db.session.add(new_msg)
            db.session.commit()

            # --- NEW: EMAIL NOTIFICATION LOGIC ---
            # Strictly triggers ONLY if the receiver is the Principal
            if target_user and target_user.role.lower() == 'principal':
                sender_name = session.get('name', 'A Staff Member')
                send_notification_email(target_user.email, sender_name)
            # --------------------------------------

            return redirect(url_for('chat', receiver_id=receiver_id))

    # --- START OF NOTIFICATION LOGIC ---
    all_staff = User.query.filter(User.id != curr_id).order_by(User.role).all()
    
    # Calculate unread messages for each staff member to display in the sidebar
    for staff in all_staff:
        staff.unread_count = Message.query.filter_by(
            sender_id=staff.id, 
            receiver_id=curr_id, 
            is_read=False
        ).count()
    # --- END OF NOTIFICATION LOGIC ---

    receiver = User.query.get(receiver_id) if receiver_id else None
    
    # Fetch messages for display
    messages = []
    if receiver_id:
        messages = Message.query.filter(
            ((Message.sender_id == curr_id) & (Message.receiver_id == receiver_id)) | 
            ((Message.sender_id == receiver_id) & (Message.receiver_id == curr_id))
        ).order_by(Message.timestamp.asc()).all()

    return render_template('chat.html', all_staff=all_staff, messages=messages, receiver=receiver)
    
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
    if not u:
        return "Employee not found", 404
        
    basic = u.salary
    hra = int(basic * 0.40)
    da = int(basic * 0.10)
    ta = 2000
    gross = basic + hra + da + ta
    
    # ADJUSTABLE TDS SLAB LOGIC
    if gross > 100000:
        tds_rate = 0.15  # 15%
    elif gross > 50000:
        tds_rate = 0.10  # 10%
    else:
        tds_rate = 0.05  # 5%
        
    tds = int(gross * tds_rate)
    epf = int((basic + da) * 0.12)
    pt = 200
    total_deductions = epf + pt + tds
    net = gross - total_deductions

    # 2. PDF Setup
    pdf = FPDF()
    pdf.add_page()
    
    # Header - College Branding
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, txt="BMS COLLEGE OF COMMERCE & MANAGEMENT", ln=True, align='C')
    pdf.set_font("Arial", '', 10)
    pdf.cell(190, 5, txt="Affiliated to Bengaluru City University", ln=True, align='C')
    pdf.ln(5)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(190, 10, txt=f"PAYSLIP FOR THE MONTH OF FEBRUARY 2026", border=1, ln=True, align='C', fill=True)
    pdf.ln(5)

    # Employee Info Row
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(40, 8, "Employee Name:", 0); pdf.set_font("Arial", '', 10); pdf.cell(60, 8, u.full_name, 0)
    pdf.set_font("Arial", 'B', 10); pdf.cell(40, 8, "Designation:", 0); pdf.set_font("Arial", '', 10); pdf.cell(50, 8, u.role, 0, 1)
    pdf.ln(5)

    # 3. Detailed Salary Table
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(230, 235, 255)
    pdf.cell(65, 10, "Earnings", 1, 0, 'C', True)
    pdf.cell(30, 10, "Amount", 1, 0, 'C', True)
    pdf.cell(65, 10, "Deductions", 1, 0, 'C', True)
    pdf.cell(30, 10, "Amount", 1, 1, 'C', True)

    pdf.set_font("Arial", '', 10)
    # Row 1
    pdf.cell(65, 8, "Basic Salary", 1); pdf.cell(30, 8, f"{basic}", 1, 0, 'R')
    pdf.cell(65, 8, "Employee PF (12%)", 1); pdf.cell(30, 8, f"{epf}", 1, 1, 'R')
    # Row 2
    pdf.cell(65, 8, "H.R.A (40%)", 1); pdf.cell(30, 8, f"{hra}", 1, 0, 'R')
    pdf.cell(65, 8, "Professional Tax", 1); pdf.cell(30, 8, f"{pt}", 1, 1, 'R')
    # Row 3
    pdf.cell(65, 8, "D.A (10%)", 1); pdf.cell(30, 8, f"{da}", 1, 0, 'R')
    pdf.cell(65, 8, f"Income Tax / TDS ({int(tds_rate*100)}%)", 1); pdf.cell(30, 8, f"{tds}", 1, 1, 'R')
    # Row 4
    pdf.cell(65, 8, "Transport Allowance", 1); pdf.cell(30, 8, f"{ta}", 1, 0, 'R')
    pdf.cell(65, 8, "Other Deductions", 1); pdf.cell(30, 8, "0", 1, 1, 'R')

    # Totals Row
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(65, 10, "Gross Earnings", 1, 0, 'L', True)
    pdf.cell(30, 10, f"{gross}", 1, 0, 'R', True)
    pdf.cell(65, 10, "Total Deductions", 1, 0, 'L', True)
    pdf.cell(30, 10, f"{total_deductions}", 1, 1, 'R', True)

    # Net Pay Box
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(190, 12, f"NET PAYABLE: INR {net} /-", border=1, ln=True, align='C')

    # 4. Seal and Signature (Blank placeholders as requested)
    pdf.ln(25)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(95, 5, "_______________________", 0, 0, 'C')
    pdf.cell(95, 5, "_______________________", 0, 1, 'C')
    pdf.cell(95, 5, "College Seal", 0, 0, 'C')
    pdf.cell(95, 5, "Principal Signature", 0, 1, 'C')

    # 5. Digital Rights Footer
    pdf.ln(15)
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(190, 5, "This is a computer-generated payslip and does not require a physical ink signature.", ln=True, align='C')
    pdf.cell(190, 5, f"Verification Code: BMS-{uid}-2026 | Digital Rights Reserved @ BMSCCM IT Cell", ln=True, align='C')

    # Output Fix (Use latin-1 encoding for FPDF string output)
    response = make_response(pdf.output(dest='S').encode('latin-1'))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=payslip_{u.username}.pdf'
    return response
    
@app.route('/send_payslip_email/<int:uid>')
def send_payslip_email(uid):
    u = User.query.get(uid)
    db.session.add(Notification(message=f"SYSTEM: Digital Payslip emailed to {u.email}"))
    db.session.commit()
    return jsonify({"message": f"Digital payslip sent to {u.email} successfully!"})

@app.route('/submit_report', methods=['POST'])
def submit_report():
    # 1. Capture the new fields from the Solid Template
    report_to = request.form.get('report_to')  # Principal or HOD
    topic = request.form.get('report_topic')
    content = request.form.get('report_content')
    
    # 2. Add to ActivityReport table 
    # (Ensure your Database Model has 'report_to' and 'topic' columns)
    new_report = ActivityReport(
        user_id=session['user_id'],
        staff_name=session['name'], # Helpful for HOD/Principal view
        report_to=report_to,
        topic=topic,
        content=content
    )
    db.session.add(new_report)

    # 3. Add to System Audit/Notification Feed
    # This makes it show up in the "Activity Feed" card on the right
    audit_msg = f"📄 {session['name']} submitted a report to {report_to} regarding {topic}"
    db.session.add(Notification(msg=audit_msg))

    # 4. Save and Redirect
    db.session.commit()
    flash(f"Report successfully submitted to {report_to}!", "success")
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
    log_action("User Logged Out") # Records the logout
    session.clear(); return redirect(url_for('login'))

@app.route('/principal_request_salary/<int:uid>', methods=['POST'])
def principal_request_salary(uid):
    if session.get('role') != 'Principal': return "Unauthorized", 403
    new_sal = request.form.get('new_salary')
    
    # Create or Update a SalaryUpdate record
    upd = SalaryUpdate.query.filter_by(user_id=uid).first() or SalaryUpdate(user_id=uid)
    upd.new_salary = float(new_sal)
    upd.status = 'Pending HR Verification' # Step 1
    
    # Also update the main user status so the UI knows where it is
    user = User.query.get(uid)
    user.status = 'Pending HR Verification'
    
    db.session.add(upd)
    db.session.commit()
    log_action(f"Principal requested salary hike: ₹{new_sal}", target=user.full_name)
    return redirect(url_for('staff_directory'))
    
@app.route('/admin_verify_docs/<int:uid>')
def admin_verify_docs(uid):
    if session.get('role') != 'HR': return "Unauthorized", 403
    user = User.query.get(uid)
    upd = SalaryUpdate.query.filter_by(user_id=uid).first()
    
    if upd:
        upd.status = 'Pending Accountant Configuration' # Step 2
        user.status = 'Pending Accountant Configuration'
        db.session.commit()
        log_action("HR Verified Salary Update", target=user.full_name)
    return redirect(url_for('staff_directory'))
    
@app.route('/finalize_payroll_config', methods=['POST'])
def finalize_payroll_config():
    if session.get('role') != 'Accountant': return "Unauthorized", 403
    uid = request.form.get('user_id')
    u = User.query.get(uid)
    
    # Update Payroll Structure
    struct = PayrollStructure.query.filter_by(user_id=uid).first() or PayrollStructure(user_id=uid)
    struct.hra_percent = 40.0
    struct.da_percent = 10.0
    struct.epf_percent = 12.0
    struct.ta_fixed = 2000
    
    # Finalize Salary
    req = SalaryUpdate.query.filter_by(user_id=uid).first()
    if req:
        u.salary = req.new_salary
        u.status = 'Active' # Step 3 - Finalized
        db.session.delete(req)
    
    db.session.add(struct)
    db.session.commit()
    log_action("Accountant Finalized Payroll", target=u.full_name)
    return redirect(url_for('staff_directory'))
    

@socketio.on('send_chat_message')
def handle_chat(data):
    # This matches the 'send_chat_message' emit from JS
    emit('new_message', {
        'user': session.get('name', 'Anonymous'),
        'text': data['text']
    }, broadcast=True)

@app.route('/email_staff_list')
def email_staff_list():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Fetch all staff
    all_users = User.query.all()
    staff_report = "Official Staff Directory:\n\n"
    for user in all_users:
        staff_report += f"Name: {user.full_name} | Role: {user.role} | Email: {user.email}\n"

    # Find the Principal's email
    principal = User.query.filter_by(role='Principal').first()
    principal_email = principal.email if principal else app.config['MAIL_USERNAME']

    try:
        # We use MailMessage (the alias) to avoid the TypeError
        msg = MailMessage(
            "Official Staff Directory - BMSCCM",
            sender=app.config['MAIL_USERNAME'],
            recipients=[principal_email]
        )
        msg.body = staff_report
        mail.send(msg)
        return "Staff list has been emailed to the Principal successfully!"
    except Exception as e:
        return f"Error sending email: {str(e)}"

@app.route('/upload_photo/<int:uid>', methods=['POST'])
def upload_photo(uid):
    if 'photo' not in request.files: return redirect(request.referrer)
    file = request.files['photo']
    if file and allowed_file(file.filename):
        user = User.query.get(uid)
        filename = f"staff_{uid}_{secure_filename(file.filename)}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        user.profile_pic = filename
        db.session.commit()
        flash("Photo updated successfully!", "success")
    return redirect(request.referrer)

@app.route('/generate_id/<int:uid>')
def generate_id(uid):
    u = User.query.get(uid)
    # ID Card Size: 54mm x 86mm (Standard CR80)
    pdf = FPDF(format=(54, 86))
    pdf.add_page()
    
    # Header Branding
    pdf.set_fill_color(27, 37, 89)
    pdf.rect(0, 0, 54, 18, 'F')
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", 'B', 8)
    pdf.text(12, 10, "BMSCCM STAFF ID")
    
    # Profile Picture
    pic_path = os.path.join(app.config['UPLOAD_FOLDER'], u.profile_pic) if u.profile_pic else None
    if not pic_path or not os.path.exists(pic_path) or u.profile_pic == 'default.png':
        pdf.rect(17, 20, 20, 20) # Placeholder
    else:
        pdf.image(pic_path, 17, 20, 20, 20)

    # Details
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 8)
    pdf.set_xy(0, 42)
    pdf.cell(54, 4, u.full_name.upper(), 0, 1, 'C')
    
    pdf.set_font("Arial", 'B', 6)
    pdf.set_text_color(67, 24, 255) # BMS Blue
    pdf.cell(54, 3, f"{u.department}", 0, 1, 'C')
    
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", '', 6)
    pdf.cell(54, 3, f"Role: {u.role}", 0, 1, 'C')
    pdf.cell(54, 3, f"Dept ID: {u.dept_id}", 0, 1, 'C')
    pdf.cell(54, 3, f"DOB: {u.dob}", 0, 1, 'C')

    # Small Address
    pdf.set_font("Arial", '', 5)
    pdf.set_xy(2, 58)
    pdf.multi_cell(50, 2.5, f"Addr: {u.address}", 0, 'C')

    # QR Code for verification
    qr_content = f"VERIFIED: {u.full_name} | DEPT_ID: {u.dept_id} | BMSCCM"
    qr = qrcode.make(qr_content)
    qr_io = io.BytesIO()
    qr.save(qr_io, format='PNG')
    qr_io.seek(0)
    
    qr_temp_path = f"static/uploads/qr_{uid}.png"
    with open(qr_temp_path, "wb") as f: f.write(qr_io.getvalue())
    
    pdf.image(qr_temp_path, 21, 68, 12, 12)
    pdf.set_font("Arial", 'I', 4)
    pdf.text(18, 82, "Scan to Verify Employment")

    response = make_response(pdf.output(dest='S').encode('latin-1'))
    response.headers['Content-Type'] = 'application/pdf'
    return response

@app.route('/send_broadcast', methods=['POST'])
def send_broadcast():
    if session.get('role') not in ['HR', 'Principal']:
        return "Unauthorized", 403
    
    msg = request.form.get('message')
    if msg:
        # Deactivate old broadcasts so only one shows at a time
        Broadcast.query.update({Broadcast.active: False})
        
        new_broadcast = Broadcast(message=msg, author=session.get('full_name'))
        db.session.add(new_broadcast)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/clear_broadcast')
def clear_broadcast():
    Broadcast.query.update({Broadcast.active: False})
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/payslip_history')
def payslip_history():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    
    # Generate list of past 6 months
    months = ["September 2025", "October 2025", "November 2025", "December 2025", "January 2026", "February 2026"]
    return render_template('payslip_history.html', user=user, months=months)

@app.route('/generate_payslip_historical/<int:uid>/<month>')
def generate_payslip_historical(uid, month):
    # This uses your existing generate_payslip logic but injects the specific month name
    # (Reuse your generate_payslip logic here, replacing "FEBRUARY 2026" with the month variable)
    return generate_payslip(uid) # Temporary redirect to main logic for now

@app.route('/delete_meeting/<room_name>')
def delete_meeting(room_name):
    if 'user_id' not in session: 
        return jsonify({"status": "error"}), 403
    
    # Find the meeting by room name
    meeting = Meeting.query.filter_by(room_name=room_name).first()
    
    # Optional: Only allow the creator or a Principal/HR to delete it
    if meeting:
        db.session.delete(meeting)
        db.session.commit()
        return jsonify({"status": "success"})
    
    return jsonify({"status": "not_found"}), 404

online_users = {} 

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        online_users[session['user_id']] = session.get('name', 'Staff')
        emit('update_online_status', list(online_users.values()), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        online_users.pop(session['user_id'], None)
        emit('update_online_status', list(online_users.values()), broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    # Sends "User is typing..." to everyone except the person typing
    emit('display_typing', {'user': session.get('name'), 'is_typing': data['is_typing']}, broadcast=True, include_self=False)

@socketio.on('send_chat_message')
def handle_chat(data):
    now = get_ist_time()
    sender_id = session.get('user_id')
    sender_name = session.get('name', 'Anonymous')

    # Save to Database for persistence
    new_msg = Message(sender_id=sender_id, content=data['text'], is_group=True, timestamp=now)
    db.session.add(new_msg)
    db.session.commit()

    emit('new_message', {
        'user': sender_name,
        'user_id': sender_id,
        'text': data['text'],
        'time': now.strftime("%I:%M %p")
    }, broadcast=True)

@app.context_processor
def inject_broadcast():
    # This makes the active alert available to all templates (base.html)
    active = Broadcast.query.filter_by(active=True).order_by(Broadcast.id.desc()).first()
    return dict(active_broadcast=active)

@app.context_processor
def inject_pending_count():
    if 'user_id' in session:
        # This makes 'pending_tasks_count' available to ALL templates automatically
        count = Task.query.filter_by(assigned_to=session['user_id'], is_done=False).count()
        return dict(pending_tasks_count=count)
    return dict(pending_tasks_count=0)
# ==========================================
# 5. FULL SEEDING (INCLUDING ALL FACULTY)
# ==========================================

def seed_database():
    db.create_all()
    
    # System Admin with Address & Dept
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(
            username='admin', 
            password=generate_password_hash('admin123'), 
            role='HR', 
            full_name='System Admin', 
            email='hr@bmsccm.edu', 
            dob='1985-10-25', 
            join_date='2018-05-10', 
            caste='General', 
            religion='Hindu',
            department='Administration',
            dept_id='BMS-ADM-001',
            address='BMSCCM Campus, Basavanagudi, Bengaluru'
        ))

    # Accountant with Address & Dept
    if not User.query.filter_by(username='acc1').first():
        db.session.add(User(
            username='acc1', 
            password=generate_password_hash('pay123'), 
            role='Accountant', 
            full_name='Rajesh Finance', 
            email='accounts@bmsccm.edu', 
            dob='1990-03-12', 
            join_date='2020-11-20', 
            caste='General', 
            religion='Hindu',
            department='Accounts',
            dept_id='BMS-ACC-001',
            address='No. 45, Gandhi Bazaar, Bengaluru'
        ))
    
    # Faculty list with added Dept, DeptID, and Address (Address is at the end)
    # Format: (username, name, role, email, caste, religion, dob, join, dept, dept_id, address)
    faculties = [
        ('balram', 'Balram M N', 'Faculty', 'balram@bmsccm.edu', 'General', 'Hindu', '1982-04-15', '2015-06-01', 'Commerce', 'BMS-COM-101', 'Jayanagar 4th Block, Bengaluru'),
        ('kiran', 'Kiran Kumar M N', 'HOD - BCA Dept', 'kiran.hod@bmsccm.edu', 'General', 'Hindu', '1978-11-20', '2010-01-15', 'Computer Applications', 'BMS-BCA-001', 'Banashankari 3rd Stage, Bengaluru'),
        ('shrinkala', 'Miss. Shrinkala', 'Faculty', 'shrinkala@bmsccm.edu', 'General', 'Hindu', '1992-08-30', '2021-09-10', 'Management', 'BMS-MGT-201', 'V.V. Puram, Bengaluru'),
        ('shivani', 'Mrs. Shivani', 'Faculty', 'shivani@bmsccm.edu', 'General', 'Hindu', '1988-03-05', '2019-02-14', 'Commerce', 'BMS-COM-102', 'Basavanagudi, Bengaluru'),
        ('ramkishore', 'Mr. Ramkishore', 'Faculty', 'ramkishore@bmsccm.edu', 'General', 'Hindu', '1985-12-12', '2017-07-20', 'Commerce', 'BMS-COM-103', 'JP Nagar, Bengaluru'),
        ('prathiba', 'Mrs. Prathiba Singh', 'Faculty', 'prathiba@bmsccm.edu', 'General', 'Hindu', '1990-05-25', '2022-11-01', 'Management', 'BMS-MGT-202', 'Uttarahalli, Bengaluru'),
        ('newfac', 'New Faculty', 'Faculty', 'new@bmsccm.edu', 'General', 'Not Specified', '1998-01-01', '2025-01-01', 'Commerce', 'BMS-COM-999', 'Bengaluru South'),
        ('pankaj', 'Mr. Pankaj Choudhry', 'Principal', 'principal@bmsccm.edu', 'General', 'Hindu', '1975-09-10', '2005-08-15', 'Executive', 'BMS-EXE-001', 'Principal Quarters, BMSCCM')
    ]

    for u, f, r, e, c, rel, d, j, dept, did, addr in faculties:
        if not User.query.filter_by(username=u).first():
            db.session.add(User(
                username=u, 
                password=generate_password_hash('bms123'), 
                role=r, 
                full_name=f, 
                salary=50000, 
                email=e, 
                dob=d, 
                join_date=j, 
                caste=c, 
                religion=rel,
                department=dept,
                dept_id=did,
                address=addr
            ))
            
    db.session.commit()

with app.app_context():
    db.create_all()
    seed_database()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))













































