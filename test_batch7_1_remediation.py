import os
import unittest
from datetime import datetime, date
from io import BytesIO
from app import app, db, User, Leave, ExpenseClaim

# Minimal valid 1x1 PNG bytes
VALID_PNG_BYTES = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'

class Batch71RemediationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

    def setUp(self):
        with app.app_context():
            self.faculty = User.query.filter_by(role='Faculty').first()
            if not self.faculty:
                self.faculty = User.query.first()
            self.faculty2 = User.query.filter(User.role == 'Faculty', User.id != self.faculty.id).first()
            self.hr = User.query.filter_by(role='HR').first()
            self.accountant = User.query.filter_by(role='Accountant').first()
            self.principal = User.query.filter_by(role='Principal').first()
            self.admin = User.query.filter_by(role='admin').first()

    def login_as(self, user):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['role'] = user.role
            sess['name'] = user.full_name

    # 1. PAYSLIP AND ID-CARD AUTHORIZATION
    def test_01_payslip_unauthenticated_blocked(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        resp = self.client.get(f'/generate_payslip/{self.faculty.id}')
        self.assertIn(resp.status_code, [302, 401])

    def test_02_payslip_self_service_allowed(self):
        self.login_as(self.faculty)
        resp = self.client.get(f'/generate_payslip/{self.faculty.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('Content-Type'), 'application/pdf')

    def test_03_payslip_other_faculty_denied(self):
        if self.faculty2:
            self.login_as(self.faculty2)
            resp = self.client.get(f'/generate_payslip/{self.faculty.id}')
            self.assertEqual(resp.status_code, 403)

    def test_04_payslip_admin_and_hr_allowed(self):
        if self.hr:
            self.login_as(self.hr)
            resp = self.client.get(f'/generate_payslip/{self.faculty.id}')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get('Content-Type'), 'application/pdf')

    def test_05_id_card_unauthenticated_blocked(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        resp = self.client.get(f'/generate_id/{self.faculty.id}')
        self.assertIn(resp.status_code, [302, 401])

    def test_06_id_card_self_service_allowed(self):
        self.login_as(self.faculty)
        resp = self.client.get(f'/generate_id/{self.faculty.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('Content-Type'), 'application/pdf')

    def test_07_id_card_other_faculty_denied(self):
        if self.faculty2:
            self.login_as(self.faculty2)
            resp = self.client.get(f'/generate_id/{self.faculty.id}')
            self.assertEqual(resp.status_code, 403)

    # 2. SERVER-SIDE LEAVE QUOTA & VALIDATION
    def test_08_leave_invalid_date_rejected(self):
        self.login_as(self.faculty)
        resp = self.client.post('/leave', data={
            'date': 'invalid-date-format',
            'reason': 'Valid reason for test'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('Invalid date format', html)

    def test_09_leave_empty_fields_rejected(self):
        self.login_as(self.faculty)
        resp = self.client.post('/leave', data={
            'date': '',
            'reason': '   '
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('Please provide both effective date and reason', html)

    def test_10_leave_quota_enforced_server_side(self):
        self.login_as(self.faculty)
        with app.app_context():
            existing_count = Leave.query.filter_by(user_id=self.faculty.id, status='Approved').count()
            test_leaves = []
            for i in range(20 - existing_count):
                l = Leave(user_id=self.faculty.id, date=f'2026-01-{i+1:02d}', reason='Quota test fill', status='Approved')
                db.session.add(l)
                test_leaves.append(l)
            db.session.commit()

            try:
                resp = self.client.post('/leave', data={
                    'date': '2026-12-31',
                    'reason': 'Attempt past quota'
                }, follow_redirects=True)
                self.assertEqual(resp.status_code, 200)
                html = resp.data.decode('utf-8')
                self.assertIn('quota (20 days) has been exhausted', html)
            finally:
                for l in test_leaves:
                    db.session.delete(l)
                db.session.commit()

    # 3. PROFILE PHOTO UPLOAD
    def test_11_upload_photo_unauthorized_blocked(self):
        if self.faculty2:
            self.login_as(self.faculty2)
            resp = self.client.post(f'/upload_photo/{self.faculty.id}', data={
                'profile_pic': (BytesIO(VALID_PNG_BYTES), 'test.jpg')
            })
            self.assertEqual(resp.status_code, 403)

    def test_12_upload_photo_dual_field_support(self):
        self.login_as(self.faculty)
        orig_pic = self.faculty.profile_pic
        try:
            # Test field name 'profile_pic'
            resp = self.client.post(f'/upload_photo/{self.faculty.id}', data={
                'profile_pic': (BytesIO(VALID_PNG_BYTES), 'test_pic.png')
            }, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)

            # Test field name 'photo' fallback
            resp2 = self.client.post(f'/upload_photo/{self.faculty.id}', data={
                'photo': (BytesIO(VALID_PNG_BYTES), 'test_photo.png')
            }, follow_redirects=True)
            self.assertEqual(resp2.status_code, 200)
        finally:
            with app.app_context():
                u = User.query.get(self.faculty.id)
                if u:
                    u.profile_pic = orig_pic
                    db.session.commit()

    # 4. ACCOUNTANT EXPENSE FINALIZATION
    def test_13_expense_acc_approve_requires_hr_approval_first(self):
        if self.accountant:
            with app.app_context():
                claim = ExpenseClaim(user_id=self.faculty.id, category='Test', amount=100.0, description='Test', status='Pending')
                db.session.add(claim)
                db.session.commit()
                claim_id = claim.id

            try:
                self.login_as(self.accountant)
                resp = self.client.get(f'/approve_expense/{claim_id}/acc_approve', follow_redirects=True)
                self.assertEqual(resp.status_code, 200)
                with app.app_context():
                    c = ExpenseClaim.query.get(claim_id)
                    self.assertEqual(c.status, 'Pending')
            finally:
                with app.app_context():
                    c = ExpenseClaim.query.get(claim_id)
                    if c:
                        db.session.delete(c)
                        db.session.commit()

    def test_14_expense_accountant_can_finalize_hr_approved(self):
        if self.accountant:
            with app.app_context():
                claim = ExpenseClaim(user_id=self.faculty.id, category='Travel', amount=250.0, description='Cab', status='Approved by HR')
                db.session.add(claim)
                db.session.commit()
                claim_id = claim.id

            try:
                self.login_as(self.accountant)
                # Verify template shows Finalize Payment button
                page_resp = self.client.get('/expenses')
                self.assertIn('Finalize Payment', page_resp.data.decode('utf-8'))

                # Execute finalization
                resp = self.client.get(f'/approve_expense/{claim_id}/acc_approve', follow_redirects=True)
                self.assertEqual(resp.status_code, 200)
                with app.app_context():
                    c = ExpenseClaim.query.get(claim_id)
                    self.assertEqual(c.status, 'Finalized')
                    self.assertIsNotNone(c.payment_date)
            finally:
                with app.app_context():
                    c = ExpenseClaim.query.get(claim_id)
                    if c:
                        db.session.delete(c)
                        db.session.commit()

    # 5. LEAVE CALENDAR MONTH BOUNDARY LOGIC
    def test_15_leave_calendar_month_boundary_and_days(self):
        if self.principal:
            self.login_as(self.principal)
            resp = self.client.get('/leave_calendar')
            self.assertEqual(resp.status_code, 200)
            html = resp.data.decode('utf-8')
            import calendar
            now = date.today()
            expected_days = calendar.monthrange(now.year, now.month)[1]
            self.assertIn(f'>{expected_days}</strong>', html)
            if expected_days < 31:
                self.assertNotIn('>31</strong>', html)

if __name__ == '__main__':
    unittest.main()
