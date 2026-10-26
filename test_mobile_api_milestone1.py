import unittest
import os
import json

os.environ['TESTING'] = '1'
from app import app, db, User, Student, Timetable

class MobileApiMilestone1TestCase(unittest.TestCase):
    """
    Integration & Unit Test Suite for Native Android Mobile App API Gateway — Milestone 1.
    Tests:
    1. Staff Authentication (/api/auth/staff-login)
    2. Student Authentication (/api/auth/student-login)
    3. Session Identity Verification (/api/auth/me)
    4. Secure Logout (/api/auth/logout)
    5. Role-Specific Mobile Dashboard Summaries (/api/dashboard/summary)
    """

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

    def setUp(self):
        self.client = app.test_client()
        with app.app_context():
            self.admin_user = User.query.filter_by(username='admin').first()
            self.teacher_user = User.query.filter_by(username='balram').first()
            self.student_user = Student.query.filter_by(uucms_id='U18IN24S0004').first()

    # -------------------------------------------------------------------------
    # 1. STAFF AUTHENTICATION
    # -------------------------------------------------------------------------
    def test_01_staff_login_success(self):
        res = self.client.post('/api/auth/staff-login', json={
            'username': 'admin',
            'password': 'bms123'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['account_type'], 'STAFF')
        self.assertEqual(data['user']['username'], 'admin')
        self.assertIn('role', data['user'])

    def test_02_staff_login_invalid_password(self):
        res = self.client.post('/api/auth/staff-login', json={
            'username': 'admin',
            'password': 'WrongPassword999!'
        })
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid', data['error'])

    def test_03_staff_login_missing_fields(self):
        res = self.client.post('/api/auth/staff-login', json={
            'username': 'admin'
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data['success'])

    # -------------------------------------------------------------------------
    # 2. STUDENT AUTHENTICATION
    # -------------------------------------------------------------------------
    def test_04_student_login_success(self):
        res = self.client.post('/api/auth/student-login', json={
            'uucms_id': self.student_user.uucms_id,
            'password': self.student_user.raw_password
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['account_type'], 'STUDENT')
        self.assertEqual(data['student']['uucms_id'], self.student_user.uucms_id)
        self.assertEqual(data['student']['role'], 'Student')
        self.assertEqual(data['student']['semester'], self.student_user.semester)

    def test_05_student_login_invalid_password(self):
        res = self.client.post('/api/auth/student-login', json={
            'uucms_id': self.student_user.uucms_id,
            'password': 'IncorrectPassword!'
        })
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data['success'])

    def test_06_student_login_nonexistent_uucms(self):
        res = self.client.post('/api/auth/student-login', json={
            'uucms_id': 'NONEXISTENT_99999',
            'password': 'SomePassword!'
        })
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data['success'])

    # -------------------------------------------------------------------------
    # 3. IDENTITY VERIFICATION (/api/auth/me) & LOGOUT
    # -------------------------------------------------------------------------
    def test_07_auth_me_unauthenticated(self):
        res = self.client.get('/api/auth/me')
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data['authenticated'])

    def test_08_auth_me_staff_session(self):
        # Log in as staff
        self.client.post('/api/auth/staff-login', json={
            'username': 'balram',
            'password': 'bms123'
        })
        res = self.client.get('/api/auth/me')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['authenticated'])
        self.assertEqual(data['account_type'], 'STAFF')
        self.assertEqual(data['user']['username'], 'balram')
        self.assertEqual(data['user']['role'], 'Faculty')

    def test_09_auth_me_student_session(self):
        # Log in as student
        self.client.post('/api/auth/student-login', json={
            'uucms_id': self.student_user.uucms_id,
            'password': self.student_user.raw_password
        })
        res = self.client.get('/api/auth/me')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['authenticated'])
        self.assertEqual(data['account_type'], 'STUDENT')
        self.assertEqual(data['student']['name'], self.student_user.name)

    def test_10_auth_logout_clears_session(self):
        # Log in first
        self.client.post('/api/auth/staff-login', json={
            'username': 'admin',
            'password': 'bms123'
        })
        # Verify authenticated
        me_res = self.client.get('/api/auth/me')
        self.assertEqual(me_res.status_code, 200)

        # Logout
        logout_res = self.client.post('/api/auth/logout')
        self.assertEqual(logout_res.status_code, 200)
        self.assertTrue(logout_res.get_json()['success'])

        # Verify session cleared
        after_res = self.client.get('/api/auth/me')
        self.assertEqual(after_res.status_code, 401)

    # -------------------------------------------------------------------------
    # 4. ROLE-SPECIFIC DASHBOARD SUMMARIES (/api/dashboard/summary)
    # -------------------------------------------------------------------------
    def test_11_dashboard_summary_unauthorized(self):
        res = self.client.get('/api/dashboard/summary')
        self.assertEqual(res.status_code, 401)

    def test_12_dashboard_summary_student(self):
        # Log in as student
        self.client.post('/api/auth/student-login', json={
            'uucms_id': self.student_user.uucms_id,
            'password': self.student_user.raw_password
        })
        res = self.client.get('/api/dashboard/summary')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['account_type'], 'STUDENT')
        self.assertEqual(data['role'], 'Student')
        self.assertEqual(data['semester'], self.student_user.semester)
        self.assertIn('overall_attendance_pct', data)
        self.assertIn('conducted', data)
        self.assertIn('attended', data)
        self.assertIn('risk_level', data)
        self.assertIn('today_classes', data)

    def test_13_dashboard_summary_teacher(self):
        # Log in as faculty (balram)
        self.client.post('/api/auth/staff-login', json={
            'username': 'balram',
            'password': 'bms123'
        })
        res = self.client.get('/api/dashboard/summary')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['account_type'], 'STAFF')
        self.assertEqual(data['role'], 'Faculty')
        self.assertIn('today_classes', data)
        self.assertIn('active_assignments_count', data)
        self.assertIn('attendance_status', data)

    def test_14_dashboard_summary_admin(self):
        # Log in as admin
        self.client.post('/api/auth/staff-login', json={
            'username': 'admin',
            'password': 'bms123'
        })
        res = self.client.get('/api/dashboard/summary')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['account_type'], 'STAFF')
        self.assertIn('total_students', data)
        self.assertIn('total_staff', data)
        self.assertIn('campus_geofence_radius', data)


if __name__ == '__main__':
    unittest.main()
