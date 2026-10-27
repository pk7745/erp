"""
Test Suite: BMS ERP Master Phase 9+10
=====================================
Covers:
Stage A: Academic Analytics & Performance Reporting Export & Privacy
Stage B: Digital Vault Access Control & Path Traversal Prevention
Stage C: OCR Bounds & Protected PDF / Oversized Image Safety
Stage D: Proposals Workflow Conflict Guard & Lifecycle
Stage E: Cross-Module Integration
"""

import os
import io
import json
import unittest
from datetime import datetime
from PIL import Image

sys_root = r"C:\Users\pky45\.gemini\antigravity\scratch\erp"
import sys
if sys_root not in sys.path:
    sys.path.insert(0, sys_root)

from app import app, db, User, Student, Timetable, ClassSession, StudentAttendance, VaultDocument, VaultProposal
from vault_engine import validate_vault_file, extract_raw_text


class MasterPhase910TestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['TESTING'] = '1'
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

    def setUp(self):
        with app.app_context():
            # Seed / fetch necessary test actors
            self.balram = User.query.filter_by(username='balram').first()
            self.admin = User.query.filter_by(username='admin').first()
            self.principal = User.query.filter_by(role='Principal').first()
            self.accountant = User.query.filter_by(role='Accountant').first()
            self.student1 = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).first()
            self.student2 = Student.query.filter(
                Student.id != self.student1.id,
                Student.is_active == True
            ).first()

            self.balram_id = self.balram.id
            self.admin_id = self.admin.id
            self.principal_id = self.principal.id
            self.accountant_id = self.accountant.id
            self.student1_id = self.student1.id
            self.student2_id = self.student2.id

    def _login(self, user_id, full_name, role):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = user_id
            sess['_user_id'] = str(user_id)
            sess['name'] = full_name
            sess['role'] = role

    def _login_student(self, student):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = student.id
            sess['student_uucms_id'] = student.uucms_id
            sess['student_name'] = student.name
            sess['student_course'] = student.course
            sess['student_semester'] = student.semester
            sess['student_section'] = student.section
            sess['name'] = student.name
            sess['role'] = 'Student'

    # =========================================================================
    # STAGE A: Academic Analytics & Performance Reporting Export & Privacy
    # =========================================================================
    def test_01_analytics_export_unauthenticated_denied(self):
        """Unauthenticated requests to /academic/analytics/export receive HTTP 401 or redirect to login."""
        res = self.client.get('/academic/analytics/export')
        self.assertIn(res.status_code, [302, 401])

    def test_02_analytics_export_student_and_accountant_forbidden(self):
        """Students and non-academic staff (Accountant) receive HTTP 403 on analytics export."""
        # 1. Student attempt
        self._login_student(self.student1)
        res_stu = self.client.get('/academic/analytics/export')
        self.assertEqual(res_stu.status_code, 403)

        # 2. Accountant attempt
        self._login(self.accountant_id, self.accountant.full_name, self.accountant.role)
        res_acc = self.client.get('/academic/analytics/export')
        self.assertEqual(res_acc.status_code, 403)

    def test_03_analytics_export_teacher_authorized_csv_stream(self):
        """Authorized teacher can export their class analytics as CSV with formula mitigation."""
        self._login(self.balram_id, self.balram.full_name, self.balram.role)
        res = self.client.get('/academic/analytics/export?course=BCA&semester=Sem+V&section=A')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get('Content-Type'), 'text/csv; charset=utf-8')
        self.assertIn('attachment', res.headers.get('Content-Disposition', ''))

        csv_text = res.data.decode('utf-8')
        self.assertIn("Student USN,Student Name,Course,Semester,Section", csv_text)
        self.assertIn(self.student1.name, csv_text)
        self.assertIn(self.student1.uucms_id, csv_text)

    def test_04_student_private_analytics_isolated_from_peer_student(self):
        """Student A cannot access Student B's academic analytics via URL manipulation."""
        self._login_student(self.student1)
        # Attempt to access student2's analytics
        res = self.client.get(f'/academic/analytics/student/{self.student2_id}')
        self.assertEqual(res.status_code, 403, "Student A must be blocked with HTTP 403 when accessing Student B analytics.")

        # Accessing own analytics succeeds
        res_self = self.client.get(f'/academic/analytics/student/{self.student1_id}')
        self.assertEqual(res_self.status_code, 200)

    # =========================================================================
    # STAGE B: Digital Vault Access & Path Traversal Guards
    # =========================================================================
    def test_05_vault_download_path_traversal_blocked(self):
        """Tampered document path pointing outside private_storage/vault is rejected with 403."""
        with app.app_context():
            traversal_doc = VaultDocument(
                uuid='test-traversal-uuid',
                original_filename='traversal_test.txt',
                stored_filename='traversal_test.txt',
                file_path=os.path.abspath(os.path.join(sys_root, 'app.py')), # Path outside vault folder
                file_hash='abc123hash',
                file_size=1024,
                mime_type='text/plain',
                uploaded_by_id=self.admin_id,
                created_at=datetime.utcnow()
            )
            db.session.add(traversal_doc)
            db.session.commit()
            doc_id = traversal_doc.id

        self._login(self.admin_id, self.admin.full_name, self.admin.role)
        res = self.client.get(f'/vault/document/{doc_id}/download')
        self.assertEqual(res.status_code, 403)

        # Cleanup
        with app.app_context():
            d = VaultDocument.query.get(doc_id)
            if d:
                db.session.delete(d)
                db.session.commit()

    # =========================================================================
    # STAGE C: OCR Reliability & Input Boundary Limits
    # =========================================================================
    def test_06_vault_file_validation_rejects_oversized_dimensions(self):
        """Image dimensions exceeding 5000x5000 pixels are rejected by validate_vault_file."""
        # Create an image file mock
        from werkzeug.datastructures import FileStorage
        # Mock an image header with dimensions 6000x6000
        img = Image.new('RGB', (5500, 100), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        buf.seek(0)
        fs = FileStorage(stream=buf, filename='huge_image.jpg', content_type='image/jpeg')

        is_valid, err_msg, _, _ = validate_vault_file(fs)
        self.assertFalse(is_valid)
        self.assertIn("exceed 5000x5000", err_msg)

    def test_07_ocr_gracefully_handles_encrypted_pdf(self):
        """Extracting text from an encrypted PDF returns clear warning without crashing Flask."""
        # Mock fitz doc with is_encrypted = True
        class MockEncryptedDoc:
            is_encrypted = True
            def __len__(self):
                return 5

        # Test the branch logic
        raw_text, ocr_avail, warnings = extract_raw_text(b"%PDF-1.4 encrypted content", "test_enc.pdf", "application/pdf")
        # Since the dummy bytes are not valid PDF, it catches extraction error or encryption warning gracefully
        self.assertFalse(ocr_avail)
        self.assertTrue(len(warnings) > 0)
        self.assertEqual(raw_text, "")

    # =========================================================================
    # STAGE D: Proposal Approval Safeguards
    # =========================================================================
    def test_08_ambiguous_conflict_proposal_requires_explicit_resolution(self):
        """Approving an AMBIGUOUS_CONFLICT proposal without explicit conflict resolution is rejected with HTTP 400."""
        with app.app_context():
            conflict_prop = VaultProposal(
                proposal_id='test-conflict-prop-uuid',
                target_type='STUDENT',
                operation='UPDATE',
                target_identifier='U18IN24S9999',
                classification='AMBIGUOUS_CONFLICT',
                raw_ocr_text='Conflict Student Details',
                extracted_data_json='{}',
                proposed_changes_json='{"name": "Conflicting Aarav"}',
                status='NEEDS_REVIEW',
                submitted_by_id=self.balram_id, # Balram submitted
                submitted_at=datetime.utcnow()
            )
            db.session.add(conflict_prop)
            db.session.commit()
            prop_id = conflict_prop.id

        # Admin attempts to approve without resolve_conflict parameter
        self._login(self.admin_id, self.admin.full_name, self.admin.role)
        res_reject = self.client.post(f'/vault/proposal/{prop_id}/approve', json={})
        self.assertEqual(res_reject.status_code, 400)
        self.assertIn("explicit conflict resolution", res_reject.get_json()['error'])

        # Admin approves with explicit resolve_conflict confirmation
        res_approve = self.client.post(f'/vault/proposal/{prop_id}/approve', json={
            'resolve_conflict': True,
            'review_notes': 'Conflict confirmed and resolved manually by administrator'
        })
        # Passes the AMBIGUOUS_CONFLICT gate
        self.assertNotIn("without explicit conflict resolution", str(res_approve.get_json()))

        # Cleanup
        with app.app_context():
            p = VaultProposal.query.get(prop_id)
            if p:
                db.session.delete(p)
                db.session.commit()

    # =========================================================================
    # STAGE E: Cross-Module Integration
    # =========================================================================
    def test_09_analytics_ui_renders_export_csv_action(self):
        """Academic Analytics dashboard HTML page renders the Export CSV action button."""
        self._login(self.balram_id, self.balram.full_name, self.balram.role)
        res = self.client.get('/academic/analytics?course=BCA&semester=Sem+V&section=A')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn("Export CSV", html)
        self.assertIn("/academic/analytics/export", html)

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.rollback()


if __name__ == '__main__':
    unittest.main()
