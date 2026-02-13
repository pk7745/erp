import os
import io
import csv
import pytz
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF

app = Flask(__name__)
# Updated Secret Key
app.secret_key = "bms_college_ultimate_v200"

# Database Configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'bms_college.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata'))

# ==========================================
# 1. DATABASE MODELS
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
    content = db.Text
    is_read = db.Column(db.Boolean, default=False) 
    timestamp = db.Column(db.DateTime, default=get_ist_time)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.String(20))
    check_in = db.Column(db.String(20))
    check_out = db.Column(db.String(20))
    work_mode = db.Column(db.String(20))

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.String(20))
    reason = db.Column(db.String(255))
    status = db.Column(db.String(50), default='Pending')  # Stages: Pending HOD, Pending Principal, Approved, Rejected
    rejection_reason = db.Column(db.String(255)) # New Field for rejection feedback
    
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
    status = db.Column(db.String(50), default='Pending Admin Approval') # Pending Admin, Pending Accountant

class PayrollStructure(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    hra_percent = db.Column(db.Float, default=40.0)
    da_percent = db.Column(db.Float, default=10.0)
    ta_fixed = db.Column(db.Integer, default=2000)
    epf_percent = db.Column(db.Float, default=12.0)

# ==========================================
# 2. APP ROUTES 
# ==========================================

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('home.html')

@app.route('/about')
def about():
    if 'user_id' not in session:
        return redirect(url_for('login'))
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
        else:
            flash('Invalid Username or Password. Please try again.', 'danger')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    today_md = get_ist_time().strftime("%m-%d")
    is_birthday = user.dob[5:] == today_md if user.dob else False
    is_anniversary = user.join_date[5:] == today_md if user.join_date else False

    unread_chats = Message.query.filter_by(receiver_id=user.id, is_read=False).count()
    tasks = Task.query.filter_by(user_id=user.id).all()
    off_days = Attendance.query.filter_by(user_id=user.id, work_mode='Office').count()
    wfh_days = Attendance.query.filter_by(user_id=user.id, work_mode='WFH').count()
    
    # Notification visibility logic
    privileged_roles = ['HR', 'Accountant', 'Principal', 'HOD - BCA Dept']
    if session['role'] in privileged_roles:
        all_notifs = Notification.query.order_by(Notification.timestamp.desc()).all()
        
        if session['role'] == 'Accountant':
            # Filter out Attendance, Meetings, and Tasks for Accountants
            excluded_keywords = ["CLOCK-IN", "CLOCK-OUT", "MEETING", "RECORDING", "TASK", "REPORT"]
            notifs = [n for n in all_notifs if not any(word in n.message for word in excluded_keywords)]
        else:
            # HR, Principal, and HOD see everything
            notifs = all_notifs
    else:
        notifs = []
    
    return render_template('dashboard.html', user=user, notifications=notifs, office_days=off_days, 
                           wfh_days=wfh_days, tasks=tasks, unread_chats=unread_chats,
                           is_birthday=is_birthday, is_anniversary=is_anniversary)
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
        if new_pass:
            user.password = generate_password_hash(new_pass)
        db.session.commit()
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user, payroll=payroll_data)

@app.route('/finance')
def finance_tab():
    if session.get('role') != 'Accountant':
        return redirect(url_for('dashboard'))
    # Filter for claims that HR has already vetted
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
    
    # Logic: Only HR, Accountant, and Principal see the full list. Faculty see only themselves.
    if curr_user.role in ['HR', 'Accountant', 'Principal']:
        employees = User.query.all()
    else:
        employees = [curr_user]
        
    return render_template('staff_directory.html', employees=employees)

@app.route('/create_meeting', methods=['POST'])
def create_meeting():
    if 'user_id' not in session: return redirect(url_for('login'))
    room = request.form.get('room_name').replace(" ", "-")
    new_meet = Meeting(room_name=room, created_by=session['name'])
    db.session.add(new_meet)
    db.session.add(Notification(message=f"MEETING: {session['name']} started a meeting: {room}"))
    db.session.commit()
    return redirect(url_for('dashboard', join_meet=room))

@app.route('/notify_recording/<room_name>')
def notify_recording(room_name):
    if 'user_id' not in session: return jsonify({"status": "error"})
    db.session.add(Notification(message=f"RECORDING: {session['name']} has started recording meeting: {room_name}"))
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
            caste=request.form.get('caste', 'General'),
            religion=request.form.get('religion', 'Not Specified')
        )
        db.session.add(new_user)
        db.session.commit()
        flash('Employee Added. Pending Admin document verification.', 'success')
  return redirect(url_for('staff_directory'))
@app.route('/api/notifications')
def get_notifications():
    role = session.get('role')
    # Principal and HR see all logs
    if role in ['Principal', 'HR']:
        all_notifs = Notification.query.order_by(Notification.timestamp.desc()).limit(10).all()
    elif role == 'Accountant':
        # Accountant sees only finance related
        all_notifs = Notification.query.filter(Notification.message.contains('SALARY')).limit(10).all()
    else:
        return jsonify([])

    return jsonify([{
        'id': n.id,
        'msg': n.message,
        'time': n.timestamp.strftime('%I:%M %p')
    } for n in all_notifs])
    
@app.route('/edit_salary/<int:uid>', methods=['POST'])
def edit_salary(uid):
    if session.get('role') == 'HR':
        emp = User.query.get(uid)
        old_sal = emp.salary
        emp.salary = int(request.form['new_salary'])
        db.session.add(Notification(message=f"SALARY CHANGE: {emp.full_name} updated from ₹{old_sal} to ₹{emp.salary}"))
        db.session.commit()
        flash('Salary Adjusted', 'success')
    return redirect(url_for('staff_directory'))

@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'user_id' not in session: return redirect(url_for('login'))
    today = get_ist_time().strftime("%Y-%m-%d")
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        t_now = get_ist_time().strftime("%I:%M %p")
        
        if not att:
            mode = request.form['work_mode']
            db.session.add(Attendance(user_id=session['user_id'], date=today, check_in=t_now, work_mode=mode))
            # Trigger real-time notification
            db.session.add(Notification(message=f"ATTENDANCE: {user.full_name} ({user.role}) CLOCKED-IN at {t_now}"))
        else:
            att.check_out = t_now
            db.session.add(Notification(message=f"ATTENDANCE: {user.full_name} ({user.role}) CLOCKED-OUT at {t_now}"))
        db.session.commit()
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history)

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    limit, taken = 20, Leave.query.filter_by(user_id=session['user_id'], status='Approved').count()
    
    if request.method == 'POST':
        # Logic for multi-stage routing
        if user.role == 'Principal':
            initial_status = 'Approved'
            msg = "Leave Self-Approved by Principal"
        elif user.role == 'Faculty':
            initial_status = 'Pending HOD'
            msg = f"Leave Request from {user.full_name} (Pending HOD)"
        else:
            # HOD, Accountant, and Admin go directly to Principal
            initial_status = 'Pending Principal'
            msg = f"Leave Request from {user.full_name} (Pending Principal)"
            
        new_leave = Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form['reason'], status=initial_status)
        db.session.add(new_leave)
        db.session.add(Notification(message=msg))
        db.session.commit()
        flash('Leave request processed.', 'success')

    # Visibility Logic
    if user.role == 'Principal':
        leaves = Leave.query.filter(Leave.status.in_(['Pending Principal', 'Approved', 'Rejected'])).all()
    elif user.role == 'HOD - BCA Dept':
        leaves = Leave.query.filter((Leave.status == 'Pending HOD') | (Leave.user_id == user.id)).all()
    elif user.role == 'HR':
        leaves = Leave.query.all()
    else:
        leaves = Leave.query.filter_by(user_id=session['user_id']).all()
        
    return render_template('leave.html', leaves=leaves, leaves_taken=taken, leaves_left=(limit-taken), leave_limit=limit)

@app.route('/approve_leave/<int:id>/<action>')
def approve_leave(id, action):
    if 'user_id' not in session: return redirect(url_for('login'))
    leave_req = Leave.query.get(id)
    role = session.get('role')
    
    if action == 'approve':
        if role == 'HOD - BCA Dept' and leave_req.status == 'Pending HOD':
            leave_req.status = 'Pending Principal'
            db.session.add(Notification(message=f"HOD Approved: {leave_req.user.full_name}'s leave (Pending Principal)"))
        elif role == 'Principal' and leave_req.status == 'Pending Principal':
            leave_req.status = 'Approved'
            db.session.add(Notification(message=f"Principal Approved: {leave_req.user.full_name}'s leave"))
            
    elif action == 'reject':
        reason = request.args.get('reason', 'No reason provided')
        leave_req.status = 'Rejected'
        leave_req.rejection_reason = reason 
        db.session.add(Notification(message=f"Leave REJECTED for {leave_req.user.full_name}: {reason}"))
        
    db.session.commit()
    return redirect(url_for('leave'))
    
@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        amt = float(request.form['amount'])
        db.session.add(ExpenseClaim(user_id=session['user_id'], category=request.form['category'], amount=amt, description=request.form['desc']))
        db.session.add(Notification(message=f"EXPENSE: {user.full_name} submitted a claim for INR {amt}"))
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
    sender = User.query.get(curr_id)
    if request.method == 'POST':
        rid = request.form['receiver_id']
        db.session.add(Message(sender_id=curr_id, receiver_id=rid, content=request.form['content']))
        db.session.add(Notification(message=f"MESSAGE: New internal message from {sender.full_name}"))
        db.session.commit()
        return redirect(url_for('chat', receiver_id=rid))
    
    contacts = User.query.filter(User.id != curr_id).all()
    messages = []
    if receiver_id:
        unread = Message.query.filter_by(sender_id=receiver_id, receiver_id=curr_id, is_read=False).all()
        for m in unread: m.is_read = True
        db.session.commit()
        messages = Message.query.filter(((Message.sender_id == curr_id) & (Message.receiver_id == receiver_id)) | ((Message.sender_id == receiver_id) & (Message.receiver_id == curr_id))).order_by(Message.timestamp.asc()).all()
    return render_template('chat.html', contacts=contacts, messages=messages, receiver_id=receiver_id)

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

# ==========================================
# 3. UTILITY & EXPORT
# ==========================================

@app.route('/export_csv/<rtype>')
def export_csv(rtype):
    if 'user_id' not in session: return redirect(url_for('login'))
    output = io.StringIO()
    writer = csv.writer(output)
    if rtype == 'attendance':
        writer.writerow(['Faculty Name', 'Date', 'Work Mode', 'Check-In', 'Check-Out'])
        records = Attendance.query.all()
        for rec in records:
            user_obj = getattr(rec, 'rel_user', getattr(rec, 'user', None))
            name = user_obj.full_name if user_obj else "Unknown/Deleted"
            mode = getattr(rec, 'status', getattr(rec, 'work_mode', 'N/A'))
            writer.writerow([name, rec.date, mode, rec.check_in, rec.check_out])
    elif rtype == 'expenses':
        writer.writerow(['Faculty Name', 'Category', 'Amount', 'Status', 'Date'])
        claims = ExpenseClaim.query.all()
        for c in claims:
            user_obj = getattr(c, 'rel_user', getattr(c, 'user', None))
            name = user_obj.full_name if user_obj else "Unknown/Deleted"
            writer.writerow([name, c.category, c.amount, c.status, c.payment_date])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={rtype}_report.csv"})

@app.route('/generate_payslip/<int:uid>')
def generate_payslip(uid):
    u = User.query.get(uid)
    if not u: return "User not found", 404
    basic = u.salary
    hra, da, ta = int(basic * 0.40), int(basic * 0.10), 2000
    gross = basic + hra + da + ta
    epf, pt = int((basic + da) * 0.12), 200
    net = gross - (epf + pt)
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 18); pdf.set_text_color(0, 51, 102) 
    pdf.cell(200, 15, txt="BMS COLLEGE OF COMMERCE & MANAGEMENT", ln=True, align='C')
    pdf.set_font("Arial", 'B', 12); pdf.set_text_color(0, 0, 0)
    pdf.cell(200, 10, txt=f"PAYSLIP FOR: {u.full_name.upper()}", ln=True, align='C')
    pdf.cell(200, 10, txt=f"Month: {get_ist_time().strftime('%B %Y')}", ln=True, align='C')
    pdf.ln(10); pdf.set_fill_color(244, 247, 254); pdf.set_font("Arial", 'B', 11)
    pdf.cell(95, 10, "EARNINGS", 1, 0, 'C', True); pdf.cell(95, 10, "DEDUCTIONS", 1, 1, 'C', True)
    pdf.set_font("Arial", '', 10)
    pdf.cell(60, 10, "Basic Salary", 1); pdf.cell(35, 10, f"INR {basic}", 1, 0, 'R')
    pdf.cell(60, 10, "Provident Fund (EPF)", 1); pdf.cell(35, 10, f"INR {epf}", 1, 1, 'R')
    pdf.cell(60, 10, "House Rent (HRA)", 1); pdf.cell(35, 10, f"INR {hra}", 1, 0, 'R')
    pdf.cell(60, 10, "Professional Tax", 1); pdf.cell(35, 10, f"INR {pt}", 1, 1, 'R')
    pdf.cell(60, 10, "Dearness (DA)", 1); pdf.cell(35, 10, f"INR {da}", 1, 0, 'R'); pdf.cell(95, 10, "", 1, 1) 
    pdf.cell(60, 10, "Travel (TA)", 1); pdf.cell(35, 10, f"INR {ta}", 1, 0, 'R'); pdf.cell(95, 10, "", 1, 1) 
    pdf.ln(5); pdf.set_font("Arial", 'B', 11); pdf.cell(60, 10, "GROSS EARNINGS", 1); pdf.cell(35, 10, f"INR {gross}", 1, 0, 'R', True)
    pdf.cell(60, 10, "TOTAL DEDUCTIONS", 1); pdf.cell(35, 10, f"INR {epf+pt}", 1, 1, 'R', True)
    pdf.ln(10); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", 'B', 14)
    pdf.cell(190, 15, txt=f"NET TAKE-HOME PAY: INR {net}", border=0, ln=True, align='C', fill=True)
    pdf.ln(15); current_y = pdf.get_y(); pdf.set_draw_color(0, 51, 102); pdf.set_line_width(0.8); pdf.ellipse(25, current_y + 5, 30, 30, 'D') 
    pdf.set_font("Arial", 'B', 6); pdf.set_text_color(0, 51, 102); pdf.text(28, current_y + 19, "BMS COLLEGE"); pdf.text(32, current_y + 22, "OFFICIAL SEAL")
    pdf.set_xy(130, current_y + 10); pdf.set_font("Courier", 'BI', 12); pdf.set_text_color(0, 0, 128); pdf.cell(50, 10, "FINANCE_BMSCCM", ln=True, align='C')
    pdf.line(135, pdf.get_y(), 175, pdf.get_y()); pdf.set_xy(130, pdf.get_y()); pdf.set_font("Arial", 'B', 10); pdf.set_text_color(0, 0, 0); pdf.cell(50, 7, "Accounts Manager", ln=True, align='C')
    pdf.set_y(-20); pdf.set_text_color(163, 174, 208); pdf.set_font("Arial", 'I', 8); pdf.cell(190, 5, txt="This payslip is digitally verified and issued by the BMS College Finance Module.", ln=True, align='C')
    return send_file(io.BytesIO(pdf.output(dest='S').encode('latin-1')), as_attachment=True, download_name=f"payslip_{u.username}_{get_ist_time().strftime('%m_%Y')}.pdf")

@app.route('/submit_report', methods=['POST'])
def submit_report():
    user = User.query.get(session['user_id'])
    db.session.add(ActivityReport(user_id=session['user_id'], content=request.form['content']))
    db.session.add(Notification(message=f"REPORT: {user.full_name} submitted a new activity report"))
    db.session.commit()
    flash('Report Sent', 'success')
    return redirect(url_for('dashboard'))

@app.route('/add_task', methods=['POST'])
def add_task():
    db.session.add(Task(user_id=session['user_id'], title=request.form['title']))
    db.session.commit()
    return redirect(url_for('dashboard'))

# --- TASK COMPLETION ---
@app.route('/toggle_task/<int:id>')
def toggle_task(id):
    t = Task.query.get(id)
    if t: 
        t.is_done = not t.is_done
        if t.is_done:
            db.session.add(Notification(message=f"TASK COMPLETED: {t.user.full_name} finished '{t.title}'"))
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

# --- WORKFLOW 1: SALARY UPDATE ---

@app.route('/principal_request_salary/<int:uid>', methods=['POST'])
def principal_request_salary(uid):
    if session.get('role') != 'Principal': 
        return "Unauthorized", 403
        
    new_val = int(request.form.get('new_salary'))
    existing = SalaryUpdate.query.filter_by(user_id=uid).first()
    
    if existing:
        existing.new_salary = new_val
        existing.status = 'Pending Admin Approval'
    else:
        new_req = SalaryUpdate(user_id=uid, new_salary=new_val)
        db.session.add(new_req)
    
    db.session.commit()
    return redirect(url_for('staff_directory'))
    
@app.route('/admin_verify_salary/<int:req_id>')
def admin_verify_salary(req_id):
    if session.get('role') != 'HR':
        return "Unauthorized", 403
    req = SalaryUpdate.query.get(req_id)
    req.status = 'Pending Accountant Configuration'
    db.session.add(Notification(message=f"ADMIN APPROVED: Salary change for {req.user_id}"))
    db.session.commit()
    flash("Admin verified. Accountant must now configure payroll.", "success")
    return redirect(url_for('staff_directory'))

@app.route('/finalize_payroll_config', methods=['POST'])
def finalize_payroll_config():
    if session.get('role') != 'Accountant': 
        return "Unauthorized", 403
    
    uid = request.form.get('user_id')
    u = User.query.get(uid)
    if not u:
        flash("User not found", "danger")
        return redirect(url_for('staff_directory'))
    
    # 1. Update the percentages in PayrollStructure
    struct = PayrollStructure.query.filter_by(user_id=uid).first()
    if not struct: 
        struct = PayrollStructure(user_id=uid)
    
    struct.hra_percent = float(request.form.get('hra_pc', 40.0))
    struct.da_percent = float(request.form.get('da_pc', 10.0))
    struct.epf_percent = float(request.form.get('epf_pc', 12.0))
    struct.ta_fixed = int(request.form.get('ta_fixed', 2000))
    
    # 2. Update the actual Salary from the request if it exists
    req = SalaryUpdate.query.filter_by(user_id=uid).first()
    if req:
        u.salary = req.new_salary
        db.session.delete(req)
    
    db.session.add(struct)
    db.session.commit()
    flash("Payroll structure configured and salary updated.", "success")
    return redirect(url_for('staff_directory'))

@app.route('/admin_verify_docs/<int:uid>')
def admin_verify_docs(uid):
    if session.get('role') != 'HR':
        return "Unauthorized", 403
    user = User.query.get(uid)
    if user:
        user.status = 'Pending Payroll Config'
        db.session.add(Notification(message=f"DOCS VERIFIED: {user.full_name}"))
        db.session.commit()
        flash(f"Documents verified for {user.full_name}.", "success")
    return redirect(url_for('staff_directory'))

# ==========================================
# 4. INITIAL SETUP 
# ==========================================
from app import app, db
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='System Admin', email='hr@bmsccm.edu', dob='1985-10-25', join_date='2018-05-10'))
        
    if not User.query.filter_by(username='acc1').first():
        db.session.add(User(username='acc1', password=generate_password_hash('pay123'), role='Accountant', full_name='Rajesh Finance', email='accounts@bmsccm.edu', dob='1990-03-12', join_date='2020-11-20'))
        
    # Updated Faculty List with Different DOB and Join Dates
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
                religion=rel
            ))
            
    db.session.commit()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)














