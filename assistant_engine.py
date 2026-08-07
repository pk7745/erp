import os, json, re
from datetime import datetime, date

# ==========================================
# DYNAMIC APP & MODEL RESOLVER (CIRCULAR IMPORT SAFE)
# ==========================================
def get_app():
    import app
    return app

# ==========================================
# SAFE NAME RESOLVER HELPER
# ==========================================
def resolve_user_by_name(query_name):
    """
    Safely resolves a spoken or typed name query to a single User record.
    Returns (user_obj, ambiguity_msg)
    """
    if not query_name:
        return None, "No name provided."

    app_mod = get_app()
    User = app_mod.User

    clean_name = query_name.strip().lower()
    # Strip common titles
    for title in ['dr.', 'dr', 'mr.', 'mr', 'mrs.', 'mrs', 'ms.', 'ms', 'prof.', 'prof']:
        if clean_name.startswith(title + ' '):
            clean_name = clean_name[len(title) + 1:].strip()

    all_users = User.query.all()
    exact_matches = []
    partial_matches = []

    for u in all_users:
        fname = u.full_name.lower()
        uname = u.username.lower()

        if clean_name == fname or clean_name == uname:
            exact_matches.append(u)
        elif clean_name in fname or clean_name in uname:
            partial_matches.append(u)

    if len(exact_matches) == 1:
        return exact_matches[0], None
    elif len(exact_matches) > 1:
        names = ", ".join([u.full_name for u in exact_matches])
        return None, f"Multiple users found with exact match: {names}. Please specify full name."

    if len(partial_matches) == 1:
        return partial_matches[0], None
    elif len(partial_matches) > 1:
        names = ", ".join([f"{u.full_name} ({u.department or u.role})" for u in partial_matches[:4]])
        return None, f"Multiple matching personnel found ({names}). Please specify full name."

    return None, f"No personnel found matching '{query_name}'."


# ==========================================
# TIER 1 WHITELOCKED QUERY FUNCTIONS (ALL AUTHENTICATED STAFF)
# ==========================================

def absent_faculty_today(date_str=None):
    """Returns list of staff on approved leave or not checked in today (Names & Department only)."""
    app_mod = get_app()
    User, Attendance, Leave = app_mod.User, app_mod.Attendance, app_mod.Leave
    
    target_date = date_str or app_mod.get_ist_time().strftime("%Y-%m-%d")
    
    approved_leaves = Leave.query.filter(Leave.date == target_date, Leave.status == 'Approved').all()
    on_leave_uids = {l.user_id for l in approved_leaves if l.user}
    
    checked_in_uids = {a.user_id for a in Attendance.query.filter(Attendance.date == target_date).all()}
    
    all_users = User.query.all()
    absent_list = []
    
    for u in all_users:
        if u.id in on_leave_uids:
            absent_list.append({'name': u.full_name, 'department': u.department or u.role, 'status': 'On Approved Leave'})
        elif u.id not in checked_in_uids:
            absent_list.append({'name': u.full_name, 'department': u.department or u.role, 'status': 'Not Checked In'})
            
    return {
        'date': target_date,
        'absent_count': len(absent_list),
        'absent_personnel': absent_list
    }

def present_faculty_today(date_str=None):
    """Returns list of staff currently checked in today."""
    app_mod = get_app()
    Attendance = app_mod.Attendance
    
    target_date = date_str or app_mod.get_ist_time().strftime("%Y-%m-%d")
    attendance_records = Attendance.query.filter(Attendance.date == target_date).all()
    
    present_list = []
    for att in attendance_records:
        if att.user:
            present_list.append({
                'name': att.user.full_name,
                'department': att.user.department or att.user.role,
                'check_in': att.check_in,
                'check_out': att.check_out or 'Currently Active',
                'work_mode': att.work_mode
            })
            
    return {
        'date': target_date,
        'present_count': len(present_list),
        'present_personnel': present_list
    }

def checkin_time(name, date_str=None):
    """Returns check-in and check-out time for a specific staff member."""
    app_mod = get_app()
    Attendance = app_mod.Attendance
    
    target_date = date_str or app_mod.get_ist_time().strftime("%Y-%m-%d")
    user, err = resolve_user_by_name(name)
    if not user:
        return {'error': err or f"Could not find staff member '{name}'."}
        
    att = Attendance.query.filter(Attendance.user_id == user.id, Attendance.date == target_date).first()
    if not att:
        return {
            'name': user.full_name,
            'date': target_date,
            'status': 'No check-in record found for today.'
        }
        
    return {
        'name': user.full_name,
        'department': user.department,
        'date': target_date,
        'check_in': att.check_in,
        'check_out': att.check_out or 'Not checked out yet',
        'work_mode': att.work_mode
    }

def todays_timetable(name=None):
    """Returns scheduled lectures/classes for a faculty member today."""
    app_mod = get_app()
    Timetable = app_mod.Timetable
    
    user, err = resolve_user_by_name(name) if name else (None, "No name provided")
    today_day = app_mod.get_ist_time().strftime("%A")
    
    query = Timetable.query.filter(Timetable.day == today_day)
    if user:
        query = query.filter(Timetable.user_id == user.id)
        
    classes = query.order_by(Timetable.time).all()
    schedule = []
    for c in classes:
        schedule.append({
            'faculty': c.faculty_rel.full_name if c.faculty_rel else 'Assigned Faculty',
            'subject': c.subject,
            'semester': c.semester,
            'time': c.time,
            'room': c.room,
            'status': c.status
        })
        
    return {
        'day': today_day,
        'person': user.full_name if user else 'All Schedule',
        'total_classes': len(schedule),
        'classes': schedule
    }

def current_class(name=None):
    """Returns the current ongoing lecture for a faculty member right now."""
    app_mod = get_app()
    Timetable = app_mod.Timetable
    
    user, err = resolve_user_by_name(name) if name else (None, "No name provided")
    today_day = app_mod.get_ist_time().strftime("%A")
    now_time_str = app_mod.get_ist_time().strftime("%I:%M %p")
    
    query = Timetable.query.filter(Timetable.day == today_day)
    if user:
        query = query.filter(Timetable.user_id == user.id)
        
    all_today = query.all()
    if not all_today:
        return {'person': user.full_name if user else 'Faculty', 'status': f'No lectures scheduled for {today_day}.'}
        
    return {
        'person': user.full_name if user else 'Faculty',
        'day': today_day,
        'time_now': now_time_str,
        'scheduled_lectures': [{
            'subject': c.subject,
            'semester': c.semester,
            'time': c.time,
            'room': c.room,
            'status': c.status
        } for c in all_today]
    }

def attendance_count(date_str=None):
    """Returns high-level headcount statistics for a date."""
    app_mod = get_app()
    User, Attendance, Leave = app_mod.User, app_mod.Attendance, app_mod.Leave
    
    target_date = date_str or app_mod.get_ist_time().strftime("%Y-%m-%d")
    total_staff = User.query.count()
    present_count = Attendance.query.filter(Attendance.date == target_date).count()
    approved_leave_count = Leave.query.filter(Leave.date == target_date, Leave.status == 'Approved').count()
    absent_count = total_staff - present_count
    
    return {
        'date': target_date,
        'total_staff': total_staff,
        'present': present_count,
        'absent': absent_count,
        'on_leave': approved_leave_count
    }

def is_person_in(name, date_str=None):
    """Simple status query checking if a specific person is on campus today."""
    app_mod = get_app()
    Attendance = app_mod.Attendance
    
    target_date = date_str or app_mod.get_ist_time().strftime("%Y-%m-%d")
    user, err = resolve_user_by_name(name)
    if not user:
        return {'error': err or f"Could not locate staff member '{name}'."}
        
    att = Attendance.query.filter(Attendance.user_id == user.id, Attendance.date == target_date).first()
    is_present = att is not None
    
    return {
        'name': user.full_name,
        'department': user.department,
        'is_present': is_present,
        'status': f"Present (Checked in at {att.check_in})" if is_present else "Not checked in today",
        'date': target_date
    }


# ==========================================
# TIER 2 WHITELOCKED QUERY FUNCTIONS (HR / PRINCIPAL / HOD / ACCOUNTANT ONLY)
# ==========================================

def leave_reason(name=None, date_str=None):
    """Returns the reason and status for a staff member's leave request."""
    app_mod = get_app()
    Leave = app_mod.Leave
    
    target_date = date_str or app_mod.get_ist_time().strftime("%Y-%m-%d")
    if not name:
        leaves = Leave.query.order_by(Leave.date.desc()).limit(10).all()
        results = []
        for l in leaves:
            if l.user:
                results.append({
                    'name': l.user.full_name,
                    'date': l.date,
                    'status': l.status,
                    'reason': l.reason
                })
        return {'scope': 'All Leaves', 'count': len(results), 'leaves': results}

    user, err = resolve_user_by_name(name)
    if not user:
        return {'error': err or f"Staff member '{name}' not found."}
        
    leave_rec = Leave.query.filter(Leave.user_id == user.id, Leave.date == target_date).first()
    if not leave_rec:
        leave_rec = Leave.query.filter(Leave.user_id == user.id).order_by(Leave.date.desc()).first()
        if not leave_rec:
            return {'name': user.full_name, 'status': 'No leave records on file.'}
            
    return {
        'name': user.full_name,
        'department': user.department,
        'leave_date': leave_rec.date,
        'status': leave_rec.status,
        'reason': leave_rec.reason,
        'rejection_reason': leave_rec.rejection_reason if leave_rec.status == 'Rejected' else None
    }

def notification_status(event=None, name=None, date_str=None):
    """Checks NotificationLog to confirm if emails/notifications were SENT or FAILED for a user."""
    app_mod = get_app()
    NotificationLog = app_mod.NotificationLog
    
    user, err = resolve_user_by_name(name) if name else (None, None)
    
    query = NotificationLog.query
    if user:
        query = query.filter(NotificationLog.user_id == user.id)
    if event:
        query = query.filter(NotificationLog.event.like(f"%{event}%"))
        
    logs = query.order_by(NotificationLog.timestamp.desc()).limit(10).all()
    results = []
    for l in logs:
        results.append({
            'event': l.event,
            'channel': l.channel,
            'status': l.status,
            'recipient': l.recipient_user.full_name if l.recipient_user else 'User',
            'detail': l.detail,
            'time': l.timestamp.strftime("%Y-%m-%d %I:%M %p") if l.timestamp else 'N/A'
        })
        
    return {
        'searched_person': user.full_name if user else 'All Staff',
        'searched_event': event or 'All Events',
        'log_count': len(results),
        'dispatches': results
    }

def late_arrivals(date_str=None):
    """Returns records of personnel arriving after 09:10 AM today."""
    app_mod = get_app()
    Attendance = app_mod.Attendance
    
    target_date = date_str or app_mod.get_ist_time().strftime("%Y-%m-%d")
    attendance_records = Attendance.query.filter(Attendance.date == target_date).all()
    
    late_list = []
    for att in attendance_records:
        if att.check_in and att.user:
            if att.check_in > "09:10 AM":
                late_list.append({
                    'name': att.user.full_name,
                    'department': att.user.department,
                    'check_in': att.check_in
                })
                
    return {
        'date': target_date,
        'late_count': len(late_list),
        'late_personnel': late_list
    }

def overtime_today(date_str=None):
    """Returns staff members with recorded overtime today."""
    app_mod = get_app()
    Attendance = app_mod.Attendance
    
    target_date = date_str or app_mod.get_ist_time().strftime("%Y-%m-%d")
    attendance_records = Attendance.query.filter(Attendance.date == target_date).all()
    
    overtime_list = []
    for att in attendance_records:
        if att.check_out and att.user:
            overtime_list.append({
                'name': att.user.full_name,
                'department': att.user.department,
                'check_in': att.check_in,
                'check_out': att.check_out
            })
            
    return {
        'date': target_date,
        'overtime_count': len(overtime_list),
        'records': overtime_list
    }

def monthly_attendance_summary(name, month_str=None):
    """Returns monthly presence, late count, and unrecorded checkouts for a staff member."""
    app_mod = get_app()
    Attendance = app_mod.Attendance
    
    user, err = resolve_user_by_name(name)
    if not user:
        return {'error': err or f"Staff member '{name}' not found."}
        
    target_month = month_str or app_mod.get_ist_time().strftime("%Y-%m")
    records = Attendance.query.filter(Attendance.user_id == user.id, Attendance.date.like(f"{target_month}%")).all()
    
    present_days = len(records)
    late_days = sum(1 for r in records if r.check_in and r.check_in > "09:10 AM")
    missing_outs = sum(1 for r in records if r.check_in and not r.check_out)
    
    return {
        'name': user.full_name,
        'department': user.department,
        'month': target_month,
        'days_present': present_days,
        'late_arrivals': late_days,
        'missing_checkouts': missing_outs
    }

def pending_leaves():
    """Returns list of leave requests awaiting approval."""
    app_mod = get_app()
    Leave = app_mod.Leave
    
    pending_list = Leave.query.filter(Leave.status.like("Pending%")).all()
    results = []
    for l in pending_list:
        if l.user:
            results.append({
                'id': l.id,
                'applicant': l.user.full_name,
                'department': l.user.department,
                'date': l.date,
                'reason': l.reason,
                'status': l.status
            })
    return {
        'pending_count': len(results),
        'requests': results
    }

def pending_expenses():
    """Returns list of expense claims awaiting approval."""
    app_mod = get_app()
    ExpenseClaim = app_mod.ExpenseClaim
    
    claims = ExpenseClaim.query.filter(ExpenseClaim.status != 'Finalized', ExpenseClaim.status != 'Rejected').all()
    results = []
    for c in claims:
        if c.rel_user:
            results.append({
                'id': c.id,
                'applicant': c.rel_user.full_name,
                'category': c.category,
                'amount': c.amount,
                'description': c.description,
                'status': c.status
            })
    return {
        'pending_count': len(results),
        'claims': results
    }


# ==========================================
# REGISTRY WHITELIST & SCHEMAS
# ==========================================

ALLOWED_MANAGEMENT_ROLES = ['admin', 'hr', 'accountant', 'principal', 'hod']

WHITELIST = {
    # TIER 1 — ALL AUTHENTICATED STAFF
    'absent_faculty_today': {
        'fn': absent_faculty_today,
        'tier': 1,
        'allowed_roles': None,
        'description': "Get list of staff who are absent or on approved leave today.",
        'schema': {'date_str': 'Optional date YYYY-MM-DD'}
    },
    'present_faculty_today': {
        'fn': present_faculty_today,
        'tier': 1,
        'allowed_roles': None,
        'description': "Get list of staff members currently present and checked in today.",
        'schema': {'date_str': 'Optional date YYYY-MM-DD'}
    },
    'checkin_time': {
        'fn': checkin_time,
        'tier': 1,
        'allowed_roles': None,
        'description': "Find check-in and check-out times for a staff member.",
        'schema': {'name': 'Staff member name', 'date_str': 'Optional date YYYY-MM-DD'}
    },
    'todays_timetable': {
        'fn': todays_timetable,
        'tier': 1,
        'allowed_roles': None,
        'description': "View scheduled lectures, subjects, rooms, and times for a faculty member today.",
        'schema': {'name': 'Optional faculty name'}
    },
    'current_class': {
        'fn': current_class,
        'tier': 1,
        'allowed_roles': None,
        'description': "Find which class or lecture a faculty member is taking right now.",
        'schema': {'name': 'Optional faculty name'}
    },
    'attendance_count': {
        'fn': attendance_count,
        'tier': 1,
        'allowed_roles': None,
        'description': "Get overall headcount metrics (present, absent, on-leave) for today.",
        'schema': {'date_str': 'Optional date YYYY-MM-DD'}
    },
    'is_person_in': {
        'fn': is_person_in,
        'tier': 1,
        'allowed_roles': None,
        'description': "Check whether a specific staff member is checked in / present today.",
        'schema': {'name': 'Staff member name', 'date_str': 'Optional date YYYY-MM-DD'}
    },

    # TIER 2 — RESTRICTED TO HR / PRINCIPAL / HOD / ACCOUNTANT
    'leave_reason': {
        'fn': leave_reason,
        'tier': 2,
        'allowed_roles': ALLOWED_MANAGEMENT_ROLES,
        'description': "Get the reason and approval status for a staff member's leave.",
        'schema': {'name': 'Staff member name', 'date_str': 'Optional date YYYY-MM-DD'}
    },
    'notification_status': {
        'fn': notification_status,
        'tier': 2,
        'allowed_roles': ALLOWED_MANAGEMENT_ROLES,
        'description': "Check if email notifications (salary, check-out, leave) were SENT or FAILED for a user.",
        'schema': {'event': 'Optional event key', 'name': 'Optional staff name', 'date_str': 'Optional date YYYY-MM-DD'}
    },
    'late_arrivals': {
        'fn': late_arrivals,
        'tier': 2,
        'allowed_roles': ALLOWED_MANAGEMENT_ROLES,
        'description': "List personnel who arrived late (after 09:10 AM) today.",
        'schema': {'date_str': 'Optional date YYYY-MM-DD'}
    },
    'overtime_today': {
        'fn': overtime_today,
        'tier': 2,
        'allowed_roles': ALLOWED_MANAGEMENT_ROLES,
        'description': "List personnel with recorded overtime today.",
        'schema': {'date_str': 'Optional date YYYY-MM-DD'}
    },
    'monthly_attendance_summary': {
        'fn': monthly_attendance_summary,
        'tier': 2,
        'allowed_roles': ALLOWED_MANAGEMENT_ROLES,
        'description': "Get monthly presence, late counts, and missing check-outs summary for a staff member.",
        'schema': {'name': 'Staff member name', 'month_str': 'Optional YYYY-MM month'}
    },
    'pending_leaves': {
        'fn': pending_leaves,
        'tier': 2,
        'allowed_roles': ALLOWED_MANAGEMENT_ROLES,
        'description': "List all leave requests pending approval.",
        'schema': {}
    },
    'pending_expenses': {
        'fn': pending_expenses,
        'tier': 2,
        'allowed_roles': ALLOWED_MANAGEMENT_ROLES,
        'description': "List all expense reimbursement claims pending approval.",
        'schema': {}
    }
}


# ==========================================
# FUNCTION EXECUTION RESOLVER (ROLE & SECURITY GATE)
# ==========================================

def execute_whitelisted_function(func_name, args, user_role, user_id=None):
    """
    Executes a whitelisted function if allowed for user's role.
    Strictly denies forbidden functions or role violations.
    """
    if not func_name or func_name not in WHITELIST:
        return {
            'success': False,
            'reason': 'UNSUPPORTED_FUNCTION',
            'message': f"The requested query '{func_name}' is not in the Whitelist. I can help with attendance, timetables, leave status, and notification logs."
        }

    meta = WHITELIST[func_name]
    role_clean = (user_role or '').lower()

    if meta['tier'] == 2:
        allowed = [r.lower() for r in (meta['allowed_roles'] or [])]
        if not any(r in role_clean for r in allowed):
            return {
                'success': False,
                'reason': 'ROLE_RESTRICTED',
                'message': f"🔒 Security Notice: '{func_name}' requires HR, Principal, HOD, or Accountant privileges. Your role ({user_role}) is restricted from viewing semi-private operational data."
            }

    try:
        fn = meta['fn']
        clean_args = {k: v for k, v in (args or {}).items() if v is not None and v != ''}
        result = fn(**clean_args)
        return {
            'success': True,
            'function_executed': func_name,
            'tier': meta['tier'],
            'data': result
        }
    except Exception as e:
        return {
            'success': False,
            'reason': 'EXECUTION_ERROR',
            'message': f"Error executing '{func_name}': {str(e)}"
        }


# ==========================================
# FORBIDDEN DATA QUERY DETECTOR
# ==========================================

FORBIDDEN_KEYWORDS = [
    'salary', 'pay', 'payroll', 'hra', 'da', 'ta', 'epf', 'pf', 'tds', 'tax', 
    'net pay', 'gross pay', 'dob', 'birth', 'caste', 'religion', 'home address', 
    'address', 'bank', 'ifsc', 'account number', 'phone number', 'personal phone', 
    'personal email', 'pan', 'aadhaar'
]

def is_forbidden_query(user_query):
    """Detects if query targets forbidden Tier 3 personal/payroll markers."""
    query_lower = user_query.lower()
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', query_lower):
            return True, kw
    return False, None


# ==========================================
# GEMINI ROUTER & NATURAL LANGUAGE ENGINE
# ==========================================

def ask_operational_assistant(user_query, user_role, user_id=None):
    """
    Main entry point for AI Operations Assistant.
    """
    forbidden, matched_kw = is_forbidden_query(user_query)
    if forbidden:
        refusal_msg = (
            f"🔒 **Security & Privacy Notice**: Personal identifiers and payroll data "
            f"(such as '{matched_kw}') are **Forbidden by Design** and completely absent from the "
            f"AI Assistant's access whitelist for all roles.\n\n"
            f"Authorized personnel can view official records on the Master Workforce Directory or Staff Directory pages."
        )
        return {
            'answer': refusal_msg,
            'function_used': 'FORBIDDEN_TIER3_REFUSAL',
            'tier': 3,
            'status': 'DENIED'
        }

    role_clean = (user_role or '').lower()
    available_tools = {}
    for name, meta in WHITELIST.items():
        if meta['tier'] == 1:
            available_tools[name] = {'description': meta['description'], 'parameters': meta['schema']}
        elif meta['tier'] == 2 and any(r in role_clean for r in (meta['allowed_roles'] or [])):
            available_tools[name] = {'description': meta['description'], 'parameters': meta['schema']}

    api_key = os.environ.get('GEMINI_API_KEY')
    selected_func = None
    func_args = {}

    if api_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-pro')
            
            system_prompt = (
                "You are an AI Operational Router for a College ERP. "
                "You MUST select exactly ONE function from the allowed whitelist JSON tools to answer the user's question.\n"
                "Return ONLY a JSON object in this format:\n"
                '{"function": "function_name", "args": {"arg1": "value1"}}\n'
                "If no whitelisted function fits, return:\n"
                '{"function": null, "args": {}}\n\n'
                f"Available Whitelisted Tools for user role ({user_role}):\n"
                f"{json.dumps(available_tools, indent=2)}"
            )

            response = model.generate_content(
                f"System: {system_prompt}\nUser Question: {user_query}"
            )
            
            resp_text = response.text.strip()
            json_match = re.search(r'\{.*\}', resp_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                selected_func = parsed.get('function')
                func_args = parsed.get('args', {})
        except Exception as e:
            print(f"Gemini Router Warning: {e}")
            selected_func = None

    # Fallback Rule-Based Router if Gemini API Key missing or unreachable
    if not selected_func:
        q_lower = user_query.lower()
        if 'absent' in q_lower or 'away' in q_lower:
            selected_func = 'absent_faculty_today'
        elif 'present' in q_lower or 'who is in' in q_lower or 'who is here' in q_lower:
            selected_func = 'present_faculty_today'
        elif 'checkin' in q_lower or 'check in' in q_lower or 'time' in q_lower:
            name_match = re.search(r'(?:of|for|did|is)\s+([a-zA-Z\s]+?)(?:\s+check|\s+in|\s+today|\?|$)', q_lower)
            if name_match:
                func_args['name'] = name_match.group(1).strip()
            selected_func = 'checkin_time' if func_args.get('name') else 'present_faculty_today'
        elif 'timetable' in q_lower or 'schedule' in q_lower or 'class' in q_lower:
            selected_func = 'todays_timetable'
        elif 'count' in q_lower or 'total' in q_lower or 'headcount' in q_lower:
            selected_func = 'attendance_count'
        elif 'leave' in q_lower and ('reason' in q_lower or 'why' in q_lower):
            selected_func = 'leave_reason'
        elif 'email' in q_lower or 'notification' in q_lower or 'sent' in q_lower:
            selected_func = 'notification_status'

    if selected_func:
        exec_res = execute_whitelisted_function(selected_func, func_args, user_role, user_id)
        if not exec_res['success']:
            return {
                'answer': exec_res['message'],
                'function_used': selected_func,
                'tier': 0,
                'status': 'DENIED'
            }

        real_data = exec_res['data']

        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                synth_model = genai.GenerativeModel('gemini-pro')
                synth_prompt = (
                    "Synthesize a clear, helpful, natural language answer for the user's operational query based ONLY on the verified data below.\n"
                    "Do NOT invent or extrapolate facts not present in the data.\n\n"
                    f"User Query: {user_query}\n"
                    f"Function Used: {selected_func}\n"
                    f"Verified Data: {json.dumps(real_data, indent=2)}"
                )
                nl_resp = synth_model.generate_content(synth_prompt)
                answer = nl_resp.text.strip()
            except Exception:
                answer = format_fallback_answer(selected_func, real_data)
        else:
            answer = format_fallback_answer(selected_func, real_data)

        return {
            'answer': answer,
            'function_used': selected_func,
            'tier': exec_res['tier'],
            'raw_data': real_data,
            'status': 'SUCCESS'
        }

    capability_msg = (
        "🤖 I am the **BMS ERP Operational AI Assistant**.\n\n"
        "I can answer natural-language operational questions such as:\n"
        "• *Who is absent or present today?*\n"
        "• *What time did Ramesh check in?*\n"
        "• *Which class is Dr. Kiran taking today?*\n"
        "• *Was the check-out reminder email sent to staff?* (Management only)\n"
        "• *Why is Ramesh on leave?* (Management only)\n\n"
        "🔒 *Security Note: Salary, payroll figures, and personal identifiers are forbidden by design.*"
    )
    return {
        'answer': capability_msg,
        'function_used': None,
        'tier': 0,
        'status': 'HELP'
    }


def format_fallback_answer(func_name, data):
    """Clean Python template formatter for function results."""
    if 'error' in data:
        return f"⚠️ {data['error']}"

    if func_name == 'absent_faculty_today':
        cnt = data.get('absent_count', 0)
        personnel = data.get('absent_personnel', [])
        if cnt == 0:
            return "✅ All staff members are present on campus today!"
        items = "\n".join([f"• **{p['name']}** ({p['department']}) — {p['status']}" for p in personnel])
        return f"📋 **Absent Personnel Today ({cnt}):**\n\n{items}"

    elif func_name == 'present_faculty_today':
        cnt = data.get('present_count', 0)
        personnel = data.get('present_personnel', [])
        if cnt == 0:
            return "No staff members have clocked in today yet."
        items = "\n".join([f"• **{p['name']}** ({p['department']}) — Checked in at {p['check_in']}" for p in personnel])
        return f"✅ **Present Personnel Today ({cnt}):**\n\n{items}"

    elif func_name == 'checkin_time':
        return f"🕒 **Attendance Record for {data.get('name')}**:\n• Check-In: **{data.get('check_in')}**\n• Check-Out: **{data.get('check_out')}**\n• Mode: {data.get('work_mode')}"

    elif func_name == 'todays_timetable':
        classes = data.get('classes', [])
        if not classes:
            return f"No scheduled classes found for {data.get('person')} today."
        items = "\n".join([f"• **{c['subject']}** ({c['semester']}) — {c['time']} in Room {c['room']} [{c['status']}]" for c in classes])
        return f"📚 **Today's Class Schedule ({data.get('day')}):**\n\n{items}"

    elif func_name == 'attendance_count':
        return f"📊 **Campus Attendance Headcount Summary ({data.get('date')}):**\n• Total Staff: **{data.get('total_staff')}**\n• Present: **{data.get('present')}**\n• Absent: **{data.get('absent')}**\n• Approved Leave: **{data.get('on_leave')}**"

    elif func_name == 'leave_reason':
        if 'leaves' in data:
            items = "\n".join([f"• **{l['name']}** ({l['date']}) — Status: **{l['status']}** | Reason: {l['reason']}" for l in data['leaves']])
            return f"📋 **Recent Leave Requests:**\n\n{items}"
        return f"📋 **Leave Record for {data.get('name')} ({data.get('leave_date')}):**\n• Status: **{data.get('status')}**\n• Reason: {data.get('reason')}" + (f"\n• Remarks: {data.get('rejection_reason')}" if data.get('rejection_reason') else "")

    elif func_name == 'notification_status':
        dispatches = data.get('dispatches', [])
        if not dispatches:
            return "No matching notification log records found."
        items = "\n".join([f"• [{d['time']}] Event: **{d['event']}** | Channel: {d['channel']} | Status: **{d['status']}** | Recipient: {d['recipient']}" for d in dispatches])
        return f"📲 **Notification Engine Dispatch Logs:**\n\n{items}"

    return f"Result: {json.dumps(data, indent=2)}"
