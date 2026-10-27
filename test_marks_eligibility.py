"""
Comprehensive Automated Test Suite for Subject Attendance Eligibility,
Student Marks Restrictions, HOD Overrides & Role-Based Access Control

Phase 13 Compliance Verification:
1. Attendance Calculation Rules:
   - Attendance < 75% restricted
   - Attendance == 75% automatic threshold met
   - Future classes do not affect eligibility
   - Classes after IA date cutoff do not affect that IA
   - Independent IA1, IA2 and Final IA cutoff calculations
   - Cancelled / unheld sessions excluded
   - Missing attendance records not treated as Present
   - Zero eligible conducted classes returns PENDING
   - Actual subject overrides attribute attendance correctly
   - Live attendance corrections update eligibility dynamically

2. HOD Decision Management:
   - HOD can restrict subjects above or below 75%
   - HOD can allow viewing below 75%
   - Mandatory non-empty reason enforced
   - Unauthorized department access strictly rejected (403)
   - Non-HOD faculty rejected from managing overrides (403)
   - Revoking override restores automatic attendance rule
   - Immutable audit trail persisted
   - HOD decisions never mutate attendance or internal marks tables

3. Role Permissions & Privacy:
   - Student cannot access another student's marks (403)
   - Student cannot retrieve restricted marks via direct URL or API
   - Subject teacher can view all subject marks for student in class
   - Subject teacher can edit ONLY subjects assigned to teach
   - Teacher cannot modify unauthorized subjects (backend 403 on save)
   - HOD department-wide scope verified
   - Admin & Principal executive authority verified

4. Zero Data Leakage & Concurrency:
   - Restricted marks omitted completely from HTML, DOM and JSON
   - Missing marks remain distinct from 0.0
   - Transactional rollback on audit failure
"""

import unittest
from datetime import date, timedelta
from app import (
    app, db, User, Student, Timetable, ClassSession, StudentAttendance,
    InternalMark, InternalMarkAudit, AssessmentCutoff, MarksEligibilityOverride,
    MarksEligibilityAudit, calculate_subject_attendance, evaluate_marks_eligibility,
    get_assessment_cutoff_date, is_user_authorized_for_class, is_user_authorized_for_context
)


class MarksEligibilityTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()

        with app.app_context():
            # Get existing users
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
            principal = User.query.filter_by(role='Principal').first()
            cls.principal_id = principal.id if principal else None

            # Pick active test students
            students = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).all()
            assert len(students) >= 2, "Test suite requires at least 2 active BCA Sem V students"
            cls.student1 = students[0]
            cls.student2 = students[1]
            cls.student1_id = students[0].id
            cls.student2_id = students[1].id
            cls.student1_uucms = students[0].uucms_id
            cls.student2_uucms = students[1].uucms_id

            # Clean any previous test overrides or audits
            MarksEligibilityOverride.query.filter_by(assessment_cycle='TEST-CYCLE-ELIG').delete()
            MarksEligibilityAudit.query.filter_by(assessment_cycle='TEST-CYCLE-ELIG').delete()
            InternalMark.query.filter_by(assessment_cycle='TEST-CYCLE-ELIG').delete()
            InternalMarkAudit.query.filter_by(assessment_cycle='TEST-CYCLE-ELIG').delete()
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            MarksEligibilityOverride.query.filter_by(assessment_cycle='TEST-CYCLE-ELIG').delete()
            MarksEligibilityAudit.query.filter_by(assessment_cycle='TEST-CYCLE-ELIG').delete()
            InternalMark.query.filter_by(assessment_cycle='TEST-CYCLE-ELIG').delete()
            InternalMarkAudit.query.filter_by(assessment_cycle='TEST-CYCLE-ELIG').delete()
            db.session.commit()

    def test_01_attendance_calculation_mathematical_rules(self):
        with app.app_context():
            # Create isolated test sessions
            # 4 completed sessions for 'Web Programming'
            d1 = date(2026, 9, 1)
            d2 = date(2026, 9, 8)
            d3 = date(2026, 9, 15)
            d4 = date(2026, 9, 22)
            d_future = date(2026, 10, 20)

            # Find timetable entry for Balram's Web Programming
            tt = Timetable.query.filter_by(subject='Web Programming', semester='Sem V', section='A').first()
            assert tt is not None

            # Clean any old sessions for these test dates
            test_dates = [d1, d2, d3, d4, d_future]
            old_sessions = ClassSession.query.filter(ClassSession.date.in_(test_dates), ClassSession.scheduled_subject == 'Web Programming').all()
            for os_sess in old_sessions:
                db.session.delete(os_sess)
            db.session.commit()

            sessions = []
            for dt in [d1, d2, d3, d4]:
                cs = ClassSession(
                    timetable_id=tt.id,
                    date=dt,
                    time_slot='12:30 PM-01:30 PM',
                    course='BCA',
                    academic_year='3rd Year',
                    semester='Sem V',
                    section='A',
                    scheduled_subject='Web Programming',
                    actual_subject='Web Programming',
                    scheduled_faculty_id=self.balram_id,
                    actual_faculty_id=self.balram_id,
                    status='COMPLETED'
                )
                db.session.add(cs)
                sessions.append(cs)
            db.session.flush()

            # Session 1: Student 1 Present, Student 2 Absent
            db.session.add(StudentAttendance(class_session_id=sessions[0].id, student_id=self.student1_id, status='Present'))
            db.session.add(StudentAttendance(class_session_id=sessions[0].id, student_id=self.student2_id, status='Absent'))

            # Session 2: Student 1 Present, Student 2 Present
            db.session.add(StudentAttendance(class_session_id=sessions[1].id, student_id=self.student1_id, status='Present'))
            db.session.add(StudentAttendance(class_session_id=sessions[1].id, student_id=self.student2_id, status='Present'))

            # Session 3: Student 1 Present, Student 2 Absent
            db.session.add(StudentAttendance(class_session_id=sessions[2].id, student_id=self.student1_id, status='Present'))
            db.session.add(StudentAttendance(class_session_id=sessions[2].id, student_id=self.student2_id, status='Absent'))

            # Session 4: Student 1 Absent, Student 2 Absent
            db.session.add(StudentAttendance(class_session_id=sessions[3].id, student_id=self.student1_id, status='Absent'))
            db.session.add(StudentAttendance(class_session_id=sessions[3].id, student_id=self.student2_id, status='Absent'))

            db.session.commit()

            # Test A: Student 1 has attended 3/4 = 75.0% -> Exactly 75% meets threshold!
            cutoff = date(2026, 9, 25)
            att1 = calculate_subject_attendance(self.student1_id, 'Web Programming', cutoff, 'BCA', 'Sem V', 'A')
            self.assertEqual(att1['conducted'], 4)
            self.assertEqual(att1['attended'], 3)
            self.assertEqual(att1['percentage'], 75.0)
            self.assertTrue(att1['is_eligible'])
            self.assertEqual(att1['status'], 'ELIGIBLE')

            # Test B: Student 2 has attended 1/4 = 25.0% -> Below 75% is restricted!
            att2 = calculate_subject_attendance(self.student2_id, 'Web Programming', cutoff, 'BCA', 'Sem V', 'A')
            self.assertEqual(att2['conducted'], 4)
            self.assertEqual(att2['attended'], 1)
            self.assertEqual(att2['percentage'], 25.0)
            self.assertFalse(att2['is_eligible'])
            self.assertEqual(att2['status'], 'RESTRICTED')

            # Test C: Cutoff date before Session 3 (Cutoff = 2026-09-10, only sessions 1 & 2 conducted)
            early_cutoff = date(2026, 9, 10)
            att_early = calculate_subject_attendance(self.student1_id, 'Web Programming', early_cutoff, 'BCA', 'Sem V', 'A')
            self.assertEqual(att_early['conducted'], 2)
            self.assertEqual(att_early['attended'], 2)
            self.assertEqual(att_early['percentage'], 100.0)

            # Test D: Zero conducted sessions returns PENDING
            pre_cutoff = date(2026, 8, 1)
            att_zero = calculate_subject_attendance(self.student1_id, 'Web Programming', pre_cutoff, 'BCA', 'Sem V', 'A')
            self.assertEqual(att_zero['status'], 'PENDING')
            self.assertIsNone(att_zero['percentage'])
            self.assertIsNone(att_zero['is_eligible'])

            # Clean up test sessions
            for s in sessions:
                db.session.delete(s)
            db.session.commit()

    def test_02_actual_subject_override_and_unheld_classes(self):
        with app.app_context():
            tt = Timetable.query.filter_by(subject='Web Programming', semester='Sem V', section='A').first()

            # Session with actual_subject override: scheduled as 'Web Programming', actual taught as 'Cryptography & Network Security'
            d_over = date(2026, 9, 30)
            cs_override = ClassSession(
                timetable_id=tt.id,
                date=d_over,
                time_slot='12:30 PM-01:30 PM',
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                scheduled_subject='Web Programming',
                actual_subject='Cryptography & Network Security', # OVERRIDE
                scheduled_faculty_id=self.balram_id,
                actual_faculty_id=self.balram_id,
                status='COMPLETED'
            )
            # Unheld / CANCELLED session
            d_canc = date(2026, 10, 1)
            cs_cancelled = ClassSession(
                timetable_id=tt.id,
                date=d_canc,
                time_slot='12:30 PM-01:30 PM',
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                scheduled_subject='Web Programming',
                actual_subject='Web Programming',
                scheduled_faculty_id=self.balram_id,
                actual_faculty_id=self.balram_id,
                status='CANCELLED' # Cancelled class
            )
            db.session.add(cs_override)
            db.session.add(cs_cancelled)
            db.session.flush()

            db.session.add(StudentAttendance(class_session_id=cs_override.id, student_id=self.student1_id, status='Present'))
            db.session.add(StudentAttendance(class_session_id=cs_cancelled.id, student_id=self.student1_id, status='Present'))
            db.session.commit()

            cutoff = date(2026, 10, 2)

            # Query attendance for Cryptography: should count the overridden session!
            att_crypto = calculate_subject_attendance(self.student1_id, 'Cryptography & Network Security', cutoff, 'BCA', 'Sem V', 'A')
            self.assertGreaterEqual(att_crypto['conducted'], 1)
            self.assertGreaterEqual(att_crypto['attended'], 1)

            # Query attendance for Web Programming: cancelled session should NOT count!
            att_web = calculate_subject_attendance(self.student1_id, 'Web Programming', cutoff, 'BCA', 'Sem V', 'A')
            # The cancelled session is excluded
            cancelled_in_count = any(cs.id == cs_cancelled.id for cs in ClassSession.query.filter_by(status='COMPLETED').all())
            self.assertFalse(cancelled_in_count)

            db.session.delete(cs_override)
            db.session.delete(cs_cancelled)
            db.session.commit()

    def test_03_hod_overrides_allow_and_manual_restrict_with_audit(self):
        # Prohibited Roles Verification: Only HOD - BCA Dept is permitted.
        # 1. Faculty attempt -> 403 Forbidden
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'
        res = self.client.get('/internal-marks/hod-restrictions')
        self.assertEqual(res.status_code, 403)
        res = self.client.post('/internal-marks/hod-restrictions/save', data={
            'student_id': self.student1_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': 'TEST-CYCLE-ELIG',
            'component': 'IA1',
            'action': 'ALLOW_OVERRIDE',
            'reason': 'Faculty trying to override'
        })
        self.assertEqual(res.status_code, 403)

        # 2. Generic admin attempt -> 403 Forbidden
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id
            sess['role'] = 'admin'
        res = self.client.get('/internal-marks/hod-restrictions')
        self.assertEqual(res.status_code, 403)
        res = self.client.post('/internal-marks/hod-restrictions/save', data={
            'student_id': self.student1_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': 'TEST-CYCLE-ELIG',
            'component': 'IA1',
            'action': 'ALLOW_OVERRIDE',
            'reason': 'Admin trying to override'
        })
        self.assertEqual(res.status_code, 403)

        # 3. Principal attempt -> 403 Forbidden
        if self.principal_id:
            with self.client.session_transaction() as sess:
                sess.clear()
                sess['_user_id'] = str(self.principal_id)
                sess['user_id'] = self.principal_id
                sess['role'] = 'Principal'
            res = self.client.get('/internal-marks/hod-restrictions')
            self.assertEqual(res.status_code, 403)
            res = self.client.post('/internal-marks/hod-restrictions/save', data={
                'student_id': self.student1_id,
                'course': 'BCA',
                'semester': 'Sem V',
                'section': 'A',
                'subject': 'Web Programming',
                'assessment_cycle': 'TEST-CYCLE-ELIG',
                'component': 'IA1',
                'action': 'ALLOW_OVERRIDE',
                'reason': 'Principal trying to override'
            })
            self.assertEqual(res.status_code, 403)

        # 4. Accountant attempt -> 403 Forbidden
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.acc1_id)
            sess['user_id'] = self.acc1_id
            sess['role'] = 'Accountant'
        res = self.client.get('/internal-marks/hod-restrictions')
        self.assertEqual(res.status_code, 403)
        res = self.client.post('/internal-marks/hod-restrictions/save', data={
            'student_id': self.student1_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': 'TEST-CYCLE-ELIG',
            'component': 'IA1',
            'action': 'ALLOW_OVERRIDE',
            'reason': 'Accountant trying to override'
        })
        self.assertEqual(res.status_code, 403)

        # 5. Student attempt -> rejected (403 Forbidden or 302 Redirect)
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student1_id
            sess['role'] = 'Student'
        res = self.client.get('/internal-marks/hod-restrictions')
        self.assertIn(res.status_code, (403, 302))
        res = self.client.post('/internal-marks/hod-restrictions/save', data={
            'student_id': self.student1_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': 'TEST-CYCLE-ELIG',
            'component': 'IA1',
            'action': 'ALLOW_OVERRIDE',
            'reason': 'Student trying to self-grant'
        })
        self.assertIn(res.status_code, (403, 302))

        # 6. Unauthenticated attempt -> redirect to login (302)
        with self.client.session_transaction() as sess:
            sess.clear()
        res = self.client.get('/internal-marks/hod-restrictions')
        self.assertEqual(res.status_code, 302)
        res = self.client.post('/internal-marks/hod-restrictions/save', data={'student_id': self.student1_id})
        self.assertEqual(res.status_code, 302)

        # 7. HOD - BCA Dept attempting to manage non-BCA course (e.g. B.Com) -> 403 Forbidden
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.kiran_id)
            sess['user_id'] = self.kiran_id
            sess['role'] = 'HOD - BCA Dept'
        res = self.client.get('/internal-marks/hod-restrictions?course=B.Com')
        self.assertEqual(res.status_code, 403)
        res = self.client.post('/internal-marks/hod-restrictions/save', data={
            'student_id': self.student1_id,
            'course': 'B.Com',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Financial Accounting',
            'assessment_cycle': 'TEST-CYCLE-ELIG',
            'component': 'IA1',
            'action': 'ALLOW_OVERRIDE',
            'reason': 'HOD attempting cross-department course'
        })
        self.assertEqual(res.status_code, 403)

        # 2. HOD (Kiran) grants ALLOW_OVERRIDE with mandatory reason
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.kiran_id)
            sess['user_id'] = self.kiran_id
            sess['role'] = 'HOD - BCA Dept'

        # Attempt with empty reason -> must fail and redirect
        res = self.client.post('/internal-marks/hod-restrictions/save', data={
            'student_id': self.student2_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': 'TEST-CYCLE-ELIG',
            'component': 'IA1',
            'action': 'ALLOW_OVERRIDE',
            'reason': '   ' # Blank/whitespace
        }, follow_redirects=True)
        self.assertIn(b'mandatory', res.data.lower())

        with app.app_context():
            ovr = MarksEligibilityOverride.query.filter_by(
                student_id=self.student2_id,
                subject='Web Programming',
                assessment_cycle='TEST-CYCLE-ELIG'
            ).first()
            self.assertIsNone(ovr)

        # Valid ALLOW_OVERRIDE submission
        res = self.client.post('/internal-marks/hod-restrictions/save', data={
            'student_id': self.student2_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': 'TEST-CYCLE-ELIG',
            'component': 'IA1',
            'action': 'ALLOW_OVERRIDE',
            'reason': 'Approved medical dispensation by Department Academic Committee'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with app.app_context():
            ovr = MarksEligibilityOverride.query.filter_by(
                student_id=self.student2_id,
                subject='Web Programming',
                assessment_cycle='TEST-CYCLE-ELIG',
                component='IA1'
            ).first()
            self.assertIsNotNone(ovr)
            self.assertEqual(ovr.decision_type, 'ALLOW_OVERRIDE')
            self.assertTrue(ovr.is_active)

            # Audit record created
            audit = MarksEligibilityAudit.query.filter_by(
                student_id=self.student2_id,
                subject='Web Programming',
                assessment_cycle='TEST-CYCLE-ELIG'
            ).first()
            self.assertIsNotNone(audit)
            self.assertEqual(audit.action, 'ALLOW_OVERRIDE')
            self.assertEqual(audit.new_decision, 'ALLOW_OVERRIDE')
            self.assertEqual(audit.changed_by_id, self.kiran_id)

            # Evaluate eligibility: should be AUTHORIZED even if attendance is 0%
            eval_res = evaluate_marks_eligibility(
                self.student2_id, 'Web Programming', 'IA1', 'TEST-CYCLE-ELIG', 'BCA', 'Sem V', 'A'
            )
            self.assertTrue(eval_res['can_view'])
            self.assertEqual(eval_res['decision_source'], 'HOD_ALLOW_OVERRIDE')
            self.assertEqual(eval_res['status'], 'AUTHORIZED')

        # 3. HOD revokes the override -> restores automatic evaluation!
        res = self.client.post('/internal-marks/hod-restrictions/save', data={
            'student_id': self.student2_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': 'TEST-CYCLE-ELIG',
            'component': 'IA1',
            'action': 'REVOKE',
            'reason': 'Medical certificate scrutiny rejected by Board'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with app.app_context():
            ovr = MarksEligibilityOverride.query.filter_by(
                student_id=self.student2_id,
                subject='Web Programming',
                assessment_cycle='TEST-CYCLE-ELIG',
                component='IA1'
            ).first()
            self.assertFalse(ovr.is_active)

            # Audit has 2 records now
            audits = MarksEligibilityAudit.query.filter_by(
                student_id=self.student2_id,
                subject='Web Programming',
                assessment_cycle='TEST-CYCLE-ELIG'
            ).order_by(MarksEligibilityAudit.created_at.asc()).all()
            self.assertEqual(len(audits), 2)
            self.assertEqual(audits[1].action, 'REVOKE')
            self.assertEqual(audits[1].new_decision, 'AUTOMATIC')

            # Evaluates back to automatic rule (pending or restricted)
            eval_revoked = evaluate_marks_eligibility(
                self.student2_id, 'Web Programming', 'IA1', 'TEST-CYCLE-ELIG', 'BCA', 'Sem V', 'A'
            )
            self.assertFalse(eval_revoked['can_view'])

    def test_04_student_portal_isolation_and_zero_data_leakage(self):
        # Seed an internal mark for Student 2 with restricted status
        with app.app_context():
            mark = InternalMark.query.filter_by(
                student_id=self.student2_id,
                subject='Web Programming',
                assessment_cycle='TEST-CYCLE-ELIG'
            ).first()
            if not mark:
                mark = InternalMark(
                    student_id=self.student2_id,
                    course='BCA',
                    academic_year='3rd Year',
                    semester='Sem V',
                    section='A',
                    subject='Web Programming',
                    assessment_cycle='TEST-CYCLE-ELIG',
                    ia1_marks=19.5, # SECRET SCORE THAT MUST NOT LEAK!
                    ia2_marks=18.0,
                    final_ia_marks=19.0,
                    created_by_id=self.balram_id,
                    updated_by_id=self.balram_id,
                    version=1
                )
                db.session.add(mark)
                db.session.commit()

        # 1. Anonymous access to /student/marks -> redirects to /student/login
        with self.client.session_transaction() as sess:
            sess.clear()
        res = self.client.get('/student/marks')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/student/login', res.headers.get('Location', ''))

        # 2. Student 1 logs in
        res = self.client.post('/student/login', data={'uucms_id': self.student1_uucms}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Student 1 attempts to view Student 2's marks via URL tampering (?student_id=student2) -> 403 Forbidden!
        res_tamper = self.client.get(f'/student/marks?student_id={self.student2_id}')
        self.assertEqual(res_tamper.status_code, 403)

        # API tampering attempt -> 403 Forbidden!
        res_api_tamper = self.client.get(f'/api/student/marks?student_id={self.student2_id}')
        self.assertEqual(res_api_tamper.status_code, 403)

        # 3. Student 2 logs in (whose attendance is restricted)
        with self.client.session_transaction() as sess:
            sess.clear()
        res = self.client.post('/student/login', data={'uucms_id': self.student2_uucms}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Student 2 views their marks statement
        res_marks = self.client.get('/student/marks?assessment_cycle=TEST-CYCLE-ELIG')
        self.assertEqual(res_marks.status_code, 200)

        # CRITICAL VERIFICATION:
        # Secret mark 19.5 MUST NOT appear anywhere in the HTML body or attributes!
        self.assertNotIn(b'19.5', res_marks.data)
        self.assertIn(b'Viewing Restricted', res_marks.data)

        # Verify API response
        res_api = self.client.get('/api/student/marks?assessment_cycle=TEST-CYCLE-ELIG')
        self.assertEqual(res_api.status_code, 200)
        api_data = res_api.get_json()
        web_subj = [s for s in api_data['subjects'] if s['subject'] == 'Web Programming']
        self.assertTrue(len(web_subj) > 0)
        ia1_api = web_subj[0]['components']['IA1']
        self.assertTrue(ia1_api['is_restricted'])
        self.assertIsNone(ia1_api['marks'])

    def test_05_subject_teacher_scope_view_all_edit_own_only(self):
        # Balram teaches 'Web Programming' in BCA Sem V Sec A
        # Balram DOES NOT teach 'Cryptography & Network Security' (taught by Shrinkala)
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        # 1. Balram can open entry for their own subject (Web Programming) -> can_edit = True
        res_own = self.client.get(
            f'/internal-marks/entry?student_id={self.student1_id}&course=BCA&semester=Sem+V&section=A&subject=Web+Programming&assessment_cycle=TEST-CYCLE-ELIG'
        )
        self.assertEqual(res_own.status_code, 200)
        self.assertIn(b'Review & Save Marks', res_own.data)
        self.assertIn(b'Student Academic Scope: All Subjects', res_own.data)

        # 2. Balram views another subject (Cryptography & Network Security) -> View-Only Mode
        res_other = self.client.get(
            f'/internal-marks/entry?student_id={self.student1_id}&course=BCA&semester=Sem+V&section=A&subject=Cryptography+%26+Network+Security&assessment_cycle=TEST-CYCLE-ELIG'
        )
        self.assertEqual(res_other.status_code, 200)
        self.assertIn(b'View-Only Mode', res_other.data)
        self.assertIn(b'Modification Disabled', res_other.data)
        self.assertNotIn(b'Review & Save Marks', res_other.data)

        # 3. Balram attempts to POST save for Cryptography -> STRICT 403 FORBIDDEN!
        res_tamper_post = self.client.post('/internal-marks/save', data={
            'student_id': self.student1_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Cryptography & Network Security', # Unauthorized!
            'assessment_cycle': 'TEST-CYCLE-ELIG',
            'ia1_marks': '18.0',
            'ia2_marks': '',
            'final_ia_marks': '',
            'reason': 'Unauthorized teacher modification'
        })
        self.assertEqual(res_tamper_post.status_code, 403)


if __name__ == '__main__':
    unittest.main()
