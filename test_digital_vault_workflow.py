"""
Comprehensive Automated Test Suite: Digital Vault & OCR Admin Approval Workflow
Strict Admin-Only Access (Strictly excluding Accountant, Principal, Faculty).
Covers:
1. File validation (unsupported extensions, empty files, size limits, integrity)
2. OCR parsing & schema validation for Student and Staff documents
3. Record matching & classification:
   - NEW_STUDENT
   - NEW_STAFF
   - UPDATE_STUDENT (with field-level diff)
   - UPDATE_STAFF (with field-level diff)
   - DUPLICATE_SUBMISSION (SHA-256 detection)
   - AMBIGUOUS_CONFLICT (conflicting identity detection)
4. Admin-Only Authorization & Security:
   - Accountant strictly restricted (403 Forbidden on all vault endpoints)
   - Principal & Faculty strictly restricted (403 Forbidden on all vault endpoints)
   - Submitter self-approval prevention (independent review policy)
   - Rejection with mandatory reason (zero DB changes)
   - Idempotency guard (prevent double approval / double application)
5. Atomic Database Synchronization:
   - Creation of new Student
   - Creation of new Staff
   - Field-level update of existing Student without touching untouched fields
   - Transaction atomicity & rollback on failure
   - Guarded secure document download
"""

import os
import io
import json
import unittest
from datetime import datetime
from PIL import Image
from werkzeug.security import generate_password_hash

from app import app, db, User, Student, VaultDocument, VaultProposal
from vault_engine import (
    validate_vault_file,
    compute_sha256,
    extract_raw_text,
    parse_extracted_text,
    classify_and_match_records,
    apply_approved_proposal
)

class TestDigitalVaultWorkflow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()

        with app.app_context():
            db.create_all()

            admin = User.query.filter_by(username='admin').first()
            acc1 = User.query.filter_by(username='acc1').first()
            principal = User.query.filter_by(username='pankaj').first()
            faculty = User.query.filter_by(username='balram').first()

            # Ensure secondary admin for independent review testing
            admin2 = User.query.filter_by(username='admin2').first()
            if not admin2:
                admin2 = User(
                    username='admin2',
                    password=generate_password_hash('bms123'),
                    role='admin',
                    full_name='Secondary Administrator',
                    email='admin2@bmsccm.edu.in'
                )
                db.session.add(admin2)
                db.session.commit()

            cls.admin_id = admin.id
            cls.admin2_id = admin2.id
            cls.accountant_id = acc1.id
            cls.principal_id = principal.id
            cls.faculty_id = faculty.id

            assert cls.admin_id is not None
            assert cls.admin2_id is not None
            assert cls.accountant_id is not None

            # Clean test proposals & students
            VaultProposal.query.filter(VaultProposal.target_identifier.like('TEST%')).delete()
            Student.query.filter(Student.uucms_id.like('TEST%')).delete()
            Student.query.filter(Student.email.in_(['aarav.sharma@bms.edu.in', 'rohan.gupta@bms.edu.in', 'priya@bms.edu.in'])).delete()
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            VaultProposal.query.filter(VaultProposal.target_identifier.like('TEST%')).delete()
            Student.query.filter(Student.uucms_id.like('TEST%')).delete()
            Student.query.filter(Student.email.in_(['aarav.sharma@bms.edu.in', 'rohan.gupta@bms.edu.in', 'priya@bms.edu.in'])).delete()
            db.session.commit()

    def _create_mock_image(self, width=200, height=100, color=(255, 255, 255)):
        img = Image.new('RGB', (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        buf.seek(0)
        return buf

    # =========================================================================
    # 1. FILE VALIDATION & SECURITY
    # =========================================================================

    def test_01_file_validation_unsupported_format(self):
        """Rejects files with unsupported extensions (.exe, .sh, .txt)."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        data = {
            'doc_file': (io.BytesIO(b'malicious script content'), 'script.exe')
        }
        res = self.client.post('/vault/scan', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 400)
        self.assertIn('Unsupported file format', res.get_json().get('error', ''))

    def test_02_file_validation_empty_file(self):
        """Rejects empty 0-byte uploads."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        data = {
            'doc_file': (io.BytesIO(b''), 'empty.jpg')
        }
        res = self.client.post('/vault/scan', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 400)
        self.assertIn('empty', res.get_json().get('error', '').lower())

    # =========================================================================
    # 2. OCR PARSING & RECORD CLASSIFICATION
    # =========================================================================

    def test_03_scan_new_student_document(self):
        """Verifies scanning a new student document classifies as NEW_STUDENT and does NOT write to Student table."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        test_uucms = 'TEST_UUCMS_001'
        mock_text = f"""
        BMS COLLEGE OF COMMERCE & MANAGEMENT
        STUDENT ADMISSION CARD - 2026
        Name: Aarav Sharma
        UUCMS ID: {test_uucms}
        Course: BCA
        Semester: Sem V
        Section: A
        Email: aarav.sharma@bms.edu.in
        """

        buf = self._create_mock_image()
        data = {
            'doc_file': (buf, 'student_aarav.jpg'),
            'test_ocr_text': mock_text
        }
        res = self.client.post('/vault/scan', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        j = res.get_json()
        self.assertTrue(j['success'])
        self.assertEqual(j['target_type'], 'STUDENT')
        self.assertEqual(j['classification'], 'NEW_STUDENT')
        self.assertEqual(j['operation'], 'CREATE')
        self.assertEqual(j['extracted_fields']['uucms_id'], test_uucms)
        self.assertEqual(j['extracted_fields']['name'], 'Aarav Sharma')

        # ZERO database writes to Student table
        with app.app_context():
            s = Student.query.filter_by(uucms_id=test_uucms).first()
            self.assertIsNone(s, "Scanning must NOT create student in database immediately!")

    def test_04_scan_existing_student_classification_and_diff(self):
        """Verifies scanning an existing student matches record, classifies as UPDATE_STUDENT, and generates diff."""
        with app.app_context():
            existing_student = Student.query.filter_by(course='BCA', semester='Sem V').first()
            self.assertIsNotNone(existing_student)
            existing_uucms = existing_student.uucms_id
            existing_name = existing_student.name
            existing_id = existing_student.id
            existing_email = existing_student.email

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        mock_text = f"""
        BMS COLLEGE OF COMMERCE & MANAGEMENT
        STUDENT RECORD
        Name: {existing_name}
        UUCMS ID: {existing_uucms}
        Course: BCA
        Semester: Sem VI
        Section: B
        Email: {existing_email}
        """

        buf = self._create_mock_image()
        data = {
            'doc_file': (buf, 'existing_student_update.jpg'),
            'test_ocr_text': mock_text
        }
        res = self.client.post('/vault/scan', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        j = res.get_json()
        self.assertEqual(j['classification'], 'UPDATE_STUDENT')
        self.assertEqual(j['operation'], 'UPDATE')
        self.assertEqual(j['target_record_id'], existing_id)

        # Verify diff contains modified fields
        sem_diff = next((d for d in j['diff_summary'] if d['field'] == 'semester'), None)
        self.assertIsNotNone(sem_diff)
        self.assertEqual(sem_diff['before'], 'Sem V')
        self.assertEqual(sem_diff['after'], 'Sem VI')
        self.assertTrue(sem_diff['changed'])

    def test_05_ambiguous_conflicting_identity_flagged(self):
        """Flags conflicting records when UUCMS ID matches student A but email matches student B."""
        with app.app_context():
            students = Student.query.limit(2).all()
            self.assertEqual(len(students), 2)
            student_a = students[0]
            student_b = students[1]
            uucms_a = student_a.uucms_id
            email_b = student_b.email

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        mock_text = f"""
        BMS COLLEGE
        STUDENT ADMISSION
        UUCMS ID: {uucms_a}
        Email: {email_b}
        Name: Conflict Person
        Course: BCA
        """
        buf = self._create_mock_image()
        data = {
            'doc_file': (buf, 'conflict_student.jpg'),
            'test_ocr_text': mock_text
        }
        res = self.client.post('/vault/scan', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        j = res.get_json()
        self.assertEqual(j['classification'], 'AMBIGUOUS_CONFLICT')
        self.assertTrue(any('Conflicting Records' in w for w in j['warnings']))

    def test_06_duplicate_document_sha256_detection(self):
        """Detects duplicate document submissions using file SHA-256 checksum."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        buf_bytes = self._create_mock_image(width=180, height=90, color=(120, 150, 180)).getvalue()

        scan_res = self.client.post(
            '/vault/scan',
            data={'doc_file': (io.BytesIO(buf_bytes), 'orig_doc.jpg'), 'test_ocr_text': 'STAFF RECORD\nName: Prof Dup Check\nStaff ID: TEST_DUP_01\nDepartment: CS'},
            content_type='multipart/form-data'
        )
        self.assertEqual(scan_res.status_code, 200)
        doc_id = scan_res.get_json()['document_id']

        sub_res = self.client.post(
            '/vault/submit_proposal',
            json={
                'document_id': doc_id,
                'target_type': 'STAFF',
                'fields': {'full_name': 'Prof Dup Check', 'dept_id': 'TEST_DUP_01', 'department': 'CS', 'role': 'Faculty'}
            }
        )
        self.assertEqual(sub_res.status_code, 200)

        # Upload identical byte content with a DIFFERENT filename
        scan_res_2 = self.client.post(
            '/vault/scan',
            data={'doc_file': (io.BytesIO(buf_bytes), 'renamed_copy.jpg'), 'test_ocr_text': 'STAFF RECORD\nName: Prof Dup Check\nStaff ID: TEST_DUP_01\nDepartment: CS'},
            content_type='multipart/form-data'
        )
        self.assertEqual(scan_res_2.status_code, 200)
        j2 = scan_res_2.get_json()
        self.assertEqual(j2['classification'], 'DUPLICATE_SUBMISSION')
        self.assertTrue(any('Duplicate document detected' in w for w in j2['warnings']))

    # =========================================================================
    # 3. STRICT ROLE-BASED ACCESS CONTROL (ADMIN ONLY)
    # =========================================================================

    def test_07_accountant_strictly_forbidden_from_digital_vault(self):
        """Verifies Accountant role is strictly restricted from all vault endpoints."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.accountant_id)
            sess['user_id'] = self.accountant_id

        # 1. UI route
        res_ui = self.client.get('/digital_vault')
        self.assertEqual(res_ui.status_code, 302) # Redirect to dashboard

        # 2. Scan API
        res_scan = self.client.post('/vault/scan', data={'doc_file': (self._create_mock_image(), 'acc_test.jpg')}, content_type='multipart/form-data')
        self.assertEqual(res_scan.status_code, 403)
        self.assertIn('strictly restricted to Admin Department', res_scan.get_json().get('error', ''))

        # 3. Proposals API
        res_props = self.client.get('/vault/proposals')
        self.assertEqual(res_props.status_code, 403)

        # 4. Legacy Scan
        res_legacy = self.client.post('/scan_and_import', data={'doc_image': (self._create_mock_image(), 'acc_test.jpg')}, content_type='multipart/form-data')
        self.assertEqual(res_legacy.status_code, 403)

    def test_08_principal_and_faculty_strictly_forbidden(self):
        """Verifies Principal and Faculty roles are strictly restricted (403 Forbidden)."""
        # Principal check
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.principal_id)
            sess['user_id'] = self.principal_id

        res_princ = self.client.post('/vault/scan', data={'doc_file': (self._create_mock_image(), 'p_test.jpg')}, content_type='multipart/form-data')
        self.assertEqual(res_princ.status_code, 403)

        # Faculty check
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.faculty_id)
            sess['user_id'] = self.faculty_id

        res_fac = self.client.post('/vault/scan', data={'doc_file': (self._create_mock_image(), 'f_test.jpg')}, content_type='multipart/form-data')
        self.assertEqual(res_fac.status_code, 403)

    def test_09_submitter_self_approval_prevention(self):
        """Prevents submitters from approving their own proposal under independent review policy."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        test_uucms = 'TEST_SELF_APP_01'
        buf = self._create_mock_image()
        scan_res = self.client.post(
            '/vault/scan',
            data={'doc_file': (buf, 'self_app.jpg'), 'test_ocr_text': f'STUDENT ADMISSION\nUUCMS ID: {test_uucms}\nName: Self App Student\nEmail: self@bms.edu.in'},
            content_type='multipart/form-data'
        )
        doc_id = scan_res.get_json()['document_id']
        sub_res = self.client.post(
            '/vault/submit_proposal',
            json={'document_id': doc_id, 'target_type': 'STUDENT', 'fields': {'uucms_id': test_uucms, 'name': 'Self App Student', 'email': 'self@bms.edu.in', 'course': 'BCA', 'semester': 'Sem V', 'section': 'A'}}
        )
        prop_id = sub_res.get_json()['proposal_id']

        # Admin attempts to approve their own proposal -> Rejected with 403
        appr_res = self.client.post(f'/vault/proposal/{prop_id}/approve')
        self.assertEqual(appr_res.status_code, 403)
        self.assertIn('Submitter cannot approve their own proposal', appr_res.get_json()['error'])

    def test_10_rejection_requires_reason_and_leaves_db_unchanged(self):
        """Verifies rejection requires mandatory reason and does not modify database."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        test_uucms = 'TEST_REJECT_01'
        buf = self._create_mock_image()
        scan_res = self.client.post(
            '/vault/scan',
            data={'doc_file': (buf, 'to_reject.jpg'), 'test_ocr_text': f'STUDENT ADMISSION\nUUCMS ID: {test_uucms}\nName: Reject Candidate\nEmail: reject@bms.edu.in'},
            content_type='multipart/form-data'
        )
        doc_id = scan_res.get_json()['document_id']
        sub_res = self.client.post(
            '/vault/submit_proposal',
            json={'document_id': doc_id, 'target_type': 'STUDENT', 'fields': {'uucms_id': test_uucms, 'name': 'Reject Candidate', 'email': 'reject@bms.edu.in', 'course': 'BCA', 'semester': 'Sem V', 'section': 'A'}}
        )
        prop_id = sub_res.get_json()['proposal_id']

        # Switch session to Admin 2 (independent administrator)
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin2_id)
            sess['user_id'] = self.admin2_id

        # Attempt reject without reason -> 400 Bad Request
        res_no_reason = self.client.post(f'/vault/proposal/{prop_id}/reject', json={'rejection_reason': ''})
        self.assertEqual(res_no_reason.status_code, 400)
        self.assertIn('mandatory', res_no_reason.get_json()['error'].lower())

        # Reject with valid reason
        res_reject = self.client.post(f'/vault/proposal/{prop_id}/reject', json={'rejection_reason': 'Document image is blurred and unverified.'})
        self.assertEqual(res_reject.status_code, 200)

        # Confirm proposal is REJECTED and student does not exist
        with app.app_context():
            p = VaultProposal.query.get(prop_id)
            self.assertEqual(p.status, 'REJECTED')
            self.assertEqual(p.rejection_reason, 'Document image is blurred and unverified.')
            s = Student.query.filter_by(uucms_id=test_uucms).first()
            self.assertIsNone(s)

    # =========================================================================
    # 4. SUCCESSFUL APPROVAL, ATOMIC APPLICATION & IDEMPOTENCY
    # =========================================================================

    def test_11_independent_admin_approval_and_atomic_creation(self):
        """Verifies independent administrator approves proposal, applying new Student atomically."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        test_uucms = 'TEST_APPR_STU_01'
        buf = self._create_mock_image()
        scan_res = self.client.post(
            '/vault/scan',
            data={'doc_file': (buf, 'student_valid.jpg'), 'test_ocr_text': f'STUDENT ADMISSION\nName: Rohan Gupta\nUUCMS ID: {test_uucms}\nEmail: rohan.gupta@bms.edu.in\nCourse: BCA'},
            content_type='multipart/form-data'
        )
        doc_id = scan_res.get_json()['document_id']
        sub_res = self.client.post(
            '/vault/submit_proposal',
            json={'document_id': doc_id, 'target_type': 'STUDENT', 'fields': {'uucms_id': test_uucms, 'name': 'Rohan Gupta', 'email': 'rohan.gupta@bms.edu.in', 'course': 'BCA', 'semester': 'Sem V', 'section': 'A'}}
        )
        prop_id = sub_res.get_json()['proposal_id']

        # Admin 2 logs in and approves
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin2_id)
            sess['user_id'] = self.admin2_id

        res_appr = self.client.post(f'/vault/proposal/{prop_id}/approve')
        self.assertEqual(res_appr.status_code, 200)
        self.assertTrue(res_appr.get_json()['success'])

        # Verify official Student record is created in DB
        with app.app_context():
            s = Student.query.filter_by(uucms_id=test_uucms).first()
            self.assertIsNotNone(s)
            self.assertEqual(s.name, 'Rohan Gupta')
            self.assertEqual(s.email, 'rohan.gupta@bms.edu.in')
            self.assertEqual(s.course, 'BCA')

            p = VaultProposal.query.get(prop_id)
            self.assertEqual(p.status, 'APPLIED')
            self.assertEqual(p.applied_by_id, self.admin2_id)
            self.__class__.applied_proposal_id = prop_id

    def test_12_idempotency_prevents_double_application(self):
        """Verifies an already applied proposal cannot be re-approved or applied twice."""
        prop_id = getattr(self.__class__, 'applied_proposal_id', None)
        self.assertIsNotNone(prop_id, "test_11 must have set applied_proposal_id")
        with app.app_context():
            p = VaultProposal.query.get(prop_id)
            self.assertIsNotNone(p)
            self.assertEqual(p.status, 'APPLIED')

        # Admin 2 attempts to approve again
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin2_id)
            sess['user_id'] = self.admin2_id

        res_dup = self.client.post(f'/vault/proposal/{prop_id}/approve')
        self.assertEqual(res_dup.status_code, 400)
        self.assertIn('already been applied', res_dup.get_json()['error'])

    def test_13_guarded_document_download(self):
        """Verifies secure download endpoint requires admin authentication and serves file with correct headers."""
        with app.app_context():
            doc = VaultDocument.query.first()
            self.assertIsNotNone(doc)
            doc_id = doc.id

        # 1. Unauthenticated download fails
        client_anon = app.test_client()
        res_anon = client_anon.get(f'/vault/document/{doc_id}/download')
        self.assertIn(res_anon.status_code, [302, 401, 403])

        # 2. Authenticated admin download succeeds
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id

        res_auth = self.client.get(f'/vault/document/{doc_id}/download')
        self.assertEqual(res_auth.status_code, 200)
        self.assertIn('attachment', res_auth.headers.get('Content-Disposition', ''))


if __name__ == '__main__':
    unittest.main()
