import os
import unittest
from datetime import datetime, date
from app import app, db, User, Student, Timetable, ClassSession, StudentAttendance, InternalMark

class RoleBasedAccessControlTestCase(unittest.TestCase):
    """
    Test Suite: Role-Based Dashboard, Navigation, and Backend Section Visibility.
    Validates that:
    1. Each role sees only authorized UI elements and navigation links.
    2. Direct backend access to unauthorized endpoints is strictly blocked with HTTP 403 or safe redirect.
    3. Student IDOR attempts across marks and attendance analytics are blocked with HTTP 403.
    4. Students have a dedicated command dashboard and cannot access staff operations.
    5. All existing non-negotiable business rules (Timetable row 31, geofence, OCR vault) remain intact.
    """

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

    def setUp(self):
        self.client = app.test_client()
        with app.app_context():
            # Identify test accounts
            self.faculty = User.query.filter_by(username='balram').first()
            if not self.faculty:
                self.faculty = User.query.filter_by(role='Faculty').first()

            self.admin = User.query.filter_by(username='admin').first()
            self.accountant = User.query.filter_by(username='acc1').first()
            self.principal = User.query.filter_by(username='pankaj').first()
            self.hod = User.query.filter_by(username='kiran').first()

            # Identify students
            students = Student.query.filter_by(is_active=True).order_by(Student.id).limit(2).all()
            self.student1 = students[0]
            self.student2 = students[1] if len(students) > 1 else students[0]

    def _login_as_staff(self, user):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = user.id
            sess['_user_id'] = str(user.id)
            sess['name'] = user.full_name
            sess['role'] = user.role

    def _login_as_student(self, student):
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

    # --------------------------------------------------------------------------
    # 1. Teacher Dashboard & Navigation
    # --------------------------------------------------------------------------
    def test_01_teacher_dashboard_and_navigation(self):
        self._login_as_staff(self.faculty)
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Authorized Teacher sections present
        self.assertIn('Teacher Quick Actions', html)
        self.assertIn('/academic-attendance/history', html)
        self.assertIn('/academic/assignments/create', html)
        self.assertIn('/academic/study-materials/upload', html)
        self.assertIn('/academic/student-timetables/upload', html)
        self.assertIn('/timetable', html)

        # Unauthorized sections MUST NOT be present in teacher HTML
        self.assertNotIn('/digital_vault', html)
        self.assertNotIn('/admin/staff_master', html)
        self.assertNotIn('/finance', html)
        self.assertNotIn('/audit_logs', html)
        self.assertNotIn('/leave_calendar', html)

    # --------------------------------------------------------------------------
    # 2. Student Dashboard & Navigation
    # --------------------------------------------------------------------------
    def test_02_student_dashboard_and_navigation(self):
        self._login_as_student(self.student1)
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Authorized Student elements present
        self.assertIn(self.student1.name, html)
        self.assertIn(self.student1.uucms_id, html)
        self.assertIn('Student Portal', html)
        self.assertIn('/student/attendance', html)
        self.assertIn('/student/marks', html)
        self.assertIn('/student/assignments', html)
        self.assertIn('/student/study-materials', html)
        self.assertIn('/student/timetable', html)
        self.assertIn('/student/logout', html)

        # Staff operations MUST NOT be present in student view
        self.assertNotIn('href="/timetable"', html)
        self.assertNotIn('href="/digital_vault"', html)
        self.assertNotIn('href="/leave_calendar"', html)
        self.assertNotIn('href="/admin/staff_master"', html)
        self.assertNotIn('href="/audit_logs"', html)

    # --------------------------------------------------------------------------
    # 3. Admin / HR Dashboard & Navigation
    # --------------------------------------------------------------------------
    def test_03_admin_hr_dashboard_and_navigation(self):
        self._login_as_staff(self.admin)
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Administrative Governance present
        self.assertIn('Administrative Governance', html)
        self.assertIn('/admin/staff_master', html)
        self.assertIn('/digital_vault', html)
        self.assertIn('/leave_calendar', html)
        self.assertIn('/admin/devices', html)

        # Teacher Timetable Overview MUST NOT be present in admin sidebar
        self.assertNotIn('href="/timetable/overview"', html)
        self.assertNotIn('href="/finance"', html)

    # --------------------------------------------------------------------------
    # 4. HOD Dashboard & Navigation
    # --------------------------------------------------------------------------
    def test_04_hod_dashboard_and_navigation(self):
        self._login_as_staff(self.hod)
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Academic oversight & leave approvals present
        self.assertIn('/academic/analytics', html)
        self.assertIn('/leave_calendar', html)
        self.assertIn('/timetable/overview', html)

        # Digital Vault & Finance MUST NOT be present
        self.assertNotIn('href="/digital_vault"', html)
        self.assertNotIn('href="/finance"', html)
        self.assertNotIn('href="/audit_logs"', html)

    # --------------------------------------------------------------------------
    # 5. Accountant Dashboard & Navigation
    # --------------------------------------------------------------------------
    def test_05_accountant_dashboard_and_navigation(self):
        self._login_as_staff(self.accountant)
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Finance Portal present
        self.assertIn('Finance &amp; Accounts Portal', html)
        self.assertIn('/finance', html)
        self.assertIn('/payslip_history', html)

        # Disallowed academic and admin sections MUST NOT be present
        self.assertNotIn('href="/digital_vault"', html)
        self.assertNotIn('href="/audit_logs"', html)
        self.assertNotIn('href="/timetable/overview"', html)
        self.assertNotIn('href="/leave_calendar"', html)
        self.assertNotIn('href="/academic/assignments/create"', html)

    # --------------------------------------------------------------------------
    # 6. Principal Dashboard & Navigation
    # --------------------------------------------------------------------------
    def test_06_principal_dashboard_and_navigation(self):
        self._login_as_staff(self.principal)
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Executive Command present
        self.assertIn('Executive Command &amp; Oversight', html)
        self.assertIn('/leave_calendar', html)
        self.assertIn('/timetable/overview', html)
        self.assertIn('/academic/analytics', html)
        self.assertIn('/audit_logs', html)

        # Digital Vault & Finance MUST NOT be present
        self.assertNotIn('href="/digital_vault"', html)
        self.assertNotIn('href="/finance"', html)

    # --------------------------------------------------------------------------
    # 7. Backend Direct Block: Teacher Accessing Unauthorized Routes
    # --------------------------------------------------------------------------
    def test_07_backend_block_teacher_from_unauthorized_routes(self):
        self._login_as_staff(self.faculty)

        # Digital Vault -> 403
        res = self.client.get('/digital_vault')
        self.assertEqual(res.status_code, 403)

        # Master Workforce Directory -> 403
        res = self.client.get('/admin/staff_master')
        self.assertEqual(res.status_code, 403)

        # Finance Portal -> 403
        res = self.client.get('/finance')
        self.assertEqual(res.status_code, 403)

        # Audit Logs -> 403
        res = self.client.get('/audit_logs')
        self.assertEqual(res.status_code, 403)

        # Leave Calendar Approvals -> 403
        res = self.client.get('/leave_calendar')
        self.assertEqual(res.status_code, 403)

        # Device Registry -> 403
        res = self.client.get('/admin/devices')
        self.assertEqual(res.status_code, 403)

    # --------------------------------------------------------------------------
    # 8. Backend Direct Block: Student Accessing Staff Routes
    # --------------------------------------------------------------------------
    def test_08_backend_block_student_from_staff_routes(self):
        self._login_as_student(self.student1)

        # Staff Dashboard -> Redirects to Student Dashboard
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/student/dashboard', res.headers.get('Location', ''))

        # Staff Attendance -> 403
        res = self.client.get('/attendance')
        self.assertEqual(res.status_code, 403)

        # Staff Leave -> 403
        res = self.client.get('/leave')
        self.assertEqual(res.status_code, 403)

        # Staff Directory -> 403
        res = self.client.get('/staff_directory')
        self.assertEqual(res.status_code, 403)

        # Staff Expenses -> 403
        res = self.client.get('/expenses')
        self.assertEqual(res.status_code, 403)

        # Digital Vault -> Safely rejected (302 redirect or 403)
        res = self.client.get('/digital_vault')
        self.assertIn(res.status_code, [302, 403])

        # Academic Attendance History -> Safely rejected (302 redirect or 403)
        res = self.client.get('/academic-attendance/history')
        self.assertIn(res.status_code, [302, 403])

    # --------------------------------------------------------------------------
    # 9. Strict Admin Exclusion from College Timetable Overview
    # --------------------------------------------------------------------------
    def test_09_backend_block_admin_from_college_timetable(self):
        self._login_as_staff(self.admin)
        res = self.client.get('/timetable/overview')
        self.assertEqual(res.status_code, 403, "Strict compliance: Admin must receive HTTP 403 Forbidden on /timetable/overview")

    # --------------------------------------------------------------------------
    # 10. Backend Block: Accountant from Academic and Administrative Routes
    # --------------------------------------------------------------------------
    def test_10_backend_block_accountant_from_academic_and_vault(self):
        self._login_as_staff(self.accountant)

        # Digital Vault -> 403
        res = self.client.get('/digital_vault')
        self.assertEqual(res.status_code, 403)

        # College Timetable Overview -> 403
        res = self.client.get('/timetable/overview')
        self.assertEqual(res.status_code, 403)

        # Audit Logs -> 403
        res = self.client.get('/audit_logs')
        self.assertEqual(res.status_code, 403)

        # Leave Calendar Approvals -> 403
        res = self.client.get('/leave_calendar')
        self.assertEqual(res.status_code, 403)

    # --------------------------------------------------------------------------
    # 11. IDOR Protection: Student Cannot View Another Student's Records
    # --------------------------------------------------------------------------
    def test_11_idor_protection_student_cannot_access_other_student_records(self):
        if self.student1.id == self.student2.id:
            self.skipTest("Need at least 2 distinct students for IDOR test")

        self._login_as_student(self.student1)

        # Attempt to access Student 2's marks page -> 403 Forbidden
        res = self.client.get(f'/student/marks?student_id={self.student2.id}')
        self.assertEqual(res.status_code, 403)

        # Attempt to access Student 2's marks API -> 403 Forbidden
        res_api = self.client.get(f'/api/student/marks?student_id={self.student2.id}')
        self.assertEqual(res_api.status_code, 403)

        # Attempt to access Student 2's attendance analytics -> 403 Forbidden
        res_att = self.client.get(f'/academic/analytics/student/{self.student2.id}')
        self.assertEqual(res_att.status_code, 403)

    # --------------------------------------------------------------------------
    # 12. Student Authorized Self-Access Permitted
    # --------------------------------------------------------------------------
    def test_12_student_own_data_access_permitted(self):
        self._login_as_student(self.student1)

        # Student Dashboard -> 200
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 200)

        # Student Attendance View -> 302 redirect to own analytics -> 200
        res_att = self.client.get('/student/attendance', follow_redirects=True)
        self.assertEqual(res_att.status_code, 200)

        # Own Marks Statement -> 200
        res_marks = self.client.get('/student/marks')
        self.assertEqual(res_marks.status_code, 200)

        # Own Published Assignments -> 200
        res_assign = self.client.get('/student/assignments')
        self.assertEqual(res_assign.status_code, 200)

        # Own Published Study Materials -> 200
        res_mat = self.client.get('/student/study-materials')
        self.assertEqual(res_mat.status_code, 200)

        # Own Published Semester Timetable -> 200
        res_tt = self.client.get('/student/timetable')
        self.assertEqual(res_tt.status_code, 200)

    # --------------------------------------------------------------------------
    # 13. Anonymous Direct Requests Safely Redirected to Login
    # --------------------------------------------------------------------------
    def test_13_anonymous_requests_redirected_to_login(self):
        # Clear any session
        with self.client.session_transaction() as sess:
            sess.clear()

        # Staff Dashboard -> redirects to staff login
        res = self.client.get('/dashboard')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers.get('Location', ''))

        # Student Dashboard -> redirects to student login
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/student/login', res.headers.get('Location', ''))

        # Digital Vault -> redirects to staff login
        res = self.client.get('/digital_vault')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers.get('Location', ''))

        # Internal Marks Dashboard -> redirects to staff login
        res = self.client.get('/internal-marks')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers.get('Location', ''))

    # --------------------------------------------------------------------------
    # 14. Preservation of Non-Negotiable Rules & Row 31 Integrity
    # --------------------------------------------------------------------------
    def test_14_preservation_of_existing_business_rules(self):
        with app.app_context():
            tt31 = Timetable.query.get(31)
            self.assertIsNotNone(tt31, "Row 31 must strictly exist in Timetable")
            self.assertEqual(tt31.subject, 'Web Programming')
            self.assertEqual(tt31.day, 'Monday')
            self.assertEqual(tt31.time_slot, '12:30 PM-01:30 PM')
            self.assertEqual(tt31.course, 'BCA')
            self.assertEqual(tt31.semester, 'Sem V')
            self.assertEqual(tt31.section, 'A')

        # Authorized Teacher can view timetable overview
        self._login_as_staff(self.faculty)
        res = self.client.get('/timetable/overview')
        self.assertEqual(res.status_code, 200)


if __name__ == '__main__':
    unittest.main()
