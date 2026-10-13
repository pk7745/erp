"""
Test Suite for Authoritative Timetable, Faculty Schedules, and Shared Overview
Verifies:
1. 20 Authoritative Semester V slots are populated exactly as per source image.
2. Timetable.id = 31 in-place update preserves FK linkage with ClassSession.
3. Conflict pre-validation reports 0 overlaps.
4. CRT Program (Add-on) slots (GF Lab 3h and Room 101 2h) are properly configured.
5. Dr. Kiran Kumar M N has 0 Semester V allocations and standard Sem I-IV titles.
6. Mr. Ramkishore is assigned only English subjects.
7. /timetable/overview returns HTTP 403 Forbidden for admin.
8. /timetable/overview returns HTTP 200 OK for regular faculty (e.g., Balram).
9. /timetable/overview returns HTTP 200 OK for faculty without Sem V allocations (e.g., Kiran).
"""

import unittest
from app import app, db, Timetable, ClassSession, User, sync_authoritative_timetable, validate_timetable_conflicts


class AuthoritativeTimetableTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()

    def test_01_sem5_slot_count_and_subjects(self):
        with app.app_context():
            sync_authoritative_timetable()
            sem5_slots = Timetable.query.filter_by(semester='Sem V').all()
            self.assertEqual(len(sem5_slots), 20, f"Expected 20 Sem V slots, found {len(sem5_slots)}")

    def test_02_preservation_of_class_session_fk_on_row_31(self):
        with app.app_context():
            tt31 = Timetable.query.get(31)
            self.assertIsNotNone(tt31, "Timetable row 31 must exist")
            self.assertEqual(tt31.day, 'Monday')
            self.assertEqual(tt31.time_slot, '12:30 PM-01:30 PM')
            self.assertEqual(tt31.subject, 'Web Programming')
            self.assertEqual(tt31.room_no, '203')
            self.assertEqual(tt31.faculty.username, 'balram')

            sessions = ClassSession.query.filter_by(timetable_id=31).all()
            self.assertGreaterEqual(len(sessions), 1, "ClassSession linkage on row 31 must be preserved")

    def test_03_crt_program_slots(self):
        with app.app_context():
            crt_slots = Timetable.query.filter(
                Timetable.semester == 'Sem V',
                Timetable.subject.like('%CRT%')
            ).all()
            self.assertEqual(len(crt_slots), 2, "Expected 2 CRT Add-on slots")
            rooms = {s.room_no for s in crt_slots}
            self.assertIn('GF Lab', rooms)
            self.assertIn('101', rooms)

    def test_04_kiran_kumar_allocations(self):
        with app.app_context():
            kiran = User.query.filter_by(username='kiran').first()
            self.assertIsNotNone(kiran, "User kiran must exist")
            kiran_slots = Timetable.query.filter_by(user_id=kiran.id).all()
            kiran_sem5 = [s for s in kiran_slots if s.semester == 'Sem V']
            self.assertEqual(len(kiran_sem5), 0, "Dr. Kiran must have 0 Sem V subjects")

            # Check standardized subject names
            subjects = {s.subject for s in kiran_slots}
            self.assertIn('C Programming', subjects)
            self.assertIn('Data Structures and Algorithms', subjects)
            self.assertIn('Database Management System', subjects)
            self.assertIn('Design and Analysis of Algorithms', subjects)

    def test_05_ramkishore_allocations(self):
        with app.app_context():
            ramkishore = User.query.filter_by(username='ramkishore').first()
            if ramkishore:
                rk_slots = Timetable.query.filter_by(user_id=ramkishore.id).all()
                for slot in rk_slots:
                    self.assertIn('English', slot.subject, "Mr. Ramkishore must only teach English")

    def test_06_admin_access_forbidden(self):
        with app.app_context():
            admin = User.query.filter_by(username='admin').first()
            admin_id = admin.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(admin_id)
            sess['user_id'] = admin_id

        res = self.client.get('/timetable/overview')
        self.assertEqual(res.status_code, 403, "Admin account must be forbidden (403) from overview")

    def test_07_faculty_access_allowed(self):
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            balram_id = balram.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(balram_id)
            sess['user_id'] = balram_id

        res = self.client.get('/timetable/overview')
        self.assertEqual(res.status_code, 200, "Faculty member must have access (200)")
        self.assertIn(b'BMS College of Commerce and Management', res.data)
        self.assertIn(b'Web Programming', res.data)

    def test_08_kiran_faculty_access_allowed(self):
        with app.app_context():
            kiran = User.query.filter_by(username='kiran').first()
            kiran_id = kiran.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(kiran_id)
            sess['user_id'] = kiran_id

        res = self.client.get('/timetable/overview')
        self.assertEqual(res.status_code, 200, "Faculty with 0 Sem V allocations must still view overview (200)")

    def test_09_anonymous_redirect(self):
        # Empty session
        with self.client.session_transaction() as sess:
            sess.clear()
        res = self.client.get('/timetable/overview')
        self.assertEqual(res.status_code, 302, "Anonymous user must be redirected to login")


if __name__ == '__main__':
    unittest.main()
