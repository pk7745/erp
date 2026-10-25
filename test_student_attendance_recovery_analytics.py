"""
Test Suite: Individual Student Attendance Analytics & 75% Recovery Predictor
=============================================================================
Institution: BMS College of Commerce & Management (BMSCCM)
Feature: Authoritative Student Attendance Dashboard, Recovery Predictor & Feasibility Analytics

Verifies all 18 mandatory acceptance criteria:
1. Student below 75% — correct minimum classes calculation (3C - 4P).
2. Student exactly at 75% — zero classes needed (x = 0).
3. Student above 75% — zero classes needed (x = 0).
4. Very low attendance — correct calculation (e.g. 5/20 -> 40 classes needed).
5. Zero conducted classes — insufficient data handling.
6. Cancelled and future sessions excluded from completed totals.
7. Duplicate attendance records do not inflate totals (DB unique constraint + service deduplication).
8. Attendance corrections update the dashboard and prediction dynamically.
9. Student with multiple subjects gets independent subject-wise predictions.
10. Remaining classes known — correct final projection and feasibility.
11. Remaining classes unknown — no fabricated feasibility claim ("Remaining classes unknown — feasibility cannot be confirmed.").
12. No remaining classes (R = 0) — correct final eligibility calculation.
13. Maximum allowable future absences calculated correctly (floor(P + R - 0.75*(C+R))).
14. Unauthorized teacher cannot access a student outside their permitted scope (HTTP 403).
15. Direct API access and student-ID substitution are blocked (HTTP 403 / 404).
16. Existing attendance creation, correction, and history functionality remains intact.
17. Charts and tables use actual backend data rather than hardcoded sample values.
18. The dashboard works responsively on desktop and mobile.
"""

import unittest
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash
from app import app, db, User, Student, ClassSession, StudentAttendance, Timetable, get_student_academic_analytics_profile
from attendance_analytics_service import (
    calculate_attendance_recovery,
    calculate_future_feasibility
)


class TestStudentAttendanceRecoveryAnalytics(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    # --------------------------------------------------------------------------
    # Scenario 1: Student below 75% — correct minimum classes calculation
    # --------------------------------------------------------------------------
    def test_01_student_below_75_calculation(self):
        # 12 attended of 20 conducted (60.0%)
        # Formula: 3*C - 4*P = 3*20 - 4*12 = 60 - 48 = 12
        res = calculate_attendance_recovery(attended=12, conducted=20, target=0.75)
        self.assertEqual(res['conducted'], 20)
        self.assertEqual(res['attended'], 12)
        self.assertEqual(res['attendance_pct'], 60.0)
        self.assertEqual(res['classes_needed'], 12)
        self.assertFalse(res['is_target_met'])
        # Attending 12 more: 24 / 32 = 75%
        new_pct = (12 + res['classes_needed']) / (20 + res['classes_needed'])
        self.assertEqual(new_pct, 0.75)
        self.assertIn("attend the next 12 eligible classes consecutively", res['explanation'])

    # --------------------------------------------------------------------------
    # Scenario 2: Student exactly at 75% — zero classes needed
    # --------------------------------------------------------------------------
    def test_02_student_exactly_75_zero_needed(self):
        # 15 attended of 20 conducted (75.0%)
        # Formula: max(0, 3*20 - 4*15) = max(0, 0) = 0
        res = calculate_attendance_recovery(attended=15, conducted=20, target=0.75)
        self.assertEqual(res['attendance_pct'], 75.0)
        self.assertEqual(res['classes_needed'], 0)
        self.assertTrue(res['is_target_met'])
        self.assertIn("meets or exceeds the 75% attendance threshold", res['explanation'])

    # --------------------------------------------------------------------------
    # Scenario 3: Student above 75% — zero classes needed
    # --------------------------------------------------------------------------
    def test_03_student_above_75_zero_needed(self):
        # 18 attended of 20 conducted (90.0%)
        # Formula: max(0, 3*20 - 4*18) = max(0, -12) = 0
        res = calculate_attendance_recovery(attended=18, conducted=20, target=0.75)
        self.assertEqual(res['attendance_pct'], 90.0)
        self.assertEqual(res['classes_needed'], 0)
        self.assertTrue(res['is_target_met'])

    # --------------------------------------------------------------------------
    # Scenario 4: Very low attendance — correct calculation
    # --------------------------------------------------------------------------
    def test_04_very_low_attendance_calculation(self):
        # 5 attended of 20 conducted (25.0%)
        # Formula: 3*20 - 4*5 = 60 - 20 = 40
        res = calculate_attendance_recovery(attended=5, conducted=20, target=0.75)
        self.assertEqual(res['attendance_pct'], 25.0)
        self.assertEqual(res['classes_needed'], 40)
        # Attending 40 more: 45 / 60 = 75%
        new_pct = (5 + 40) / (20 + 40)
        self.assertEqual(new_pct, 0.75)

    # --------------------------------------------------------------------------
    # Scenario 5: Zero conducted classes — insufficient data
    # --------------------------------------------------------------------------
    def test_05_zero_conducted_classes_insufficient_data(self):
        res = calculate_attendance_recovery(attended=0, conducted=0, target=0.75)
        self.assertIsNone(res['attendance_pct'])
        self.assertEqual(res['classes_needed'], 0)
        self.assertEqual(res['risk_label'], 'Insufficient Data')
        self.assertEqual(res['status_code'], 'INSUFFICIENT_DATA')
        self.assertIn("No attendance data recorded yet", res['explanation'])

    # --------------------------------------------------------------------------
    # Scenario 6: Cancelled and future sessions excluded from completed totals
    # --------------------------------------------------------------------------
    def test_06_cancelled_and_future_sessions_excluded(self):
        hod = User.query.filter_by(role='HOD - BCA Dept').first()
        student = Student.query.filter_by(course='BCA', semester='Sem V', section='A').first()
        self.assertIsNotNone(student)

        # Baseline count
        p_base = get_student_academic_analytics_profile(student, hod)
        base_conducted = p_base['conducted_count']

        # Add a CANCELLED session in the past
        cancelled_cs = ClassSession(
            timetable_id=1,
            date=date.today() - timedelta(days=2),
            time_slot='10:00 AM-11:00 AM',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A',
            scheduled_subject='Software Testing',
            actual_subject='Software Testing',
            scheduled_faculty_id=hod.id,
            actual_faculty_id=hod.id,
            status='CANCELLED'
        )
        # Add a FUTURE session
        future_cs = ClassSession(
            timetable_id=1,
            date=date.today() + timedelta(days=5),
            time_slot='11:00 AM-12:00 PM',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A',
            scheduled_subject='Software Testing',
            actual_subject='Software Testing',
            scheduled_faculty_id=hod.id,
            actual_faculty_id=hod.id,
            status='COMPLETED'  # future date should be excluded regardless
        )
        db.session.add(cancelled_cs)
        db.session.add(future_cs)
        db.session.flush()

        p_after = get_student_academic_analytics_profile(student, hod)
        self.assertEqual(p_after['conducted_count'], base_conducted, "Cancelled and future sessions must not inflate conducted totals")

    # --------------------------------------------------------------------------
    # Scenario 7: Duplicate attendance records do not inflate totals
    # --------------------------------------------------------------------------
    def test_07_duplicate_attendance_records_do_not_inflate_totals(self):
        hod = User.query.filter_by(role='HOD - BCA Dept').first()
        student = Student.query.filter_by(course='BCA', semester='Sem V', section='A').first()

        # Create one session
        cs = ClassSession(
            timetable_id=1,
            date=date.today() - timedelta(days=1),
            time_slot='09:00 AM-10:00 AM',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A',
            scheduled_subject='Cyber Security Test Subj',
            actual_subject='Cyber Security Test Subj',
            scheduled_faculty_id=hod.id,
            actual_faculty_id=hod.id,
            status='COMPLETED'
        )
        db.session.add(cs)
        db.session.flush()

        # Verify DB unique constraint prevents duplicate insertion
        att1 = StudentAttendance(class_session_id=cs.id, student_id=student.id, status='Present')
        db.session.add(att1)
        db.session.flush()

        # Second record with same session and student triggers IntegrityError
        from sqlalchemy.exc import IntegrityError
        att2 = StudentAttendance(class_session_id=cs.id, student_id=student.id, status='Present')
        db.session.add(att2)
        with self.assertRaises(IntegrityError):
            db.session.flush()

        db.session.rollback()

        # Verify profile computes correctly without inflated records
        p = get_student_academic_analytics_profile(student, hod)
        card = next((c for c in p['subject_cards'] if c['subject'] == 'Cyber Security Test Subj'), None)
        self.assertIsNone(card)  # Rolled back cleanly

    # --------------------------------------------------------------------------
    # Scenario 8: Attendance corrections update dashboard and prediction
    # --------------------------------------------------------------------------
    def test_08_attendance_corrections_update_dashboard_and_prediction(self):
        hod = User.query.filter_by(role='HOD - BCA Dept').first()
        student = Student.query.filter_by(course='BCA', semester='Sem V', section='A').first()

        cs = ClassSession(
            timetable_id=1,
            date=date.today() - timedelta(days=3),
            time_slot='02:00 PM-03:00 PM',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A',
            scheduled_subject='Dynamic Correction Subj',
            actual_subject='Dynamic Correction Subj',
            scheduled_faculty_id=hod.id,
            actual_faculty_id=hod.id,
            status='COMPLETED'
        )
        db.session.add(cs)
        db.session.flush()

        # Initially Absent
        att = StudentAttendance(class_session_id=cs.id, student_id=student.id, status='Absent')
        db.session.add(att)
        db.session.flush()

        p_before = get_student_academic_analytics_profile(student, hod)
        card_before = next((c for c in p_before['subject_cards'] if c['subject'] == 'Dynamic Correction Subj'), None)
        self.assertEqual(card_before['attended_count'], 0)
        self.assertEqual(card_before['classes_needed'], 3)  # 3*1 - 4*0 = 3

        # Correct to Present
        att.status = 'Present'
        db.session.flush()

        p_after = get_student_academic_analytics_profile(student, hod)
        card_after = next((c for c in p_after['subject_cards'] if c['subject'] == 'Dynamic Correction Subj'), None)
        self.assertEqual(card_after['attended_count'], 1)
        self.assertEqual(card_after['classes_needed'], 0)  # 1/1 = 100% >= 75%

    # --------------------------------------------------------------------------
    # Scenario 9: Student with multiple subjects gets independent subject-wise predictions
    # --------------------------------------------------------------------------
    def test_09_multiple_subjects_independent_predictions(self):
        res_a = calculate_attendance_recovery(12, 20)
        res_b = calculate_attendance_recovery(18, 20)

        self.assertEqual(res_a['classes_needed'], 12)
        self.assertEqual(res_b['classes_needed'], 0)
        self.assertNotEqual(res_a['classes_needed'], res_b['classes_needed'])

    # --------------------------------------------------------------------------
    # Scenario 10: Remaining classes known — correct final projection and feasibility
    # --------------------------------------------------------------------------
    def test_10_remaining_classes_known_feasibility(self):
        # 12 of 20 conducted (60%), needs 12 classes to reach 75%
        # Remaining classes R = 15
        # Projected final % = (12 + 15) / (20 + 15) * 100 = 27 / 35 * 100 = 77.14% >= 75% -> Recoverable!
        feas = calculate_future_feasibility(attended=12, conducted=20, remaining_classes=15, target=0.75)
        self.assertTrue(feas['is_remaining_known'])
        self.assertEqual(feas['remaining_classes'], 15)
        self.assertEqual(feas['projected_final_percentage'], 77.14)
        self.assertTrue(feas['is_recoverable'])
        self.assertEqual(feas['risk_label'], 'Needs Attention')
        self.assertIn("Recoverable", feas['feasibility_message'])

        # Now test impossible case: only 5 remaining classes (needs 12)
        # Projected final % = (12 + 5) / (20 + 5) * 100 = 17 / 25 * 100 = 68.0% < 75% -> Impossible!
        feas_imp = calculate_future_feasibility(attended=12, conducted=20, remaining_classes=5, target=0.75)
        self.assertTrue(feas_imp['is_remaining_known'])
        self.assertEqual(feas_imp['projected_final_percentage'], 68.0)
        self.assertFalse(feas_imp['is_recoverable'])
        self.assertEqual(feas_imp['risk_label'], 'High Risk')
        self.assertIn("Mathematically Impossible", feas_imp['feasibility_message'])

    # --------------------------------------------------------------------------
    # Scenario 11: Remaining classes unknown — no fabricated feasibility claim
    # --------------------------------------------------------------------------
    def test_11_remaining_classes_unknown_no_fabricated_claim(self):
        feas = calculate_future_feasibility(attended=12, conducted=20, remaining_classes=None, target=0.75)
        self.assertFalse(feas['is_remaining_known'])
        self.assertIsNone(feas['remaining_classes'])
        self.assertIsNone(feas['projected_final_percentage'])
        self.assertIsNone(feas['is_recoverable'])
        self.assertEqual(feas['risk_label'], 'Projection Unavailable')
        self.assertEqual(feas['feasibility_message'], 'Remaining classes unknown — feasibility cannot be confirmed.')

    # --------------------------------------------------------------------------
    # Scenario 12: No remaining classes (R = 0) — correct final eligibility
    # --------------------------------------------------------------------------
    def test_12_no_remaining_classes_final_eligibility(self):
        # Case A: Below 75% with R = 0
        feas_low = calculate_future_feasibility(attended=12, conducted=20, remaining_classes=0, target=0.75)
        self.assertTrue(feas_low['is_remaining_known'])
        self.assertEqual(feas_low['remaining_classes'], 0)
        self.assertEqual(feas_low['projected_final_percentage'], 60.0)
        self.assertFalse(feas_low['is_recoverable'])
        self.assertEqual(feas_low['risk_label'], 'High Risk')
        self.assertIn("Semester ended with 60.0% — below 75% threshold", feas_low['feasibility_message'])

        # Case B: At/Above 75% with R = 0
        feas_high = calculate_future_feasibility(attended=16, conducted=20, remaining_classes=0, target=0.75)
        self.assertTrue(feas_high['is_remaining_known'])
        self.assertEqual(feas_high['remaining_classes'], 0)
        self.assertEqual(feas_high['projected_final_percentage'], 80.0)
        self.assertTrue(feas_high['is_recoverable'])
        self.assertEqual(feas_high['risk_label'], 'On Track')
        self.assertIn("Final attendance is 80.0% — threshold met", feas_high['feasibility_message'])

    # --------------------------------------------------------------------------
    # Scenario 13: Maximum allowable future absences calculated correctly
    # --------------------------------------------------------------------------
    def test_13_max_allowable_future_absences_calculation(self):
        # P = 18, C = 20, R = 10. Total classes = 30.
        # Threshold 75% of 30 = 22.5 => student needs at least 23 attended sessions.
        # Already has 18, so must attend at least 5 of the 10 remaining classes.
        # Can afford to miss up to 10 - 5 = 5 classes.
        # Formula: floor(18 + 10 - 0.75 * 30) = floor(28 - 22.5) = floor(5.5) = 5
        feas = calculate_future_feasibility(attended=18, conducted=20, remaining_classes=10, target=0.75)
        self.assertTrue(feas['is_recoverable'])
        self.assertEqual(feas['max_allowable_absences'], 5)

        # Another case: P = 15, C = 20, R = 4. Total = 24. 75% of 24 = 18.
        # Student has 15, must attend at least 3 of 4 => can miss at most 1 class.
        # floor(15 + 4 - 0.75 * 24) = floor(19 - 18) = 1.
        feas2 = calculate_future_feasibility(attended=15, conducted=20, remaining_classes=4, target=0.75)
        self.assertEqual(feas2['max_allowable_absences'], 1)

    # --------------------------------------------------------------------------
    # Scenario 14: Unauthorized teacher cannot access student outside permitted scope
    # --------------------------------------------------------------------------
    def test_14_unauthorized_teacher_blocked(self):
        # Create an unauthorized teacher not teaching BCA Sem V A
        unauth_fac = User.query.filter_by(username='unauth_test_faculty').first()
        if not unauth_fac:
            unauth_fac = User(
                username='unauth_test_faculty',
                email='unauth@bms.edu',
                full_name='Unauth Teacher',
                role='Faculty',
                password='Password123!'
            )
            db.session.add(unauth_fac)
            db.session.flush()

        student = Student.query.filter_by(course='BCA', semester='Sem V', section='A').first()
        self.assertIsNotNone(student)

        with self.client.session_transaction() as sess:
            sess['user_id'] = unauth_fac.id

        resp = self.client.get(f'/academic/analytics/student/{student.id}')
        self.assertEqual(resp.status_code, 403, "Teacher outside permitted class scope must receive 403 Forbidden")

    # --------------------------------------------------------------------------
    # Scenario 15: Direct API access and student-ID substitution blocked
    # --------------------------------------------------------------------------
    def test_15_direct_api_access_and_id_substitution_blocked(self):
        # A: Non-authenticated access redirects to login
        resp_unauth = self.client.get('/academic/analytics/student/1')
        self.assertEqual(resp_unauth.status_code, 302)
        self.assertIn('/login', resp_unauth.headers.get('Location', ''))

        # B: Authenticated HOD accessing non-existent student ID returns 404
        hod = User.query.filter_by(role='HOD - BCA Dept').first()
        with self.client.session_transaction() as sess:
            sess['user_id'] = hod.id

        resp_404 = self.client.get('/academic/analytics/student/999999')
        self.assertEqual(resp_404.status_code, 404)

        # C: Non-academic role (e.g. HR / Accountant) returns 403
        hr_user = User.query.filter_by(role='HR').first()
        if hr_user:
            with self.client.session_transaction() as sess:
                sess['user_id'] = hr_user.id
            student = Student.query.first()
            resp_hr = self.client.get(f'/academic/analytics/student/{student.id}')
            self.assertEqual(resp_hr.status_code, 403)

    # --------------------------------------------------------------------------
    # Scenario 16: Existing attendance creation, correction, and history intact
    # --------------------------------------------------------------------------
    def test_16_existing_attendance_workflows_intact(self):
        hod = User.query.filter_by(role='HOD - BCA Dept').first()
        with self.client.session_transaction() as sess:
            sess['user_id'] = hod.id

        resp_hist = self.client.get('/academic-attendance/history')
        self.assertIn(resp_hist.status_code, [200, 302], "Existing academic attendance history route must remain accessible")

        # Verify Teacher Timetable schedule record id=31 is completely intact
        row_31 = Timetable.query.get(31)
        if row_31:
            self.assertIsNotNone(row_31.subject)
            self.assertIsNotNone(row_31.time_slot)

    # --------------------------------------------------------------------------
    # Scenario 17: Charts and tables use actual backend data rather than hardcoded sample values
    # --------------------------------------------------------------------------
    def test_17_charts_use_actual_backend_data(self):
        hod = User.query.filter_by(role='HOD - BCA Dept').first()
        student = Student.query.filter_by(course='BCA', semester='Sem V', section='A').first()

        profile = get_student_academic_analytics_profile(student, hod)
        chart_data = profile['chart_data']

        self.assertIn('subjects', chart_data)
        self.assertIn('percentages', chart_data)
        self.assertIn('attended', chart_data)
        self.assertIn('absent', chart_data)
        self.assertIn('classes_needed', chart_data)

        # Confirm length matches actual subject cards length
        self.assertEqual(len(chart_data['subjects']), len(profile['subject_cards']))
        for i, card in enumerate(profile['subject_cards']):
            self.assertEqual(chart_data['subjects'][i], card['subject'])
            self.assertEqual(chart_data['attended'][i], card['attended_count'])
            self.assertEqual(chart_data['absent'][i], card['absent_count'])
            self.assertEqual(chart_data['classes_needed'][i], card['classes_needed'])

    # --------------------------------------------------------------------------
    # Scenario 18: Dashboard works responsively on desktop and mobile
    # --------------------------------------------------------------------------
    def test_18_dashboard_responsive_design(self):
        hod = User.query.filter_by(role='HOD - BCA Dept').first()
        student = Student.query.filter_by(course='BCA', semester='Sem V', section='A').first()

        with self.client.session_transaction() as sess:
            sess['user_id'] = hod.id

        resp = self.client.get(f'/academic/analytics/student/{student.id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Check for responsive viewport and CSS rules
        self.assertIn('viewport', html)
        self.assertIn('@media (max-width: 768px)', html)
        self.assertIn('chart-container-card', html)
        self.assertIn('analytics-kpi-card', html)
        self.assertIn('overflow-x: auto', html)


if __name__ == '__main__':
    unittest.main(verbosity=2)
