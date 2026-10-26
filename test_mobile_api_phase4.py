import unittest
import os
import json
import time

os.environ['TESTING'] = '1'
from werkzeug.security import generate_password_hash
from app import (
    app, db, User, Student, Timetable, Attendance, ClassSession,
    StudentAttendance, StudentSemesterTimetable, StudyMaterial
)

class MobileApiPhase4TestCase(unittest.TestCase):
    """
    Test suite for Phase 4 Mobile API Endpoints:
    1. Student Attendance Analytics & 75% Recovery Predictor
    2. Staff Campus GPS Attendance & Server-side Geofence Enforcement
    3. Student Semester Timetable Viewing & Secure Download
    4. Study Materials Listing & Secure Download
    """

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

    def setUp(self):
        self.client = app.test_client()
        with app.app_context():
            db.create_all()

            # Ensure upload dirs exist for tests
            os.makedirs(app.config['STUDENT_TIMETABLES_STORAGE_FOLDER'], exist_ok=True)
            os.makedirs(app.config['STUDY_MATERIALS_STORAGE_FOLDER'], exist_ok=True)

            # 1. Staff: Teacher
            teacher = User.query.filter_by(username='prof_phase4').first()
            if not teacher:
                teacher = User(
                    username='prof_phase4',
                    full_name='Prof. Suresh Kumar',
                    email='suresh@bms.edu',
                    role='Faculty',
                    department='Computer Applications',
                    status='Active',
                    password=generate_password_hash('teacherpass123')
                )
                db.session.add(teacher)

            # 2. Staff: Other Teacher (not teaching student's class)
            other_teacher = User.query.filter_by(username='prof_other').first()
            if not other_teacher:
                other_teacher = User(
                    username='prof_other',
                    full_name='Prof. Other Faculty',
                    email='other@bms.edu',
                    role='Faculty',
                    department='Commerce',
                    status='Active',
                    password=generate_password_hash('otherpass123')
                )
                db.session.add(other_teacher)

            # 3. Student 1: BCA Sem 4 Sec A
            student1 = Student.query.filter_by(uucms_id='U03MB24S0001').first()
            if not student1:
                student1 = Student(
                    name='Rohan Verma',
                    email='rohan@bms.edu',
                    uucms_id='U03MB24S0001',
                    course='BCA',
                    academic_year='2nd Year',
                    semester=4,
                    section='A',
                    is_active=True,
                    password_hash=generate_password_hash('studentpass123'),
                    raw_password='studentpass123'
                )
                db.session.add(student1)

            # 4. Student 2: B.Com Sem 2 Sec B (Different cohort)
            student2 = Student.query.filter_by(uucms_id='U03MB24C0002').first()
            if not student2:
                student2 = Student(
                    name='Pooja Hegde',
                    email='pooja@bms.edu',
                    uucms_id='U03MB24C0002',
                    course='B.Com',
                    academic_year='1st Year',
                    semester=2,
                    section='B',
                    is_active=True,
                    password_hash=generate_password_hash('poojapass123'),
                    raw_password='poojapass123'
                )
                db.session.add(student2)

            db.session.commit()

            # Store IDs and credentials
            self.teacher_id = teacher.id
            self.teacher_email = teacher.email
            self.teacher_pass = 'teacherpass123'

            self.other_teacher_id = other_teacher.id
            self.other_teacher_email = other_teacher.email
            self.other_teacher_pass = 'otherpass123'

            self.student1_id = student1.id
            self.student1_uucms = student1.uucms_id
            self.student1_pass = 'studentpass123'

            self.student2_id = student2.id
            self.student2_uucms = student2.uucms_id
            self.student2_pass = 'poojapass123'

            # Assign teacher to Student 1's class in Timetable
            tt = Timetable.query.filter_by(course='BCA', semester=4, section='A', user_id=teacher.id).first()
            if not tt:
                tt = Timetable(
                    user_id=teacher.id,
                    subject='Python Programming',
                    course='BCA',
                    semester=4,
                    section='A',
                    day='Monday',
                    time_slot='10:00 - 11:00',
                    room_no='Lab 2',
                    status='approved'
                )
                db.session.add(tt)
                db.session.commit()

            # Create an attendance session and student attendance for real analytics
            from datetime import date
            cs = ClassSession.query.filter_by(scheduled_subject='Python Programming', course='BCA', semester=4, section='A').first()
            if not cs:
                cs = ClassSession(
                    timetable_id=tt.id,
                    date=date.today(),
                    time_slot='10:00 - 11:00',
                    course='BCA',
                    academic_year='2nd Year',
                    semester=4,
                    section='A',
                    scheduled_subject='Python Programming',
                    actual_subject='Python Programming',
                    scheduled_faculty_id=teacher.id,
                    actual_faculty_id=teacher.id,
                    status='COMPLETED'
                )
                db.session.add(cs)
                db.session.commit()

                sa = StudentAttendance(
                    class_session_id=cs.id,
                    student_id=student1.id,
                    status='Present',
                    marked_by=teacher.id
                )
                db.session.add(sa)
                db.session.commit()

            # Create published Student Semester Timetable
            tt_file_key = 'test_tt_sem4.pdf'
            tt_path = os.path.join(app.config['STUDENT_TIMETABLES_STORAGE_FOLDER'], tt_file_key)
            with open(tt_path, 'wb') as f:
                f.write(b'%PDF-1.4 test timetable content')

            stt = StudentSemesterTimetable.query.filter_by(course='BCA', semester=4, section='A').first()
            if not stt:
                stt = StudentSemesterTimetable(
                    title='BCA Sem 4 Time Table 2026',
                    course='BCA',
                    academic_year='2nd Year',
                    semester=4,
                    section='A',
                    version=1,
                    status='PUBLISHED',
                    file_storage_key=tt_file_key,
                    file_filename='BCA_Sem4_TT.pdf',
                    file_size=len(b'%PDF-1.4 test timetable content'),
                    file_mimetype='application/pdf',
                    uploaded_by_id=teacher.id
                )
                db.session.add(stt)
                db.session.commit()
            self.student_tt_id = stt.id

            # Create published Study Material
            sm_file_key = 'test_sm_python.pdf'
            sm_path = os.path.join(app.config['STUDY_MATERIALS_STORAGE_FOLDER'], sm_file_key)
            with open(sm_path, 'wb') as f:
                f.write(b'%PDF-1.4 test study material content')

            sm = StudyMaterial.query.filter_by(title='Python Fundamentals Notes').first()
            if not sm:
                sm = StudyMaterial(
                    title='Python Fundamentals Notes',
                    subject='Python Programming',
                    course='BCA',
                    academic_year='2nd Year',
                    semester=4,
                    section='A',
                    category='Textbooks',
                    description='Comprehensive lecture notes on Python',
                    tags='python, programming, notes',
                    status='Published',
                    file_storage_key=sm_file_key,
                    file_filename='Python_Notes.pdf',
                    file_size=len(b'%PDF-1.4 test study material content'),
                    file_mimetype='application/pdf',
                    created_by_id=teacher.id,
                    updated_by_id=teacher.id
                )
                db.session.add(sm)
                db.session.commit()
            self.study_material_id = sm.id

    def login_student(self, uucms_id, password):
        return self.client.post('/api/auth/student-login', json={
            'uucms_id': uucms_id,
            'password': password
        })

    def login_staff(self, email, password):
        return self.client.post('/api/auth/staff-login', json={
            'email': email,
            'password': password
        })

    # =========================================================================
    # 1. Student Attendance Analytics & 75% Recovery Predictor
    # =========================================================================

    def test_01_student_attendance_analytics_authorized(self):
        self.login_student(self.student1_uucms, self.student1_pass)
        res = self.client.get('/api/student/attendance-analytics')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['student_id'], self.student1_id)
        self.assertEqual(data['uucms_id'], 'U03MB24S0001')
        self.assertEqual(data['course'], 'BCA')
        self.assertEqual(str(data['semester']), '4')
        self.assertIn('overall_attendance_pct', data)
        self.assertIn('overall_status', data)
        self.assertIn('subject_cards', data)
        self.assertTrue(len(data['subject_cards']) > 0)
        card = data['subject_cards'][0]
        self.assertEqual(card['subject'], 'Python Programming')
        self.assertIn('attendance_pct', card)
        self.assertIn('classes_needed', card)
        self.assertIn('is_target_met', card)
        self.assertIn('risk_label', card)

    def test_02_student_attendance_analytics_unauthorized(self):
        self.client.post('/api/auth/logout')
        res = self.client.get('/api/student/attendance-analytics')
        self.assertEqual(res.status_code, 401)

    def test_03_student_attendance_analytics_cross_student_blocked(self):
        # Student 1 logs in, tries to access Student 2's analytics
        self.login_student(self.student1_uucms, self.student1_pass)
        res = self.client.get(f'/academic/analytics/student/{self.student2_id}', headers={'Accept': 'application/json'})
        self.assertEqual(res.status_code, 403)

    def test_04_teacher_student_analytics_authorized(self):
        # Teacher who teaches BCA Sem 4 accesses Student 1
        self.login_staff(self.teacher_email, self.teacher_pass)
        res = self.client.get(f'/academic/analytics/student/{self.student1_id}', headers={'Accept': 'application/json'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['student_id'], self.student1_id)
        self.assertEqual(data['name'], 'Rohan Verma')

    def test_05_teacher_student_analytics_unauthorized_class(self):
        # Other teacher who does NOT teach BCA Sem 4 tries to access Student 1
        self.login_staff(self.other_teacher_email, self.other_teacher_pass)
        res = self.client.get(f'/academic/analytics/student/{self.student1_id}', headers={'Accept': 'application/json'})
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # 2. Staff Campus GPS Attendance & Geofence Enforcement
    # =========================================================================

    def test_06_staff_attendance_status(self):
        self.login_staff(self.teacher_email, self.teacher_pass)
        res = self.client.get('/api/attendance/status')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['user_id'], self.teacher_id)
        self.assertIn('geofence_config', data)
        geo = data['geofence_config']
        self.assertEqual(geo['center_lat'], 12.9515)
        self.assertEqual(geo['center_lon'], 77.5762)
        self.assertEqual(geo['radius_meters'], 150.0)
        self.assertEqual(geo['max_accuracy_meters'], 50.0)

    def test_07_student_blocked_from_staff_attendance_status(self):
        self.login_student(self.student1_uucms, self.student1_pass)
        res = self.client.get('/api/attendance/status')
        self.assertEqual(res.status_code, 403)

    def test_08_staff_clock_in_inside_geofence_success(self):
        self.login_staff(self.teacher_email, self.teacher_pass)
        now_ts = int(time.time() * 1000)
        res = self.client.post('/attendance', json={
            'lat': 12.951500,
            'lon': 77.576200,
            'accuracy': 12.0,
            'client_timestamp': now_ts,
            'is_inside_campus': True
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status_code'], 'CAMPUS_VERIFIED')

    def test_09_staff_clock_in_outside_geofence_rejected(self):
        self.login_staff(self.teacher_email, self.teacher_pass)
        now_ts = int(time.time() * 1000)
        res = self.client.post('/attendance', json={
            'lat': 13.050000,
            'lon': 77.650000,
            'accuracy': 15.0,
            'client_timestamp': now_ts,
            'is_inside_campus': False
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data['success'])
        self.assertEqual(data['reason_code'], 'OUTSIDE_CAMPUS')

    def test_10_staff_clock_in_poor_accuracy_rejected(self):
        self.login_staff(self.teacher_email, self.teacher_pass)
        now_ts = int(time.time() * 1000)
        res = self.client.post('/attendance', json={
            'lat': 12.951500,
            'lon': 77.576200,
            'accuracy': 85.0,  # Max allowed is 50.0m
            'client_timestamp': now_ts,
            'is_inside_campus': True
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data['success'])
        self.assertEqual(data['reason_code'], 'UNACCEPTABLE_ACCURACY')

    def test_11_staff_clock_in_stale_location_rejected(self):
        self.login_staff(self.teacher_email, self.teacher_pass)
        old_ts = int((time.time() - 300) * 1000)  # 5 minutes old (> 120s max age)
        res = self.client.post('/attendance', json={
            'lat': 12.951500,
            'lon': 77.576200,
            'accuracy': 10.0,
            'client_timestamp': old_ts,
            'is_inside_campus': True
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data['success'])
        self.assertEqual(data['reason_code'], 'STALE_LOCATION')

    # =========================================================================
    # 3. Student Semester Timetable
    # =========================================================================

    def test_12_student_timetable_metadata(self):
        self.login_student(self.student1_uucms, self.student1_pass)
        res = self.client.get('/api/student/timetable')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['has_timetable'])
        tt = data['timetable']
        self.assertEqual(tt['course'], 'BCA')
        self.assertEqual(str(tt['semester']), '4')
        self.assertEqual(tt['section'], 'A')
        self.assertEqual(tt['file_filename'], 'BCA_Sem4_TT.pdf')
        self.assertIn('/download', tt['download_url'])

    def test_13_student_timetable_download_authorized(self):
        self.login_student(self.student1_uucms, self.student1_pass)
        res = self.client.get(f'/academic/student-timetables/{self.student_tt_id}/download')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'application/pdf')
        self.assertIn(b'%PDF-1.4', res.data)

    def test_14_student_timetable_download_cross_cohort_blocked(self):
        # Student 2 (B.Com Sem 2) tries to download Student 1's BCA Sem 4 Timetable
        self.login_student(self.student2_uucms, self.student2_pass)
        res = self.client.get(f'/academic/student-timetables/{self.student_tt_id}/download')
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # 4. Study Materials
    # =========================================================================

    def test_15_student_study_materials_listing(self):
        self.login_student(self.student1_uucms, self.student1_pass)
        res = self.client.get('/api/student/study-materials')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['current_category'], 'Textbooks')
        self.assertTrue(data['materials_count'] >= 1)
        mat = data['materials'][0]
        self.assertEqual(mat['title'], 'Python Fundamentals Notes')
        self.assertEqual(mat['subject'], 'Python Programming')
        self.assertIn('/download', mat['download_url'])

    def test_16_student_study_materials_download_authorized(self):
        self.login_student(self.student1_uucms, self.student1_pass)
        res = self.client.get(f'/academic/study-materials/{self.study_material_id}/download')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'application/pdf')
        self.assertIn(b'%PDF-1.4', res.data)

    def test_17_student_study_materials_download_cross_cohort_blocked(self):
        # Student 2 (B.Com Sem 2) tries to download BCA Sem 4 Study Material
        self.login_student(self.student2_uucms, self.student2_pass)
        res = self.client.get(f'/academic/study-materials/{self.study_material_id}/download')
        self.assertEqual(res.status_code, 403)


if __name__ == '__main__':
    unittest.main()
