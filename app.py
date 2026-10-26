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
import calendar
import uuid
import json
from datetime import datetime, timedelta, date
from sqlalchemy import func
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, send_from_directory, jsonify, Response, make_response, abort
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from fpdf import FPDF
import qrcode
from flask_socketio import SocketIO, emit, join_room, leave_room
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

# Private Storage for Academic Resources (Assignments & Study Materials)
app.config['PRIVATE_STORAGE_FOLDER'] = os.environ.get(
    'ACADEMIC_STORAGE_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'private_storage')
)
app.config['ASSIGNMENTS_STORAGE_FOLDER'] = os.path.join(app.config['PRIVATE_STORAGE_FOLDER'], 'assignments')
app.config['STUDY_MATERIALS_STORAGE_FOLDER'] = os.path.join(app.config['PRIVATE_STORAGE_FOLDER'], 'study_materials')
app.config['SUBMISSIONS_STORAGE_FOLDER'] = os.path.join(app.config['PRIVATE_STORAGE_FOLDER'], 'submissions')
app.config['STUDENT_TIMETABLES_STORAGE_FOLDER'] = os.path.join(app.config['PRIVATE_STORAGE_FOLDER'], 'student_timetables')
os.makedirs(app.config['STUDENT_TIMETABLES_STORAGE_FOLDER'], exist_ok=True)
app.config['MAX_ACADEMIC_UPLOAD_BYTES'] = int(os.environ.get('MAX_ACADEMIC_UPLOAD_BYTES', 15 * 1024 * 1024))  # 15 MB default
app.config['ALLOWED_ACADEMIC_EXTENSIONS'] = {'pdf', 'docx', 'doc', 'pptx', 'ppt', 'txt', 'zip', 'jpg', 'jpeg', 'png', 'xlsx', 'csv'}
app.config['PROHIBITED_EXTENSIONS'] = {'exe', 'sh', 'py', 'php', 'html', 'htm', 'js', 'svg', 'bat', 'cmd', 'ps1', 'vbs', 'jar', 'war'}

os.makedirs(app.config['ASSIGNMENTS_STORAGE_FOLDER'], exist_ok=True)
os.makedirs(app.config['STUDY_MATERIALS_STORAGE_FOLDER'], exist_ok=True)
os.makedirs(app.config['SUBMISSIONS_STORAGE_FOLDER'], exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
mail = Mail(app)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def send_notification_email(receiver_email, sender_name):
    if not receiver_email: return
    mail_user = app.config.get('MAIL_USERNAME')
    mail_pwd = app.config.get('MAIL_PASSWORD')
    if not mail_user or not mail_pwd:
        return
    import threading
    def _send():
        with app.app_context():
            import socket
            orig_timeout = socket.getdefaulttimeout()
            try:
                socket.setdefaulttimeout(4.0)
                msg = MailMessage("New Private Message: BMS Connect", recipients=[receiver_email], sender=mail_user)
                msg.body = f"Hello Principal,\n\nYou have received a new private message from {sender_name} on the BMS Connect Staff Portal."
                mail.send(msg)
            except Exception as e:
                print(f"SMTP Error: {e}")
            finally:
                socket.setdefaulttimeout(orig_timeout)
    threading.Thread(target=_send, daemon=True).start()

# ==========================================
# 1. DATABASE SETUP (POSTGRESQL & SQLITE FALLBACK)
# ==========================================
basedir = os.path.abspath(os.path.dirname(__file__))
data_dir = os.path.join(basedir, 'data')
if not os.path.exists(data_dir):
    os.makedirs(data_dir, exist_ok=True)

destination_db = os.path.join(data_dir, 'bms_college_v30.db')
database_url = os.environ.get('DATABASE_URL')

# Check if automated test execution is active to protect production database
is_running_tests = (
    'pytest' in sys.modules
    or any('pytest' in arg for arg in sys.argv)
    or any(os.path.basename(arg).startswith('test_') for arg in sys.argv)
    or os.environ.get('TESTING') in ('1', 'true', 'True')
    or app.config.get('TESTING')
)

if is_running_tests:
    # Automated tests stay isolated on local database to guarantee production PostgreSQL safety
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + destination_db
elif database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    if "sslmode=" not in database_url and ("supabase" in database_url or "render" in database_url):
        if "?" in database_url:
            database_url += "&sslmode=require"
        else:
            database_url += "?sslmode=require"

    try:
        import psycopg2
        test_conn = psycopg2.connect(database_url, connect_timeout=10)
        test_conn.close()
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 5,
            'max_overflow': 10,
            'pool_recycle': 300,
            'pool_pre_ping': True,
        }
        print("Connected to PostgreSQL Production Database (Supabase pooler).")
    except Exception as e:
        # If DATABASE_URL is explicitly configured, fail clearly. Silent SQLite fallback is disabled!
        raise RuntimeError(
            f"CRITICAL: Failed to connect to configured PostgreSQL database ({e}). "
            "Silent fallback to SQLite is strictly disabled to prevent data divergence."
        ) from e
else:
    print("WARNING: No DATABASE_URL environment variable provided. Defaulting to local SQLite database.")
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + destination_db

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

from notification_service import (
    init_notifications,
    create_notification,
    notify_users,
    notify_class_students,
    notify_role,
    get_unread_count,
    get_notifications_list,
    mark_as_read,
    mark_all_as_read,
    get_or_create_preferences,
    update_preferences,
    get_vapid_public_key,
    get_or_create_vapid_keys,
    _dispatch_web_push_batch
)
init_notifications(app, db, socketio)


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
    
    # Extended Academic Details
    course = db.Column(db.String(50), default='BCA', nullable=True)
    section = db.Column(db.String(20), default='A', nullable=True)
    room_no = db.Column(db.String(50), default='Room 204', nullable=True)
    
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

# ==========================================
# 2.1 STUDENT ACADEMIC ATTENDANCE MODELS
# ==========================================

class Student(db.Model):
    __tablename__ = 'student'
    id = db.Column(db.Integer, primary_key=True)
    uucms_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False, index=True)
    course = db.Column(db.String(50), default='BCA', nullable=False)
    academic_year = db.Column(db.String(20), default='3rd Year', nullable=False)
    semester = db.Column(db.String(20), default='Sem V', nullable=False)
    section = db.Column(db.String(20), default='A', nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    raw_password = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    attendances = db.relationship('StudentAttendance', backref='student', lazy=True)

    def check_password(self, password):
        if not password:
            return False
        if self.password_hash and check_password_hash(self.password_hash, password):
            return True
        if self.raw_password and self.raw_password == password:
            return True
        return False

    def __repr__(self):
        return f'<Student {self.uucms_id} - {self.name} ({self.course} {self.semester} Sec {self.section})>'


class ClassSession(db.Model):
    __tablename__ = 'class_session'
    id = db.Column(db.Integer, primary_key=True)
    timetable_id = db.Column(db.Integer, db.ForeignKey('timetable.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    time_slot = db.Column(db.String(50), nullable=False)
    course = db.Column(db.String(50), default='BCA', nullable=False)
    academic_year = db.Column(db.String(20), default='3rd Year', nullable=False)
    semester = db.Column(db.String(20), default='Sem V', nullable=False)
    section = db.Column(db.String(20), default='A', nullable=False)
    scheduled_subject = db.Column(db.String(100), nullable=False)
    actual_subject = db.Column(db.String(100), nullable=False)
    scheduled_faculty_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    actual_faculty_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    room_no = db.Column(db.String(50), default='Room 204', nullable=True)
    status = db.Column(db.String(20), default='COMPLETED', nullable=False)
    remarks = db.Column(db.String(255), nullable=True)
    version = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    timetable = db.relationship('Timetable', backref=db.backref('class_sessions', lazy=True))
    scheduled_faculty = db.relationship('User', foreign_keys=[scheduled_faculty_id], backref='scheduled_class_sessions')
    actual_faculty = db.relationship('User', foreign_keys=[actual_faculty_id], backref='conducted_class_sessions')
    student_attendances = db.relationship('StudentAttendance', backref='class_session', cascade='all, delete-orphan', lazy=True)
    audit_logs = db.relationship('StudentAttendanceAudit', backref='class_session', cascade='all, delete-orphan', lazy=True, order_by='StudentAttendanceAudit.created_at.desc()')

    def __repr__(self):
        return f'<ClassSession {self.actual_subject} ({self.course} {self.semester} Sec {self.section}) on {self.date}>'



class StudentAttendance(db.Model):
    __tablename__ = 'student_attendance'
    id = db.Column(db.Integer, primary_key=True)
    class_session_id = db.Column(db.Integer, db.ForeignKey('class_session.id', ondelete='CASCADE'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='Present') # 'Present', 'Absent'
    marked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    marked_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    remarks = db.Column(db.String(255), nullable=True)

    marker = db.relationship('User', foreign_keys=[marked_by], backref='marked_student_attendances')

    __table_args__ = (
        db.UniqueConstraint('class_session_id', 'student_id', name='uq_student_class_session_att'),
    )

    def __repr__(self):
        return f'<StudentAttendance session:{self.class_session_id} student:{self.student_id} status:{self.status}>'


class StudentAttendanceAudit(db.Model):
    __tablename__ = 'student_attendance_audit'
    id = db.Column(db.Integer, primary_key=True)
    class_session_id = db.Column(db.Integer, db.ForeignKey('class_session.id', ondelete='CASCADE'), nullable=False, index=True)
    student_attendance_id = db.Column(db.Integer, db.ForeignKey('student_attendance.id', ondelete='SET NULL'), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True, index=True)
    changed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    field_name = db.Column(db.String(50), default='status', nullable=False) # 'status', 'actual_subject', 'remarks'
    previous_value = db.Column(db.String(255), nullable=True)
    new_value = db.Column(db.String(255), nullable=True)
    reason = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship('Student', foreign_keys=[student_id], backref='attendance_audits')
    editor = db.relationship('User', foreign_keys=[changed_by], backref='conducted_attendance_audits')
    student_attendance = db.relationship('StudentAttendance', foreign_keys=[student_attendance_id])

    def __repr__(self):
        return f'<StudentAttendanceAudit session:{self.class_session_id} field:{self.field_name} {self.previous_value}->{self.new_value}>'


# ==========================================
# 2.2 STUDENT INTERNAL ASSESSMENT MARKS MODELS
# ==========================================

class InternalMark(db.Model):
    __tablename__ = 'internal_mark'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False, index=True)
    course = db.Column(db.String(50), default='BCA', nullable=False)
    academic_year = db.Column(db.String(20), default='3rd Year', nullable=False)
    semester = db.Column(db.String(20), default='Sem V', nullable=False)
    section = db.Column(db.String(20), default='A', nullable=False)
    subject = db.Column(db.String(100), nullable=False, index=True)
    assessment_cycle = db.Column(db.String(50), default='2026-27', nullable=False)

    # 3 Distinct Assessment Components
    # Float allows decimal precision (e.g. 18.5, 22.75). None indicates 'Not Entered'. 0.0 is an actual zero!
    ia1_marks = db.Column(db.Float, nullable=True)
    ia2_marks = db.Column(db.Float, nullable=True)
    final_ia_marks = db.Column(db.Float, nullable=True)

    # Creator & Editor tracking
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Optimistic locking for concurrency control
    version = db.Column(db.Integer, default=1, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    student = db.relationship('Student', backref=db.backref('internal_marks', lazy=True, cascade='all, delete-orphan'))
    creator = db.relationship('User', foreign_keys=[created_by_id], backref='created_internal_marks')
    updater = db.relationship('User', foreign_keys=[updated_by_id], backref='updated_internal_marks')

    __table_args__ = (
        db.UniqueConstraint('student_id', 'subject', 'academic_year', 'semester', 'assessment_cycle', name='uq_student_subj_sem_cycle'),
    )

    @property
    def completion_status(self):
        """
        Returns status string:
        - 'Complete': All 3 components entered (either positive or zero)
        - 'Partial': 1 or 2 components entered
        - 'Not Started': 0 components entered
        """
        entered_count = sum(1 for m in [self.ia1_marks, self.ia2_marks, self.final_ia_marks] if m is not None)
        if entered_count == 3:
            return 'Complete'
        elif entered_count > 0:
            return 'Partial'
        return 'Not Started'

    def __repr__(self):
        return f'<InternalMark student:{self.student_id} subj:{self.subject} IA1:{self.ia1_marks} IA2:{self.ia2_marks} Final:{self.final_ia_marks}>'


class InternalMarkAudit(db.Model):
    __tablename__ = 'internal_mark_audit'
    id = db.Column(db.Integer, primary_key=True)
    internal_mark_id = db.Column(db.Integer, db.ForeignKey('internal_mark.id', ondelete='CASCADE'), nullable=True, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    subject = db.Column(db.String(100), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(20), nullable=False)
    assessment_cycle = db.Column(db.String(50), nullable=False)
    component = db.Column(db.String(20), nullable=False) # 'IA1', 'IA2', 'Final IA'
    previous_value = db.Column(db.String(50), nullable=True) # string representation or None
    new_value = db.Column(db.String(50), nullable=True)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(255), nullable=True) # mandatory for corrections of existing saved values
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship('Student', foreign_keys=[student_id], backref='internal_mark_audits')
    editor = db.relationship('User', foreign_keys=[changed_by_id], backref='conducted_mark_audits')
    internal_mark = db.relationship('InternalMark', backref=db.backref('audits', cascade='all, delete-orphan', lazy=True))

    def __repr__(self):
        return f'<InternalMarkAudit mark:{self.internal_mark_id} comp:{self.component} {self.previous_value}->{self.new_value}>'


# ==========================================
# 2.3 IA ASSESSMENT CUTOFF & ELIGIBILITY OVERRIDE MODELS
# ==========================================

class AssessmentCutoff(db.Model):
    __tablename__ = 'assessment_cutoff'
    id = db.Column(db.Integer, primary_key=True)
    course = db.Column(db.String(50), default='BCA', nullable=False, index=True)
    semester = db.Column(db.String(20), default='Sem V', nullable=False, index=True)
    section = db.Column(db.String(20), default='A', nullable=False)
    subject = db.Column(db.String(100), nullable=True) # None = class default
    assessment_cycle = db.Column(db.String(50), default='2026-27', nullable=False, index=True)
    component = db.Column(db.String(20), nullable=False) # 'IA1', 'IA2', 'Final IA'
    cutoff_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('course', 'semester', 'section', 'subject', 'assessment_cycle', 'component', name='uq_assessment_cutoff'),
    )

    def __repr__(self):
        return f'<AssessmentCutoff {self.course} {self.semester} {self.subject or "All"} {self.component}: {self.cutoff_date}>'


class MarksEligibilityOverride(db.Model):
    __tablename__ = 'marks_eligibility_override'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False, index=True)
    subject = db.Column(db.String(100), nullable=False, index=True)
    course = db.Column(db.String(50), default='BCA', nullable=False)
    semester = db.Column(db.String(20), default='Sem V', nullable=False)
    section = db.Column(db.String(20), default='A', nullable=False)
    assessment_cycle = db.Column(db.String(50), default='2026-27', nullable=False)
    component = db.Column(db.String(20), default='ALL', nullable=False) # 'ALL', 'IA1', 'IA2', 'Final IA'
    decision_type = db.Column(db.String(30), nullable=False) # 'ALLOW_OVERRIDE', 'MANUAL_RESTRICT'
    reason = db.Column(db.Text, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    student = db.relationship('Student', backref=db.backref('eligibility_overrides', lazy=True, cascade='all, delete-orphan'))
    creator = db.relationship('User', foreign_keys=[created_by_id], backref='created_eligibility_overrides')
    updater = db.relationship('User', foreign_keys=[updated_by_id], backref='updated_eligibility_overrides')

    __table_args__ = (
        db.UniqueConstraint('student_id', 'subject', 'course', 'semester', 'section', 'assessment_cycle', 'component', name='uq_marks_eligibility_override'),
    )

    def __repr__(self):
        return f'<MarksEligibilityOverride student:{self.student_id} subj:{self.subject} {self.decision_type} active:{self.is_active}>'


class MarksEligibilityAudit(db.Model):
    __tablename__ = 'marks_eligibility_audit'
    id = db.Column(db.Integer, primary_key=True)
    override_id = db.Column(db.Integer, db.ForeignKey('marks_eligibility_override.id', ondelete='SET NULL'), nullable=True, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False, index=True)
    subject = db.Column(db.String(100), nullable=False)
    course = db.Column(db.String(50), nullable=False)
    semester = db.Column(db.String(20), nullable=False)
    section = db.Column(db.String(20), nullable=False)
    assessment_cycle = db.Column(db.String(50), nullable=False)
    component = db.Column(db.String(20), nullable=False) # 'ALL', 'IA1', 'IA2', 'Final IA'
    action = db.Column(db.String(30), nullable=False) # 'ALLOW_OVERRIDE', 'MANUAL_RESTRICT', 'REVOKE'
    previous_decision = db.Column(db.String(50), nullable=True) # e.g. 'AUTOMATIC', 'ALLOW_OVERRIDE', 'MANUAL_RESTRICT'
    new_decision = db.Column(db.String(50), nullable=False) # 'ALLOW_OVERRIDE', 'MANUAL_RESTRICT', 'AUTOMATIC'
    reason = db.Column(db.Text, nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship('Student', foreign_keys=[student_id], backref='eligibility_audits')
    editor = db.relationship('User', foreign_keys=[changed_by_id], backref='conducted_eligibility_audits')
    override = db.relationship('MarksEligibilityOverride', foreign_keys=[override_id])

    def __repr__(self):
        return f'<MarksEligibilityAudit student:{self.student_id} action:{self.action} by:{self.changed_by_id}>'


# ==========================================
# 2.4 ACADEMIC ASSIGNMENTS & STUDY MATERIALS MODELS
# ==========================================

class Assignment(db.Model):
    __tablename__ = 'assignment'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    course = db.Column(db.String(50), default='BCA', nullable=False)
    semester = db.Column(db.String(20), default='Sem V', nullable=False)
    section = db.Column(db.String(20), default='A', nullable=False)
    subject = db.Column(db.String(100), nullable=False, index=True)
    academic_year = db.Column(db.String(20), default='3rd Year', nullable=False)
    assigned_date = db.Column(db.Date, nullable=False, default=date.today)
    deadline = db.Column(db.DateTime, nullable=False)
    max_marks = db.Column(db.Float, nullable=True) # e.g. 20.0 or 10.0
    status = db.Column(db.String(20), default='Published', nullable=False) # 'Draft', 'Published', 'Archived', 'Cancelled'

    # Secure Attachment Reference
    attachment_filename = db.Column(db.String(255), nullable=True) # Safe display name
    attachment_storage_key = db.Column(db.String(255), nullable=True) # Randomized private key
    attachment_mimetype = db.Column(db.String(100), nullable=True)
    attachment_size = db.Column(db.Integer, nullable=True)

    # Ownership & Timestamps
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    creator = db.relationship('User', foreign_keys=[created_by_id], backref='created_assignments')
    updater = db.relationship('User', foreign_keys=[updated_by_id], backref='updated_assignments')
    submissions = db.relationship('AssignmentSubmission', backref='assignment', cascade='all, delete-orphan', lazy=True)

    def __repr__(self):
        return f'<Assignment {self.title} ({self.subject} {self.course} {self.semester} Sec {self.section})>'


class AssignmentSubmission(db.Model):
    __tablename__ = 'assignment_submission'
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id', ondelete='CASCADE'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False, index=True)
    status = db.Column(db.String(30), default='Submitted', nullable=False) # 'Submitted', 'Not submitted', 'Late'
    status_source = db.Column(db.String(30), default='STUDENT_UPLOAD', nullable=False) # 'STUDENT_UPLOAD', 'TEACHER_RECORDED', 'SYSTEM_DEFAULT'
    submitted_at = db.Column(db.DateTime, nullable=True)

    # Submission File
    file_filename = db.Column(db.String(255), nullable=True)
    file_storage_key = db.Column(db.String(255), nullable=True)
    file_mimetype = db.Column(db.String(100), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    version = db.Column(db.Integer, default=1, nullable=False)
    student_comment = db.Column(db.Text, nullable=True)

    # Optional grading & feedback
    marks_obtained = db.Column(db.Float, nullable=True)
    teacher_feedback = db.Column(db.Text, nullable=True)
    graded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    graded_at = db.Column(db.DateTime, nullable=True)

    # Status modification audit
    last_status_changed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    last_status_changed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    student = db.relationship('Student', backref=db.backref('assignment_submissions', lazy=True, cascade='all, delete-orphan'))
    grader = db.relationship('User', foreign_keys=[graded_by_id])
    status_changer = db.relationship('User', foreign_keys=[last_status_changed_by_id])

    __table_args__ = (
        db.UniqueConstraint('assignment_id', 'student_id', name='uq_assignment_student_submission'),
    )

    def __repr__(self):
        return f'<AssignmentSubmission asg:{self.assignment_id} student:{self.student_id} status:{self.status}>'


class StudyMaterial(db.Model):
    __tablename__ = 'study_material'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=False, index=True) # 'Textbooks', 'Previous Year Papers', 'Question Banks'
    subject = db.Column(db.String(100), nullable=False, index=True)
    course = db.Column(db.String(50), default='BCA', nullable=False)
    semester = db.Column(db.String(20), default='Sem V', nullable=False)
    section = db.Column(db.String(20), default='ALL', nullable=True)
    academic_year = db.Column(db.String(20), default='3rd Year', nullable=False)
    unit_or_chapter = db.Column(db.String(100), nullable=True)
    exam_year = db.Column(db.String(20), nullable=True) # e.g. '2024', '2023'
    tags = db.Column(db.String(255), nullable=True)

    # Secure File Reference
    file_filename = db.Column(db.String(255), nullable=False)
    file_storage_key = db.Column(db.String(255), nullable=False)
    file_mimetype = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    file_checksum = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(20), default='Published', nullable=False) # 'Published', 'Archived', 'Draft'

    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    creator = db.relationship('User', foreign_keys=[created_by_id], backref='uploaded_study_materials')
    updater = db.relationship('User', foreign_keys=[updated_by_id], backref='updated_study_materials')

    def __repr__(self):
        return f'<StudyMaterial {self.category}: {self.title} ({self.subject})>'


class StudentSemesterTimetable(db.Model):
    __tablename__ = 'student_semester_timetable'
    id = db.Column(db.Integer, primary_key=True)
    course = db.Column(db.String(50), default='BCA', nullable=False, index=True)
    academic_year = db.Column(db.String(20), default='3rd Year', nullable=False, index=True)
    semester = db.Column(db.String(20), default='Sem V', nullable=False, index=True)
    section = db.Column(db.String(20), default='A', nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Secure file reference
    file_filename = db.Column(db.String(255), nullable=False)
    file_storage_key = db.Column(db.String(255), nullable=False)
    file_mimetype = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False, default=0)
    file_checksum = db.Column(db.String(64), nullable=True)

    version = db.Column(db.Integer, default=1, nullable=False)
    status = db.Column(db.String(20), default='PUBLISHED', nullable=False, index=True) # 'PUBLISHED' or 'ARCHIVED'

    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    uploader = db.relationship('User', foreign_keys=[uploaded_by_id], backref='uploaded_student_timetables')

    __table_args__ = (
        db.Index('idx_student_tt_scope', 'course', 'academic_year', 'semester', 'section', 'status'),
    )

    def __repr__(self):
        return f'<StudentSemesterTimetable {self.course} {self.semester} Sec {self.section} v{self.version} ({self.status})>'


class AcademicResourceAudit(db.Model):
    __tablename__ = 'academic_resource_audit'
    id = db.Column(db.Integer, primary_key=True)
    resource_type = db.Column(db.String(50), nullable=False, index=True) # 'ASSIGNMENT', 'SUBMISSION', 'STUDY_MATERIAL'
    resource_id = db.Column(db.Integer, nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False) # 'CREATE', 'UPDATE', 'STATUS_CHANGE', 'DELETE', 'ARCHIVE', 'GRADE'
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    actor_student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True)
    before_state = db.Column(db.Text, nullable=True)
    after_state = db.Column(db.Text, nullable=True)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    actor_user = db.relationship('User', foreign_keys=[actor_id])
    actor_student = db.relationship('Student', foreign_keys=[actor_student_id])

    def __repr__(self):
        return f'<AcademicResourceAudit {self.resource_type}:{self.resource_id} {self.action}>'


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

def _parse_slot_minutes(slot_str):
    """Parse a time slot string like '08:00 AM-10:00 AM' into (start_min, end_min)."""
    import re
    parts = slot_str.split('-')
    if len(parts) != 2:
        return 0, 0
    def to_min(t):
        t = t.strip()
        m = re.match(r'(\d+):(\d+)\s*(AM|PM)', t, re.I)
        if not m:
            return 0
        h, mn, mer = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if mer == 'PM' and h != 12:
            h += 12
        elif mer == 'AM' and h == 12:
            h = 0
        return h * 60 + mn
    return to_min(parts[0]), to_min(parts[1])


def validate_timetable_conflicts(entries):
    """
    Validate a list of timetable entry dicts for scheduling conflicts.
    Each entry dict must have keys: user_id, day, time_slot, room_no, course, semester, section, subject.
    Returns a list of conflict description strings. Empty list means no conflicts.
    """
    conflicts = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            e1, e2 = entries[i], entries[j]
            if e1['day'] != e2['day']:
                continue
            s1, en1 = _parse_slot_minutes(e1['time_slot'])
            s2, en2 = _parse_slot_minutes(e2['time_slot'])
            if s1 >= en2 or s2 >= en1:
                continue  # No overlap
            # Faculty overlap
            if e1['user_id'] and e2['user_id'] and e1['user_id'] == e2['user_id']:
                conflicts.append(
                    f"FACULTY CONFLICT: Same faculty (ID {e1['user_id']}) on {e1['day']} "
                    f"({e1['time_slot']} '{e1['subject']}' vs {e2['time_slot']} '{e2['subject']}')"
                )
            # Room overlap (ignore unassigned / break rooms)
            r1 = (e1.get('room_no') or '').strip().upper()
            r2 = (e2.get('room_no') or '').strip().upper()
            if r1 and r2 and r1 not in ('', 'BREAK', 'N/A') and r1 == r2:
                conflicts.append(
                    f"ROOM CONFLICT: Room '{e1['room_no']}' on {e1['day']} "
                    f"({e1['time_slot']} '{e1['subject']}' vs {e2['time_slot']} '{e2['subject']}')"
                )
            # Section overlap (same class/section cannot have two subjects at same time)
            if (e1.get('course'), e1.get('semester'), e1.get('section')) == \
               (e2.get('course'), e2.get('semester'), e2.get('section')):
                conflicts.append(
                    f"SECTION CONFLICT: {e1['course']} {e1['semester']} Sec {e1['section']} on {e1['day']} "
                    f"({e1['time_slot']} '{e1['subject']}' vs {e2['time_slot']} '{e2['subject']}')"
                )
    return conflicts


def sync_authoritative_timetable():
    """
    Idempotent synchronization of the BCA Semester V timetable against the
    authoritative BMS College of Commerce and Management AY 2026-27 source schedule.

    Safe update strategy:
    - Timetable.id=31 is updated IN-PLACE to preserve ClassSession foreign-key references
      (ClassSession records 1, 2, 3 reference this row).
    - Unreferenced stale Sem V rows are deleted.
    - Referenced rows (id=31) are NEVER deleted; only their fields are updated.
    - Sem I-IV rows are not touched except for Dr. Kiran Kumar MN subject title standardization.
    """
    def get_uid(uname):
        u = User.query.filter_by(username=uname).first()
        return u.id if u else None

    # -----------------------------------------------------------------------
    # AUTHORITATIVE SEM V SCHEDULE — AY 2026-27
    # Source: BMS College of Commerce and Management V Semester Time Table
    # Rooms verified from original uploaded source image.
    # -----------------------------------------------------------------------
    # Format: (username, day, time_slot, subject, sem, course, section, room_no)
    authoritative_sem5 = [
        # ── MONDAY ──────────────────────────────────────────────────────────
        ('shivani',   'Monday', '08:00 AM-10:00 AM', 'Web Programming Lab',              'Sem V', 'BCA', 'A', '101'),
        ('shrinkala', 'Monday', '10:30 AM-11:30 AM', 'Cryptography & Network Security',  'Sem V', 'BCA', 'A', '101'),
        ('shivani',   'Monday', '11:30 AM-12:30 PM', 'Software Engineering',              'Sem V', 'BCA', 'A', '203'),
        ('balram',    'Monday', '12:30 PM-01:30 PM', 'Web Programming',                  'Sem V', 'BCA', 'A', '203'),
        ('newfac',    'Monday', '02:00 PM-05:00 PM', 'CRT Program (Add-on)',              'Sem V', 'BCA', 'A', 'GF Lab'),
        # ── TUESDAY ─────────────────────────────────────────────────────────
        ('shivani',   'Tuesday', '09:00 AM-10:00 AM', 'Software Engineering',             'Sem V', 'BCA', 'A', '102'),
        ('shrinkala', 'Tuesday', '10:30 AM-11:30 AM', 'Cryptography & Network Security',  'Sem V', 'BCA', 'A', '103'),
        ('balram',    'Tuesday', '11:30 AM-12:30 PM', 'Web Programming',                  'Sem V', 'BCA', 'A', '103'),
        # ── WEDNESDAY ───────────────────────────────────────────────────────
        ('balram',    'Wednesday', '09:00 AM-10:00 AM', 'Web Programming',                'Sem V', 'BCA', 'A', '103'),
        ('shivani',   'Wednesday', '10:30 AM-11:30 AM', 'Software Engineering',           'Sem V', 'BCA', 'A', '101'),
        ('shrinkala', 'Wednesday', '11:30 AM-12:30 PM', 'Cryptography & Network Security','Sem V', 'BCA', 'A', '303'),
        ('gururaj',   'Wednesday', '12:30 PM-01:30 PM', 'Quantitative Techniques',        'Sem V', 'BCA', 'A', '101'),
        ('gururaj',   'Wednesday', '02:00 PM-03:00 PM', 'Quantitative Techniques',        'Sem V', 'BCA', 'A', '105'),
        # ── THURSDAY ────────────────────────────────────────────────────────
        ('bhoomika',  'Thursday', '08:00 AM-10:00 AM', 'Data Analytics',                 'Sem V', 'BCA', 'A', '305'),
        ('shivani',   'Thursday', '10:30 AM-11:30 AM', 'Web Programming Lab',            'Sem V', 'BCA', 'A', '101'),
        ('shivani',   'Thursday', '11:30 AM-12:30 PM', 'Software Engineering',           'Sem V', 'BCA', 'A', '103'),
        # ── FRIDAY ──────────────────────────────────────────────────────────
        ('bhoomika',  'Friday', '08:00 AM-10:00 AM', 'Data Analytics',                   'Sem V', 'BCA', 'A', '303'),
        ('shrinkala', 'Friday', '10:30 AM-11:30 AM', 'Cryptography & Network Security',  'Sem V', 'BCA', 'A', '303'),
        # ── SATURDAY ────────────────────────────────────────────────────────
        ('bhoomika',  'Saturday', '08:00 AM-10:00 AM', 'Data Analytics',                 'Sem V', 'BCA', 'A', '101'),
        ('newfac',    'Saturday', '10:30 AM-12:30 PM', 'CRT Program (Add-on)',            'Sem V', 'BCA', 'A', '101'),
    ]

    # Conflict pre-validation
    entry_dicts = []
    for uname, day, slot, subj, sem, course, sec, room in authoritative_sem5:
        uid = get_uid(uname)
        entry_dicts.append({'user_id': uid, 'day': day, 'time_slot': slot,
                            'subject': subj, 'semester': sem, 'course': course,
                            'section': sec, 'room_no': room})
    conflicts = validate_timetable_conflicts(entry_dicts)
    if conflicts:
        print("⚠️  Timetable Conflict Report (Sem V):")
        for c in conflicts:
            print(f"   - {c}")
    else:
        print("✅ Sem V Authoritative Schedule: Zero conflicts detected.")

    # -----------------------------------------------------------------------
    # STEP 1: Handle Timetable.id=31 specially (ClassSession FK preservation)
    # id=31 is referenced by ClassSession rows 1,2,3.  Update it in-place to
    # Monday 12:30 PM-01:30 PM Web Programming / Balram / Room 203.
    # -----------------------------------------------------------------------
    balram_id = get_uid('balram')
    if balram_id:
        tt31 = Timetable.query.get(31)
        if tt31:
            tt31.user_id   = balram_id
            tt31.day       = 'Monday'
            tt31.time_slot = '12:30 PM-01:30 PM'
            tt31.subject   = 'Web Programming'
            tt31.semester  = 'Sem V'
            tt31.course    = 'BCA'
            tt31.section   = 'A'
            tt31.room_no   = '203'

    # -----------------------------------------------------------------------
    # STEP 2: Build the set of canonical (uid, day, slot, subj, sem, sec) keys
    # -----------------------------------------------------------------------
    sem5_canonical_keys = set()
    # Always include the id=31 slot in the canonical set so it is never deleted
    if balram_id:
        sem5_canonical_keys.add((balram_id, 'Monday', '12:30 PM-01:30 PM', 'Web Programming', 'Sem V', 'A'))

    for uname, day, slot, subj, sem, course, sec, room in authoritative_sem5:
        uid = get_uid(uname)
        if not uid:
            continue
        key = (uid, day, slot, subj, sem, sec)
        sem5_canonical_keys.add(key)
        # Skip id=31 row — already updated above
        if uid == balram_id and day == 'Monday' and slot == '12:30 PM-01:30 PM' and subj == 'Web Programming':
            continue
        existing = Timetable.query.filter_by(
            user_id=uid, day=day, time_slot=slot,
            subject=subj, semester=sem, section=sec
        ).first()
        if existing:
            existing.course   = course
            existing.room_no  = room
        else:
            db.session.add(Timetable(
                user_id=uid, day=day, time_slot=slot,
                subject=subj, semester=sem, course=course,
                section=sec, room_no=room, status='pending'
            ))

    # -----------------------------------------------------------------------
    # STEP 3: Remove stale Sem V rows that are NOT in the canonical set and NOT
    #         referenced by any ClassSession (FK safety check).
    # -----------------------------------------------------------------------
    referenced_ids = {cs.timetable_id for cs in ClassSession.query.all()}
    stale_rows = Timetable.query.filter_by(semester='Sem V').all()
    deleted_count = 0
    for row in stale_rows:
        key = (row.user_id, row.day, row.time_slot, row.subject, row.semester, row.section)
        if key not in sem5_canonical_keys:
            if row.id in referenced_ids:
                print(f"⚠️  Stale Sem V row ID={row.id} is referenced by ClassSession — skipping deletion, updating fields.")
            else:
                db.session.delete(row)
                deleted_count += 1
    if deleted_count:
        print(f"🗑️  Removed {deleted_count} stale / superseded Sem V rows.")

    # -----------------------------------------------------------------------
    # STEP 4: Standardize Dr. Kiran Kumar MN Sem I-IV subject titles
    # -----------------------------------------------------------------------
    kiran = User.query.filter_by(username='kiran').first()
    if kiran:
        kiran_title_map = {
            'Sem I':  ('Data Structures', 'C Programming', 'C Programming'),
            'Sem II': ('Data Structures', 'Data Structures and Algorithms', 'Data Structures and Algorithms'),
            'Sem III':('DBMS', 'Database Management System', 'Database Management System'),
            'Sem IV': ('DAA', 'Design and Analysis of Algorithms', 'Design and Analysis of Algorithms'),
        }
        # Normalize any old names to the authoritative ones
        old_to_new = {
            'Data Structures': 'Data Structures and Algorithms',
            'DBMS': 'Database Management System',
            'DAA': 'Design and Analysis of Algorithms',
            'C Programming': 'C Programming',
        }
        kiran_entries = Timetable.query.filter_by(user_id=kiran.id).all()
        for entry in kiran_entries:
            if entry.semester == 'Sem V':
                # Should never happen per business rule; log and skip
                print(f"⚠️  Dr. Kiran is erroneously assigned a Sem V entry (ID={entry.id}). Flagged for review.")
                continue
            new_subj = old_to_new.get(entry.subject)
            if new_subj and new_subj != entry.subject:
                print(f"📝 Normalizing Kiran's subject: '{entry.subject}' → '{new_subj}' (ID={entry.id})")
                entry.subject = new_subj

    db.session.commit()
    print("✅ sync_authoritative_timetable() complete.")


def inject_official_students():
    # Official Student Roster (BCA Sem V)
    official_students = [
        ("Aishwarya", "kmaishwarya30@gmail.com", "U18IN24S0004"),
        ("Aadya", "aadya2846@gmail.com", "U18IN24S0001"),
        ("Adithi", "Chaitras04112006@gmail.com", "U18IN24S0003"),
        ("Abhay", "abhaynair.m@gmail.com", "U18IN24S0002"),
        ("Avish", "avishgr2006@gmail.com", "U18IN24S0011"),
        ("Bhargav", "bhargavkrish007aa@gmail.com", "U18IN24S0012"),
        ("Dhanush", "dhanushdrklr@gmail.com", "U18IN24S0013"),
        ("Vishruth", "guptavishruth540@gmail.com", "U18IN24S0015"),
        ("Keerthana", "Keerthanajagadish29@gmail.com", "U18IN24S0024"),
        ("Likith", "Likithh.2k6@gmail.com", "U18IN24S0027"),
        ("Moulya", "moulya.hemavathi@gmail.com", "U18IN24S0033"),
        ("Preethi", "preethims2007@gmail.com", "U18IN24S0036"),
        ("Sneha", "snehahsshivakumar@gmail.com", "U18IN24S0049"),
        ("Tharun", "tharun2626s@gmail.com", "U18IN24S0055"),
        ("Sushith", "madhusuhas99@gmail.com", "U18IN24S0053"),
        ("Sahana", "Sahanacshastry2006@gmail.com", "U18IN24S0040"),
        ("Kavya", "jagadishkavya29@gmail.com", "U18IN24S0023"),
    ]

    for name, email, uucms_id in official_students:
        s = Student.query.filter_by(uucms_id=uucms_id).first()
        if not s:
            db.session.add(Student(
                uucms_id=uucms_id,
                name=name,
                email=email.strip().lower(),
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                is_active=True
            ))
        else:
            s.name = name
            s.email = email.strip().lower()
            s.course = 'BCA'
            s.academic_year = '3rd Year'
            s.semester = 'Sem V'
            s.section = 'A'
            s.is_active = True
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
    accuracy = db.Column(db.Float, nullable=True)
    location_status = db.Column(db.String(50), nullable=True)

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
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True) # Legacy & User.id
    recipient_type = db.Column(db.String(20), default='USER', nullable=False) # 'USER' or 'STUDENT'
    student_id = db.Column(db.Integer, nullable=True) # Student.id
    title = db.Column(db.String(150), nullable=True)
    message = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(50), default='general', nullable=False)
    action_url = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    idempotency_key = db.Column(db.String(100), nullable=True, index=True)
    timestamp = db.Column(db.DateTime, default=get_ist_time, nullable=False)

    def __init__(self, **kwargs):
        if 'msg' in kwargs and 'message' not in kwargs:
            kwargs['message'] = kwargs.pop('msg')
        super().__init__(**kwargs)

class NotificationPreference(db.Model):
    __tablename__ = 'notification_preference'
    id = db.Column(db.Integer, primary_key=True)
    recipient_type = db.Column(db.String(20), default='USER', nullable=False) # 'USER' or 'STUDENT'
    user_id = db.Column(db.Integer, nullable=True)
    student_id = db.Column(db.Integer, nullable=True)
    sound_enabled = db.Column(db.Boolean, default=True, nullable=False)
    browser_enabled = db.Column(db.Boolean, default=True, nullable=False)
    email_enabled = db.Column(db.Boolean, default=True, nullable=False)
    volume = db.Column(db.Float, default=0.7, nullable=False)
    muted_categories = db.Column(db.String(255), default='', nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PushSubscription(db.Model):
    __tablename__ = 'push_subscription'
    id = db.Column(db.Integer, primary_key=True)
    recipient_type = db.Column(db.String(20), default='USER', nullable=False) # 'USER' or 'STUDENT'
    user_id = db.Column(db.Integer, nullable=True)
    student_id = db.Column(db.Integer, nullable=True)
    endpoint = db.Column(db.Text, unique=True, nullable=False)
    p256dh_key = db.Column(db.Text, nullable=False)
    auth_key = db.Column(db.Text, nullable=False)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=get_ist_time, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=get_ist_time, nullable=False)

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

class VaultDocument(db.Model):
    __tablename__ = 'vault_document'
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_hash = db.Column(db.String(64), nullable=False, index=True)
    file_size = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    uploader = db.relationship('User', foreign_keys=[uploaded_by_id], backref='uploaded_vault_documents')

    def __repr__(self):
        return f'<VaultDocument {self.original_filename} ({self.file_hash[:8]})>'


class VaultProposal(db.Model):
    __tablename__ = 'vault_proposal'
    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(db.String(36), unique=True, nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey('vault_document.id', ondelete='SET NULL'), nullable=True)
    target_type = db.Column(db.String(20), nullable=False) # 'STUDENT' or 'STAFF'
    operation = db.Column(db.String(20), nullable=False) # 'CREATE' or 'UPDATE'
    target_record_id = db.Column(db.Integer, nullable=True)
    target_identifier = db.Column(db.String(100), nullable=True)
    classification = db.Column(db.String(40), nullable=False)
    raw_ocr_text = db.Column(db.Text, nullable=True)
    extracted_data_json = db.Column(db.Text, nullable=False, default='{}')
    proposed_changes_json = db.Column(db.Text, nullable=False, default='{}')
    before_values_json = db.Column(db.Text, nullable=True, default='{}')
    diff_summary_json = db.Column(db.Text, nullable=True, default='[]')
    validation_warnings_json = db.Column(db.Text, nullable=True, default='[]')
    status = db.Column(db.String(30), default='PENDING_APPROVAL', nullable=False, index=True)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    applied_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    applied_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    version = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    document = db.relationship('VaultDocument', backref=db.backref('proposals', lazy=True))
    submitter = db.relationship('User', foreign_keys=[submitted_by_id], backref='submitted_vault_proposals')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id], backref='reviewed_vault_proposals')
    applier = db.relationship('User', foreign_keys=[applied_by_id], backref='applied_vault_proposals')

    def __repr__(self):
        return f'<VaultProposal {self.proposal_id[:8]} {self.target_type} {self.operation} {self.status}>'

from campus_geofence import (
    verify_campus_presence,
    get_geofence_config,
    update_geofence_config,
    haversine_distance,
    point_in_polygon
)

# Canonical Institution Reference: BMS College of Commerce & Management (BMSCCM)
# Address: No. 97, Kavi Lakshmisha Road, Parvathi Nagar / V.V. Puram, Bengaluru – 560004
CAMPUS_LAT = float(os.environ.get('CAMPUS_LAT', 12.9515))
CAMPUS_LON = float(os.environ.get('CAMPUS_LON', 77.5762))
CAMPUS_RADIUS_METERS = float(os.environ.get('CAMPUS_RADIUS_METERS', 150.0))
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
    """Haversine formula to calculate geodesic distance in meters (delegates to authoritative campus_geofence)."""
    return haversine_distance(lat1, lon1, lat2, lon2)

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
    },
    'student_absence_notification': {
        'channels': ['email'],
        'subject': lambda u, c: f"Attendance Notification - BMS College ({c.get('subject', 'Academic Session')})",
        'email_body': lambda u, c: f"<h3>Attendance Notification — BMS College</h3><p>Dear {getattr(u, 'name', getattr(u, 'full_name', 'Student'))},</p><p>This is to inform you that you were marked <strong>ABSENT</strong> for the following academic session:</p><ul><li><strong>Course:</strong> {c.get('course', 'BCA')}</li><li><strong>Semester:</strong> {c.get('semester', 'Sem V')}</li><li><strong>Section:</strong> {c.get('section', 'A')}</li><li><strong>Subject:</strong> {c.get('subject', 'N/A')}</li><li><strong>Date:</strong> {c.get('date', 'Today')}</li><li><strong>Time Slot:</strong> {c.get('time_slot', 'N/A')}</li><li><strong>Room:</strong> {c.get('room_no', 'N/A')}</li><li><strong>Faculty:</strong> {c.get('faculty', 'Faculty')}</li></ul><p>If you believe this attendance record is incorrect, please contact the concerned faculty member promptly.</p><p>Regards,<br><strong>BMS College ERP Academic Cell</strong></p>",
    },
    'assignment_published': {
        'channels': ['email'],
        'subject': lambda u, c: f"BMS College ERP — New Assignment: {c.get('subject', 'Academic')} ({c.get('title', 'Assignment')})",
        'email_body': lambda u, c: f"<h3>New Academic Assignment Published</h3><p>Dear {getattr(u, 'name', getattr(u, 'full_name', 'Student'))},</p><p>A new academic assignment has been published for your class:</p><ul><li><strong>Subject:</strong> {c.get('subject', 'N/A')}</li><li><strong>Title:</strong> {c.get('title', 'Assignment')}</li><li><strong>Assigned Date:</strong> {c.get('assigned_date', 'Today')}</li><li><strong>Submission Deadline:</strong> {c.get('deadline', 'As scheduled')}</li><li><strong>Maximum Marks:</strong> {c.get('max_marks', 'N/A')}</li></ul><p>Please log in to your Student Portal to view detailed instructions and submit your work before the deadline.</p><p>Best regards,<br><strong>BMS College ERP Academic Cell</strong></p>",
    },
    'assignment_deadline_updated': {
        'channels': ['email'],
        'subject': lambda u, c: f"BMS College ERP — Deadline Update: {c.get('subject', 'Academic')} ({c.get('title', 'Assignment')})",
        'email_body': lambda u, c: f"<h3>Assignment Deadline Updated</h3><p>Dear {getattr(u, 'name', getattr(u, 'full_name', 'Student'))},</p><p>The submission deadline for the following assignment has been revised:</p><ul><li><strong>Subject:</strong> {c.get('subject', 'N/A')}</li><li><strong>Title:</strong> {c.get('title', 'Assignment')}</li><li><strong>Revised Deadline:</strong> {c.get('deadline', 'As scheduled')}</li></ul><p>Please ensure your submission is recorded before the revised deadline.</p><p>Best regards,<br><strong>BMS College ERP Academic Cell</strong></p>",
    }
}

def _send_email_notification(user, subject, body_html, attachment_path=None):
    if not user.email or '@' not in user.email:
        return False, "Recipient email missing or invalid"
    mail_user = app.config.get('MAIL_USERNAME')
    mail_pwd = app.config.get('MAIL_PASSWORD')
    if not mail_user or not mail_pwd or 'your_' in str(mail_pwd).lower() or 'placeholder' in str(mail_pwd).lower() or app.config.get('TESTING'):
        return False, "Email skipped: MAIL_USERNAME or MAIL_PASSWORD not configured"

    import socket
    orig_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(4.0)
        sender_email = mail_user or 'noreply@bmserp.edu.in'
        msg = MailMessage(subject=subject, recipients=[user.email], html=body_html, sender=sender_email)
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as f:
                filename = os.path.basename(attachment_path)
                msg.attach(filename, 'application/pdf', f.read())
        mail.send(msg)
        return True, f"Email sent successfully to {user.email}"
    except Exception as e:
        return False, f"Email Dispatch Error: {str(e)}"
    finally:
        socket.setdefaulttimeout(orig_timeout)

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

    # Execute synchronously only for diagnostic self-test or explicit sync requests
    is_sync = (event == 'selftest') or context.get('sync', False)

    if not is_sync:
        import threading
        user_id = user.id
        user_name = user.full_name

        def _async_notify_worker():
            with app.app_context():
                target_user = User.query.get(user_id)
                if not target_user:
                    return
                for ch in target_channels:
                    success = False
                    detail = ""
                    if ch == 'email':
                        success, detail = _send_email_notification(target_user, subject, email_body, attachment_path)
                    elif ch == 'whatsapp':
                        success, detail = _send_whatsapp_notification(target_user, wa_body)
                    elif ch == 'sms':
                        success, detail = _send_sms_notification(target_user, wa_body)
                    else:
                        success, detail = False, f"Unknown notification channel: {ch}"

                    status_str = "SENT" if success else ("FAILED" if "Error" in detail or "missing" in detail or "Sandbox" in detail else "SKIPPED")
                    try:
                        db.session.add(NotificationLog(
                            user_id=target_user.id,
                            event=event,
                            channel=ch,
                            status=status_str,
                            detail=detail
                        ))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

                    try:
                        log_action(f"Notification [{event}] via {ch}: {status_str} ({detail[:60]})", target=user_name)
                    except Exception:
                        pass

        threading.Thread(target=_async_notify_worker, daemon=True).start()
        return {ch: {"success": True, "status": "QUEUED", "detail": "Dispatched in background"} for ch in target_channels}

    # Synchronous path (for selftest or explicit sync requests)
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


def dispatch_notification(user, event, context=None):
    """Unified dispatcher for User or Student notifications."""
    try:
        route_info = NOTIFICATION_ROUTING_MAP.get(event, {})
        subj_tmpl = route_info.get('subject', 'BMS College ERP Notification')
        subject = subj_tmpl(user, context or {}) if callable(subj_tmpl) else subj_tmpl
        email_tmpl = route_info.get('email_body')
        body = email_tmpl(user, context or {}) if callable(email_tmpl) else f"<p>{event}</p>"
        _send_email_notification(user, subject, body)
    except Exception as e:
        app.logger.warning(f"Notification dispatch skipped: {e}")

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
                    create_notification(
                        recipient_type='USER',
                        recipient_id=user.id,
                        title="Security Alert: New Sign-In",
                        message=f"New sign-in detected from {user_agent[:40]} (IP: {client_ip}).",
                        category='security',
                        action_url=url_for('my_profile'),
                        idempotency_key=f"login_dev_{user.id}_{device_hash}",
                        sound=True
                    )
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


# ==============================================================================
# NATIVE MOBILE APP API GATEWAY — MILESTONE 1 AUTH & DASHBOARD
# ==============================================================================

@app.route('/api/auth/staff-login', methods=['POST'])
def api_staff_login():
    data = request.get_json(silent=True) or request.form
    identifier = (data.get('username') or data.get('email') or '').strip()
    password = (data.get('password') or '').strip()

    if not identifier or not password:
        return jsonify({'success': False, 'error': 'Username and password are required.'}), 400

    user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'success': False, 'error': 'Invalid Username or Password.'}), 401

    session['user_id'] = user.id
    session['role'] = user.role 
    session['name'] = user.full_name
    login_user(user)

    # Device tracking
    try:
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or '127.0.0.1').split(',')[0].strip()
        user_agent = request.headers.get('User-Agent', 'BmsErpAndroid/1.0')
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
    except Exception as dev_err:
        pass

    return jsonify({
        'success': True,
        'message': 'Staff authentication successful',
        'account_type': 'STAFF',
        'user': {
            'id': user.id,
            'username': user.username,
            'full_name': user.full_name,
            'email': user.email,
            'role': user.role,
            'department': user.department,
            'dept_id': user.dept_id,
            'status': user.status or 'Active'
        }
    }), 200


@app.route('/api/auth/student-login', methods=['POST'])
def api_student_login():
    data = request.get_json(silent=True) or request.form
    uucms_id = (data.get('uucms_id') or '').strip()
    password = (data.get('password') or '').strip()

    if not uucms_id or not password:
        return jsonify({'success': False, 'error': 'Official UUCMS ID and password are required.'}), 400

    student = Student.query.filter(
        func.lower(Student.uucms_id) == uucms_id.lower(),
        Student.is_active == True
    ).first()

    if not student:
        return jsonify({'success': False, 'error': 'Invalid or inactive UUCMS ID. Please verify your registration or contact the department.'}), 401

    is_authenticated = False
    if app.config.get('TESTING') and not password:
        is_authenticated = True
    elif password and student.check_password(password):
        is_authenticated = True

    if not is_authenticated:
        return jsonify({'success': False, 'error': 'Invalid password. Please check your credentials or contact the department.'}), 401

    session['student_id'] = student.id
    session['student_uucms_id'] = student.uucms_id
    session['student_name'] = student.name
    session['student_course'] = student.course
    session['student_semester'] = student.semester
    session['student_section'] = student.section
    session['name'] = student.name
    session['role'] = 'Student'

    return jsonify({
        'success': True,
        'message': 'Student authentication successful',
        'account_type': 'STUDENT',
        'student': {
            'id': student.id,
            'uucms_id': student.uucms_id,
            'name': student.name,
            'email': student.email,
            'course': student.course,
            'academic_year': student.academic_year,
            'semester': student.semester,
            'section': student.section,
            'role': 'Student'
        }
    }), 200


@app.route('/api/auth/me', methods=['GET'])
def api_auth_me():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if not user:
            session.clear()
            return jsonify({'authenticated': False, 'error': 'User not found'}), 401
        return jsonify({
            'authenticated': True,
            'account_type': 'STAFF',
            'user': {
                'id': user.id,
                'username': user.username,
                'full_name': user.full_name,
                'email': user.email,
                'role': user.role,
                'department': user.department,
                'dept_id': user.dept_id,
                'status': user.status or 'Active'
            }
        }), 200

    elif 'student_id' in session:
        student = Student.query.get(session['student_id'])
        if not student or not student.is_active:
            session.clear()
            return jsonify({'authenticated': False, 'error': 'Student not found or inactive'}), 401
        return jsonify({
            'authenticated': True,
            'account_type': 'STUDENT',
            'student': {
                'id': student.id,
                'uucms_id': student.uucms_id,
                'name': student.name,
                'email': student.email,
                'course': student.course,
                'academic_year': student.academic_year,
                'semester': student.semester,
                'section': student.section,
                'role': 'Student'
            }
        }), 200

    return jsonify({'authenticated': False, 'error': 'No active session'}), 401


@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    session.clear()
    try:
        logout_user()
    except Exception:
        pass
    return jsonify({'success': True, 'message': 'Logged out successfully'}), 200


@app.route('/api/dashboard/summary', methods=['GET'])
def api_dashboard_summary():
    if 'student_id' in session:
        student = Student.query.get(session['student_id'])
        if not student:
            return jsonify({'error': 'Student not found'}), 404

        analytics = get_student_academic_analytics_profile(student, viewing_user=None)

        today_name = get_ist_time().strftime('%A')
        today_classes = Timetable.query.filter_by(
            course=student.course,
            semester=student.semester,
            day=today_name
        ).filter(
            Timetable.section.in_([student.section, 'ALL', 'A'])
        ).order_by(Timetable.time_slot.asc()).all()

        schedule_items = []
        for c in today_classes:
            teacher = User.query.get(c.user_id) if c.user_id else None
            schedule_items.append({
                'id': c.id,
                'subject': c.subject,
                'time_slot': c.time_slot,
                'room_no': c.room_no or 'Room 204',
                'faculty': teacher.full_name if teacher else 'Assigned Faculty'
            })

        return jsonify({
            'account_type': 'STUDENT',
            'role': 'Student',
            'name': student.name,
            'uucms_id': student.uucms_id,
            'course': student.course,
            'semester': student.semester,
            'section': student.section,
            'overall_attendance_pct': analytics.get('overall_attendance_pct', 0.0),
            'conducted': analytics.get('conducted_count', 0),
            'attended': analytics.get('attended_count', 0),
            'missed': analytics.get('total_missed', 0),
            'subjects_below_75': analytics.get('subjects_below_75_count', 0),
            'risk_level': analytics.get('overall_status', 'NORMAL') if isinstance(analytics.get('overall_status'), str) else (analytics.get('overall_status', {}).get('label', 'NORMAL') if isinstance(analytics.get('overall_status'), dict) else 'NORMAL'),
            'today_classes_count': len(schedule_items),
            'today_classes': schedule_items
        }), 200

    elif 'user_id' in session:
        user = User.query.get(session['user_id'])
        if not user:
            return jsonify({'error': 'User not found'}), 404

        today_name = get_ist_time().strftime('%A')

        if user.role in ['Faculty', 'teacher']:
            today_classes = Timetable.query.filter_by(
                user_id=user.id,
                day=today_name
            ).order_by(Timetable.time_slot.asc()).all()

            classes_data = [{
                'id': c.id,
                'subject': c.subject,
                'time_slot': c.time_slot,
                'course': c.course,
                'semester': c.semester,
                'section': c.section,
                'room_no': c.room_no or '101'
            } for c in today_classes]

            active_asgns = Assignment.query.filter_by(
                created_by_id=user.id,
                status='Published'
            ).count()

            today_str = get_ist_time().strftime("%Y-%m-%d")
            att = Attendance.query.filter_by(user_id=user.id, date=today_str).first()
            att_status = {
                'clocked_in': att is not None and att.check_in is not None,
                'check_in': att.check_in if att else None,
                'check_out': att.check_out if att else None,
                'location_status': att.location_status if att else None
            }

            return jsonify({
                'account_type': 'STAFF',
                'role': user.role,
                'name': user.full_name,
                'department': user.department,
                'dept_id': user.dept_id,
                'today_classes': classes_data,
                'today_classes_count': len(classes_data),
                'active_assignments_count': active_asgns,
                'attendance_status': att_status
            }), 200

        else:
            total_students = Student.query.filter_by(is_active=True).count()
            total_staff = User.query.filter(User.status == 'Active').count()
            from campus_geofence import get_geofence_config
            geo_cfg = get_geofence_config()

            return jsonify({
                'account_type': 'STAFF',
                'role': user.role,
                'name': user.full_name,
                'department': user.department,
                'dept_id': user.dept_id,
                'total_students': total_students,
                'total_staff': total_staff,
                'campus_geofence_radius': geo_cfg.get('radius_meters', 150)
            }), 200

    return jsonify({'error': 'Unauthorized'}), 401


# ==============================================================================
# MOBILE API GATEWAY — PHASE 4: ACADEMIC MODULES AND GPS ATTENDANCE
# ==============================================================================

@app.route('/api/student/attendance-analytics', methods=['GET'])
def api_student_attendance_analytics():
    """
    Authoritative Student Attendance Analytics and 75% Recovery Predictor for logged-in student.
    Returns overall attendance metrics and subject-wise recovery feasibility projections.
    """
    if 'student_id' not in session:
        return jsonify({'error': 'Unauthorized. Student session required.'}), 401
    
    student = Student.query.get(session['student_id'])
    if not student or not student.is_active:
        return jsonify({'error': 'Student account inactive or not found.'}), 404

    profile_data = get_student_academic_analytics_profile(student, viewing_user=None)

    return jsonify({
        'student_id': student.id,
        'name': student.name,
        'uucms_id': student.uucms_id,
        'course': student.course,
        'semester': student.semester,
        'section': student.section,
        'overall_attendance_pct': profile_data.get('overall_attendance_pct'),
        'conducted_count': profile_data.get('conducted_count', 0),
        'attended_count': profile_data.get('attended_count', 0),
        'total_missed': profile_data.get('total_missed', 0),
        'overall_status': profile_data.get('overall_status', 'PENDING'),
        'overall_classes_needed': profile_data.get('overall_classes_needed', 0),
        'subjects_below_75_count': profile_data.get('subjects_below_75_count', 0),
        'subjects_at_or_above_75_count': profile_data.get('subjects_at_or_above_75_count', 0),
        'subjects_recoverable_count': profile_data.get('subjects_recoverable_count', 0),
        'subjects_impossible_count': profile_data.get('subjects_impossible_count', 0),
        'subject_cards': profile_data.get('client_subject_cards', []),
        'calculation_timestamp': profile_data.get('calculation_timestamp')
    }), 200


@app.route('/api/attendance/status', methods=['GET'])
def api_attendance_status():
    """
    Returns today's clock-in / clock-out status and authoritative campus geofence configuration.
    Restricted to staff and faculty.
    """
    if 'student_id' in session:
        return jsonify({'error': 'Access Denied: Staff attendance portal is restricted to employees.'}), 403
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized. Staff session required.'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found.'}), 404

    today = get_ist_time().strftime("%Y-%m-%d")
    att = Attendance.query.filter_by(user_id=user.id, date=today).first()
    from campus_geofence import get_geofence_config
    cfg = get_geofence_config()

    return jsonify({
        'date': today,
        'user_id': user.id,
        'user_name': user.full_name,
        'has_clocked_in': att is not None and att.check_in is not None,
        'check_in_time': att.check_in if att else None,
        'has_clocked_out': att is not None and att.check_out is not None,
        'check_out_time': att.check_out if att else None,
        'work_mode': att.work_mode if att else 'Office',
        'location_status': att.location_status if att else None,
        'geofence_config': {
            'enabled': cfg.get('enabled', True),
            'center_lat': cfg.get('center_lat', 12.9515),
            'center_lon': cfg.get('center_lon', 77.5762),
            'radius_meters': cfg.get('radius_meters', 150.0),
            'max_accuracy_meters': cfg.get('max_accuracy_meters', 50.0),
            'max_age_seconds': cfg.get('max_age_seconds', 120),
            'boundary_buffer_meters': cfg.get('boundary_buffer_meters', 10.0)
        }
    }), 200


@app.route('/api/student/timetable', methods=['GET'])
def api_student_timetable():
    """
    Retrieves current published semester timetable for the logged-in student's cohort.
    Strictly isolated by course, academic_year, semester, and section.
    """
    if 'student_id' not in session:
        return jsonify({'error': 'Unauthorized. Student session required.'}), 401

    student = Student.query.get(session['student_id'])
    if not student or not student.is_active:
        return jsonify({'error': 'Student account inactive or not found.'}), 404

    course = student.course
    academic_year = student.academic_year
    semester = student.semester
    section = student.section or 'A'

    timetable = StudentSemesterTimetable.query.filter(
        StudentSemesterTimetable.course == course,
        StudentSemesterTimetable.academic_year == academic_year,
        StudentSemesterTimetable.semester == semester,
        StudentSemesterTimetable.section.in_([section, 'ALL']),
        StudentSemesterTimetable.status == 'PUBLISHED'
    ).order_by(
        db.case((StudentSemesterTimetable.section == section, 1), else_=2),
        StudentSemesterTimetable.version.desc()
    ).first()

    if not timetable:
        return jsonify({
            'has_timetable': False,
            'message': f'No published timetable available for {course} Semester {semester} Section {section}.',
            'course': course,
            'semester': semester,
            'section': section
        }), 200

    return jsonify({
        'has_timetable': True,
        'timetable': {
            'id': timetable.id,
            'title': timetable.title,
            'course': timetable.course,
            'academic_year': timetable.academic_year,
            'semester': timetable.semester,
            'section': timetable.section,
            'version': timetable.version,
            'file_filename': timetable.file_filename,
            'file_size_bytes': timetable.file_size,
            'file_mimetype': timetable.file_mimetype,
            'uploaded_at': timetable.created_at.strftime('%Y-%m-%d %H:%M') if timetable.created_at else None,
            'download_url': f'/academic/student-timetables/{timetable.id}/download',
            'view_url': f'/academic/student-timetables/{timetable.id}/view'
        }
    }), 200


@app.route('/api/student/study-materials', methods=['GET'])
def api_student_study_materials():
    """
    Retrieves published study materials strictly isolated to the logged-in student's academic cohort.
    Supports filtering by category, subject, and search query.
    """
    if 'student_id' not in session:
        return jsonify({'error': 'Unauthorized. Student session required.'}), 401

    student = Student.query.get(session['student_id'])
    if not student or not student.is_active:
        return jsonify({'error': 'Student account inactive or not found.'}), 404

    category = (request.args.get('category') or 'Textbooks').strip()
    if category not in VALID_STUDY_MATERIAL_CATEGORIES:
        category = 'Textbooks'

    subject = (request.args.get('subject') or '').strip()
    search = (request.args.get('search') or '').strip()

    query = StudyMaterial.query.filter(
        StudyMaterial.course == student.course,
        StudyMaterial.academic_year == student.academic_year,
        StudyMaterial.semester == student.semester,
        StudyMaterial.section.in_([student.section, 'ALL']),
        StudyMaterial.category == category,
        StudyMaterial.status == 'Published'
    )

    if subject:
        query = query.filter(StudyMaterial.subject == subject)
    if search:
        search_pat = f"%{search}%"
        query = query.filter(
            (StudyMaterial.title.ilike(search_pat)) |
            (StudyMaterial.description.ilike(search_pat)) |
            (StudyMaterial.tags.ilike(search_pat))
        )

    materials = query.order_by(StudyMaterial.created_at.desc()).all()

    class_subjects = [
        r[0] for r in db.session.query(Timetable.subject).filter_by(
            course=student.course,
            semester=student.semester,
            section=student.section
        ).distinct().all() if r[0]
    ]

    materials_list = []
    for m in materials:
        materials_list.append({
            'id': m.id,
            'title': m.title,
            'subject': m.subject,
            'category': m.category,
            'description': m.description,
            'file_filename': m.file_filename,
            'file_size_bytes': m.file_size,
            'file_mimetype': m.file_mimetype,
            'created_at': m.created_at.strftime('%Y-%m-%d') if m.created_at else None,
            'download_url': f'/academic/study-materials/{m.id}/download',
            'preview_url': f'/academic/study-materials/{m.id}/preview'
        })

    return jsonify({
        'current_category': category,
        'categories': VALID_STUDY_MATERIAL_CATEGORIES,
        'materials_count': len(materials_list),
        'materials': materials_list,
        'available_subjects': sorted(class_subjects)
    }), 200


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
        return redirect(url_for('dashboard')), 403
    
    # Fetch all logs, newest first
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    return render_template('audit_logs.html', logs=logs)

@app.route('/clear_audit_logs', methods=['POST'])
def clear_audit_logs():
    # SECURITY: Only allow Principal to purge the records
    if session.get('role') != 'Principal':
        flash("Access Denied: You do not have permission to purge system logs.", "error")
        return redirect(url_for('dashboard')), 403

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

    # 4. TODAY'S CLASSES & ACADEMIC ATTENDANCE
    today_date = get_ist_time().date()
    today_day_name = get_ist_time().strftime('%A')
    
    today_entries = Timetable.query.filter_by(user_id=view_id, day=today_day_name).order_by(Timetable.time_slot).all()
    today_classes = []
    for entry in today_entries:
        existing_session = ClassSession.query.filter_by(timetable_id=entry.id, date=today_date).first()
        present_cnt = 0
        absent_cnt = 0
        if existing_session:
            present_cnt = StudentAttendance.query.filter_by(class_session_id=existing_session.id, status='Present').count()
            absent_cnt = StudentAttendance.query.filter_by(class_session_id=existing_session.id, status='Absent').count()
        today_classes.append({
            'entry': entry,
            'session': existing_session,
            'present_count': present_cnt,
            'absent_count': absent_cnt
        })

    for entry in timetable_entries:
        entry.today_session = ClassSession.query.filter_by(timetable_id=entry.id, date=today_date).first()

    return render_template('timetable.html', 
                           user=user,
                           target_user=target_user,
                           timetable=timetable_entries, 
                           staff_list=staff_list,
                           free_slots=free_slots,
                           today_classes=today_classes,
                           today_date=today_date,
                           today_day_name=today_day_name,
                           chart_data=[held_count, missed_count, pending_count])

@app.route('/timetable/overview', methods=['GET'])
@login_required
def timetable_overview():
    user = current_user if (hasattr(current_user, 'is_authenticated') and current_user.is_authenticated) else User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    # Strict Admin Exclusion: Return 403 Forbidden
    if user.username == 'admin' or user.role == 'admin':
        abort(403)

    # Exclude non-academic staff (Accountant, Clerk) and students
    if user.role in ['Accountant', 'Clerk']:
        abort(403)

    available_semesters = ['Sem I', 'Sem II', 'Sem III', 'Sem IV', 'Sem V', 'Sem VI']
    try:
        db_sems = [r[0] for r in db.session.query(Timetable.semester).distinct().all() if r[0]]
        for s in db_sems:
            if s not in available_semesters:
                available_semesters.append(s)
    except Exception:
        pass

    selected_semester = request.args.get('semester', 'Sem V')
    if selected_semester:
        selected_semester = selected_semester.strip()
    if not selected_semester or selected_semester not in available_semesters:
        selected_semester = 'Sem V'

    # Fetch timetable entries for selected semester
    semester_entries = Timetable.query.filter_by(semester=selected_semester).all()

    # Organize entries by day
    timetable_by_day = {
        'Monday': [],
        'Tuesday': [],
        'Wednesday': [],
        'Thursday': [],
        'Friday': [],
        'Saturday': []
    }
    for entry in semester_entries:
        if entry.day in timetable_by_day:
            timetable_by_day[entry.day].append(entry)

    # Sort entries by start time for consistent display
    for day in timetable_by_day:
        timetable_by_day[day].sort(key=lambda e: _parse_slot_minutes(e.time_slot)[0])

    # Faculty teaching allocations for selected semester
    faculty_allocations = {}
    for entry in semester_entries:
        fac_name = entry.faculty.full_name if (entry.faculty and entry.faculty.full_name) else 'Department Faculty'
        if fac_name not in faculty_allocations:
            faculty_allocations[fac_name] = {
                'faculty': entry.faculty,
                'subjects': set(),
                'rooms': set(),
                'slot_count': 0
            }
        faculty_allocations[fac_name]['subjects'].add(entry.subject)
        if entry.room_no:
            faculty_allocations[fac_name]['rooms'].add(f'Room {entry.room_no}')
        faculty_allocations[fac_name]['slot_count'] += 1

    return render_template(
        'timetable_overview.html',
        user=user,
        timetable_by_day=timetable_by_day,
        sem5_entries=semester_entries,  # Backwards compatibility
        semester_entries=semester_entries,
        selected_semester=selected_semester,
        available_semesters=available_semesters,
        faculty_allocations=faculty_allocations,
        total_slots=len(semester_entries)
    )


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

# ==========================================
# 3B. STUDENT ACADEMIC ATTENDANCE WORKFLOW
# ==========================================

def _dispatch_absence_emails_async(absent_students, session_info, faculty_info):
    """Dispatches personalized absence notification emails asynchronously in a background daemon thread."""
    def _worker():
        with app.app_context():
            mail_user = app.config.get('MAIL_USERNAME')
            mail_pwd = app.config.get('MAIL_PASSWORD')
            has_creds = bool(mail_user and mail_pwd and 'your_' not in str(mail_pwd).lower() and 'placeholder' not in str(mail_pwd).lower() and not app.config.get('TESTING'))

            for s_info in absent_students:
                s_email = s_info.get('email')
                s_name = s_info.get('name')
                s_uucms = s_info.get('uucms_id')

                if not s_email or '@' not in s_email:
                    continue

                subject = f"Attendance Notification - BMS College ({session_info.get('actual_subject')})"
                body_html = (
                    f"<h3>Attendance Notification — BMS College</h3>"
                    f"<p>Dear <strong>{s_name}</strong> ({s_uucms}),</p>"
                    f"<p>This is to inform you that you were marked <strong>ABSENT</strong> for the following scheduled academic session:</p>"
                    f"<ul>"
                    f"<li><strong>Course:</strong> {session_info.get('course')}</li>"
                    f"<li><strong>Semester:</strong> {session_info.get('semester')}</li>"
                    f"<li><strong>Section:</strong> {session_info.get('section')}</li>"
                    f"<li><strong>Subject:</strong> {session_info.get('actual_subject')}</li>"
                    f"<li><strong>Date:</strong> {session_info.get('date_str')}</li>"
                    f"<li><strong>Time Slot:</strong> {session_info.get('time_slot')}</li>"
                    f"<li><strong>Room:</strong> {session_info.get('room_no')}</li>"
                    f"<li><strong>Faculty:</strong> {faculty_info.get('full_name')}</li>"
                    f"</ul>"
                    f"<p>If you believe this attendance record is incorrect, please contact the concerned faculty member promptly.</p>"
                    f"<p>Regards,<br><strong>BMS College ERP Academic Cell</strong></p>"
                )

                sent_success = False
                detail_msg = ""
                if has_creds:
                    import socket
                    orig_timeout = socket.getdefaulttimeout()
                    try:
                        socket.setdefaulttimeout(4.0)
                        msg = MailMessage(subject=subject, recipients=[s_email], html=body_html, sender=mail_user)
                        mail.send(msg)
                        sent_success = True
                        detail_msg = f"Absence email delivered successfully to {s_email}"
                    except Exception as err:
                        sent_success = False
                        detail_msg = f"Email Dispatch Error: {str(err)}"
                    finally:
                        socket.setdefaulttimeout(orig_timeout)
                else:
                    sent_success = False
                    detail_msg = "Email skipped: MAIL_USERNAME or MAIL_PASSWORD not configured (or test mode)"

                status_str = "SENT" if sent_success else ("SKIPPED" if "skipped" in detail_msg else "FAILED")
                try:
                    db.session.add(NotificationLog(
                        user_id=faculty_info.get('id'),
                        event='student_absence_notification',
                        channel='email',
                        status=status_str,
                        detail=f"Student: {s_name} ({s_uucms}, {s_email}) | {detail_msg}"
                    ))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

    import threading
    threading.Thread(target=_worker, daemon=True).start()

@app.route('/academic-attendance/take/<int:timetable_id>', methods=['GET', 'POST'])
@login_required
def take_academic_attendance(timetable_id):
    user = User.query.get(session['user_id'])
    timetable_entry = Timetable.query.get_or_404(timetable_id)

    # Server-Side RBAC Authorization Check
    is_authorized = (
        timetable_entry.user_id == user.id or
        user.role in ['Principal', 'HOD - BCA Dept', 'admin']
    )
    if not is_authorized:
        flash('You are not authorized to take attendance for this class.', 'danger')
        return redirect(url_for('view_timetable')), 403

    today_date = get_ist_time().date()

    # Duplicate check: Check if attendance already recorded today for this timetable entry
    existing_session = ClassSession.query.filter_by(timetable_id=timetable_entry.id, date=today_date).first()

    if request.method == 'POST':
        if existing_session:
            flash('Attendance has already been submitted for this class today.', 'warning')
            return redirect(url_for('view_class_session', session_id=existing_session.id))

        actual_subject = (request.form.get('actual_subject') or timetable_entry.subject).strip()
        remarks = (request.form.get('remarks') or '').strip()

        # Database Transaction
        try:
            session_record = ClassSession(
                timetable_id=timetable_entry.id,
                date=today_date,
                time_slot=timetable_entry.time_slot,
                course=timetable_entry.course,
                academic_year='3rd Year',
                semester=timetable_entry.semester,
                section=timetable_entry.section,
                scheduled_subject=timetable_entry.subject,
                actual_subject=actual_subject,
                scheduled_faculty_id=timetable_entry.user_id,
                actual_faculty_id=user.id,
                room_no=timetable_entry.room_no,
                status='COMPLETED',
                remarks=remarks
            )
            db.session.add(session_record)
            db.session.flush()

            # Server-side validation of student roster
            class_students = {
                s.id: s for s in Student.query.filter_by(
                    course=timetable_entry.course,
                    semester=timetable_entry.semester,
                    section=timetable_entry.section,
                    is_active=True
                ).all()
            }

            present_count = 0
            absent_students = []

            submitted_ids = request.form.getlist('student_ids')
            for sid_str in submitted_ids:
                try:
                    sid = int(sid_str)
                except (ValueError, TypeError):
                    continue

                if sid not in class_students:
                    continue

                student = class_students[sid]
                status = request.form.get(f'status_{sid}', 'Present')
                if status not in ['Present', 'Absent']:
                    status = 'Present'

                att = StudentAttendance(
                    class_session_id=session_record.id,
                    student_id=student.id,
                    status=status,
                    marked_at=get_ist_time().replace(tzinfo=None),
                    marked_by=user.id
                )
                db.session.add(att)

                if status == 'Present':
                    present_count += 1
                else:
                    absent_students.append(student)

            # Update timetable entry status
            timetable_entry.status = 'held'

            # COMMIT TRANSACTION
            db.session.commit()
            log_action(f"Academic attendance submission: teacher={user.id} session={session_record.id} class={session_record.course} {session_record.semester} {session_record.section} present={present_count} absent={len(absent_students)}", target=user.full_name)
        except Exception as db_err:
            db.session.rollback()
            flash(f"Database persistence error: {str(db_err)}", "danger")
            return redirect(url_for('take_academic_attendance', timetable_id=timetable_id))

        # AFTER COMMIT: Dispatch in-app notifications and absence emails
        if absent_students:
            for s in absent_students:
                try:
                    create_notification(
                        recipient_type='STUDENT',
                        recipient_id=s.id,
                        title=f"Absence Notice: {session_record.actual_subject}",
                        message=f"You were marked ABSENT for {session_record.actual_subject} on {session_record.date.strftime('%d %b %Y')} ({session_record.time_slot}).",
                        category='attendance',
                        action_url=url_for('student_marks'),
                        idempotency_key=f"att_abs_{session_record.id}_{s.id}",
                        sound=True
                    )
                except Exception as notif_err:
                    pass
            _dispatch_absence_emails_async(
                absent_students=[{'id': s.id, 'name': s.name, 'email': s.email, 'uucms_id': s.uucms_id} for s in absent_students],
                session_info={
                    'course': session_record.course,
                    'semester': session_record.semester,
                    'section': session_record.section,
                    'actual_subject': session_record.actual_subject,
                    'scheduled_subject': session_record.scheduled_subject,
                    'date_str': session_record.date.strftime("%d %B %Y"),
                    'time_slot': session_record.time_slot,
                    'room_no': session_record.room_no
                },
                faculty_info={'id': user.id, 'full_name': user.full_name}
            )

        flash(f"Attendance submitted successfully. {present_count + len(absent_students)} students processed. {present_count} Present, {len(absent_students)} Absent. Absence notification processing started.", "success")
        return redirect(url_for('view_class_session', session_id=session_record.id))

    # GET Request: If already taken today, redirect to session view
    if existing_session:
        flash('Attendance has already been submitted for this class today. You can view or modify the records below.', 'info')
        return redirect(url_for('view_class_session', session_id=existing_session.id))

    # Load active student roster matching class
    students = Student.query.filter_by(
        course=timetable_entry.course,
        semester=timetable_entry.semester,
        section=timetable_entry.section,
        is_active=True
    ).order_by(Student.uucms_id).all()

    return render_template(
        'take_attendance.html',
        user=user,
        timetable_entry=timetable_entry,
        students=students,
        today_date=today_date
    )

@app.route('/academic-attendance/session/<int:session_id>', methods=['GET'])
@login_required
def view_class_session(session_id):
    user = User.query.get(session['user_id'])
    session_obj = ClassSession.query.get_or_404(session_id)

    # Authorization Check
    if user.role not in ['Principal', 'HOD - BCA Dept', 'admin']:
        if session_obj.actual_faculty_id != user.id and session_obj.scheduled_faculty_id != user.id:
            flash('Unauthorized access to session details.', 'danger')
            return redirect(url_for('view_timetable')), 403

    attendances = StudentAttendance.query.filter_by(class_session_id=session_obj.id).join(Student).order_by(Student.uucms_id).all()
    total_count = len(attendances)
    present_count = sum(1 for a in attendances if a.status == 'Present')
    absent_count = sum(1 for a in attendances if a.status == 'Absent')

    audit_logs = StudentAttendanceAudit.query.filter_by(class_session_id=session_obj.id).order_by(StudentAttendanceAudit.created_at.desc()).all()

    return render_template(
        'class_session_view.html',
        user=user,
        session_obj=session_obj,
        attendances=attendances,
        total_count=total_count,
        present_count=present_count,
        absent_count=absent_count,
        audit_logs=audit_logs
    )

@app.route('/academic-attendance/edit/<int:session_id>', methods=['GET', 'POST'])
@login_required
def edit_academic_attendance(session_id):
    user = User.query.get(session['user_id'])
    session_obj = ClassSession.query.get_or_404(session_id)

    # Authorization Check: only the faculty who conducted the class, scheduled faculty, or Admin/HOD/Principal
    is_authorized = (
        user.role in ['Principal', 'HOD - BCA Dept', 'admin'] or
        session_obj.actual_faculty_id == user.id or
        session_obj.scheduled_faculty_id == user.id
    )
    if not is_authorized:
        flash('You are not authorized to modify attendance for this class session.', 'danger')
        return redirect(url_for('view_class_session', session_id=session_id)), 403

    if request.method == 'POST':
        # Optimistic concurrency check
        submitted_version = request.form.get('version', type=int)
        current_version = getattr(session_obj, 'version', 1) or 1
        if submitted_version is not None and current_version != submitted_version:
            flash('Concurrency Conflict: This attendance record was modified by another user while you were editing. Please review the updated records before making changes.', 'warning')
            return redirect(url_for('edit_academic_attendance', session_id=session_id))

        actual_subject = (request.form.get('actual_subject') or session_obj.scheduled_subject).strip()
        remarks = (request.form.get('remarks') or '').strip()
        reason = (request.form.get('reason') or '').strip()

        # Fetch current attendance records for this session
        existing_attendances = {
            a.student_id: a for a in StudentAttendance.query.filter_by(class_session_id=session_obj.id).all()
        }

        # Verify class student roster
        class_students = {
            s.id: s for s in Student.query.filter_by(
                course=session_obj.course,
                semester=session_obj.semester,
                section=session_obj.section,
                is_active=True
            ).all()
        }

        # Compare submitted statuses against saved records
        status_changes = []
        newly_absent_students = []
        submitted_ids = request.form.getlist('student_ids')
        for sid_str in submitted_ids:
            try:
                sid = int(sid_str)
            except (ValueError, TypeError):
                continue

            if sid not in class_students:
                continue

            student = class_students[sid]
            new_status = request.form.get(f'status_{sid}', 'Present')
            if new_status not in ['Present', 'Absent']:
                new_status = 'Present'

            att = existing_attendances.get(sid)
            old_status = att.status if att else 'Present'
            if old_status != new_status:
                status_changes.append({
                    'student': student,
                    'att': att,
                    'old_status': old_status,
                    'new_status': new_status
                })
                if old_status == 'Present' and new_status == 'Absent':
                    newly_absent_students.append(student)

        subject_changed = (actual_subject != session_obj.actual_subject)
        remarks_changed = (remarks != (session_obj.remarks or ''))

        # Validation: If any changes are made, a meaningful correction reason is mandatory!
        if (status_changes or subject_changed or remarks_changed) and not reason:
            flash('A meaningful correction reason is required whenever attendance statuses or session details are modified.', 'danger')
            return redirect(url_for('edit_academic_attendance', session_id=session_id))

        # If zero changes detected:
        if not status_changes and not subject_changed and not remarks_changed:
            flash('No changes detected. The attendance record remains unchanged.', 'info')
            return redirect(url_for('view_class_session', session_id=session_id))

        # Perform atomic database updates and write audit records
        try:
            if subject_changed:
                audit_subj = StudentAttendanceAudit(
                    class_session_id=session_obj.id,
                    changed_by=user.id,
                    field_name='actual_subject',
                    previous_value=session_obj.actual_subject,
                    new_value=actual_subject,
                    reason=reason
                )
                db.session.add(audit_subj)
                session_obj.actual_subject = actual_subject

            if remarks_changed:
                audit_rem = StudentAttendanceAudit(
                    class_session_id=session_obj.id,
                    changed_by=user.id,
                    field_name='remarks',
                    previous_value=session_obj.remarks or '',
                    new_value=remarks,
                    reason=reason
                )
                db.session.add(audit_rem)
                session_obj.remarks = remarks

            # Update student attendance records
            for ch in status_changes:
                att = ch['att']
                student = ch['student']
                old_status = ch['old_status']
                new_status = ch['new_status']

                if att:
                    att.status = new_status
                    att.marked_at = get_ist_time().replace(tzinfo=None)
                    att.marked_by = user.id
                    att_id = att.id
                else:
                    att = StudentAttendance(
                        class_session_id=session_obj.id,
                        student_id=student.id,
                        status=new_status,
                        marked_at=get_ist_time().replace(tzinfo=None),
                        marked_by=user.id
                    )
                    db.session.add(att)
                    db.session.flush()
                    att_id = att.id

                # Mandatory Audit Trail Entry
                audit_entry = StudentAttendanceAudit(
                    class_session_id=session_obj.id,
                    student_attendance_id=att_id,
                    student_id=student.id,
                    changed_by=user.id,
                    field_name='status',
                    previous_value=old_status,
                    new_value=new_status,
                    reason=reason
                )
                db.session.add(audit_entry)

            session_obj.version = current_version + 1
            session_obj.updated_at = get_ist_time().replace(tzinfo=None)

            db.session.commit()
            log_action(f"Academic attendance edited: user={user.id} session={session_obj.id} changed={len(status_changes)} reason='{reason}'", target=user.full_name)
        except Exception as db_err:
            db.session.rollback()
            flash(f"Database error during attendance correction: {str(db_err)}", "danger")
            return redirect(url_for('edit_academic_attendance', session_id=session_id))

        # Post-commit In-App Notifications for corrected attendance
        for ch in status_changes:
            try:
                st = ch['student']
                create_notification(
                    recipient_type='STUDENT',
                    recipient_id=st.id,
                    title=f"Attendance Corrected: {session_obj.actual_subject}",
                    message=f"Your attendance for {session_obj.actual_subject} on {session_obj.date.strftime('%d %b %Y')} was corrected to {ch['new_status']} (Reason: {reason}).",
                    category='attendance',
                    action_url=url_for('student_marks'),
                    idempotency_key=f"att_corr_{session_obj.id}_{st.id}_{ch['new_status']}",
                    sound=True
                )
            except Exception:
                pass

        # Post-commit Notification Policy:
        # Only notify students whose status changed from Present -> Absent.
        # Do not resend emails for students unchanged or changed to Present.
        if newly_absent_students:
            _dispatch_absence_emails_async(
                absent_students=[{'id': s.id, 'name': s.name, 'email': s.email, 'uucms_id': s.uucms_id} for s in newly_absent_students],
                session_info={
                    'course': session_obj.course,
                    'semester': session_obj.semester,
                    'section': session_obj.section,
                    'actual_subject': session_obj.actual_subject,
                    'scheduled_subject': session_obj.scheduled_subject,
                    'date_str': session_obj.date.strftime("%d %B %Y"),
                    'time_slot': session_obj.time_slot,
                    'room_no': session_obj.room_no
                },
                faculty_info={'id': user.id, 'full_name': user.full_name}
            )

        flash(f"Attendance for Session #{session_obj.id} updated successfully! {len(status_changes)} student record(s) corrected. Audit log recorded.", "success")
        return redirect(url_for('view_class_session', session_id=session_obj.id))

    # GET Request: Prepare roster with current recorded attendance
    existing_attendances = {
        a.student_id: a for a in StudentAttendance.query.filter_by(class_session_id=session_obj.id).all()
    }

    students = Student.query.filter_by(
        course=session_obj.course,
        semester=session_obj.semester,
        section=session_obj.section,
        is_active=True
    ).order_by(Student.uucms_id).all()

    student_records = []
    present_count = 0
    absent_count = 0
    for s in students:
        att = existing_attendances.get(s.id)
        cur_status = att.status if att else 'Present'
        if cur_status == 'Present':
            present_count += 1
        else:
            absent_count += 1
        student_records.append({
            'student': s,
            'status': cur_status,
            'marked_at': att.marked_at if att else None
        })

    return render_template(
        'edit_attendance.html',
        user=user,
        session_obj=session_obj,
        student_records=student_records,
        total_students=len(student_records),
        present_count=present_count,
        absent_count=absent_count
    )

@app.route('/academic-attendance/history', methods=['GET'])
@login_required
def academic_attendance_history():
    if 'student_id' in session:
        flash('Access Denied: Academic attendance is restricted to staff.', 'danger')
        return redirect(url_for('student_attendance_view')), 403

    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Access Denied: Academic attendance is restricted to teaching faculty and administration.', 'danger')
        return redirect(url_for('dashboard')), 403

    is_management = user.role in ['Principal', 'HOD - BCA Dept', 'admin']

    query = ClassSession.query

    # RBAC Authorization Filter
    if not is_management:
        query = query.filter(
            (ClassSession.actual_faculty_id == user.id) | (ClassSession.scheduled_faculty_id == user.id)
        )
    elif request.args.get('faculty_id'):
        try:
            f_id = int(request.args.get('faculty_id'))
            query = query.filter(
                (ClassSession.actual_faculty_id == f_id) | (ClassSession.scheduled_faculty_id == f_id)
            )
        except (ValueError, TypeError):
            pass

    # 1. Specific Date Filter
    filter_date_str = (request.args.get('date') or '').strip()
    if filter_date_str:
        try:
            filter_date = datetime.strptime(filter_date_str, '%Y-%m-%d').date()
            query = query.filter(ClassSession.date == filter_date)
        except ValueError:
            pass

    # 2. Date Range Filter
    start_date_str = (request.args.get('start_date') or '').strip()
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query = query.filter(ClassSession.date >= start_date)
        except ValueError:
            pass

    end_date_str = (request.args.get('end_date') or '').strip()
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            query = query.filter(ClassSession.date <= end_date)
        except ValueError:
            pass

    # 3. Month Filter (e.g., '2026-10' or '2026-02') - leap-year and calendar aware
    filter_month_str = (request.args.get('month') or '').strip()
    if filter_month_str:
        try:
            m_parts = filter_month_str.split('-')
            m_year, m_month = int(m_parts[0]), int(m_parts[1])
            _, last_day = calendar.monthrange(m_year, m_month)
            month_start = date(m_year, m_month, 1)
            month_end = date(m_year, m_month, last_day)
            query = query.filter(ClassSession.date >= month_start, ClassSession.date <= month_end)
        except Exception:
            pass

    # 4. Course, Semester, Section filters
    course_filter = (request.args.get('course') or '').strip()
    if course_filter:
        query = query.filter(ClassSession.course == course_filter)

    semester_filter = (request.args.get('semester') or '').strip()
    if semester_filter:
        query = query.filter(ClassSession.semester == semester_filter)

    section_filter = (request.args.get('section') or '').strip()
    if section_filter:
        query = query.filter(ClassSession.section == section_filter)

    # 5. Subject Search
    search_query = (request.args.get('search') or '').strip()
    if search_query:
        query = query.filter(
            db.or_(
                ClassSession.actual_subject.ilike(f'%{search_query}%'),
                ClassSession.scheduled_subject.ilike(f'%{search_query}%'),
                ClassSession.remarks.ilike(f'%{search_query}%')
            )
        )

    # Ordering
    query = query.order_by(ClassSession.date.desc(), ClassSession.created_at.desc())

    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    if per_page not in [10, 15, 25, 50]:
        per_page = 15

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    sessions_list = pagination.items

    session_records = []
    total_attendances = 0
    total_presents = 0

    for s in sessions_list:
        p_cnt = sum(1 for a in s.student_attendances if a.status == 'Present')
        a_cnt = sum(1 for a in s.student_attendances if a.status == 'Absent')
        total_attendances += (p_cnt + a_cnt)
        total_presents += p_cnt
        session_records.append({
            'session': s,
            'present_count': p_cnt,
            'absent_count': a_cnt,
            'total_count': p_cnt + a_cnt
        })

    avg_rate = round((total_presents / total_attendances * 100), 1) if total_attendances > 0 else 0.0

    faculty_list = User.query.filter(User.role.in_(['Faculty', 'HOD - BCA Dept'])).order_by(User.full_name).all() if is_management else []

    return render_template(
        'academic_attendance_history.html',
        user=user,
        session_records=session_records,
        pagination=pagination,
        total_sessions=pagination.total,
        total_attendances=total_attendances,
        avg_attendance_rate=avg_rate,
        is_management=is_management,
        faculty_list=faculty_list,
        filter_date=filter_date_str,
        filter_start_date=start_date_str,
        filter_end_date=end_date_str,
        filter_month=filter_month_str,
        filter_course=course_filter,
        filter_semester=semester_filter,
        filter_section=section_filter,
        filter_search=search_query,
        filter_faculty_id=request.args.get('faculty_id', '')
    )

@app.route('/academic-attendance/today', methods=['GET'])
@login_required
def academic_attendance_today():
    return redirect(url_for('view_timetable') + '#todays-classes')


# ==============================================================================
# FEATURE — STUDENT INTERNAL ASSESSMENT MARKS MANAGEMENT
# ==============================================================================

# Configurable assessment maxima (defaults to 20.0 each per BMS College policy)
DEFAULT_ASSESSMENT_MAXIMA = {
    'IA1': 20.0,
    'IA2': 20.0,
    'Final IA': 20.0
}

def get_assessment_maxima():
    return {
        'IA1': float(os.getenv('IA1_MAX_MARKS', DEFAULT_ASSESSMENT_MAXIMA['IA1'])),
        'IA2': float(os.getenv('IA2_MAX_MARKS', DEFAULT_ASSESSMENT_MAXIMA['IA2'])),
        'Final IA': float(os.getenv('FINAL_IA_MAX_MARKS', DEFAULT_ASSESSMENT_MAXIMA['Final IA']))
    }

def parse_and_validate_mark(raw_value, component_name, max_mark):
    if raw_value is None:
        return None, None
    raw_str = str(raw_value).strip()
    if raw_str == '':
        return None, None

    try:
        val = float(raw_str)
    except (ValueError, TypeError):
        return None, f"Invalid value for {component_name}: '{raw_str}' is not a valid number."

    if math.isnan(val) or math.isinf(val):
        return None, f"Invalid value for {component_name}: infinite or NaN numbers are prohibited."

    if val < 0.0:
        return None, f"Invalid value for {component_name}: marks cannot be negative ({val} entered)."

    if val > max_mark:
        return None, f"Invalid value for {component_name}: marks ({val}) exceed maximum allowed ({max_mark})."

    if '.' in raw_str:
        dec_part = raw_str.split('.')[1]
        if len(dec_part) > 2:
            return None, f"Invalid value for {component_name}: decimal precision cannot exceed 2 decimal places."

    return round(val, 2), None

VALID_STUDY_MATERIAL_CATEGORIES = ['Textbooks', 'Previous Year Papers', 'Question Banks']
VALID_COURSES = ['BCA', 'B.Com', 'BBA']
VALID_ACADEMIC_YEARS = ['1st Year', '2nd Year', '3rd Year']
VALID_SECTIONS = ['A', 'B', 'ALL']
VALID_ACADEMIC_YEAR_SEMESTERS = {
    '1st Year': ['Sem I', 'Sem II'],
    '2nd Year': ['Sem III', 'Sem IV'],
    '3rd Year': ['Sem V', 'Sem VI']
}
SEMESTER_TO_ACADEMIC_YEAR = {
    'Sem I': '1st Year',
    'Sem II': '1st Year',
    'Sem III': '2nd Year',
    'Sem IV': '2nd Year',
    'Sem V': '3rd Year',
    'Sem VI': '3rd Year'
}

def get_authorized_subject_contexts(user):
    if user.role in ['Principal', 'admin']:
        rows = db.session.query(
            Timetable.course,
            Timetable.semester,
            Timetable.section,
            Timetable.subject
        ).distinct().order_by(Timetable.course, Timetable.semester, Timetable.section, Timetable.subject).all()
    elif user.role == 'HOD - BCA Dept':
        rows = db.session.query(
            Timetable.course,
            Timetable.semester,
            Timetable.section,
            Timetable.subject
        ).filter(Timetable.course == 'BCA').distinct().order_by(Timetable.semester, Timetable.section, Timetable.subject).all()
    else:
        rows = db.session.query(
            Timetable.course,
            Timetable.semester,
            Timetable.section,
            Timetable.subject
        ).filter(Timetable.user_id == user.id).distinct().order_by(Timetable.semester, Timetable.section, Timetable.subject).all()

    contexts = []
    for c, sem, sec, subj in rows:
        contexts.append({
            'course': c or 'BCA',
            'academic_year': SEMESTER_TO_ACADEMIC_YEAR.get(sem, '3rd Year'),
            'semester': sem,
            'section': sec or 'A',
            'subject': subj
        })
    return contexts

def is_user_authorized_for_context(user, course, semester, section, subject):
    if not user:
        return False
    if user.role in ['Principal', 'admin']:
        return True
    if user.role == 'HOD - BCA Dept' and course == 'BCA':
        return True
    if user.role == 'Faculty':
        match = Timetable.query.filter_by(
            user_id=user.id,
            course=course,
            semester=semester,
            section=section,
            subject=subject
        ).first()
        return match is not None
    return False

def is_user_authorized_for_class(user, course, semester, section):
    """
    Checks if a user is authorized to view students/records for this class context.
    - Principal & admin: All classes
    - HOD - BCA Dept: BCA courses
    - Faculty: Classes where they teach at least one subject (via Timetable or ClassSession)
    """
    if not user:
        return False
    if user.role in ['Principal', 'admin']:
        return True
    if user.role == 'HOD - BCA Dept' and course == 'BCA':
        return True
    if user.role == 'Faculty':
        match = Timetable.query.filter_by(
            user_id=user.id,
            course=course,
            semester=semester,
            section=section
        ).first()
        if match:
            return True
        session_match = ClassSession.query.filter(
            (ClassSession.scheduled_faculty_id == user.id) | (ClassSession.actual_faculty_id == user.id),
            ClassSession.course == course,
            ClassSession.semester == semester,
            ClassSession.section == section
        ).first()
        return session_match is not None
    return False

def get_assessment_cutoff_date(course='BCA', semester='Sem V', section='A', subject=None, assessment_cycle='2026-27', component='IA1'):
    """
    Resolves the authoritative cutoff date for an assessment component.
    Hierarchy:
    1. Exact subject-level cutoff
    2. Class-level default cutoff (subject=None)
    3. Institutional default fallback for the cycle
    """
    if subject:
        specific = AssessmentCutoff.query.filter_by(
            course=course,
            semester=semester,
            section=section,
            subject=subject,
            assessment_cycle=assessment_cycle,
            component=component
        ).first()
        if specific:
            return specific.cutoff_date

    general = AssessmentCutoff.query.filter_by(
        course=course,
        semester=semester,
        section=section,
        subject=None,
        assessment_cycle=assessment_cycle,
        component=component
    ).first()
    if general:
        return general.cutoff_date

    defaults = {
        'IA1': date(2026, 10, 5),
        'IA2': date(2026, 11, 15),
        'Final IA': date(2026, 12, 10)
    }
    return defaults.get(component, date(2026, 12, 31))

def calculate_subject_attendance(student_id, subject, assessment_date, course='BCA', semester='Sem V', section='A'):
    """
    Calculates qualifying attendance up to the assessment_date cutoff.
    Rules:
    - Only finalized, actually conducted sessions (ClassSession.status == 'COMPLETED').
    - Date <= assessment_date.
    - Subject attribution: ClassSession.actual_subject == subject (or scheduled_subject fallback).
    - Class scope: course, semester, section match.
    - Attended: StudentAttendance.status == 'Present'.
    - Unheld/cancelled/future classes excluded.
    - 0 conducted classes -> explicit pending/unavailable status.
    """
    if isinstance(assessment_date, datetime):
        assessment_date = assessment_date.date()

    # Query completed class sessions on or before assessment_date
    sessions = ClassSession.query.filter(
        ClassSession.course == course,
        ClassSession.semester == semester,
        ClassSession.section == section,
        ClassSession.status == 'COMPLETED',
        ClassSession.date <= assessment_date
    ).all()

    # Filter for attributable subject (actual_subject takes precedence over scheduled_subject)
    matching_session_ids = [
        s.id for s in sessions
        if (s.actual_subject == subject if s.actual_subject else s.scheduled_subject == subject)
    ]

    conducted_count = len(matching_session_ids)
    if conducted_count == 0:
        return {
            'status': 'PENDING',
            'percentage': None,
            'attended': 0,
            'conducted': 0,
            'is_eligible': None,
            'message': 'No conducted sessions before assessment cutoff.'
        }

    # Query attendance records for this student across these sessions
    attendances = StudentAttendance.query.filter(
        StudentAttendance.class_session_id.in_(matching_session_ids),
        StudentAttendance.student_id == student_id
    ).all()

    # Avoid duplicate counting of sessions: unique session IDs marked Present
    attended_session_ids = {
        a.class_session_id for a in attendances
        if a.status == 'Present'
    }
    attended_count = len(attended_session_ids)

    percentage = round((attended_count * 100.0) / conducted_count, 2)
    is_eligible = (percentage >= 75.0)

    return {
        'status': 'ELIGIBLE' if is_eligible else 'RESTRICTED',
        'percentage': percentage,
        'attended': attended_count,
        'conducted': conducted_count,
        'is_eligible': is_eligible,
        'message': f'{percentage}% ({attended_count}/{conducted_count} sessions)'
    }

def evaluate_marks_eligibility(student_id, subject, component='IA1', assessment_cycle='2026-27', course='BCA', semester='Sem V', section='A'):
    """
    Evaluates student visibility for a specific subject and assessment component.
    1. Check for active HOD override (component-specific first, then 'ALL')
    2. If active override exists:
       - MANUAL_RESTRICT -> can_view=False, decision_source='HOD_MANUAL_RESTRICT'
       - ALLOW_OVERRIDE -> can_view=True, decision_source='HOD_ALLOW_OVERRIDE'
    3. If no active override (or revoked):
       - Evaluate automatic attendance up to assessment cutoff date:
         - PENDING (0 classes) -> can_view=False, decision_source='AUTOMATIC_PENDING'
         - < 75% -> can_view=False, decision_source='AUTOMATIC_RESTRICTED'
         - >= 75% -> can_view=True, decision_source='AUTOMATIC_ELIGIBLE'
    """
    cutoff_date = get_assessment_cutoff_date(
        course=course,
        semester=semester,
        section=section,
        subject=subject,
        assessment_cycle=assessment_cycle,
        component=component
    )

    att_res = calculate_subject_attendance(
        student_id=student_id,
        subject=subject,
        assessment_date=cutoff_date,
        course=course,
        semester=semester,
        section=section
    )

    override = MarksEligibilityOverride.query.filter(
        MarksEligibilityOverride.student_id == student_id,
        MarksEligibilityOverride.subject == subject,
        MarksEligibilityOverride.course == course,
        MarksEligibilityOverride.semester == semester,
        MarksEligibilityOverride.section == section,
        MarksEligibilityOverride.assessment_cycle == assessment_cycle,
        MarksEligibilityOverride.component.in_([component, 'ALL']),
        MarksEligibilityOverride.is_active == True
    ).order_by(
        db.case((MarksEligibilityOverride.component == component, 1), else_=2)
    ).first()

    if override:
        if override.decision_type == 'MANUAL_RESTRICT':
            return {
                'can_view': False,
                'decision_source': 'HOD_MANUAL_RESTRICT',
                'status': 'RESTRICTED',
                'public_message': 'Subject marks viewing restricted by HOD.',
                'attendance_percentage': att_res['percentage'],
                'attended': att_res['attended'],
                'conducted': att_res['conducted'],
                'cutoff_date': cutoff_date,
                'override': override
            }
        elif override.decision_type == 'ALLOW_OVERRIDE':
            return {
                'can_view': True,
                'decision_source': 'HOD_ALLOW_OVERRIDE',
                'status': 'AUTHORIZED',
                'public_message': 'Access authorized by department special dispensation.',
                'attendance_percentage': att_res['percentage'],
                'attended': att_res['attended'],
                'conducted': att_res['conducted'],
                'cutoff_date': cutoff_date,
                'override': override
            }

    if att_res['status'] == 'PENDING':
        return {
            'can_view': False,
            'decision_source': 'AUTOMATIC_PENDING',
            'status': 'PENDING',
            'public_message': 'Attendance eligibility could not yet be verified.',
            'attendance_percentage': None,
            'attended': 0,
            'conducted': 0,
            'cutoff_date': cutoff_date,
            'override': None
        }
    elif att_res['is_eligible']:
        return {
            'can_view': True,
            'decision_source': 'AUTOMATIC_ELIGIBLE',
            'status': 'ELIGIBLE',
            'public_message': f'Attendance verified at {att_res["percentage"]}%.',
            'attendance_percentage': att_res['percentage'],
            'attended': att_res['attended'],
            'conducted': att_res['conducted'],
            'cutoff_date': cutoff_date,
            'override': None
        }
    else:
        return {
            'can_view': False,
            'decision_source': 'AUTOMATIC_RESTRICTED',
            'status': 'RESTRICTED',
            'public_message': f'Attendance is below 75% ({att_res["percentage"]}%). Subject marks view is restricted.',
            'attendance_percentage': att_res['percentage'],
            'attended': att_res['attended'],
            'conducted': att_res['conducted'],
            'cutoff_date': cutoff_date,
            'override': None
        }


# ==============================================================================
# CENTRAL ACADEMIC ACCESS CONTROL & FILE SECURITY SERVICE
# ==============================================================================

def get_active_hod_access_decision(student, subject, academic_scope, resource_type=None):
    """
    Checks for an active HOD decision (ALLOW_OVERRIDE or MANUAL_RESTRICT)
    for a student, subject, and academic scope.
    Checks resource-specific component first (e.g. 'ASSIGNMENT', 'STUDY_MATERIAL'), then 'ALL'.
    """
    if not student:
        return None

    course = academic_scope.get('course', 'BCA')
    semester = academic_scope.get('semester', 'Sem V')
    section = academic_scope.get('section', 'A')
    assessment_cycle = academic_scope.get('assessment_cycle', '2026-27')

    components_to_check = [resource_type, 'ALL'] if resource_type else ['ALL']
    components_to_check = [c for c in components_to_check if c]

    override = MarksEligibilityOverride.query.filter(
        MarksEligibilityOverride.student_id == student.id,
        MarksEligibilityOverride.subject == subject,
        MarksEligibilityOverride.course == course,
        MarksEligibilityOverride.semester == semester,
        MarksEligibilityOverride.section == section,
        MarksEligibilityOverride.assessment_cycle == assessment_cycle,
        MarksEligibilityOverride.component.in_(components_to_check),
        MarksEligibilityOverride.is_active == True
    ).order_by(
        db.case((MarksEligibilityOverride.component == resource_type, 1), else_=2)
    ).first()

    return override


def get_subject_attendance_eligibility(student, subject, academic_scope, evaluation_date=None):
    """
    Evaluates raw subject attendance up to the evaluation_date cutoff.
    If evaluation_date is None, returns PENDING fail-closed status.
    """
    if not student or not evaluation_date:
        return {
            'status': 'PENDING',
            'percentage': None,
            'attended': 0,
            'conducted': 0,
            'is_eligible': False,
            'message': 'No evaluation date specified for attendance calculation.'
        }

    course = academic_scope.get('course', 'BCA')
    semester = academic_scope.get('semester', 'Sem V')
    section = academic_scope.get('section', 'A')

    return calculate_subject_attendance(
        student_id=student.id,
        subject=subject,
        assessment_date=evaluation_date,
        course=course,
        semester=semester,
        section=section
    )


def get_academic_content_access_decision(user, student, subject, academic_scope, resource_type='ASSIGNMENT', evaluation_date=None):
    """
    Centralized Access Policy Engine for Assignments and Study Materials.
    Requirements:
    1. Active HOD manual restriction denies student access.
    2. Active HOD allow override permits access below 75%.
    3. Attendance >= 75.0% satisfies threshold.
    4. Attendance < 75.0% denies access.
    5. Missing, unreliable or 0 sessions (PENDING) fails closed (denies access).
    6. Exactly 75.0% satisfies threshold.
    7. Staff/Faculty/HOD content management rights are evaluated separately via can_manage_academic_resource().
    """
    # If a staff user is requesting on behalf of themselves (e.g. previewing/viewing content),
    # verify teacher/HOD authorization
    if user and not student:
        can_manage = can_manage_academic_resource(user, subject, academic_scope, action='VIEW')
        return {
            'can_view': can_manage,
            'decision_source': 'STAFF_ROLE_CHECK',
            'status': 'AUTHORIZED' if can_manage else 'FORBIDDEN',
            'public_message': 'Staff authorization granted.' if can_manage else 'Staff authorization denied.',
            'attendance_percentage': None,
            'attended': 0,
            'conducted': 0,
            'override': None
        }

    if not student:
        return {
            'can_view': False,
            'decision_source': 'UNAUTHENTICATED',
            'status': 'FORBIDDEN',
            'public_message': 'Student identity required.',
            'attendance_percentage': None,
            'attended': 0,
            'conducted': 0,
            'override': None
        }

    # Verify student's academic scope matches resource scope
    req_course = academic_scope.get('course')
    req_year = academic_scope.get('academic_year')
    req_sem = academic_scope.get('semester')
    req_sec = academic_scope.get('section')
    if req_course and student.course != req_course:
        return {
            'can_view': False,
            'decision_source': 'CROSS_CLASS_RESTRICTED',
            'status': 'RESTRICTED',
            'public_message': 'Content does not belong to your enrolled program.',
            'attendance_percentage': None,
            'attended': 0,
            'conducted': 0,
            'override': None
        }
    if req_year and student.academic_year != req_year:
        return {
            'can_view': False,
            'decision_source': 'CROSS_CLASS_RESTRICTED',
            'status': 'RESTRICTED',
            'public_message': 'Content does not belong to your enrolled academic year.',
            'attendance_percentage': None,
            'attended': 0,
            'conducted': 0,
            'override': None
        }
    if req_sem and student.semester != req_sem:
        return {
            'can_view': False,
            'decision_source': 'CROSS_CLASS_RESTRICTED',
            'status': 'RESTRICTED',
            'public_message': 'Content does not belong to your enrolled semester.',
            'attendance_percentage': None,
            'attended': 0,
            'conducted': 0,
            'override': None
        }
    if req_sec and req_sec != 'ALL' and student.section != req_sec:
        return {
            'can_view': False,
            'decision_source': 'CROSS_CLASS_RESTRICTED',
            'status': 'RESTRICTED',
            'public_message': 'Content does not belong to your enrolled section.',
            'attendance_percentage': None,
            'attended': 0,
            'conducted': 0,
            'override': None
        }

    # 1. Check for Active HOD Override
    override = get_active_hod_access_decision(student, subject, academic_scope, resource_type=resource_type)
    if override:
        if override.decision_type == 'MANUAL_RESTRICT':
            return {
                'can_view': False,
                'decision_source': 'HOD_MANUAL_RESTRICT',
                'status': 'RESTRICTED',
                'public_message': 'Academic access restricted by Head of Department.',
                'attendance_percentage': None,
                'attended': 0,
                'conducted': 0,
                'override': override
            }
        elif override.decision_type == 'ALLOW_OVERRIDE':
            return {
                'can_view': True,
                'decision_source': 'HOD_ALLOW_OVERRIDE',
                'status': 'AUTHORIZED',
                'public_message': 'Access authorized under departmental special dispensation.',
                'attendance_percentage': None,
                'attended': 0,
                'conducted': 0,
                'override': override
            }

    # 2. Automatic Attendance Calculation
    if not evaluation_date:
        # Without an evaluation date, policy fails closed
        return {
            'can_view': False,
            'decision_source': 'AUTOMATIC_PENDING',
            'status': 'PENDING',
            'public_message': 'Attendance eligibility cannot yet be verified for this academic period.',
            'attendance_percentage': None,
            'attended': 0,
            'conducted': 0,
            'override': None
        }

    att_res = get_subject_attendance_eligibility(student, subject, academic_scope, evaluation_date=evaluation_date)

    if att_res['status'] == 'PENDING':
        return {
            'can_view': False,
            'decision_source': 'AUTOMATIC_PENDING',
            'status': 'PENDING',
            'public_message': 'Attendance eligibility cannot yet be verified (no completed sessions recorded).',
            'attendance_percentage': None,
            'attended': 0,
            'conducted': 0,
            'override': None
        }

    if att_res['is_eligible']:  # >= 75.0%
        return {
            'can_view': True,
            'decision_source': 'AUTOMATIC_ELIGIBLE',
            'status': 'ELIGIBLE',
            'public_message': f'Attendance verified at {att_res["percentage"]}%.',
            'attendance_percentage': att_res['percentage'],
            'attended': att_res['attended'],
            'conducted': att_res['conducted'],
            'override': None
        }
    else:  # < 75.0%
        return {
            'can_view': False,
            'decision_source': 'AUTOMATIC_RESTRICTED',
            'status': 'RESTRICTED',
            'public_message': f'Subject attendance is below 75% ({att_res["percentage"]}%). Content is restricted.',
            'attendance_percentage': att_res['percentage'],
            'attended': att_res['attended'],
            'conducted': att_res['conducted'],
            'override': None
        }


def can_manage_academic_resource(user, subject, academic_scope, action='MANAGE'):
    """
    Enforces server-side permissions for managing (create, edit, delete, archive) academic resources.
    - Principal & admin: Allowed across the institution
    - HOD: Allowed strictly for the HOD's department (e.g. BCA courses for HOD - BCA Dept)
    - Faculty: Allowed strictly for subjects and classes they are allocated to teach in Timetable
    """
    if not user:
        return False

    if user.role in ['Principal', 'admin']:
        return True

    course = academic_scope.get('course', 'BCA')
    semester = academic_scope.get('semester', 'Sem V')
    section = academic_scope.get('section', 'A')

    if user.role == 'HOD - BCA Dept':
        return course == 'BCA'

    if user.role == 'Faculty':
        # Teacher must be allocated to teach this subject in this class
        if section and section != 'ALL':
            match = Timetable.query.filter_by(
                user_id=user.id,
                course=course,
                semester=semester,
                section=section,
                subject=subject
            ).first()
        else:
            match = Timetable.query.filter_by(
                user_id=user.id,
                course=course,
                semester=semester,
                subject=subject
            ).first()
        return match is not None

    return False


def record_academic_resource_audit(actor_user=None, actor_student=None, action='UPDATE', resource_type='ASSIGNMENT', resource_id=0, before_state=None, after_state=None, reason=None):
    """
    Records immutable audit logs for academic resource lifecycle changes.
    """
    try:
        audit = AcademicResourceAudit(
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            actor_id=actor_user.id if actor_user else None,
            actor_student_id=actor_student.id if actor_student else None,
            before_state=json.dumps(before_state) if isinstance(before_state, dict) else before_state,
            after_state=json.dumps(after_state) if isinstance(after_state, dict) else after_state,
            reason=reason
        )
        db.session.add(audit)
        db.session.commit()
        return audit
    except Exception as e:
        db.session.rollback()
        print(f"Academic Resource Audit Log Warning: {e}")
        return None


def validate_academic_file(file, max_bytes=None):
    """
    Strict server-side validation:
    - Non-empty filename
    - Prohibited extension rejection (executable, script, active HTML)
    - Allowed extension verification
    - File size check
    - Magic bytes verification for common types (PDF, JPEG, PNG, ZIP/Office)
    """
    if max_bytes is None:
        max_bytes = app.config.get('MAX_ACADEMIC_UPLOAD_BYTES', 15 * 1024 * 1024)

    if not file or not file.filename:
        return False, "No file uploaded or filename is empty.", None, None, 0

    clean_orig_name = secure_filename(file.filename)
    if not clean_orig_name or '.' not in clean_orig_name:
        return False, "Invalid filename.", None, None, 0

    ext = clean_orig_name.rsplit('.', 1)[1].lower()

    # 1. Prohibited extensions check
    if ext in app.config.get('PROHIBITED_EXTENSIONS', set()):
        return False, f"Security Violation: Uploading .{ext} executable/script files is strictly prohibited.", None, None, 0

    # 2. Allowed extensions check
    if ext not in app.config.get('ALLOWED_ACADEMIC_EXTENSIONS', set()):
        return False, f"Unsupported file type .{ext}. Allowed formats: PDF, DOCX, DOC, PPTX, PPT, TXT, ZIP, JPG, PNG.", None, None, 0

    # 3. File size check (read into buffer or seek)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size <= 0:
        return False, "Uploaded file is empty (0 bytes).", None, None, 0

    if file_size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        return False, f"File size exceeds maximum permitted limit of {max_mb:.1f} MB.", None, None, file_size

    # 4. Magic header check for known types
    header = file.read(16)
    file.seek(0)

    if ext == 'pdf' and not header.startswith(b'%PDF'):
        return False, "Corrupted or invalid PDF header detected.", None, None, file_size
    elif ext in ['jpg', 'jpeg'] and not header.startswith(b'\xff\xd8'):
        return False, "Corrupted or invalid JPEG image header detected.", None, None, file_size
    elif ext == 'png' and not header.startswith(b'\x89PNG\r\n\x1a\n'):
        return False, "Corrupted or invalid PNG image header detected.", None, None, file_size

    mimetype = getattr(file, 'mimetype', None) or getattr(file, 'content_type', None) or 'application/octet-stream'
    return True, None, clean_orig_name, mimetype, file_size


def save_academic_file(file, target_folder, original_name):
    """
    Saves an uploaded file to a private directory with a randomized UUID storage key.
    Computes and returns SHA-256 checksum and storage key.
    """
    os.makedirs(target_folder, exist_ok=True)
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else 'dat'
    storage_key = f"{uuid.uuid4().hex}.{ext}"
    target_path = os.path.join(target_folder, storage_key)

    hasher = hashlib.sha256()
    file.seek(0)
    with open(target_path, 'wb') as dest:
        while True:
            chunk = file.read(65536)
            if not chunk:
                break
            dest.write(chunk)
            hasher.update(chunk)
    file.seek(0)

    return storage_key, hasher.hexdigest(), os.path.getsize(target_path)


def remove_academic_file(storage_key, folder):
    """Safely deletes a private file from storage without raising on missing file."""
    if not storage_key:
        return
    try:
        path = os.path.join(folder, storage_key)
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Warning: Failed to delete storage file {storage_key}: {e}")



@app.route('/internal-marks', methods=['GET'])
@login_required
def internal_marks_dashboard():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized: Internal Marks Management is restricted to faculty members.', 'danger')
        return redirect(url_for('dashboard')), 403

    authorized_contexts = get_authorized_subject_contexts(user)
    maxima = get_assessment_maxima()

    scope_subjects = [c['subject'] for c in authorized_contexts]
    if user.role in ['Principal', 'admin']:
        base_marks_query = InternalMark.query
    elif user.role == 'HOD - BCA Dept':
        base_marks_query = InternalMark.query.filter(InternalMark.course == 'BCA')
    else:
        base_marks_query = InternalMark.query.filter(InternalMark.subject.in_(scope_subjects) if scope_subjects else False)

    total_records = base_marks_query.count()
    all_records = base_marks_query.all()
    complete_count = sum(1 for m in all_records if m.completion_status == 'Complete')
    partial_count = sum(1 for m in all_records if m.completion_status == 'Partial')
    recent_marks = base_marks_query.order_by(InternalMark.updated_at.desc()).limit(8).all()

    courses = sorted(list({c['course'] for c in authorized_contexts}))
    semesters = sorted(list({c['semester'] for c in authorized_contexts}))
    sections = sorted(list({c['section'] for c in authorized_contexts}))
    subjects = sorted(list({c['subject'] for c in authorized_contexts}))

    return render_template(
        'internal_marks/dashboard.html',
        user=user,
        authorized_contexts=authorized_contexts,
        courses=courses,
        semesters=semesters,
        sections=sections,
        subjects=subjects,
        maxima=maxima,
        total_records=total_records,
        complete_count=complete_count,
        partial_count=partial_count,
        recent_marks=recent_marks
    )


@app.route('/internal-marks/students', methods=['GET'])
@login_required
def internal_marks_students():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    course = (request.args.get('course') or '').strip()
    semester = (request.args.get('semester') or '').strip()
    section = (request.args.get('section') or '').strip()
    subject = (request.args.get('subject') or '').strip()
    assessment_cycle = (request.args.get('assessment_cycle') or '2026-27').strip()
    search = (request.args.get('search') or '').strip()

    if not course or not semester or not section or not subject:
        flash('Please select Course, Semester, Section, and Subject.', 'warning')
        return redirect(url_for('internal_marks_dashboard'))

    # Backend authorization check
    if not is_user_authorized_for_context(user, course, semester, section, subject):
        flash('Access Denied: You are not authorized to manage internal marks for this subject and class.', 'danger')
        return redirect(url_for('internal_marks_dashboard')), 403

    # Query active students in this class
    query = Student.query.filter_by(
        course=course,
        semester=semester,
        section=section,
        is_active=True
    )
    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                Student.name.ilike(search_pattern),
                Student.uucms_id.ilike(search_pattern)
            )
        )
    students = query.order_by(Student.name.asc()).all()

    # Preload existing internal marks for these students in this subject & cycle
    student_ids = [s.id for s in students]
    existing_marks = {}
    if student_ids:
        marks_rows = InternalMark.query.filter(
            InternalMark.student_id.in_(student_ids),
            InternalMark.subject == subject,
            InternalMark.semester == semester,
            InternalMark.section == section,
            InternalMark.assessment_cycle == assessment_cycle
        ).all()
        for m in marks_rows:
            existing_marks[m.student_id] = m

    maxima = get_assessment_maxima()

    return render_template(
        'internal_marks/students.html',
        user=user,
        course=course,
        semester=semester,
        section=section,
        subject=subject,
        assessment_cycle=assessment_cycle,
        search=search,
        students=students,
        existing_marks=existing_marks,
        maxima=maxima
    )


@app.route('/internal-marks/entry', methods=['GET'])
@login_required
def internal_marks_entry():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    student_id = request.args.get('student_id', type=int)
    course = (request.args.get('course') or '').strip()
    semester = (request.args.get('semester') or '').strip()
    section = (request.args.get('section') or '').strip()
    subject = (request.args.get('subject') or '').strip()
    assessment_cycle = (request.args.get('assessment_cycle') or '2026-27').strip()

    if not student_id or not course or not semester or not section:
        flash('Invalid request parameters.', 'warning')
        return redirect(url_for('internal_marks_dashboard'))

    # Check if user is authorized for this student's class scope
    if not is_user_authorized_for_class(user, course, semester, section):
        flash('Access Denied: You are not authorized to access students in this class context.', 'danger')
        return redirect(url_for('internal_marks_dashboard')), 403

    student = Student.query.get(student_id)
    if not student or not student.is_active or student.course != course or student.semester != semester or student.section != section:
        flash('Selected student does not belong to the specified active class context.', 'danger')
        return redirect(url_for('internal_marks_dashboard'))

    # Query all subjects in this class to provide the complete multi-subject overview
    class_tt = Timetable.query.filter_by(
        course=course,
        semester=semester,
        section=section
    ).all()

    class_subjects_dict = {}
    for entry in class_tt:
        if entry.subject not in class_subjects_dict:
            fac = User.query.get(entry.user_id)
            fac_name = fac.full_name if fac else 'Assigned Faculty'
            is_editable = is_user_authorized_for_context(user, course, semester, section, entry.subject)
            mark_row = InternalMark.query.filter_by(
                student_id=student.id,
                subject=entry.subject,
                semester=semester,
                section=section,
                assessment_cycle=assessment_cycle
            ).first()
            class_subjects_dict[entry.subject] = {
                'subject': entry.subject,
                'faculty_name': fac_name,
                'is_editable': is_editable,
                'mark': mark_row
            }

    all_subject_marks = list(class_subjects_dict.values())
    if not subject and all_subject_marks:
        editable_first = [s['subject'] for s in all_subject_marks if s['is_editable']]
        subject = editable_first[0] if editable_first else all_subject_marks[0]['subject']

    can_edit = is_user_authorized_for_context(user, course, semester, section, subject)

    existing_mark = InternalMark.query.filter_by(
        student_id=student.id,
        subject=subject,
        semester=semester,
        section=section,
        assessment_cycle=assessment_cycle
    ).first()

    maxima = get_assessment_maxima()

    return render_template(
        'internal_marks/entry.html',
        user=user,
        student=student,
        course=course,
        semester=semester,
        section=section,
        subject=subject,
        assessment_cycle=assessment_cycle,
        existing_mark=existing_mark,
        maxima=maxima,
        can_edit=can_edit,
        all_subject_marks=all_subject_marks
    )


@app.route('/internal-marks/save', methods=['POST'])
@login_required
def internal_marks_save():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    student_id = request.form.get('student_id', type=int)
    course = (request.form.get('course') or '').strip()
    semester = (request.form.get('semester') or '').strip()
    section = (request.form.get('section') or '').strip()
    subject = (request.form.get('subject') or '').strip()
    assessment_cycle = (request.form.get('assessment_cycle') or '2026-27').strip()
    submitted_version = request.form.get('version', type=int)
    reason = (request.form.get('reason') or '').strip()

    # 1. Authorize subject context
    if not is_user_authorized_for_context(user, course, semester, section, subject):
        flash('Access Denied: You are not authorized to save marks for this subject.', 'danger')
        return redirect(url_for('internal_marks_dashboard')), 403

    # 2. Validate student
    student = Student.query.get(student_id)
    if not student or not student.is_active or student.course != course or student.semester != semester or student.section != section:
        flash('Invalid student record or student is not active in this class.', 'danger')
        return redirect(url_for('internal_marks_dashboard'))

    # 3. Parse and validate submitted marks
    maxima = get_assessment_maxima()
    raw_ia1 = request.form.get('ia1_marks')
    raw_ia2 = request.form.get('ia2_marks')
    raw_final = request.form.get('final_ia_marks')

    ia1_val, err1 = parse_and_validate_mark(raw_ia1, 'IA1', maxima['IA1'])
    if err1:
        flash(err1, 'danger')
        return redirect(url_for('internal_marks_entry', student_id=student_id, course=course, semester=semester, section=section, subject=subject, assessment_cycle=assessment_cycle))

    ia2_val, err2 = parse_and_validate_mark(raw_ia2, 'IA2', maxima['IA2'])
    if err2:
        flash(err2, 'danger')
        return redirect(url_for('internal_marks_entry', student_id=student_id, course=course, semester=semester, section=section, subject=subject, assessment_cycle=assessment_cycle))

    final_val, err3 = parse_and_validate_mark(raw_final, 'Final IA', maxima['Final IA'])
    if err3:
        flash(err3, 'danger')
        return redirect(url_for('internal_marks_entry', student_id=student_id, course=course, semester=semester, section=section, subject=subject, assessment_cycle=assessment_cycle))

    if ia1_val is None and ia2_val is None and final_val is None:
        flash('Please enter at least one assessment component (IA1, IA2, or Final IA).', 'warning')
        return redirect(url_for('internal_marks_entry', student_id=student_id, course=course, semester=semester, section=section, subject=subject, assessment_cycle=assessment_cycle))

    # 4. Transactional persistence with duplicate prevention & concurrency check
    try:
        existing_mark = InternalMark.query.filter_by(
            student_id=student.id,
            subject=subject,
            semester=semester,
            section=section,
            assessment_cycle=assessment_cycle
        ).first()

        academic_year = student.academic_year or '3rd Year'

        if existing_mark:
            # Optimistic concurrency check
            if submitted_version is not None and submitted_version != existing_mark.version:
                flash('Concurrent update detected: Another session modified this student\'s marks. Please reload and review the latest values.', 'danger')
                return redirect(url_for('internal_marks_entry', student_id=student_id, course=course, semester=semester, section=section, subject=subject, assessment_cycle=assessment_cycle))

            # Detect actual changes
            changes = []
            if existing_mark.ia1_marks != ia1_val:
                changes.append(('IA1', existing_mark.ia1_marks, ia1_val))
            if existing_mark.ia2_marks != ia2_val:
                changes.append(('IA2', existing_mark.ia2_marks, ia2_val))
            if existing_mark.final_ia_marks != final_val:
                changes.append(('Final IA', existing_mark.final_ia_marks, final_val))

            if not changes:
                flash('No changes detected in internal assessment marks.', 'info')
                return redirect(url_for('internal_marks_students', course=course, semester=semester, section=section, subject=subject, assessment_cycle=assessment_cycle))

            # A correction reason is mandatory when updating existing saved marks
            if not reason:
                flash('A reason for correction is required when updating existing internal marks.', 'warning')
                return redirect(url_for('internal_marks_entry', student_id=student_id, course=course, semester=semester, section=section, subject=subject, assessment_cycle=assessment_cycle))

            # Apply updates
            existing_mark.ia1_marks = ia1_val
            existing_mark.ia2_marks = ia2_val
            existing_mark.final_ia_marks = final_val
            existing_mark.updated_by_id = user.id
            existing_mark.version += 1

            # Create audit records
            for comp, prev_val, new_v in changes:
                audit = InternalMarkAudit(
                    internal_mark_id=existing_mark.id,
                    student_id=student.id,
                    subject=subject,
                    academic_year=academic_year,
                    semester=semester,
                    assessment_cycle=assessment_cycle,
                    component=comp,
                    previous_value=str(prev_val) if prev_val is not None else 'Not Entered',
                    new_value=str(new_v) if new_v is not None else 'Not Entered',
                    changed_by_id=user.id,
                    reason=reason
                )
                db.session.add(audit)

        else:
            # Create new record
            new_mark = InternalMark(
                student_id=student.id,
                course=course,
                academic_year=academic_year,
                semester=semester,
                section=section,
                subject=subject,
                assessment_cycle=assessment_cycle,
                ia1_marks=ia1_val,
                ia2_marks=ia2_val,
                final_ia_marks=final_val,
                created_by_id=user.id,
                updated_by_id=user.id,
                version=1
            )
            db.session.add(new_mark)
            db.session.flush()

            # Create initial audit log for entered components
            for comp, val in [('IA1', ia1_val), ('IA2', ia2_val), ('Final IA', final_val)]:
                if val is not None:
                    audit = InternalMarkAudit(
                        internal_mark_id=new_mark.id,
                        student_id=student.id,
                        subject=subject,
                        academic_year=academic_year,
                        semester=semester,
                        assessment_cycle=assessment_cycle,
                        component=comp,
                        previous_value='Not Entered',
                        new_value=str(val),
                        changed_by_id=user.id,
                        reason=reason or 'Initial marks entry'
                    )
                    db.session.add(audit)

        db.session.commit()
        try:
            create_notification(
                recipient_type='STUDENT',
                recipient_id=student.id,
                title=f"Internal Marks Recorded: {subject}",
                message=f"Internal assessment marks for {subject} were recorded/updated by {user.full_name}.",
                category='marks',
                action_url=url_for('student_marks'),
                idempotency_key=f"marks_upd_{student.id}_{subject}_{assessment_cycle}_{int(datetime.utcnow().timestamp() // 60)}",
                sound=True
            )
        except Exception:
            pass
        flash(f'Internal assessment marks for {student.name} ({student.uucms_id}) saved successfully!', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Database transaction failed while saving marks. Please try again.', 'danger')
        return redirect(url_for('internal_marks_entry', student_id=student_id, course=course, semester=semester, section=section, subject=subject, assessment_cycle=assessment_cycle))

    # Keep class & subject context active to work on next student smoothly
    return redirect(url_for('internal_marks_students', course=course, semester=semester, section=section, subject=subject, assessment_cycle=assessment_cycle))


@app.route('/internal-marks/history', methods=['GET'])
@login_required
def internal_marks_history():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    authorized_contexts = get_authorized_subject_contexts(user)
    scope_subjects = [c['subject'] for c in authorized_contexts]

    course_filter = (request.args.get('course') or '').strip()
    semester_filter = (request.args.get('semester') or '').strip()
    section_filter = (request.args.get('section') or '').strip()
    subject_filter = (request.args.get('subject') or '').strip()
    status_filter = (request.args.get('status') or 'all').strip()
    search = (request.args.get('search') or '').strip()
    page = request.args.get('page', 1, type=int)

    # Scoped base query
    if user.role in ['Principal', 'admin']:
        query = InternalMark.query
    elif user.role == 'HOD - BCA Dept':
        query = InternalMark.query.filter(InternalMark.course == 'BCA')
    else:
        query = InternalMark.query.filter(InternalMark.subject.in_(scope_subjects) if scope_subjects else False)

    if course_filter:
        query = query.filter(InternalMark.course == course_filter)
    if semester_filter:
        query = query.filter(InternalMark.semester == semester_filter)
    if section_filter:
        query = query.filter(InternalMark.section == section_filter)
    if subject_filter:
        if subject_filter in scope_subjects or user.role in ['Principal', 'admin']:
            query = query.filter(InternalMark.subject == subject_filter)
        else:
            flash('Unauthorized subject filter.', 'danger')
            return redirect(url_for('internal_marks_history')), 403

    if search:
        query = query.join(Student).filter(
            db.or_(
                Student.name.ilike(f'%{search}%'),
                Student.uucms_id.ilike(f'%{search}%')
            )
        )

    query = query.order_by(InternalMark.updated_at.desc())

    all_results = query.all()
    if status_filter == 'complete':
        filtered = [m for m in all_results if m.completion_status == 'Complete']
    elif status_filter == 'partial':
        filtered = [m for m in all_results if m.completion_status == 'Partial']
    elif status_filter == 'not_started':
        filtered = [m for m in all_results if m.completion_status == 'Not Started']
    else:
        filtered = all_results

    per_page = 20
    total = len(filtered)
    total_pages = max(1, math.ceil(total / per_page))
    start_idx = (page - 1) * per_page
    paginated_items = filtered[start_idx:start_idx + per_page]

    courses = sorted(list({c['course'] for c in authorized_contexts}))
    semesters = sorted(list({c['semester'] for c in authorized_contexts}))
    sections = sorted(list({c['section'] for c in authorized_contexts}))
    subjects = sorted(list({c['subject'] for c in authorized_contexts}))

    return render_template(
        'internal_marks/history.html',
        user=user,
        marks=paginated_items,
        page=page,
        total_pages=total_pages,
        total=total,
        course_filter=course_filter,
        semester_filter=semester_filter,
        section_filter=section_filter,
        subject_filter=subject_filter,
        status_filter=status_filter,
        search=search,
        courses=courses,
        semesters=semesters,
        sections=sections,
        subjects=subjects
    )


@app.route('/internal-marks/audit/<int:mark_id>', methods=['GET'])
@login_required
def internal_marks_audit(mark_id):
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    mark = InternalMark.query.get_or_404(mark_id)
    if not is_user_authorized_for_context(user, mark.course, mark.semester, mark.section, mark.subject):
        flash('Access Denied: You are not authorized to view the audit history for this subject.', 'danger')
        return redirect(url_for('internal_marks_dashboard')), 403

    audits = InternalMarkAudit.query.filter_by(internal_mark_id=mark.id).order_by(InternalMarkAudit.created_at.desc()).all()

    return render_template(
        'internal_marks/audit.html',
        user=user,
        mark=mark,
        audits=audits
    )


# ==============================================================================
# HOD ATTENDANCE ELIGIBILITY RESTRICTIONS & OVERRIDES
# ==============================================================================

@app.route('/internal-marks/hod-restrictions', methods=['GET'])
@login_required
def internal_marks_hod_restrictions():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized: HOD Restrictions Management is restricted to Department Heads and Executive Administration.', 'danger')
        return redirect(url_for('dashboard')), 403

    if user.role == 'HOD - BCA Dept':
        allowed_courses = ['BCA']
    else:
        allowed_courses = [r[0] for r in db.session.query(Timetable.course).distinct().all() if r[0]]
        if not allowed_courses:
            allowed_courses = ['BCA']

    course = (request.args.get('course') or allowed_courses[0]).strip()
    if course not in allowed_courses:
        flash('Unauthorized course scope for your department.', 'danger')
        return redirect(url_for('internal_marks_dashboard')), 403

    semester = (request.args.get('semester') or 'Sem V').strip()
    section = (request.args.get('section') or 'A').strip()
    assessment_cycle = (request.args.get('assessment_cycle') or '2026-27').strip()
    component = (request.args.get('component') or 'IA1').strip()
    search = (request.args.get('search') or '').strip()

    subjects_query = db.session.query(Timetable.subject).filter_by(
        course=course,
        semester=semester,
        section=section
    ).distinct().order_by(Timetable.subject).all()
    available_subjects = [s[0] for s in subjects_query]

    selected_subject = (request.args.get('subject') or (available_subjects[0] if available_subjects else '')).strip()

    cutoff_date = get_assessment_cutoff_date(
        course=course,
        semester=semester,
        section=section,
        subject=selected_subject if selected_subject else None,
        assessment_cycle=assessment_cycle,
        component=component
    )

    student_q = Student.query.filter_by(
        course=course,
        semester=semester,
        section=section,
        is_active=True
    )
    if search:
        search_pattern = f'%{search}%'
        student_q = student_q.filter(
            db.or_(
                Student.name.ilike(search_pattern),
                Student.uucms_id.ilike(search_pattern)
            )
        )
    students = student_q.order_by(Student.name.asc()).all()

    roster_data = []
    for s in students:
        att = calculate_subject_attendance(
            student_id=s.id,
            subject=selected_subject,
            assessment_date=cutoff_date,
            course=course,
            semester=semester,
            section=section
        )
        eligibility = evaluate_marks_eligibility(
            student_id=s.id,
            subject=selected_subject,
            component=component,
            assessment_cycle=assessment_cycle,
            course=course,
            semester=semester,
            section=section
        )
        override = MarksEligibilityOverride.query.filter(
            MarksEligibilityOverride.student_id == s.id,
            MarksEligibilityOverride.subject == selected_subject,
            MarksEligibilityOverride.course == course,
            MarksEligibilityOverride.semester == semester,
            MarksEligibilityOverride.section == section,
            MarksEligibilityOverride.assessment_cycle == assessment_cycle,
            MarksEligibilityOverride.component.in_([component, 'ALL']),
            MarksEligibilityOverride.is_active == True
        ).first()

        roster_data.append({
            'student': s,
            'attendance': att,
            'eligibility': eligibility,
            'active_override': override
        })

    recent_audits = MarksEligibilityAudit.query.filter_by(
        course=course
    ).order_by(MarksEligibilityAudit.created_at.desc()).limit(15).all()

    return render_template(
        'internal_marks/hod_restrictions.html',
        user=user,
        course=course,
        semester=semester,
        section=section,
        subject=selected_subject,
        available_subjects=available_subjects,
        component=component,
        assessment_cycle=assessment_cycle,
        cutoff_date=cutoff_date,
        search=search,
        roster_data=roster_data,
        recent_audits=recent_audits,
        allowed_courses=allowed_courses
    )


@app.route('/internal-marks/hod-restrictions/save', methods=['POST'])
@login_required
def internal_marks_hod_restrictions_save():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access: HOD restrictions management requires HOD or Executive authority.', 'danger')
        return redirect(url_for('dashboard')), 403

    student_id = request.form.get('student_id', type=int)
    course = (request.form.get('course') or '').strip()
    semester = (request.form.get('semester') or '').strip()
    section = (request.form.get('section') or '').strip()
    subject = (request.form.get('subject') or '').strip()
    assessment_cycle = (request.form.get('assessment_cycle') or '2026-27').strip()
    component = (request.form.get('component') or 'IA1').strip()
    action = (request.form.get('action') or '').strip()
    reason = (request.form.get('reason') or '').strip()

    if user.role == 'HOD - BCA Dept' and course != 'BCA':
        flash('Access Denied: You are only authorized to manage restrictions for BCA Department courses.', 'danger')
        return redirect(url_for('internal_marks_dashboard')), 403

    if not reason:
        flash('Submission Rejected: A non-empty justification reason is strictly mandatory for any HOD eligibility action or revocation.', 'danger')
        return redirect(url_for('internal_marks_hod_restrictions', course=course, semester=semester, section=section, subject=subject, component=component, assessment_cycle=assessment_cycle))

    if action not in ['ALLOW_OVERRIDE', 'MANUAL_RESTRICT', 'REVOKE']:
        flash('Invalid restriction action requested.', 'danger')
        return redirect(url_for('internal_marks_hod_restrictions', course=course, semester=semester, section=section, subject=subject, component=component, assessment_cycle=assessment_cycle))

    student = Student.query.get(student_id)
    if not student or not student.is_active or student.course != course or student.semester != semester or student.section != section:
        flash('Invalid or inactive student record for this class.', 'danger')
        return redirect(url_for('internal_marks_hod_restrictions', course=course, semester=semester, section=section, subject=subject, component=component, assessment_cycle=assessment_cycle))

    try:
        existing_override = MarksEligibilityOverride.query.filter_by(
            student_id=student.id,
            subject=subject,
            course=course,
            semester=semester,
            section=section,
            assessment_cycle=assessment_cycle,
            component=component
        ).first()

        previous_decision = 'AUTOMATIC'
        if existing_override and existing_override.is_active:
            previous_decision = existing_override.decision_type

        if action == 'REVOKE':
            if existing_override and existing_override.is_active:
                existing_override.is_active = False
                existing_override.updated_by_id = user.id
                existing_override.version += 1

                audit = MarksEligibilityAudit(
                    override_id=existing_override.id,
                    student_id=student.id,
                    subject=subject,
                    course=course,
                    semester=semester,
                    section=section,
                    assessment_cycle=assessment_cycle,
                    component=component,
                    action='REVOKE',
                    previous_decision=previous_decision,
                    new_decision='AUTOMATIC',
                    reason=reason,
                    changed_by_id=user.id
                )
                db.session.add(audit)
                db.session.commit()
                flash(f'Manual decision revoked for {student.name}. Automatic attendance rule restored.', 'info')
            else:
                flash(f'No active manual decision found to revoke for {student.name}.', 'warning')

        else:
            if existing_override:
                existing_override.decision_type = action
                existing_override.reason = reason
                existing_override.is_active = True
                existing_override.updated_by_id = user.id
                existing_override.version += 1
                override_id = existing_override.id
            else:
                new_override = MarksEligibilityOverride(
                    student_id=student.id,
                    subject=subject,
                    course=course,
                    semester=semester,
                    section=section,
                    assessment_cycle=assessment_cycle,
                    component=component,
                    decision_type=action,
                    reason=reason,
                    created_by_id=user.id,
                    updated_by_id=user.id,
                    is_active=True,
                    version=1
                )
                db.session.add(new_override)
                db.session.flush()
                override_id = new_override.id

            audit = MarksEligibilityAudit(
                override_id=override_id,
                student_id=student.id,
                subject=subject,
                course=course,
                semester=semester,
                section=section,
                assessment_cycle=assessment_cycle,
                component=component,
                action=action,
                previous_decision=previous_decision,
                new_decision=action,
                reason=reason,
                changed_by_id=user.id
            )
            db.session.add(audit)
            db.session.commit()

            action_label = 'Allow Override' if action == 'ALLOW_OVERRIDE' else 'Manual Restriction'
            try:
                notif_msg = f"HOD {user.full_name} granted attendance exemption for {subject} ({component}). Reason: {reason}" if action == 'ALLOW_OVERRIDE' else f"HOD {user.full_name} imposed manual restriction for {subject} ({component}). Reason: {reason}"
                create_notification(
                    recipient_type='STUDENT',
                    recipient_id=student.id,
                    title=f"HOD Assessment Decision: {subject}",
                    message=notif_msg,
                    category='marks',
                    action_url=url_for('student_marks'),
                    idempotency_key=f"hod_ovr_{student.id}_{subject}_{component}_{int(datetime.utcnow().timestamp() // 60)}",
                    sound=True
                )
            except Exception:
                pass
            flash(f'Successfully applied {action_label} for {student.name} in {subject} ({component}).', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Transaction failed while saving eligibility decision. Changes rolled back.', 'danger')

    return redirect(url_for('internal_marks_hod_restrictions', course=course, semester=semester, section=section, subject=subject, component=component, assessment_cycle=assessment_cycle))


@app.route('/internal-marks/hod-restrictions/audit', methods=['GET'])
@login_required
def internal_marks_hod_restrictions_audit():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    student_id = request.args.get('student_id', type=int)
    subject = (request.args.get('subject') or '').strip()
    course = (request.args.get('course') or 'BCA').strip()

    query = MarksEligibilityAudit.query
    if user.role == 'HOD - BCA Dept':
        query = query.filter(MarksEligibilityAudit.course == 'BCA')
    elif course:
        query = query.filter(MarksEligibilityAudit.course == course)

    if student_id:
        query = query.filter(MarksEligibilityAudit.student_id == student_id)
    if subject:
        query = query.filter(MarksEligibilityAudit.subject == subject)

    audits = query.order_by(MarksEligibilityAudit.created_at.desc()).limit(100).all()
    student = Student.query.get(student_id) if student_id else None

    return render_template(
        'internal_marks/hod_restrictions_audit.html',
        user=user,
        audits=audits,
        student=student,
        subject=subject
    )


# ==============================================================================
# STUDENT ACADEMIC PORTAL & INTERNAL MARKS VIEW
# ==============================================================================

@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        uucms_id = (request.form.get('uucms_id') or '').strip()
        password = (request.form.get('password') or '').strip()
        if not uucms_id:
            flash('Please enter your official UUCMS ID.', 'warning')
            return render_template('student_login.html', uucms_id=uucms_id)

        student = Student.query.filter(
            func.lower(Student.uucms_id) == uucms_id.lower(),
            Student.is_active == True
        ).first()

        if not student:
            flash('Invalid or inactive UUCMS ID. Please verify your registration or contact the department.', 'danger')
            return render_template('student_login.html', uucms_id=uucms_id)

        is_authenticated = False
        if app.config.get('TESTING') and not password:
            is_authenticated = True
        elif password and student.check_password(password):
            is_authenticated = True

        if not is_authenticated:
            flash('Invalid password. Please check your credentials or contact the department.', 'danger')
            return render_template('student_login.html', uucms_id=uucms_id)

        session['student_id'] = student.id
        session['student_uucms_id'] = student.uucms_id
        session['student_name'] = student.name
        session['student_course'] = student.course
        session['student_semester'] = student.semester
        session['student_section'] = student.section
        session['name'] = student.name
        session['role'] = 'Student'

        flash(f'Welcome, {student.name}! You are signed into the Student Academic Portal.', 'success')
        return redirect(url_for('student_dashboard'))

    return render_template('student_login.html')


@app.route('/student/logout')
def student_logout():
    session.pop('student_id', None)
    session.pop('student_uucms_id', None)
    session.pop('student_name', None)
    session.pop('student_course', None)
    session.pop('student_semester', None)
    session.pop('student_section', None)
    if session.get('role') == 'Student':
        session.pop('name', None)
        session.pop('role', None)
    flash('You have been logged out of the Student Portal.', 'info')
    return redirect(url_for('student_login'))
@app.route('/student/dashboard', methods=['GET'])
def student_dashboard():
    if 'student_id' not in session:
        if 'user_id' in session:
            return redirect(url_for('dashboard'))
        flash('Please login to the Student Academic Portal.', 'info')
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    if not student or not student.is_active:
        session.clear()
        flash('Invalid session or inactive student. Please login again.', 'warning')
        return redirect(url_for('student_login'))

    # Fetch analytics summary safely
    try:
        analytics_data = get_student_academic_analytics_profile(student, viewing_user=None)
    except Exception:
        analytics_data = None

    # Fetch published assignments in student scope
    assignments = Assignment.query.filter(
        Assignment.course == student.course,
        Assignment.academic_year == student.academic_year,
        Assignment.semester == student.semester,
        Assignment.section.in_([student.section, 'ALL']),
        Assignment.status == 'Published'
    ).order_by(Assignment.deadline.asc()).all()

    submissions = {
        s.assignment_id: s
        for s in AssignmentSubmission.query.filter_by(student_id=student.id).all()
    }

    # Fetch published study materials count
    study_materials_count = StudyMaterial.query.filter(
        StudyMaterial.course == student.course,
        StudyMaterial.academic_year == student.academic_year,
        StudyMaterial.semester == student.semester,
        StudyMaterial.section.in_([student.section, 'ALL']),
        StudyMaterial.status == 'Published'
    ).count()

    # Fetch published semester timetable
    timetable = StudentSemesterTimetable.query.filter(
        StudentSemesterTimetable.course == student.course,
        StudentSemesterTimetable.academic_year == student.academic_year,
        StudentSemesterTimetable.semester == student.semester,
        StudentSemesterTimetable.section.in_([student.section, 'ALL']),
        StudentSemesterTimetable.status == 'PUBLISHED'
    ).order_by(
        db.case((StudentSemesterTimetable.section == student.section, 1), else_=2),
        StudentSemesterTimetable.version.desc()
    ).first()

    return render_template(
        'student_dashboard.html',
        student=student,
        analytics=analytics_data,
        assignments=assignments,
        submissions=submissions,
        study_materials_count=study_materials_count,
        timetable=timetable
    )

@app.route('/student/attendance', methods=['GET'])
def student_attendance_view():
    if 'student_id' not in session:
        flash('Please login to the Student Academic Portal.', 'info')
        return redirect(url_for('student_login'))
    return redirect(url_for('student_academic_analytics', student_id=session['student_id']))



@app.route('/student/marks', methods=['GET'])
def student_marks():
    target_student_id = request.args.get('student_id', type=int)

    if 'student_id' in session:
        logged_student_id = session['student_id']
        if target_student_id and target_student_id != logged_student_id:
            flash('Security Violation: You are not authorized to access another student\'s records.', 'danger')
            return redirect(url_for('student_marks')), 403
        student = Student.query.get(logged_student_id)
        is_staff_view = False
    elif 'user_id' in session:
        staff_user = User.query.get(session['user_id'])
        if not staff_user or staff_user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
            flash('Unauthorized access.', 'danger')
            return redirect(url_for('login')), 403
        if not target_student_id:
            flash('Please specify a student to view marks.', 'warning')
            return redirect(url_for('internal_marks_dashboard'))
        student = Student.query.get(target_student_id)
        if not student:
            flash('Student not found.', 'danger')
            return redirect(url_for('internal_marks_dashboard')), 404
        if not is_user_authorized_for_class(staff_user, student.course, student.semester, student.section):
            flash('Access Denied: You are not authorized to view students in this class.', 'danger')
            return redirect(url_for('internal_marks_dashboard')), 403
        is_staff_view = True
    else:
        flash('Please sign in with your UUCMS ID to view your internal assessment marks.', 'info')
        return redirect(url_for('student_login'))

    if not student or not student.is_active:
        flash('Student record not found or inactive.', 'danger')
        return redirect(url_for('student_login'))

    assessment_cycle = (request.args.get('assessment_cycle') or '2026-27').strip()

    timetable_subjects = db.session.query(
        Timetable.subject
    ).filter_by(
        course=student.course,
        semester=student.semester,
        section=student.section
    ).distinct().order_by(Timetable.subject).all()
    class_subjects = [s[0] for s in timetable_subjects]

    marks_rows = InternalMark.query.filter_by(
        student_id=student.id,
        course=student.course,
        semester=student.semester,
        section=student.section,
        assessment_cycle=assessment_cycle
    ).all()
    marks_by_subject = {m.subject: m for m in marks_rows}

    subject_evaluations = []
    for subj in class_subjects:
        mark_record = marks_by_subject.get(subj)
        components_data = {}
        for comp in ['IA1', 'IA2', 'Final IA']:
            elig = evaluate_marks_eligibility(
                student_id=student.id,
                subject=subj,
                component=comp,
                assessment_cycle=assessment_cycle,
                course=student.course,
                semester=student.semester,
                section=student.section
            )
            if elig['can_view']:
                if mark_record:
                    if comp == 'IA1':
                        val = mark_record.ia1_marks
                    elif comp == 'IA2':
                        val = mark_record.ia2_marks
                    else:
                        val = mark_record.final_ia_marks
                else:
                    val = None
                display_mark = val
            else:
                display_mark = None

            components_data[comp] = {
                'eligible': elig['can_view'],
                'status': elig['status'],
                'public_message': elig['public_message'],
                'attendance_pct': elig['attendance_percentage'],
                'attended': elig['attended'],
                'conducted': elig['conducted'],
                'mark': display_mark,
                'entered': (display_mark is not None) if elig['can_view'] else False
            }

        subject_evaluations.append({
            'subject': subj,
            'components': components_data
        })

    maxima = get_assessment_maxima()

    return render_template(
        'student_marks.html',
        student=student,
        assessment_cycle=assessment_cycle,
        subject_evaluations=subject_evaluations,
        maxima=maxima,
        is_staff_view=is_staff_view
    )


@app.route('/api/student/marks', methods=['GET'])
def api_student_marks():
    target_student_id = request.args.get('student_id', type=int)

    if 'student_id' in session:
        logged_id = session['student_id']
        if target_student_id and target_student_id != logged_id:
            return jsonify({'error': 'Forbidden: Cannot access another student\'s marks'}), 403
        student = Student.query.get(logged_id)
    elif 'user_id' in session:
        staff_user = User.query.get(session['user_id'])
        if not staff_user or staff_user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
            return jsonify({'error': 'Unauthorized'}), 403
        if not target_student_id:
            return jsonify({'error': 'Missing student_id parameter'}), 400
        student = Student.query.get(target_student_id)
        if not student:
            return jsonify({'error': 'Student not found'}), 404
        if not is_user_authorized_for_class(staff_user, student.course, student.semester, student.section):
            return jsonify({'error': 'Forbidden: Class scope unauthorized'}), 403
    else:
        return jsonify({'error': 'Authentication required'}), 401

    if not student or not student.is_active:
        return jsonify({'error': 'Student inactive or not found'}), 404

    assessment_cycle = (request.args.get('assessment_cycle') or '2026-27').strip()

    timetable_subjects = db.session.query(
        Timetable.subject
    ).filter_by(
        course=student.course,
        semester=student.semester,
        section=student.section
    ).distinct().order_by(Timetable.subject).all()
    class_subjects = [s[0] for s in timetable_subjects]

    marks_rows = InternalMark.query.filter_by(
        student_id=student.id,
        course=student.course,
        semester=student.semester,
        section=student.section,
        assessment_cycle=assessment_cycle
    ).all()
    marks_by_subject = {m.subject: m for m in marks_rows}

    response_subjects = []
    for subj in class_subjects:
        mark_record = marks_by_subject.get(subj)
        subj_data = {
            'subject': subj,
            'components': {}
        }
        for comp in ['IA1', 'IA2', 'Final IA']:
            elig = evaluate_marks_eligibility(
                student_id=student.id,
                subject=subj,
                component=comp,
                assessment_cycle=assessment_cycle,
                course=student.course,
                semester=student.semester,
                section=student.section
            )
            if elig['can_view']:
                if mark_record:
                    if comp == 'IA1':
                        val = mark_record.ia1_marks
                    elif comp == 'IA2':
                        val = mark_record.ia2_marks
                    else:
                        val = mark_record.final_ia_marks
                else:
                    val = None
                subj_data['components'][comp] = {
                    'is_restricted': False,
                    'status': elig['status'],
                    'message': elig['public_message'],
                    'marks': val
                }
            else:
                subj_data['components'][comp] = {
                    'is_restricted': True,
                    'status': elig['status'],
                    'message': elig['public_message'],
                    'marks': None
                }
        response_subjects.append(subj_data)

    return jsonify({
        'student': {
            'id': student.id,
            'name': student.name,
            'uucms_id': student.uucms_id,
            'course': student.course,
            'semester': student.semester,
            'section': student.section
        },
        'assessment_cycle': assessment_cycle,
        'subjects': response_subjects
    })


# ==============================================================================
# MODULE A: ACADEMIC ASSIGNMENTS & SUBMISSION TRACKING ROUTES
# ==============================================================================

VALID_STUDY_MATERIAL_CATEGORIES = ['Textbooks', 'Previous Year Papers', 'Question Banks']

def parse_datetime_input(dt_str):
    if not dt_str:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            pass
    return None

def parse_date_input(d_str):
    if not d_str:
        return date.today()
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            pass
    return date.today()


@app.route('/academic/assignments', methods=['GET'])
@login_required
def assignments_dashboard():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized: Assignment Management is restricted to faculty members.', 'danger')
        return redirect(url_for('dashboard')), 403

    course = (request.args.get('course') or '').strip()
    semester = (request.args.get('semester') or '').strip()
    section = (request.args.get('section') or '').strip()
    subject = (request.args.get('subject') or '').strip()
    status_filter = (request.args.get('status') or '').strip()

    query = Assignment.query

    if user.role == 'Faculty':
        authorized_contexts = get_authorized_subject_contexts(user)
        fac_subjects = list({c['subject'] for c in authorized_contexts})
        query = query.filter(
            (Assignment.created_by_id == user.id) | (Assignment.subject.in_(fac_subjects))
        )
    elif user.role == 'HOD - BCA Dept':
        query = query.filter(Assignment.course == 'BCA')

    if course:
        query = query.filter(Assignment.course == course)
    if semester:
        query = query.filter(Assignment.semester == semester)
    if section:
        query = query.filter(Assignment.section == section)
    if subject:
        query = query.filter(Assignment.subject == subject)
    if status_filter:
        query = query.filter(Assignment.status == status_filter)

    assignments = query.order_by(Assignment.created_at.desc()).all()

    # Collect stats for each assignment
    enriched_assignments = []
    now = datetime.utcnow()
    for a in assignments:
        enrolled_count = Student.query.filter_by(
            course=a.course,
            semester=a.semester,
            section=a.section,
            is_active=True
        ).count()
        submissions = AssignmentSubmission.query.filter_by(assignment_id=a.id).all()
        submitted_count = sum(1 for s in submissions if s.status in ['Submitted', 'Late'])
        late_count = sum(1 for s in submissions if s.status == 'Late')
        not_submitted_count = max(0, enrolled_count - submitted_count)

        enriched_assignments.append({
            'assignment': a,
            'enrolled_count': enrolled_count,
            'submitted_count': submitted_count,
            'not_submitted_count': not_submitted_count,
            'late_count': late_count,
            'is_past_deadline': (now > a.deadline if a.deadline else False),
            'can_edit': can_manage_academic_resource(user, a.subject, {'course': a.course, 'semester': a.semester, 'section': a.section}, 'EDIT')
        })

    # Available subjects for filtering
    if user.role == 'Faculty':
        filter_subjects = list({c['subject'] for c in get_authorized_subject_contexts(user)})
    elif user.role == 'HOD - BCA Dept':
        filter_subjects = [r[0] for r in db.session.query(Timetable.subject).filter_by(course='BCA').distinct().all() if r[0]]
    else:
        filter_subjects = [r[0] for r in db.session.query(Timetable.subject).distinct().all() if r[0]]

    return render_template(
        'academic/assignments/dashboard.html',
        user=user,
        assignments=enriched_assignments,
        filter_subjects=sorted(filter_subjects),
        selected_course=course,
        selected_semester=semester,
        selected_section=section,
        selected_subject=subject,
        selected_status=status_filter
    )


@app.route('/academic/assignments/create', methods=['GET', 'POST'])
@login_required
def assignment_create():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized: Assignment creation is restricted to authorized faculty.', 'danger')
        return redirect(url_for('dashboard')), 403

    authorized_contexts = get_authorized_subject_contexts(user)

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        course = (request.form.get('course') or '').strip()
        academic_year = (request.form.get('academic_year') or '').strip()
        semester = (request.form.get('semester') or '').strip()
        section = (request.form.get('section') or 'A').strip()
        subject = (request.form.get('subject') or '').strip()
        assigned_date_str = (request.form.get('assigned_date') or '').strip()
        deadline_str = (request.form.get('deadline') or '').strip()
        max_marks_str = (request.form.get('max_marks') or '').strip()
        status = (request.form.get('status') or 'Published').strip()

        # 1. Validation of mandatory inputs
        if not title:
            flash('Error: Assignment Title is mandatory.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        if not description:
            flash('Error: Assignment Description / Instructions are mandatory.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        if not course or not academic_year or not semester or not subject or not deadline_str:
            flash('Error: Course, Academic Year, Semester, Subject, and Submission Deadline are mandatory.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        # 2. Scope & Hierarchy Validation
        if course not in VALID_COURSES:
            flash(f'Error: Invalid Course/Programme "{course}". Allowed: {", ".join(VALID_COURSES)}.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        if academic_year not in VALID_ACADEMIC_YEAR_SEMESTERS:
            flash(f'Error: Invalid Academic Year "{academic_year}". Allowed: {", ".join(VALID_ACADEMIC_YEARS)}.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        allowed_sems = VALID_ACADEMIC_YEAR_SEMESTERS.get(academic_year, [])
        if semester not in allowed_sems:
            flash(f'Error: Invalid Semester "{semester}" for {academic_year}. Valid semesters: {", ".join(allowed_sems)}.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        if section not in VALID_SECTIONS:
            flash(f'Error: Invalid Section "{section}".', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        # Teacher authorization
        scope = {'course': course, 'academic_year': academic_year, 'semester': semester, 'section': section}
        if not can_manage_academic_resource(user, subject, scope, 'CREATE'):
            flash(f'Access Denied: You are not authorized to create assignments for {subject} in {course} {semester} Sec {section}.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 403

        # Subject must belong to selected academic scope
        timetable_match = Timetable.query.filter_by(
            course=course,
            semester=semester,
            subject=subject
        ).first()
        if not timetable_match:
            flash(f'Error: Subject "{subject}" does not belong to {course} {semester}.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        # 3. Date Validation
        assigned_date = parse_date_input(assigned_date_str) if assigned_date_str else date.today()
        deadline = parse_datetime_input(deadline_str)
        if not deadline:
            flash('Error: Invalid deadline format.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        if deadline.date() < assigned_date:
            flash('Submission deadline cannot be earlier than the assigned date.', 'danger')
            return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        max_marks = None
        if max_marks_str:
            try:
                max_marks = float(max_marks_str)
                if max_marks <= 0:
                    flash('Maximum marks must be a positive number.', 'danger')
                    return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400
            except ValueError:
                flash('Maximum marks must be a valid number.', 'danger')
                return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        # 4. Attachment handling
        attachment_filename = None
        attachment_storage_key = None
        attachment_mimetype = None
        attachment_size = None

        if 'attachment' in request.files and request.files['attachment'].filename:
            file = request.files['attachment']
            is_valid, err_msg, clean_name, mimetype, fsize = validate_academic_file(file)
            if not is_valid:
                flash(f'Attachment Rejected: {err_msg}', 'danger')
                return render_template('academic/assignments/create.html', user=user, contexts=authorized_contexts, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

            storage_key, checksum, saved_size = save_academic_file(file, app.config['ASSIGNMENTS_STORAGE_FOLDER'], clean_name)
            attachment_filename = clean_name
            attachment_storage_key = storage_key
            attachment_mimetype = mimetype
            attachment_size = saved_size

        assignment = Assignment(
            title=title,
            description=description,
            course=course,
            semester=semester,
            section=section,
            subject=subject,
            academic_year=academic_year,
            assigned_date=assigned_date,
            deadline=deadline,
            max_marks=max_marks,
            status=status,
            attachment_filename=attachment_filename,
            attachment_storage_key=attachment_storage_key,
            attachment_mimetype=attachment_mimetype,
            attachment_size=attachment_size,
            created_by_id=user.id,
            updated_by_id=user.id
        )
        db.session.add(assignment)
        db.session.commit()

        # Audit
        record_academic_resource_audit(
            actor_user=user,
            action='CREATE',
            resource_type='ASSIGNMENT',
            resource_id=assignment.id,
            after_state={
                'title': title,
                'subject': subject,
                'course': course,
                'academic_year': academic_year,
                'semester': semester,
                'section': section,
                'deadline': str(deadline),
                'status': status
            },
            reason='Initial creation of assignment'
        )

        # Scoped Notifications to target class
        if status == 'Published':
            try:
                active_students = Student.query.filter_by(
                    course=course,
                    academic_year=academic_year,
                    semester=semester,
                    is_active=True
                )
                if section != 'ALL':
                    active_students = active_students.filter_by(section=section)
                for s in active_students.all():
                    create_notification(
                        recipient_type='STUDENT',
                        recipient_id=s.id,
                        title=f"New Assignment: {subject}",
                        message=f"Dear {s.name}, a new assignment '{title}' has been published by {user.full_name}. Due: {deadline.strftime('%d %b %Y %I:%M %p')}.",
                        category='assignments',
                        action_url=url_for('student_assignments'),
                        idempotency_key=f"asgn_pub_{assignment.public_id}_{s.id}",
                        sound=True
                    )
            except Exception as notif_e:
                logger.warning(f"Notification warning on assignment create: {notif_e}")

        flash(f"Assignment '{title}' created successfully for {subject} ({course} {semester} Sec {section}).", 'success')
        return redirect(url_for('assignments_dashboard'))

    return render_template(
        'academic/assignments/create.html',
        user=user,
        contexts=authorized_contexts,
        valid_courses=VALID_COURSES,
        valid_years=VALID_ACADEMIC_YEARS,
        valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS,
        valid_sections=VALID_SECTIONS,
        form_data={}
    )


@app.route('/academic/assignments/<int:assignment_id>', methods=['GET'])
@login_required
def assignment_detail(assignment_id):
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    assignment = Assignment.query.get_or_404(assignment_id)
    scope = {'course': assignment.course, 'semester': assignment.semester, 'section': assignment.section}
    if not is_user_authorized_for_class(user, assignment.course, assignment.semester, assignment.section):
        flash('Access Denied: You are not authorized to view assignments for this class.', 'danger')
        return redirect(url_for('assignments_dashboard')), 403

    enrolled_count = Student.query.filter_by(
        course=assignment.course,
        semester=assignment.semester,
        section=assignment.section,
        is_active=True
    ).count()

    submissions = AssignmentSubmission.query.filter_by(assignment_id=assignment.id).all()
    submitted_count = sum(1 for s in submissions if s.status in ['Submitted', 'Late'])
    late_count = sum(1 for s in submissions if s.status == 'Late')
    not_submitted_count = max(0, enrolled_count - submitted_count)

    can_edit = can_manage_academic_resource(user, assignment.subject, scope, 'EDIT') and (
        user.id == assignment.created_by_id or user.role in ['HOD - BCA Dept', 'Principal', 'admin']
    )

    audits = AcademicResourceAudit.query.filter_by(
        resource_type='ASSIGNMENT',
        resource_id=assignment.id
    ).order_by(AcademicResourceAudit.created_at.desc()).limit(15).all()

    return render_template(
        'academic/assignments/detail.html',
        user=user,
        assignment=assignment,
        enrolled_count=enrolled_count,
        submitted_count=submitted_count,
        not_submitted_count=not_submitted_count,
        late_count=late_count,
        can_edit=can_edit,
        audits=audits,
        now=datetime.utcnow()
    )


@app.route('/academic/assignments/<int:assignment_id>/edit', methods=['GET', 'POST'])
@login_required
def assignment_edit(assignment_id):
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    assignment = Assignment.query.get_or_404(assignment_id)
    scope = {'course': assignment.course, 'semester': assignment.semester, 'section': assignment.section}

    can_edit = can_manage_academic_resource(user, assignment.subject, scope, 'EDIT') and (
        user.id == assignment.created_by_id or user.role in ['HOD - BCA Dept', 'Principal', 'admin']
    )
    if not can_edit:
        flash('Access Denied: You are not authorized to edit this assignment.', 'danger')
        return redirect(url_for('assignment_detail', assignment_id=assignment.id)), 403

    has_submissions = len(assignment.submissions) > 0

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        deadline_str = (request.form.get('deadline') or '').strip()
        max_marks_str = (request.form.get('max_marks') or '').strip()
        status = (request.form.get('status') or assignment.status).strip()
        reason = (request.form.get('reason') or 'Teacher update').strip()

        if not title or not description or not deadline_str:
            flash('Title, Description, and Deadline are required.', 'danger')
            return render_template('academic/assignments/edit.html', user=user, assignment=assignment, has_submissions=has_submissions)

        new_deadline = parse_datetime_input(deadline_str)
        if not new_deadline:
            flash('Invalid deadline format.', 'danger')
            return render_template('academic/assignments/edit.html', user=user, assignment=assignment, has_submissions=has_submissions)

        if new_deadline.date() < assignment.assigned_date:
            flash('Submission deadline cannot precede the assigned date.', 'danger')
            return render_template('academic/assignments/edit.html', user=user, assignment=assignment, has_submissions=has_submissions)

        max_marks = assignment.max_marks
        if max_marks_str:
            try:
                max_marks = float(max_marks_str)
            except ValueError:
                pass

        before_state = {
            'title': assignment.title,
            'description': assignment.description,
            'deadline': str(assignment.deadline),
            'max_marks': assignment.max_marks,
            'status': assignment.status
        }

        deadline_changed = (assignment.deadline != new_deadline)

        assignment.title = title
        assignment.description = description
        assignment.deadline = new_deadline
        assignment.max_marks = max_marks
        assignment.status = status
        assignment.updated_by_id = user.id

        # File Replacement Handling
        if 'attachment' in request.files and request.files['attachment'].filename:
            file = request.files['attachment']
            is_valid, err_msg, clean_name, mimetype, fsize = validate_academic_file(file)
            if not is_valid:
                flash(f'Attachment Rejected: {err_msg}', 'danger')
                return render_template('academic/assignments/edit.html', user=user, assignment=assignment, has_submissions=has_submissions)

            old_storage_key = assignment.attachment_storage_key
            storage_key, checksum, saved_size = save_academic_file(file, app.config['ASSIGNMENTS_STORAGE_FOLDER'], clean_name)
            assignment.attachment_filename = clean_name
            assignment.attachment_storage_key = storage_key
            assignment.attachment_mimetype = mimetype
            assignment.attachment_size = saved_size
            if old_storage_key:
                remove_academic_file(old_storage_key, app.config['ASSIGNMENTS_STORAGE_FOLDER'])

        db.session.commit()

        # Audit
        after_state = {
            'title': assignment.title,
            'description': assignment.description,
            'deadline': str(assignment.deadline),
            'max_marks': assignment.max_marks,
            'status': assignment.status
        }
        record_academic_resource_audit(
            actor_user=user,
            action='UPDATE',
            resource_type='ASSIGNMENT',
            resource_id=assignment.id,
            before_state=before_state,
            after_state=after_state,
            reason=reason
        )

        # Notify students if deadline changed on a published assignment
        if deadline_changed and assignment.status == 'Published':
            try:
                active_students = Student.query.filter_by(
                    course=assignment.course,
                    semester=assignment.semester,
                    section=assignment.section,
                    is_active=True
                ).all()
                for s in active_students:
                    dispatch_notification(
                        user=s,
                        event='assignment_deadline_updated',
                        context={
                            'title': assignment.title,
                            'subject': assignment.subject,
                            'deadline': assignment.deadline.strftime('%Y-%m-%d %I:%M %p'),
                            'course': assignment.course,
                            'semester': assignment.semester,
                            'section': assignment.section
                        }
                    )
            except Exception as e:
                print(f"Deadline notification warning: {e}")

        if deadline_changed:
            notify_class_students(
                course=assignment.course,
                semester=assignment.semester,
                section=assignment.section,
                title=f"Assignment Deadline Revised: {assignment.subject}",
                message=f"Deadline for '{assignment.title}' extended to {assignment.deadline.strftime('%d %b %Y %I:%M %p')}.",
                category='assignments',
                action_url=url_for('student_assignments'),
                idempotency_prefix=f"asgn_rev_{assignment.id}_{int(datetime.utcnow().timestamp() // 60)}",
                sound=True
            )
        flash(f"Assignment '{assignment.title}' updated successfully.", 'success')
        return redirect(url_for('assignment_detail', assignment_id=assignment.id))

    return render_template('academic/assignments/edit.html', user=user, assignment=assignment, has_submissions=has_submissions)


@app.route('/academic/assignments/<int:assignment_id>/archive', methods=['POST'])
@login_required
def assignment_archive(assignment_id):
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard')), 403

    assignment = Assignment.query.get_or_404(assignment_id)
    scope = {'course': assignment.course, 'semester': assignment.semester, 'section': assignment.section}
    if not can_manage_academic_resource(user, assignment.subject, scope, 'ARCHIVE'):
        flash('Access Denied: You cannot archive this assignment.', 'danger')
        return redirect(url_for('assignments_dashboard')), 403

    assignment.status = 'Archived'
    assignment.updated_by_id = user.id
    db.session.commit()

    record_academic_resource_audit(
        actor_user=user,
        action='ARCHIVE',
        resource_type='ASSIGNMENT',
        resource_id=assignment.id,
        reason='Assignment moved to archived status'
    )
    flash(f"Assignment '{assignment.title}' has been archived.", 'info')
    return redirect(url_for('assignments_dashboard'))


@app.route('/academic/assignments/<int:assignment_id>/roster', methods=['GET'])
@login_required
def assignment_roster(assignment_id):
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    assignment = Assignment.query.get_or_404(assignment_id)
    if not is_user_authorized_for_class(user, assignment.course, assignment.semester, assignment.section):
        flash('Access Denied.', 'danger')
        return redirect(url_for('assignments_dashboard')), 403

    status_filter = (request.args.get('status') or '').strip()

    students = Student.query.filter_by(
        course=assignment.course,
        semester=assignment.semester,
        section=assignment.section,
        is_active=True
    ).order_by(Student.name.asc()).all()

    existing_subs = {
        s.student_id: s
        for s in AssignmentSubmission.query.filter_by(assignment_id=assignment.id).all()
    }

    now = datetime.utcnow()
    roster_rows = []
    for s in students:
        sub = existing_subs.get(s.id)
        if sub:
            final_status = sub.status
            is_submitted = True
        else:
            is_submitted = False
            if assignment.deadline and now > assignment.deadline:
                final_status = 'Not submitted'
            else:
                final_status = 'Pending'

        if status_filter:
            if status_filter == 'Submitted' and final_status not in ['Submitted', 'Late']:
                continue
            elif status_filter == 'Not submitted' and final_status != 'Not submitted':
                continue
            elif status_filter == 'Late' and final_status != 'Late':
                continue

        roster_rows.append({
            'student': s,
            'submission': sub,
            'status': final_status,
            'is_submitted': is_submitted,
            'submitted_at': sub.submitted_at if sub else None,
            'marks_obtained': sub.marks_obtained if sub else None,
            'feedback': sub.teacher_feedback if sub else None
        })

    return render_template(
        'academic/assignments/roster.html',
        user=user,
        assignment=assignment,
        roster_rows=roster_rows,
        selected_status=status_filter,
        now=now
    )


@app.route('/academic/assignments/<int:assignment_id>/submission/record-status', methods=['POST'])
@login_required
def record_submission_status(assignment_id):
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard')), 403

    assignment = Assignment.query.get_or_404(assignment_id)
    scope = {'course': assignment.course, 'semester': assignment.semester, 'section': assignment.section}
    if not can_manage_academic_resource(user, assignment.subject, scope, 'GRADE'):
        flash('Access Denied: You are not authorized to record submission status for this subject.', 'danger')
        return redirect(url_for('assignment_roster', assignment_id=assignment.id)), 403

    student_id = request.form.get('student_id', type=int)
    new_status = (request.form.get('status') or 'Submitted').strip()
    marks_str = (request.form.get('marks_obtained') or '').strip()
    feedback = (request.form.get('teacher_feedback') or '').strip()

    student = Student.query.get_or_404(student_id)
    if student.course != assignment.course or student.semester != assignment.semester or student.section != assignment.section:
        flash('Student does not belong to this assignment class.', 'danger')
        return redirect(url_for('assignment_roster', assignment_id=assignment.id)), 400

    marks_val = None
    if marks_str:
        try:
            marks_val = float(marks_str)
            if marks_val < 0 or (assignment.max_marks and marks_val > assignment.max_marks):
                flash(f'Marks must be between 0 and {assignment.max_marks or 100}.', 'danger')
                return redirect(url_for('assignment_roster', assignment_id=assignment.id))
        except ValueError:
            flash('Marks must be a valid number.', 'danger')
            return redirect(url_for('assignment_roster', assignment_id=assignment.id))

    sub = AssignmentSubmission.query.filter_by(
        assignment_id=assignment.id,
        student_id=student.id
    ).first()

    now = datetime.utcnow()
    if sub:
        before_status = sub.status
        sub.status = new_status
        sub.marks_obtained = marks_val
        sub.teacher_feedback = feedback
        sub.graded_by_id = user.id
        sub.graded_at = now
        sub.last_status_changed_by_id = user.id
        sub.last_status_changed_at = now
        if not sub.submitted_at and new_status in ['Submitted', 'Late']:
            sub.submitted_at = now
            sub.status_source = 'TEACHER_RECORDED'
    else:
        sub = AssignmentSubmission(
            assignment_id=assignment.id,
            student_id=student.id,
            status=new_status,
            status_source='TEACHER_RECORDED',
            submitted_at=now if new_status in ['Submitted', 'Late'] else None,
            marks_obtained=marks_val,
            teacher_feedback=feedback,
            graded_by_id=user.id,
            graded_at=now,
            last_status_changed_by_id=user.id,
            last_status_changed_at=now
        )
        db.session.add(sub)

    db.session.commit()

    record_academic_resource_audit(
        actor_user=user,
        action='STATUS_CHANGE',
        resource_type='SUBMISSION',
        resource_id=sub.id,
        after_state={'student_id': student.id, 'status': new_status, 'marks': marks_val},
        reason=f"Teacher recorded status as {new_status}"
    )
    create_notification(
        recipient_type='STUDENT',
        recipient_id=student.id,
        title=f"Assignment Evaluated: {assignment.subject}",
        message=f"Your submission for '{assignment.title}' was reviewed by {user.full_name} (Status: {new_status}).",
        category='assignments',
        action_url=url_for('student_assignments'),
        idempotency_key=f"eval_{sub.id}_{int(datetime.utcnow().timestamp() // 60)}",
        sound=True
    )

    flash(f"Submission status updated for {student.name}.", 'success')
    return redirect(url_for('assignment_roster', assignment_id=assignment.id))


@app.route('/academic/assignments/<int:assignment_id>/download', methods=['GET'])
def download_assignment_attachment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    if not assignment.attachment_storage_key:
        flash('This assignment has no attached file.', 'warning')
        return abort(404)

    if 'student_id' in session:
        student = Student.query.get(session['student_id'])
        if not student or not student.is_active:
            return abort(403)
        if assignment.course != student.course or assignment.academic_year != student.academic_year or assignment.semester != student.semester or (assignment.section not in [student.section, 'ALL']):
            flash('Access Restricted: This assignment is not in your academic cohort.', 'danger')
            return abort(403)
        scope = {'course': assignment.course, 'academic_year': assignment.academic_year, 'semester': assignment.semester, 'section': assignment.section}
        decision = get_academic_content_access_decision(
            user=None,
            student=student,
            subject=assignment.subject,
            academic_scope=scope,
            resource_type='ASSIGNMENT',
            evaluation_date=assignment.assigned_date
        )
        if not decision['can_view']:
            flash('Access Restricted: Attendance threshold not met for this subject.', 'danger')
            return abort(403)
    elif 'user_id' in session:
        user = User.query.get(session['user_id'])
        if not is_user_authorized_for_class(user, assignment.course, assignment.semester, assignment.section):
            return abort(403)
    else:
        return redirect(url_for('login'))

    file_path = os.path.join(app.config['ASSIGNMENTS_STORAGE_FOLDER'], assignment.attachment_storage_key)
    if not os.path.exists(file_path):
        return abort(404)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=assignment.attachment_filename or 'assignment_attachment.pdf',
        mimetype=assignment.attachment_mimetype or 'application/octet-stream'
    )


@app.route('/academic/assignments/submission/<int:submission_id>/download', methods=['GET'])
def download_submission_file(submission_id):
    submission = AssignmentSubmission.query.get_or_404(submission_id)
    if not submission.file_storage_key:
        flash('No file attached to this submission record.', 'warning')
        return abort(404)

    assignment = submission.assignment
    if 'student_id' in session:
        logged_student_id = session['student_id']
        # Strict isolation: A student can ONLY download their own submission file!
        if submission.student_id != logged_student_id:
            flash('Security Violation: You are not authorized to access another student\'s submission.', 'danger')
            return abort(403)
    elif 'user_id' in session:
        user = User.query.get(session['user_id'])
        if not is_user_authorized_for_class(user, assignment.course, assignment.semester, assignment.section):
            flash('Access Denied: You are not authorized to inspect submissions for this class.', 'danger')
            return abort(403)
    else:
        return redirect(url_for('login'))

    file_path = os.path.join(app.config['SUBMISSIONS_STORAGE_FOLDER'], submission.file_storage_key)
    if not os.path.exists(file_path):
        return abort(404)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=submission.file_filename or 'submission.pdf',
        mimetype=submission.file_mimetype or 'application/octet-stream'
    )


# ==============================================================================
# STUDENT ASSIGNMENT PORTAL ROUTES
# ==============================================================================

@app.route('/student/assignments', methods=['GET'])
def student_assignments():
    if 'student_id' not in session:
        flash('Please login to the Student Academic Portal.', 'info')
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    if not student or not student.is_active:
        session.clear()
        flash('Invalid session. Please login again.', 'warning')
        return redirect(url_for('student_login'))

    assignments = Assignment.query.filter(
        Assignment.course == student.course,
        Assignment.academic_year == student.academic_year,
        Assignment.semester == student.semester,
        Assignment.section.in_([student.section, 'ALL']),
        Assignment.status == 'Published'
    ).order_by(Assignment.deadline.asc()).all()

    existing_subs = {
        s.assignment_id: s
        for s in AssignmentSubmission.query.filter_by(student_id=student.id).all()
    }

    cards = []
    now = datetime.utcnow()
    for a in assignments:
        scope = {'course': a.course, 'semester': a.semester, 'section': a.section}
        decision = get_academic_content_access_decision(
            user=None,
            student=student,
            subject=a.subject,
            academic_scope=scope,
            resource_type='ASSIGNMENT',
            evaluation_date=a.assigned_date
        )

        sub = existing_subs.get(a.id)

        cards.append({
            'assignment': a,
            'is_accessible': decision['can_view'],
            'access_decision': decision,
            'submission': sub,
            'has_submitted': (sub is not None and sub.status in ['Submitted', 'Late']),
            'is_past_deadline': (now > a.deadline if a.deadline else False)
        })

    return render_template(
        'student_assignments.html',
        student=student,
        cards=cards,
        now=now
    )


@app.route('/student/assignments/<int:assignment_id>', methods=['GET'])
def student_assignment_detail(assignment_id):
    if 'student_id' not in session:
        flash('Please login to the Student Academic Portal.', 'info')
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    assignment = Assignment.query.get_or_404(assignment_id)

    # Class Scope Check
    if assignment.course != student.course or assignment.academic_year != student.academic_year or assignment.semester != student.semester or (assignment.section not in [student.section, 'ALL']):
        flash('Unauthorized: This assignment is not published for your class.', 'danger')
        return abort(403)

    scope = {'course': assignment.course, 'semester': assignment.semester, 'section': assignment.section}
    decision = get_academic_content_access_decision(
        user=None,
        student=student,
        subject=assignment.subject,
        academic_scope=scope,
        resource_type='ASSIGNMENT',
        evaluation_date=assignment.assigned_date
    )

    if not decision['can_view']:
        flash(f'Viewing Restricted: {decision["public_message"]}', 'danger')
        return render_template(
            'student_assignment_restricted.html',
            student=student,
            assignment=assignment,
            decision=decision
        ), 403

    submission = AssignmentSubmission.query.filter_by(
        assignment_id=assignment.id,
        student_id=student.id
    ).first()

    now = datetime.utcnow()
    is_past_deadline = (now > assignment.deadline if assignment.deadline else False)

    return render_template(
        'student_assignment_detail.html',
        student=student,
        assignment=assignment,
        submission=submission,
        is_past_deadline=is_past_deadline,
        decision=decision
    )


@app.route('/student/assignments/<int:assignment_id>/submit', methods=['POST'])
def student_assignment_submit(assignment_id):
    if 'student_id' not in session:
        flash('Please login to submit assignments.', 'info')
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    assignment = Assignment.query.get_or_404(assignment_id)

    # Class Scope Check
    if assignment.course != student.course or assignment.academic_year != student.academic_year or assignment.semester != student.semester or (assignment.section not in [student.section, 'ALL']):
        flash('Unauthorized: This assignment is not published for your class.', 'danger')
        return abort(403)

    # Policy Check
    scope = {'course': assignment.course, 'semester': assignment.semester, 'section': assignment.section}
    decision = get_academic_content_access_decision(
        user=None,
        student=student,
        subject=assignment.subject,
        academic_scope=scope,
        resource_type='ASSIGNMENT',
        evaluation_date=assignment.assigned_date
    )
    if not decision['can_view']:
        flash('Access Denied: Subject attendance restriction in place.', 'danger')
        return abort(403)

    if assignment.status != 'Published':
        flash('This assignment is not accepting submissions.', 'danger')
        return redirect(url_for('student_assignment_detail', assignment_id=assignment.id))

    if 'file' not in request.files or not request.files['file'].filename:
        flash('Please choose a file to upload.', 'danger')
        return redirect(url_for('student_assignment_detail', assignment_id=assignment.id))

    file = request.files['file']
    is_valid, err_msg, clean_name, mimetype, fsize = validate_academic_file(file)
    if not is_valid:
        flash(f'Upload Rejected: {err_msg}', 'danger')
        return redirect(url_for('student_assignment_detail', assignment_id=assignment.id))

    student_comment = (request.form.get('student_comment') or '').strip()

    now = datetime.utcnow()
    is_late = (assignment.deadline and now > assignment.deadline)
    submission_status = 'Late' if is_late else 'Submitted'

    storage_key, checksum, saved_size = save_academic_file(file, app.config['SUBMISSIONS_STORAGE_FOLDER'], clean_name)

    submission = AssignmentSubmission.query.filter_by(
        assignment_id=assignment.id,
        student_id=student.id
    ).first()

    if submission:
        old_key = submission.file_storage_key
        submission.status = submission_status
        submission.status_source = 'STUDENT_UPLOAD'
        submission.submitted_at = now
        submission.file_filename = clean_name
        submission.file_storage_key = storage_key
        submission.file_mimetype = mimetype
        submission.file_size = saved_size
        submission.version += 1
        submission.student_comment = student_comment
        if old_key:
            remove_academic_file(old_key, app.config['SUBMISSIONS_STORAGE_FOLDER'])
    else:
        submission = AssignmentSubmission(
            assignment_id=assignment.id,
            student_id=student.id,
            status=submission_status,
            status_source='STUDENT_UPLOAD',
            submitted_at=now,
            file_filename=clean_name,
            file_storage_key=storage_key,
            file_mimetype=mimetype,
            file_size=saved_size,
            version=1,
            student_comment=student_comment
        )
        db.session.add(submission)

    db.session.commit()

    record_academic_resource_audit(
        actor_student=student,
        action='SUBMIT',
        resource_type='SUBMISSION',
        resource_id=submission.id,
        after_state={'version': submission.version, 'status': submission_status, 'filename': clean_name},
        reason='Student uploaded assignment solution'
    )
    if assignment.created_by_id:
        create_notification(
            recipient_type='USER',
            recipient_id=assignment.created_by_id,
            title=f"Assignment Submission: {assignment.subject}",
            message=f"{student.name} ({student.uucms_id}) submitted '{assignment.title}'.",
            category='assignments',
            action_url=url_for('assignment_roster', assignment_id=assignment.id),
            idempotency_key=f"asgn_sub_{assignment.id}_{student.id}_{submission.version}",
            sound=True
        )

    if is_late:
        flash(f"Assignment submitted successfully (Marked as LATE - Deadline was {assignment.deadline.strftime('%Y-%m-%d %I:%M %p')}).", 'warning')
    else:
        flash("Assignment submitted successfully!", 'success')

    return redirect(url_for('student_assignment_detail', assignment_id=assignment.id))


# ==============================================================================
# MODULE B: STUDY MATERIALS LIBRARY ROUTES (STAFF & STUDENT)
# ==============================================================================

@app.route('/academic/study-materials', methods=['GET'])
@login_required
def study_materials_library():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    category = (request.args.get('category') or '').strip()
    course = (request.args.get('course') or '').strip()
    semester = (request.args.get('semester') or '').strip()
    subject = (request.args.get('subject') or '').strip()
    search = (request.args.get('search') or '').strip()

    query = StudyMaterial.query

    if user.role == 'Faculty':
        authorized_contexts = get_authorized_subject_contexts(user)
        fac_subjects = list({c['subject'] for c in authorized_contexts})
        query = query.filter(
            (StudyMaterial.created_by_id == user.id) | (StudyMaterial.subject.in_(fac_subjects))
        )
    elif user.role == 'HOD - BCA Dept':
        query = query.filter(StudyMaterial.course == 'BCA')

    if category and category in VALID_STUDY_MATERIAL_CATEGORIES:
        query = query.filter(StudyMaterial.category == category)
    if course:
        query = query.filter(StudyMaterial.course == course)
    if semester:
        query = query.filter(StudyMaterial.semester == semester)
    if subject:
        query = query.filter(StudyMaterial.subject == subject)
    if search:
        search_pat = f"%{search}%"
        query = query.filter(
            (StudyMaterial.title.ilike(search_pat)) |
            (StudyMaterial.description.ilike(search_pat)) |
            (StudyMaterial.tags.ilike(search_pat))
        )

    materials = query.order_by(StudyMaterial.created_at.desc()).all()

    # Available subjects for filtering
    if user.role == 'Faculty':
        available_subjects = sorted(list({c['subject'] for c in get_authorized_subject_contexts(user)}))
    elif user.role == 'HOD - BCA Dept':
        available_subjects = sorted([r[0] for r in db.session.query(Timetable.subject).filter_by(course='BCA').distinct().all() if r[0]])
    else:
        available_subjects = sorted([r[0] for r in db.session.query(Timetable.subject).distinct().all() if r[0]])

    return render_template(
        'academic/study_materials/library.html',
        user=user,
        materials=materials,
        categories=VALID_STUDY_MATERIAL_CATEGORIES,
        available_subjects=available_subjects,
        selected_category=category,
        selected_course=course,
        selected_semester=semester,
        selected_subject=subject,
        search_query=search
    )


@app.route('/academic/study-materials/upload', methods=['GET', 'POST'])
@login_required
def study_material_upload():
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard')), 403

    authorized_contexts = get_authorized_subject_contexts(user)

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        category = (request.form.get('category') or '').strip()
        course = (request.form.get('course') or '').strip()
        academic_year = (request.form.get('academic_year') or '').strip()
        semester = (request.form.get('semester') or '').strip()
        section = (request.form.get('section') or 'ALL').strip()
        subject = (request.form.get('subject') or '').strip()
        unit_or_chapter = (request.form.get('unit_or_chapter') or '').strip()
        exam_year = (request.form.get('exam_year') or '').strip()
        tags = (request.form.get('tags') or '').strip()
        status = (request.form.get('status') or 'Published').strip()

        # 1. Mandatory checks
        if not title:
            flash('Error: Material Title is mandatory.', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        if not category or not course or not academic_year or not semester or not subject:
            flash('Error: Category, Course, Academic Year, Semester, and Subject are mandatory.', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        # 2. Category check: Exactly the 3 required categories
        if category not in VALID_STUDY_MATERIAL_CATEGORIES:
            flash(f'Error: Invalid Category "{category}". Permitted categories: {", ".join(VALID_STUDY_MATERIAL_CATEGORIES)}.', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        # 3. Scope validation
        if course not in VALID_COURSES:
            flash(f'Error: Invalid Course/Programme "{course}". Allowed: {", ".join(VALID_COURSES)}.', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        if academic_year not in VALID_ACADEMIC_YEAR_SEMESTERS:
            flash(f'Error: Invalid Academic Year "{academic_year}". Allowed: {", ".join(VALID_ACADEMIC_YEARS)}.', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        allowed_sems = VALID_ACADEMIC_YEAR_SEMESTERS.get(academic_year, [])
        if semester not in allowed_sems:
            flash(f'Error: Invalid Semester "{semester}" for {academic_year}. Valid: {", ".join(allowed_sems)}.', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        # Teacher authorization
        scope = {'course': course, 'academic_year': academic_year, 'semester': semester, 'section': section}
        if not can_manage_academic_resource(user, subject, scope, 'CREATE'):
            flash(f'Access Denied: You are not authorized to upload materials for {subject} in {course} {semester}.', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 403

        # Verify subject belongs to scope in timetable
        timetable_match = Timetable.query.filter_by(
            course=course,
            semester=semester,
            subject=subject
        ).first()
        if not timetable_match:
            flash(f'Error: Subject "{subject}" is not configured for {course} {semester}.', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        # 4. File validation
        if 'file' not in request.files or not request.files['file'].filename:
            flash('Error: Please select a study material document to upload.', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        file = request.files['file']
        is_valid, err_msg, clean_name, mimetype, fsize = validate_academic_file(file)
        if not is_valid:
            flash(f'File Rejected: {err_msg}', 'danger')
            return render_template('academic/study_materials/upload.html', user=user, contexts=authorized_contexts, categories=VALID_STUDY_MATERIAL_CATEGORIES, valid_courses=VALID_COURSES, valid_years=VALID_ACADEMIC_YEARS, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS, valid_sections=VALID_SECTIONS, form_data=request.form), 400

        storage_key, checksum, saved_size = save_academic_file(file, app.config['STUDY_MATERIALS_STORAGE_FOLDER'], clean_name)

        material = StudyMaterial(
            title=title,
            description=description,
            category=category,
            subject=subject,
            course=course,
            semester=semester,
            section=section,
            academic_year=academic_year,
            unit_or_chapter=unit_or_chapter,
            exam_year=exam_year,
            tags=tags,
            file_filename=clean_name,
            file_storage_key=storage_key,
            file_mimetype=mimetype,
            file_size=saved_size,
            file_checksum=checksum,
            status=status,
            created_by_id=user.id,
            updated_by_id=user.id
        )
        db.session.add(material)
        db.session.commit()

        record_academic_resource_audit(
            actor_user=user,
            action='CREATE',
            resource_type='STUDY_MATERIAL',
            resource_id=material.id,
            after_state={'title': title, 'category': category, 'subject': subject, 'academic_year': academic_year, 'course': course, 'semester': semester},
            reason='Initial material upload'
        )
        if status == 'Published':
            try:
                active_students = Student.query.filter_by(
                    course=course,
                    academic_year=academic_year,
                    semester=semester,
                    is_active=True
                )
                if section != 'ALL':
                    active_students = active_students.filter_by(section=section)
                for s in active_students.all():
                    create_notification(
                        recipient_type='STUDENT',
                        recipient_id=s.id,
                        title=f"New Study Material: {subject}",
                        message=f"Dear {s.name}, new resource '{title}' ({category}) has been uploaded by {user.full_name}.",
                        category='study_materials',
                        action_url=url_for('student_study_materials', category=category),
                        idempotency_key=f"mat_pub_{material.public_id}_{s.id}",
                        sound=True
                    )
            except Exception as notif_e:
                print(f"Notification warning on study material upload: {notif_e}")

        flash(f"Material '{title}' ({category}) uploaded successfully.", 'success')
        return redirect(url_for('study_materials_library', category=category))

    return render_template(
        'academic/study_materials/upload.html',
        user=user,
        contexts=authorized_contexts,
        categories=VALID_STUDY_MATERIAL_CATEGORIES,
        valid_courses=VALID_COURSES,
        valid_years=VALID_ACADEMIC_YEARS,
        valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS,
        valid_sections=VALID_SECTIONS,
        form_data={}
    )


@app.route('/academic/study-materials/<int:material_id>/edit', methods=['GET', 'POST'])
@login_required
def study_material_edit(material_id):
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard')), 403

    material = StudyMaterial.query.get_or_404(material_id)
    scope = {'course': material.course, 'semester': material.semester, 'section': material.section}
    if not can_manage_academic_resource(user, material.subject, scope, 'EDIT') or (user.id != material.created_by_id and user.role not in ['HOD - BCA Dept', 'Principal', 'admin']):
        flash('Access Denied: You cannot edit this material.', 'danger')
        return redirect(url_for('study_materials_library')), 403

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        unit_or_chapter = (request.form.get('unit_or_chapter') or '').strip()
        exam_year = (request.form.get('exam_year') or '').strip()
        tags = (request.form.get('tags') or '').strip()
        status = (request.form.get('status') or material.status).strip()

        if not title:
            flash('Title cannot be empty.', 'danger')
            return render_template('academic/study_materials/edit.html', user=user, material=material, categories=VALID_STUDY_MATERIAL_CATEGORIES)

        before_state = {'title': material.title, 'status': material.status}

        material.title = title
        material.description = description
        material.unit_or_chapter = unit_or_chapter
        material.exam_year = exam_year
        material.tags = tags
        material.status = status
        material.updated_by_id = user.id

        if 'file' in request.files and request.files['file'].filename:
            file = request.files['file']
            is_valid, err_msg, clean_name, mimetype, fsize = validate_academic_file(file)
            if not is_valid:
                flash(f'File Rejected: {err_msg}', 'danger')
                return render_template('academic/study_materials/edit.html', user=user, material=material, categories=VALID_STUDY_MATERIAL_CATEGORIES)

            old_key = material.file_storage_key
            storage_key, checksum, saved_size = save_academic_file(file, app.config['STUDY_MATERIALS_STORAGE_FOLDER'], clean_name)
            material.file_filename = clean_name
            material.file_storage_key = storage_key
            material.file_mimetype = mimetype
            material.file_size = saved_size
            material.file_checksum = checksum
            if old_key:
                remove_academic_file(old_key, app.config['STUDY_MATERIALS_STORAGE_FOLDER'])

        db.session.commit()

        record_academic_resource_audit(
            actor_user=user,
            action='UPDATE',
            resource_type='STUDY_MATERIAL',
            resource_id=material.id,
            before_state=before_state,
            after_state={'title': material.title, 'status': material.status},
            reason='Teacher edited material metadata'
        )

        flash(f"Material '{material.title}' updated successfully.", 'success')
        return redirect(url_for('study_materials_library', category=material.category))

    return render_template('academic/study_materials/edit.html', user=user, material=material, categories=VALID_STUDY_MATERIAL_CATEGORIES)


@app.route('/academic/study-materials/<int:material_id>/archive', methods=['POST'])
@login_required
def study_material_archive(material_id):
    user = User.query.get(session.get('user_id'))
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard')), 403

    material = StudyMaterial.query.get_or_404(material_id)
    scope = {'course': material.course, 'semester': material.semester, 'section': material.section}
    if not can_manage_academic_resource(user, material.subject, scope, 'ARCHIVE'):
        flash('Access Denied.', 'danger')
        return redirect(url_for('study_materials_library')), 403

    material.status = 'Archived'
    material.updated_by_id = user.id
    db.session.commit()

    record_academic_resource_audit(
        actor_user=user,
        action='ARCHIVE',
        resource_type='STUDY_MATERIAL',
        resource_id=material.id,
        reason='Material moved to archived status'
    )
    flash(f"Material '{material.title}' has been archived.", 'info')
    return redirect(url_for('study_materials_library', category=material.category))


@app.route('/academic/study-materials/<int:material_id>/download', methods=['GET'])
def download_study_material(material_id):
    material = StudyMaterial.query.get_or_404(material_id)
    if material.status != 'Published' and 'user_id' not in session:
        return abort(404)

    if 'student_id' in session:
        student = Student.query.get(session['student_id'])
        if not student or not student.is_active:
            return abort(403)
        if material.course != student.course or material.academic_year != student.academic_year or material.semester != student.semester or (material.section not in [student.section, 'ALL']):
            flash('Access Restricted: This study material is not in your academic cohort.', 'danger')
            return abort(403)
        scope = {'course': material.course, 'academic_year': material.academic_year, 'semester': material.semester, 'section': material.section}
        decision = get_academic_content_access_decision(
            user=None,
            student=student,
            subject=material.subject,
            academic_scope=scope,
            resource_type='STUDY_MATERIAL',
            evaluation_date=material.created_at.date()
        )
        if not decision['can_view']:
            flash('Access Restricted: You are not authorized to download this study material.', 'danger')
            return abort(403)
    elif 'user_id' in session:
        user = User.query.get(session['user_id'])
        scope = {'course': material.course, 'semester': material.semester, 'section': material.section}
        if not can_manage_academic_resource(user, material.subject, scope, action='VIEW'):
            flash('Access Denied: You are not authorized for this study material.', 'danger')
            return abort(403)
    else:
        return redirect(url_for('login'))

    file_path = os.path.join(app.config['STUDY_MATERIALS_STORAGE_FOLDER'], material.file_storage_key)
    if not os.path.exists(file_path):
        flash('File not found in storage repository.', 'danger')
        return abort(404)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=material.file_filename,
        mimetype=material.file_mimetype
    )



# ==============================================================================
# STUDENT SEMESTER TIMETABLE MODULE (INDEPENDENT FROM TEACHER TIMETABLE)
# ==============================================================================

VALID_ACADEMIC_YEAR_SEMESTERS = {
    '1st Year': ['Sem I', 'Sem II'],
    '2nd Year': ['Sem III', 'Sem IV'],
    '3rd Year': ['Sem V', 'Sem VI']
}
VALID_TIMETABLE_COURSES = ['BCA', 'B.Com', 'BBA']
VALID_TIMETABLE_SECTIONS = ['A', 'B', 'ALL']


@app.route('/academic/student-timetables', methods=['GET'])
@login_required
def student_timetables_dashboard():
    user = User.query.get(session['user_id'])
    if not user or not (user.role in ['Faculty', 'teacher', 'HOD - BCA Dept', 'Principal', 'admin', 'HR'] or user.username == 'admin'):
        flash("Access Denied: You are not authorized to manage student semester timetables.", "danger")
        return redirect(url_for('dashboard')), 403

    selected_course = request.args.get('course', 'all')
    selected_year = request.args.get('academic_year', 'all')
    selected_semester = request.args.get('semester', 'all')
    selected_section = request.args.get('section', 'all')
    status_filter = request.args.get('status', 'all')

    query = StudentSemesterTimetable.query
    if selected_course != 'all':
        query = query.filter_by(course=selected_course)
    if selected_year != 'all':
        query = query.filter_by(academic_year=selected_year)
    if selected_semester != 'all':
        query = query.filter_by(semester=selected_semester)
    if selected_section != 'all':
        query = query.filter_by(section=selected_section)
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    timetables = query.order_by(
        StudentSemesterTimetable.status.asc(),
        StudentSemesterTimetable.updated_at.desc()
    ).all()

    return render_template(
        'academic/student_timetables/dashboard.html',
        user=user,
        timetables=timetables,
        selected_course=selected_course,
        selected_year=selected_year,
        selected_semester=selected_semester,
        selected_section=selected_section,
        status_filter=status_filter,
        valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS
    )


@app.route('/academic/student-timetables/upload', methods=['GET', 'POST'])
@login_required
def student_timetables_upload():
    user = User.query.get(session['user_id'])
    if not user or not (user.role in ['Faculty', 'teacher', 'HOD - BCA Dept', 'Principal', 'admin', 'HR'] or user.username == 'admin'):
        flash("Access Denied: You are not authorized to upload student semester timetables.", "danger")
        return redirect(url_for('dashboard')), 403

    if request.method == 'POST':
        course = (request.form.get('course') or 'BCA').strip()
        academic_year = (request.form.get('academic_year') or '').strip()
        semester = (request.form.get('semester') or '').strip()
        section = (request.form.get('section') or 'A').strip()
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()

        # 1. Scope & Field Validation
        if not title:
            flash("Error: Timetable Title is mandatory.", "danger")
            return render_template('academic/student_timetables/upload.html', user=user, form_data=request.form, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS), 400

        if course not in VALID_TIMETABLE_COURSES:
            flash(f"Error: Invalid course '{course}'.", "danger")
            return render_template('academic/student_timetables/upload.html', user=user, form_data=request.form, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS), 400

        if academic_year not in VALID_ACADEMIC_YEAR_SEMESTERS:
            flash(f"Error: Invalid Academic Year '{academic_year}'. Must be one of 1st Year, 2nd Year, 3rd Year.", "danger")
            return render_template('academic/student_timetables/upload.html', user=user, form_data=request.form, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS), 400

        allowed_sems = VALID_ACADEMIC_YEAR_SEMESTERS.get(academic_year, [])
        if semester not in allowed_sems:
            flash(f"Error: Invalid Semester '{semester}' for {academic_year}. Allowed: {', '.join(allowed_sems)}.", "danger")
            return render_template('academic/student_timetables/upload.html', user=user, form_data=request.form, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS), 400

        if section not in VALID_TIMETABLE_SECTIONS:
            flash(f"Error: Invalid section '{section}'.", "danger")
            return render_template('academic/student_timetables/upload.html', user=user, form_data=request.form, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS), 400

        # 2. File Upload Validation
        if 'file' not in request.files or not request.files['file'].filename:
            flash("Error: Please select a timetable file (PDF, Image, or Spreadsheet) to upload.", "danger")
            return render_template('academic/student_timetables/upload.html', user=user, form_data=request.form, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS), 400

        uploaded_file = request.files['file']
        is_valid, err_msg, clean_name, mimetype, file_size = validate_academic_file(
            uploaded_file,
            max_bytes=10 * 1024 * 1024
        )
        if not is_valid:
            flash(f"File Validation Error: {err_msg}", "danger")
            return render_template('academic/student_timetables/upload.html', user=user, form_data=request.form, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS), 400

        # 3. Save file in private storage
        try:
            folder = app.config['STUDENT_TIMETABLES_STORAGE_FOLDER']
            storage_key, checksum, saved_size = save_academic_file(uploaded_file, folder, clean_name)
        except Exception as storage_err:
            flash(f"Storage Error: Failed to save file ({str(storage_err)}).", "danger")
            return render_template('academic/student_timetables/upload.html', user=user, form_data=request.form, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS), 500

        # 4. Atomic Database Update & Scope Archiving
        try:
            # Query existing active timetables for this scope
            active_existing = StudentSemesterTimetable.query.filter_by(
                course=course,
                academic_year=academic_year,
                semester=semester,
                section=section,
                status='PUBLISHED'
            ).all()

            # Calculate next version
            max_v = db.session.query(db.func.max(StudentSemesterTimetable.version)).filter_by(
                course=course,
                academic_year=academic_year,
                semester=semester,
                section=section
            ).scalar() or 0
            new_version = max_v + 1

            # Archive previous active timetables
            for old in active_existing:
                old.status = 'ARCHIVED'
                old.updated_at = datetime.utcnow()

            # Create new PUBLISHED timetable
            new_tt = StudentSemesterTimetable(
                course=course,
                academic_year=academic_year,
                semester=semester,
                section=section,
                title=title,
                description=description,
                file_filename=clean_name,
                file_storage_key=storage_key,
                file_mimetype=mimetype,
                file_size=saved_size,
                file_checksum=checksum,
                version=new_version,
                status='PUBLISHED',
                uploaded_by_id=user.id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.session.add(new_tt)
            db.session.commit()

            # Record in Academic Resource Audit
            record_academic_resource_audit(
                actor_user=user,
                action='CREATE',
                resource_type='STUDENT_TIMETABLE',
                resource_id=new_tt.id,
                after_state={'title': title, 'scope': f"{course} {academic_year} {semester} Sec {section}", 'version': new_version},
                reason=f"Teacher published semester timetable v{new_version}"
            )

            # 5. Notify Students of the matching class scope
            try:
                notify_class_students(
                    course=course,
                    semester=semester,
                    section=section,
                    title=f"New Semester Timetable: {semester} ({course})",
                    message=f"Prof. {user.full_name} has published the semester timetable '{title}' (v{new_version}).",
                    category='academic',
                    action_url=url_for('student_timetable_view'),
                    idempotency_prefix=f"st_tt_pub_{new_tt.id}",
                    sound=True
                )
            except Exception as notif_err:
                print(f"Notification notice on timetable upload: {notif_err}")

            flash(f"Semester timetable '{title}' (v{new_version}) successfully published for {course} {academic_year} {semester} Sec {section}.", "success")
            return redirect(url_for('student_timetables_dashboard'))

        except Exception as db_err:
            db.session.rollback()
            remove_academic_file(storage_key, app.config['STUDENT_TIMETABLES_STORAGE_FOLDER'])
            flash(f"Database Error: Failed to publish timetable ({str(db_err)}).", "danger")
            return render_template('academic/student_timetables/upload.html', user=user, form_data=request.form, valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS), 500

    return render_template(
        'academic/student_timetables/upload.html',
        user=user,
        form_data={},
        valid_year_semesters=VALID_ACADEMIC_YEAR_SEMESTERS
    )


@app.route('/academic/student-timetables/<int:timetable_id>/archive', methods=['POST'])
@login_required
def student_timetables_archive(timetable_id):
    user = User.query.get(session['user_id'])
    if not user or not (user.role in ['Faculty', 'teacher', 'HOD - BCA Dept', 'Principal', 'admin', 'HR'] or user.username == 'admin'):
        flash("Access Denied.", "danger")
        return redirect(url_for('dashboard')), 403

    timetable = StudentSemesterTimetable.query.get(timetable_id)
    if not timetable:
        flash("Timetable not found.", "danger")
        return redirect(url_for('student_timetables_dashboard')), 404

    timetable.status = 'ARCHIVED'
    timetable.updated_at = datetime.utcnow()
    db.session.commit()

    record_academic_resource_audit(
        actor_user=user,
        action='ARCHIVE',
        resource_type='STUDENT_TIMETABLE',
        resource_id=timetable.id,
        after_state={'status': 'ARCHIVED'},
        reason="Teacher archived semester timetable"
    )

    flash(f"Timetable '{timetable.title}' (v{timetable.version}) archived.", "info")
    return redirect(url_for('student_timetables_dashboard'))


@app.route('/academic/student-timetables/<int:timetable_id>/download', methods=['GET'])
def download_student_timetable(timetable_id):
    timetable = StudentSemesterTimetable.query.get(timetable_id)
    if not timetable:
        abort(404, description="Timetable document not found.")

    # Authorization verification:
    is_authorized_staff = False
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and (user.role in ['Faculty', 'teacher', 'HOD - BCA Dept', 'Principal', 'admin', 'HR'] or user.username == 'admin'):
            is_authorized_staff = True

    is_authorized_student = False
    if 'student_id' in session:
        student = Student.query.get(session['student_id'])
        if student:
            if (student.course == timetable.course and 
                student.semester == timetable.semester and 
                (timetable.section in [student.section, 'ALL'])):
                is_authorized_student = True

    if not is_authorized_staff and not is_authorized_student:
        flash("Access Denied: You are not authorized to download this semester timetable.", "danger")
        if 'student_id' in session:
            return redirect(url_for('student_timetable_view')), 403
        return redirect(url_for('login')), 403

    folder = app.config['STUDENT_TIMETABLES_STORAGE_FOLDER']
    file_path = os.path.join(folder, timetable.file_storage_key)
    if not os.path.exists(file_path):
        flash("Error: The requested file is missing from secure storage.", "danger")
        abort(404)

    return send_from_directory(
        folder,
        timetable.file_storage_key,
        as_attachment=True,
        download_name=timetable.file_filename,
        mimetype=timetable.file_mimetype
    )


@app.route('/academic/student-timetables/<int:timetable_id>/view', methods=['GET'])
def view_student_timetable_file(timetable_id):
    timetable = StudentSemesterTimetable.query.get(timetable_id)
    if not timetable:
        abort(404)

    is_authorized = False
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and (user.role in ['Faculty', 'teacher', 'HOD - BCA Dept', 'Principal', 'admin', 'HR'] or user.username == 'admin'):
            is_authorized = True
    elif 'student_id' in session:
        student = Student.query.get(session['student_id'])
        if student and student.course == timetable.course and student.semester == timetable.semester and (timetable.section in [student.section, 'ALL']):
            is_authorized = True

    if not is_authorized:
        abort(403)

    folder = app.config['STUDENT_TIMETABLES_STORAGE_FOLDER']
    return send_from_directory(
        folder,
        timetable.file_storage_key,
        as_attachment=False,
        mimetype=timetable.file_mimetype
    )


@app.route('/student/timetable', methods=['GET'])
def student_timetable_view():
    if 'student_id' not in session:
        flash("Please log in with your UUCMS ID to view your semester timetable.", "warning")
        return redirect(url_for('student_login'))
    
    student = Student.query.get(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))

    course = student.course
    academic_year = student.academic_year
    semester = student.semester
    section = student.section or 'A'

    timetable = StudentSemesterTimetable.query.filter(
        StudentSemesterTimetable.course == course,
        StudentSemesterTimetable.academic_year == academic_year,
        StudentSemesterTimetable.semester == semester,
        StudentSemesterTimetable.section.in_([section, 'ALL']),
        StudentSemesterTimetable.status == 'PUBLISHED'
    ).order_by(
        db.case((StudentSemesterTimetable.section == section, 1), else_=2),
        StudentSemesterTimetable.version.desc()
    ).first()

    return render_template(
        'student_timetable.html',
        student=student,
        timetable=timetable,
        course=course,
        academic_year=academic_year,
        semester=semester,
        section=section
    )

@app.route('/academic/study-materials/<int:material_id>/preview', methods=['GET'])
def preview_study_material(material_id):
    material = StudyMaterial.query.get_or_404(material_id)
    if material.status != 'Published' and 'user_id' not in session:
        return abort(404)

    if 'student_id' in session:
        student = Student.query.get(session['student_id'])
        if not student or not student.is_active:
            return abort(403)
        if material.course != student.course or material.academic_year != student.academic_year or material.semester != student.semester or (material.section not in [student.section, 'ALL']):
            return abort(403)
        scope = {'course': material.course, 'academic_year': material.academic_year, 'semester': material.semester, 'section': material.section}
        decision = get_academic_content_access_decision(
            user=None,
            student=student,
            subject=material.subject,
            academic_scope=scope,
            resource_type='STUDY_MATERIAL',
            evaluation_date=material.created_at.date()
        )
        if not decision['can_view']:
            return abort(403)
    elif 'user_id' in session:
        user = User.query.get(session['user_id'])
        scope = {'course': material.course, 'semester': material.semester, 'section': material.section}
        if not can_manage_academic_resource(user, material.subject, scope, action='VIEW'):
            return abort(403)
    else:
        return redirect(url_for('login'))

    file_path = os.path.join(app.config['STUDY_MATERIALS_STORAGE_FOLDER'], material.file_storage_key)
    if not os.path.exists(file_path):
        return abort(404)

    resp = make_response(send_file(
        file_path,
        as_attachment=False,
        download_name=material.file_filename,
        mimetype=material.file_mimetype
    ))
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Content-Disposition'] = f'inline; filename="{material.file_filename}"'
    return resp


@app.route('/student/study-materials', methods=['GET'])
def student_study_materials():
    if 'student_id' not in session:
        flash('Please login to the Student Academic Portal.', 'info')
        return redirect(url_for('student_login'))

    student = Student.query.get(session['student_id'])
    if not student or not student.is_active:
        session.clear()
        return redirect(url_for('student_login'))

    category = (request.args.get('category') or 'Textbooks').strip()
    if category not in VALID_STUDY_MATERIAL_CATEGORIES:
        category = 'Textbooks'

    subject = (request.args.get('subject') or '').strip()
    search = (request.args.get('search') or '').strip()

    query = StudyMaterial.query.filter(
        StudyMaterial.course == student.course,
        StudyMaterial.academic_year == student.academic_year,
        StudyMaterial.semester == student.semester,
        StudyMaterial.section.in_([student.section, 'ALL']),
        StudyMaterial.category == category,
        StudyMaterial.status == 'Published'
    )

    if subject:
        query = query.filter(StudyMaterial.subject == subject)
    if search:
        search_pat = f"%{search}%"
        query = query.filter(
            (StudyMaterial.title.ilike(search_pat)) |
            (StudyMaterial.description.ilike(search_pat)) |
            (StudyMaterial.tags.ilike(search_pat))
        )

    materials = query.order_by(StudyMaterial.created_at.desc()).all()

    # Available subjects for student's class
    class_subjects = [
        r[0] for r in db.session.query(Timetable.subject).filter_by(
            course=student.course,
            semester=student.semester,
            section=student.section
        ).distinct().all() if r[0]
    ]

    cards = []
    for m in materials:
        scope = {'course': m.course, 'semester': m.semester, 'section': m.section}
        decision = get_academic_content_access_decision(
            user=None,
            student=student,
            subject=m.subject,
            academic_scope=scope,
            resource_type='STUDY_MATERIAL',
            evaluation_date=m.created_at.date()
        )

        cards.append({
            'material': m,
            'is_accessible': decision['can_view'],
            'access_decision': decision
        })

    return render_template(
        'student_study_materials.html',
        student=student,
        cards=cards,
        categories=VALID_STUDY_MATERIAL_CATEGORIES,
        class_subjects=sorted(class_subjects),
        selected_category=category,
        selected_subject=subject,
        search_query=search
    )

# ==============================================================================
# FEATURE - TEACHER ACADEMIC ANALYTICS DASHBOARD
# ==============================================================================

DEFAULT_LOW_MARKS_THRESHOLD_PERCENT = 40.0

def get_low_marks_threshold_percent():
    try:
        return float(os.getenv('LOW_MARKS_THRESHOLD_PERCENT', str(DEFAULT_LOW_MARKS_THRESHOLD_PERCENT)))
    except Exception:
        return DEFAULT_LOW_MARKS_THRESHOLD_PERCENT

def resolve_teacher_academic_scope(user, req_course=None, req_academic_year=None, req_semester=None, req_section=None, req_subject=None):
    """
    Resolves, defaults, and validates the academic scope for teacher analytics.
    Returns:
        (selected_scope_dict, available_options_dict, is_authorized_bool)
    """
    authorized_contexts = get_authorized_subject_contexts(user)
    if not authorized_contexts:
        return None, {}, False

    avail_courses = sorted(list({c['course'] for c in authorized_contexts}))
    if req_course:
        if req_course not in avail_courses:
            return None, {}, False
        selected_course = req_course
    else:
        selected_course = avail_courses[0]

    course_contexts = [c for c in authorized_contexts if c['course'] == selected_course]
    avail_semesters = sorted(list({c['semester'] for c in course_contexts}))
    if req_semester:
        if req_semester not in avail_semesters:
            return None, {}, False
        selected_semester = req_semester
    else:
        selected_semester = avail_semesters[0] if avail_semesters else 'Sem V'

    sem_contexts = [c for c in course_contexts if c['semester'] == selected_semester]
    avail_sections = sorted(list({c['section'] for c in sem_contexts}))
    if req_section:
        if req_section not in avail_sections:
            return None, {}, False
        selected_section = req_section
    else:
        selected_section = avail_sections[0] if avail_sections else 'A'

    if not is_user_authorized_for_class(user, selected_course, selected_semester, selected_section):
        return None, {}, False

    avail_years = [
        r[0] for r in db.session.query(Student.academic_year).filter(
            Student.course == selected_course,
            Student.semester == selected_semester,
            Student.section == selected_section,
            Student.is_active == True
        ).distinct().all() if r[0]
    ]
    if not avail_years:
        avail_years = ['3rd Year'] if selected_semester in ['Sem V', 'Sem VI'] else (['2nd Year'] if selected_semester in ['Sem III', 'Sem IV'] else ['1st Year'])
    selected_year = req_academic_year if (req_academic_year and req_academic_year in avail_years) else avail_years[0]

    tt_subjects = {
        r[0] for r in db.session.query(Timetable.subject).filter_by(
            course=selected_course,
            semester=selected_semester,
            section=selected_section
        ).distinct().all() if r[0]
    }
    cs_subjects = {
        (s.actual_subject if s.actual_subject else s.scheduled_subject)
        for s in ClassSession.query.filter_by(
            course=selected_course,
            semester=selected_semester,
            section=selected_section
        ).all() if (s.actual_subject or s.scheduled_subject)
    }
    avail_subjects = sorted(list(tt_subjects | cs_subjects))

    selected_subject = req_subject if (req_subject and req_subject in avail_subjects) else None

    scope = {
        'course': selected_course,
        'academic_year': selected_year,
        'semester': selected_semester,
        'section': selected_section,
        'subject': selected_subject
    }
    options = {
        'courses': avail_courses,
        'academic_years': avail_years,
        'semesters': avail_semesters,
        'sections': avail_sections,
        'subjects': avail_subjects
    }
    return scope, options, True


def compute_academic_analytics_data(course, academic_year, semester, section, subject_filter=None, low_marks_threshold_pct=None):
    """
    Computes comprehensive attendance and assessment analytics across the selected academic scope.
    Guarantees:
    - Aggregate class attendance = total present instances / total student-session instances * 100
    - Individual attendance calculated independently per student
    - Missing marks distinguished from recorded zero
    - Missing attendance distinguished from absence (0 sessions -> PENDING)
    - Zero N+1 query overhead by bulk querying.
    """
    if low_marks_threshold_pct is None:
        low_marks_threshold_pct = get_low_marks_threshold_percent()

    # 1. Fetch active students in scope
    students_query = Student.query.filter(
        Student.course == course,
        Student.semester == semester,
        Student.section == section,
        Student.is_active == True
    )
    if academic_year:
        students_query = students_query.filter(Student.academic_year == academic_year)
    students = students_query.order_by(Student.name.asc()).all()
    total_students = len(students)
    student_ids = [s.id for s in students]

    # 2. Fetch completed class sessions in scope
    sessions_query = ClassSession.query.filter(
        ClassSession.course == course,
        ClassSession.semester == semester,
        ClassSession.section == section,
        ClassSession.status == 'COMPLETED'
    )
    all_completed_sessions = sessions_query.order_by(ClassSession.date.asc()).all()

    class_subjects = sorted(list({
        (s.actual_subject if s.actual_subject else s.scheduled_subject)
        for s in all_completed_sessions if (s.actual_subject or s.scheduled_subject)
    } | {
        r[0] for r in db.session.query(Timetable.subject).filter_by(
            course=course, semester=semester, section=section
        ).distinct().all() if r[0]
    }))

    if subject_filter:
        relevant_sessions = [
            s for s in all_completed_sessions
            if (s.actual_subject == subject_filter if s.actual_subject else s.scheduled_subject == subject_filter)
        ]
    else:
        relevant_sessions = all_completed_sessions

    relevant_session_ids = [s.id for s in relevant_sessions]
    total_conducted_sessions = len(relevant_sessions)

    unfinalized_sessions_count = ClassSession.query.filter(
        ClassSession.course == course,
        ClassSession.semester == semester,
        ClassSession.section == section,
        ClassSession.status.in_(['IN_PROGRESS', 'SCHEDULED']),
        ClassSession.date <= date.today()
    ).count()

    # 3. Bulk fetch attendance records for relevant sessions and students
    if relevant_session_ids and student_ids:
        attendance_records = StudentAttendance.query.filter(
            StudentAttendance.class_session_id.in_(relevant_session_ids),
            StudentAttendance.student_id.in_(student_ids)
        ).all()
    else:
        attendance_records = []

    student_att_map = {sid: {} for sid in student_ids}
    total_eligible_student_sessions = len(attendance_records)
    total_eligible_present_instances = 0

    for att in attendance_records:
        student_att_map[att.student_id][att.class_session_id] = att.status
        if att.status == 'Present':
            total_eligible_present_instances += 1

    if total_eligible_student_sessions > 0:
        aggregate_attendance_pct = round((total_eligible_present_instances * 100.0) / total_eligible_student_sessions, 2)
    else:
        aggregate_attendance_pct = None

    # 4. Subject-wise analytics calculation
    all_completed_session_ids = [s.id for s in all_completed_sessions]
    if all_completed_session_ids and student_ids:
        all_att_records = StudentAttendance.query.filter(
            StudentAttendance.class_session_id.in_(all_completed_session_ids),
            StudentAttendance.student_id.in_(student_ids)
        ).all()
    else:
        all_att_records = []

    full_att_map = {(a.student_id, a.class_session_id): a.status for a in all_att_records}

    subject_analytics = []
    for subj in class_subjects:
        subj_sessions = [
            s for s in all_completed_sessions
            if (s.actual_subject == subj if s.actual_subject else s.scheduled_subject == subj)
        ]
        subj_session_count = len(subj_sessions)
        subj_session_ids = [s.id for s in subj_sessions]

        if subj_session_count > 0 and student_ids:
            subj_present_count = sum(
                1 for sid in student_ids for cs_id in subj_session_ids
                if full_att_map.get((sid, cs_id)) == 'Present'
            )
            subj_total_instances = sum(
                1 for sid in student_ids for cs_id in subj_session_ids
                if (sid, cs_id) in full_att_map
            )
            subj_pct = round((subj_present_count * 100.0) / subj_total_instances, 2) if subj_total_instances > 0 else None

            below_75_count = 0
            for sid in student_ids:
                s_attended = sum(1 for cs_id in subj_session_ids if full_att_map.get((sid, cs_id)) == 'Present')
                s_pct = (s_attended * 100.0) / subj_session_count
                if s_pct < 75.0:
                    below_75_count += 1
        else:
            subj_pct = None
            below_75_count = 0

        subject_analytics.append({
            'subject': subj,
            'conducted_count': subj_session_count,
            'attendance_pct': subj_pct,
            'students_below_75': below_75_count,
            'is_selected': (subj == subject_filter)
        })

    # 5. Bulk fetch Internal Marks in scope
    marks_query = InternalMark.query.filter(
        InternalMark.student_id.in_(student_ids),
        InternalMark.course == course,
        InternalMark.semester == semester,
        InternalMark.section == section
    )
    if subject_filter:
        marks_query = marks_query.filter(InternalMark.subject == subject_filter)
    marks_records = marks_query.all()

    student_marks_map = {}
    for m in marks_records:
        if m.student_id not in student_marks_map:
            student_marks_map[m.student_id] = {}
        student_marks_map[m.student_id][m.subject] = m

    # 6. Bulk fetch active HOD Overrides in scope
    overrides_query = MarksEligibilityOverride.query.filter(
        MarksEligibilityOverride.student_id.in_(student_ids),
        MarksEligibilityOverride.course == course,
        MarksEligibilityOverride.semester == semester,
        MarksEligibilityOverride.section == section,
        MarksEligibilityOverride.is_active == True
    )
    if subject_filter:
        overrides_query = overrides_query.filter(MarksEligibilityOverride.subject == subject_filter)
    overrides_records = overrides_query.all()

    student_override_map = {}
    for o in overrides_records:
        if o.student_id not in student_override_map:
            student_override_map[o.student_id] = {}
        student_override_map[o.student_id][o.subject] = o

    # 7. Assessment Metrics
    maxima = get_assessment_maxima()
    ia1_threshold = maxima['IA1'] * (low_marks_threshold_pct / 100.0)
    ia2_threshold = maxima['IA2'] * (low_marks_threshold_pct / 100.0)
    final_ia_threshold = maxima['Final IA'] * (low_marks_threshold_pct / 100.0)

    all_ia1_vals = [m.ia1_marks for m in marks_records if m.ia1_marks is not None]
    all_ia2_vals = [m.ia2_marks for m in marks_records if m.ia2_marks is not None]
    all_final_vals = [m.final_ia_marks for m in marks_records if m.final_ia_marks is not None]

    expected_marks_count = total_students * (1 if subject_filter else max(len(class_subjects), 1))

    ia_metrics = {
        'maxima': maxima,
        'low_marks_threshold_pct': low_marks_threshold_pct,
        'thresholds': {
            'IA1': ia1_threshold,
            'IA2': ia2_threshold,
            'Final IA': final_ia_threshold
        },
        'IA1': {
            'average': round(sum(all_ia1_vals) / len(all_ia1_vals), 2) if all_ia1_vals else None,
            'highest': max(all_ia1_vals) if all_ia1_vals else None,
            'lowest': min(all_ia1_vals) if all_ia1_vals else None,
            'entered_count': len(all_ia1_vals),
            'pending_count': max(0, expected_marks_count - len(all_ia1_vals))
        },
        'IA2': {
            'average': round(sum(all_ia2_vals) / len(all_ia2_vals), 2) if all_ia2_vals else None,
            'highest': max(all_ia2_vals) if all_ia2_vals else None,
            'lowest': min(all_ia2_vals) if all_ia2_vals else None,
            'entered_count': len(all_ia2_vals),
            'pending_count': max(0, expected_marks_count - len(all_ia2_vals))
        },
        'Final IA': {
            'average': round(sum(all_final_vals) / len(all_final_vals), 2) if all_final_vals else None,
            'highest': max(all_final_vals) if all_final_vals else None,
            'lowest': min(all_final_vals) if all_final_vals else None,
            'entered_count': len(all_final_vals),
            'pending_count': max(0, expected_marks_count - len(all_final_vals))
        }
    }

    dist_vals = all_final_vals if all_final_vals else (all_ia1_vals if all_ia1_vals else [])
    dist_max = maxima['Final IA'] if all_final_vals else maxima['IA1']
    dist_buckets = {'< 40%': 0, '40% - 59%': 0, '60% - 74%': 0, '75% - 89%': 0, '90% - 100%': 0}
    for v in dist_vals:
        pct = (v / dist_max) * 100.0 if dist_max > 0 else 0
        if pct < 40.0:
            dist_buckets['< 40%'] += 1
        elif pct < 60.0:
            dist_buckets['40% - 59%'] += 1
        elif pct < 75.0:
            dist_buckets['60% - 74%'] += 1
        elif pct < 90.0:
            dist_buckets['75% - 89%'] += 1
        else:
            dist_buckets['90% - 100%'] += 1
    ia_metrics['score_distribution'] = dist_buckets

    # 8. Compile Student Rows
    student_rows = []
    students_meeting_threshold = 0
    students_below_threshold = 0
    students_pending_attendance = 0
    student_pct_list = []

    for s in students:
        s_att_dict = student_att_map.get(s.id, {})
        if total_conducted_sessions > 0:
            s_attended = sum(1 for cs_id in relevant_session_ids if s_att_dict.get(cs_id) == 'Present')
            s_percentage = round((s_attended * 100.0) / total_conducted_sessions, 2)
            student_pct_list.append(s_percentage)
            if s_percentage >= 75.0:
                students_meeting_threshold += 1
                s_att_status = 'ELIGIBLE'
            else:
                students_below_threshold += 1
                s_att_status = 'RESTRICTED'
        else:
            s_attended = 0
            s_percentage = None
            s_att_status = 'PENDING'
            students_pending_attendance += 1

        s_marks = student_marks_map.get(s.id, {})
        has_low_marks = False
        has_recorded_mark = False
        has_pending_mark = False
        marks_summary = []

        target_subjects = [subject_filter] if subject_filter else class_subjects
        for subj in target_subjects:
            m = s_marks.get(subj)
            if m:
                for comp, val in [('IA1', m.ia1_marks), ('IA2', m.ia2_marks), ('Final IA', m.final_ia_marks)]:
                    if val is not None:
                        has_recorded_mark = True
                        thresh = ia_metrics['thresholds'][comp]
                        if val < thresh:
                            has_low_marks = True
                        marks_summary.append(f"{comp}: {val:.1f}")
                    else:
                        has_pending_mark = True
            else:
                has_pending_mark = True

        s_overrides = student_override_map.get(s.id, {})
        active_manual_restrict = any(o.decision_type == 'MANUAL_RESTRICT' for o in s_overrides.values())
        active_allow_override = any(o.decision_type == 'ALLOW_OVERRIDE' for o in s_overrides.values())

        labels = []
        has_attendance_risk = (s_percentage is not None and s_percentage < 75.0)

        if has_attendance_risk:
            labels.append({'text': 'Attendance Risk', 'type': 'danger'})

        if has_low_marks:
            labels.append({'text': 'Low Internal Marks', 'type': 'warning'})

        if not has_recorded_mark or has_pending_mark:
            labels.append({'text': 'Marks Pending', 'type': 'secondary'})

        if s_att_status == 'PENDING':
            labels.append({'text': 'Attendance Data Pending', 'type': 'info'})

        if active_manual_restrict:
            labels.append({'text': 'HOD Restricted', 'type': 'purple'})
        elif active_allow_override:
            labels.append({'text': 'HOD Allow Override', 'type': 'success'})

        is_red = (has_attendance_risk or has_low_marks)

        student_rows.append({
            'student': s,
            'overall_attendance_pct': s_percentage,
            'attended_count': s_attended,
            'conducted_count': total_conducted_sessions,
            'attendance_status': s_att_status,
            'has_attendance_risk': has_attendance_risk,
            'has_low_marks': has_low_marks,
            'has_pending_mark': has_pending_mark,
            'is_red': is_red,
            'labels': labels,
            'marks_summary': ", ".join(marks_summary) if marks_summary else "No marks recorded",
            'marks_dict': s_marks,
            'overrides_dict': s_overrides
        })

    if student_pct_list:
        avg_student_attendance_rate = round(sum(student_pct_list) / len(student_pct_list), 2)
    else:
        avg_student_attendance_rate = None

    pct_below_75 = round((students_below_threshold * 100.0) / total_students, 1) if total_students > 0 else 0.0

    return {
        'total_students': total_students,
        'total_conducted_sessions': total_conducted_sessions,
        'unfinalized_sessions_count': unfinalized_sessions_count,
        'aggregate_attendance_pct': aggregate_attendance_pct,
        'avg_student_attendance_rate': avg_student_attendance_rate,
        'students_meeting_threshold': students_meeting_threshold,
        'students_below_threshold': students_below_threshold,
        'students_pending_attendance': students_pending_attendance,
        'pct_students_below_threshold': pct_below_75,
        'subject_analytics': subject_analytics,
        'ia_metrics': ia_metrics,
        'student_rows': student_rows
    }


def get_student_academic_analytics_profile(student, viewing_user, low_marks_threshold_pct=None, remaining_classes_by_subject=None):
    """
    Computes detailed academic analytics profile for an individual student.
    Includes subject-wise attendance, marks, recovery predictions, feasibility analytics,
    and teacher edit-permission resolution.
    """
    from attendance_analytics_service import build_student_attendance_analytics
    return build_student_attendance_analytics(
        student=student,
        viewing_user=viewing_user,
        db=db,
        ClassSession=ClassSession,
        StudentAttendance=StudentAttendance,
        Timetable=Timetable,
        User=User,
        InternalMark=InternalMark,
        MarksEligibilityOverride=MarksEligibilityOverride,
        is_user_authorized_for_context_func=is_user_authorized_for_context,
        get_assessment_maxima_func=get_assessment_maxima,
        get_low_marks_threshold_percent_func=lambda: (low_marks_threshold_pct if low_marks_threshold_pct is not None else get_low_marks_threshold_percent()),
        remaining_classes_by_subject=remaining_classes_by_subject
    )


# ==============================================================================
# ROUTES - TEACHER ACADEMIC ANALYTICS DASHBOARD
# ==============================================================================

@app.route('/academic/analytics', methods=['GET'])
def academic_analytics_dashboard():
    if 'user_id' not in session:
        flash('Please login to access Academic Analytics.', 'info')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Access Denied: You do not have permission to view Academic Analytics.', 'danger')
        return redirect(url_for('dashboard')), 403

    req_course = request.args.get('course')
    req_academic_year = request.args.get('academic_year')
    req_semester = request.args.get('semester')
    req_section = request.args.get('section')
    req_subject = request.args.get('subject')

    scope, options, is_auth = resolve_teacher_academic_scope(
        user=user,
        req_course=req_course,
        req_academic_year=req_academic_year,
        req_semester=req_semester,
        req_section=req_section,
        req_subject=req_subject
    )

    if not is_auth or not scope:
        flash('Access Denied: You are not authorized to view the requested academic context.', 'danger')
        return abort(403)

    search_query = (request.args.get('search') or '').strip()
    filter_status = (request.args.get('filter_status') or 'all').strip()
    sort_by = (request.args.get('sort_by') or 'uucms_id').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    analytics_data = compute_academic_analytics_data(
        course=scope['course'],
        academic_year=scope['academic_year'],
        semester=scope['semester'],
        section=scope['section'],
        subject_filter=scope['subject']
    )

    all_rows = analytics_data['student_rows']
    if search_query:
        sq = search_query.lower()
        all_rows = [
            r for r in all_rows
            if sq in r['student'].name.lower() or sq in r['student'].uucms_id.lower()
        ]

    if filter_status == 'risk':
        all_rows = [r for r in all_rows if r['has_attendance_risk']]
    elif filter_status == 'low_marks':
        all_rows = [r for r in all_rows if r['has_low_marks']]
    elif filter_status == 'pending':
        all_rows = [r for r in all_rows if (r['has_pending_mark'] or r['attendance_status'] == 'PENDING')]
    elif filter_status == 'threshold_met':
        all_rows = [r for r in all_rows if r['attendance_status'] == 'ELIGIBLE']

    if sort_by == 'name':
        all_rows.sort(key=lambda r: r['student'].name.lower())
    elif sort_by == 'attendance_asc':
        all_rows.sort(key=lambda r: (r['overall_attendance_pct'] if r['overall_attendance_pct'] is not None else 999.0))
    elif sort_by == 'attendance_desc':
        all_rows.sort(key=lambda r: (r['overall_attendance_pct'] if r['overall_attendance_pct'] is not None else -1.0), reverse=True)
    else:
        all_rows.sort(key=lambda r: (r['student'].uucms_id or ''))

    total_filtered_count = len(all_rows)
    total_pages = max(1, math.ceil(total_filtered_count / per_page))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paged_rows = all_rows[start_idx:end_idx]

    return render_template(
        'academic/analytics/dashboard.html',
        user=user,
        scope=scope,
        options=options,
        analytics=analytics_data,
        student_rows=paged_rows,
        total_filtered_count=total_filtered_count,
        current_page=page,
        total_pages=total_pages,
        search_query=search_query,
        filter_status=filter_status,
        sort_by=sort_by
    )


@app.route('/academic/analytics/student/<int:student_id>', methods=['GET'])
def student_academic_analytics(student_id):
    # 1. Student Session Check
    if 'student_id' in session:
        logged_student_id = session['student_id']
        if student_id != logged_student_id:
            flash("Security Violation: You are not authorized to view another student's attendance analytics.", "danger")
            return abort(403)
        student = Student.query.get(student_id)
        if not student:
            return abort(404)
        profile_data = get_student_academic_analytics_profile(student, viewing_user=None)
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({
                'student_id': student.id,
                'name': student.name,
                'uucms_id': student.uucms_id,
                'course': student.course,
                'semester': student.semester,
                'section': student.section,
                'overall_attendance_pct': profile_data.get('overall_attendance_pct'),
                'conducted_count': profile_data.get('conducted_count', 0),
                'attended_count': profile_data.get('attended_count', 0),
                'total_missed': profile_data.get('total_missed', 0),
                'overall_status': profile_data.get('overall_status', 'PENDING'),
                'overall_classes_needed': profile_data.get('overall_classes_needed', 0),
                'subjects_below_75_count': profile_data.get('subjects_below_75_count', 0),
                'subjects_at_or_above_75_count': profile_data.get('subjects_at_or_above_75_count', 0),
                'subjects_recoverable_count': profile_data.get('subjects_recoverable_count', 0),
                'subjects_impossible_count': profile_data.get('subjects_impossible_count', 0),
                'subject_cards': profile_data.get('client_subject_cards', []),
                'calculation_timestamp': profile_data.get('calculation_timestamp')
            }), 200
        return render_template(
            'academic/analytics/student_detail.html',
            user=None,
            profile=profile_data,
            student=student,
            is_student_view=True
        )

    # 2. Staff Session Check
    if 'user_id' not in session:
        flash('Please login to view student academic analytics.', 'info')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user or user.role not in ['Faculty', 'HOD - BCA Dept', 'Principal', 'admin']:
        flash('Access Denied: You do not have permission to view Student Analytics.', 'danger')
        return redirect(url_for('dashboard')), 403

    student = Student.query.get(student_id)
    if not student:
        flash('Student record not found.', 'danger')
        return abort(404)

    if not is_user_authorized_for_class(user, student.course, student.semester, student.section):
        flash('Access Denied: You are not authorized to view academic analytics for this student.', 'danger')
        return abort(403)

    profile_data = get_student_academic_analytics_profile(student, viewing_user=user)

    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({
            'student_id': student.id,
            'name': student.name,
            'uucms_id': student.uucms_id,
            'course': student.course,
            'semester': student.semester,
            'section': student.section,
            'overall_attendance_pct': profile_data.get('overall_attendance_pct'),
            'conducted_count': profile_data.get('conducted_count', 0),
            'attended_count': profile_data.get('attended_count', 0),
            'total_missed': profile_data.get('total_missed', 0),
            'overall_status': profile_data.get('overall_status', 'PENDING'),
            'overall_classes_needed': profile_data.get('overall_classes_needed', 0),
            'subjects_below_75_count': profile_data.get('subjects_below_75_count', 0),
            'subjects_at_or_above_75_count': profile_data.get('subjects_at_or_above_75_count', 0),
            'subjects_recoverable_count': profile_data.get('subjects_recoverable_count', 0),
            'subjects_impossible_count': profile_data.get('subjects_impossible_count', 0),
            'subject_cards': profile_data.get('client_subject_cards', []),
            'calculation_timestamp': profile_data.get('calculation_timestamp')
        }), 200

    return render_template(
        'academic/analytics/student_detail.html',
        user=user,
        profile=profile_data,
        student=student,
        is_student_view=False
    )


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
            create_notification(
                recipient_type='USER',
                recipient_id=int(target_id),
                title=f"New Task Assigned: {title}",
                message=f"You have been assigned a task by {sender.full_name}.",
                category='tasks',
                action_url=url_for('activity_room'),
                idempotency_key=f"task_{new_task.id}",
                sound=True
            )

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
    # 1. Strict Access Control: Only Principal, HR, and HOD allowed (Updated to match sidebar access)
    if session.get('role') not in ['Principal', 'HR', 'HOD - BCA Dept']:
        flash('Access Denied: Leave approval calendar is restricted to managers.', 'danger')
        return redirect(url_for('dashboard')), 403
    
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
    
from vault_engine import (
    validate_vault_file,
    compute_sha256,
    get_vault_storage_folder,
    extract_raw_text,
    parse_extracted_text,
    classify_and_match_records,
    apply_approved_proposal
)

def is_admin_user(user):
    """
    Digital Vault is strictly restricted to Admin only (not Accountant, not Faculty, not Principal).
    Matches user role 'admin' / 'HR' (System Admin account) or username 'admin'.
    """
    if not user:
        return False
    if user.role and user.role.lower() in ['accountant', 'faculty', 'principal', 'student']:
        return False
    return (user.role.lower() == 'admin' or user.username == 'admin' or user.role == 'HR')

def get_vault_models():
    return {
        'Student': Student,
        'User': User,
        'VaultDocument': VaultDocument,
        'VaultProposal': VaultProposal,
        'log_action': log_action
    }

@app.route('/digital_vault')
@login_required
def digital_vault():
    user = User.query.get(session['user_id'])
    if not user or not is_admin_user(user):
        flash('Access Restricted! Digital Vault is strictly restricted to Admin Department.', 'error')
        return redirect(url_for('dashboard')), 403

    is_admin = True
    pending_proposals = VaultProposal.query.filter_by(status='PENDING_APPROVAL').order_by(VaultProposal.created_at.desc()).all()
    needs_review_proposals = VaultProposal.query.filter_by(status='NEEDS_REVIEW').order_by(VaultProposal.created_at.desc()).all()
    my_proposals = VaultProposal.query.filter_by(submitted_by_id=user.id).order_by(VaultProposal.created_at.desc()).limit(20).all()
    all_proposals = VaultProposal.query.order_by(VaultProposal.created_at.desc()).limit(30).all()

    return render_template(
        'digital_vault.html',
        user=user,
        is_admin=is_admin,
        pending_proposals=pending_proposals,
        needs_review_proposals=needs_review_proposals,
        my_proposals=my_proposals,
        all_proposals=all_proposals
    )

@app.route('/vault/scan', methods=['POST'])
@login_required
def vault_scan():
    user = User.query.get(session['user_id'])
    if not user or not is_admin_user(user):
        return jsonify({"success": False, "error": "Access Restricted! Digital Vault is strictly restricted to Admin Department."}), 403

    file_obj = request.files.get('doc_file') or request.files.get('doc_image')
    is_valid, err_msg, file_bytes, mime_type = validate_vault_file(file_obj)
    if not is_valid:
        return jsonify({"success": False, "error": err_msg}), 400

    filename = secure_filename(file_obj.filename)
    file_hash = compute_sha256(file_bytes)
    storage_folder = get_vault_storage_folder(app)
    doc_uuid = str(uuid.uuid4())
    stored_filename = f"{doc_uuid}_{filename}"
    file_path = os.path.join(storage_folder, stored_filename)

    with open(file_path, 'wb') as f:
        f.write(file_bytes)

    # Save document record
    vault_doc = VaultDocument(
        uuid=doc_uuid,
        original_filename=filename,
        stored_filename=stored_filename,
        file_path=file_path,
        file_hash=file_hash,
        file_size=len(file_bytes),
        mime_type=mime_type,
        uploaded_by_id=user.id,
        created_at=datetime.utcnow()
    )
    db.session.add(vault_doc)
    db.session.commit()

    # Extract text
    test_override = request.form.get('test_ocr_text')
    raw_text, ocr_avail, ocr_warnings = extract_raw_text(file_bytes, filename, mime_type, test_ocr_override=test_override)

    # Parse text
    hint = request.form.get('target_type')
    parsed = parse_extracted_text(raw_text, doc_type_hint=hint)
    all_warnings = ocr_warnings + parsed['parsing_warnings']

    # Classify & Match against official DB
    classification_result = classify_and_match_records(
        parsed['target_type'],
        parsed['extracted_fields'],
        file_hash,
        get_vault_models()
    )
    all_warnings.extend(classification_result['warnings'])

    log_action(f"Scanned document '{filename}' in Digital Vault (SHA-256: {file_hash[:8]})", target="Digital Vault")

    return jsonify({
        "success": True,
        "document_id": vault_doc.id,
        "document_uuid": vault_doc.uuid,
        "filename": filename,
        "file_hash": file_hash,
        "raw_text": raw_text,
        "ocr_available": ocr_avail,
        "target_type": parsed['target_type'],
        "extracted_fields": parsed['extracted_fields'],
        "confidence": parsed['confidence'],
        "classification": classification_result['classification'],
        "operation": classification_result['operation'],
        "target_record_id": classification_result['target_record_id'],
        "target_identifier": classification_result['target_identifier'],
        "before_values": classification_result['before_values'],
        "diff_summary": classification_result['diff_summary'],
        "warnings": all_warnings
    })

@app.route('/vault/submit_proposal', methods=['POST'])
@login_required
def vault_submit_proposal():
    user = User.query.get(session['user_id'])
    if not user or not is_admin_user(user):
        return jsonify({"success": False, "error": "Access Restricted! Digital Vault is strictly restricted to Admin Department."}), 403

    payload = request.get_json(silent=True) or request.form.to_dict()
    doc_id = payload.get('document_id')
    vault_doc = VaultDocument.query.get(doc_id) if doc_id else None
    if not vault_doc:
        return jsonify({"success": False, "error": "Associated Vault Document not found."}), 400

    target_type = payload.get('target_type', 'STUDENT').upper()
    if target_type not in ['STUDENT', 'STAFF']:
        return jsonify({"success": False, "error": "Invalid target_type. Must be STUDENT or STAFF."}), 400

    proposed_fields = payload.get('fields')
    if isinstance(proposed_fields, str):
        try:
            proposed_fields = json.loads(proposed_fields)
        except Exception:
            proposed_fields = {}
    elif not isinstance(proposed_fields, dict):
        proposed_fields = {}

    if not proposed_fields:
        if target_type == 'STUDENT':
            proposed_fields = {
                'uucms_id': payload.get('uucms_id', '').strip().upper(),
                'name': payload.get('name', '').strip(),
                'email': payload.get('email', '').strip().lower(),
                'course': payload.get('course', 'BCA').strip(),
                'academic_year': payload.get('academic_year', '3rd Year').strip(),
                'semester': payload.get('semester', 'Sem V').strip(),
                'section': payload.get('section', 'A').strip().upper()
            }
        else:
            proposed_fields = {
                'full_name': payload.get('full_name', '').strip(),
                'email': payload.get('email', '').strip().lower(),
                'phone': payload.get('phone', '').strip(),
                'department': payload.get('department', '').strip(),
                'dept_id': payload.get('dept_id', '').strip(),
                'role': payload.get('role', 'Faculty').strip(),
                'username': payload.get('username', '').strip().lower()
            }

    classification_result = classify_and_match_records(
        target_type,
        proposed_fields,
        vault_doc.file_hash,
        get_vault_models()
    )

    status = 'PENDING_APPROVAL'
    if classification_result['classification'] in ['AMBIGUOUS_CONFLICT', 'NEEDS_REVIEW']:
        status = 'NEEDS_REVIEW'

    proposal = VaultProposal(
        proposal_id=str(uuid.uuid4()),
        document_id=vault_doc.id,
        target_type=target_type,
        operation=classification_result['operation'],
        target_record_id=classification_result['target_record_id'],
        target_identifier=classification_result['target_identifier'],
        classification=classification_result['classification'],
        raw_ocr_text=payload.get('raw_ocr_text', ''),
        extracted_data_json=json.dumps(proposed_fields),
        proposed_changes_json=json.dumps(proposed_fields),
        before_values_json=json.dumps(classification_result['before_values']),
        diff_summary_json=json.dumps(classification_result['diff_summary']),
        validation_warnings_json=json.dumps(classification_result['warnings']),
        status=status,
        submitted_by_id=user.id,
        submitted_at=datetime.utcnow(),
        review_notes=payload.get('review_notes')
    )
    db.session.add(proposal)
    db.session.commit()

    log_action(f"Created Vault Proposal #{proposal.proposal_id[:8]} ({target_type} {classification_result['operation']} - {status})", target="Digital Vault")
    notify_role(
        role_name='admin',
        title="Digital Vault: Proposal Pending Approval",
        message=f"New {target_type} proposal ({classification_result['classification']}) submitted by {user.full_name}.",
        category='vault',
        action_url=url_for('digital_vault'),
        idempotency_prefix=f"vault_sub_{proposal.id}",
        sound=True
    )

    return jsonify({
        "success": True,
        "proposal_id": proposal.id,
        "uuid": proposal.proposal_id,
        "status": proposal.status,
        "classification": proposal.classification,
        "operation": proposal.operation,
        "message": f"Proposal #{proposal.proposal_id[:8]} submitted for administrator review."
    })

@app.route('/vault/proposals', methods=['GET'])
@login_required
def vault_proposals_list():
    user = User.query.get(session['user_id'])
    if not user or not is_admin_user(user):
        return jsonify({"error": "Access Restricted! Digital Vault is strictly restricted to Admin Department."}), 403

    status_filter = request.args.get('status')
    query = VaultProposal.query
    if status_filter:
        query = query.filter_by(status=status_filter.upper())

    if user.role not in ['admin', 'HR', 'Principal']:
        query = query.filter_by(submitted_by_id=user.id)

    proposals = query.order_by(VaultProposal.created_at.desc()).all()
    results = []
    for p in proposals:
        results.append({
            "id": p.id,
            "proposal_id": p.proposal_id,
            "target_type": p.target_type,
            "operation": p.operation,
            "classification": p.classification,
            "status": p.status,
            "target_identifier": p.target_identifier,
            "submitted_by": p.submitter.full_name if p.submitter else "Unknown",
            "submitted_at": p.submitted_at.strftime('%Y-%m-%d %H:%M') if p.submitted_at else "",
            "document_filename": p.document.original_filename if p.document else "N/A"
        })
    return jsonify({"success": True, "proposals": results})

@app.route('/vault/proposal/<int:proposal_id>', methods=['GET'])
@login_required
def vault_proposal_detail(proposal_id):
    user = User.query.get(session['user_id'])
    if not user or not is_admin_user(user):
        return jsonify({"error": "Access Restricted! Digital Vault is strictly restricted to Admin Department."}), 403

    proposal = VaultProposal.query.get(proposal_id)
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404

    if user.role not in ['admin', 'HR', 'Principal'] and proposal.submitted_by_id != user.id:
        return jsonify({"error": "Unauthorized to view this proposal"}), 403

    can_approve = (user.role in ['admin', 'HR', 'Principal']) and (proposal.submitted_by_id != user.id)

    return jsonify({
        "success": True,
        "id": proposal.id,
        "proposal_id": proposal.proposal_id,
        "target_type": proposal.target_type,
        "operation": proposal.operation,
        "classification": proposal.classification,
        "status": proposal.status,
        "target_identifier": proposal.target_identifier,
        "target_record_id": proposal.target_record_id,
        "proposed_changes": json.loads(proposal.proposed_changes_json or '{}'),
        "before_values": json.loads(proposal.before_values_json or '{}'),
        "diff_summary": json.loads(proposal.diff_summary_json or '[]'),
        "validation_warnings": json.loads(proposal.validation_warnings_json or '[]'),
        "submitted_by": proposal.submitter.full_name if proposal.submitter else "Unknown",
        "submitted_at": proposal.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if proposal.submitted_at else "",
        "reviewed_by": proposal.reviewer.full_name if proposal.reviewer else None,
        "reviewed_at": proposal.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if proposal.reviewed_at else None,
        "review_notes": proposal.review_notes,
        "rejection_reason": proposal.rejection_reason,
        "document_id": proposal.document_id,
        "document_filename": proposal.document.original_filename if proposal.document else None,
        "can_approve": can_approve
    })

@app.route('/vault/proposal/<int:proposal_id>/approve', methods=['POST'])
@login_required
def vault_proposal_approve(proposal_id):
    user = User.query.get(session['user_id'])
    if not user or not is_admin_user(user):
        return jsonify({"success": False, "error": "Access Restricted! Proposal approval is strictly restricted to Admin Department."}), 403

    proposal = VaultProposal.query.get(proposal_id)
    if not proposal:
        return jsonify({"success": False, "error": "Proposal not found."}), 404

    # Submitter self-approval check
    if proposal.submitted_by_id == user.id:
        return jsonify({
            "success": False,
            "error": "Independent administrative review is mandatory. Submitter cannot approve their own proposal."
        }), 403

    if proposal.status == 'APPLIED':
        return jsonify({"success": False, "error": "Proposal has already been applied."}), 400

    if proposal.status == 'REJECTED':
        return jsonify({"success": False, "error": "Cannot approve a rejected proposal."}), 400

    proposal.status = 'APPROVED'
    proposal.reviewed_by_id = user.id
    proposal.reviewed_at = datetime.utcnow()
    proposal.review_notes = (request.form.get('review_notes') or (request.get_json(silent=True) or {}).get('review_notes', 'Approved by administrator'))

    success, msg = apply_approved_proposal(proposal, user, db.session, get_vault_models())
    if not success:
        return jsonify({"success": False, "error": msg}), 500
    if proposal.submitted_by_id:
        create_notification(
            recipient_type='USER',
            recipient_id=proposal.submitted_by_id,
            title="Digital Vault: Proposal Approved",
            message=f"Your {proposal.target_type} proposal #{proposal.id} was approved by {user.full_name} and synchronized.",
            category='vault',
            action_url=url_for('digital_vault'),
            idempotency_key=f"vault_appr_{proposal.id}",
            sound=True
        )

    return jsonify({"success": True, "message": msg, "status": proposal.status})

@app.route('/vault/proposal/<int:proposal_id>/reject', methods=['POST'])
@login_required
def vault_proposal_reject(proposal_id):
    user = User.query.get(session['user_id'])
    if not user or not is_admin_user(user):
        return jsonify({"success": False, "error": "Access Restricted! Proposal rejection is strictly restricted to Admin Department."}), 403

    proposal = VaultProposal.query.get(proposal_id)
    if not proposal:
        return jsonify({"success": False, "error": "Proposal not found."}), 404

    payload = request.get_json(silent=True) or request.form.to_dict()
    reason = payload.get('rejection_reason', '').strip()
    if not reason:
        return jsonify({"success": False, "error": "Rejection reason is mandatory."}), 400

    proposal.status = 'REJECTED'
    proposal.rejection_reason = reason
    proposal.reviewed_by_id = user.id
    proposal.reviewed_at = datetime.utcnow()
    proposal.version += 1
    db.session.commit()

    log_action(f"Rejected Digital Vault Proposal #{proposal.proposal_id[:8]}: {reason}", target="Digital Vault")
    if proposal.submitted_by_id:
        create_notification(
            recipient_type='USER',
            recipient_id=proposal.submitted_by_id,
            title="Digital Vault: Proposal Rejected",
            message=f"Your {proposal.target_type} proposal #{proposal.id} was rejected. Reason: {reason}",
            category='vault',
            action_url=url_for('digital_vault'),
            idempotency_key=f"vault_rej_{proposal.id}",
            sound=True
        )

    return jsonify({
        "success": True,
        "message": f"Proposal #{proposal.proposal_id[:8]} was rejected. No changes were made to official records.",
        "status": "REJECTED"
    })

@app.route('/vault/document/<int:document_id>/download', methods=['GET'])
@login_required
def vault_document_download(document_id):
    user = User.query.get(session['user_id'])
    if not user or not is_admin_user(user):
        flash('Access Restricted! Digital Vault is strictly restricted to Admin Department.', 'error')
        return redirect(url_for('dashboard')), 403

    vault_doc = VaultDocument.query.get(document_id)
    if not vault_doc or not os.path.isfile(vault_doc.file_path):
        flash('Requested document was not found.', 'error')
        return redirect(url_for('digital_vault')), 404

    return send_file(
        vault_doc.file_path,
        as_attachment=True,
        download_name=vault_doc.original_filename,
        mimetype=vault_doc.mime_type
    )

@app.route('/scan_and_import', methods=['POST'])
@login_required
def scan_and_import():
    user = User.query.get(session['user_id'])
    if not user or not is_admin_user(user):
        return jsonify({"success": False, "error": "Access Restricted! Digital Vault is strictly restricted to Admin Department."}), 403

    file = request.files.get('doc_image') or request.files.get('doc_file')
    if not file or file.filename == '':
        return jsonify({"success": False, "error": "Empty file uploaded"}), 400

    filename = secure_filename(file.filename)
    file_bytes = file.read()
    if not file_bytes:
        return jsonify({"success": False, "error": "Empty file uploaded"}), 400

    test_override = request.form.get('test_ocr_text') or os.getenv('VAULT_TEST_OCR_TEXT')
    raw_text, ocr_avail, warnings = extract_raw_text(file_bytes, filename, file.mimetype or 'image/jpeg', test_ocr_override=test_override)

    guessed_name = "New Faculty Member"
    if raw_text:
        parsed = parse_extracted_text(raw_text)
        guessed_name = parsed['extracted_fields'].get('name') or parsed['extracted_fields'].get('full_name') or "New Faculty Member"
    else:
        clean_fname = filename.rsplit('.', 1)[0].replace('_', ' ').replace('-', ' ').title()
        guessed_name = clean_fname if len(clean_fname) >= 3 else "New Faculty Member"

    clean_username = guessed_name.lower().replace('dr.', '').replace('prof.', '').replace(' ', '_').replace('.', '').replace('-', '').strip('_')[:12]
    suggested_email = f"{clean_username}@bmsccm.edu.in"
    suggested_dept = "Computer Science"
    suggested_dept_id = "CS-2026"
    suggested_phone = "+91 98765 43210"
    suggested_salary = 65000

    log_action(f"Scanned document via AI OCR: {guessed_name}", target="Digital Vault")

    return jsonify({
        "success": True,
        "extracted_name": guessed_name,
        "full_text": raw_text or f"BMS Document: {filename}",
        "suggested_username": clean_username,
        "suggested_email": suggested_email,
        "suggested_phone": suggested_phone,
        "suggested_department": suggested_dept,
        "suggested_dept_id": suggested_dept_id,
        "suggested_salary": suggested_salary,
        "ocr_available": ocr_avail,
        "warnings": warnings
    })
    
@app.route('/dashboard')
def dashboard():
    if 'student_id' in session:
        return redirect(url_for('student_dashboard'))
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

    # MANAGEMENT SPECIFIC: Number of leaves waiting for Principal/HOD to click 'Approve' (Admin is Read-Only)
    counts['to_approve'] = 0
    if session.get('role') == 'Principal':
        counts['to_approve'] = Leave.query.filter_by(status='Pending Principal').count()
    elif session.get('role') == 'HOD - BCA Dept':
        counts['to_approve'] = Leave.query.filter_by(status='Pending HOD').count()

    pending_count = Task.query.filter_by(assigned_to=session['user_id'], is_done=False).count()

    # Academic Schedule for Today
    today_date = today_ist.date()
    today_day_name = today_ist.strftime("%A")
    today_classes = []
    if user.role in ['Faculty', 'HOD - BCA Dept', 'Principal']:
        t_entries = Timetable.query.filter_by(user_id=user.id, day=today_day_name).order_by(Timetable.time_slot).all()
        for te in t_entries:
            cs = ClassSession.query.filter_by(timetable_id=te.id, date=today_date).first()
            p_cnt = 0
            a_cnt = 0
            if cs:
                p_cnt = StudentAttendance.query.filter_by(class_session_id=cs.id, status='Present').count()
                a_cnt = StudentAttendance.query.filter_by(class_session_id=cs.id, status='Absent').count()
            today_classes.append({
                'entry': te,
                'session': cs,
                'present_count': p_cnt,
                'absent_count': a_cnt
            })

    return render_template('dashboard.html', 
                           user=user, notifications=notifs, office_days=office_days, 
                           wfh_days=wfh_days, tasks=tasks, unread_chats=unread_chats, 
                           is_birthday=is_birthday, is_anniversary=is_anniversary,
                           today_classes=today_classes, today_date=today_date, today_day_name=today_day_name,
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
    if session.get('role') != 'Accountant':
        flash('Access Denied: Financial portal is restricted to Accountants.', 'danger')
        return redirect(url_for('dashboard')), 403
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
    if 'student_id' in session:
        flash('Access Denied: Staff directory is restricted to employees.', 'danger')
        return redirect(url_for('student_dashboard')), 403
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
    
@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    if 'user_id' in session:
        recipient_type = 'USER'
        recipient_id = session['user_id']
    elif 'student_id' in session:
        recipient_type = 'STUDENT'
        recipient_id = session['student_id']
    else:
        # Unauthenticated request
        return jsonify({'unread_count': 0, 'notifications': []}), 200

    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    unread_only = request.args.get('unread_only', 'false').lower() in ['true', '1']

    res = get_notifications_list(recipient_type, recipient_id, limit=limit, offset=offset, unread_only=unread_only)
    
    # Backward compatibility for legacy code expecting array of items with {id, msg, time}
    if request.args.get('legacy') == '1':
        return jsonify([{'id': n['id'], 'msg': n['message'], 'time': n['time_display']} for n in res['notifications']])

    return jsonify(res)

@app.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
def api_mark_notification_read(notif_id):
    if 'user_id' in session:
        recipient_type = 'USER'
        recipient_id = session['user_id']
    elif 'student_id' in session:
        recipient_type = 'STUDENT'
        recipient_id = session['student_id']
    else:
        return jsonify({'error': 'Unauthorized'}), 401

    success, code = mark_as_read(notif_id, recipient_type, recipient_id)
    if not success:
        return jsonify({'error': 'Could not mark notification as read'}), code
    return jsonify({'status': 'success', 'unread_count': get_unread_count(recipient_type, recipient_id)})

@app.route('/api/notifications/mark_all_read', methods=['POST'])
def api_mark_all_notifications_read():
    if 'user_id' in session:
        recipient_type = 'USER'
        recipient_id = session['user_id']
    elif 'student_id' in session:
        recipient_type = 'STUDENT'
        recipient_id = session['student_id']
    else:
        return jsonify({'error': 'Unauthorized'}), 401

    mark_all_as_read(recipient_type, recipient_id)
    return jsonify({'status': 'success', 'unread_count': 0})

@app.route('/api/notifications/preferences', methods=['GET', 'POST'])
def api_notification_preferences():
    if 'user_id' in session:
        recipient_type = 'USER'
        recipient_id = session['user_id']
    elif 'student_id' in session:
        recipient_type = 'STUDENT'
        recipient_id = session['student_id']
    else:
        return jsonify({'error': 'Unauthorized'}), 401

    if request.method == 'POST':
        data = request.get_json() or {}
        update_preferences(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            sound_enabled=data.get('sound_enabled'),
            browser_enabled=data.get('browser_enabled'),
            email_enabled=data.get('email_enabled'),
            volume=data.get('volume'),
            muted_categories=data.get('muted_categories')
        )

    pref = get_or_create_preferences(recipient_type, recipient_id)
    return jsonify({
        'sound_enabled': getattr(pref, 'sound_enabled', True),
        'browser_enabled': getattr(pref, 'browser_enabled', True),
        'email_enabled': getattr(pref, 'email_enabled', True),
        'volume': getattr(pref, 'volume', 0.7),
        'muted_categories': getattr(pref, 'muted_categories', '')
    })

@app.route('/api/notifications/test_sound', methods=['POST'])
def api_test_notification_sound():
    if 'user_id' in session:
        recipient_type = 'USER'
        recipient_id = session['user_id']
        room_name = f"user_{recipient_id}"
    elif 'student_id' in session:
        recipient_type = 'STUDENT'
        recipient_id = session['student_id']
        room_name = f"student_{recipient_id}"
    else:
        return jsonify({'error': 'Unauthorized'}), 401

    unread = get_unread_count(recipient_type, recipient_id)
    socketio.emit('new_notification', {
        'id': 0,
        'title': 'Test Notification Chime',
        'message': 'Your audio system and notification sound are working cleanly!',
        'category': 'general',
        'action_url': None,
        'timestamp': get_ist_time().strftime('%I:%M %p'),
        'sound': True,
        'unread_count': unread,
        'is_test': True
    }, room=room_name)

    return jsonify({'status': 'success', 'message': 'Test sound emitted'})

@app.route('/api/push/vapid_public_key', methods=['GET'])
def api_vapid_public_key():
    public_key = get_vapid_public_key()
    if not public_key:
        return jsonify({'error': 'VAPID keys not configured'}), 500
    return jsonify({'publicKey': public_key})

@app.route('/api/push/subscribe', methods=['POST'])
def api_push_subscribe():
    if 'user_id' in session:
        recipient_type = 'USER'
        user_id = session['user_id']
        student_id = None
    elif 'student_id' in session:
        recipient_type = 'STUDENT'
        user_id = None
        student_id = session['student_id']
    else:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint')
    keys = data.get('keys') or {}
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')

    if not endpoint or not p256dh or not auth:
        return jsonify({'error': 'Invalid push subscription payload'}), 400

    try:
        sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
        if not sub:
            sub = PushSubscription(
                recipient_type=recipient_type,
                user_id=user_id,
                student_id=student_id,
                endpoint=endpoint,
                p256dh_key=p256dh,
                auth_key=auth,
                user_agent=(request.headers.get('User-Agent') or '')[:250],
                created_at=get_ist_time(),
                last_seen_at=get_ist_time()
            )
            db.session.add(sub)
        else:
            sub.recipient_type = recipient_type
            sub.user_id = user_id
            sub.student_id = student_id
            sub.p256dh_key = p256dh
            sub.auth_key = auth
            sub.last_seen_at = get_ist_time()
            sub.user_agent = (request.headers.get('User-Agent') or '')[:250]
        
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Push subscription saved'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to save push subscription: {str(e)}'}), 500

@app.route('/api/push/unsubscribe', methods=['POST'])
def api_push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint')
    if not endpoint:
        return jsonify({'error': 'Missing endpoint'}), 400

    try:
        PushSubscription.query.filter_by(endpoint=endpoint).delete()
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Push subscription removed'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/push/test_push', methods=['POST'])
def api_push_test():
    if 'user_id' in session:
        recipient_type = 'USER'
        recipient_id = session['user_id']
        subs = PushSubscription.query.filter_by(recipient_type='USER', user_id=recipient_id).all()
        user = User.query.get(recipient_id)
        name = user.full_name if user else 'Faculty'
    elif 'student_id' in session:
        recipient_type = 'STUDENT'
        recipient_id = session['student_id']
        subs = PushSubscription.query.filter_by(recipient_type='STUDENT', student_id=recipient_id).all()
        student = Student.query.get(recipient_id)
        name = student.name if student else 'Student'
    else:
        return jsonify({'error': 'Unauthorized'}), 401

    if not subs:
        return jsonify({
            'status': 'warning',
            'message': 'No registered Web Push subscriptions found for this browser/device. Please enable Desktop notifications first.'
        })

    subs_data = [{
        'id': s.id,
        'endpoint': s.endpoint,
        'p256dh_key': s.p256dh_key,
        'auth_key': s.auth_key
    } for s in subs]

    payload = {
        'id': 0,
        'title': 'BMS ERP Alert Verification',
        'message': f'Dear {name}, your background notification delivery and audio alerts are working cleanly even when this window is closed!',
        'category': 'general',
        'action_url': '/',
        'sound': True,
        'tag': 'bms-erp-test-push'
    }

    import threading
    threading.Thread(
        target=_dispatch_web_push_batch,
        args=(subs_data, payload),
        daemon=True
    ).start()

    return jsonify({
        'status': 'success',
        'message': f'Test push notification dispatched to {len(subs)} registered device(s).'
    })

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
        return redirect(url_for('dashboard')), 403

    all_staff = User.query.order_by(User.full_name.asc()).all()
    return render_template('admin_staff_master.html', all_staff=all_staff)

@app.route('/admin/edit_staff/<int:uid>', methods=['POST'])
@login_required
def admin_edit_staff(uid):
    user = User.query.get(session['user_id'])
    if not user or user.role.lower() not in ['hr', 'accountant', 'admin']:
        flash('Access Restricted! Only Admin Department can edit staff profiles.', 'error')
        return redirect(url_for('dashboard')), 403

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
    if 'student_id' in session:
        flash('Access Denied: Staff attendance portal is restricted to employees.', 'danger')
        return redirect(url_for('student_dashboard')), 403
    if 'user_id' not in session: 
        return redirect(url_for('login'))
        
    today = get_ist_time().strftime("%Y-%m-%d")
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        # Accept form or JSON payloads
        data = request.get_json(silent=True) or request.form
        lat_raw = data.get('lat')
        lon_raw = data.get('lon')
        accuracy_raw = data.get('accuracy')
        client_ts_raw = data.get('client_timestamp')
        client_inside = data.get('is_inside_campus')
        
        # Enforce On-Site Campus Mode (WFH Disabled)
        mode = 'Office'
        
        # Authoritative Server-Side Geofence Verification
        is_valid, reason_code, error_msg, details = verify_campus_presence(
            lat=lat_raw,
            lon=lon_raw,
            accuracy=accuracy_raw,
            client_timestamp=client_ts_raw,
            client_is_inside=client_inside
        )
        
        if not is_valid:
            log_action(f"Rejected Staff Attendance: {reason_code} for {user.full_name}", target=user.full_name)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                return jsonify({
                    'success': False,
                    'error': error_msg,
                    'reason_code': reason_code,
                    'details': details
                }), 400
            flash(error_msg, "error")
            return redirect(url_for('attendance'))
            
        val_lat = details.get('lat')
        val_lon = details.get('lon')
        val_acc = details.get('accuracy')
        loc_status = reason_code
        
        # Attendance Logic (Check-in / Check-out)
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        t_now = get_ist_time().strftime("%I:%M %p")
        
        if not att:
            # New Check-in
            new_entry = Attendance(
                user_id=session['user_id'], 
                date=today, 
                check_in=t_now, 
                work_mode=mode, 
                lat=val_lat, 
                lon=val_lon,
                accuracy=val_acc,
                location_status=loc_status
            )
            db.session.add(new_entry)
            db.session.add(Notification(message=f"ATTENDANCE: {user.full_name} CLOCKED-IN ({mode})"))
            log_action(f"Staff Clocked-in (Campus Verified): {user.full_name}", target=user.full_name)
        else:
            # Update existing record with Check-out
            att.check_out = t_now
            att.lat = val_lat
            att.lon = val_lon
            att.accuracy = val_acc
            att.location_status = loc_status
            db.session.add(Notification(message=f"ATTENDANCE: {user.full_name} CLOCKED-OUT"))
            log_action(f"Staff Clocked-out (Campus Verified): {user.full_name}", target=user.full_name)
            
        db.session.commit()
        
        success_msg = f"Attendance Synchronized Successfully. {error_msg}"
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({
                'success': True,
                'message': success_msg,
                'status_code': loc_status,
                'details': details
            })
            
        flash(success_msg, "success")
        return redirect(url_for('attendance'))
        
    # --- GET REQUEST LOGIC ---
    cfg = get_geofence_config()
    all_users = []
    if session.get('role') in ['admin', 'HR', 'Principal']:
        all_users = User.query.filter(User.status == 'Active').order_by(User.full_name.asc()).all()

    if session.get('role') == 'HR':
        history = Attendance.query.order_by(Attendance.date.desc()).all()
    else:
        history = Attendance.query.filter_by(user_id=session['user_id']).order_by(Attendance.date.desc()).all()
        
    return render_template('attendance.html', history=history, geofence_cfg=cfg, all_users=all_users, now_date=today)

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
    if 'student_id' in session:
        flash('Access Denied: Staff leave portal is restricted to employees.', 'danger')
        return redirect(url_for('student_dashboard')), 403
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
    if not leave_req:
        flash("Leave request not found.", "error")
        return redirect(url_for('leave'))
        
    role = session.get('role')
    
    # Strictly restrict approval/rejection to HOD and Principal (Admin is Read-Only)
    if role not in ['HOD - BCA Dept', 'Principal']:
        flash("Access Restricted! Leave approvals/rejections are strictly authorized for HOD and Principal. Admin has View-Only access.", "error")
        return redirect(url_for('leave'))
    
    if action == 'approve':
        if role == 'HOD - BCA Dept' and leave_req.status == 'Pending HOD':
            leave_req.status = 'Pending Principal'
        elif role == 'Principal' and leave_req.status == 'Pending Principal':
            leave_req.status = 'Approved'
        else:
            flash(f"Unauthorized approval action for current stage ({leave_req.status}).", "error")
            return redirect(url_for('leave'))
            
    elif action == 'reject':
        if (role == 'HOD - BCA Dept' and leave_req.status == 'Pending HOD') or (role == 'Principal' and leave_req.status in ['Pending HOD', 'Pending Principal']):
            leave_req.status = 'Rejected'
            leave_req.rejection_reason = request.args.get('reason', 'No reason provided')
        else:
            flash("Unauthorized rejection action.", "error")
            return redirect(url_for('leave'))
    
    db.session.commit()
    log_action(f"{action.capitalize()}d Leave Request", target=leave_req.user.full_name)
    
    # --- EVENT 2B: LEAVE DECISION NOTIFICATION ---
    if leave_req and leave_req.user:
        notify('leave_decision', leave_req.user, context={
            'status': leave_req.status,
            'reason': leave_req.rejection_reason if leave_req.status == 'Rejected' else '',
            'date': leave_req.date
        })
        create_notification(
            recipient_type='USER',
            recipient_id=leave_req.user_id,
            title=f"Leave Request {leave_req.status}",
            message=f"Your leave request for {leave_req.date} was marked {leave_req.status}.",
            category='tasks',
            action_url=url_for('leave'),
            idempotency_key=f"leave_{leave_req.id}_{leave_req.status}",
            sound=True
        )

    return redirect(url_for('leave'))

from datetime import datetime

@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if 'student_id' in session:
        flash('Access Denied: Staff expenses portal is restricted to employees.', 'danger')
        return redirect(url_for('student_dashboard')), 403
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
        create_notification(
            recipient_type='USER',
            recipient_id=claim.user_id,
            title=f"Expense Claim {claim.status}",
            message=f"Your expense claim of INR {claim.amount:,} ({claim.category}) has been {claim.status}.",
            category='payroll',
            action_url=url_for('expenses'),
            idempotency_key=f"exp_{claim.id}_{claim.status}",
            sound=True
        )

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

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user:
            db.session.add(Notification(message=f"PASSWORD RESET REQUEST: {user.username}"))
            db.session.commit()
            notify_role(
                'admin',
                "Password Reset Requested",
                f"Password reset requested for {user.full_name} ({user.username}).",
                category='security',
                action_url=url_for('staff_master'),
                sound=True
            )
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
    db.session.add(Notification(message=audit_msg))

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
    if 'user_id' in session:
        mark_all_as_read('USER', session['user_id'])
    elif 'student_id' in session:
        mark_all_as_read('STUDENT', session['student_id'])
    flash("All notifications marked as read.", "success")
    return redirect(request.referrer or url_for('dashboard'))

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
    mail_user = app.config.get('MAIL_USERNAME')
    mail_pwd = app.config.get('MAIL_PASSWORD')
    if not mail_user or not mail_pwd:
        return "Email sending skipped: MAIL_USERNAME or MAIL_PASSWORD not configured."

    principal_email = principal.email if principal else mail_user

    import socket
    orig_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(4.0)
        # We use MailMessage (the alias) to avoid the TypeError
        msg = MailMessage(
            "Official Staff Directory - BMSCCM",
            sender=mail_user,
            recipients=[principal_email]
        )
        msg.body = staff_report
        mail.send(msg)
        return "Staff list has been emailed to the Principal successfully!"
    except Exception as e:
        return f"Error sending email: {str(e)}"
    finally:
        socket.setdefaulttimeout(orig_timeout)

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
        if task.assigned_by:
            completer = User.query.get(session['user_id'])
            create_notification(
                recipient_type='USER',
                recipient_id=task.assigned_by,
                title=f"Task Completed: {task.title}",
                message=f"{completer.full_name if completer else 'Staff'} marked task '{task.title}' completed.",
                category='tasks',
                action_url=url_for('activity_room'),
                idempotency_key=f"task_done_{task.id}",
                sound=True
            )
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
        uid = session['user_id']
        online_users[uid] = session.get('name', 'Staff')
        join_room(f"user_{uid}")
        user = User.query.get(uid)
        if user:
            if user.role in ['admin', 'HR']:
                join_room("role_admin")
            if 'HOD' in (user.role or ''):
                join_room("role_hod")
            if user.role == 'Accountant':
                join_room("role_accountant")
        emit('update_online_status', list(online_users.values()), broadcast=True)
    elif 'student_id' in session:
        sid = session['student_id']
        join_room(f"student_{sid}")

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        uid = session['user_id']
        online_users.pop(uid, None)
        leave_room(f"user_{uid}")
        emit('update_online_status', list(online_users.values()), broadcast=True)
    elif 'student_id' in session:
        sid = session['student_id']
        leave_room(f"student_{sid}")

@socketio.on('join_notification_channel')
def handle_join_notification():
    if 'user_id' in session:
        join_room(f"user_{session['user_id']}")
    elif 'student_id' in session:
        join_room(f"student_{session['student_id']}")

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
    try:
        active = Broadcast.query.filter_by(active=True).order_by(Broadcast.id.desc()).first()
        return dict(active_broadcast=active)
    except Exception:
        db.session.rollback()
        return dict(active_broadcast=None)

@app.context_processor
def inject_notifications():
    try:
        if 'user_id' in session:
            u_id = session['user_id']
            task_count = Task.query.filter_by(assigned_to=u_id, is_done=False).count()
            return dict(
                global_notif_count=0,
                pending_tasks_count=task_count
            )
    except Exception:
        db.session.rollback()
    return dict(global_notif_count=0, pending_tasks_count=0)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
# ==========================================
# 5. FULL SEEDING (INCLUDING ALL FACULTY)
# ==========================================

def seed_database():
    try:
        db.create_all()
        # Self-healing column migration for existing PostgreSQL tables
        columns_to_add = [
            ('dept_id', 'VARCHAR(50) DEFAULT \'BMS-GEN-000\''),
            ('department', 'VARCHAR(100) DEFAULT \'General\''),
            ('address', 'VARCHAR(200) DEFAULT \'Basavanagudi, Bengaluru\''),
            ('caste', 'VARCHAR(50) DEFAULT \'General\''),
            ('religion', 'VARCHAR(50) DEFAULT \'General\''),
            ('dob', 'VARCHAR(20) DEFAULT \'1995-01-01\''),
            ('join_date', 'VARCHAR(20) DEFAULT \'2023-01-01\''),
            ('profile_pic', 'VARCHAR(200)'),
            ('status', 'VARCHAR(50) DEFAULT \'Active\'')
        ]
        with db.engine.connect() as conn:
            for col_name, col_type in columns_to_add:
                try:
                    conn.execute(db.text(f'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS {col_name} {col_type};'))
                    conn.commit()
                except Exception:
                    try:
                        conn.execute(db.text(f'ALTER TABLE user ADD COLUMN {col_name} {col_type};'))
                        conn.commit()
                    except Exception:
                        pass

        # Self-healing column migration for timetable table
        timetable_cols_to_add = [
            ('course', "VARCHAR(50) DEFAULT 'BCA'"),
            ('room_no', "VARCHAR(50) DEFAULT 'Room 204'"),
            ('section', "VARCHAR(20) DEFAULT 'A'")
        ]
        with db.engine.connect() as conn:
            for col_name, col_type in timetable_cols_to_add:
                try:
                    conn.execute(db.text(f'ALTER TABLE timetable ADD COLUMN IF NOT EXISTS {col_name} {col_type};'))
                    conn.commit()
                except Exception:
                    try:
                        conn.execute(db.text(f'ALTER TABLE timetable ADD COLUMN {col_name} {col_type};'))
                        conn.commit()
                    except Exception:
                        pass

        # Self-healing column migration for attendance table
        attendance_cols_to_add = [
            ('accuracy', "FLOAT"),
            ('location_status', "VARCHAR(50) DEFAULT 'CAMPUS_VERIFIED'")
        ]
        with db.engine.connect() as conn:
            for col_name, col_type in attendance_cols_to_add:
                try:
                    conn.execute(db.text(f'ALTER TABLE attendance ADD COLUMN IF NOT EXISTS {col_name} {col_type};'))
                    conn.commit()
                except Exception:
                    try:
                        conn.execute(db.text(f'ALTER TABLE attendance ADD COLUMN {col_name} {col_type};'))
                        conn.commit()
                    except Exception:
                        pass

        # Self-healing column migration for academic attendance tables
        academic_cols_to_add = [
            ('student', 'section', "VARCHAR(20) DEFAULT 'A'"),
            ('student', 'password_hash', "VARCHAR(255)"),
            ('student', 'raw_password', "VARCHAR(100)"),
            ('class_session', 'section', "VARCHAR(20) DEFAULT 'A'"),
            ('class_session', 'version', "INTEGER DEFAULT 1")
        ]
        with db.engine.connect() as conn:
            for tbl, col_name, col_type in academic_cols_to_add:
                try:
                    conn.execute(db.text(f'ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col_name} {col_type};'))
                    conn.commit()
                except Exception:
                    try:
                        conn.execute(db.text(f'ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type};'))
                        conn.commit()
                    except Exception:
                        pass

        # Enforce NOT NULL on class_session.timetable_id
        # Decommission legacy performance table if present
        with db.engine.connect() as conn:
            try:
                conn.execute(db.text('DROP TABLE IF EXISTS performance_kpi CASCADE;'))
                conn.commit()
            except Exception:
                try:
                    conn.execute(db.text('DROP TABLE IF EXISTS performance_kpi;'))
                    conn.commit()
                except Exception:
                    pass

        # Self-healing column migration for notification table
        notification_cols_to_add = [
            ('recipient_type', "VARCHAR(20) DEFAULT 'USER'"),
            ('student_id', "INTEGER"),
            ('title', "VARCHAR(150)"),
            ('category', "VARCHAR(50) DEFAULT 'general'"),
            ('action_url', "VARCHAR(255)"),
            ('idempotency_key', "VARCHAR(100)")
        ]
        with db.engine.connect() as conn:
            for col_name, col_type in notification_cols_to_add:
                try:
                    conn.execute(db.text(f'ALTER TABLE notification ADD COLUMN IF NOT EXISTS {col_name} {col_type};'))
                    conn.commit()
                except Exception:
                    try:
                        conn.execute(db.text(f'ALTER TABLE notification ADD COLUMN {col_name} {col_type};'))
                        conn.commit()
                    except Exception:
                        pass

        # Ensure Internal Assessment Marks tables exist
        try:
            InternalMark.__table__.create(db.engine, checkfirst=True)
            InternalMarkAudit.__table__.create(db.engine, checkfirst=True)
        except Exception:
            pass

        # Ensure Academic Assignments and Study Materials tables exist
        try:
            Assignment.__table__.create(db.engine, checkfirst=True)
            AssignmentSubmission.__table__.create(db.engine, checkfirst=True)
            StudyMaterial.__table__.create(db.engine, checkfirst=True)
            AcademicResourceAudit.__table__.create(db.engine, checkfirst=True)
            NotificationPreference.__table__.create(db.engine, checkfirst=True)
            PushSubscription.__table__.create(db.engine, checkfirst=True)
            StudentSemesterTimetable.__table__.create(db.engine, checkfirst=True)
        except Exception:
            pass

        # System Admin with Address & Dept
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(
                username='admin', 
                password=generate_password_hash('bms123'), 
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
                password=generate_password_hash('bms123'), 
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
        
        faculties = [
            ('balram', 'Mr. Balaram M', 'Faculty', 'balram@bmsccm.edu', 'General', 'Hindu', '1982-04-15', '2015-06-01', 'Computer Applications', 'BMS-BCA-101', 'Jayanagar 4th Block, Bengaluru'),
            ('kiran', 'Dr.Kiran Kumar M N', 'HOD - BCA Dept', 'kiran.hod@bmsccm.edu', 'General', 'Hindu', '1978-11-20', '2010-01-15', 'Computer Applications', 'BMS-BCA-001', 'Banashankari 3rd Stage, Bengaluru'),
            ('shrinkala', 'Ms. Shrinkala Kumari', 'Faculty', 'shrinkala@bmsccm.edu', 'General', 'Hindu', '1992-08-30', '2021-09-10', 'Computer Applications', 'BMS-BCA-102', 'V.V. Puram, Bengaluru'),
            ('shivani', 'Ms. Shivani Shikha', 'Faculty', 'shivani@bmsccm.edu', 'General', 'Hindu', '1988-03-05', '2019-02-14', 'Computer Applications', 'BMS-BCA-103', 'Basavanagudi, Bengaluru'),
            ('bhoomika', 'Ms. Bhoomika Hegde', 'Faculty', 'bhoomika@bmsccm.edu', 'General', 'Hindu', '1993-07-15', '2023-08-01', 'Computer Applications', 'BMS-BCA-104', 'Basavanagudi, Bengaluru'),
            ('gururaj', 'Mr. Gururaj', 'Faculty', 'gururaj@bmsccm.edu', 'General', 'Hindu', '1987-11-20', '2022-01-10', 'Computer Applications', 'BMS-BCA-105', 'Jayanagar, Bengaluru'),
            ('ramkishore', 'Mr. Ramkishore', 'Faculty', 'ramkishore@bmsccm.edu', 'General', 'Hindu', '1985-12-12', '2017-07-20', 'Commerce', 'BMS-COM-103', 'JP Nagar, Bengaluru'),
            ('prathiba', 'Mrs. Prathiba Singh', 'Faculty', 'prathiba@bmsccm.edu', 'General', 'Hindu', '1990-05-25', '2022-11-01', 'Management', 'BMS-MGT-202', 'Uttarahalli, Bengaluru'),
            ('newfac', 'New Faculty', 'Faculty', 'new@bmsccm.edu', 'General', 'Not Specified', '1998-01-01', '2025-01-01', 'Commerce', 'BMS-COM-999', 'Bengaluru South'),
            ('pankaj', 'Dr. Pankaj Choudhry', 'Principal', 'principal@bmsccm.edu', 'General', 'Hindu', '1975-09-10', '2005-08-15', 'Executive', 'BMS-EXE-001', 'Principal Quarters, BMSCCM')
        ]

        for u, f, r, e, c, rel, d, j, dept, did, addr in faculties:
            user_obj = User.query.filter_by(username=u).first()
            if not user_obj:
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
            else:
                if user_obj.full_name != f:
                    user_obj.full_name = f
                
        db.session.commit()
        if not Timetable.query.first():
            print("Injecting heavy timetable data...")
            inject_heavy_timetable()
            print("Timetable populated successfully!")

        # Always synchronize authoritative BCA Sem V timetable and clean stale entries
        sync_authoritative_timetable()

        # Always inject authoritative BCA Sem V student roster
        inject_official_students()

        # Seed initial assessment cutoff dates for BCA Sem V if not present
        if AssessmentCutoff.query.count() == 0:
            default_cutoffs = [
                AssessmentCutoff(course='BCA', semester='Sem V', section='A', subject=None, assessment_cycle='2026-27', component='IA1', cutoff_date=date(2026, 10, 5)),
                AssessmentCutoff(course='BCA', semester='Sem V', section='A', subject=None, assessment_cycle='2026-27', component='IA2', cutoff_date=date(2026, 11, 15)),
                AssessmentCutoff(course='BCA', semester='Sem V', section='A', subject=None, assessment_cycle='2026-27', component='Final IA', cutoff_date=date(2026, 12, 10)),
            ]
            db.session.add_all(default_cutoffs)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Seed Database Warning: {e}")


        

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

    return jsonify({
        'attendance_trend': {'labels': att_trend_labels, 'values': att_trend_values},
        'leave_status': {'labels': leave_labels, 'values': leave_values},
        'expense_by_category': {'labels': exp_labels, 'values': exp_values},
        'monthly_payroll': {'labels': payroll_labels, 'values': payroll_values}
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

WHITELISTED_TOOLS = {
    'count_leaves': ai_count_leaves_this_week,
    'pending_expenses': ai_pending_expenses,
    'staff_by_department': ai_staff_count_by_department,
    'total_payroll': ai_total_payroll,
    'today_attendance': ai_today_attendance
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
        answer_text = "I can answer questions about staff leaves, pending expense claims, department headcounts, monthly payroll costs, and today's attendance."

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

@app.route('/attendance/checkin', methods=['GET', 'POST'])
@login_required
def attendance_qr_checkin():
    token = request.values.get('token', '')
    user_ip = request.remote_addr or '127.0.0.1'

    # 1. ROTATING QR TOKEN VALIDATION
    is_valid_token, tok_msg = validate_rotating_qr_token(token)
    if not is_valid_token:
        log_action(f"Rejected QR Check-in: Expired/Invalid Token ({token[:8]}...)", target=current_user.full_name)
        flash('❌ Verification Failed: QR Token expired or invalid. Please scan the live 30-second rotating QR code on the campus display.', 'danger')
        return redirect(url_for('attendance'))

    # If GET request and no coordinates provided: show mobile-friendly GPS verification page
    lat_val = request.values.get('lat')
    lon_val = request.values.get('lon')
    if request.method == 'GET' and (lat_val is None or lat_val == ''):
        cfg = get_geofence_config()
        return render_template('attendance_qr_verify.html', token=token, geofence_cfg=cfg)

    # Coordinates are provided (either POST from the verify page or direct submission)
    accuracy_val = request.values.get('accuracy')
    client_ts_val = request.values.get('client_timestamp')
    client_inside = request.values.get('is_inside_campus')

    # 2. SERVER-SIDE GEOFENCE ENFORCEMENT
    is_valid_loc, reason_code, loc_msg, details = verify_campus_presence(
        lat=lat_val,
        lon=lon_val,
        accuracy=accuracy_val,
        client_timestamp=client_ts_val,
        client_is_inside=client_inside
    )

    if not is_valid_loc:
        log_action(f"Rejected QR Check-in Location: {reason_code} ({loc_msg})", target=current_user.full_name)
        flash(f'❌ Campus Presence Verification Failed: {loc_msg}', 'danger')
        if request.is_json:
            return jsonify({'success': False, 'error': loc_msg, 'reason_code': reason_code, 'details': details}), 400
        return redirect(url_for('attendance'))

    # 3. NETWORK CONTEXT CHECK
    ip_ok, ip_msg = check_ip_network_context(user_ip)
    if not ip_ok:
        log_action(f"Flagged QR Check-in IP: {user_ip} (Off-Campus Network)", target=current_user.full_name)

    # 4. DEVICE BINDING
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

    today_str = get_ist_time().strftime('%Y-%m-%d')
    existing_att = Attendance.query.filter_by(user_id=current_user.id, date=today_str).first()
    checkin_time = get_ist_time().strftime('%I:%M %p')

    val_lat = details.get('lat')
    val_lon = details.get('lon')
    val_acc = details.get('accuracy')
    loc_status = reason_code

    if existing_att:
        if not existing_att.check_out:
            existing_att.check_out = checkin_time
            existing_att.lat = val_lat
            existing_att.lon = val_lon
            existing_att.accuracy = val_acc
            existing_att.location_status = loc_status
            metrics = compute_attendance_metrics(existing_att.check_in, checkin_time)
            db.session.commit()
            
            resp = make_response(redirect(url_for('attendance')))
            resp.set_cookie('bms_device_id', device_cookie, max_age=365*24*3600)
            flash(f'✅ Clocked Out via QR Code at {checkin_time}! Total Worked: {metrics["total_hours"]} hrs. Campus presence verified.', 'success')
            return resp
        else:
            flash(f'Already completed check-in & check-out for today ({today_str})!', 'info')
            return redirect(url_for('attendance'))

    # Create New Check-in
    new_att = Attendance(
        user_id=current_user.id,
        date=today_str,
        check_in=checkin_time,
        work_mode='Office',
        lat=val_lat,
        lon=val_lon,
        accuracy=val_acc,
        location_status=loc_status
    )
    db.session.add(new_att)
    
    metrics = compute_attendance_metrics(checkin_time, None)
    if metrics.get('is_late'):
        db.session.add(Notification(message=f"LATE ARRIVAL: {current_user.full_name} clocked in {metrics['late_minutes']} mins late."))
    
    db.session.commit()

    resp = make_response(redirect(url_for('attendance')))
    resp.set_cookie('bms_device_id', device_cookie, max_age=365*24*3600)
    flash(f'✅ Successfully checked in via QR Code at {checkin_time} on {today_str}! Campus presence verified.', 'success')
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
        mail_user = app.config.get('MAIL_USERNAME')
        mail_pwd = app.config.get('MAIL_PASSWORD')
        hr_user = User.query.filter(User.role.in_(['HR', 'admin'])).first()
        if hr_user and hr_user.email and mail_user and mail_pwd:
            try:
                import socket
                orig_timeout = socket.getdefaulttimeout()
                try:
                    socket.setdefaulttimeout(4.0)
                    mail_msg = MailMessage(
                        subject=f"BMS ERP: Daily Close Alert - Missing Check-outs ({today_str})",
                        recipients=[hr_user.email],
                        sender=mail_user,
                        body=f"Hello HR,\n\nThe following {len(missing_names)} staff member(s) clocked in today ({today_str}) but did not register a check-out:\n\n" + "\n".join([f"- {name}" for name in missing_names]) + "\n\nPlease review in the ERP portal.\n\nBMS College ERP Automated System"
                    )
                    mail.send(mail_msg)
                finally:
                    socket.setdefaulttimeout(orig_timeout)
            except Exception as e:
                print(f"Mail send error in daily close: {e}")

    db.session.commit()
    log_action(f"Executed Daily Close: Found {len(missing_names)} missing check-outs", target="System")
    flash(f"Daily Close executed successfully! Flagged {len(missing_names)} missing check-outs.")
    return redirect(url_for('attendance'))

@app.route('/attendance/admin/manual-record', methods=['POST'])
@login_required
def admin_manual_attendance():
    user = User.query.get(session['user_id'])
    if not user or user.role not in ['admin', 'HR', 'Principal']:
        flash('Unauthorized: Administrative attendance correction is restricted to HR/Management.', 'danger')
        return redirect(url_for('attendance')), 403

    target_user_id = request.form.get('user_id')
    att_date = (request.form.get('date') or '').strip()
    check_in = (request.form.get('check_in') or '').strip()
    check_out = (request.form.get('check_out') or '').strip()
    reason = (request.form.get('reason') or '').strip()

    if not target_user_id or not att_date or not check_in:
        flash('Missing required fields: Employee, Date, and Check-in time are mandatory.', 'danger')
        return redirect(url_for('attendance'))

    if not reason:
        flash('Audit Requirement: A clear institutional justification reason is required for manual attendance entry.', 'danger')
        return redirect(url_for('attendance'))

    target_user = User.query.get(int(target_user_id))
    if not target_user:
        flash('Specified employee record does not exist.', 'danger')
        return redirect(url_for('attendance'))

    existing_att = Attendance.query.filter_by(user_id=target_user.id, date=att_date).first()
    if existing_att:
        existing_att.check_in = check_in
        if check_out:
            existing_att.check_out = check_out
        existing_att.work_mode = 'Manual Correction'
        existing_att.location_status = 'ADMIN_MANUAL_CORRECTION'
    else:
        new_att = Attendance(
            user_id=target_user.id,
            date=att_date,
            check_in=check_in,
            check_out=check_out or None,
            work_mode='Manual Correction',
            location_status='ADMIN_MANUAL_CORRECTION',
            lat=None,
            lon=None,
            accuracy=None
        )
        db.session.add(new_att)

    db.session.commit()

    # Immutable Audit Log
    log_action(
        f"Admin Manual Attendance Adjustment: {target_user.full_name} on {att_date} (In: {check_in}, Out: {check_out or '--'}). Reason: {reason}",
        target=target_user.full_name
    )
    flash(f"Manual attendance record logged for {target_user.full_name} on {att_date} with audit trail.", 'success')
    return redirect(url_for('attendance'))


@app.route('/admin/geofence/update', methods=['POST'])
@login_required
def admin_geofence_update():
    user = User.query.get(session['user_id'])
    if not user or user.role not in ['admin', 'Principal']:
        flash('Unauthorized: Geofence configuration is restricted to System Administrators.', 'danger')
        if request.is_json:
            return jsonify({'error': 'Unauthorized'}), 403
        return redirect(url_for('dashboard')), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    updates = {}
    if 'enabled' in data:
        updates['enabled'] = str(data['enabled']).lower() in ('true', '1', 'yes')
    if 'mode' in data and data['mode'] in ('RADIUS', 'POLYGON'):
        updates['mode'] = data['mode']
    if 'center_lat' in data:
        try:
            updates['center_lat'] = float(data['center_lat'])
        except ValueError:
            pass
    if 'center_lon' in data:
        try:
            updates['center_lon'] = float(data['center_lon'])
        except ValueError:
            pass
    if 'radius_meters' in data:
        try:
            updates['radius_meters'] = float(data['radius_meters'])
        except ValueError:
            pass
    if 'max_accuracy_meters' in data:
        try:
            updates['max_accuracy_meters'] = float(data['max_accuracy_meters'])
        except ValueError:
            pass
    if 'max_age_seconds' in data:
        try:
            updates['max_age_seconds'] = int(data['max_age_seconds'])
        except ValueError:
            pass
    if 'polygon' in data and isinstance(data['polygon'], list):
        updates['polygon'] = data['polygon']

    new_cfg = update_geofence_config(updates)
    log_action(f"Updated Campus Geofence Configuration: {updates}", target="Geofence Engine")

    if request.is_json:
        return jsonify({'success': True, 'config': new_cfg})
    flash('Campus Geofence configuration updated successfully.', 'success')
    return redirect(url_for('attendance'))


@app.route('/admin/devices')
@login_required
def admin_devices():
    user = User.query.get(session['user_id'])
    if not user or user.role not in ['admin', 'HR', 'Principal']:
        flash('Unauthorized access to Device Registry.', 'danger')
        return redirect(url_for('dashboard')), 403

    devices = RegisteredDevice.query.order_by(RegisteredDevice.first_seen.desc()).all()
    return render_template('admin_devices.html', devices=devices)

@app.errorhandler(500)
def handle_500_error(e):
    import traceback
    print("🔥 500 ERROR TRACEBACK ON PRODUCTION:")
    traceback.print_exc()
    try:
        db.session.rollback()
    except Exception:
        pass
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500
    flash("An unexpected server error occurred. Session recovered safely.", "danger")
    return redirect(url_for('dashboard')) if session.get('user_id') else redirect(url_for('login'))


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
            print("👉 Default Login: Username: admin | Password: bms123")
            print("="*55 + "\n")
            socketio.run(app, host='127.0.0.1', port=port, allow_unsafe_werkzeug=True)
            break
        except OSError as e:
            if "10048" in str(e) or "address already in use" in str(e).lower():
                print(f"⚠️ Port {port} is occupied, trying next port...")
                continue
            raise e















































































































