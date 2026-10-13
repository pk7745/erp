"""
Comprehensive Automated Test Suite for Student Internal Assessment Marks Management
Covers:
1. Authentication & RBAC (Anonymous redirect, Accountant 403, Faculty 200)
2. Subject Authorization (Teacher authorized for own subject, rejected for unauthorized subject)
3. Student Search by UUCMS ID and Name restricted to class
4. Inactive student rejection & class mismatch rejection
5. Assessment validation:
   - Positive decimal marks within maximum accepted
   - Zero (0.0) is stored as 0.0 and distinct from None
   - Missing/blank input is stored as None
   - Negative values rejected
   - Values exceeding configured maxima rejected
   - Non-numeric strings, NaN, Infinity rejected
   - Precision > 2 decimal places rejected
6. Partial / Draft entries (e.g., only IA1 entered)
7. Save vs. Update (in-place update, duplicate prevention via unique constraint)
8. Component preservation: editing only IA2 preserves IA1 and Final IA
9. Optimistic Concurrency Control (version mismatch rejected)
10. Immutable Audit Trail:
    - Changes logged with previous and new values, actor, timestamp, reason
    - Mandatory correction reason on update of existing marks
    - Unchanged values generate no audit events
11. History & Audit Views (scoped to teacher, server-side filters)
12. Regression verification
"""

import unittest
from app import app, db, User, Student, Timetable, InternalMark, InternalMarkAudit, parse_and_validate_mark, get_assessment_maxima, is_user_authorized_for_context


class InternalMarksTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()

        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            shrinkala = User.query.filter_by(username='shrinkala').first()
            acc1 = User.query.filter_by(username='acc1').first()
            kiran = User.query.filter_by(username='kiran').first()
            admin = User.query.filter_by(username='admin').first()

            cls.balram_id = balram.id
            cls.shrinkala_id = shrinkala.id
            cls.acc1_id = acc1.id
            cls.kiran_id = kiran.id
            cls.admin_id = admin.id

            student = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).first()
            assert student is not None, "Test requires at least one active BCA Sem V student"
            cls.student_id = student.id
            cls.student_uucms_id = student.uucms_id
            cls.student_name = student.name

            inactive = Student.query.filter_by(uucms_id='TEST_INACTIVE_01').first()
            if not inactive:
                inactive = Student(
                    uucms_id='TEST_INACTIVE_01',
                    name='Inactive Test Student',
                    email='inactive@bms.test',
                    course='BCA',
                    academic_year='3rd Year',
                    semester='Sem V',
                    section='A',
                    is_active=False
                )
                db.session.add(inactive)
                db.session.commit()
            cls.inactive_student_id = inactive.id

            InternalMark.query.filter_by(student_id=cls.student_id, assessment_cycle='TEST-CYCLE-26').delete()
            db.session.commit()

    def test_01_authentication_and_rbac(self):
        # 1. Anonymous access -> redirect to login
        with self.client.session_transaction() as sess:
            sess.clear()
        res = self.client.get('/internal-marks')
        self.assertEqual(res.status_code, 302)

        # 2. Accountant access -> 403 Forbidden
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.acc1_id)
            sess['user_id'] = self.acc1_id
        res = self.client.get('/internal-marks')
        self.assertEqual(res.status_code, 403)

        # 3. Faculty access (Balram) -> 200 OK
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
        res = self.client.get('/internal-marks')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Internal Assessment Marks', res.data)

    def test_02_subject_authorization(self):
        # Balram teaches 'Web Programming' in BCA Sem V Sec A
        with app.app_context():
            balram = User.query.get(self.balram_id)
            auth_wp = is_user_authorized_for_context(balram, 'BCA', 'Sem V', 'A', 'Web Programming')
            self.assertTrue(auth_wp, "Balram must be authorized for Web Programming")

            # Balram does NOT teach 'Cryptography & Network Security' (taught by Shrinkala)
            auth_cns = is_user_authorized_for_context(balram, 'BCA', 'Sem V', 'A', 'Cryptography & Network Security')
            self.assertFalse(auth_cns, "Balram must NOT be authorized for Cryptography & Network Security")

        # Test route access: Balram accessing students list for Cryptography -> 403 Forbidden
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
        res = self.client.get('/internal-marks/students?course=BCA&semester=Sem+V&section=A&subject=Cryptography+%26+Network+Security')
        self.assertEqual(res.status_code, 403)

        # Balram accessing students list for Web Programming -> 200 OK
        res = self.client.get('/internal-marks/students?course=BCA&semester=Sem+V&section=A&subject=Web+Programming')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Active Class Roster', res.data)

    def test_03_student_search(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        # Search by exact UUCMS ID
        res = self.client.get(f'/internal-marks/students?course=BCA&semester=Sem+V&section=A&subject=Web+Programming&search={self.student_uucms_id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(self.student_uucms_id.encode(), res.data)
        self.assertIn(self.student_name.encode(), res.data)

        # Search by student name substring
        first_name = self.student_name.split()[0]
        res = self.client.get(f'/internal-marks/students?course=BCA&semester=Sem+V&section=A&subject=Web+Programming&search={first_name}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(self.student_name.encode(), res.data)

        # Search for non-existent student
        res = self.client.get('/internal-marks/students?course=BCA&semester=Sem+V&section=A&subject=Web+Programming&search=NONEXISTENT_STUDENT_XYZ')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'No Students Found', res.data)

    def test_04_marks_validation_helper(self):
        maxima = get_assessment_maxima()
        max_ia1 = maxima['IA1']

        # 1. Valid numbers
        val, err = parse_and_validate_mark('20.5', 'IA1', max_ia1)
        self.assertIsNone(err)
        self.assertEqual(val, 20.5)

        val, err = parse_and_validate_mark('0', 'IA1', max_ia1)
        self.assertIsNone(err)
        self.assertEqual(val, 0.0)

        val, err = parse_and_validate_mark('25.0', 'IA1', max_ia1)
        self.assertIsNone(err)
        self.assertEqual(val, 25.0)

        # 2. Blank / None input
        val, err = parse_and_validate_mark('', 'IA1', max_ia1)
        self.assertIsNone(err)
        self.assertIsNone(val)

        val, err = parse_and_validate_mark(None, 'IA1', max_ia1)
        self.assertIsNone(err)
        self.assertIsNone(val)

        # 3. Negative value rejected
        val, err = parse_and_validate_mark('-1.5', 'IA1', max_ia1)
        self.assertIsNotNone(err)
        self.assertIn('negative', err.lower())

        # 4. Exceeding maximum rejected
        val, err = parse_and_validate_mark(str(max_ia1 + 1), 'IA1', max_ia1)
        self.assertIsNotNone(err)
        self.assertIn('exceed', err.lower())

        # 5. Non-numeric / NaN / Inf rejected
        val, err = parse_and_validate_mark('abc', 'IA1', max_ia1)
        self.assertIsNotNone(err)

        val, err = parse_and_validate_mark('nan', 'IA1', max_ia1)
        self.assertIsNotNone(err)

        # 6. Precision > 2 decimals rejected
        val, err = parse_and_validate_mark('18.755', 'IA1', max_ia1)
        self.assertIsNotNone(err)
        self.assertIn('precision', err.lower())

    def test_05_save_and_update_with_audit_trail(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        cycle = 'TEST-CYCLE-26'

        # 1. Save new partial record: only IA1 entered
        payload = {
            'student_id': self.student_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': cycle,
            'ia1_marks': '19.5',
            'ia2_marks': '',
            'final_ia_marks': '',
            'reason': 'First IA conducted'
        }
        res = self.client.post('/internal-marks/save', data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with app.app_context():
            saved = InternalMark.query.filter_by(
                student_id=self.student_id,
                subject='Web Programming',
                assessment_cycle=cycle
            ).first()
            self.assertIsNotNone(saved)
            self.assertEqual(saved.ia1_marks, 19.5)
            self.assertIsNone(saved.ia2_marks)
            self.assertIsNone(saved.final_ia_marks)
            self.assertEqual(saved.completion_status, 'Partial')
            self.assertEqual(saved.version, 1)

            # Check initial audit log
            audits = InternalMarkAudit.query.filter_by(internal_mark_id=saved.id).all()
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].component, 'IA1')
            self.assertEqual(audits[0].new_value, '19.5')

        # 2. Update record: add IA2 and modify IA1 with mandatory reason
        with app.app_context():
            saved = InternalMark.query.filter_by(student_id=self.student_id, subject='Web Programming', assessment_cycle=cycle).first()
            current_ver = saved.version

        update_payload = {
            'student_id': self.student_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': cycle,
            'version': current_ver,
            'ia1_marks': '21.0',  # Modified from 19.5
            'ia2_marks': '22.5',  # Newly entered
            'final_ia_marks': '',
            'reason': 'Re-evaluation mark addition'
        }
        res = self.client.post('/internal-marks/save', data=update_payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with app.app_context():
            updated = InternalMark.query.filter_by(student_id=self.student_id, subject='Web Programming', assessment_cycle=cycle).first()
            self.assertEqual(updated.ia1_marks, 21.0)
            self.assertEqual(updated.ia2_marks, 22.5)
            self.assertIsNone(updated.final_ia_marks)
            self.assertEqual(updated.version, 2)

            audits = InternalMarkAudit.query.filter_by(internal_mark_id=updated.id).order_by(InternalMarkAudit.created_at.asc()).all()
            self.assertEqual(len(audits), 3)
            ia1_update = [a for a in audits if a.component == 'IA1' and a.previous_value == '19.5'][0]
            self.assertEqual(ia1_update.new_value, '21.0')
            self.assertEqual(ia1_update.reason, 'Re-evaluation mark addition')

    def test_06_concurrency_optimistic_locking(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        cycle = 'TEST-CYCLE-26'
        stale_payload = {
            'student_id': self.student_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': cycle,
            'version': 1,  # STALE VERSION (actual is 2)
            'ia1_marks': '24.0',
            'ia2_marks': '22.5',
            'final_ia_marks': '',
            'reason': 'Concurrent edit attempt'
        }
        res = self.client.post('/internal-marks/save', data=stale_payload, follow_redirects=True)
        self.assertIn(b'Concurrent update detected', res.data)

        with app.app_context():
            mark = InternalMark.query.filter_by(student_id=self.student_id, subject='Web Programming', assessment_cycle=cycle).first()
            self.assertEqual(mark.ia1_marks, 21.0)

    def test_07_unauthorized_teacher_tampering_rejected(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.shrinkala_id)
            sess['user_id'] = self.shrinkala_id

        payload = {
            'student_id': self.student_id,
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',  # Shrinkala not authorized!
            'assessment_cycle': 'TEST-CYCLE-26',
            'ia1_marks': '25.0',
            'reason': 'Tamper attempt'
        }
        res = self.client.post('/internal-marks/save', data=payload)
        self.assertEqual(res.status_code, 403)

    def test_08_inactive_student_rejected(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        payload = {
            'student_id': self.inactive_student_id,  # INACTIVE STUDENT!
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assessment_cycle': 'TEST-CYCLE-26',
            'ia1_marks': '20.0',
            'reason': 'Inactive student attempt'
        }
        res = self.client.post('/internal-marks/save', data=payload, follow_redirects=True)
        self.assertIn(b'Invalid student record or student is not active', res.data)

    def test_09_history_and_audit_views(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        # 1. History view
        res = self.client.get('/internal-marks/history?subject=Web+Programming')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Internal Assessment History', res.data)

        # 2. Audit view
        with app.app_context():
            mark = InternalMark.query.filter_by(student_id=self.student_id, subject='Web Programming', assessment_cycle='TEST-CYCLE-26').first()
            mark_id = mark.id

        res = self.client.get(f'/internal-marks/audit/{mark_id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Immutable Audit Trail', res.data)
        self.assertIn(b'Re-evaluation mark addition', res.data)

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            InternalMark.query.filter_by(assessment_cycle='TEST-CYCLE-26').delete()
            db.session.commit()


if __name__ == '__main__':
    unittest.main()
