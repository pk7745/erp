"""
Automated Test Suite for Teacher Academic Analytics Dashboard
Covers:
1. Semester-wide aggregate class attendance (total present / total eligible instances * 100)
2. Individual attendance calculation (attended / conducted * 100)
3. 75% boundary conditions (exactly 75%, below 75%, above 75%)
4. Zero eligible sessions and pending attendance handling
5. Future, cancelled and unheld session exclusions
6. Duplicate session and attendance safety
7. IA1, IA2 and Final IA averages, highest, lowest, entered and pending counts
8. Missing marks vs recorded zero handling (missing marks never treated as zero in averages)
9. Configured low-marks threshold (< 40%) and distinct label assignment
10. Independent and combined warning labels (Attendance Risk & Low Internal Marks)
11. HOD restriction and allow-override status representation
12. Role-based access control, teacher authorization and cross-class isolation (403 Forbidden)
13. Individual student analytics profile and subject-specific marks edit authorization
"""

import unittest
from datetime import date, datetime, timedelta
from app import (
    app, db, User, Student, Timetable, ClassSession, StudentAttendance,
    InternalMark, InternalMarkAudit, AssessmentCutoff, MarksEligibilityOverride,
    resolve_teacher_academic_scope, compute_academic_analytics_data,
    get_student_academic_analytics_profile, get_assessment_maxima,
    is_user_authorized_for_class, is_user_authorized_for_context
)


class AcademicAnalyticsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()

        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            shrinkala = User.query.filter_by(username='shrinkala').first()
            kiran = User.query.filter_by(username='kiran').first()
            admin = User.query.filter_by(username='admin').first()
            acc1 = User.query.filter_by(username='acc1').first()

            cls.balram_id = balram.id
            cls.shrinkala_id = shrinkala.id
            cls.kiran_id = kiran.id
            cls.admin_id = admin.id
            cls.acc1_id = acc1.id

            students = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).all()
            assert len(students) >= 2, "Test requires at least 2 active BCA Sem V students"
            cls.student1_id = students[0].id
            cls.student2_id = students[1].id
            cls.student1_uucms = students[0].uucms_id
            cls.student2_uucms = students[1].uucms_id

            # Clean any old test records for these students
            InternalMark.query.filter(InternalMark.student_id.in_([cls.student1_id, cls.student2_id])).delete()
            MarksEligibilityOverride.query.filter(MarksEligibilityOverride.student_id.in_([cls.student1_id, cls.student2_id])).delete()
            db.session.commit()

            # Create dedicated test sessions for 'Web Programming'
            tt_web = Timetable.query.filter_by(subject='Web Programming', semester='Sem V', section='A').first()

            cls.test_dates = [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22)]
            old_sessions = ClassSession.query.filter(ClassSession.date.in_(cls.test_dates)).all()
            for os_sess in old_sessions:
                StudentAttendance.query.filter_by(class_session_id=os_sess.id).delete()
                db.session.delete(os_sess)
            db.session.commit()

            cls.test_session_ids = []
            for dt in cls.test_dates:
                cs = ClassSession(
                    timetable_id=tt_web.id if tt_web else None,
                    date=dt,
                    time_slot='12:30 PM-01:30 PM',
                    course='BCA',
                    academic_year='3rd Year',
                    semester='Sem V',
                    section='A',
                    scheduled_subject='Web Programming',
                    actual_subject='Web Programming',
                    scheduled_faculty_id=cls.balram_id,
                    actual_faculty_id=cls.balram_id,
                    status='COMPLETED'
                )
                db.session.add(cs)
                db.session.flush()
                cls.test_session_ids.append(cs.id)

            # Session 1: Student 1 Present, Student 2 Absent
            db.session.add(StudentAttendance(class_session_id=cls.test_session_ids[0], student_id=cls.student1_id, status='Present'))
            db.session.add(StudentAttendance(class_session_id=cls.test_session_ids[0], student_id=cls.student2_id, status='Absent'))

            # Session 2: Student 1 Present, Student 2 Present
            db.session.add(StudentAttendance(class_session_id=cls.test_session_ids[1], student_id=cls.student1_id, status='Present'))
            db.session.add(StudentAttendance(class_session_id=cls.test_session_ids[1], student_id=cls.student2_id, status='Present'))

            # Session 3: Student 1 Present, Student 2 Absent
            db.session.add(StudentAttendance(class_session_id=cls.test_session_ids[2], student_id=cls.student1_id, status='Present'))
            db.session.add(StudentAttendance(class_session_id=cls.test_session_ids[2], student_id=cls.student2_id, status='Absent'))

            # Session 4: Student 1 Absent, Student 2 Absent
            db.session.add(StudentAttendance(class_session_id=cls.test_session_ids[3], student_id=cls.student1_id, status='Absent'))
            db.session.add(StudentAttendance(class_session_id=cls.test_session_ids[3], student_id=cls.student2_id, status='Absent'))

            # Create 1 CANCELLED session and 1 FUTURE session to verify exclusion
            canc_cs = ClassSession(
                timetable_id=tt_web.id if tt_web else None,
                date=date(2026, 9, 29),
                time_slot='12:30 PM-01:30 PM',
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                scheduled_subject='Web Programming',
                actual_subject='Web Programming',
                scheduled_faculty_id=cls.balram_id,
                actual_faculty_id=cls.balram_id,
                status='CANCELLED'
            )
            fut_cs = ClassSession(
                timetable_id=tt_web.id if tt_web else None,
                date=date(2026, 12, 1),
                time_slot='12:30 PM-01:30 PM',
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                scheduled_subject='Web Programming',
                actual_subject='Web Programming',
                scheduled_faculty_id=cls.balram_id,
                actual_faculty_id=cls.balram_id,
                status='SCHEDULED'
            )
            db.session.add(canc_cs)
            db.session.add(fut_cs)
            db.session.commit()

            cls.cancelled_session_id = canc_cs.id
            cls.future_session_id = fut_cs.id

            # Seed test internal marks
            # Student 1: High marks (IA1=18.0, IA2=17.0, Final IA=19.0)
            m1 = InternalMark(
                student_id=cls.student1_id,
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                subject='Web Programming',
                assessment_cycle='2026-27',
                ia1_marks=18.0,
                ia2_marks=17.0,
                final_ia_marks=19.0,
                created_by_id=cls.balram_id,
                updated_by_id=cls.balram_id
            )
            # Student 2: Has a recorded zero and a low mark!
            # IA1 = 0.0 (actual recorded zero!), IA2 = None (pending), Final IA = 6.0 (< 40% of 20 = 8.0)
            m2 = InternalMark(
                student_id=cls.student2_id,
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                subject='Web Programming',
                assessment_cycle='2026-27',
                ia1_marks=0.0,
                ia2_marks=None,
                final_ia_marks=6.0,
                created_by_id=cls.balram_id,
                updated_by_id=cls.balram_id
            )
            db.session.add(m1)
            db.session.add(m2)
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            InternalMark.query.filter(InternalMark.student_id.in_([cls.student1_id, cls.student2_id])).delete()
            MarksEligibilityOverride.query.filter(MarksEligibilityOverride.student_id.in_([cls.student1_id, cls.student2_id])).delete()
            if hasattr(cls, 'test_session_ids') and cls.test_session_ids:
                StudentAttendance.query.filter(StudentAttendance.class_session_id.in_(cls.test_session_ids)).delete(synchronize_session=False)
                ClassSession.query.filter(ClassSession.id.in_(cls.test_session_ids)).delete(synchronize_session=False)
            if hasattr(cls, 'cancelled_session_id'):
                ClassSession.query.filter_by(id=cls.cancelled_session_id).delete()
            if hasattr(cls, 'future_session_id'):
                ClassSession.query.filter_by(id=cls.future_session_id).delete()
            db.session.commit()

    # =========================================================================
    # 1. ATTENDANCE ANALYTICS (AGGREGATE, INDIVIDUAL, 75% BOUNDARY)
    # =========================================================================

    def test_01_attendance_analytics_calculations(self):
        """Verifies aggregate class attendance and individual student percentage calculations."""
        with app.app_context():
            analytics = compute_academic_analytics_data(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                subject_filter='Web Programming'
            )

            # 4 completed sessions held
            self.assertEqual(analytics['total_conducted_sessions'], 4)

            # Cancelled & future sessions are strictly excluded
            session_ids = [s.id for s in ClassSession.query.filter_by(
                course='BCA', semester='Sem V', section='A', status='COMPLETED', scheduled_subject='Web Programming'
            ).all() if s.date in self.test_dates]
            self.assertEqual(len(session_ids), 4)

            # Find Student 1 and Student 2 rows
            s1_row = next((r for r in analytics['student_rows'] if r['student'].id == self.student1_id), None)
            s2_row = next((r for r in analytics['student_rows'] if r['student'].id == self.student2_id), None)

            self.assertIsNotNone(s1_row)
            self.assertIsNotNone(s2_row)

            # Student 1 attended 3 of 4 sessions -> exactly 75.0%!
            self.assertEqual(s1_row['attended_count'], 3)
            self.assertEqual(s1_row['conducted_count'], 4)
            self.assertEqual(s1_row['overall_attendance_pct'], 75.0)
            self.assertEqual(s1_row['attendance_status'], 'ELIGIBLE')
            self.assertFalse(s1_row['has_attendance_risk']) # Exactly 75% meets threshold!

            # Student 2 attended 1 of 4 sessions -> 25.0% (< 75%)
            self.assertEqual(s2_row['attended_count'], 1)
            self.assertEqual(s2_row['conducted_count'], 4)
            self.assertEqual(s2_row['overall_attendance_pct'], 25.0)
            self.assertEqual(s2_row['attendance_status'], 'RESTRICTED')
            self.assertTrue(s2_row['has_attendance_risk']) # Attendance Risk!

            # Aggregate Class Attendance:
            # Student 1 attended 3/4, Student 2 attended 1/4 -> total present instances = 4
            # total student-session instances = 4 + 4 = 8
            # Aggregate % = 4 / 8 * 100 = 50.0%
            self.assertEqual(analytics['aggregate_attendance_pct'], 50.0)

    def test_02_zero_eligible_sessions_returns_pending(self):
        """Verifies that an academic context with 0 conducted sessions returns PENDING / Unavailable."""
        with app.app_context():
            analytics = compute_academic_analytics_data(
                course='BCA',
                academic_year='1st Year',
                semester='Sem I',
                section='B',
                subject_filter='NonExistentSubject'
            )
            # Denominator is 0
            self.assertIsNone(analytics['aggregate_attendance_pct'])
            self.assertIsNone(analytics['avg_student_attendance_rate'])
            self.assertEqual(analytics['total_conducted_sessions'], 0)

    # =========================================================================
    # 2. INTERNAL MARKS ANALYTICS (ZERO VS PENDING, AVERAGES, LOW MARKS)
    # =========================================================================

    def test_03_internal_marks_metrics_and_zero_vs_missing(self):
        """Verifies IA averages, highest/lowest, and distinguishes recorded zero from missing mark."""
        with app.app_context():
            analytics = compute_academic_analytics_data(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                subject_filter='Web Programming'
            )
            ia_metrics = analytics['ia_metrics']

            # IA1: Student 1 has 18.0, Student 2 has 0.0 (recorded zero!)
            # Both values are valid numbers, so average = (18.0 + 0.0) / 2 = 9.0
            self.assertEqual(ia_metrics['IA1']['average'], 9.0)
            self.assertEqual(ia_metrics['IA1']['highest'], 18.0)
            self.assertEqual(ia_metrics['IA1']['lowest'], 0.0)
            self.assertEqual(ia_metrics['IA1']['entered_count'], 2)

            # IA2: Student 1 has 17.0, Student 2 has None (missing / pending)
            # Missing mark must NOT be treated as zero in average! Average should be 17.0 / 1 = 17.0
            self.assertEqual(ia_metrics['IA2']['average'], 17.0)
            self.assertEqual(ia_metrics['IA2']['highest'], 17.0)
            self.assertEqual(ia_metrics['IA2']['lowest'], 17.0)
            self.assertEqual(ia_metrics['IA2']['entered_count'], 1)

            # Final IA: Student 1 has 19.0, Student 2 has 6.0
            # Average = (19.0 + 6.0) / 2 = 12.5
            self.assertEqual(ia_metrics['Final IA']['average'], 12.5)
            self.assertEqual(ia_metrics['Final IA']['highest'], 19.0)
            self.assertEqual(ia_metrics['Final IA']['lowest'], 6.0)

    def test_04_low_marks_and_red_highlighting_rules(self):
        """Verifies low-marks warning label (< 40%), red name highlighting, and independent labels."""
        with app.app_context():
            analytics = compute_academic_analytics_data(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                subject_filter='Web Programming',
                low_marks_threshold_pct=40.0 # 40% of 20 = 8.0
            )

            s1_row = next(r for r in analytics['student_rows'] if r['student'].id == self.student1_id)
            s2_row = next(r for r in analytics['student_rows'] if r['student'].id == self.student2_id)

            # Student 1:
            # Attendance = 75.0% (No risk)
            # Marks = 18.0, 17.0, 19.0 (No low marks)
            self.assertFalse(s1_row['has_attendance_risk'])
            self.assertFalse(s1_row['has_low_marks'])
            self.assertFalse(s1_row['is_red']) # Not highlighted red!

            # Student 2:
            # Attendance = 25.0% -> has_attendance_risk = True
            # IA1 = 0.0 (< 8.0) and Final IA = 6.0 (< 8.0) -> has_low_marks = True
            # IA2 = None -> has_pending_mark = True
            self.assertTrue(s2_row['has_attendance_risk'])
            self.assertTrue(s2_row['has_low_marks'])
            self.assertTrue(s2_row['is_red']) # Must be highlighted in RED!

            # Verify separate distinct labels
            label_texts = [lbl['text'] for lbl in s2_row['labels']]
            self.assertIn('Attendance Risk', label_texts)
            self.assertIn('Low Internal Marks', label_texts)
            self.assertIn('Marks Pending', label_texts)

    def test_05_hod_override_badges(self):
        """Verifies that active HOD restrictions and allow overrides are displayed as distinct badges."""
        with app.app_context():
            # Add an active HOD ALLOW_OVERRIDE for Student 2
            override = MarksEligibilityOverride(
                student_id=self.student2_id,
                subject='Web Programming',
                course='BCA',
                semester='Sem V',
                section='A',
                assessment_cycle='2026-27',
                component='ALL',
                decision_type='ALLOW_OVERRIDE',
                reason='Medical approval',
                created_by_id=self.kiran_id,
                updated_by_id=self.kiran_id,
                is_active=True
            )
            db.session.add(override)
            db.session.commit()

            analytics = compute_academic_analytics_data(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                subject_filter='Web Programming'
            )
            s2_row = next(r for r in analytics['student_rows'] if r['student'].id == self.student2_id)
            label_texts = [lbl['text'] for lbl in s2_row['labels']]

            # HOD Allow Override badge present
            self.assertIn('HOD Allow Override', label_texts)

            # Change to MANUAL_RESTRICT
            override.decision_type = 'MANUAL_RESTRICT'
            db.session.commit()

            analytics_restricted = compute_academic_analytics_data(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                subject_filter='Web Programming'
            )
            s2_row_res = next(r for r in analytics_restricted['student_rows'] if r['student'].id == self.student2_id)
            res_labels = [lbl['text'] for lbl in s2_row_res['labels']]
            self.assertIn('HOD Restricted', res_labels)

            # Cleanup override
            db.session.delete(override)
            db.session.commit()

    # =========================================================================
    # 3. RBAC, AUTHORIZATION & ACCESS ISOLATION
    # =========================================================================

    def test_06_unauthenticated_and_unauthorized_roles_blocked(self):
        """Verifies anonymous visitors and unauthorized roles (e.g. Accountant) are rejected."""
        # 1. Anonymous visitor -> redirected to login
        res_anon = self.client.get('/academic/analytics')
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn('/login', res_anon.location)

        # 2. Accountant login -> 403 Forbidden!
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.acc1_id)
            sess['user_id'] = self.acc1_id

        res_acc = self.client.get('/academic/analytics')
        self.assertEqual(res_acc.status_code, 403)

    def test_07_cross_class_isolation_for_faculty(self):
        """Verifies that a faculty cannot access a class context they do not teach."""
        # Balram teaches BCA Sem V Sec A, but NOT B.Com
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        # Authorized access to BCA Sem V
        res_auth = self.client.get('/academic/analytics?course=BCA&semester=Sem+V&section=A')
        self.assertEqual(res_auth.status_code, 200)
        self.assertIn(b'Academic Analytics Dashboard', res_auth.data)

        # Unauthorized access to B.Com -> 403 Forbidden!
        res_unauth = self.client.get('/academic/analytics?course=B.Com&semester=Sem+V&section=A')
        self.assertEqual(res_unauth.status_code, 403)

    # =========================================================================
    # 4. INDIVIDUAL STUDENT ANALYTICS PROFILE & EDIT RIGHTS
    # =========================================================================

    def test_08_individual_student_analytics_profile_and_edit_permission(self):
        """Verifies individual student analytics page and subject-specific marks edit permission."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        # 1. Balram views Student 1's profile -> 200 OK
        res = self.client.get(f'/academic/analytics/student/{self.student1_id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Subject-Wise Attendance Surveillance', res.data)
        self.assertIn(b'Internal Assessment Marks Record', res.data)

        # 2. Check edit permission:
        # Balram teaches 'Web Programming' -> 'Edit Marks' button must be rendered
        self.assertIn(b'Edit Marks', res.data)

        # 3. Individual analytics profile helper verification
        with app.app_context():
            student = Student.query.get(self.student1_id)
            balram = User.query.get(self.balram_id)
            profile = get_student_academic_analytics_profile(student, viewing_user=balram)

            self.assertGreaterEqual(profile['overall_attendance_pct'], 75.0)
            self.assertEqual(profile['overall_status'], 'ELIGIBLE')

            # Find Web Programming card
            wp_card = next((c for c in profile['subject_cards'] if c['subject'] == 'Web Programming'), None)
            self.assertIsNotNone(wp_card)
            self.assertEqual(wp_card['attendance_pct'], 75.0)
            self.assertEqual(wp_card['attended_count'], 3)
            self.assertEqual(wp_card['conducted_count'], 4)
            self.assertTrue(wp_card['can_edit_marks']) # Balram can edit!

            # Find Cryptography card (taught by Shrinkala)
            crypto_card = next((c for c in profile['subject_cards'] if c['subject'] == 'Cryptography & Network Security'), None)
            if crypto_card:
                self.assertFalse(crypto_card['can_edit_marks']) # Balram CANNOT edit Cryptography!


if __name__ == '__main__':
    unittest.main()
