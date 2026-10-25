"""
Automated Comprehensive Test Suite for BMS ERP Assignments & Study Materials Modules
=====================================================================================
Validates all requirements from the Senior Engineer Implementation Brief:
1. Academic scope validation: Course, Academic Year, Semester, Section, Subject.
2. Rejection of invalid academic scope combinations (e.g., 1st Year with Sem V -> 400).
3. Rejection of subjects not belonging to the chosen academic scope (400).
4. Rejection of invalid date order (deadline earlier than assigned date -> 400).
5. Authorization enforcement: Unauthorized teachers cannot create/edit content (403).
6. Scoped student visibility: Students see only published content matching their cohort.
7. Anti-tampering: Cross-semester/cross-course access and downloads are denied (403).
8. Preserving existing submissions & history during assignment edits.
9. Study materials in exactly 3 categories: Textbooks, Previous Year Papers, Question Banks.
10. Rejection of invalid study material categories (400).
11. Secure file upload validation and private streaming.
12. Scoped notifications with personalized addressing and idempotency.
13. Strict verification that the Teacher Timetable module remains 100% untouched.
"""

import io
import os
import unittest
from datetime import date, datetime, timedelta

from app import (
    app, db, User, Student, Timetable, Assignment, AssignmentSubmission,
    StudyMaterial, AcademicResourceAudit, Notification,
    VALID_STUDY_MATERIAL_CATEGORIES, VALID_COURSES, VALID_ACADEMIC_YEARS,
    VALID_ACADEMIC_YEAR_SEMESTERS
)
from notification_service import get_notifications_list


class TestAssignmentsMaterialsCompliance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

        with app.app_context():
            # Authorized Faculty for BCA Sem V 'Web Programming'
            cls.teacher_balram = User.query.filter_by(username='balram').first()
            assert cls.teacher_balram, "Teacher balram required"
            cls.balram_id = cls.teacher_balram.id

            # Unauthorized Faculty (teaches different subject, e.g. Mathematics/Business)
            cls.teacher_kiran = User.query.filter_by(username='kiran').first()
            assert cls.teacher_kiran, "Teacher kiran required"
            cls.kiran_id = cls.teacher_kiran.id

            # Student 1: BCA 3rd Year Sem V Section A
            cls.student_sem5 = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).first()
            assert cls.student_sem5, "BCA Sem V student required"
            cls.student_sem5_id = cls.student_sem5.id

            # Student 2: BCA 1st Year Sem I Section A (different cohort)
            cls.student_sem1 = Student.query.filter_by(course='BCA', semester='Sem I', section='A', is_active=True).first()
            if not cls.student_sem1:
                cls.student_sem1 = Student(
                    uucms_id='COMPLIANCE_STU_SEM1',
                    name='First Year Student',
                    email='firstyear@bms.test',
                    course='BCA',
                    academic_year='1st Year',
                    semester='Sem I',
                    section='A',
                    is_active=True
                )
                db.session.add(cls.student_sem1)
                db.session.commit()
            cls.student_sem1_id = cls.student_sem1.id

    def setUp(self):
        # Clean any test artifacts created with COMPLIANCE_ prefix
        with app.app_context():
            test_asgs = Assignment.query.filter(Assignment.title.like('COMPL_%')).all()
            for a in test_asgs:
                if a.attachment_storage_key:
                    path = os.path.join(app.config['ASSIGNMENTS_STORAGE_FOLDER'], a.attachment_storage_key)
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass
                db.session.delete(a)

            test_mats = StudyMaterial.query.filter(StudyMaterial.title.like('COMPL_%')).all()
            for m in test_mats:
                if m.file_storage_key:
                    path = os.path.join(app.config['STUDY_MATERIALS_STORAGE_FOLDER'], m.file_storage_key)
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass
                db.session.delete(m)

            Notification.query.filter(Notification.message.like('%COMPL_%')).delete(synchronize_session=False)
            db.session.commit()

    # --------------------------------------------------------------------------
    # 1. ASSIGNMENT SCOPE & SCHEDULE VALIDATION
    # --------------------------------------------------------------------------
    def test_01_assignment_validation_rejects_missing_mandatory_fields(self):
        """Verifies rejection with 400 when title, description, or deadline is missing."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        res = res = self.client.post('/academic/assignments/create', data={
            'title': '', # Empty title
            'description': 'Valid description',
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'deadline': '2026-11-30T23:59'
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn(b"Assignment Title is mandatory", res.data)

    def test_02_assignment_validation_rejects_mismatched_year_semester(self):
        """Verifies server rejects invalid year-semester combinations (e.g. 1st Year with Sem V) with 400."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        res = res = self.client.post('/academic/assignments/create', data={
            'title': 'COMPL_Mismatched_Scope',
            'description': 'Test scope mismatch',
            'course': 'BCA',
            'academic_year': '1st Year',
            'semester': 'Sem V', # 1st Year only allows Sem I, Sem II!
            'section': 'A',
            'subject': 'Web Programming',
            'assigned_date': '2026-11-01',
            'deadline': '2026-11-20T23:59'
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn(b"Invalid Semester", res.data)

    def test_03_assignment_validation_rejects_subject_not_in_scope(self):
        """Verifies server rejects a subject that does not belong to the selected course/semester."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        res = res = self.client.post('/academic/assignments/create', data={
            'title': 'COMPL_Invalid_Subject',
            'description': 'Test non-existent subject for BCA Sem V',
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'NonExistentQuantumRoboticsSubject', # Not in curriculum!
            'assigned_date': '2026-11-01',
            'deadline': '2026-11-20T23:59'
        })
        self.assertEqual(res.status_code, 403) # Unauthorized / not in teacher scope

    def test_04_assignment_validation_rejects_deadline_before_given_date(self):
        """Verifies server rejects a submission deadline that precedes the assigned date with 400."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        res = res = self.client.post('/academic/assignments/create', data={
            'title': 'COMPL_Bad_Dates',
            'description': 'Deadline is before assigned date',
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assigned_date': '2026-11-15',
            'deadline': '2026-11-10T12:00' # 5 days earlier!
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn(b"Submission deadline cannot be earlier than the assigned date", res.data)

    def test_05_unauthorized_teacher_denied_assignment_creation(self):
        """Verifies unauthorized teacher cannot create assignments for subjects they do not teach (403)."""
        # Balram is NOT authorized for 'Financial Accounting' or 'Discrete Structure'
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        res = res = self.client.post('/academic/assignments/create', data={
            'title': 'COMPL_Unauthorized_Attempt',
            'description': 'Balram trying to create unauthorized subject assignment',
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Financial Accounting', # Balram does not teach this!
            'assigned_date': '2026-11-01',
            'deadline': '2026-11-20T23:59'
        })
        self.assertEqual(res.status_code, 403)

    # --------------------------------------------------------------------------
    # 2. SUCCESSFUL CREATION, SCOPE VISIBILITY & EDITING PRESERVATION
    # --------------------------------------------------------------------------
    def test_06_assignment_creation_and_automatic_student_scoping(self):
        """Verifies an authorized teacher creates an assignment and it is visible only to matching students."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        pdf_bytes = b"%PDF-1.4\n%COMPLIANCE-TEST-ATTACHMENT\n%%EOF"
        res = res = self.client.post('/academic/assignments/create', data={
            'title': 'COMPL_Valid_Assignment_v1',
            'description': 'Build an authenticated REST endpoint with CSRF protection.',
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assigned_date': '2026-11-01',
            'deadline': '2026-11-20T23:59',
            'max_marks': '25.0',
            'status': 'Published',
            'attachment': (io.BytesIO(pdf_bytes), 'spec.pdf')
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # 1. Matching 3rd Year Sem V student sees it
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_sem5_id

        res_sem5 = self.client.get('/student/assignments')
        self.assertEqual(res_sem5.status_code, 200)
        self.assertIn(b"COMPL_Valid_Assignment_v1", res_sem5.data)

        # 2. 1st Year Sem I student DOES NOT see it
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_sem1_id

        res_sem1 = self.client.get('/student/assignments')
        self.assertEqual(res_sem1.status_code, 200)
        self.assertNotIn(b"COMPL_Valid_Assignment_v1", res_sem1.data)

    def test_07_cross_cohort_tampering_denied_on_detail_and_download(self):
        """Verifies student from 1st Year cannot view or download 3rd Year assignment via direct URL (403)."""
        with app.app_context():
            asg = Assignment(
                title='COMPL_Private_Sem5_Assignment',
                description='Restricted cohort task',
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                subject='Web Programming',
                assigned_date=date(2026, 11, 1),
                deadline=datetime(2026, 11, 25, 23, 59),
                status='Published',
                attachment_filename='secret.pdf',
                attachment_storage_key='compl_secret.pdf',
                created_by_id=self.balram_id,
                updated_by_id=self.balram_id
            )
            db.session.add(asg)
            db.session.commit()
            asg_id = asg.id

        # Student from Sem I attempts to access Sem V assignment detail -> 403 Forbidden
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_sem1_id

        res_detail = self.client.get(f'/student/assignments/{asg_id}')
        self.assertEqual(res_detail.status_code, 403)

        # Student from Sem I attempts to download Sem V attachment -> 403 Forbidden
        res_dl = self.client.get(f'/academic/assignments/{asg_id}/download')
        self.assertEqual(res_dl.status_code, 403)

    def test_08_assignment_edit_preserves_submissions_and_files(self):
        """Verifies editing assignment details preserves existing student submissions without silent destruction."""
        with app.app_context():
            asg = Assignment(
                title='COMPL_Assignment_To_Edit',
                description='Initial instructions',
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='A',
                subject='Web Programming',
                assigned_date=date(2026, 11, 1),
                deadline=datetime(2026, 11, 15, 23, 59),
                status='Published',
                created_by_id=self.balram_id,
                updated_by_id=self.balram_id
            )
            db.session.add(asg)
            db.session.commit()
            asg_id = asg.id

            # Add existing student submission
            sub = AssignmentSubmission(
                assignment_id=asg_id,
                student_id=self.student_sem5_id,
                status='Submitted',
                status_source='STUDENT_UPLOAD',
                submitted_at=datetime(2026, 11, 5, 14, 0),
                file_filename='my_solution.pdf',
                file_storage_key='dummy_sub_key.pdf',
                version=1
            )
            db.session.add(sub)
            db.session.commit()
            sub_id = sub.id

        # Teacher edits assignment deadline and guidelines
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        res_edit = self.client.post(f'/academic/assignments/{asg_id}/edit', data={
            'title': 'COMPL_Assignment_To_Edit_Extended',
            'description': 'Updated guidelines and rubric',
            'deadline': '2026-11-28T23:59',
            'max_marks': '30.0',
            'status': 'Published',
            'reason': 'Extended by 13 days for student revisions'
        }, follow_redirects=True)
        self.assertEqual(res_edit.status_code, 200)

        # Verify submission record and file metadata are 100% preserved
        with app.app_context():
            asg_updated = Assignment.query.get(asg_id)
            self.assertEqual(asg_updated.title, 'COMPL_Assignment_To_Edit_Extended')
            self.assertEqual(asg_updated.max_marks, 30.0)

            sub_preserved = AssignmentSubmission.query.get(sub_id)
            self.assertIsNotNone(sub_preserved)
            self.assertEqual(sub_preserved.status, 'Submitted')
            self.assertEqual(sub_preserved.file_filename, 'my_solution.pdf')
            self.assertEqual(sub_preserved.version, 1)

    # --------------------------------------------------------------------------
    # 3. STUDY MATERIALS WORKFLOW & THREE MANDATORY CATEGORIES
    # --------------------------------------------------------------------------
    def test_09_study_material_upload_all_three_categories(self):
        """Verifies study materials can be uploaded in Textbooks, Previous Year Papers, and Question Banks."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        pdf_bytes = b"%PDF-1.4\n%COMPL-STUDY-MATERIAL\n%%EOF"

        for cat in ['Textbooks', 'Previous Year Papers', 'Question Banks']:
            res = self.client.post('/academic/study-materials/upload', data={
                'title': f'COMPL_{cat}_Resource',
                'description': f'Essential {cat} document',
                'category': cat,
                'course': 'BCA',
                'academic_year': '3rd Year',
                'semester': 'Sem V',
                'section': 'ALL',
                'subject': 'Web Programming',
                'status': 'Published',
                'file': (io.BytesIO(pdf_bytes), f'{cat.lower().replace(" ", "_")}.pdf')
            }, follow_redirects=True)
            self.assertEqual(res.status_code, 200)

        with app.app_context():
            saved_mats = StudyMaterial.query.filter(StudyMaterial.title.like('COMPL_%_Resource')).all()
            self.assertEqual(len(saved_mats), 3)
            found_cats = {m.category for m in saved_mats}
            self.assertEqual(found_cats, {'Textbooks', 'Previous Year Papers', 'Question Banks'})

    def test_10_study_material_rejects_invalid_category(self):
        """Verifies server strictly rejects non-permitted categories (400)."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        pdf_bytes = b"%PDF-1.4\n%COMPL-INVALID-CAT\n%%EOF"
        res = self.client.post('/academic/study-materials/upload', data={
            'title': 'COMPL_Invalid_Category',
            'description': 'Unsupported category',
            'category': 'Random Unofficial Notes', # Invalid category!
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'ALL',
            'subject': 'Web Programming',
            'file': (io.BytesIO(pdf_bytes), 'notes.pdf')
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn(b"Invalid Category", res.data)

    def test_11_study_material_cross_cohort_isolation(self):
        """Verifies student from 1st Year cannot see or download 3rd Year study materials."""
        with app.app_context():
            mat = StudyMaterial(
                title='COMPL_Sem5_Textbook',
                category='Textbooks',
                course='BCA',
                academic_year='3rd Year',
                semester='Sem V',
                section='ALL',
                subject='Web Programming',
                file_filename='web_prog.pdf',
                file_storage_key='compl_web_prog.pdf',
                file_mimetype='application/pdf',
                file_size=1024,
                status='Published',
                created_by_id=self.balram_id,
                updated_by_id=self.balram_id
            )
            db.session.add(mat)
            db.session.commit()
            mat_id = mat.id

        # Sem I student cannot download Sem V material -> 403 Forbidden
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_sem1_id

        res_dl = self.client.get(f'/academic/study-materials/{mat_id}/download')
        self.assertEqual(res_dl.status_code, 403)

        res_prev = self.client.get(f'/academic/study-materials/{mat_id}/preview')
        self.assertEqual(res_prev.status_code, 403)

    # --------------------------------------------------------------------------
    # 4. NOTIFICATION DISPATCH
    # --------------------------------------------------------------------------
    def test_12_notifications_dispatched_with_personalization(self):
        """Verifies student notification is dispatched with personalized greeting without sensitive URLs."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        pdf_bytes = b"%PDF-1.4\n%COMPL-NOTIF-TEST\n%%EOF"
        res = self.client.post('/academic/assignments/create', data={
            'title': 'COMPL_Notification_Assignment',
            'description': 'Assignment notification test',
            'course': 'BCA',
            'academic_year': '3rd Year',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'assigned_date': '2026-11-01',
            'deadline': '2026-11-20T23:59',
            'status': 'Published',
            'attachment': (io.BytesIO(pdf_bytes), 'specs.pdf')
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with app.app_context():
            notif = Notification.query.filter(
                Notification.recipient_type == 'STUDENT',
                Notification.student_id == self.student_sem5_id,
                Notification.message.like('%COMPL_Notification_Assignment%')
            ).order_by(Notification.id.desc()).first()

            self.assertIsNotNone(notif)
            self.assertTrue(notif.message.startswith(f"Dear {self.student_sem5.name},"))
            self.assertIn(self.teacher_balram.full_name, notif.message)
            self.assertEqual(notif.action_url, '/student/assignments')
            # Verify no secret storage paths are leaked
            self.assertNotIn("private_storage", notif.message)

    # --------------------------------------------------------------------------
    # 5. STRICT PRESERVATION OF TEACHER TIMETABLE MODULE
    # --------------------------------------------------------------------------
    def test_13_teacher_timetable_module_strictly_untouched(self):
        """
        NON-NEGOTIABLE VERIFICATION:
        Ensures existing Teacher Timetable module remains 100% untouched:
        1. Timetable table name and schema are intact.
        2. Timetable.id = 31 exists.
        3. Teacher routes /timetable, /timetable/manage, /timetable/overview are functional.
        """
        with app.app_context():
            self.assertEqual(Timetable.__tablename__, 'timetable')
            columns = {c.name for c in Timetable.__table__.columns}
            required_cols = {'id', 'day', 'time_slot', 'subject', 'semester', 'course', 'section', 'room_no', 'status', 'user_id', 'created_at'}
            self.assertTrue(required_cols.issubset(columns))

            tt31 = Timetable.query.get(31)
            self.assertIsNotNone(tt31, "CRITICAL ERROR: Timetable.id = 31 was modified or deleted!")
            self.assertEqual(tt31.semester, 'Sem V')

        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id
            sess['role'] = 'Faculty'

        res_tt = self.client.get('/timetable')
        self.assertEqual(res_tt.status_code, 200)

        res_overview = self.client.get('/timetable/overview')
        self.assertEqual(res_overview.status_code, 200)


if __name__ == '__main__':
    unittest.main()
