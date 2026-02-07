from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import io
import os
import pytz 

app = Flask(__name__)
app.secret_key = "nexus_enterprise_ultimate_2026"

# --- Database Config ---
basedir = os.path.abspath(os.path.dirname(__file__))
# v25 ensures a clean start and fixes the "Internal Server Error" on login
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'nexus_final_v25.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Models ---
class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    users = db.relationship('User', backref='dept', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20)) 
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    salary = db.Column(db.Integer, default=50000)
    address = db.Column(db.String(255), default="Not Set")
    dept_id = db.Column(db.Integer, db.ForeignKey('department.id'))

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.String(20))
    reason = db.Column(db.String(255)) 
    status = db.Column(db.String(20), default='Pending')
    user = db.relationship('User', backref=db.backref('leaves', lazy=True))

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- Routes ---

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session.clear() # Clear old broken sessions
            session['user_id'] = user.id
            session['role'] = user.role
            session['name'] = user.full_name
            return redirect(url_for('dashboard'))
        flash('Invalid Username or Password', 'error')
    return render_template('login.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        user = User.query.filter_by(username=username).first()
        if user:
            # ALERT SENT TO HR
            db.session.add(Notification(message=f"PASSWORD RESET REQUEST: '{username}' ({user.full_name})"))
            db.session.commit()
            flash('Alert sent to HR. They will assist you.', 'success')
            return redirect(url_for('login'))
        flash('Username not found.', 'error')
    return render_template('forgot_password.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_obj = User.query.get(session['user_id'])
    notifications = Notification.query.order_by(Notification.timestamp.desc()).all() if session['role'] == 'HR' else []
    return render_template('dashboard.html', user=user_obj, notifications=notifications)

@app.route('/leave', methods=['GET', 'POST'])
def leave():
    if 'user_id' not in session: return redirect(url_for('login'))
    LEAVE_LIMIT = 2 
    local_tz = pytz.timezone('Asia/Kolkata')
    current_month = datetime.now(local_tz).strftime("%Y-%m")
    
    leaves_taken = Leave.query.filter(Leave.user_id == session['user_id'], Leave.date.like(f"{current_month}%"), Leave.status != 'Rejected').count()
    leaves_left = max(0, LEAVE_LIMIT - leaves_taken)

    if request.method == 'POST':
        if leaves_left > 0:
            new_leave = Leave(user_id=session['user_id'], date=request.form['date'], reason=request.form.get('reason', 'N/A'))
            db.session.add(new_leave)
            db.session.add(Notification(message=f"LEAVE REQUEST: {session['name']}"))
            db.session.commit()
            flash('Leave Applied!', 'success')
            return redirect(url_for('leave'))
    
    leaves = Leave.query.all() if session['role'] == 'HR' else Leave.query.filter_by(user_id=session['user_id']).all()
    return render_template('leave.html', leaves=leaves, leave_limit=LEAVE_LIMIT, leaves_taken=leaves_taken, leaves_left=leaves_left)

@app.route('/staff_directory')
def staff_directory():
    if 'user_id' not in session: return redirect(url_for('login'))
    users = User.query.all()
    return render_template('staff_directory.html', employees=users)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- DB INIT ---
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            dept = Department(name="Operations")
            db.session.add(dept)
            db.session.commit()
            
            hr = User(username='admin', password=generate_password_hash('admin123'), role='HR', full_name='pavan kumar', email='pk@nexus.com', salary=95000, address="123 HR Tower", dept_id=1)
            e1 = User(username='emp1', password=generate_password_hash('pass123'), role='Employee', full_name='John Dsouza', email='john@nexus.com', salary=55000, address="New Delhi", dept_id=1)
            e2 = User(username='emp2', password=generate_password_hash('pass123'), role='Employee', full_name='Kartik Sharma', email='kar@nexus.com', salary=62000, address="Bangalore", dept_id=1)
            e3 = User(username='emp3', password=generate_password_hash('pass123'), role='Employee', full_name='Pranav Avadhani', email='pr@nexus.com', salary=48000, address="Gurgaon", dept_id=1)
            e4 = User(username='emp4', password=generate_password_hash('pass123'), role='Employee', full_name='Parthiv Reddy', email='red@nexus.com', salary=51000, address="Kochi", dept_id=1)
            
            db.session.add_all([hr, e1, e2, e3, e4])
            db.session.commit()

init_db()

if __name__ == '__main__':
    app.run()
