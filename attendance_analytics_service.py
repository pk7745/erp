import math
from datetime import datetime, date


def calculate_attendance_recovery(attended: int, conducted: int, target: float = 0.75) -> dict:
    """
    Core 75% Attendance Recovery Predictor.
    Calculates the exact minimum number of additional consecutive classes a student
    must attend (with 0 absences) to reach the institutional target threshold (default 75%).

    P = attended classes
    C = conducted classes
    T = target percentage (e.g. 0.75)
    x = minimum additional consecutive classes needed

    Formula:
    (P + x) / (C + x) >= T  =>  x >= (T * C - P) / (1 - T)
    For T = 0.75: x = max(0, ceil((0.75 * C - P) / 0.25)) = max(0, 3*C - 4*P).
    """
    if conducted <= 0:
        return {
            'attended': 0,
            'conducted': 0,
            'absent': 0,
            'attendance_pct': None,
            'target_pct': target * 100.0,
            'classes_needed': 0,
            'is_target_met': False,
            'explanation': 'No attendance data recorded yet.',
            'risk_label': 'Insufficient Data',
            'status_code': 'INSUFFICIENT_DATA'
        }

    attended = max(0, attended)
    conducted = max(attended, conducted)
    absent = conducted - attended
    attendance_pct = round((attended * 100.0) / conducted, 2)

    # Use exact integer arithmetic for T = 0.75 to prevent float boundary errors
    if abs(target - 0.75) < 1e-6:
        classes_needed = max(0, 3 * conducted - 4 * attended)
    else:
        classes_needed = max(0, int(math.ceil((target * conducted - attended) / (1.0 - target))))

    is_target_met = (attendance_pct >= (target * 100.0))

    if is_target_met:
        explanation = f"Currently meets or exceeds the {int(target * 100)}% attendance threshold."
    else:
        explanation = (
            f"To reach {int(target * 100)}% in this subject, attend the next {classes_needed} eligible "
            f"classes consecutively, assuming no additional absences."
        )

    return {
        'attended': attended,
        'conducted': conducted,
        'absent': absent,
        'attendance_pct': attendance_pct,
        'target_pct': target * 100.0,
        'classes_needed': classes_needed,
        'is_target_met': is_target_met,
        'explanation': explanation,
    }


def calculate_future_feasibility(
    attended: int,
    conducted: int,
    remaining_classes: int = None,
    target: float = 0.75
) -> dict:
    """
    Determines future-class feasibility and projections for a subject:
    - If remaining_classes is None: "Remaining classes unknown — feasibility cannot be confirmed."
    - If remaining_classes == 0: evaluates final eligibility based on conducted sessions.
    - If remaining_classes > 0:
      projected_final_percentage = (P + R) / (C + R) * 100
      is_recoverable = (projected_final_percentage >= target * 100)
      max_allowable_absences = floor(P + R - target * (C + R))
    """
    recovery = calculate_attendance_recovery(attended, conducted, target)

    if conducted <= 0:
        return {
            **recovery,
            'is_remaining_known': False if remaining_classes is None else True,
            'remaining_classes': remaining_classes,
            'projected_final_percentage': None,
            'is_recoverable': None,
            'max_allowable_absences': None,
            'feasibility_message': 'Insufficient data to project attendance.',
            'risk_label': 'Insufficient Data',
            'status_code': 'INSUFFICIENT_DATA'
        }

    # Case 1: Remaining classes unknown
    if remaining_classes is None:
        if recovery['is_target_met']:
            risk_label = 'On Track'
            status_code = 'ON_TRACK'
        else:
            risk_label = 'Projection Unavailable'
            status_code = 'PROJECTION_UNAVAILABLE'

        return {
            **recovery,
            'is_remaining_known': False,
            'remaining_classes': None,
            'projected_final_percentage': None,
            'is_recoverable': None,
            'max_allowable_absences': None,
            'feasibility_message': 'Remaining classes unknown — feasibility cannot be confirmed.',
            'risk_label': risk_label,
            'status_code': status_code
        }

    # Case 2: No remaining classes (R = 0, Semester ended)
    if remaining_classes == 0:
        final_pct = recovery['attendance_pct']
        is_recoverable = recovery['is_target_met']
        if is_recoverable:
            risk_label = 'On Track'
            status_code = 'ON_TRACK'
            msg = f"Final attendance is {final_pct}% — threshold met."
        else:
            risk_label = 'High Risk'
            status_code = 'HIGH_RISK'
            msg = f"Semester ended with {final_pct}% — below {int(target*100)}% threshold."

        return {
            **recovery,
            'is_remaining_known': True,
            'remaining_classes': 0,
            'projected_final_percentage': final_pct,
            'is_recoverable': is_recoverable,
            'max_allowable_absences': 0,
            'feasibility_message': msg,
            'risk_label': risk_label,
            'status_code': status_code
        }

    # Case 3: Remaining classes known and R > 0
    R = max(0, int(remaining_classes))
    P = recovery['attended']
    C = recovery['conducted']
    x = recovery['classes_needed']

    total_possible_sessions = C + R
    projected_final_percentage = round(((P + R) * 100.0) / total_possible_sessions, 2)
    is_recoverable = (projected_final_percentage >= (target * 100.0))

    if is_recoverable:
        # Max additional absences allowed while still reaching >= target
        # (P + R - m) / (C + R) >= target => m <= P + R - target * (C + R)
        raw_max_absences = (P + R) - (target * total_possible_sessions)
        max_allowable_absences = max(0, int(math.floor(raw_max_absences)))

        if recovery['is_target_met']:
            risk_label = 'On Track'
            status_code = 'ON_TRACK'
            msg = (
                f"On Track: Reaches {projected_final_percentage}% if all {R} remaining classes are attended. "
                f"Can afford up to {max_allowable_absences} absences and still maintain >= {int(target*100)}%."
            )
        else:
            risk_label = 'Needs Attention'
            status_code = 'NEEDS_ATTENTION'
            msg = (
                f"Recoverable: Attending at least {x} of the {R} remaining classes consecutively "
                f"restores attendance to {int(target*100)}% (max allowable absences: {max_allowable_absences})."
            )
    else:
        max_allowable_absences = 0
        risk_label = 'High Risk'
        status_code = 'HIGH_RISK'
        msg = (
            f"Mathematically Impossible: Even with 100% attendance across all {R} remaining classes, "
            f"maximum reachable attendance is {projected_final_percentage}% (needs {x} classes, but only {R} remain)."
        )

    return {
        **recovery,
        'is_remaining_known': True,
        'remaining_classes': R,
        'projected_final_percentage': projected_final_percentage,
        'is_recoverable': is_recoverable,
        'max_allowable_absences': max_allowable_absences,
        'feasibility_message': msg,
        'risk_label': risk_label,
        'status_code': status_code
    }


def resolve_subject_faculty(course, semester, section, subject, completed_sessions, db, Timetable, User):
    """
    Resolves the assigned faculty name for a given subject scope.
    """
    for cs in completed_sessions:
        subj = cs.actual_subject if cs.actual_subject else cs.scheduled_subject
        if subj == subject:
            if cs.actual_faculty and getattr(cs.actual_faculty, 'full_name', None):
                return cs.actual_faculty.full_name
            if cs.scheduled_faculty and getattr(cs.scheduled_faculty, 'full_name', None):
                return cs.scheduled_faculty.full_name

    tt = Timetable.query.filter_by(
        course=course,
        semester=semester,
        section=section,
        subject=subject
    ).first()
    if tt and tt.user_id:
        u = User.query.get(tt.user_id)
        if u and getattr(u, 'full_name', None):
            return u.full_name

    return "Assigned Faculty"


def build_student_attendance_analytics(
    student,
    viewing_user,
    db,
    ClassSession,
    StudentAttendance,
    Timetable,
    User,
    InternalMark,
    MarksEligibilityOverride,
    is_user_authorized_for_context_func,
    get_assessment_maxima_func,
    get_low_marks_threshold_percent_func,
    remaining_classes_by_subject: dict = None
) -> dict:
    """
    Constructs the complete, authoritative individual student attendance analytics payload.
    Enforces deduplication, exclusion of future/cancelled sessions, exact recovery formulas,
    projections, and Chart.js datasets.
    """
    course = student.course
    semester = student.semester
    section = student.section
    today = date.today()

    # 1. Authoritative completed sessions: status == 'COMPLETED' and date <= today
    all_sessions = ClassSession.query.filter_by(
        course=course,
        semester=semester,
        section=section
    ).all()

    completed_sessions = [
        cs for cs in all_sessions
        if cs.status == 'COMPLETED' and cs.date <= today
    ]
    # Sort completed sessions chronologically for trend and reverse-chronologically for table
    completed_sessions.sort(key=lambda cs: (cs.date, cs.id), reverse=True)

    # Scheduled future sessions
    future_scheduled_sessions = [
        cs for cs in all_sessions
        if cs.status == 'SCHEDULED' and cs.date >= today
    ]

    total_conducted_sessions = len(completed_sessions)
    session_ids = [cs.id for cs in completed_sessions]

    # 2. De-duplicate StudentAttendance records by class_session_id
    att_by_session = {}
    if session_ids:
        attendances = StudentAttendance.query.filter(
            StudentAttendance.class_session_id.in_(session_ids),
            StudentAttendance.student_id == student.id
        ).order_by(StudentAttendance.id.desc()).all()

        for a in attendances:
            if a.class_session_id not in att_by_session:
                att_by_session[a.class_session_id] = a.status

    # 3. Overall Student Attendance Metrics
    total_attended = sum(1 for cs_id, status in att_by_session.items() if status == 'Present')
    total_missed = max(0, total_conducted_sessions - total_attended)

    if total_conducted_sessions > 0:
        overall_attendance_pct = round((total_attended * 100.0) / total_conducted_sessions, 2)
        overall_status = 'ELIGIBLE' if overall_attendance_pct >= 75.0 else 'RESTRICTED'
    else:
        overall_attendance_pct = None
        overall_status = 'PENDING'

    # Overall recovery calculation
    overall_recovery = calculate_attendance_recovery(total_attended, total_conducted_sessions, target=0.75)

    # 4. Class Subjects Scope
    class_subjects = sorted(list({
        (cs.actual_subject if cs.actual_subject else cs.scheduled_subject)
        for cs in completed_sessions if (cs.actual_subject or cs.scheduled_subject)
    } | {
        (cs.actual_subject if cs.actual_subject else cs.scheduled_subject)
        for cs in future_scheduled_sessions if (cs.actual_subject or cs.scheduled_subject)
    } | {
        r[0] for r in db.session.query(Timetable.subject).filter_by(
            course=course, semester=semester, section=section
        ).distinct().all() if r[0]
    }))

    # 5. Internal Marks & Overrides
    marks_records = InternalMark.query.filter_by(
        student_id=student.id,
        course=course,
        semester=semester,
        section=section
    ).all()
    marks_by_subject = {m.subject: m for m in marks_records}

    overrides = MarksEligibilityOverride.query.filter_by(
        student_id=student.id,
        course=course,
        semester=semester,
        section=section,
        is_active=True
    ).all()
    overrides_by_subject = {o.subject: o for o in overrides}

    # 6. Subject-Wise Analytics Cards
    subject_cards = []
    subjects_below_75_count = 0
    subjects_at_or_above_75_count = 0
    subjects_no_data_count = 0
    subjects_recoverable_count = 0
    subjects_impossible_count = 0
    subjects_projection_unavailable_count = 0

    for subj in class_subjects:
        subj_sessions = [
            cs for cs in completed_sessions
            if (cs.actual_subject == subj if cs.actual_subject else cs.scheduled_subject == subj)
        ]
        s_conducted = len(subj_sessions)
        s_attended = sum(1 for cs in subj_sessions if att_by_session.get(cs.id) == 'Present')
        s_absent = max(0, s_conducted - s_attended)

        # Faculty resolution
        faculty_name = resolve_subject_faculty(
            course, semester, section, subj, subj_sessions, db, Timetable, User
        )

        # Determine remaining classes for this subject
        # Priority: explicit dictionary parameter > scheduled sessions in DB > None
        if remaining_classes_by_subject is not None and subj in remaining_classes_by_subject:
            rem_classes = remaining_classes_by_subject[subj]
        else:
            future_subj_sessions = [
                cs for cs in future_scheduled_sessions
                if (cs.actual_subject == subj if cs.actual_subject else cs.scheduled_subject == subj)
            ]
            if future_subj_sessions:
                rem_classes = len(future_subj_sessions)
            else:
                rem_classes = None

        feasibility = calculate_future_feasibility(
            attended=s_attended,
            conducted=s_conducted,
            remaining_classes=rem_classes,
            target=0.75
        )

        # Last updated session
        if subj_sessions:
            latest_cs = subj_sessions[0]
            last_updated = latest_cs.date.strftime('%d %b %Y')
        else:
            last_updated = 'No sessions held'

        # Subject-specific session history for drill-down
        subj_history = []
        for cs in subj_sessions[:30]:
            fac = cs.actual_faculty.full_name if cs.actual_faculty else (
                cs.scheduled_faculty.full_name if cs.scheduled_faculty else faculty_name
            )
            subj_history.append({
                'date': cs.date.strftime('%d %b %Y'),
                'time_slot': cs.time_slot,
                'room_no': cs.room_no or 'N/A',
                'faculty_name': fac,
                'status': att_by_session.get(cs.id, 'Unrecorded')
            })

        # Count metrics
        if feasibility['attendance_pct'] is None:
            subjects_no_data_count += 1
            s_status = 'PENDING'
        elif feasibility['is_target_met']:
            subjects_at_or_above_75_count += 1
            s_status = 'ELIGIBLE'
        else:
            subjects_below_75_count += 1
            s_status = 'RESTRICTED'

        if feasibility['is_recoverable'] is True:
            subjects_recoverable_count += 1
        elif feasibility['is_recoverable'] is False:
            subjects_impossible_count += 1
        elif feasibility['is_recoverable'] is None and feasibility['attendance_pct'] is not None and not feasibility['is_target_met']:
            subjects_projection_unavailable_count += 1

        m = marks_by_subject.get(subj)
        override = overrides_by_subject.get(subj)
        can_edit_marks = is_user_authorized_for_context_func(viewing_user, course, semester, section, subj)

        subject_cards.append({
            'subject': subj,
            'faculty_name': faculty_name,
            'conducted_count': s_conducted,
            'attended_count': s_attended,
            'absent_count': s_absent,
            'attendance_pct': feasibility['attendance_pct'],
            'attendance_status': s_status,
            'required_threshold_pct': 75.0,
            'classes_needed': feasibility['classes_needed'],
            'is_target_met': feasibility['is_target_met'],
            'recovery_explanation': feasibility['explanation'],
            'is_remaining_known': feasibility['is_remaining_known'],
            'remaining_classes': feasibility['remaining_classes'],
            'projected_final_percentage': feasibility['projected_final_percentage'],
            'is_recoverable': feasibility['is_recoverable'],
            'max_allowable_absences': feasibility['max_allowable_absences'],
            'feasibility_message': feasibility['feasibility_message'],
            'risk_label': feasibility['risk_label'],
            'status_code': feasibility['status_code'],
            'last_updated': last_updated,
            'override': override,
            'internal_mark': m,
            'can_edit_marks': can_edit_marks,
            'subject_history': subj_history
        })

    # Client-safe JSON serializable subject cards for frontend modals/scripts
    client_subject_cards = [
        {
            'subject': sc['subject'],
            'faculty_name': sc['faculty_name'],
            'conducted_count': sc['conducted_count'],
            'attended_count': sc['attended_count'],
            'absent_count': sc['absent_count'],
            'attendance_pct': sc['attendance_pct'],
            'classes_needed': sc['classes_needed'],
            'is_target_met': sc['is_target_met'],
            'recovery_explanation': sc['recovery_explanation'],
            'is_remaining_known': sc['is_remaining_known'],
            'remaining_classes': sc['remaining_classes'],
            'projected_final_percentage': sc['projected_final_percentage'],
            'is_recoverable': sc['is_recoverable'],
            'max_allowable_absences': sc['max_allowable_absences'],
            'feasibility_message': sc['feasibility_message'],
            'risk_label': sc['risk_label'],
            'status_code': sc['status_code'],
            'last_updated': sc['last_updated'],
            'subject_history': sc['subject_history']
        }
        for sc in subject_cards
    ]

    # 7. Recent Session History Log (All Subjects)
    session_history = []
    for cs in completed_sessions[:50]:
        subj = cs.actual_subject if cs.actual_subject else cs.scheduled_subject
        fac = cs.actual_faculty.full_name if cs.actual_faculty else (
            cs.scheduled_faculty.full_name if cs.scheduled_faculty else 'Faculty'
        )
        session_history.append({
            'date': cs.date,
            'time_slot': cs.time_slot,
            'subject': subj,
            'faculty_name': fac,
            'room_no': cs.room_no or 'N/A',
            'status': att_by_session.get(cs.id, 'Unrecorded')
        })

    # 8. Cumulative Attendance Trend Over Time (Chronological)
    trend_sessions = list(reversed(completed_sessions))
    trend_labels = []
    trend_percentages = []
    running_attended = 0
    running_conducted = 0

    for cs in trend_sessions:
        status = att_by_session.get(cs.id)
        if status in ['Present', 'Absent']:
            running_conducted += 1
            if status == 'Present':
                running_attended += 1
            trend_labels.append(cs.date.strftime('%d %b'))
            trend_percentages.append(round((running_attended * 100.0) / running_conducted, 2))

    # 9. Chart Data Object for Chart.js
    chart_data = {
        'subjects': [sc['subject'] for sc in subject_cards],
        'percentages': [sc['attendance_pct'] if sc['attendance_pct'] is not None else 0 for sc in subject_cards],
        'attended': [sc['attended_count'] for sc in subject_cards],
        'absent': [sc['absent_count'] for sc in subject_cards],
        'classes_needed': [sc['classes_needed'] for sc in subject_cards],
        'trend_labels': trend_labels,
        'trend_percentages': trend_percentages,
        'has_sessions': total_conducted_sessions > 0
    }

    maxima = get_assessment_maxima_func()
    low_marks_threshold_pct = get_low_marks_threshold_percent_func()
    now_utc = datetime.utcnow()

    return {
        'student': student,
        'overall_attendance_pct': overall_attendance_pct,
        'attended_count': total_attended,
        'conducted_count': total_conducted_sessions,
        'total_missed': total_missed,
        'overall_status': overall_status,
        'overall_classes_needed': overall_recovery['classes_needed'],
        'subjects_below_75_count': subjects_below_75_count,
        'subjects_at_or_above_75_count': subjects_at_or_above_75_count,
        'subjects_no_data_count': subjects_no_data_count,
        'subjects_recoverable_count': subjects_recoverable_count,
        'subjects_impossible_count': subjects_impossible_count,
        'subjects_projection_unavailable_count': subjects_projection_unavailable_count,
        'subject_cards': subject_cards,
        'client_subject_cards': client_subject_cards,
        'session_history': session_history,
        'chart_data': chart_data,
        'calculation_timestamp': now_utc.strftime('%d %b %Y, %H:%M UTC'),
        'maxima': maxima,
        'low_marks_threshold_pct': low_marks_threshold_pct
    }
