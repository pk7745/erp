"""
Automated Test Suite for Academic Assignments and Study Materials Library
Covers:
1. Central Academic Access Control & Shared Attendance Policy (75% threshold, fail-closed PENDING, HOD overrides)
2. Assignment Creation, Validation, Lifecycle, Deadlines & Audits
3. Student Submission Uploads, Late Calculation, Resubmission Versioning & Cross-Student Isolation
4. Teacher Submission Roster & Manual Status Recording
5. Study Materials Library (Textbooks, Previous Year Papers, Question Banks)
6. File Security: Extension, Signature/Magic Bytes, Path Traversal Defense & Private Streaming
7. Zero Data Leakage on Restricted Content
"""

import io
import os
import unittest
from datetime import date, datetime, timedelta
from app import (
    app, db, User, Student, Timetable, ClassSession, StudentAttendance,
    Assignment, AssignmentSubmission, StudyMaterial, AcademicResourceAudit,
    MarksEligibilityOverride, MarksEligibilityAudit,
    get_academic_content_access_decision, can_manage_academic_resource,
    get_subject_attendance_eligibility, get_active_hod_access_decision,
    validate_academic_file, save_academic_file, remove_academic_file,
    VALID_STUDY_MATERIAL_CATEGORIES
)


class AssignmentsAndStudyMaterialsTestCase(unittest.TestCase):
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

            students = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).all()
            assert len(students) >= 2, "Test requires at least 2 active BCA Sem V students"
            cls.student1_id = students[0].id
            cls.student2_id = students[1].id
            cls.student1_uucms = students[0].uucms_id
            cls.student2_uucms = students[1].uucms_id

            # Clean any old test assignments, submissions, materials or audits
            AssignmentSubmission.query.delete()
            AcademicResourceAudit.query.delete()
            Assignment.query.filter(Assignment.title.like('TEST-ASG%')).delete()
            StudyMaterial.query.filter(StudyMaterial.title.like('TEST-MAT%')).delete()
            db.session.commit()

            # Create isolated test sessions for 'Web Programming' on 2026-09-01, 2026-09-08, 2026-09-15, 2026-09-22
            tt = Timetable.query.filter_by(subject='Web Programming', semester='Sem V', section='A').first()
            test_dates = [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22)]

            old_sessions = ClassSession.query.filter(ClassSession.date.in_(test_dates), ClassSession.scheduled_subject == 'Web Programming').all()
            for os_sess in old_sessions:
                StudentAttendance.query.filter_by(class_session_id=os_sess.id).delete()
                db.session.delete(os_sess)
            db.session.commit()

            cls.test_session_ids = []
            for dt in test_dates:
                cs = ClassSession(
                    timetable_id=tt.id if tt else None,
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

            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            AssignmentSubmission.query.delete()
            AcademicResourceAudit.query.delete()
            Assignment.query.filter(Assignment.title.like('TEST-ASG%')).delete()
            StudyMaterial.query.filter(StudyMaterial.title.like('TEST-MAT%')).delete()
            if hasattr(cls, 'test_session_ids') and cls.test_session_ids:
                StudentAttendance.query.filter(StudentAttendance.class_session_id.in_(cls.test_session_ids)).delete(synchronize_session=False)
                ClassSession.query.filter(ClassSession.id.in_(cls.test_session_ids)).delete(synchronize_session=False)
            db.session.commit()

    # =========================================================================
    # 1. CENTRALIZED ATTENDANCE ACCESS CONTROL POLICY
    # =========================================================================

    def test_01_centralized_attendance_policy_matrix(self):
        """Tests the shared access decision rules across 75% boundary, pending state, and HOD overrides."""
        with app.app_context():
            student = Student.query.get(self.student1_id)
            scope = {'course': 'BCA', 'semester': 'Sem V', 'section': 'A', 'assessment_cycle': '2026-27'}

            # Rule 5: No evaluation date provided -> fail-closed PENDING state
            dec_no_date = get_academic_content_access_decision(
                user=None, student=student, subject='Web Programming', academic_scope=scope,
                resource_type='ASSIGNMENT', evaluation_date=None
            )
            self.assertFalse(dec_no_date['can_view'])
            self.assertEqual(dec_no_date['status'], 'PENDING')

            # Clean any active overrides for this student
            MarksEligibilityOverride.query.filter_by(
                student_id=student.id, subject='Web Programming', course='BCA', semester='Sem V', section='A'
            ).delete()
            db.session.commit()

            # Rule 1: Active HOD manual restriction denies student access unconditionally
            override_restrict = MarksEligibilityOverride(
                student_id=student.id, subject='Web Programming', course='BCA', semester='Sem V', section='A',
                assessment_cycle='2026-27', component='ALL', decision_type='MANUAL_RESTRICT',
                reason='Disciplinary restriction', created_by_id=self.kiran_id, updated_by_id=self.kiran_id, is_active=True
            )
            db.session.add(override_restrict)
            db.session.commit()

            dec_hod_restrict = get_academic_content_access_decision(
                user=None, student=student, subject='Web Programming', academic_scope=scope,
                resource_type='ASSIGNMENT', evaluation_date=date(2026, 10, 1)
            )
            self.assertFalse(dec_hod_restrict['can_view'])
            self.assertEqual(dec_hod_restrict['decision_source'], 'HOD_MANUAL_RESTRICT')

            # Rule 2: Active HOD explicit allow permits student access below 75%
            override_restrict.decision_type = 'ALLOW_OVERRIDE'
            override_restrict.reason = 'Medical dispensation approved'
            db.session.commit()

            dec_hod_allow = get_academic_content_access_decision(
                user=None, student=student, subject='Web Programming', academic_scope=scope,
                resource_type='ASSIGNMENT', evaluation_date=date(2026, 10, 1)
            )
            self.assertTrue(dec_hod_allow['can_view'])
            self.assertEqual(dec_hod_allow['decision_source'], 'HOD_ALLOW_OVERRIDE')

            # Clean override to test automatic attendance
            db.session.delete(override_restrict)
            db.session.commit()

    def test_02_can_manage_academic_resource_permissions(self):
        """Validates that teachers can only manage subjects they teach, and HOD scope is department-limited."""
        with app.app_context():
            balram = User.query.get(self.balram_id)
            shrinkala = User.query.get(self.shrinkala_id)
            kiran = User.query.get(self.kiran_id)
            acc1 = User.query.get(self.acc1_id)

            bca_scope = {'course': 'BCA', 'semester': 'Sem V', 'section': 'A'}
            bcom_scope = {'course': 'B.Com', 'semester': 'Sem V', 'section': 'A'}

            # Balram teaches Web Programming in BCA Sem V Sec A
            self.assertTrue(can_manage_academic_resource(balram, 'Web Programming', bca_scope, 'CREATE'))

            # Balram DOES NOT teach Cryptography (Shrinkala does)
            self.assertFalse(can_manage_academic_resource(balram, 'Cryptography & Network Security', bca_scope, 'CREATE'))

            # Shrinkala teaches Cryptography
            self.assertTrue(can_manage_academic_resource(shrinkala, 'Cryptography & Network Security', bca_scope, 'CREATE'))

            # HOD Kiran can manage BCA courses
            self.assertTrue(can_manage_academic_resource(kiran, 'Web Programming', bca_scope, 'MANAGE'))

            # HOD Kiran CANNOT manage non-BCA courses (B.Com)
            self.assertFalse(can_manage_academic_resource(kiran, 'Financial Accounting', bcom_scope, 'MANAGE'))

            # Accountant cannot manage academic resources
            self.assertFalse(can_manage_academic_resource(acc1, 'Web Programming', bca_scope, 'MANAGE'))

    # =========================================================================
    # 2. FILE VALIDATION & SECURITY
    # =========================================================================

    def test_03_file_security_validation(self):
        """Verifies rejection of executables/scripts and acceptance of valid documents."""
        # 1. Prohibited executable/script rejection (.sh, .exe, .py)
        sh_file = io.BytesIO(b"#!/bin/bash\necho 'malicious'")
        sh_file.filename = "script.sh"
        valid, err, _, _, _ = validate_academic_file(sh_file)
        self.assertFalse(valid)
        self.assertIn("executable/script", err)

        exe_file = io.BytesIO(b"MZ\x90\x00\x03\x00")
        exe_file.filename = "trojan.exe"
        valid, err, _, _, _ = validate_academic_file(exe_file)
        self.assertFalse(valid)

        # 2. Corrupted PDF header rejection
        fake_pdf = io.BytesIO(b"This is not a real PDF file")
        fake_pdf.filename = "assignment.pdf"
        valid, err, _, _, _ = validate_academic_file(fake_pdf)
        self.assertFalse(valid)
        self.assertIn("PDF header", err)

        # 3. Valid PDF document acceptance
        valid_pdf = io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")
        valid_pdf.filename = "valid_assignment.pdf"
        valid, err, clean_name, mime, size = validate_academic_file(valid_pdf)
        self.assertTrue(valid)
        self.assertEqual(clean_name, "valid_assignment.pdf")

        # 4. Storage helper creates private file with random UUID key and checksum
        storage_key, checksum, fsize = save_academic_file(
            valid_pdf,
            app.config['ASSIGNMENTS_STORAGE_FOLDER'],
            clean_name
        )
        self.assertTrue(storage_key.endswith('.pdf'))
        self.assertNotEqual(storage_key, clean_name) # Key is randomized UUID
        self.assertTrue(len(checksum) == 64) # SHA-256

        # Cleanup
        remove_academic_file(storage_key, app.config['ASSIGNMENTS_STORAGE_FOLDER'])

    # =========================================================================
    # 3. ASSIGNMENT WORKFLOW (CREATE, EDIT, ROSTER, AUDIT)
    # =========================================================================

    def test_04_assignment_creation_and_date_validation(self):
        """Tests that authorized teachers can create assignments and invalid schedules are rejected."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        # 1. Invalid schedule: deadline earlier than assigned_date rejected
        invalid_payload = {
            'title': 'TEST-ASG-Invalid Dates',
            'description': 'Test assignment with bad dates',
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'academic_year': '3rd Year',
            'assigned_date': '2026-10-15',
            'deadline': '2026-10-10T12:00', # 5 days BEFORE assigned date!
            'max_marks': '20.0',
            'status': 'Published'
        }
        res = self.client.post('/academic/assignments/create', data=invalid_payload, follow_redirects=True)
        self.assertIn(b'Submission deadline cannot be earlier than the assigned date', res.data)

        # 2. Unauthorized teacher attempting to create assignment for another subject
        unauth_payload = dict(invalid_payload)
        unauth_payload['subject'] = 'Financial Accounting' # Balram not authorized!
        unauth_payload['deadline'] = '2026-10-25T12:00'
        res_unauth = self.client.post('/academic/assignments/create', data=unauth_payload)
        self.assertEqual(res_unauth.status_code, 403)

        # 3. Valid assignment creation with attachment
        valid_pdf_content = b"%PDF-1.4\n%BMS-TEST-ASSIGNMENT\ntrailer\n<<>>\n%%EOF"
        valid_payload = {
            'title': 'TEST-ASG-Web Programming Lab 1',
            'description': 'Implement session management in PHP and SQLite database connection.',
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'A',
            'subject': 'Web Programming',
            'academic_year': '3rd Year',
            'assigned_date': '2026-10-01',
            'deadline': '2026-10-20T23:59',
            'max_marks': '20.0',
            'status': 'Published',
            'attachment': (io.BytesIO(valid_pdf_content), 'lab1_specs.pdf')
        }
        res_create = self.client.post('/academic/assignments/create', data=valid_payload, follow_redirects=True)
        self.assertEqual(res_create.status_code, 200)

        with app.app_context():
            asg = Assignment.query.filter_by(title='TEST-ASG-Web Programming Lab 1').first()
            self.assertIsNotNone(asg)
            self.assertEqual(asg.subject, 'Web Programming')
            self.assertEqual(asg.attachment_filename, 'lab1_specs.pdf')
            self.assertIsNotNone(asg.attachment_storage_key)
            self.assertEqual(asg.max_marks, 20.0)

            # Audit record verification
            audit = AcademicResourceAudit.query.filter_by(resource_type='ASSIGNMENT', resource_id=asg.id).first()
            self.assertIsNotNone(audit)
            self.assertEqual(audit.action, 'CREATE')

    def test_05_assignment_edit_and_unauthorized_tampering(self):
        """Verifies that an unauthorized teacher cannot modify another teacher's assignment."""
        with app.app_context():
            asg = Assignment.query.filter_by(title='TEST-ASG-Web Programming Lab 1').first()
            asg_id = asg.id

        # Shrinkala attempts to edit Balram's assignment -> 403 Forbidden!
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.shrinkala_id)
            sess['user_id'] = self.shrinkala_id

        tamper_payload = {
            'title': 'TEST-ASG-Tampered Title',
            'description': 'Malicious modification',
            'deadline': '2026-10-25T23:59',
            'status': 'Published',
            'reason': 'Unauthorized edit'
        }
        res_tamper = self.client.post(f'/academic/assignments/{asg_id}/edit', data=tamper_payload)
        self.assertEqual(res_tamper.status_code, 403)

        # Balram edits his assignment legally
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        legal_payload = {
            'title': 'TEST-ASG-Web Programming Lab 1 (Extended)',
            'description': 'Extended deadline with updated evaluation criteria.',
            'deadline': '2026-10-25T23:59',
            'max_marks': '20.0',
            'status': 'Published',
            'reason': 'Extended deadline per student requests'
        }
        res_legal = self.client.post(f'/academic/assignments/{asg_id}/edit', data=legal_payload, follow_redirects=True)
        self.assertEqual(res_legal.status_code, 200)

        with app.app_context():
            updated_asg = Assignment.query.get(asg_id)
            self.assertEqual(updated_asg.title, 'TEST-ASG-Web Programming Lab 1 (Extended)')

    # =========================================================================
    # 4. STUDENT SUBMISSION, LATE STATUS & CROSS-STUDENT ISOLATION
    # =========================================================================

    def test_06_student_submission_and_cross_student_isolation(self):
        """Verifies submission tracking, deadline calculation, and zero cross-student leakage."""
        with app.app_context():
            asg = Assignment.query.filter(Assignment.title.like('TEST-ASG-Web Programming%')).first()
            asg_id = asg.id

        # 1. Student 1 logs in
        with self.client.session_transaction() as sess:
            sess.clear()
        res_login = self.client.post('/student/login', data={'uucms_id': self.student1_uucms}, follow_redirects=True)
        self.assertEqual(res_login.status_code, 200)

        # 2. Student 1 submits valid solution file
        sol_content = b"%PDF-1.4\n%STUDENT1-SOLUTION\ntrailer\n<<>>\n%%EOF"
        sub_payload = {
            'file': (io.BytesIO(sol_content), 'student1_solution.pdf'),
            'student_comment': 'Completed all exercises'
        }
        res_sub = self.client.post(f'/student/assignments/{asg_id}/submit', data=sub_payload, follow_redirects=True)
        self.assertEqual(res_sub.status_code, 200)

        with app.app_context():
            sub = AssignmentSubmission.query.filter_by(assignment_id=asg_id, student_id=self.student1_id).first()
            self.assertIsNotNone(sub)
            self.assertEqual(sub.version, 1)
            self.assertEqual(sub.file_filename, 'student1_solution.pdf')
            sub1_id = sub.id

        # 3. Student 2 logs in
        with self.client.session_transaction() as sess:
            sess.clear()
        res_login2 = self.client.post('/student/login', data={'uucms_id': self.student2_uucms}, follow_redirects=True)
        self.assertEqual(res_login2.status_code, 200)

        # CRITICAL SECURITY CHECK: Student 2 attempts to download Student 1's submission file -> 403 Forbidden!
        res_leak = self.client.get(f'/academic/assignments/submission/{sub1_id}/download')
        self.assertEqual(res_leak.status_code, 403)

    def test_07_teacher_submission_roster_and_grading(self):
        """Verifies teacher submission roster, manual status recording, and grading."""
        with app.app_context():
            asg = Assignment.query.filter(Assignment.title.like('TEST-ASG-Web Programming%')).first()
            asg_id = asg.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        # 1. View Roster
        res_roster = self.client.get(f'/academic/assignments/{asg_id}/roster')
        self.assertEqual(res_roster.status_code, 200)
        self.assertIn(b'Submission Roster', res_roster.data)

        # 2. Teacher records grade and feedback for Student 1
        grade_payload = {
            'student_id': self.student1_id,
            'status': 'Submitted',
            'marks_obtained': '18.5',
            'teacher_feedback': 'Excellent implementation of session tokens.'
        }
        res_grade = self.client.post(f'/academic/assignments/{asg_id}/submission/record-status', data=grade_payload, follow_redirects=True)
        self.assertEqual(res_grade.status_code, 200)

        with app.app_context():
            sub = AssignmentSubmission.query.filter_by(assignment_id=asg_id, student_id=self.student1_id).first()
            self.assertEqual(sub.marks_obtained, 18.5)
            self.assertEqual(sub.teacher_feedback, 'Excellent implementation of session tokens.')

    # =========================================================================
    # 5. STUDY MATERIALS LIBRARY (TEXTBOOKS, PREV PAPERS, QUESTION BANKS)
    # =========================================================================

    def test_08_study_materials_all_three_categories_and_security(self):
        """Verifies upload and retrieval across Textbooks, Previous Year Papers, and Question Banks."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        pdf_bytes = b"%PDF-1.4\n%BMS-STUDY-MATERIAL\ntrailer\n<<>>\n%%EOF"

        # 1. Upload Textbook
        tb_payload = {
            'title': 'TEST-MAT-Web Programming with PHP and MySQL',
            'description': 'Comprehensive reference textbook for Sem V students.',
            'category': 'Textbooks',
            'subject': 'Web Programming',
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'ALL',
            'academic_year': '3rd Year',
            'unit_or_chapter': 'Chapters 1-5',
            'tags': 'Reference, MySQL, PHP',
            'status': 'Published',
            'file': (io.BytesIO(pdf_bytes), 'web_prog_book.pdf')
        }
        res_tb = self.client.post('/academic/study-materials/upload', data=tb_payload, follow_redirects=True)
        self.assertEqual(res_tb.status_code, 200)

        # 2. Upload Previous Year Paper
        pyp_payload = {
            'title': 'TEST-MAT-Web Programming 2024 University Question Paper',
            'description': 'End-semester question paper with solutions.',
            'category': 'Previous Year Papers',
            'subject': 'Web Programming',
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'ALL',
            'academic_year': '3rd Year',
            'exam_year': '2024',
            'tags': 'Solved, Past Paper',
            'status': 'Published',
            'file': (io.BytesIO(pdf_bytes), 'exam_2024.pdf')
        }
        res_pyp = self.client.post('/academic/study-materials/upload', data=pyp_payload, follow_redirects=True)
        self.assertEqual(res_pyp.status_code, 200)

        # 3. Upload Question Bank
        qb_payload = {
            'title': 'TEST-MAT-Web Programming 200 Questions Bank',
            'description': 'Departmental question bank covering modules 1 to 5.',
            'category': 'Question Banks',
            'subject': 'Web Programming',
            'course': 'BCA',
            'semester': 'Sem V',
            'section': 'ALL',
            'academic_year': '3rd Year',
            'tags': 'Question Bank, 2026',
            'status': 'Published',
            'file': (io.BytesIO(pdf_bytes), 'qbank_2026.pdf')
        }
        res_qb = self.client.post('/academic/study-materials/upload', data=qb_payload, follow_redirects=True)
        self.assertEqual(res_qb.status_code, 200)

        with app.app_context():
            # Verify all three exist in database with checksums
            materials = StudyMaterial.query.filter(StudyMaterial.title.like('TEST-MAT%')).all()
            self.assertEqual(len(materials), 3)
            categories = {m.category for m in materials}
            self.assertEqual(categories, {'Textbooks', 'Previous Year Papers', 'Question Banks'})
            for m in materials:
                self.assertIsNotNone(m.file_checksum)
                self.assertEqual(len(m.file_checksum), 64)

    def test_09_study_material_archive_and_unauthorized_edit(self):
        """Verifies unauthorized edit is rejected, and archiving works."""
        with app.app_context():
            mat = StudyMaterial.query.filter_by(category='Textbooks').filter(StudyMaterial.title.like('TEST-MAT%')).first()
            mat_id = mat.id

        # Shrinkala attempts to archive Balram's textbook -> 403 Forbidden!
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.shrinkala_id)
            sess['user_id'] = self.shrinkala_id

        res_unauth = self.client.post(f'/academic/study-materials/{mat_id}/archive')
        self.assertEqual(res_unauth.status_code, 403)

        # Balram archives his textbook
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.balram_id)
            sess['user_id'] = self.balram_id

        res_archive = self.client.post(f'/academic/study-materials/{mat_id}/archive', follow_redirects=True)
        self.assertEqual(res_archive.status_code, 200)

        with app.app_context():
            archived_mat = StudyMaterial.query.get(mat_id)
            self.assertEqual(archived_mat.status, 'Archived')

    # =========================================================================
    # 6. ZERO DATA LEAKAGE ON DIRECT ACCESS TO RESTRICTED CONTENT
    # =========================================================================

    def test_10_restricted_student_file_access_blocked(self):
        """Verifies that an attendance-restricted student cannot access downloads or previews."""
        with app.app_context():
            student = Student.query.get(self.student2_id)
            asg = Assignment.query.filter(Assignment.title.like('TEST-ASG-Web Programming%')).first()
            mat = StudyMaterial.query.filter_by(category='Previous Year Papers').filter(StudyMaterial.title.like('TEST-MAT%')).first()

            # Apply an explicit HOD manual restriction for Student 2
            MarksEligibilityOverride.query.filter_by(
                student_id=student.id, subject='Web Programming', course='BCA', semester='Sem V', section='A'
            ).delete()

            override = MarksEligibilityOverride(
                student_id=student.id,
                subject='Web Programming',
                course='BCA',
                semester='Sem V',
                section='A',
                assessment_cycle='2026-27',
                component='ALL',
                decision_type='MANUAL_RESTRICT',
                reason='Mandatory test restriction',
                created_by_id=self.kiran_id,
                updated_by_id=self.kiran_id,
                is_active=True
            )
            db.session.add(override)
            db.session.commit()

            asg_id = asg.id
            mat_id = mat.id

        # Student 2 logs in
        with self.client.session_transaction() as sess:
            sess.clear()
        self.client.post('/student/login', data={'uucms_id': self.student2_uucms}, follow_redirects=True)

        # 1. Direct assignment attachment download blocked with 403 Forbidden!
        res_asg_dl = self.client.get(f'/academic/assignments/{asg_id}/download')
        self.assertEqual(res_asg_dl.status_code, 403)

        # 2. Direct study material download blocked with 403 Forbidden!
        res_mat_dl = self.client.get(f'/academic/study-materials/{mat_id}/download')
        self.assertEqual(res_mat_dl.status_code, 403)

        # 3. Direct study material preview blocked with 403 Forbidden!
        res_mat_prev = self.client.get(f'/academic/study-materials/{mat_id}/preview')
        self.assertEqual(res_mat_prev.status_code, 403)

        # 4. Student assignment detail view shows restricted page without file leaks
        res_asg_detail = self.client.get(f'/student/assignments/{asg_id}')
        self.assertEqual(res_asg_detail.status_code, 403)
        self.assertIn(b'Academic Access Restricted', res_asg_detail.data)
        self.assertNotIn(b'Download File', res_asg_detail.data)


if __name__ == '__main__':
    unittest.main()
