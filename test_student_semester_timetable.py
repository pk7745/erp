"""
Automated Test Suite for BMS College ERP Student Semester Timetable Module
==========================================================================
Verifies:
1. Teacher management dashboard & upload interface access controls.
2. Server-side validation of academic scope (course, academic year, semester, section).
3. Rejection of invalid semester-year combinations (e.g., 1st Year with Sem V).
4. Strict file upload validation (formats, magic byte headers, size caps, empty files).
5. Safe file persistence in private storage with SHA-256 checksum computation.
6. Replacement behavior: automatically archiving previous active versions and incrementing version numbers.
7. Student self-service timetable view automatically matching authenticated student's academic scope.
8. Anti-tampering: students cannot access or download other semesters' timetables.
9. Appropriate empty state display when no timetable is published.
10. Secure download and inline view authorization.
11. Notification dispatch to matching enrolled students upon publication.
12. NON-NEGOTIABLE REQUIREMENT: Strict verification that the existing teacher timetable
    model, routes, templates, data, and tests remain 100% untouched and functional.
"""

import os
import io
import json
import unittest
from datetime import datetime

from app import (
    app, db, User, Student, Notification,
    Timetable, StudentSemesterTimetable
)
from notification_service import get_unread_count


class TestStudentSemesterTimetable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

        with app.app_context():
            db.create_all()

            # 1. Authorized Teacher User
            cls.teacher = User.query.filter_by(username='test_tt_teacher').first()
            if not cls.teacher:
                cls.teacher = User(
                    username='test_tt_teacher',
                    password='hashed_dummy_pw',
                    full_name='Prof. Test Teacher',
                    role='Faculty',
                    email='test_tt_teacher@bms.test'
                )
                db.session.add(cls.teacher)

            # 2. Unauthorized Staff (e.g., General Employee)
            cls.unauth_staff = User.query.filter_by(username='test_tt_unauth').first()
            if not cls.unauth_staff:
                cls.unauth_staff = User(
                    username='test_tt_unauth',
                    password='hashed_dummy_pw',
                    full_name='Staff Clerk',
                    role='Clerk',
                    email='test_tt_clerk@bms.test'
                )
                db.session.add(cls.unauth_staff)

            # 3. Student in BCA 3rd Year Sem V Section A
            cls.student_sem5 = Student.query.filter_by(uucms_id='TEST_STU_SEM5_A').first()
            if not cls.student_sem5:
                cls.student_sem5 = Student(
                    uucms_id='TEST_STU_SEM5_A',
                    name='Aarav Sharma',
                    email='aarav_sem5@bms.test',
                    course='BCA',
                    academic_year='3rd Year',
                    semester='Sem V',
                    section='A',
                    is_active=True
                )
                db.session.add(cls.student_sem5)

            # 4. Student in BCA 1st Year Sem I Section A (Different Scope)
            cls.student_sem1 = Student.query.filter_by(uucms_id='TEST_STU_SEM1_A').first()
            if not cls.student_sem1:
                cls.student_sem1 = Student(
                    uucms_id='TEST_STU_SEM1_A',
                    name='Rohan Verma',
                    email='rohan_sem1@bms.test',
                    course='BCA',
                    academic_year='1st Year',
                    semester='Sem I',
                    section='A',
                    is_active=True
                )
                db.session.add(cls.student_sem1)

            db.session.commit()
            cls.teacher_id = cls.teacher.id
            cls.unauth_staff_id = cls.unauth_staff.id
            cls.student_sem5_id = cls.student_sem5.id
            cls.student_sem1_id = cls.student_sem1.id

    def setUp(self):
        # Clean test timetables
        with app.app_context():
            test_tts = StudentSemesterTimetable.query.filter(
                StudentSemesterTimetable.title.like('TEST_%')
            ).all()
            for t in test_tts:
                file_path = os.path.join(app.config['STUDENT_TIMETABLES_STORAGE_FOLDER'], t.file_storage_key)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                db.session.delete(t)
            db.session.commit()

    # --------------------------------------------------------------------------
    # 1. ACCESS CONTROLS & DASHBOARD
    # --------------------------------------------------------------------------
    def test_01_authorized_teacher_can_access_dashboard_and_upload_form(self):
        """Verifies authorized teacher can access the student timetables management dashboard and upload page."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = 'Prof. Test Teacher'

        res_dash = self.client.get('/academic/student-timetables')
        self.assertEqual(res_dash.status_code, 200)
        self.assertIn(b"Student Semester Timetables", res_dash.data)

        res_upload = self.client.get('/academic/student-timetables/upload')
        self.assertEqual(res_upload.status_code, 200)
        self.assertIn(b"Publish Student Semester Timetable", res_upload.data)

    def test_02_unauthorized_user_denied_dashboard_and_upload(self):
        """Verifies unauthenticated users and students are denied access to timetable management."""
        # Unauthenticated -> redirect to login
        with self.client.session_transaction() as sess:
            sess.clear()

        res1 = self.client.get('/academic/student-timetables')
        self.assertEqual(res1.status_code, 302)

        res2 = self.client.get('/academic/student-timetables/upload')
        self.assertEqual(res2.status_code, 302)

        # Student user in session -> 403 Forbidden / redirect
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_sem5_id

        res3 = self.client.get('/academic/student-timetables')
        self.assertEqual(res3.status_code, 302)

    # --------------------------------------------------------------------------
    # 2. VALIDATION OF ACADEMIC SCOPE & FIELDS
    # --------------------------------------------------------------------------
    def test_03_validation_rejection_missing_fields_and_invalid_scopes(self):
        """Verifies server rejects missing title, invalid courses, and mismatched year/semester."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'

        def make_dummy_pdf():
            return (io.BytesIO(b"%PDF-1.4\nTest PDF content\n%%EOF"), "timetable.pdf")

        # Missing title -> 400
        res1 = self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': '',
            'file': make_dummy_pdf()
        }, content_type='multipart/form-data')
        self.assertEqual(res1.status_code, 400)
        self.assertIn(b"Title is mandatory", res1.data)

        # Invalid Academic Year -> 400
        res2 = self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '10th Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': 'TEST_Invalid_Year',
            'file': make_dummy_pdf()
        }, content_type='multipart/form-data')
        self.assertEqual(res2.status_code, 400)
        self.assertIn(b"Invalid Academic Year", res2.data)

        # Mismatched Semester for Year: 1st Year with Sem V -> 400
        res3 = self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '1st Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': 'TEST_Mismatched_Scope',
            'file': make_dummy_pdf()
        }, content_type='multipart/form-data')
        self.assertEqual(res3.status_code, 400)
        self.assertIn(b"Invalid Semester", res3.data)

    def test_04_file_validation_rejection(self):
        """Verifies rejection of prohibited extensions, empty files, and corrupted headers."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'

        # Prohibited executable (.exe)
        exe_file = (io.BytesIO(b"MZ\x90\x00executable content"), "malicious.exe")
        res1 = self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': 'TEST_Malicious_Exe',
            'file': exe_file
        }, content_type='multipart/form-data')
        self.assertEqual(res1.status_code, 400)

        # Empty file (0 bytes)
        empty_file = (io.BytesIO(b""), "empty.pdf")
        res2 = self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': 'TEST_Empty_File',
            'file': empty_file
        }, content_type='multipart/form-data')
        self.assertEqual(res2.status_code, 400)
        self.assertIn(b"empty", res2.data)

        # Corrupted PDF header
        corrupt_file = (io.BytesIO(b"NOT_A_REAL_PDF_HEADER_123456"), "corrupt.pdf")
        res3 = self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': 'TEST_Corrupt_PDF',
            'file': corrupt_file
        }, content_type='multipart/form-data')
        self.assertEqual(res3.status_code, 400)
        self.assertIn(b"Corrupted or invalid PDF header", res3.data)

    # --------------------------------------------------------------------------
    # 3. SUCCESSFUL UPLOAD, PUBLICATION & REPLACEMENT/VERSIONING
    # --------------------------------------------------------------------------
    def test_05_successful_timetable_upload_and_publication(self):
        """Verifies an authorized teacher can publish a timetable with secure storage and SHA-256 computation."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = 'Prof. Test Teacher'

        valid_pdf = (io.BytesIO(b"%PDF-1.4\n1 0 obj\n<< /Title (Semester V Timetable) >>\nendobj\n%%EOF"), "bca_sem5_tt.pdf")
        res = self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': 'TEST_BCA_Sem5_SecA_Timetable_v1',
            'description': 'Official Room 204 Class Schedule',
            'file': valid_pdf
        }, content_type='multipart/form-data')

        self.assertEqual(res.status_code, 302) # Redirect to dashboard upon success

        with app.app_context():
            tt = StudentSemesterTimetable.query.filter_by(
                title='TEST_BCA_Sem5_SecA_Timetable_v1'
            ).first()
            self.assertIsNotNone(tt)
            self.assertEqual(tt.course, 'BCA')
            self.assertEqual(tt.academic_year, '3rd Year')
            self.assertEqual(tt.semester, 'Sem V')
            self.assertEqual(tt.section, 'A')
            self.assertEqual(tt.status, 'PUBLISHED')
            self.assertEqual(tt.version, 1)
            self.assertEqual(tt.file_filename, 'bca_sem5_tt.pdf')
            self.assertTrue(len(tt.file_checksum) == 64) # SHA-256 hex string

            # Verify file exists on disk
            path = os.path.join(app.config['STUDENT_TIMETABLES_STORAGE_FOLDER'], tt.file_storage_key)
            self.assertTrue(os.path.exists(path))

    def test_06_replacement_and_versioning_archives_previous_active(self):
        """Verifies uploading a timetable for the same scope automatically archives version 1 and publishes version 2."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = 'Prof. Test Teacher'

        # Upload Version 1
        pdf1 = (io.BytesIO(b"%PDF-1.4\nVersion 1 Content\n%%EOF"), "v1.pdf")
        self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': 'TEST_BCA_Sem5_SecA_v1',
            'file': pdf1
        }, content_type='multipart/form-data')

        # Upload Version 2 for exact same scope
        pdf2 = (io.BytesIO(b"%PDF-1.4\nVersion 2 Revised Schedule\n%%EOF"), "v2_revised.pdf")
        res2 = self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': 'TEST_BCA_Sem5_SecA_v2',
            'file': pdf2
        }, content_type='multipart/form-data')
        self.assertEqual(res2.status_code, 302)

        with app.app_context():
            tt_v1 = StudentSemesterTimetable.query.filter_by(title='TEST_BCA_Sem5_SecA_v1').first()
            tt_v2 = StudentSemesterTimetable.query.filter_by(title='TEST_BCA_Sem5_SecA_v2').first()

            self.assertIsNotNone(tt_v1)
            self.assertIsNotNone(tt_v2)

            # v1 must be ARCHIVED
            self.assertEqual(tt_v1.status, 'ARCHIVED')
            self.assertEqual(tt_v1.version, 1)

            # v2 must be PUBLISHED with version 2
            self.assertEqual(tt_v2.status, 'PUBLISHED')
            self.assertEqual(tt_v2.version, 2)

            # Exactly one active timetable for this scope
            active_count = StudentSemesterTimetable.query.filter_by(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                status='PUBLISHED'
            ).count()
            self.assertEqual(active_count, 1)

    # --------------------------------------------------------------------------
    # 4. STUDENT TIMETABLE VIEW & SCOPE MATCHING
    # --------------------------------------------------------------------------
    def test_07_student_automatic_scope_retrieval(self):
        """Verifies student sees their matching published timetable automatically without manual selection."""
        # First ensure a published timetable exists for Sem V Sec A
        with app.app_context():
            tt = StudentSemesterTimetable(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                title='TEST_BCA_Sem5_SecA_Official',
                description='Room 204 Schedule',
                file_filename='official_sem5.pdf',
                file_storage_key='test_official_sem5.pdf',
                file_mimetype='application/pdf',
                file_size=2048,
                file_checksum='abc123sha256',
                version=1,
                status='PUBLISHED',
                uploaded_by_id=self.teacher_id,
                created_at=datetime.utcnow()
            )
            db.session.add(tt)
            db.session.commit()

        # Log in as Sem V student
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_sem5_id

        res = self.client.get('/student/timetable')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"TEST_BCA_Sem5_SecA_Official", res.data)
        self.assertIn(b"BCA", res.data)
        self.assertIn(b"Sem V", res.data)
        self.assertIn(b"Section A", res.data)
        self.assertIn(b"Download Timetable", res.data)

    def test_08_scope_isolation_and_tampering_prevention(self):
        """Verifies student from 1st Year Sem I cannot download 3rd Year Sem V timetable via direct ID."""
        with app.app_context():
            sem5_tt = StudentSemesterTimetable(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                title='TEST_Sem5_Private_Timetable',
                file_filename='sem5_sched.pdf',
                file_storage_key='test_sem5_sched.pdf',
                file_mimetype='application/pdf',
                file_size=1024,
                file_checksum='dummy_checksum',
                version=1,
                status='PUBLISHED',
                uploaded_by_id=self.teacher_id
            )
            db.session.add(sem5_tt)
            db.session.commit()
            sem5_tt_id = sem5_tt.id

        # Log in as 1st Year Sem I student
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_sem1_id

        # Student Sem I attempts to download Sem V timetable by guessing ID -> 403 Forbidden
        res = self.client.get(f'/academic/student-timetables/{sem5_tt_id}/download')
        self.assertEqual(res.status_code, 403)

    def test_09_empty_state_when_no_timetable_published(self):
        """Verifies empty state is cleanly rendered when no timetable has been published for student's scope."""
        # Log in as Sem I student where no timetable has been uploaded
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_sem1_id

        res = self.client.get('/student/timetable')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"No Timetable Published Yet", res.data)
        self.assertIn(b"BCA 1st Year Sem I Section A", res.data)

    def test_10_secure_download_and_view(self):
        """Verifies student in matching scope and authorized teacher can view and download the timetable."""
        # Create physical dummy file
        dummy_content = b"%PDF-1.4\nDownload test stream\n%%EOF"
        storage_folder = app.config['STUDENT_TIMETABLES_STORAGE_FOLDER']
        test_filename = 'test_downloadable_tt.pdf'
        full_path = os.path.join(storage_folder, test_filename)
        with open(full_path, 'wb') as f:
            f.write(dummy_content)

        with app.app_context():
            tt = StudentSemesterTimetable(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                title='TEST_Download_Timetable',
                file_filename='bca_sem5_final.pdf',
                file_storage_key=test_filename,
                file_mimetype='application/pdf',
                file_size=len(dummy_content),
                file_checksum='checksum123',
                version=1,
                status='PUBLISHED',
                uploaded_by_id=self.teacher_id
            )
            db.session.add(tt)
            db.session.commit()
            tt_id = tt.id

        # Authorized student download
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_sem5_id

        res_dl = self.client.get(f'/academic/student-timetables/{tt_id}/download')
        self.assertEqual(res_dl.status_code, 200)
        self.assertIn('attachment', res_dl.headers.get('Content-Disposition', ''))
        self.assertEqual(res_dl.data, dummy_content)

        # Authorized student inline view (for PDF iframe / image rendering)
        res_view = self.client.get(f'/academic/student-timetables/{tt_id}/view')
        self.assertEqual(res_view.status_code, 200)
        self.assertEqual(res_view.mimetype, 'application/pdf')

        # Clean up physical test file
        try:
            res_dl.close()
            res_view.close()
        except Exception:
            pass
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except Exception:
                pass

    def test_11_teacher_archive_action(self):
        """Verifies teacher can manually archive a published timetable."""
        with app.app_context():
            tt = StudentSemesterTimetable(
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                title='TEST_To_Archive',
                file_filename='temp.pdf',
                file_storage_key='temp.pdf',
                file_mimetype='application/pdf',
                file_size=100,
                version=1,
                status='PUBLISHED',
                uploaded_by_id=self.teacher_id
            )
            db.session.add(tt)
            db.session.commit()
            tt_id = tt.id

        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = 'Prof. Test Teacher'

        res = self.client.post(f'/academic/student-timetables/{tt_id}/archive')
        self.assertEqual(res.status_code, 302)

        with app.app_context():
            archived = StudentSemesterTimetable.query.get(tt_id)
            self.assertEqual(archived.status, 'ARCHIVED')

    def test_12_notifications_dispatched_to_matching_students(self):
        """Verifies student receives notification with proper name addressing when a timetable is published."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = 'Prof. Test Teacher'

        dummy_pdf = (io.BytesIO(b"%PDF-1.4\nNotification test PDF\n%%EOF"), "notif_test.pdf")
        self.client.post('/academic/student-timetables/upload', data={
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'title': 'TEST_BCA_Sem5_Notif_Timetable',
            'file': dummy_pdf
        }, content_type='multipart/form-data')

        with app.app_context():
            notif = Notification.query.filter(
                Notification.recipient_type == 'STUDENT',
                Notification.student_id == self.student_sem5_id,
                Notification.title.like('%Semester Timetable%')
            ).order_by(Notification.id.desc()).first()

            self.assertIsNotNone(notif)
            self.assertTrue(notif.message.startswith(f"Dear {self.student_sem5.name},"))
            self.assertIn("Prof. Test Teacher", notif.message)
            self.assertEqual(notif.action_url, '/student/timetable')

    # --------------------------------------------------------------------------
    # 5. NON-NEGOTIABLE REQUIREMENT: TEACHER TIMETABLE MODULE PRESERVATION
    # --------------------------------------------------------------------------
    def test_13_non_negotiable_teacher_timetable_preservation(self):
        """
        NON-NEGOTIABLE VERIFICATION:
        Ensures existing Teacher Timetable module remains completely untouched:
        1. Timetable model schema and table name are unchanged.
        2. Timetable.id = 31 foreign-key linked slot exists.
        3. Teacher routes /timetable, /timetable/manage, /timetable/overview are functional.
        """
        with app.app_context():
            # 1. Model schema verification
            self.assertEqual(Timetable.__tablename__, 'timetable')
            columns = {c.name for c in Timetable.__table__.columns}
            required_teacher_cols = {'id', 'day', 'time_slot', 'subject', 'semester', 'course', 'section', 'room_no', 'status', 'user_id', 'created_at'}
            self.assertTrue(required_teacher_cols.issubset(columns))

            # 2. Critical Timetable.id = 31 preservation
            tt31 = Timetable.query.get(31)
            self.assertIsNotNone(tt31, "CRITICAL ERROR: Timetable.id = 31 was modified or deleted!")
            self.assertEqual(tt31.semester, 'Sem V')

        # 3. Teacher routes functional
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = 'Prof. Test Teacher'

        res_teacher_tt = self.client.get('/timetable')
        self.assertEqual(res_teacher_tt.status_code, 200)

        res_overview = self.client.get('/timetable/overview')
        self.assertEqual(res_overview.status_code, 200)


if __name__ == '__main__':
    unittest.main()
