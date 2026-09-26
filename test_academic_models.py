import unittest
import sys
import os
from datetime import date, datetime
from sqlalchemy.exc import IntegrityError

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"C:\Users\pky45\.gemini\antigravity\scratch\erp")

from app import app, db, User, Timetable, Student, ClassSession, StudentAttendance, Attendance

class AcademicModelsTestCase(unittest.TestCase):
    """
    Step 3.1 Verification Suite: Academic Attendance Models, Section Support & Historical Integrity.
    Tests:
      1. Student creation with valid fields including Section (A, B)
      2. Student UUCMS ID uniqueness enforcement (duplicate throws IntegrityError)
      3. Student email storage and query
      4. Timetable extended fields (course, section, room_no)
      5. ClassSession links to Timetable and enforces non-nullable timetable_id
      6. ClassSession preserves historical integrity if Timetable is later altered
      7. ClassSession faculty substitution (scheduled vs actual faculty)
      8. ClassSession date validation (strictly date object)
      9. StudentAttendance link, status values, and unique constraint (session + student)
      10. Staff Attendance model remains completely independent without interference
    """

    @classmethod
    def clean_test_data(cls):
        try:
            StudentAttendance.query.filter(StudentAttendance.remarks.like('TEST_%')).delete(synchronize_session=False)
            ClassSession.query.filter(ClassSession.remarks.like('TEST_%')).delete(synchronize_session=False)
            Student.query.filter(Student.uucms_id.like('TEST_%')).delete(synchronize_session=False)
            Attendance.query.filter(Attendance.work_mode == 'TEST_OFFICE').delete(synchronize_session=False)
            Timetable.query.filter(Timetable.subject.like('TEST_%')).delete(synchronize_session=False)
            db.session.commit()
        except Exception:
            db.session.rollback()

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()

        cls.clean_test_data()

        cls.fac1 = User.query.filter_by(username='kiran').first()
        cls.fac2 = User.query.filter_by(username='shrinkala').first()
        if not cls.fac1:
            cls.fac1 = User(username='test_kiran', role='faculty', full_name='Dr. Kiran Kumar', email='kiran@bms.edu.in')
            db.session.add(cls.fac1)
        if not cls.fac2:
            cls.fac2 = User(username='test_shrinkala', role='faculty', full_name='Prof. Shrinkhala', email='shrinkala@bms.edu.in')
            db.session.add(cls.fac2)
        db.session.commit()

        cls.tt = Timetable.query.first()
        if not cls.tt:
            cls.tt = Timetable(
                user_id=cls.fac1.id,
                day='Monday',
                time_slot='09:00 AM-10:00 AM',
                subject='Web Programming',
                semester='Sem V',
                course='BCA',
                section='A',
                room_no='Room 204'
            )
            db.session.add(cls.tt)
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        cls.clean_test_data()
        cls.app_context.pop()

    def setUp(self):
        self.clean_test_data()

    def tearDown(self):
        self.clean_test_data()

    def test_01_student_creation_with_section(self):
        """1. Student creation with valid fields including Section (A, B)"""
        student_a = Student(
            uucms_id='TEST_UUCMS_001_A',
            name='Aarav Sharma',
            email='aarav.sharma@bms.edu.in',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A',
            is_active=True
        )
        student_b = Student(
            uucms_id='TEST_UUCMS_001_B',
            name='Bhavna Reddy',
            email='bhavna.reddy@bms.edu.in',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='B',
            is_active=True
        )
        db.session.add_all([student_a, student_b])
        db.session.commit()

        fetched_a = Student.query.filter_by(uucms_id='TEST_UUCMS_001_A').first()
        fetched_b = Student.query.filter_by(uucms_id='TEST_UUCMS_001_B').first()

        self.assertIsNotNone(fetched_a)
        self.assertEqual(fetched_a.section, 'A')
        self.assertEqual(fetched_a.course, 'BCA')
        self.assertEqual(fetched_a.semester, 'Sem V')
        self.assertEqual(fetched_a.academic_year, '3rd Year')

        self.assertIsNotNone(fetched_b)
        self.assertEqual(fetched_b.section, 'B')

    def test_02_student_uucms_id_uniqueness(self):
        """2. Student UUCMS ID uniqueness enforcement (duplicate throws IntegrityError)"""
        student1 = Student(
            uucms_id='TEST_UUCMS_UNIQUE',
            name='Unique Student 1',
            email='u1@bms.edu.in',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A'
        )
        db.session.add(student1)
        db.session.commit()

        student2 = Student(
            uucms_id='TEST_UUCMS_UNIQUE',
            name='Unique Student 2 (Duplicate)',
            email='u2@bms.edu.in',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A'
        )
        db.session.add(student2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_03_student_email_storage_and_query(self):
        """3. Student email storage and query"""
        student = Student(
            uucms_id='TEST_UUCMS_003',
            name='Diya Patel',
            email='diya.patel@bms.edu.in',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A'
        )
        db.session.add(student)
        db.session.commit()

        queried = Student.query.filter_by(email='diya.patel@bms.edu.in').first()
        self.assertIsNotNone(queried)
        self.assertEqual(queried.uucms_id, 'TEST_UUCMS_003')

    def test_04_timetable_extended_fields(self):
        """4. Verify Timetable.course, Timetable.section, Timetable.room_no"""
        tt_entry = Timetable(
            user_id=self.fac1.id,
            day='Tuesday',
            time_slot='10:30 AM-11:30 AM',
            subject='TEST_ADV_JAVA',
            semester='Sem V',
            course='BCA',
            section='B',
            room_no='Room 305'
        )
        db.session.add(tt_entry)
        db.session.commit()

        fetched = Timetable.query.get(tt_entry.id)
        self.assertEqual(fetched.course, 'BCA')
        self.assertEqual(fetched.section, 'B')
        self.assertEqual(fetched.room_no, 'Room 305')
        self.assertEqual(fetched.semester, 'Sem V')

    def test_05_class_session_linked_to_timetable_and_non_nullable(self):
        """5. ClassSession links to Timetable and enforces non-nullable timetable_id"""
        session_obj = ClassSession(
            timetable_id=self.tt.id,
            date=date.today(),
            time_slot=self.tt.time_slot,
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section=getattr(self.tt, 'section', 'A') or 'A',
            scheduled_subject=self.tt.subject,
            actual_subject=self.tt.subject,
            scheduled_faculty_id=self.fac1.id,
            actual_faculty_id=self.fac1.id,
            room_no='Room 204',
            status='COMPLETED',
            remarks='TEST_SESSION_TT'
        )
        db.session.add(session_obj)
        db.session.commit()

        self.assertIsNotNone(session_obj.id)
        self.assertEqual(session_obj.timetable_id, self.tt.id)
        self.assertEqual(session_obj.section, 'A')
        self.assertEqual(session_obj.course, 'BCA')
        self.assertEqual(session_obj.academic_year, '3rd Year')
        self.assertEqual(session_obj.semester, 'Sem V')

        # Test non-nullable constraint on timetable_id
        session_without_tt = ClassSession(
            timetable_id=None,
            date=date.today(),
            time_slot='09:00 AM-10:00 AM',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A',
            scheduled_subject='Web Programming',
            actual_subject='Web Programming',
            scheduled_faculty_id=self.fac1.id,
            actual_faculty_id=self.fac1.id,
            status='COMPLETED',
            remarks='TEST_SESSION_NO_TT'
        )
        db.session.add(session_without_tt)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_06_class_session_historical_integrity(self):
        """6. ClassSession preserves historical integrity if Timetable is later altered"""
        tt_sample = Timetable(
            user_id=self.fac1.id,
            day='Wednesday',
            time_slot='02:00 PM-03:00 PM',
            subject='TEST_DATA_STRUCTURES',
            semester='Sem V',
            course='BCA',
            section='A',
            room_no='Room 204'
        )
        db.session.add(tt_sample)
        db.session.commit()

        hist_session = ClassSession(
            timetable_id=tt_sample.id,
            date=date.today(),
            time_slot=tt_sample.time_slot,
            course=tt_sample.course,
            academic_year='3rd Year',
            semester=tt_sample.semester,
            section=tt_sample.section,
            scheduled_subject=tt_sample.subject,
            actual_subject=tt_sample.subject,
            scheduled_faculty_id=tt_sample.user_id,
            actual_faculty_id=tt_sample.user_id,
            room_no=tt_sample.room_no,
            status='COMPLETED',
            remarks='TEST_HISTORICAL_INTEGRITY'
        )
        db.session.add(hist_session)
        db.session.commit()
        session_id = hist_session.id

        # Timetable modified in a subsequent term
        tt_sample.semester = 'Sem VI'
        tt_sample.section = 'B'
        tt_sample.subject = 'TEST_ADVANCED_DS'
        tt_sample.room_no = 'Room 401'
        db.session.commit()

        # ClassSession retains original historical values
        reloaded_session = ClassSession.query.get(session_id)
        self.assertEqual(reloaded_session.course, 'BCA')
        self.assertEqual(reloaded_session.academic_year, '3rd Year')
        self.assertEqual(reloaded_session.semester, 'Sem V')
        self.assertEqual(reloaded_session.section, 'A')
        self.assertEqual(reloaded_session.scheduled_subject, 'TEST_DATA_STRUCTURES')
        self.assertEqual(reloaded_session.room_no, 'Room 204')

    def test_07_class_session_faculty_substitution(self):
        """7. ClassSession creation with distinct scheduled_faculty and actual_faculty (substitution support)"""
        session_obj = ClassSession(
            timetable_id=self.tt.id,
            date=date.today(),
            time_slot='10:30 AM-11:30 AM',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A',
            scheduled_subject='Data Structures',
            actual_subject='Data Structures',
            scheduled_faculty_id=self.fac1.id,
            actual_faculty_id=self.fac2.id,
            room_no='Room 204',
            status='COMPLETED',
            remarks='TEST_FACULTY_SUBSTITUTION'
        )
        db.session.add(session_obj)
        db.session.commit()

        self.assertNotEqual(session_obj.scheduled_faculty_id, session_obj.actual_faculty_id)
        self.assertEqual(session_obj.scheduled_faculty.id, self.fac1.id)
        self.assertEqual(session_obj.actual_faculty.id, self.fac2.id)

    def test_08_class_session_date_validation(self):
        """8. ClassSession date validation (strictly date object)"""
        today_date = date.today()
        session_obj = ClassSession(
            timetable_id=self.tt.id,
            date=today_date,
            time_slot='11:30 AM-12:30 PM',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A',
            scheduled_subject='DBMS',
            actual_subject='DBMS',
            scheduled_faculty_id=self.fac1.id,
            actual_faculty_id=self.fac1.id,
            room_no='Room 204',
            status='COMPLETED',
            remarks='TEST_DATE_VALIDATION'
        )
        db.session.add(session_obj)
        db.session.commit()

        fetched = ClassSession.query.filter_by(remarks='TEST_DATE_VALIDATION').first()
        self.assertIsInstance(fetched.date, date)
        self.assertEqual(fetched.date, today_date)

    def test_09_student_attendance_link_status_and_uniqueness(self):
        """9. StudentAttendance link, status values, and unique constraint (session + student)"""
        student = Student(
            uucms_id='TEST_UUCMS_009_LINK',
            name='Kavya Nair',
            email='kavya.nair@bms.edu.in',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A'
        )
        db.session.add(student)
        db.session.commit()

        session_obj = ClassSession(
            timetable_id=self.tt.id,
            date=date.today(),
            time_slot='10:30 AM-11:30 AM',
            course='BCA',
            academic_year='3rd Year',
            semester='Sem V',
            section='A',
            scheduled_subject='DAA',
            actual_subject='DAA',
            scheduled_faculty_id=self.fac1.id,
            actual_faculty_id=self.fac1.id,
            room_no='Room 204',
            status='COMPLETED',
            remarks='TEST_ATT_DUPLICATE_CHECK'
        )
        db.session.add(session_obj)
        db.session.commit()

        att1 = StudentAttendance(
            class_session_id=session_obj.id,
            student_id=student.id,
            status='Present',
            marked_by=self.fac1.id,
            remarks='TEST_FIRST_MARK'
        )
        db.session.add(att1)
        db.session.commit()

        self.assertIsNotNone(att1.id)
        self.assertEqual(att1.status, 'Present')
        self.assertEqual(att1.student.uucms_id, 'TEST_UUCMS_009_LINK')
        self.assertEqual(att1.class_session.remarks, 'TEST_ATT_DUPLICATE_CHECK')

        # Duplicate check: Attempt to mark same student twice for the same session
        att2 = StudentAttendance(
            class_session_id=session_obj.id,
            student_id=student.id,
            status='Absent',
            remarks='TEST_DUPLICATE_MARK'
        )
        db.session.add(att2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_10_staff_attendance_remains_independent(self):
        """10. Existing staff Attendance model operates completely independently without interference"""
        today_str = date.today().strftime('%Y-%m-%d')
        now_time = datetime.now().strftime('%H:%M:%S')

        staff_att = Attendance(
            user_id=self.fac1.id,
            date=today_str,
            check_in=now_time,
            check_out='17:00:00',
            work_mode='TEST_OFFICE',
            lat=12.9716,
            lon=77.5946
        )
        db.session.add(staff_att)
        db.session.commit()

        fetched_staff = Attendance.query.filter_by(work_mode='TEST_OFFICE').first()
        self.assertIsNotNone(fetched_staff)
        self.assertEqual(fetched_staff.user_id, self.fac1.id)
        self.assertEqual(fetched_staff.check_in, now_time)
        self.assertEqual(fetched_staff.work_mode, 'TEST_OFFICE')

        self.assertTrue(hasattr(Attendance, 'user_id'))
        self.assertTrue(hasattr(Attendance, 'check_in'))
        self.assertTrue(hasattr(Attendance, 'check_out'))
        self.assertTrue(hasattr(Attendance, 'work_mode'))
        self.assertTrue(hasattr(Attendance, 'lat'))
        self.assertTrue(hasattr(Attendance, 'lon'))
        self.assertFalse(hasattr(Attendance, 'student_id'))
        self.assertFalse(hasattr(Attendance, 'class_session_id'))

if __name__ == '__main__':
    unittest.main()
