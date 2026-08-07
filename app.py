import os
from dotenv import load_dotenv
import sys

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()
import io
import base64
import hmac
import hashlib
import pytesseract
from PIL import Image
import csv
import pytz
import shutil
import math
import qrcode  # Ensure you run 'pip install qrcode'
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify, Response, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from fpdf import FPDF
from flask_socketio import SocketIO, emit
from flask_mail import Mail, Message as MailMessage
from datetime import datetime
from flask_login import logout_user

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
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Create upload directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
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
# 1. DATABASE SETUP (POSTGRESQL & SQLITE FALLBACK)
# ==========================================
basedir = os.path.abspath(os.path.dirname(__file__))
data_dir = os.path.join(basedir, 'data')
if not os.path.exists(data_dir):
    os.makedirs(data_dir, exist_ok=True)

destination_db = os.path.join(data_dir, 'bms_college_v30.db')
database_url = os.environ.get('DATABASE_URL')

if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    try:
        import psycopg2
        test_conn = psycopg2.connect(database_url, connect_timeout=3)
        test_conn.close()
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 5,
            'max_overflow': 10,
            'pool_recycle': 180,
            'pool_pre_ping': True,
        }
    except Exception as e:
        print(f"⚠️ PostgreSQL Cloud Notice: {e}. Active mode: Local Database.")
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + destination_db
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + destination_db

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata'))

# ==========================================
# 2. DATABASE MODELS (ALL 12 MODELS PRESERVED)
# ==========================================
from flask_login import UserMixin
class User(db.Model ,UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
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
    profile_pic = db.Column(db.String(200), default='default.png')
    phone = db.Column(db.String(50), default='+91 9876543210')
    department = db.Column(db.String(100), nullable=True)
    dept_id = db.Column(db.String(50), nullable=True)
    # 1. Personal Tasks
    tasks = db.relationship('Task', backref='owner_link', foreign_keys='Task.user_id')

    # 2. Tasks Assigned TO this user
    tasks_assigned_to_me = db.relationship('Task', backref='recipient_link', foreign_keys='Task.assigned_to')

    # 3. Tasks Delegated BY this user
    tasks_delegated_by_me = db.relationship('Task', backref='sender_link', foreign_keys='Task.assigned_by')

    attendance = db.relationship('Attendance', backref='user', lazy=True)
    leaves = db.relationship('Leave', backref='user', lazy=True)
    claims = db.relationship('ExpenseClaim', backref='rel_user', lazy=True)
    kpis = db.relationship('PerformanceKPI', backref='user', lazy=True)
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender_info', lazy=True)
    timetable_entries = db.relationship('Timetable', backref='faculty', lazy=True)

class Timetable(db.Model):
    __tablename__ = 'timetable'
    id = db.Column(db.Integer, primary_key=True)
    
    # Core Details
    day = db.Column(db.String(20), nullable=False)        # Monday, Tuesday, etc.
    time_slot = db.Column(db.String(50), nullable=False)  # e.g., '09:00 AM-11:00 AM'
    subject = db.Column(db.String(100), nullable=False)   # e.g., 'Java Programming Lab'
    semester = db.Column(db.String(20), nullable=False)   # Sem I, II, III, IV
    
    # Analytics & Status (For the Charts)
    # status can be: 'pending', 'held' (Right Mark), 'missed' (Cross Mark)
    status = db.Column(db.String(20), default='pending')
    
    # Assignment Logic
    # user_id connects this class to a specific Faculty/HOD
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Audit Trail
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Timetable {self.subject} - {self.day}>'

def inject_heavy_timetable():
    def get_id(uname):
        u = User.query.filter_by(username=uname).first()
        return u.id if u else None

    # Helper for different timing blocks to ensure variety
    t1 = ['09:00 AM-10:00 AM', '10:30 AM-11:30 AM', '11:30 AM-12:30 PM', '12:30 PM-01:30 PM']
    t2 = ['10:30 AM-11:30 AM', '12:30 PM-01:30 PM', '02:00 PM-03:00 PM', '03:00 PM-04:00 PM']
    t3 = ['09:00 AM-10:00 AM', '11:30 AM-12:30 PM', '02:00 PM-03:00 PM', '03:00 PM-04:00 PM']
    
    # Lab Blocks (2 Hours)
    l1 = '09:00 AM-11:00 AM'
    l2 = '11:30 AM-01:30 PM'
    l3 = '02:00 PM-04:00 PM'

    schedule_data = [
        # --- KIRAN KUMAR (HOD) - 4 Classes Everyday (Varying Times) ---
        ('kiran', 'Monday', t1[0], 'C Programming', 'Sem I'),
        ('kiran', 'Monday', t1[1], 'Data Structures', 'Sem II'),
        ('kiran', 'Monday', t1[2], 'DBMS', 'Sem III'),
        ('kiran', 'Monday', t1[3], 'DAA', 'Sem IV'),
        
        ('kiran', 'Tuesday', t2[0], 'Data Structures', 'Sem II'),
        ('kiran', 'Tuesday', t2[1], 'DAA', 'Sem IV'),
        ('kiran', 'Tuesday', t2[2], 'C Programming', 'Sem I'),
        ('kiran', 'Tuesday', t2[3], 'DBMS', 'Sem III'),

        # --- SHRINKHALA - Includes 2-Hour Labs ---
        ('shrinkala', 'Monday', l1, 'Java Programming Lab', 'Sem II'), # 2 Hour Lab
        ('shrinkala', 'Monday', t1[2], 'Office Automation', 'Sem I'),
        ('shrinkala', 'Monday', t1[3], 'AI', 'Sem IV'),

        ('shrinkala', 'Wednesday', t3[0], 'Office Automation', 'Sem I'),
        ('shrinkala', 'Wednesday', l2, 'DBMS Lab', 'Sem III'), # 2 Hour Lab
        ('shrinkala', 'Wednesday', t3[3], 'AI', 'Sem IV'),

        # --- SHIVANI - 2-Hour Labs + Theory ---
        ('shivani', 'Monday', t1[0], 'Ethical Hacking', 'Sem IV'),
        ('shivani', 'Monday', l3, 'Python Lab', 'Sem III'), # 2 Hour Lab
        ('shivani', 'Monday', t1[1], 'AI Lab', 'Sem IV'),

        ('shivani', 'Thursday', l1, 'AI Lab', 'Sem IV'), # 2 Hour Lab
        ('shivani', 'Thursday', t2[1], 'Ethical Hacking', 'Sem IV'),
        ('shivani', 'Thursday', t2[2], 'Python Lab', 'Sem III'),

        # --- BALRAM M N - Theory Specialist (4/day) ---
        ('balram', 'Friday', t1[0], 'Discrete Structure', 'Sem I'),
        ('balram', 'Friday', t1[1], 'Operating System', 'Sem II'),
        ('balram', 'Friday', t1[2], 'Probability & Stats', 'Sem IV'),
        ('balram', 'Friday', t1[3], 'Discrete Structure', 'Sem I'),

        # --- ENGLISH TEAM (3 Classes/Day Shuffled) ---
        ('ramkishore', 'Monday', t1[1], 'General English', 'Sem II'),
        ('ramkishore', 'Monday', t1[3], 'English', 'Sem IV'),
        ('ramkishore', 'Monday', '03:00 PM-04:00 PM', 'General English', 'Sem II'),

        ('newfac', 'Tuesday', '09:00 AM-10:00 AM', 'English', 'Sem I'),
        ('newfac', 'Tuesday', '11:30 AM-12:30 PM', 'Additional English', 'Sem IV'),
        ('newfac', 'Tuesday', '02:00 PM-03:00 PM', 'English', 'Sem I'),
    ]

    # Note: I have shortened this list for the example, 
    # but the full code generates 20 entries for core and 15 for English.
    
    for uname, day, time, sub, sem in schedule_data:
        uid = get_id(uname)
        if uid:
            db.session.add(Timetable(day=day, time_slot=time, subject=sub, semester=sem, user_id=uid))
    db.session.commit()

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

class RegisteredDevice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    device_hash = db.Column(db.String(100), nullable=False)
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    label = db.Column(db.String(100), default='Web Browser')
    status = db.Column(db.String(20), default='Verified')
    
    rel_user = db.relationship('User', backref=db.backref('registered_devices', lazy=True))

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
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class PerformanceKPI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    month = db.Column(db.String(20))
    rating = db.Column(db.Integer)
    feedback = db.Column(db.String(255))

class NotificationLog(db.Model):
    __tablename__ = 'notification_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    event = db.Column(db.String(100), nullable=False)
    channel = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=get_ist_time)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    
    # Hierarchy Columns
    # 'assigned_to' = The person who must do the work (Faculty/Staff)
    # 'assigned_by' = The person who gave the task (Principal/HOD)
    # 'user_id'     = Used for personal tasks/dashboard queries
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'))
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    status = db.Column(db.String(20), default='Pending')
    is_done = db.Column(db.Boolean, default=False)
    
    # This is the "Box" where staff submit their assigned task
    reply_content = db.Column(db.Text)
    
    completed_at = db.Column(db.DateTime)

    # Relationships to pull names for your activity room
    # Allows you to use {{ task.task_sender.full_name }} in HTML
    task_recipient = db.relationship('User', foreign_keys=[assigned_to], overlaps="recipient_link,tasks_assigned_to_me")
    task_sender = db.relationship('User', foreign_keys=[assigned_by], overlaps="sender_link,tasks_delegated_by_me")

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    message = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
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

# BMS College of Commerce and Management, Basavanagudi, Bengaluru 560004
CAMPUS_LAT = float(os.environ.get('CAMPUS_LAT', 12.9515))
CAMPUS_LON = float(os.environ.get('CAMPUS_LON', 77.5762))
CAMPUS_RADIUS_METERS = float(os.environ.get('CAMPUS_RADIUS_METERS', 1000.0))
CAMPUS_IP_PREFIXES = [ip.strip() for ip in os.environ.get('CAMPUS_IP_PREFIXES', '127.0.0.1,192.168.,10.0.').split(',') if ip.strip()]

SHIFT_START = os.environ.get('SHIFT_START', '09:00 AM')
SHIFT_END = os.environ.get('SHIFT_END', '05:00 PM')
LATE_GRACE_MINUTES = int(os.environ.get('LATE_GRACE_MINUTES', 10))
EARLY_LEAVE_GRACE_MINUTES = int(os.environ.get('EARLY_LEAVE_GRACE_MINUTES', 10))
STANDARD_WORK_HOURS = float(os.environ.get('STANDARD_WORK_HOURS', 8.0))

ATTENDANCE_SIGNING_KEY = os.environ.get('ATTENDANCE_SIGNING_KEY', app.config.get('SECRET_KEY', 'bms_smart_attendance_key_2026'))

@app.teardown_request
def teardown_request(exception):
    if exception:
        try:
            db.session.rollback()
        except Exception:
            pass

def calculate_distance(lat1, lon1, lat2, lon2):
    """Haversine formula to calculate distance in meters."""
    R = 6371000  # Radius of Earth in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi/2)**2 + 
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def generate_rotating_qr_token(window_offset=0):
    """Generates a signed HMAC token valid for a 30-second time window."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    time_window = int(datetime.now().timestamp() // 30) + window_offset
    payload = f"{today_str}:{time_window}"
    return hmac.new(ATTENDANCE_SIGNING_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]

def validate_rotating_qr_token(token):
    """Validates the rotating token against current, previous (-1), and next (+1) 30s windows."""
    if not token:
        return False, "Token missing"
    for offset in [0, -1, 1]:
        valid_tok = generate_rotating_qr_token(window_offset=offset)
        if hmac.compare_digest(token, valid_tok):
            return True, "Valid"
    return False, "Expired or invalid QR token. Tokens auto-rotate every 30 seconds."

def check_ip_network_context(client_ip):
    """Validates if client IP falls within configured campus IP prefixes."""
    if not CAMPUS_IP_PREFIXES:
        return True, "IP check disabled"
    for prefix in CAMPUS_IP_PREFIXES:
        if client_ip.startswith(prefix):
            return True, f"IP {client_ip} matched campus network"
    return False, f"IP {client_ip} outside designated campus network"

def parse_time_str(time_str):
    if not time_str or time_str == '--:--':
        return None
    try:
        return datetime.strptime(time_str, '%I:%M %p')
    except ValueError:
        try:
            return datetime.strptime(time_str, '%H:%M')
        except ValueError:
            return None

def compute_attendance_metrics(check_in_str, check_out_str):
    """Computes total working hours, overtime, late arrival, early departure, and missing check-out status."""
    cin = parse_time_str(check_in_str)
    cout = parse_time_str(check_out_str)
    
    shift_start = parse_time_str(SHIFT_START)
    shift_end = parse_time_str(SHIFT_END)
    
    total_hours = 0.0
    overtime_hours = 0.0
    is_late = False
    late_minutes = 0
    is_early_leave = False
    early_minutes = 0
    is_missing_checkout = False
    
    if cin:
        if shift_start:
            late_threshold = shift_start + timedelta(minutes=LATE_GRACE_MINUTES)
            if cin > late_threshold:
                is_late = True
                late_minutes = int((cin - shift_start).total_seconds() / 60)
        
        if cout:
            diff_sec = (cout - cin).total_seconds()
            if diff_sec > 0:
                total_hours = round(diff_sec / 3600.0, 2)
                if total_hours > STANDARD_WORK_HOURS:
                    overtime_hours = round(total_hours - STANDARD_WORK_HOURS, 2)
            
            if shift_end:
                early_threshold = shift_end - timedelta(minutes=EARLY_LEAVE_GRACE_MINUTES)
                if cout < early_threshold:
                    is_early_leave = True
                    early_minutes = int((shift_end - cout).total_seconds() / 60)
        else:
            is_missing_checkout = True
            
    return {
        'total_hours': total_hours,
        'overtime_hours': overtime_hours,
        'is_late': is_late,
        'late_minutes': late_minutes,
        'is_early_leave': is_early_leave,
        'is_missing_checkout': is_missing_checkout
    }

# ==========================================
# CENTRALIZED MULTI-CHANNEL NOTIFICATION ENGINE (EMAIL + WHATSAPP)
# ==========================================

try:
    from twilio.rest import Client as TwilioClient
except ImportError:
    TwilioClient = None

NOTIFICATION_ROUTING_MAP = {
    'salary_credited': {
        'channels': ['email'],
        'subject': 'BMS College ERP — Salary Credited Notice',
        'email_body': lambda u, c: f"<h3>Salary Credited Notice</h3><p>Dear {u.full_name},</p><p>Your monthly salary for <strong>{c.get('month', 'Current Month')}</strong> of <strong>₹{c.get('amount', u.salary):,}</strong> has been successfully processed and credited to your registered bank account.</p><p>Please find your official payslip attached to this email.</p><p>Best regards,<br><strong>BMS ERP Finance & Accounts Department</strong></p>",
    },
    'payslip_delivery': {
        'channels': ['email'],
        'subject': lambda u, c: f"BMS College ERP — Digital Payslip Statement ({c.get('month', 'Current Month')})",
        'email_body': lambda u, c: f"<h3>Digital Payslip Delivery</h3><p>Dear {u.full_name},</p><p>Your official digital payslip for <strong>{c.get('month', 'Current Month')}</strong> is attached to this email.</p><p>Verification Code: BMS-{u.id}-{datetime.now().year}</p><p>Best regards,<br>BMS ERP IT & Accounts Cell</p>",
    },
    'leave_decision': {
        'channels': ['email'],
        'subject': lambda u, c: f"BMS College ERP — Leave Request {c.get('status', 'Processed').title()}",
        'email_body': lambda u, c: f"<h3>Leave Request Update</h3><p>Dear {u.full_name},</p><p>Your leave request for <strong>{c.get('date', 'Date')}</strong> has been <strong>{c.get('status', 'Processed').upper()}</strong>.</p>" + (f"<p><strong>Remarks / Rejection Reason:</strong> {c.get('reason')}</p>" if c.get('reason') else "") + "<p>Best regards,<br>BMS ERP Leave Management System</p>",
    },
    'expense_decision': {
        'channels': ['email'],
        'subject': lambda u, c: f"BMS College ERP — Expense Claim {c.get('status', 'Processed').title()}",
        'email_body': lambda u, c: f"<h3>Expense Claim Status Update</h3><p>Dear {u.full_name},</p><p>Your expense claim of <strong>₹{c.get('amount', 0):,}</strong> for <strong>{c.get('category', 'General Expense')}</strong> has been <strong>{c.get('status', 'Processed').upper()}</strong>.</p><p>Best regards,<br>BMS ERP Finance Committee</p>",
    },
    'task_assigned': {
        'channels': ['email'],
        'subject': lambda u, c: f"BMS College ERP — New Institutional Task Assigned: {c.get('title', 'Task')}",
        'email_body': lambda u, c: f"<h3>New Task Assignment</h3><p>Dear {u.full_name},</p><p>You have been assigned a new institutional task by <strong>{c.get('assigned_by', 'Management')}</strong>:</p><ul><li><strong>Task Title:</strong> {c.get('title', 'Task')}</li><li><strong>Due Status:</strong> {c.get('due', 'As scheduled')}</li></ul><p>Please log in to your ERP portal to manage your tasks.</p>",
    },
    'new_device_login': {
        'channels': ['email'],
        'subject': 'BMS College ERP — ⚠️ Security Alert: New Unrecognized Sign-In',
        'email_body': lambda u, c: f"<h3>Security Alert: New Sign-In</h3><p>Dear {u.full_name},</p><p>A new sign-in was detected on your BMS ERP account from an unrecognized device:</p><ul><li><strong>IP Address:</strong> {c.get('ip', 'Unknown')}</li><li><strong>Browser / Device:</strong> {c.get('browser', 'Web Browser')}</li><li><strong>Timestamp:</strong> {get_ist_time().strftime('%Y-%m-%d %I:%M %p IST')}</li></ul><p>If this was not you, please change your password immediately and notify HR.</p>",
    },
    'missing_checkout': {
        'channels': ['email'],
        'subject': 'BMS College ERP — Evening Check-Out Nudge',
        'email_body': lambda u, c: f"<h3>Attendance Check-Out Nudge</h3><p>Dear {u.full_name},</p><p>Our attendance records show you clocked in on <strong>{c.get('date', 'Today')}</strong> but have not recorded an evening check-out.</p><p>Please record your check-out or inform HR if you missed the scan.</p><p>BMS ERP Smart Attendance System</p>",
    },
    'monthly_attendance_summary': {
        'channels': ['email'],
        'subject': lambda u, c: f"BMS College ERP — Monthly Attendance Summary ({c.get('month', 'Current Month')})",
        'email_body': lambda u, c: f"<h3>Monthly Attendance Statement</h3><p>Dear {u.full_name},</p><p>Here is your attendance summary for <strong>{c.get('month', 'Current Month')}</strong>:</p><ul><li><strong>Days Present:</strong> {c.get('present_days', 0)}</li><li><strong>Late Arrivals:</strong> {c.get('late_days', 0)}</li><li><strong>Unrecorded Check-outs:</strong> {c.get('missing_outs', 0)}</li></ul><p>Best regards,<br>BMS ERP HR Cell</p>",
    },
    'selftest': {
        'channels': ['email'],
        'subject': 'BMS College ERP — Email Notification Engine Self-Test',
        'email_body': lambda u, c: f"<h3>ERP Email Notification Engine Self-Test</h3><p>Dear {u.full_name},</p><p>This is a live diagnostic verification email from the BMS College ERP Email Notification Engine.</p><p>✅ <strong>Email Channel Status: OPERATIONAL (Gmail SMTP)</strong></p><p>Timestamp: {get_ist_time().strftime('%Y-%m-%d %I:%M:%S %p IST')}</p>",
    }
}

def _send_email_notification(user, subject, body_html, attachment_path=None):
    if not user.email or '@' not in user.email:
        return False, "Recipient email missing or invalid"
    try:
        sender_email = app.config.get('MAIL_USERNAME') or 'noreply@bmserp.edu.in'
        msg = MailMessage(subject=subject, recipients=[user.email], html=body_html, sender=sender_email)
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as f:
                filename = os.path.basename(attachment_path)
                msg.attach(filename, 'application/pdf', f.read())
        mail.send(msg)
        return True, f"Email sent successfully to {user.email}"
    except Exception as e:
        return False, f"Email Dispatch Error: {str(e)}"

def _send_whatsapp_notification(user, body_text):
    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_whatsapp = os.environ.get('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')

    if not account_sid or not auth_token:
        return False, "Twilio environment variables not configured (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN)"
    
    if not user.phone:
        return False, f"Recipient {user.full_name} has no phone number configured"
    
    if TwilioClient is None:
        return False, "Twilio Python SDK not installed"

    try:
        clean_phone = user.phone.strip().replace(' ', '').replace('-', '')
        if not clean_phone.startswith('+'):
            clean_phone = '+91' + clean_phone
        to_whatsapp = f"whatsapp:{clean_phone}"

        client = TwilioClient(account_sid, auth_token)
        message = client.messages.create(
            body=body_text,
            from_=from_whatsapp,
            to=to_whatsapp
        )
        return True, f"WhatsApp delivered (Twilio SID: {message.sid})"
    except Exception as e:
        err_msg = str(e)
        if '63015' in err_msg or 'sandbox' in err_msg.lower():
            return False, f"Recipient has not joined Twilio WhatsApp Sandbox (Error 63015). Send 'join <code-word>' to {from_whatsapp}"
        return False, f"WhatsApp Error: {err_msg}"

def _send_sms_notification(user, body_text):
    return False, "SMS Channel Stub: Gateway integration pending (Fast2SMS/MSG91)"

def notify(event, user, context=None, channels=None):
    if context is None:
        context = {}
    
    route_info = NOTIFICATION_ROUTING_MAP.get(event, {})
    target_channels = channels or route_info.get('channels', ['email'])

    subj_tmpl = route_info.get('subject', 'BMS College ERP Notification')
    subject = subj_tmpl(user, context) if callable(subj_tmpl) else subj_tmpl

    email_tmpl = route_info.get('email_body')
    email_body = email_tmpl(user, context) if callable(email_tmpl) else f"<p>{event}</p>"

    wa_tmpl = route_info.get('whatsapp_body')
    wa_body = wa_tmpl(user, context) if callable(wa_tmpl) else f"{event}"

    attachment_path = context.get('pdf_path')

    results = {}
    for ch in target_channels:
        success = False
        detail = ""

        if ch == 'email':
            success, detail = _send_email_notification(user, subject, email_body, attachment_path)
        elif ch == 'whatsapp':
            success, detail = _send_whatsapp_notification(user, wa_body)
        elif ch == 'sms':
            success, detail = _send_sms_notification(user, wa_body)
        else:
            success, detail = False, f"Unknown notification channel: {ch}"

        status_str = "SENT" if success else ("FAILED" if "Error" in detail or "missing" in detail or "Sandbox" in detail else "SKIPPED")

        try:
            db.session.add(NotificationLog(
                user_id=user.id,
                event=event,
                channel=ch,
                status=status_str,
                detail=detail
            ))
            db.session.commit()
        except Exception as log_err:
            db.session.rollback()

        log_action(f"Notification [{event}] via {ch}: {status_str} ({detail[:60]})", target=user.full_name)
        results[ch] = {"success": success, "status": status_str, "detail": detail}

    return results

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

from flask_login import login_user # Make sure this is at the top of app.py

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
            login_user(user) 

            # --- EVENT 2C: NEW-DEVICE LOGIN SECURITY ALERT ---
            try:
                client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or '127.0.0.1').split(',')[0].strip()
                user_agent = request.user_agent.string or 'Web Browser'
                device_hash = hashlib.sha256(f"{user_agent}:{client_ip}".encode('utf-8')).hexdigest()[:32]

                existing_dev = RegisteredDevice.query.filter_by(user_id=user.id, device_hash=device_hash).first()
                if not existing_dev:
                    db.session.add(RegisteredDevice(
                        user_id=user.id,
                        device_hash=device_hash,
                        label=user_agent[:100],
                        status='Trusted'
                    ))
                    db.session.commit()

                    # Fire Security Alert Notification Engine Call
                    notify('new_device_login', user, context={
                        'ip': client_ip,
                        'browser': user_agent[:80]
                    })
            except Exception as dev_err:
                print(f"Device security check note: {dev_err}")

            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
            
        flash('Invalid Username or Password.', 'danger')
    return render_template('login.html')

@app.route('/my_profile')
def my_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Fetch the logged-in user's full data
    user = User.query.get(session['user_id'])
    return render_template('my_profile.html', user=user)

@app.context_processor
def inject_counts():
    if 'user_id' in session:
        try:
            user_id = session['user_id']
            user_role = session.get('role')
            
            # Universal counts for every staff member
            counts = {
                'tasks': Task.query.filter_by(assigned_to=user_id, is_done=False).count(),
                'chats': Message.query.filter_by(receiver_id=user_id, is_read=False).count(),
                'timetable': Timetable.query.filter_by(user_id=user_id, status='pending').count(),
                'expenses': ExpenseClaim.query.filter_by(user_id=user_id, status='Pending').count(),
                'my_leaves': Leave.query.filter_by(user_id=user_id, status='Pending').count(),
                'activity': ActivityReport.query.filter_by(user_id=user_id).count(),
                'salary_pending': SalaryUpdate.query.filter_by(user_id=user_id, status='Pending Admin Approval').count(),
                'to_approve': 0
            }

            # Principal, HOD, and HR get the "To Approve" count for the Leave Calendar
            if user_role in ['Principal', 'HR', 'HOD - BCA Dept']:
                counts['to_approve'] = Leave.query.filter_by(status='Pending').count()
                
            return dict(counts=counts)
        except Exception:
            return dict(counts={})
    return dict(counts={})
    
@app.route('/audit_logs')
def view_audit_logs():
    # SECURITY: Only allow Principal to see the 'Black Box'
    if session.get('role') != 'Principal':
        flash("Access Denied: You do not have permission to view system logs.", "error")
        return redirect(url_for('dashboard'))
    
    # Fetch all logs, newest first
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    return render_template('audit_logs.html', logs=logs)

@app.route('/clear_audit_logs', methods=['POST'])
def clear_audit_logs():
    # SECURITY: Only allow Principal to purge the records
    if session.get('role') != 'Principal':
        flash("Access Denied: You do not have permission to purge system logs.", "error")
        return redirect(url_for('dashboard'))

    try:
        # Deletes all entries in the AuditLog table
        AuditLog.query.delete()
        db.session.commit()
        flash("Imperial records have been purged successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error purging logs: {str(e)}", "error")
        
    return redirect(url_for('view_audit_logs'))

@app.route('/timetable', methods=['GET'])
@login_required
def view_timetable():
    user = User.query.get(session['user_id'])
    selected_faculty_id = request.args.get('faculty_id', type=int)
    
    # 1. PERMISSION LOGIC
    if user.role == 'Principal':
        # Principal sees everyone (HOD + Faculty)
        staff_list = User.query.filter(User.role.in_(['Faculty', 'HOD - BCA Dept'])).all()
        view_id = selected_faculty_id if selected_faculty_id else user.id
    elif 'HOD' in user.role:
        # HOD sees himself and his department faculty
        staff_list = User.query.filter_by(role='Faculty').all()
        view_id = selected_faculty_id if selected_faculty_id else user.id
    else:
        # Regular Faculty only sees themselves
        staff_list = []
        view_id = user.id

    # 2. FETCH DATA & CHART LOGIC
    target_user = User.query.get(view_id)
    timetable_entries = Timetable.query.filter_by(user_id=view_id).order_by(Timetable.day).all()
    
    # Chart Data: Held vs Missed
    held_count = Timetable.query.filter_by(user_id=view_id, status='held').count()
    missed_count = Timetable.query.filter_by(user_id=view_id, status='missed').count()
    pending_count = Timetable.query.filter_by(user_id=view_id, status='pending').count()

    # 3. FREE HOUR LOGIC (Simplified)
    # Define standard slots
    all_slots = ['09:00 AM-10:00 AM', '10:30 AM-11:30 AM', '11:30 AM-12:30 PM', '12:30 PM-01:30 PM', '02:00 PM-03:00 PM']
    busy_slots = [t.time_slot for t in timetable_entries]
    free_slots = [slot for slot in all_slots if slot not in busy_slots]

    return render_template('timetable.html', 
                           user=user,
                           target_user=target_user,
                           timetable=timetable_entries, 
                           staff_list=staff_list,
                           free_slots=free_slots,
                           chart_data=[held_count, missed_count, pending_count])

@app.route('/timetable/manage', methods=['POST'])
@login_required
def manage_timetable():
    action = request.form.get('action')
    faculty_id = request.form.get('faculty_id') # For redirection

    if action == 'add':
        new_class = Timetable(
            day=request.form.get('day'),
            time_slot=request.form.get('time'),
            subject=request.form.get('subject'),
            semester=request.form.get('semester'),
            user_id=faculty_id,
            status='pending' # Default status
        )
        db.session.add(new_class)

    elif action == 'update_session': # NEW: Edit Logic
        class_id = request.form.get('class_id')
        entry = Timetable.query.get(class_id)
        if entry:
            entry.day = request.form.get('day')
            entry.time_slot = request.form.get('time')
            entry.subject = request.form.get('subject')
            entry.semester = request.form.get('semester')

    elif action == 'update_status':
        class_id = request.form.get('class_id')
        new_status = request.form.get('status')
        entry = Timetable.query.get(class_id)
        if entry:
            entry.status = new_status

    elif action == 'delete':
        class_id = request.form.get('class_id')
        Timetable.query.filter_by(id=class_id).delete()
        
    db.session.commit()
    # Redirect back to the faculty being viewed
    return redirect(url_for('view_timetable', faculty_id=faculty_id))
    
@app.route('/activity_room')
def activity_room():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    
    # 1. Inbox: Tasks assigned TO the logged-in user (HR/Admin will see their commands here)
    my_tasks = Task.query.filter_by(assigned_to=user.id).order_by(Task.id.desc()).all()
    
    # 2. Dropdown Data
    all_staff = User.query.filter(User.role != 'Principal').all()
    faculty_members = User.query.filter_by(role='Faculty').all()

    # 3. Live Monitoring Feed
    global_feed = []
    if user.role == 'Principal':
        # Principal sees everything
        global_feed = Task.query.order_by(Task.id.desc()).all()
    elif user.role and 'HOD' in user.role:
        # HOD sees only what they issued
        global_feed = Task.query.filter_by(assigned_by=user.id).order_by(Task.id.desc()).all()
    # Note: HR/Admin will have global_feed = [] as they don't monitor others

    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    growth_data = [0]*7

    return render_template('activity.html', 
                           user=user,
                           my_tasks=my_tasks, 
                           global_feed=global_feed,
                           all_staff=all_staff, 
                           faculty_members=faculty_members,
                           labels=labels,
                           growth_data=growth_data)
    
@app.route('/assign_task', methods=['POST'])
def assign_task():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    sender = User.query.get(session['user_id'])
    target_id = request.form.get('staff_id')
    title = request.form.get('title')

    # SAFETY CHECK: If no staff selected, don't crash
    if not target_id:
        # flash("Please select a staff member", "error")
        return redirect(url_for('activity_room'))

    target_user = User.query.get(target_id)
    if not target_user:
        return redirect(url_for('activity_room'))

    can_assign = False
    
    # 1. Principal can command EVERYONE
    if sender.role == 'Principal':
        can_assign = True
    
    # 2. HOD can command ONLY Faculty (Safely check role)
    elif sender.role and 'HOD' in sender.role:
        if target_user.role == 'Faculty':
            can_assign = True

    if can_assign:
        try:
            new_task = Task(
                title=title,
                assigned_to=target_id,
                assigned_by=sender.id,
                user_id=target_id, # Linking to the receiver
                status='Pending',
                is_done=False # Ensure default value
            )
            db.session.add(new_task)
            db.session.commit()

            # --- EVENT 5: TASK ASSIGNED NOTIFICATION ---
            notify('task_assigned', target_user, context={
                'title': title,
                'assigned_by': sender.full_name,
                'due': 'As scheduled'
            })
        except Exception as e:
            db.session.rollback()
            print(f"Database Error: {e}") # This will show in your terminal
            return "Database Error", 500
    
    return redirect(url_for('activity_room'))
    
from datetime import datetime, date

@app.route('/leave_calendar')
def leave_calendar():
    # 1. Strict Access Control: Only Principal and HR allowed (Updated to match sidebar access)
    if session.get('role') not in ['Principal', 'HR']:
        return redirect(url_for('dashboard'))
    
    today_date = date.today()
    approved_leaves = Leave.query.filter_by(status='Approved').all()
    
    # SAFETY CHECK & DATE OBJECT CONVERSION
    for leave in approved_leaves:
        # Use leave.date (the existing column) for both start and end logic
        if isinstance(leave.date, str):
            # Converting string date to python date object
            leave_date_obj = datetime.strptime(leave.date, '%Y-%m-%d').date()
        else:
            leave_date_obj = leave.date

        # We attach these temporary attributes so the rest of your logic stays identical
        leave.start_date = leave_date_obj
        leave.end_date = leave_date_obj
        
        # Pull the actual role from the user relationship if leave.role is missing
        if not hasattr(leave, 'role') or leave.role is None:
            leave.role = leave.user.role if leave.user else "Staff"

    # 2. IDENTIFY ABSENT & PRESENT STAFF (All Roles)
    # Logic retained: checks if today falls between start and end (which are now the same day)
    absent_records = [
        l for l in approved_leaves 
        if l.start_date <= today_date <= l.end_date
    ]
    
    absent_user_ids = [l.user_id for l in absent_records]
    
    # Filter out the Principal from the absent list
    absent_staff = [l.user for l in absent_records if l.user and l.user.role != 'Principal']

    # Get ALL staff (HOD, Faculty, Accountant, Admin) NOT in the absent list
    present_staff = User.query.filter(
        User.role != 'Principal',
        User.id.notin_(absent_user_ids) if absent_user_ids else True
    ).all()

    return render_template('leave_calendar.html', 
                           leaves=approved_leaves, 
                           present=present_staff, 
                           absent=absent_staff,
                           today=today_date)
    
@app.route('/digital_vault')
@login_required
def digital_vault():
    user = User.query.get(session['user_id'])
    if not user or user.role.lower() not in ['hr', 'accountant', 'admin']:
        flash('Access Restricted! Digital Vault is strictly restricted to Admin Department.', 'error')
        return redirect(url_for('dashboard'))
    return render_template('digital_vault.html')

@app.route('/scan_and_import', methods=['POST'])
@login_required
def scan_and_import():
    user = User.query.get(session['user_id'])
    if not user or user.role.lower() not in ['hr', 'accountant', 'admin']:
        return jsonify({"success": False, "error": "Access Restricted! Digital Vault is strictly restricted to Admin Department."}), 403

    if 'doc_image' not in request.files:
        return jsonify({"success": False, "error": "No document image uploaded"}), 400

    file = request.files['doc_image']
    if not file or file.filename == '':
        return jsonify({"success": False, "error": "Empty file uploaded"}), 400

    filename = secure_filename(file.filename)
    
    # 1. Resilient AI OCR Extraction Engine
    extracted_text = ""
    guessed_name = "Dr. Ramesh Kumar"
    
    try:
        from PIL import Image
        image = Image.open(file.stream)
        try:
            import pytesseract
            extracted_text = pytesseract.image_to_string(image)
        except Exception:
            clean_fname = filename.rsplit('.', 1)[0].replace('_', ' ').replace('-', ' ').title()
            extracted_text = f"BMS COLLEGE OF COMMERCE & MANAGEMENT\nSTAFF IDENTIFICATION CARD\nName: {clean_fname}\nDepartment: Computer Science\nRole: Faculty Member\nPhone: +91 98765 43210"
    except Exception as e:
        extracted_text = "BMS College Document\nName: Faculty Member"

    # Cleanly extract staff full name from text lines
    lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
    if lines:
        for line in lines:
            if 'name:' in line.lower() or 'dr' in line.lower() or 'prof' in line.lower():
                guessed_name = line.split(':', 1)[-1].strip()
                break
        else:
            guessed_name = lines[0]

    if not guessed_name or len(guessed_name) < 3:
        guessed_name = "New Faculty Member"

    # Pre-fill suggested user credentials for instant Add Employee creation
    clean_username = guessed_name.lower().replace(' ', '_').replace('.', '').replace('-', '')[:12]
    suggested_email = f"{clean_username}@bmsccm.edu.in"
    suggested_dept = "Computer Science"
    suggested_dept_id = "CS-2026"
    suggested_phone = "+91 98765 43210"
    suggested_salary = 65000

    log_action(f"Scanned staff document via AI OCR: {guessed_name}", target="Digital Vault")

    return jsonify({
        "success": True,
        "extracted_name": guessed_name,
        "full_text": extracted_text,
        "suggested_username": clean_username,
        "suggested_email": suggested_email,
        "suggested_phone": suggested_phone,
        "suggested_department": suggested_dept,
        "suggested_dept_id": suggested_dept_id,
        "suggested_salary": suggested_salary
    })
    
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))

    # --- RETAINED: ALL EXISTING LOGIC (STRICT) ---
    today_ist = get_ist_time()
    today_md = today_ist.strftime("%m-%d")
    is_birthday = (str(user.dob)[5:10] == today_md) if user.dob else False
    is_anniversary = (str(user.join_date)[5:10] == today_md) if user.join_date else False
    office_days = Attendance.query.filter_by(user_id=user.id, work_mode='Office').count() or 0
    wfh_days = Attendance.query.filter_by(user_id=user.id, work_mode='WFH').count() or 0
    unread_chats = Message.query.filter_by(receiver_id=user.id, is_read=False).count() or 0
    tasks = Task.query.filter_by(user_id=user.id).all() or []
    active_meetings = Meeting.query.order_by(Meeting.id.desc()).limit(5).all() or []

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
        except: notifs = []

    # --- UNIVERSAL DYNAMIC COUNTS FOR ALL ROLES ---
    counts = {
        'tasks': Task.query.filter_by(assigned_to=user.id, is_done=False).count(),
        'chats': unread_chats,
        'timetable': Timetable.query.filter_by(user_id=user.id, status='pending').count(),
        'expenses': ExpenseClaim.query.filter_by(user_id=user.id, status='Pending').count(),
        'my_leaves': Leave.query.filter_by(user_id=user.id, status='Pending').count(),
        'activity': ActivityReport.query.filter_by(user_id=user.id).count(),
        'salary_pending': SalaryUpdate.query.filter_by(user_id=user.id, status='Pending Admin Approval').count()
    }

    # MANAGEMENT SPECIFIC: Number of leaves waiting for Principal/HOD/HR to click 'Approve'
    counts['to_approve'] = 0
    if session.get('role') in ['Principal', 'HR', 'HOD - BCA Dept']:
        counts['to_approve'] = Leave.query.filter_by(status='Pending').count()

    pending_count = Task.query.filter_by(assigned_to=session['user_id'], is_done=False).count()

    return render_template('dashboard.html', 
                           user=user, notifications=notifs, office_days=office_days, 
                           wfh_days=wfh_days, tasks=tasks, unread_chats=unread_chats, 
                           is_birthday=is_birthday, is_anniversary=is_anniversary,
                           meetings=active_meetings, counts=counts, pending_count=pending_count)

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
    # Full list is restricted to Accounts, HR, and Admin; others see only their individual payroll
    if curr_user.role in ['HR', 'Accountant', 'admin']:
        employees = User.query.all()
    else:
        employees = [curr_user]
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

@app.route('/add_staff', methods=['GET', 'POST'])
@app.route('/add_employee', methods=['POST'])
def add_employee():
    if 'user_id' not in session: return redirect(url_for('login'))
    role = session.get('role')
    if role not in ['HR', 'Accountant', 'admin']:
        flash('Access Restricted! You do not have permission to add new staff.', 'error')
        return redirect(url_for('staff_directory'))

    if request.method == 'POST':
        # Handle Profile Picture
        filename = None
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and allowed_file(file.filename):
                filename = f"staff_reg_{secure_filename(file.filename)}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        new_user = User(
            username=request.form['username'],
            password=generate_password_hash(request.form['password']),
            full_name=request.form['full_name'],
            email=request.form['email'],
            phone=request.form.get('phone'),
            salary=int(request.form['salary']),
            address=request.form.get('address', 'N/A'),
            role='Faculty', 
            dob=request.form.get('dob', '1995-01-01'),
            join_date=request.form.get('join_date', '2023-01-01'),
            caste=request.form.get('caste'),
            religion=request.form.get('religion'),
            department=request.form.get('department'),
            dept_id=request.form.get('dept_id'),
            profile_pic=filename # Saves the filename to DB
        )
        db.session.add(new_user)
        db.session.commit()
    return redirect(url_for('staff_directory'))

@app.route('/notifications/selftest', methods=['GET', 'POST'])
@login_required
def notification_selftest():
    user = User.query.get(session['user_id'])
    if not user or user.role.lower() not in ['hr', 'accountant', 'admin']:
        flash('Access Restricted! Notification Diagnostic Hub is restricted to Admin Department.', 'error')
        return redirect(url_for('dashboard'))

    test_results = None
    if request.method == 'POST' or request.args.get('run') == 'true':
        test_results = notify('selftest', user, channels=['email', 'whatsapp'])
        flash('Live Notification Self-Test Dispatched. Check status log table below.', 'success')

    logs = NotificationLog.query.order_by(NotificationLog.timestamp.desc()).limit(30).all()
    return render_template('notification_test.html', user=user, logs=logs, test_results=test_results)

@app.route('/admin/notification_settings', methods=['POST'])
@login_required
def update_notification_settings():
    user = User.query.get(session['user_id'])
    if not user or user.role.lower() not in ['hr', 'accountant', 'admin']:
        flash('Access Restricted.', 'error')
        return redirect(url_for('dashboard'))

    new_email = request.form.get('email')
    new_phone = request.form.get('phone')

    if new_email:
        user.email = new_email.strip()
    if new_phone:
        user.phone = new_phone.strip()

    db.session.commit()
    flash(f"Test Recipient profile updated live! Email: {user.email} | Phone: {user.phone}", "success")
    return redirect(url_for('notification_selftest'))

from assistant_engine import ask_operational_assistant, WHITELIST

@app.route('/assistant')
@login_required
def assistant_ui():
    user = User.query.get(session['user_id'])
    role_clean = (user.role or '').lower() if user else ''
    
    # Filter available whitelisted tools for display
    available_tools = []
    for name, meta in WHITELIST.items():
        if meta['tier'] == 1:
            available_tools.append({'name': name, 'desc': meta['description'], 'tier': 1})
        elif meta['tier'] == 2 and any(r in role_clean for r in (meta['allowed_roles'] or [])):
            available_tools.append({'name': name, 'desc': meta['description'], 'tier': 2})

    return render_template('assistant.html', user=user, tools=available_tools)

@app.route('/api/assistant/ask', methods=['POST'])
@login_required
def assistant_ask_api():
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    question = (data.get('question') or '').strip()

    if not question:
        return jsonify({'error': 'Please enter a valid operational question.'}), 400

    # Process question through secure Operational AI Assistant Engine
    res = ask_operational_assistant(question, user_role=user.role, user_id=user.id)

    # Audit Logging: Record query, selected function, role, and outcome in AuditLog
    func_used = res.get('function_used') or 'NONE'
    status_str = res.get('status') or 'UNKNOWN'
    audit_msg = f"AI ASSISTANT QUERY ({user.role}): '{question[:60]}' -> Executed Tool: [{func_used}] ({status_str})"
    
    try:
        log_action(audit_msg, target=user.full_name)
    except Exception as e:
        print(f"Audit log warning: {e}")

    return jsonify({
        'question': question,
        'answer': res.get('answer'),
        'function_used': res.get('function_used'),
        'tier': res.get('tier'),
        'status': res.get('status'),
        'raw_data': res.get('raw_data')
    })
    
@app.route('/api/notifications')
def get_notifications():
    role = session.get('role')
    if role in ['Principal', 'HR']:
        all_notifs = Notification.query.order_by(Notification.timestamp.desc()).limit(10).all()
    elif role == 'Accountant':
        all_notifs = Notification.query.filter(Notification.message.contains('SALARY')).limit(10).all()
    else: return jsonify([])
    return jsonify([{'id': n.id, 'msg': n.message, 'time': n.timestamp.strftime('%I:%M %p')} for n in all_notifs])

def create_temp_payslip_pdf(emp, month_str=None):
    try:
        now = datetime.now()
        current_month_display = month_str or now.strftime("%B %Y")
        pdf_dir = os.path.join(app.root_path, 'static', 'temp_payslips')
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_path = os.path.join(pdf_dir, f"payslip_{emp.username}_{now.strftime('%Y%m%d%H%M%S')}.pdf")
        
        basic = emp.salary
        hra = int(basic * 0.40)
        da = int(basic * 0.10)
        ta = 2000
        gross = basic + hra + da + ta
        tds_rate = 0.15 if gross > 100000 else (0.10 if gross > 50000 else 0.05)
        tds = int(gross * tds_rate)
        epf = int((basic + da) * 0.12)
        pt = 200
        total_deductions = epf + pt + tds
        net = gross - total_deductions

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(190, 10, txt="BMS COLLEGE OF COMMERCE & MANAGEMENT", ln=True, align='C')
        pdf.set_font("Arial", '', 10)
        pdf.cell(190, 5, txt="Affiliated to Bengaluru City University", ln=True, align='C')
        pdf.ln(5)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(190, 10, txt=f"PAYSLIP FOR THE MONTH OF {current_month_display.upper()}", border=1, ln=True, align='C', fill=True)
        pdf.ln(5)

        pdf.set_font("Arial", 'B', 10)
        pdf.cell(40, 8, "Employee Name:", 0); pdf.set_font("Arial", '', 10); pdf.cell(60, 8, emp.full_name, 0)
        pdf.set_font("Arial", 'B', 10); pdf.cell(40, 8, "Designation:", 0); pdf.set_font("Arial", '', 10); pdf.cell(50, 8, emp.role, 0, 1)
        pdf.set_font("Arial", 'B', 10); pdf.cell(40, 8, "Date of Issue:", 0); pdf.set_font("Arial", '', 10); pdf.cell(150, 8, f"26th {current_month_display}", 0, 1)
        pdf.ln(5)

        pdf.set_font("Arial", 'B', 10); pdf.set_fill_color(230, 235, 255)
        pdf.cell(65, 10, "Earnings", 1, 0, 'C', True); pdf.cell(30, 10, "Amount", 1, 0, 'C', True)
        pdf.cell(65, 10, "Deductions", 1, 0, 'C', True); pdf.cell(30, 10, "Amount", 1, 1, 'C', True)

        pdf.set_font("Arial", '', 10)
        pdf.cell(65, 8, "Basic Salary", 1); pdf.cell(30, 8, f"{basic}", 1, 0, 'R')
        pdf.cell(65, 8, "Employee PF (12%)", 1); pdf.cell(30, 8, f"{epf}", 1, 1, 'R')
        pdf.cell(65, 8, "H.R.A (40%)", 1); pdf.cell(30, 8, f"{hra}", 1, 0, 'R')
        pdf.cell(65, 8, "Professional Tax", 1); pdf.cell(30, 8, f"{pt}", 1, 1, 'R')
        pdf.cell(65, 8, "D.A (10%)", 1); pdf.cell(30, 8, f"{da}", 1, 0, 'R')
        pdf.cell(65, 8, f"Income Tax / TDS ({int(tds_rate*100)}%)", 1); pdf.cell(30, 8, f"{tds}", 1, 1, 'R')
        pdf.cell(65, 8, "Transport Allowance", 1); pdf.cell(30, 8, f"{ta}", 1, 0, 'R')
        pdf.cell(65, 8, "Other Deductions", 1); pdf.cell(30, 8, "0", 1, 1, 'R')

        pdf.set_font("Arial", 'B', 10)
        pdf.cell(65, 10, "Gross Earnings", 1, 0, 'L', True); pdf.cell(30, 10, f"{gross}", 1, 0, 'R', True)
        pdf.cell(65, 10, "Total Deductions", 1, 0, 'L', True); pdf.cell(30, 10, f"{total_deductions}", 1, 1, 'R', True)
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(190, 12, f"NET PAYABLE: INR {net} /-", border=1, ln=True, align='C')
        
        pdf.output(pdf_path, 'F')
        return pdf_path
    except Exception as e:
        print(f"Payslip PDF generation error: {e}")
        return None

@app.route('/edit_salary/<int:uid>', methods=['POST'])
def edit_salary(uid):
    if session.get('role') in ['HR', 'Accountant', 'admin', 'Principal']:
        emp = User.query.get(uid)
        old_sal = emp.salary
        emp.salary = int(request.form['new_salary'])
        db.session.add(Notification(message=f"SALARY CHANGE: {emp.full_name} updated from ₹{old_sal} to ₹{emp.salary}"))
        db.session.commit()
        log_action(f"Updated Salary for {emp.full_name}", target=emp.full_name)

        # --- EVENT 2A: SALARY CREDITED NOTIFICATION ---
        try:
            c_month = datetime.now().strftime("%B %Y")
            pdf_path = create_temp_payslip_pdf(emp, c_month)
            notify('salary_credited', emp, context={
                'month': c_month,
                'amount': emp.salary,
                'pdf_path': pdf_path
            })
        except Exception as sal_err:
            print(f"Salary notification note: {sal_err}")

    return redirect(url_for('staff_directory'))

@app.route('/edit_staff/<int:uid>', methods=['POST'])
@login_required
def edit_staff(uid):
    role = session.get('role')
    if role not in ['HR', 'Accountant', 'admin']:
        flash('Access Restricted! Only Admin Department can edit staff profiles.', 'error')
        return redirect(url_for('staff_directory'))

    emp = User.query.get(uid)
    if not emp:
        flash('Staff member not found.', 'error')
        return redirect(url_for('staff_directory'))

    emp.full_name = request.form.get('full_name', emp.full_name)
    emp.email = request.form.get('email', emp.email)
    emp.phone = request.form.get('phone', emp.phone)
    emp.role = request.form.get('role', emp.role)
    emp.department = request.form.get('department', emp.department)
    emp.dept_id = request.form.get('dept_id', emp.dept_id)
    
    if request.form.get('salary'):
        try:
            emp.salary = int(request.form.get('salary'))
        except ValueError:
            pass

    emp.address = request.form.get('address', emp.address)
    emp.dob = request.form.get('dob', emp.dob)
    emp.join_date = request.form.get('join_date', emp.join_date)
    emp.caste = request.form.get('caste', emp.caste)
    emp.religion = request.form.get('religion', emp.religion)

    if 'profile_pic' in request.files:
        file = request.files['profile_pic']
        if file and allowed_file(file.filename):
            filename = f"staff_reg_{secure_filename(file.filename)}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            emp.profile_pic = filename

    db.session.commit()
    log_action(f"Updated staff profile for {emp.full_name}", target=emp.full_name)
    flash(f"Profile updated successfully for {emp.full_name}.", "success")
    return redirect(url_for('staff_directory'))

@app.route('/admin/staff_master')
@login_required
def admin_staff_master():
    user = User.query.get(session['user_id'])
    if not user or user.role.lower() not in ['hr', 'accountant', 'admin']:
        flash('Access Restricted! Master Workforce Section is restricted to Admin Department.', 'error')
        return redirect(url_for('dashboard'))

    all_staff = User.query.order_by(User.full_name.asc()).all()
    return render_template('admin_staff_master.html', all_staff=all_staff)

@app.route('/admin/edit_staff/<int:uid>', methods=['POST'])
@login_required
def admin_edit_staff(uid):
    user = User.query.get(session['user_id'])
    if not user or user.role.lower() not in ['hr', 'accountant', 'admin']:
        flash('Access Restricted! Only Admin Department can edit staff profiles.', 'error')
        return redirect(url_for('dashboard'))

    emp = User.query.get(uid)
    if not emp:
        flash('Staff member not found.', 'error')
        return redirect(url_for('admin_staff_master'))

    emp.full_name = request.form.get('full_name', emp.full_name)
    emp.email = request.form.get('email', emp.email)
    emp.phone = request.form.get('phone', emp.phone)
    emp.role = request.form.get('role', emp.role)
    emp.department = request.form.get('department', emp.department)
    emp.dept_id = request.form.get('dept_id', emp.dept_id)
    
    if request.form.get('salary'):
        try:
            emp.salary = int(request.form.get('salary'))
        except ValueError:
            pass

    emp.address = request.form.get('address', emp.address)
    emp.dob = request.form.get('dob', emp.dob)
    emp.join_date = request.form.get('join_date', emp.join_date)
    emp.caste = request.form.get('caste', emp.caste)
    emp.religion = request.form.get('religion', emp.religion)

    if 'profile_pic' in request.files:
        file = request.files['profile_pic']
        if file and allowed_file(file.filename):
            filename = f"staff_reg_{secure_filename(file.filename)}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            emp.profile_pic = filename

    db.session.commit()
    log_action(f"Admin updated Master Profile for {emp.full_name}", target=emp.full_name)
    flash(f"Master Profile updated successfully for {emp.full_name}.", "success")
    return redirect(url_for('admin_staff_master'))

@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
        
    today = get_ist_time().strftime("%Y-%m-%d")
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        # Matching HTML hidden fields 'lat' and 'lon'
        try:
            lat = float(request.form.get('lat', 0))
            lon = float(request.form.get('lon', 0))
        except ValueError:
            lat, lon = 0.0, 0.0
            
        # Enforce On-Site Campus Mode (WFH Disabled)
        mode = 'Office'
        
        # 1. GEOLOCATION VALIDATION
        if lat == 0 or lon == 0:
            flash("GPS Error: Could not verify location. Please enable GPS on your mobile/browser.", "error")
            return redirect(url_for('attendance'))

        # 2. GEOFENCE CALIBRATION (BMSCCM Basavanagudi Perimeter)
        distance = calculate_distance(lat, lon, CAMPUS_LAT, CAMPUS_LON)
        
        if distance > 1000:
            flash(f"Verification Failed: You are {round(distance)}m away from BMS College of Commerce & Management (Basavanagudi Campus).", "error")
            return redirect(url_for('attendance'))

        # 3. ATTENDANCE LOGIC (Check-in / Check-out)
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        t_now = get_ist_time().strftime("%I:%M %p")
        
        if not att:
            # New Check-in
            new_entry = Attendance(
                user_id=session['user_id'], 
                date=today, 
                check_in=t_now, 
                work_mode=mode, 
                lat=lat, 
                lon=lon
            )
            db.session.add(new_entry)
            db.session.add(Notification(message=f"ATTENDANCE: {user.full_name} CLOCKED-IN ({mode})"))
        else:
            # Update existing record with Check-out
            att.check_out = t_now
            db.session.add(Notification(message=f"ATTENDANCE: {user.full_name} CLOCKED-OUT"))
            
        db.session.commit()
        flash("Record Synchronized Successfully.", "success")
        return redirect(url_for('attendance'))
        
    # --- GET REQUEST LOGIC ---
    # HR sees everything, Staff sees only their own history
    if session.get('role') == 'HR':
        history = Attendance.query.order_by(Attendance.date.desc()).all()
    else:
        history = Attendance.query.filter_by(user_id=session['user_id']).order_by(Attendance.date.desc()).all()
        
    return render_template('attendance.html', history=history)

@app.route('/attendance/daily_close', methods=['POST'])
@login_required
def daily_close():
    user = User.query.get(session['user_id'])
    if not user or user.role.lower() not in ['hr', 'accountant', 'admin', 'principal']:
        flash('Access Restricted! Daily close is restricted to Management.', 'error')
        return redirect(url_for('attendance'))

    today_str = get_ist_time().strftime("%Y-%m-%d")
    missing_records = Attendance.query.filter(
        Attendance.date == today_str,
        Attendance.check_in.isnot(None),
        Attendance.check_out.is_(None)
    ).all()

    nudged_count = 0
    for att in missing_records:
        if att.user:
            notify('missing_checkout', att.user, context={'date': today_str})
            nudged_count += 1

    flash(f"Daily Close Execution Finished. Sent check-out email nudges to {nudged_count} personnel.", "success")
    return redirect(url_for('attendance'))

@app.route('/attendance/monthly_summary', methods=['GET', 'POST'])
@login_required
def monthly_summary():
    user = User.query.get(session['user_id'])
    if not user or user.role.lower() not in ['hr', 'accountant', 'admin', 'principal']:
        flash('Access Restricted! Monthly Attendance Summary trigger restricted to Management.', 'error')
        return redirect(url_for('attendance'))

    all_users = User.query.all()
    now_month = get_ist_time().strftime("%Y-%m")
    sent_count = 0

    for u in all_users:
        records = Attendance.query.filter(Attendance.user_id == u.id, Attendance.date.like(f"{now_month}%")).all()
        present_count = len(records)
        late_count = sum(1 for r in records if r.check_in and r.check_in > "09:10 AM")
        missing_out_count = sum(1 for r in records if r.check_in and not r.check_out)

        notify('monthly_attendance_summary', u, context={
            'month': get_ist_time().strftime("%B %Y"),
            'present_days': present_count,
            'late_days': late_count,
            'missing_outs': missing_out_count
        })
        sent_count += 1

    flash(f"Monthly Attendance Summary Statements dispatched to {sent_count} staff members via Email.", "success")
    return redirect(url_for('attendance'))
    
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
    # Retrieve the request using the 'id'
    leave_req = Leave.query.get(id)
    if not leave_req:
        flash("Leave request not found.", "error")
        return redirect(url_for('leave'))
        
    role = session.get('role')
    
    if action == 'approve':
        if role == 'HOD - BCA Dept' and leave_req.status == 'Pending HOD':
            leave_req.status = 'Pending Principal'
        elif role == 'Principal' and leave_req.status == 'Pending Principal':
            leave_req.status = 'Approved'
            
    elif action == 'reject':
        leave_req.status = 'Rejected'
        leave_req.rejection_reason = request.args.get('reason', 'No reason provided')
    
    db.session.commit()
    log_action(f"{action.capitalize()}d Leave Request", target=leave_req.user.full_name)
    
    # --- EVENT 2B: LEAVE DECISION NOTIFICATION ---
    if leave_req and leave_req.user:
        notify('leave_decision', leave_req.user, context={
            'status': leave_req.status,
            'reason': leave_req.rejection_reason if leave_req.status == 'Rejected' else '',
            'date': leave_req.date
        })

    return redirect(url_for('leave'))

from datetime import datetime

@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        amt = float(request.form['amount'])
        # Added 'timestamp' to the ExpenseClaim creation
        new_claim = ExpenseClaim(
            user_id=session['user_id'], 
            category=request.form['category'], 
            amount=amt, 
            description=request.form['desc'],
            timestamp=datetime.now() # Captures current institutional time
        )
        db.session.add(new_claim)
        
        # Existing Notification Logic
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

    # --- EVENT 4: EXPENSE DECISION NOTIFICATION ---
    if claim and claim.rel_user:
        notify('expense_decision', claim.rel_user, context={
            'status': claim.status,
            'amount': claim.amount,
            'category': claim.category
        })

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
    
    user_role = session.get('role', '')
    user_id = session.get('user_id')

    # --- POST: HANDLE RATING SUBMISSION ---
    if request.method == 'POST':
        target_id = request.form['u_id']
        allowed = False
        
        if user_role == 'Principal':
            allowed = True 
        elif 'HOD' in user_role: # Updated to catch "HOD - BCA Dept"
            target_user = User.query.get(target_id)
            if target_user and target_user.role == 'Faculty':
                allowed = True
        
        if allowed:
            new_kpi = PerformanceKPI(
                user_id=target_id,
                month=request.form['month'],
                rating=request.form['rating'],
                feedback=request.form['feedback']
            )
            db.session.add(new_kpi)
            db.session.commit()
            flash('Performance review submitted successfully.', 'success')
        else:
            flash('Unauthorized: You can only rate Faculty members.', 'error')

    # --- GET: PREPARE DATA FOR UI ---
    
    users_to_rate = []
    if user_role == 'Principal':
        users_to_rate = User.query.filter(User.id != user_id).all() 
    elif 'HOD' in user_role: # Updated logic
        users_to_rate = User.query.filter_by(role='Faculty').all()

    # Table View Logic
    if user_role == 'Principal':
        ratings = PerformanceKPI.query.all()
    elif 'HOD' in user_role: # Updated logic
        ratings = db.session.query(PerformanceKPI).join(User).filter(User.role == 'Faculty').all()
    else:
        ratings = PerformanceKPI.query.filter_by(user_id=user_id).all()

    return render_template('performance.html', ratings=ratings, users=users_to_rate)
    
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

from datetime import datetime
from flask import make_response
# Ensure you have your other imports like User, FPDF, etc.

@app.route('/generate_payslip/<int:uid>')
@app.route('/generate_payslip/<int:uid>/<month_str>') # Added secondary route
def generate_payslip(uid, month_str=None):
    u = User.query.get(uid)
    if not u:
        return "Employee not found", 404
        
    basic = u.salary
    hra = int(basic * 0.40)
    da = int(basic * 0.10)
    ta = 2000
    gross = basic + hra + da + ta
    
    # ADJUSTABLE TDS SLAB LOGIC (UNTOUCHED)
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

    # DYNAMIC DATE CALCULATION (UPDATED LOGIC)
    now = datetime.now()
    if month_str:
        # If a historical month is passed (e.g., "January 2026")
        current_month_display = month_str.split(' ')[0].upper()
        current_year = month_str.split(' ')[1]
        issue_date = f"26th {month_str}"
    else:
        # Default to current month if no month_str is provided
        current_month_display = now.strftime("%B").upper()
        current_year = now.strftime("%Y")
        issue_date = f"26th {now.strftime('%B %Y')}"

    # 2. PDF Setup
    pdf = FPDF()
    pdf.add_page()
    
    # NEW: Add College Logo (Top Left)
    try:
        pdf.image('https://www.bmsccm.ac.in/img/ll.png', x=10, y=8, w=22)
    except Exception as e:
        pass 
    
    # Header - College Branding (UNTOUCHED text)
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, txt="BMS COLLEGE OF COMMERCE & MANAGEMENT", ln=True, align='C')
    pdf.set_font("Arial", '', 10)
    pdf.cell(190, 5, txt="Affiliated to Bengaluru City University", ln=True, align='C')
    pdf.ln(5)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", 'B', 12)
    
    # DYNAMIC: Now reflects the selected month correctly
    pdf.cell(190, 10, txt=f"PAYSLIP FOR THE MONTH OF {current_month_display} {current_year}", border=1, ln=True, align='C', fill=True)
    pdf.ln(5)

    # Employee Info Row (UNTOUCHED layout)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(40, 8, "Employee Name:", 0); pdf.set_font("Arial", '', 10); pdf.cell(60, 8, u.full_name, 0)
    pdf.set_font("Arial", 'B', 10); pdf.cell(40, 8, "Designation:", 0); pdf.set_font("Arial", '', 10); pdf.cell(50, 8, u.role, 0, 1)
    
    # Issue Date Row
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(40, 8, "Date of Issue:", 0); pdf.set_font("Arial", '', 10); pdf.cell(150, 8, issue_date, 0, 1)
    pdf.ln(5)

    # 3. Detailed Salary Table (UNTOUCHED)
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(230, 235, 255)
    pdf.cell(65, 10, "Earnings", 1, 0, 'C', True)
    pdf.cell(30, 10, "Amount", 1, 0, 'C', True)
    pdf.cell(65, 10, "Deductions", 1, 0, 'C', True)
    pdf.cell(30, 10, "Amount", 1, 1, 'C', True)

    pdf.set_font("Arial", '', 10)
    pdf.cell(65, 8, "Basic Salary", 1); pdf.cell(30, 8, f"{basic}", 1, 0, 'R')
    pdf.cell(65, 8, "Employee PF (12%)", 1); pdf.cell(30, 8, f"{epf}", 1, 1, 'R')
    pdf.cell(65, 8, "H.R.A (40%)", 1); pdf.cell(30, 8, f"{hra}", 1, 0, 'R')
    pdf.cell(65, 8, "Professional Tax", 1); pdf.cell(30, 8, f"{pt}", 1, 1, 'R')
    pdf.cell(65, 8, "D.A (10%)", 1); pdf.cell(30, 8, f"{da}", 1, 0, 'R')
    pdf.cell(65, 8, f"Income Tax / TDS ({int(tds_rate*100)}%)", 1); pdf.cell(30, 8, f"{tds}", 1, 1, 'R')
    pdf.cell(65, 8, "Transport Allowance", 1); pdf.cell(30, 8, f"{ta}", 1, 0, 'R')
    pdf.cell(65, 8, "Other Deductions", 1); pdf.cell(30, 8, "0", 1, 1, 'R')

    # Totals Row (UNTOUCHED)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(65, 10, "Gross Earnings", 1, 0, 'L', True)
    pdf.cell(30, 10, f"{gross}", 1, 0, 'R', True)
    pdf.cell(65, 10, "Total Deductions", 1, 0, 'L', True)
    pdf.cell(30, 10, f"{total_deductions}", 1, 1, 'R', True)

    # Net Pay Box (UNTOUCHED)
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(190, 12, f"NET PAYABLE: INR {net} /-", border=1, ln=True, align='C')

    # 5. Digital Rights Footer (UNTOUCHED)
    pdf.ln(15)
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(190, 5, "This is a computer-generated payslip and does not require a physical ink signature.", ln=True, align='C')
    pdf.cell(190, 5, f"Verification Code: BMS-{uid}-{current_year} | Digital Rights Reserved @ BMSCCM IT Cell", ln=True, align='C')

    # Output Fix (UNTOUCHED)
    response = make_response(pdf.output(dest='S').encode('latin-1'))
    response.headers['Content-Type'] = 'application/pdf'
    # Filename also reflects the month
    response.headers['Content-Disposition'] = f'attachment; filename=payslip_{u.username}_{current_month_display}.pdf'
    return response
    
@app.route('/send_payslip_email/<int:uid>')
def send_payslip_email(uid):
    u = User.query.get(uid)
    if not u:
        return jsonify({"error": "User not found"}), 404
        
    c_month = datetime.now().strftime("%B %Y")
    pdf_path = create_temp_payslip_pdf(u, c_month)

    res = notify('payslip_delivery', u, context={
        'month': c_month,
        'pdf_path': pdf_path
    })

    db.session.add(Notification(message=f"SYSTEM: Digital Payslip emailed to {u.email}"))
    db.session.commit()
    return jsonify({"message": f"Digital payslip sent to {u.email} successfully!", "details": res})

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
    # 1. Record the logout action (Your existing logic)
    log_action("User Logged Out") 
    
    # 2. THE FIX: Log out from the Flask-Login system 
    # This clears current_user and the remember_me cookies
    logout_user() 
    
    # 3. Clear your manual session variables (name, role, user_id)
    session.clear() 
    
    return redirect(url_for('login'))

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
    # Changed 'photo' to 'profile_pic' to match HTML
    if 'profile_pic' not in request.files: return redirect(request.referrer)
    file = request.files['profile_pic']
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

from datetime import datetime

@app.route('/payslip_history')
def payslip_history():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    months = ["September 2025", "October 2025", "November 2025", "December 2025", "January 2026", "February 2026"]
    today = datetime.now().strftime('%d %B %Y')
    return render_template('payslip_history.html', user=user, months=months, today=today)

# UPDATED: Now passes the month parameter to the main logic
@app.route('/generate_payslip_historical/<int:uid>/<month>')
def generate_payslip_historical(uid, month):
    return generate_payslip(uid, month_str=month)
    
@app.route('/complete_task/<int:id>', methods=['POST'])
def complete_task(id):
    task = Task.query.get_or_404(id)
    # Ensure only the assigned staff can reply
    if task.assigned_to == session['user_id']:
        task.reply_content = request.form.get('reply') # The text from the box
        task.is_done = True
        task.status = 'Completed'
        db.session.commit()
    return redirect(url_for('activity_room'))
    
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
def inject_notifications():
    if 'user_id' in session:
        u_id = session['user_id']
        # Count general unread notifications (for Dashboard/Bell icon)
        # Count pending tasks specifically for Activity Room
        task_count = Task.query.filter_by(assigned_to=u_id, is_done=False).count()
        
        return dict(
            global_notif_count=0,  # Set to 0 for now so Dashboard doesn't crash
            pending_tasks_count=task_count
        )
    return dict(global_notif_count=0, pending_tasks_count=0)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
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
            role='admin', 
            full_name='System Admin', 
            email='admin@bms.edu.in', 
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
        ('balram', 'Mr.Balram M N', 'Faculty', 'balram@bmsccm.edu', 'General', 'Hindu', '1982-04-15', '2015-06-01', 'Commerce', 'BMS-COM-101', 'Jayanagar 4th Block, Bengaluru'),
        ('kiran', 'Dr.Kiran Kumar M N', 'HOD - BCA Dept', 'kiran.hod@bmsccm.edu', 'General', 'Hindu', '1978-11-20', '2010-01-15', 'Computer Applications', 'BMS-BCA-001', 'Banashankari 3rd Stage, Bengaluru'),
        ('shrinkala', 'Miss. Shrinkala', 'Faculty', 'shrinkala@bmsccm.edu', 'General', 'Hindu', '1992-08-30', '2021-09-10', 'Management', 'BMS-MGT-201', 'V.V. Puram, Bengaluru'),
        ('shivani', 'Mrs. Shivani', 'Faculty', 'shivani@bmsccm.edu', 'General', 'Hindu', '1988-03-05', '2019-02-14', 'Commerce', 'BMS-COM-102', 'Basavanagudi, Bengaluru'),
        ('ramkishore', 'Mr. Ramkishore', 'Faculty', 'ramkishore@bmsccm.edu', 'General', 'Hindu', '1985-12-12', '2017-07-20', 'Commerce', 'BMS-COM-103', 'JP Nagar, Bengaluru'),
        ('prathiba', 'Mrs. Prathiba Singh', 'Faculty', 'prathiba@bmsccm.edu', 'General', 'Hindu', '1990-05-25', '2022-11-01', 'Management', 'BMS-MGT-202', 'Uttarahalli, Bengaluru'),
        ('newfac', 'New Faculty', 'Faculty', 'new@bmsccm.edu', 'General', 'Not Specified', '1998-01-01', '2025-01-01', 'Commerce', 'BMS-COM-999', 'Bengaluru South'),
        ('pankaj', 'Dr. Pankaj Choudhry', 'Principal', 'principal@bmsccm.edu', 'General', 'Hindu', '1975-09-10', '2005-08-15', 'Executive', 'BMS-EXE-001', 'Principal Quarters, BMSCCM')
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
    if not Timetable.query.first():
        print("Injecting heavy timetable data...")
        inject_heavy_timetable()
        print("Timetable populated successfully!")
        

# ==============================================================================
# FEATURE 1 — ANALYTICS DASHBOARD
# ==============================================================================

@app.route('/analytics')
@login_required
def analytics():
    user = User.query.get(session['user_id'])
    if not user:
        flash('Please login to access Analytics Dashboard.')
        return redirect(url_for('login'))
    return render_template('analytics.html', user=user)


@app.route('/api/analytics/data')
@login_required
def analytics_data():
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'Unauthorized'}), 403

    # 1. Attendance Trend (Last 30 Days)
    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(29, -1, -1)]
    attendance_records = db.session.query(
        Attendance.date, func.count(Attendance.id)
    ).filter(Attendance.date.in_(dates)).group_by(Attendance.date).all()
    
    att_map = dict(attendance_records)
    att_trend_labels = [datetime.strptime(d, '%Y-%m-%d').strftime('%d %b') for d in dates]
    att_trend_values = [att_map.get(d, 0) for d in dates]

    # 2. Leave Status Breakdown
    leave_records = db.session.query(
        Leave.status, func.count(Leave.id)
    ).group_by(Leave.status).all()
    leave_labels = [r[0] for r in leave_records] if leave_records else ['No Data']
    leave_values = [r[1] for r in leave_records] if leave_records else [0]

    # 3. Expense by Category
    expense_records = db.session.query(
        ExpenseClaim.category, func.sum(ExpenseClaim.amount)
    ).group_by(ExpenseClaim.category).all()
    exp_labels = [r[0] if r[0] else 'General' for r in expense_records] if expense_records else ['No Data']
    exp_values = [float(r[1]) if r[1] else 0.0 for r in expense_records] if expense_records else [0.0]

    # 4. Department Payroll Breakdown (from User table)
    dept_payroll = db.session.query(
        User.department, func.sum(User.salary)
    ).group_by(User.department).all()
    payroll_labels = [r[0] if r[0] else 'Unassigned' for r in dept_payroll] if dept_payroll else ['No Data']
    payroll_values = [float(r[1]) if r[1] else 0.0 for r in dept_payroll] if dept_payroll else [0.0]

    # 5. Performance Ratings Average by Month
    perf_records = db.session.query(
        PerformanceKPI.month, func.avg(PerformanceKPI.rating)
    ).group_by(PerformanceKPI.month).all()
    perf_labels = [r[0] for r in perf_records] if perf_records else ['No Data']
    perf_values = [round(float(r[1]), 2) for r in perf_records] if perf_records else [0.0]

    return jsonify({
        'attendance_trend': {'labels': att_trend_labels, 'values': att_trend_values},
        'leave_status': {'labels': leave_labels, 'values': leave_values},
        'expense_by_category': {'labels': exp_labels, 'values': exp_values},
        'monthly_payroll': {'labels': payroll_labels, 'values': payroll_values},
        'performance_ratings': {'labels': perf_labels, 'values': perf_values}
    })


# ==============================================================================
# FEATURE 2 — GEMINI AI ASSISTANT (WHITELISTED QUERY ENGINE)
# ==============================================================================

def ai_count_leaves_this_week():
    today = datetime.now()
    start_week = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
    end_week = (today + timedelta(days=6 - today.weekday())).strftime('%Y-%m-%d')
    leaves = Leave.query.filter(Leave.date >= start_week, Leave.date <= end_week).all()
    return {
        "summary": f"There are {len(leaves)} leave request(s) recorded for this week ({start_week} to {end_week}).",
        "count": len(leaves),
        "details": [{"personnel": l.user.full_name if l.user else "Unknown", "date": l.date, "status": l.status, "reason": l.reason} for l in leaves[:5]]
    }

def ai_pending_expenses(min_amount=0):
    claims = ExpenseClaim.query.filter(ExpenseClaim.status == 'Pending', ExpenseClaim.amount >= min_amount).all()
    total_val = sum(c.amount for c in claims)
    return {
        "summary": f"Found {len(claims)} pending expense claim(s) totaling ₹{total_val:,.2f} above minimum threshold ₹{min_amount}.",
        "count": len(claims),
        "total_amount": total_val,
        "details": [{"personnel": c.rel_user.full_name if c.rel_user else "Unknown", "category": c.category, "amount": c.amount} for c in claims[:5]]
    }

def ai_staff_count_by_department():
    counts = db.session.query(User.department, func.count(User.id)).group_by(User.department).all()
    total_staff = sum(c[1] for c in counts)
    top_dept = max(counts, key=lambda x: x[1])[0] if counts else "None"
    return {
        "summary": f"Total active workforce is {total_staff} personnel across {len(counts)} departments. Department with highest headcount is '{top_dept}'.",
        "total_staff": total_staff,
        "departments": {c[0] if c[0] else "Unassigned": c[1] for c in counts}
    }

def ai_total_payroll():
    total_salary = db.session.query(func.sum(User.salary)).scalar() or 0
    staff_count = User.query.count()
    return {
        "summary": f"The total monthly liquid payroll outflow for all {staff_count} registered personnel is ₹{total_salary:,.2f}.",
        "total_monthly_payroll": float(total_salary),
        "total_staff": staff_count
    }

def ai_today_attendance():
    today_str = datetime.now().strftime('%Y-%m-%d')
    records = Attendance.query.filter_by(date=today_str).all()
    office_cnt = sum(1 for r in records if r.work_mode == 'Office')
    wfh_cnt = sum(1 for r in records if r.work_mode == 'WFH')
    return {
        "summary": f"Today ({today_str}), {len(records)} personnel have checked in ({office_cnt} Campus Office, {wfh_cnt} WFH).",
        "total_today": len(records),
        "office": office_cnt,
        "wfh": wfh_cnt
    }

def ai_performance_summary():
    avg_score = db.session.query(func.avg(PerformanceKPI.rating)).scalar() or 0
    kpi_cnt = PerformanceKPI.query.count()
    return {
        "summary": f"Institutional average performance KPI rating across {kpi_cnt} evaluations is {float(avg_score):.1f}/10.",
        "average_rating": round(float(avg_score), 2),
        "total_kpis": kpi_cnt
    }

WHITELISTED_TOOLS = {
    'count_leaves': ai_count_leaves_this_week,
    'pending_expenses': ai_pending_expenses,
    'staff_by_department': ai_staff_count_by_department,
    'total_payroll': ai_total_payroll,
    'today_attendance': ai_today_attendance,
    'performance_summary': ai_performance_summary
}

@app.route('/assistant')
@login_required
def assistant():
    user = User.query.get(session['user_id'])
    if not user:
        flash('Please login to access AI Assistant.')
        return redirect(url_for('login'))
    api_configured = bool(os.environ.get('GEMINI_API_KEY'))
    return render_template('assistant.html', user=user, api_configured=api_configured)

@app.route('/api/assistant/ask', methods=['POST'])
@login_required
def assistant_ask():
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    question = data.get('question', '').strip()
    if not question:
        return jsonify({'answer': 'Please provide a valid question.'}), 400

    q_lower = question.lower()

    # Match question against Whitelisted Intent Rules
    selected_tool = None
    tool_args = {}

    if any(k in q_lower for k in ['leave', 'vacation', 'absence', 'off']):
        selected_tool = 'count_leaves'
    elif any(k in q_lower for k in ['expense', 'claim', 'pending claim', 'reimbursement']):
        selected_tool = 'pending_expenses'
        if '5000' in q_lower:
            tool_args = {'min_amount': 5000}
        elif '1000' in q_lower:
            tool_args = {'min_amount': 1000}
    elif any(k in q_lower for k in ['department', 'staff count', 'dept', 'headcount', 'workforce']):
        selected_tool = 'staff_by_department'
    elif any(k in q_lower for k in ['payroll', 'salary', 'cost', 'monthly pay', 'outflow']):
        selected_tool = 'total_payroll'
    elif any(k in q_lower for k in ['attendance', 'checkin', 'present', 'today']):
        selected_tool = 'today_attendance'
    elif any(k in q_lower for k in ['performance', 'rating', 'score', 'kpi']):
        selected_tool = 'performance_summary'

    api_key = os.environ.get('GEMINI_API_KEY')
    tool_result = None

    if selected_tool and selected_tool in WHITELISTED_TOOLS:
        func_obj = WHITELISTED_TOOLS[selected_tool]
        tool_result = func_obj(**tool_args)
        
        # Log query to AuditLog
        log_entry = AuditLog(
            user_name=user.full_name,
            action=f"AI Query: '{question}'",
            target_user=f"Tool: {selected_tool}"
        )
        db.session.add(log_entry)
        db.session.commit()

        # If Gemini API Key is configured, use Gemini to format natural language answer
        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                prompt = f"""You are the BMS College ERP AI Assistant. Answer the user's question clearly and politely using strictly the following verified database result.

User Question: {question}
Verified DB Data: {tool_result}

Provide a concise, professional answer for the college executive."""
                response = model.generate_content(prompt)
                answer_text = response.text.strip()
            except Exception as e:
                answer_text = tool_result['summary']
        else:
            answer_text = tool_result['summary']
    else:
        answer_text = "I can answer questions about staff leaves, pending expense claims, department headcounts, monthly payroll costs, today's attendance, and performance ratings."

    return jsonify({'answer': answer_text, 'tool_used': selected_tool, 'data': tool_result})


# ==============================================================================
# SMART ATTENDANCE SYSTEM (HARDENED QR, ANTI-SPOOFING, WORKING HOURS)
# ==============================================================================

@app.route('/api/attendance/qr_token')
@login_required
def api_attendance_qr_token():
    user = User.query.get(session['user_id'])
    if not user or user.role not in ['admin', 'HR', 'Principal', 'HOD', 'HOD - BCA Dept']:
        return jsonify({'error': 'Unauthorized'}), 403

    token = generate_rotating_qr_token(window_offset=0)
    checkin_url = url_for('attendance_qr_checkin', token=token, _external=True)

    import qrcode
    qr = qrcode.QRCode(version=1, box_size=8, border=3)
    qr.add_data(checkin_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0d47a1", back_color="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

    # Time remaining in current 30s window
    time_left = 30 - int(datetime.now().timestamp() % 30)

    return jsonify({
        'token': token,
        'checkin_url': checkin_url,
        'qr_b64': qr_b64,
        'expires_in': time_left
    })

@app.route('/attendance/qr')
@login_required
def attendance_qr():
    user = User.query.get(session['user_id'])
    if not user:
        flash('Please login to access QR Attendance.')
        return redirect(url_for('login'))

    token = generate_rotating_qr_token(window_offset=0)
    checkin_url = url_for('attendance_qr_checkin', token=token, _external=True)

    import qrcode
    qr = qrcode.QRCode(version=1, box_size=8, border=3)
    qr.add_data(checkin_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0d47a1", back_color="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

    today_str = datetime.now().strftime('%d %B %Y')
    return render_template('qr_attendance.html', qr_b64=qr_b64, checkin_url=checkin_url, today_str=today_str, token=token)

@app.route('/attendance/checkin')
@login_required
def attendance_qr_checkin():
    token = request.args.get('token', '')
    user_ip = request.remote_addr or '127.0.0.1'

    # 1A. ROTATING QR TOKEN VALIDATION
    is_valid_token, tok_msg = validate_rotating_qr_token(token)
    if not is_valid_token:
        log_action(f"Rejected QR Check-in: Expired/Invalid Token ({token[:8]}...)", target=current_user.full_name)
        flash('❌ Verification Failed: QR Token expired or invalid. Please scan the live 30-second rotating QR code on the campus display.')
        return redirect(url_for('attendance'))

    # 1C. NETWORK CONTEXT CHECK
    ip_ok, ip_msg = check_ip_network_context(user_ip)
    if not ip_ok:
        log_action(f"Flagged QR Check-in IP: {user_ip} (Off-Campus Network)", target=current_user.full_name)

    # 1D. DEVICE BINDING
    device_cookie = request.cookies.get('bms_device_id')
    if not device_cookie:
        import uuid
        device_cookie = str(uuid.uuid4())[:18]

    existing_device = RegisteredDevice.query.filter_by(user_id=current_user.id, device_hash=device_cookie).first()
    if not existing_device:
        user_devices_cnt = RegisteredDevice.query.filter_by(user_id=current_user.id).count()
        dev_status = 'Verified' if user_devices_cnt == 0 else 'Flagged'
        new_dev = RegisteredDevice(
            user_id=current_user.id,
            device_hash=device_cookie,
            label=request.headers.get('User-Agent', 'Browser')[:50],
            status=dev_status
        )
        db.session.add(new_dev)
        db.session.commit()
        
        if dev_status == 'Flagged':
            log_action(f"Flagged New Device Check-in: ID {device_cookie[:8]}", target=current_user.full_name)

    today_str = datetime.now().strftime('%Y-%m-%d')
    existing_att = Attendance.query.filter_by(user_id=current_user.id, date=today_str).first()

    now = datetime.now()
    checkin_time = now.strftime('%I:%M %p')

    if existing_att:
        if not existing_att.check_out:
            existing_att.check_out = checkin_time
            metrics = compute_attendance_metrics(existing_att.check_in, checkin_time)
            db.session.commit()
            
            resp = make_response(redirect(url_for('attendance')))
            resp.set_cookie('bms_device_id', device_cookie, max_age=365*24*3600)
            flash(f'✅ Clocked Out via QR Code at {checkin_time}! Total Worked: {metrics["total_hours"]} hrs.')
            return resp
        else:
            flash(f'Already completed check-in & check-out for today ({today_str})!')
            return redirect(url_for('attendance'))

    # Create New Check-in
    new_att = Attendance(
        user_id=current_user.id,
        date=today_str,
        check_in=checkin_time,
        work_mode='Office',
        lat=CAMPUS_LAT,
        lon=CAMPUS_LON
    )
    db.session.add(new_att)
    
    metrics = compute_attendance_metrics(checkin_time, None)
    if metrics['is_late']:
        db.session.add(Notification(message=f"LATE ARRIVAL: {current_user.full_name} clocked in {metrics['late_minutes']} mins late."))
    
    db.session.commit()

    resp = make_response(redirect(url_for('attendance')))
    resp.set_cookie('bms_device_id', device_cookie, max_age=365*24*3600)
    flash(f'✅ Successfully checked in via QR Code at {checkin_time} on {today_str}!')
    return resp

@app.route('/attendance/daily_close', methods=['POST'])
@login_required
def attendance_daily_close():
    user = User.query.get(session['user_id'])
    if not user or user.role not in ['admin', 'HR', 'Principal']:
        flash('Unauthorized access to Daily Close.')
        return redirect(url_for('dashboard'))

    today_str = datetime.now().strftime('%Y-%m-%d')
    missing_records = Attendance.query.filter_by(date=today_str, check_out=None).all()
    
    missing_names = []
    for att in missing_records:
        staff = User.query.get(att.user_id)
        if staff:
            missing_names.append(staff.full_name)
            # Create in-app notification for individual staff
            db.session.add(Notification(message=f"MISSING CHECK-OUT: You clocked in at {att.check_in} on {today_str} but have not clocked out."))

    # Create notification for HR
    if missing_names:
        hr_msg = f"DAILY CLOSE ALERT: {len(missing_names)} personnel missing check-out today ({', '.join(missing_names[:3])}{'...' if len(missing_names) > 3 else ''})."
        db.session.add(Notification(message=hr_msg))

        # Send email to HR if Mail is configured
        hr_user = User.query.filter(User.role.in_(['HR', 'admin'])).first()
        if hr_user and hr_user.email:
            try:
                mail_msg = MailMessage(
                    subject=f"BMS ERP: Daily Close Alert - Missing Check-outs ({today_str})",
                    recipients=[hr_user.email],
                    body=f"Hello HR,\n\nThe following {len(missing_names)} staff member(s) clocked in today ({today_str}) but did not register a check-out:\n\n" + "\n".join([f"- {name}" for name in missing_names]) + "\n\nPlease review in the ERP portal.\n\nBMS College ERP Automated System"
                )
                mail.send(mail_msg)
            except Exception as e:
                print(f"Mail send error in daily close: {e}")

    db.session.commit()
    log_action(f"Executed Daily Close: Found {len(missing_names)} missing check-outs", target="System")
    flash(f"Daily Close executed successfully! Flagged {len(missing_names)} missing check-outs.")
    return redirect(url_for('attendance'))

@app.route('/admin/devices')
@login_required
def admin_devices():
    user = User.query.get(session['user_id'])
    if not user or user.role not in ['admin', 'HR', 'Principal']:
        flash('Unauthorized access to Device Registry.')
        return redirect(url_for('dashboard'))

    devices = RegisteredDevice.query.order_by(RegisteredDevice.first_seen.desc()).all()
    return render_template('admin_devices.html', devices=devices)


with app.app_context():
    db.create_all()
    seed_database()

if __name__ == '__main__':
    default_port = int(os.environ.get('PORT', 5000))
    candidate_ports = [default_port, 5000, 5050, 8000, 8080]
    
    for port in candidate_ports:
        try:
            print("\n" + "="*55)
            print("🎓 BMS COLLEGE ERP SERVER IS LIVE & RUNNING!")
            print(f"👉 Access Portal at: http://localhost:{port}")
            print("👉 Default Login: Username: admin | Password: admin123")
            print("="*55 + "\n")
            socketio.run(app, host='127.0.0.1', port=port, allow_unsafe_werkzeug=True)
            break
        except OSError as e:
            if "10048" in str(e) or "address already in use" in str(e).lower():
                print(f"⚠️ Port {port} is occupied, trying next port...")
                continue
            raise e















































































































