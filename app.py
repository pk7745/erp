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
app.secret_key = "nexus_ultimate_v200"

# Database Configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_ultimate.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata'))

# ==========================================
# 1. DATABASE MODELS (Appended - No removal)
# ==========================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='Employee') 
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    salary = db.Column(db.Integer, default=50000)
    address = db.Column(db.String(200))
    # NEW FIELDS FOR ANNIVERSARY/ID CARD (Database Update)
    dob = db.Column(db.String(20), default="1995-01-01") 
    join_date = db.Column(db.String(20), default="2023-01-01")
    
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
    status = db.Column(db.String(20), default='Pending')

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

# ==========================================
# 2. APP ROUTES (Fully Synced)
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
    user = User.query.get(session['user_id']) # Get the specific user
    return render_template('about.html', user=user) # Pass user to the page

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        # CORRECTED CHECK: Use check_password_hash because passwords in DB are hashed
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['role'] = user.role  # Ensure role is in session
            session['name'] = user.full_name
            return redirect(url_for('dashboard'))
        else:
            # Only flashes if the check fails
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
    notifs = Notification.query.order_by(Notification.timestamp.desc()).all() if session['role'] in ['HR', 'Accountant'] else []
    
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
    if request.method == 'POST':
        user.full_name = request.form.get('full_name')
        user.email = request.form.get('email')
        user.address = request.form.get('address')
        if request.form.get('password'):
            user.password = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash('Profile Updated Successfully', 'success')
    return render_template('profile.html', user=user)

@app.route('/staff_directory')
def staff_directory():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('staff_directory.html', employees=User.query.all())

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') == 'HR':
        new_user = User(
            username=request.form['username'],
            password=generate_password_hash(request.form['password']),
            full_name=request.form['full_name'],
            email=request.form['email'],
            salary=int(request.form['salary']),
            address=request.form['address'],
            role='Employee',
            dob=request.form.get('dob', '1995-01-01'),
            join_date=request.form.get('join_date', '2023-01-01')
        )
        db.session.add(new_user)
        db.session.commit()
        flash('New Employee Registered', 'success')
    return redirect(url_for('staff_directory'))

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
    if request.method == 'POST':
        att = Attendance.query.filter_by(user_id=session['user_id'], date=today).first()
        t_now = get_ist_time().strftime("%I:%M %p")
        if not att:
            db.session.add(Attendance(user_id=session['user_id'], date=today, check_in=t_now, work_mode=request.form['work_mode']))
        else:
            att.check_out = t_now
        db.session.commit()
    history = Attendance.query.all() if session['role'] == 'HR' else Attendance.query.filter_by(user_id=session['user_id']).all()
    return render_template('attendance.html', history=history)

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    limit = 20
    taken = Leave.query.filter_by(user_id=session['user_id'], status='Approved').count()
    if request.method == 'POST':
        db.session.add(Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form['reason']))
        db.session.commit()
        flash('Leave Request Submitted', 'success')
    leaves = Leave.query.all() if session['role'] == 'HR' else Leave.query.filter_by(user_id=session['user_id']).all()
    return render_template('leave.html', leaves=leaves, leaves_taken=taken, leaves_left=(limit-taken), leave_limit=limit)

@app.route('/approve_leave/<int:id>/<status>')
def approve_leave(id, status):
    if session.get('role') == 'HR':
        l = Leave.query.get(id)
        l.status = status
        db.session.commit()
    return redirect(url_for('leave'))

@app.route('/expenses', methods=['GET', 'POST'])
def expenses():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        db.session.add(ExpenseClaim(user_id=session['user_id'], category=request.form['category'], amount=float(request.form['amount']), description=request.form['desc']))
        db.session.commit()
    claims = ExpenseClaim.query.all() if session['role'] in ['HR', 'Accountant'] else ExpenseClaim.query.filter_by(user_id=session['user_id']).all()
    return render_template('expenses.html', claims=claims)

@app.route('/approve_expense/<int:id>/<action>')
def approve_expense(id, action):
    claim = ExpenseClaim.query.get(id)
    if action == 'hr_approve' and session['role'] == 'HR':
        claim.status = 'Approved by HR'
    elif action == 'acc_approve' and session['role'] == 'Accountant':
        claim.status = 'Finalized'
        claim.payment_date = get_ist_time().strftime("%d-%m-%Y")
        claim.processed_by = session['name']
    elif action == 'reject':
        claim.status = 'Rejected'
    db.session.commit()
    return redirect(url_for('expenses'))

@app.route('/chat', methods=['GET', 'POST'])
@app.route('/chat/<int:receiver_id>', methods=['GET', 'POST'])
def chat(receiver_id=None):
    if 'user_id' not in session: return redirect(url_for('login'))
    curr_id = session['user_id']
    if request.method == 'POST':
        db.session.add(Message(sender_id=curr_id, receiver_id=request.form['receiver_id'], content=request.form['content']))
        db.session.commit()
        return redirect(url_for('chat', receiver_id=request.form['receiver_id']))
    
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

@app.route('/download_attendance_csv')
def download_attendance_csv():
    def generate():
        data = io.StringIO()
        w = csv.writer(data)
        w.writerow(['Name', 'Date', 'Mode', 'In', 'Out'])
        for a in Attendance.query.all():
            w.writerow([a.user.full_name, a.date, a.work_mode, a.check_in, a.check_out])
        yield data.getvalue()
    return Response(generate(), mimetype='text/csv', headers={"Content-disposition":"attachment; filename=attendance.csv"})

@app.route('/download_expenses_csv')
def download_expenses_csv():
    def generate():
        data = io.StringIO()
        w = csv.writer(data)
        w.writerow(['Employee', 'Category', 'Amount', 'Status'])
        for c in ExpenseClaim.query.all():
            w.writerow([c.rel_user.full_name, c.category, c.amount, c.status])
        yield data.getvalue()
    return Response(generate(), mimetype='text/csv', headers={"Content-disposition":"attachment; filename=expenses.csv"})

@app.route('/generate_payslip/<int:uid>')
def generate_payslip(uid):
    u = User.query.get(uid)
    if not u:
        return "User not found", 404

    # --- SALARY CALCULATIONS ---
    basic = u.salary
    hra = int(basic * 0.40)  # 40% of basic
    da = int(basic * 0.10)   # 10% of basic
    ta = 2000                # Fixed Travel Allowance
    
    gross_salary = basic + hra + da + ta
    
    # Deductions
    epf = int((basic + da) * 0.12)  # 12% of Basic + DA
    prof_tax = 200                  # Standard Professional Tax
    
    total_deductions = epf + prof_tax
    net_salary = gross_salary - total_deductions

    # --- PDF GENERATION ---
    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("Arial", 'B', 20)
    pdf.set_text_color(67, 24, 255) # Nexus Primary Blue
    pdf.cell(200, 15, txt="NEXUS INTELLIGENCE SYSTEMS", ln=True, align='C')
    
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(200, 10, txt=f"PAYSLIP FOR: {u.full_name.upper()}", ln=True, align='C')
    pdf.cell(200, 10, txt=f"Month: {get_ist_time().strftime('%B %Y')}", ln=True, align='C')
    pdf.ln(10)

    # Table Header
    pdf.set_fill_color(244, 247, 254) # Nexus BG Gray
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(95, 10, "EARNINGS", 1, 0, 'C', True)
    pdf.cell(95, 10, "DEDUCTIONS", 1, 1, 'C', True)

    # Table Body (Earnings vs Deductions)
    pdf.set_font("Arial", '', 10)
    
    # Row 1
    pdf.cell(60, 10, "Basic Salary", 1); pdf.cell(35, 10, f"INR {basic}", 1, 0, 'R')
    pdf.cell(60, 10, "Provident Fund (EPF)", 1); pdf.cell(35, 10, f"INR {epf}", 1, 1, 'R')
    
    # Row 2
    pdf.cell(60, 10, "House Rent (HRA)", 1); pdf.cell(35, 10, f"INR {hra}", 1, 0, 'R')
    pdf.cell(60, 10, "Professional Tax", 1); pdf.cell(35, 10, f"INR {prof_tax}", 1, 1, 'R')
    
    # Row 3
    pdf.cell(60, 10, "Dearness (DA)", 1); pdf.cell(35, 10, f"INR {da}", 1, 0, 'R')
    pdf.cell(95, 10, "", 1, 1) # Empty cell for alignment
    
    # Row 4
    pdf.cell(60, 10, "Travel (TA)", 1); pdf.cell(35, 10, f"INR {ta}", 1, 0, 'R')
    pdf.cell(95, 10, "", 1, 1) # Empty cell for alignment

    pdf.ln(5)

    # Totals
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(60, 10, "GROSS EARNINGS", 1); pdf.cell(35, 10, f"INR {gross_salary}", 1, 0, 'R', True)
    pdf.cell(60, 10, "TOTAL DEDUCTIONS", 1); pdf.cell(35, 10, f"INR {total_deductions}", 1, 1, 'R', True)

    pdf.ln(10)
    
    # Net Pay Highlight
    pdf.set_fill_color(5, 205, 153) # Nexus Success Green
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(190, 15, txt=f"NET TAKE-HOME PAY: INR {net_salary}", border=0, ln=True, align='C', fill=True)

    pdf.ln(20)
    pdf.set_text_color(163, 174, 208) # Nexus Gray
    pdf.set_font("Arial", 'I', 8)
    pdf.cell(190, 5, txt="This is a computer-generated document and does not require a signature.", ln=True, align='C')

    # Output
    return send_file(
        io.BytesIO(pdf.output(dest='S').encode('latin-1')), 
        as_attachment=True, 
        download_name=f"payslip_{u.username}_{get_ist_time().strftime('%m_%Y')}.pdf"
    )
@app.route('/submit_report', methods=['POST'])
def submit_report():
    db.session.add(ActivityReport(user_id=session['user_id'], content=request.form['content']))
    db.session.commit()
    flash('Report Sent', 'success')
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
    pdf = FPDF()
    pdf.add_page(); pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt=f"NEXUS {rtype.upper()} REPORT", ln=True, align='C')
    return send_file(io.BytesIO(pdf.output(dest='S').encode('latin-1')), as_attachment=True, download_name=f"{rtype}.pdf")

@app.route('/clear_notifications')
def clear_notifications():
    Notification.query.delete()
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/api/stats')
def get_stats():
    u_id = session.get('user_id')
    off = Attendance.query.filter_by(u_id, work_mode='Office').count()
    wfh = Attendance.query.filter_by(u_id, work_mode='WFH').count()
    return jsonify({'office': off, 'wfh': wfh})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==========================================
# 4. INITIAL SETUP (Updated with Unique Seed Data)
# ==========================================
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        # UPDATED: Admin (HR) with unique DOB and Join Date
        db.session.add(User(
            username='admin', 
            password=generate_password_hash('admin123'), 
            role='HR', 
            full_name='System Admin', 
            email='hr@nexus.com',
            dob='1985-10-25',
            join_date='2018-05-10'
        ))
        
        # UPDATED: Accountant with unique DOB and Join Date
        db.session.add(User(
            username='acc1', 
            password=generate_password_hash('pay123'), 
            role='Accountant', 
            full_name='Rajesh Finance', 
            email='finance@nexus.com',
            dob='1990-03-12',
            join_date='2020-11-20'
        ))
        
        # Employees with individual DOB and Join Dates
        emps = [
            ('emp1', 'Amit Sharma', 45000, 'emp1@nexus.com', '1992-05-15', '2021-06-01'),
            ('emp2', 'Priya Singh', 48000, 'emp2@nexus.com', '1994-08-22', '2022-01-15'),
            ('emp3', 'Vikram Aditya', 52000, 'emp3@nexus.com', '1990-12-10', '2020-03-20'),
            ('emp4', 'Sneha Reddy', 46000, 'emp4@nexus.com', '1997-02-10', '2023-09-05')
        ]
        for u, f, s, e, d, j in emps:
            db.session.add(User(
                username=u, 
                password=generate_password_hash('emp123'), 
                role='Employee', 
                full_name=f, 
                salary=s, 
                email=e,
                dob=d,        
                join_date=j   
            ))
        db.session.commit()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)




