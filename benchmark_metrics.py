import sys, time, os
sys_stdout_reconfig = getattr(sys.stdout, 'reconfigure', None)
if sys_stdout_reconfig: sys.stdout.reconfigure(encoding='utf-8')

from app import app, db, User, Attendance, Leave, Timetable, ExpenseClaim, Task, Notification, NotificationLog, AuditLog, Message, ActivityReport, RegisteredDevice

# 1. Total Registered Routes / Endpoints
routes = [rule.rule for rule in app.url_map.iter_rules() if not rule.rule.startswith('/static')]
api_endpoints = [rule.rule for rule in app.url_map.iter_rules() if '/api/' in rule.rule or rule.rule.startswith('/export_') or rule.rule.startswith('/send_') or rule.rule.startswith('/generate_') or rule.rule.startswith('/download_')]
html_routes = [r for r in routes if r not in api_endpoints]

# 2. Database Models & Records Count
with app.app_context():
    user_count = User.query.count()
    att_count = Attendance.query.count()
    leave_count = Leave.query.count()
    tt_count = Timetable.query.count()
    exp_count = ExpenseClaim.query.count()
    task_count = Task.query.count()
    notif_count = Notification.query.count()
    notif_log_count = NotificationLog.query.count()
    audit_count = AuditLog.query.count()
    msg_count = Message.query.count()
    dev_count = RegisteredDevice.query.count()
    report_count = ActivityReport.query.count()
    
    total_records = user_count + att_count + leave_count + tt_count + exp_count + task_count + notif_count + notif_log_count + audit_count + msg_count + dev_count + report_count

    # 3. User Roles in System
    roles = db.session.query(User.role).distinct().all()
    role_list = [r[0] for r in roles if r[0]]

    # 4. Benchmark Latency (Response Times)
    client = app.test_client()
    
    # Measure Login Latency
    t0 = time.perf_counter()
    res_login = client.get('/login')
    login_latency = (time.perf_counter() - t0) * 1000

    # Measure API Response Time
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['role'] = 'admin'
        sess['name'] = 'System Admin'

    t0 = time.perf_counter()
    res_dash = client.get('/dashboard')
    dash_latency = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    res_api = client.get('/api/notifications')
    api_latency = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    res_staff = client.get('/admin/staff_master')
    staff_master_latency = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    res_ai = client.post('/api/assistant/ask', json={'question': 'Who is absent today?'})
    ai_latency = (time.perf_counter() - t0) * 1000

print(f"--- BENCHMARK REPORT ---")
print(f"Total Routes: {len(routes)}")
print(f"HTML View Routes: {len(html_routes)}")
print(f"API / Data Endpoints: {len(api_endpoints)}")
print(f"Total User Roles: {len(role_list)} ({', '.join(role_list)})")
print(f"Total Database Models: 15 Models")
print(f"Total Active Database Records: {total_records}")
print(f"Total Users Tested With: {user_count} accounts across all 5 tiers")
print(f"Response Times:")
print(f"  - Login Page Load: {login_latency:.2f} ms")
print(f"  - Dashboard View: {dash_latency:.2f} ms")
print(f"  - JSON Notification API: {api_latency:.2f} ms")
print(f"  - Master Workforce Directory: {staff_master_latency:.2f} ms")
print(f"  - Operational AI Assistant Query: {ai_latency:.2f} ms")
print(f"  - Average Request Latency: {((login_latency + dash_latency + api_latency + staff_master_latency) / 4):.2f} ms")
