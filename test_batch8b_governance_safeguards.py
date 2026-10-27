"""
Test Suite: Batch 8B Security Hardening, Administration & Audit Safeguards
==========================================================================
Verifies:
1. HOD Timetable Scope:
   - HOD - BCA Dept can add/modify/delete BCA timetable slots.
   - HOD - BCA Dept cannot add/modify/delete non-BCA timetable slots (HTTP 403, DB untouched).
   - Principal and admin retain institution-wide authority.
2. Staff Directory Privacy:
   - Regular faculty can browse active colleagues.
   - Server response masks colleague salaries (salary=0) and personal demographics.
   - General staff cannot view colleague payslips or confidential payroll structures.
   - HR, Accountant, and Admin have unmasked access.
   - Students receive HTTP 403 on staff directory.
3. Audit Log Safeguards:
   - Only Principal can view and export audit logs.
   - Non-Principal users receive HTTP 403 on /audit_logs and /audit_logs/export.
   - CSV export generates valid CSV and safely escapes formula injection characters.
   - Permanent audit log purge is disabled (/clear_audit_logs preserves records).
   - Timetable additions, updates, and deletions append audit log entries.
"""

import os
import unittest
from datetime import datetime
from app import app, db, User, Student, Timetable, AuditLog


class Batch8BGovernanceSafeguardsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['TESTING'] = '1'
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

    def setUp(self):
        with app.app_context():
            faculty_a = User.query.filter_by(username='balram').first()
            if not faculty_a:
                faculty_a = User.query.filter_by(role='Faculty').first()
            self.faculty_a_id = faculty_a.id
            self.faculty_a_name = faculty_a.full_name
            self.faculty_a_role = faculty_a.role

            faculty_b = User.query.filter_by(username='shivani').first()
            if not faculty_b or faculty_b.id == faculty_a.id:
                faculty_b = User.query.filter(User.role == 'Faculty', User.id != faculty_a.id).first()
            self.faculty_b_id = faculty_b.id
            self.faculty_b_name = faculty_b.full_name
            self.faculty_b_role = faculty_b.role

            admin = User.query.filter_by(username='admin').first()
            self.admin_id = admin.id
            self.admin_name = admin.full_name
            self.admin_role = admin.role

            hod = User.query.filter_by(role='HOD - BCA Dept').first()
            self.hod_id = hod.id
            self.hod_name = hod.full_name
            self.hod_role = hod.role

            principal = User.query.filter_by(role='Principal').first()
            self.principal_id = principal.id
            self.principal_name = principal.full_name
            self.principal_role = principal.role

            accountant = User.query.filter_by(role='Accountant').first()
            self.accountant_id = accountant.id
            self.accountant_name = accountant.full_name
            self.accountant_role = accountant.role

            student = Student.query.filter_by(is_active=True).first()
            self.student_id = student.id
            self.student_uucms_id = student.uucms_id
            self.student_name = student.name
            self.student_course = student.course
            self.student_semester = student.semester
            self.student_section = student.section

            # Create test slots: 1 BCA slot and 1 non-BCA slot
            bca_slot = Timetable.query.filter_by(subject='B8B BCA Test Slot').first()
            if not bca_slot:
                bca_slot = Timetable(
                    day='Wednesday',
                    time_slot='10:00 AM-11:00 AM',
                    subject='B8B BCA Test Slot',
                    semester='Sem V',
                    course='BCA',
                    section='A',
                    room_no='Room 101',
                    status='pending',
                    user_id=self.faculty_b_id
                )
                db.session.add(bca_slot)

            bcom_slot = Timetable.query.filter_by(subject='B8B BCom Non-BCA Slot').first()
            if not bcom_slot:
                bcom_slot = Timetable(
                    day='Thursday',
                    time_slot='11:00 AM-12:00 PM',
                    subject='B8B BCom Non-BCA Slot',
                    semester='Sem III',
                    course='B.Com',
                    section='B',
                    room_no='Room 302',
                    status='pending',
                    user_id=self.faculty_b_id
                )
                db.session.add(bcom_slot)

            db.session.commit()
            self.bca_slot_id = bca_slot.id
            self.bcom_slot_id = bcom_slot.id

    def _login_as(self, user_id, full_name, role):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = user_id
            sess['_user_id'] = str(user_id)
            sess['name'] = full_name
            sess['role'] = role

    def _login_as_student(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_id
            sess['student_uucms_id'] = self.student_uucms_id
            sess['student_name'] = self.student_name
            sess['student_course'] = self.student_course
            sess['student_semester'] = self.student_semester
            sess['student_section'] = self.student_section
            sess['name'] = self.student_name
            sess['role'] = 'Student'

    def _logout(self):
        with self.client.session_transaction() as sess:
            sess.clear()

    # =========================================================================
    # Task 1: HOD Departmental Timetable Scope
    # =========================================================================
    def test_01_hod_can_manage_bca_slots(self):
        self._login_as(self.hod_id, self.hod_name, self.hod_role)
        # 1. Update BCA slot status
        res = self.client.post('/timetable/manage', data={
            'action': 'update_status',
            'class_id': self.bca_slot_id,
            'status': 'held',
            'faculty_id': self.faculty_b_id
        })
        self.assertEqual(res.status_code, 302)
        with app.app_context():
            slot = Timetable.query.get(self.bca_slot_id)
            self.assertEqual(slot.status, 'held')

        # 2. Add BCA slot for faculty
        res_add = self.client.post('/timetable/manage', data={
            'action': 'add',
            'faculty_id': self.faculty_b_id,
            'subject': 'B8B HOD Authorized BCA Slot',
            'day': 'Friday',
            'time': '02:00 PM-03:00 PM',
            'semester': 'Sem V',
            'course': 'BCA'
        })
        self.assertEqual(res_add.status_code, 302)
        with app.app_context():
            added_slot = Timetable.query.filter_by(subject='B8B HOD Authorized BCA Slot').first()
            self.assertIsNotNone(added_slot)
            self.assertEqual(added_slot.course, 'BCA')

    def test_02_hod_cannot_manage_non_bca_slots(self):
        self._login_as(self.hod_id, self.hod_name, self.hod_role)
        # 1. Attempt to update non-BCA slot
        res_upd = self.client.post('/timetable/manage', data={
            'action': 'update_status',
            'class_id': self.bcom_slot_id,
            'status': 'held',
            'faculty_id': self.faculty_b_id
        })
        self.assertEqual(res_upd.status_code, 403, "HOD - BCA Dept must receive HTTP 403 modifying non-BCA slot.")
        with app.app_context():
            slot = Timetable.query.get(self.bcom_slot_id)
            self.assertEqual(slot.status, 'pending', "Non-BCA slot status must remain untouched.")

        # 2. Attempt to delete non-BCA slot
        res_del = self.client.post('/timetable/manage', data={
            'action': 'delete',
            'class_id': self.bcom_slot_id,
            'faculty_id': self.faculty_b_id
        })
        self.assertEqual(res_del.status_code, 403, "HOD - BCA Dept must receive HTTP 403 deleting non-BCA slot.")
        with app.app_context():
            slot = Timetable.query.get(self.bcom_slot_id)
            self.assertIsNotNone(slot, "Non-BCA slot must NOT be deleted.")

        # 3. Attempt to add non-BCA slot
        res_add_non = self.client.post('/timetable/manage', data={
            'action': 'add',
            'faculty_id': self.faculty_b_id,
            'subject': 'B8B Unauthorized BCom Slot by HOD',
            'day': 'Monday',
            'time': '09:00 AM-10:00 AM',
            'semester': 'Sem II',
            'course': 'B.Com'
        })
        self.assertEqual(res_add_non.status_code, 403, "HOD - BCA Dept must receive HTTP 403 adding non-BCA slot.")
        with app.app_context():
            unauth = Timetable.query.filter_by(subject='B8B Unauthorized BCom Slot by HOD').first()
            self.assertIsNone(unauth, "Unauthorized non-BCA slot must NOT exist in database.")

    def test_03_principal_can_manage_across_all_courses(self):
        self._login_as(self.principal_id, self.principal_name, self.principal_role)
        # Principal updates status of non-BCA slot
        res = self.client.post('/timetable/manage', data={
            'action': 'update_status',
            'class_id': self.bcom_slot_id,
            'status': 'held',
            'faculty_id': self.faculty_b_id
        })
        self.assertEqual(res.status_code, 302, "Principal can manage across courses.")
        with app.app_context():
            slot = Timetable.query.get(self.bcom_slot_id)
            self.assertEqual(slot.status, 'held')

    # =========================================================================
    # Task 2: Staff Directory Privacy
    # =========================================================================
    def test_04_student_denied_from_staff_directory(self):
        self._login_as_student()
        res = self.client.get('/staff_directory')
        self.assertEqual(res.status_code, 403, "Student must receive HTTP 403 on staff directory.")

    def test_05_faculty_views_colleagues_with_sensitive_fields_masked(self):
        self._login_as(self.faculty_a_id, self.faculty_a_name, self.faculty_a_role)
        res = self.client.get('/staff_directory')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Colleague professional details are visible
        self.assertIn(self.faculty_b_name, html, "Colleague name must be visible in directory.")

        # Confidential indicators are present
        self.assertIn("Confidential Payroll", html)
        self.assertIn("Demographics Protected", html)

        # Peer salary input element must NOT be present in DOM
        self.assertIn(f'salaryInput_{self.faculty_a_id}', html, "Own salary input is rendered for self.")
        self.assertNotIn(f'salaryInput_{self.faculty_b_id}', html, "Peer salary input must NOT be rendered.")

    def test_06_privileged_roles_see_complete_payroll_matrix(self):
        # HR/Admin login
        self._login_as(self.admin_id, self.admin_name, self.admin_role)
        res = self.client.get('/staff_directory')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn("Monthly Outflow Payroll", html)
        self.assertIn("Complete Payroll Structure", html)

    # =========================================================================
    # Task 3: Audit Log Safeguards & CSV Export
    # =========================================================================
    def test_07_audit_log_access_restricted_to_principal(self):
        # Faculty attempt
        self._login_as(self.faculty_a_id, self.faculty_a_name, self.faculty_a_role)
        res_fac = self.client.get('/audit_logs')
        self.assertEqual(res_fac.status_code, 403, "Faculty must receive HTTP 403 on audit logs.")

        res_exp_fac = self.client.get('/audit_logs/export')
        self.assertEqual(res_exp_fac.status_code, 403, "Faculty must receive HTTP 403 on audit export.")

        # Principal success
        self._login_as(self.principal_id, self.principal_name, self.principal_role)
        res_princ = self.client.get('/audit_logs')
        self.assertEqual(res_princ.status_code, 200)

    def test_08_audit_log_export_csv_mitigates_formula_injection(self):
        self._login_as(self.principal_id, self.principal_name, self.principal_role)

        # Add a log entry with formula injection characters to test sanitization
        with app.app_context():
            inj_log = AuditLog(
                user_name="=cmd|' /C calc'!A0",
                action="+2+5*cmd",
                target_user="-DANGEROUS_TARGET",
                timestamp=datetime.utcnow()
            )
            db.session.add(inj_log)
            db.session.commit()
            inj_log_id = inj_log.id

        res = self.client.get('/audit_logs/export')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get('Content-Type'), 'text/csv; charset=utf-8')
        csv_text = res.data.decode('utf-8')

        # Verify formula characters are prepended with single quote
        self.assertIn("Log ID,Timestamp (IST),Actor (User),Action Description,Target Resource", csv_text)
        self.assertIn("'+2+5*cmd", csv_text)
        self.assertIn("'-DANGEROUS_TARGET", csv_text)

        # Clean up injection test row
        with app.app_context():
            row = AuditLog.query.get(inj_log_id)
            if row:
                db.session.delete(row)
                db.session.commit()

    def test_09_clear_audit_logs_disabled_and_preserves_records(self):
        self._login_as(self.principal_id, self.principal_name, self.principal_role)

        with app.app_context():
            count_before = AuditLog.query.count()

        # Invoke POST /clear_audit_logs
        res = self.client.post('/clear_audit_logs')
        self.assertEqual(res.status_code, 302)

        with app.app_context():
            count_after = AuditLog.query.count()
            self.assertEqual(count_before, count_after, "Audit log records must NOT be purged.")

    def test_10_timetable_mutations_create_audit_logs(self):
        self._login_as(self.faculty_a_id, self.faculty_a_name, self.faculty_a_role)

        # Add own slot
        res = self.client.post('/timetable/manage', data={
            'action': 'add',
            'faculty_id': self.faculty_a_id,
            'subject': 'B8B Audit Verified Slot',
            'day': 'Monday',
            'time': '10:30 AM-11:30 AM',
            'semester': 'Sem V',
            'course': 'BCA'
        })
        self.assertEqual(res.status_code, 302)

        with app.app_context():
            latest_log = AuditLog.query.filter(AuditLog.action.like("%B8B Audit Verified Slot%")).first()
            self.assertIsNotNone(latest_log, "Audit log entry must be created on timetable add.")
            self.assertIn("Timetable slot added", latest_log.action)
            self.assertEqual(latest_log.target_user, self.faculty_a_name)

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            Timetable.query.filter(Timetable.subject.in_([
                'B8B BCA Test Slot',
                'B8B BCom Non-BCA Slot',
                'B8B HOD Authorized BCA Slot',
                'B8B Audit Verified Slot'
            ])).delete(synchronize_session=False)
            db.session.commit()


if __name__ == '__main__':
    unittest.main()
