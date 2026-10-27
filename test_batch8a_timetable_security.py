"""
Test Suite: Batch 8A Timetable Authorization Security Hotfix
============================================================
Verifies:
1. Unauthenticated users cannot modify timetables (redirect to login/302).
2. Students and non-academic staff (e.g. Accountant) cannot modify timetable management (302/403).
3. Faculty A cannot delete Faculty B's timetable slot (HTTP 403; DB record unchanged).
4. Faculty A cannot update Faculty B's timetable slot details (HTTP 403; DB record unchanged).
5. Faculty A cannot update Faculty B's timetable slot status (HTTP 403; DB record unchanged).
6. Faculty A cannot add a timetable slot assigned to Faculty B (HTTP 403; DB record count unchanged).
7. Authorized faculty can add, update session, update status, and delete their own timetable slot.
8. Administrative roles (Principal, HOD - BCA Dept, admin) can manage timetable slots across faculty.
9. Malformed and nonexistent identifiers (non-integer class_id, missing action, unknown class_id) are handled safely.
10. Slots with recorded ClassSession attendance sessions cannot be deleted.
"""

import os
import unittest
from app import app, db, User, Student, Timetable, ClassSession


class Batch8ATimetableSecurityTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['TESTING'] = '1'
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

    def setUp(self):
        with app.app_context():
            # Identify faculty members
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

            # Identify admin, HOD, principal, accountant, student
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

            # Ensure Faculty B has an isolated timetable slot for testing
            test_slot_b = Timetable.query.filter_by(user_id=self.faculty_b_id, subject='Batch8A Target Subject').first()
            if not test_slot_b:
                test_slot_b = Timetable(
                    day='Tuesday',
                    time_slot='02:00 PM-03:00 PM',
                    subject='Batch8A Target Subject',
                    semester='Sem V',
                    course='BCA',
                    section='A',
                    room_no='Room 204',
                    status='pending',
                    user_id=self.faculty_b_id
                )
                db.session.add(test_slot_b)
                db.session.commit()
            self.test_slot_b_id = test_slot_b.id

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

    # -------------------------------------------------------------------------
    # 1. Unauthenticated & Unauthorized Non-Faculty Roles
    # -------------------------------------------------------------------------
    def test_01_unauthenticated_user_cannot_manage_timetable(self):
        self._logout()
        res = self.client.post('/timetable/manage', data={
            'action': 'delete',
            'class_id': self.test_slot_b_id
        })
        self.assertIn(res.status_code, [302, 401])
        with app.app_context():
            slot = Timetable.query.get(self.test_slot_b_id)
            self.assertIsNotNone(slot, "Record must NOT be deleted by unauthenticated caller.")

    def test_02_student_cannot_manage_timetable(self):
        self._login_as_student()
        res = self.client.post('/timetable/manage', data={
            'action': 'delete',
            'class_id': self.test_slot_b_id
        })
        self.assertIn(res.status_code, [302, 403], "Student must receive HTTP 302/403 on timetable management.")
        with app.app_context():
            slot = Timetable.query.get(self.test_slot_b_id)
            self.assertIsNotNone(slot, "Record must NOT be deleted by student.")

    def test_03_non_academic_staff_cannot_manage_timetable(self):
        self._login_as(self.accountant_id, self.accountant_name, self.accountant_role)
        res = self.client.post('/timetable/manage', data={
            'action': 'delete',
            'class_id': self.test_slot_b_id
        })
        self.assertEqual(res.status_code, 403, "Accountant must receive HTTP 403 on timetable management.")
        with app.app_context():
            slot = Timetable.query.get(self.test_slot_b_id)
            self.assertIsNotNone(slot, "Record must NOT be deleted by Accountant.")

    # -------------------------------------------------------------------------
    # 2. Peer Faculty Cross-Ownership Protection (Faculty A vs Faculty B)
    # -------------------------------------------------------------------------
    def test_04_faculty_cannot_delete_peer_faculty_slot(self):
        self._login_as(self.faculty_a_id, self.faculty_a_name, self.faculty_a_role)
        res = self.client.post('/timetable/manage', data={
            'action': 'delete',
            'class_id': self.test_slot_b_id,
            'faculty_id': self.faculty_b_id
        })
        self.assertEqual(res.status_code, 403, "Faculty A must receive HTTP 403 when attempting to delete Faculty B's slot.")
        with app.app_context():
            slot = Timetable.query.get(self.test_slot_b_id)
            self.assertIsNotNone(slot, "Faculty B's slot must NOT be deleted in database.")

    def test_05_faculty_cannot_update_peer_faculty_session(self):
        self._login_as(self.faculty_a_id, self.faculty_a_name, self.faculty_a_role)
        res = self.client.post('/timetable/manage', data={
            'action': 'update_session',
            'class_id': self.test_slot_b_id,
            'subject': 'Tampered Subject by Faculty A',
            'day': 'Friday',
            'time': '10:00 AM-11:00 AM',
            'semester': 'Sem I'
        })
        self.assertEqual(res.status_code, 403, "Faculty A must receive HTTP 403 when attempting to edit Faculty B's slot.")
        with app.app_context():
            slot = Timetable.query.get(self.test_slot_b_id)
            self.assertEqual(slot.subject, 'Batch8A Target Subject', "Database subject must remain unchanged.")
            self.assertEqual(slot.day, 'Tuesday', "Database day must remain unchanged.")

    def test_06_faculty_cannot_update_peer_faculty_status(self):
        self._login_as(self.faculty_a_id, self.faculty_a_name, self.faculty_a_role)
        res = self.client.post('/timetable/manage', data={
            'action': 'update_status',
            'class_id': self.test_slot_b_id,
            'status': 'missed'
        })
        self.assertEqual(res.status_code, 403, "Faculty A must receive HTTP 403 when attempting to alter Faculty B's slot status.")
        with app.app_context():
            slot = Timetable.query.get(self.test_slot_b_id)
            self.assertEqual(slot.status, 'pending', "Database status must remain unchanged.")

    def test_07_faculty_cannot_add_slot_for_peer_faculty(self):
        self._login_as(self.faculty_a_id, self.faculty_a_name, self.faculty_a_role)
        res = self.client.post('/timetable/manage', data={
            'action': 'add',
            'faculty_id': self.faculty_b_id,
            'subject': 'Unauthorized Assignment by Peer',
            'day': 'Wednesday',
            'time': '09:00 AM-10:00 AM',
            'semester': 'Sem V'
        })
        self.assertEqual(res.status_code, 403, "Faculty A must receive HTTP 403 when adding slot for Faculty B.")
        with app.app_context():
            slot = Timetable.query.filter_by(subject='Unauthorized Assignment by Peer').first()
            self.assertIsNone(slot, "Database must NOT contain unauthorized slot assigned to Faculty B.")

    # -------------------------------------------------------------------------
    # 3. Authorized Faculty Self-Management
    # -------------------------------------------------------------------------
    def test_08_faculty_can_manage_own_timetable(self):
        self._login_as(self.faculty_a_id, self.faculty_a_name, self.faculty_a_role)
        # 1. Add own slot
        res_add = self.client.post('/timetable/manage', data={
            'action': 'add',
            'faculty_id': self.faculty_a_id,
            'subject': 'Faculty A Self Class',
            'day': 'Thursday',
            'time': '11:30 AM-12:30 PM',
            'semester': 'Sem V'
        })
        self.assertEqual(res_add.status_code, 302, "Faculty A must successfully add own slot (302 redirect).")

        with app.app_context():
            own_slot = Timetable.query.filter_by(user_id=self.faculty_a_id, subject='Faculty A Self Class').first()
            self.assertIsNotNone(own_slot, "Own slot must be created in database.")
            slot_id = own_slot.id

        # 2. Update own status
        res_stat = self.client.post('/timetable/manage', data={
            'action': 'update_status',
            'class_id': slot_id,
            'status': 'held',
            'faculty_id': self.faculty_a_id
        })
        self.assertEqual(res_stat.status_code, 302)
        with app.app_context():
            updated_slot = Timetable.query.get(slot_id)
            self.assertEqual(updated_slot.status, 'held', "Own slot status must be updated to 'held'.")

        # 3. Update own session details
        res_edit = self.client.post('/timetable/manage', data={
            'action': 'update_session',
            'class_id': slot_id,
            'subject': 'Faculty A Self Class Renamed',
            'day': 'Friday',
            'time': '11:30 AM-12:30 PM',
            'semester': 'Sem V'
        })
        self.assertEqual(res_edit.status_code, 302)
        with app.app_context():
            edited_slot = Timetable.query.get(slot_id)
            self.assertEqual(edited_slot.subject, 'Faculty A Self Class Renamed', "Own slot details must be updated.")

        # 4. Delete own slot
        res_del = self.client.post('/timetable/manage', data={
            'action': 'delete',
            'class_id': slot_id,
            'faculty_id': self.faculty_a_id
        })
        self.assertEqual(res_del.status_code, 302)
        with app.app_context():
            deleted_slot = Timetable.query.get(slot_id)
            self.assertIsNone(deleted_slot, "Own slot must be deleted from database.")

    # -------------------------------------------------------------------------
    # 4. Administrative Privileges (Principal, HOD, Admin)
    # -------------------------------------------------------------------------
    def test_09_principal_can_manage_faculty_timetable(self):
        self._login_as(self.principal_id, self.principal_name, self.principal_role)
        # Principal updates status of Faculty B's slot
        res = self.client.post('/timetable/manage', data={
            'action': 'update_status',
            'class_id': self.test_slot_b_id,
            'status': 'held',
            'faculty_id': self.faculty_b_id
        })
        self.assertEqual(res.status_code, 302, "Principal must be authorized to update faculty slot status.")
        with app.app_context():
            slot = Timetable.query.get(self.test_slot_b_id)
            self.assertEqual(slot.status, 'held', "Principal update must persist in database.")

    def test_10_hod_can_manage_department_faculty_timetable(self):
        self._login_as(self.hod_id, self.hod_name, self.hod_role)
        # HOD updates session of Faculty B's slot
        res = self.client.post('/timetable/manage', data={
            'action': 'update_session',
            'class_id': self.test_slot_b_id,
            'subject': 'Batch8A Target Subject HOD Adjusted',
            'day': 'Tuesday',
            'time': '02:00 PM-03:00 PM',
            'semester': 'Sem V',
            'faculty_id': self.faculty_b_id
        })
        self.assertEqual(res.status_code, 302, "HOD must be authorized to adjust department faculty slot.")
        with app.app_context():
            slot = Timetable.query.get(self.test_slot_b_id)
            self.assertEqual(slot.subject, 'Batch8A Target Subject HOD Adjusted')

    def test_11_admin_can_manage_faculty_timetable(self):
        self._login_as(self.admin_id, self.admin_name, self.admin_role)
        # Admin resets status back to pending
        res = self.client.post('/timetable/manage', data={
            'action': 'update_status',
            'class_id': self.test_slot_b_id,
            'status': 'pending',
            'faculty_id': self.faculty_b_id
        })
        self.assertEqual(res.status_code, 302, "Admin must be authorized to manage timetable slots.")
        with app.app_context():
            slot = Timetable.query.get(self.test_slot_b_id)
            self.assertEqual(slot.status, 'pending')

    # -------------------------------------------------------------------------
    # 5. Robustness & Safe Error Handling
    # -------------------------------------------------------------------------
    def test_12_nonexistent_and_malformed_identifiers_handled_safely(self):
        self._login_as(self.faculty_a_id, self.faculty_a_name, self.faculty_a_role)

        # Non-integer class_id
        res_malformed = self.client.post('/timetable/manage', data={
            'action': 'delete',
            'class_id': 'malformed_not_an_int'
        })
        self.assertEqual(res_malformed.status_code, 400, "Malformed class_id must return HTTP 400.")

        # Nonexistent class_id
        res_nonexistent = self.client.post('/timetable/manage', data={
            'action': 'delete',
            'class_id': 9999999
        })
        self.assertEqual(res_nonexistent.status_code, 404, "Nonexistent class_id must return HTTP 404.")

        # Unknown action
        res_unknown_action = self.client.post('/timetable/manage', data={
            'action': 'arbitrary_drop_database',
            'class_id': self.test_slot_b_id
        })
        self.assertEqual(res_unknown_action.status_code, 400, "Unknown action must return HTTP 400.")

        # Missing action
        res_missing_action = self.client.post('/timetable/manage', data={
            'class_id': self.test_slot_b_id
        })
        self.assertEqual(res_missing_action.status_code, 400, "Missing action must return HTTP 400.")

    def test_13_cannot_delete_slot_with_active_class_sessions(self):
        # Timetable slot 31 is the known authoritative row referenced by ClassSession
        with app.app_context():
            session_with_slot = ClassSession.query.filter_by(timetable_id=31).first()
            if not session_with_slot:
                session_with_slot = ClassSession.query.first()
            if session_with_slot:
                target_tt_id = session_with_slot.timetable_id
                target_slot = Timetable.query.get(target_tt_id)
                target_owner_id = target_slot.user_id
                target_owner = User.query.get(target_owner_id)
                target_owner_name = target_owner.full_name
                target_owner_role = target_owner.role
            else:
                target_tt_id = None
                target_owner_id = None

        if target_tt_id and target_owner_id:
            self._login_as(target_owner_id, target_owner_name, target_owner_role)
            res = self.client.post('/timetable/manage', data={
                'action': 'delete',
                'class_id': target_tt_id,
                'faculty_id': target_owner_id
            })
            self.assertEqual(res.status_code, 400, "Must return HTTP 400 when attempting to delete slot with recorded attendance.")
            with app.app_context():
                persisted_slot = Timetable.query.get(target_tt_id)
                self.assertIsNotNone(persisted_slot, "Slot with ClassSession FK reference must NOT be deleted.")

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            # Clean up test slot
            slot = Timetable.query.filter_by(subject='Batch8A Target Subject').first()
            if slot:
                db.session.delete(slot)
                db.session.commit()
            slot_adj = Timetable.query.filter_by(subject='Batch8A Target Subject HOD Adjusted').first()
            if slot_adj:
                db.session.delete(slot_adj)
                db.session.commit()


if __name__ == '__main__':
    unittest.main()
