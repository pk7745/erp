import unittest
import sys
import os
import time
from datetime import datetime, date

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"C:\Users\pky45\.gemini\antigravity\scratch\erp")
from app import app, db, User, Student, Timetable, ClassSession, StudentAttendance, StudentAttendanceAudit, NotificationLog, get_ist_time

class AcademicAttendanceWorkflowTests(unittest.TestCase):
    """Production test suite for Student Academic Attendance - Take Attendance Workflow"""

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

    def login_as(self, username='balram', password='bms123'):
        with app.app_context():
            u = User.query.filter_by(username=username).first()
            if u:
                from werkzeug.security import generate_password_hash
                u.password = generate_password_hash(password)
                db.session.commit()
        return self.client.post('/login', data=dict(
            username=username,
            password=password
        ), follow_redirects=True)

    def test_01_unauthenticated_access_denied(self):
        """Unauthenticated user must be redirected to login"""
        with app.app_context():
            tt = Timetable.query.filter_by(course='BCA', semester='Sem V', section='A').first()
            self.assertIsNotNone(tt, "Sem V timetable entry should exist")
            tt_id = tt.id

        res = self.client.get(f'/academic-attendance/take/{tt_id}', follow_redirects=False)
        self.assertIn(res.status_code, [302, 401], "Unauthenticated GET should redirect to login")
        self.assertIn('/login', res.headers.get('Location', ''))

        res_post = self.client.post(f'/academic-attendance/take/{tt_id}', data={}, follow_redirects=False)
        self.assertIn(res_post.status_code, [302, 401], "Unauthenticated POST should redirect to login")

        res_hist = self.client.get('/academic-attendance/history', follow_redirects=False)
        self.assertIn(res_hist.status_code, [302, 401])

    def test_02_teacher_authorization_restrictions(self):
        """Teacher cannot take attendance for another teacher's private timetable entry"""
        with app.app_context():
            shivani = User.query.filter_by(username='shivani').first()
            balram = User.query.filter_by(username='balram').first()
            self.assertIsNotNone(shivani)
            self.assertIsNotNone(balram)
            
            tt_shivani = Timetable.query.filter_by(user_id=shivani.id, course='BCA', semester='Sem V').first()
            self.assertIsNotNone(tt_shivani)
            tt_shivani_id = tt_shivani.id

        # Log in as Balram
        self.login_as(username='balram', password='bms123')

        # Balram attempts to access Shivani's class
        res = self.client.get(f'/academic-attendance/take/{tt_shivani_id}', follow_redirects=True)
        self.assertIn("not authorized", res.get_data(as_text=True).lower())

        # Balram attempts to POST attendance for Shivani's class
        res_post = self.client.post(f'/academic-attendance/take/{tt_shivani_id}', data={
            'actual_subject': 'Malicious Override',
            'student_ids': ['1', '2']
        }, follow_redirects=True)
        self.assertIn("not authorized", res_post.get_data(as_text=True).lower())

    def test_03_roster_loading_and_class_details(self):
        """Authorized teacher sees all 17 active BCA Sem V Sec A students and session details"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            tt_balram = Timetable.query.filter_by(user_id=balram.id, course='BCA', semester='Sem V').first()
            self.assertIsNotNone(tt_balram)
            tt_id = tt_balram.id
            sched_subj = tt_balram.subject
            room_no = tt_balram.room_no
            today = get_ist_time().date()
            existing = ClassSession.query.filter_by(timetable_id=tt_id, date=today).first()
            if existing:
                db.session.delete(existing)
                db.session.commit()

        self.login_as(username='balram', password='bms123')
        res = self.client.get(f'/academic-attendance/take/{tt_id}')
        html = res.get_data(as_text=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(sched_subj, html)
        self.assertIn(room_no, html)
        self.assertIn("BCA", html)
        self.assertIn("Sem V", html)
        self.assertIn("Aadya", html)
        self.assertIn("U18IN24S0001", html)
        self.assertIn("Aishwarya", html)
        self.assertIn("U18IN24S0004", html)
        self.assertIn("Total: 17", html)

    def test_04_successful_attendance_submission_and_override(self):
        """Teacher submits attendance with Actual Subject override; verifies transactional persistence"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            balram_id = balram.id
            tt = Timetable.query.filter_by(user_id=balram.id, course='BCA', semester='Sem V').order_by(Timetable.id).first()
            tt_id = tt.id
            scheduled_subject = tt.subject
            today = get_ist_time().date()

            # Clean any existing ClassSession for today on this slot to test fresh submission
            existing = ClassSession.query.filter_by(timetable_id=tt_id, date=today).first()
            if existing:
                db.session.delete(existing)
                db.session.commit()

            students = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).all()
            self.assertEqual(len(students), 17)
            student_ids = [s.id for s in students]

        self.login_as(username='balram', password='bms123')

        # Mark 15 Present and 2 Absent
        post_data = {
            'actual_subject': f"{scheduled_subject} - Advanced Module",
            'remarks': 'Unit 4 Hands-on Demonstration',
            'student_ids': [str(sid) for sid in student_ids]
        }
        absent_ids = [student_ids[2], student_ids[5]]
        for sid in student_ids:
            if sid in absent_ids:
                post_data[f'status_{sid}'] = 'Absent'
            else:
                post_data[f'status_{sid}'] = 'Present'

        res = self.client.post(f'/academic-attendance/take/{tt_id}', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("Attendance submitted successfully", html)
        self.assertIn("15", html)
        self.assertIn("2", html)

        # Allow async worker thread to complete
        time.sleep(0.5)

        # Verify Database Records directly
        with app.app_context():
            cs = ClassSession.query.filter_by(timetable_id=tt_id, date=today).first()
            self.assertIsNotNone(cs, "ClassSession must be persisted")
            self.assertEqual(cs.scheduled_subject, scheduled_subject)
            self.assertEqual(cs.actual_subject, f"{scheduled_subject} - Advanced Module")
            self.assertEqual(cs.status, 'COMPLETED')
            self.assertEqual(cs.actual_faculty_id, balram_id)
            self.assertEqual(cs.room_no, tt.room_no)

            attendances = StudentAttendance.query.filter_by(class_session_id=cs.id).all()
            self.assertEqual(len(attendances), 17, "Exactly 17 student attendance records must exist")

            p_cnt = sum(1 for a in attendances if a.status == 'Present')
            a_cnt = sum(1 for a in attendances if a.status == 'Absent')
            self.assertEqual(p_cnt, 15)
            self.assertEqual(a_cnt, 2)

            # Timetable status updated
            tt_reloaded = Timetable.query.get(tt_id)
            self.assertEqual(tt_reloaded.status, 'held')
            # Historical check: original timetable subject was NOT modified
            self.assertEqual(tt_reloaded.subject, scheduled_subject)

    def test_05_duplicate_submission_prevented(self):
        """Duplicate submission for the same timetable and date must be blocked gracefully"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            tt = Timetable.query.filter_by(user_id=balram.id, course='BCA', semester='Sem V').order_by(Timetable.id).first()
            tt_id = tt.id
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(timetable_id=tt_id, date=today).first()
            self.assertIsNotNone(cs, "Pre-existing session must exist from previous test")

        self.login_as(username='balram', password='bms123')
        # Attempt to POST again
        res = self.client.post(f'/academic-attendance/take/{tt_id}', data={
            'actual_subject': 'Duplicate Attempt',
            'student_ids': ['1']
        }, follow_redirects=True)

        self.assertIn("already been submitted", res.get_data(as_text=True))

        # Check count remains exactly 1 session
        with app.app_context():
            count = ClassSession.query.filter_by(timetable_id=tt_id, date=today).count()
            self.assertEqual(count, 1, "Duplicate ClassSession must not be created")

    def test_06_unauthorized_student_ids_filtered(self):
        """Foreign student IDs outside the class are safely rejected server-side"""
        with app.app_context():
            shivani = User.query.filter_by(username='shivani').first()
            tt = Timetable.query.filter_by(user_id=shivani.id, course='BCA', semester='Sem V').first()
            tt_id = tt.id
            actual_subject = tt.subject
            today = get_ist_time().date()
            existing = ClassSession.query.filter_by(timetable_id=tt_id, date=today).first()
            if existing:
                db.session.delete(existing)
                db.session.commit()

            # Create a dummy student in another course/section
            foreign_student = Student.query.filter_by(uucms_id='DUMMY999').first()
            if not foreign_student:
                foreign_student = Student(
                    uucms_id='DUMMY999',
                    name='Outsider Student',
                    email='outsider@bms.edu',
                    course='BCOM',
                    semester='Sem I',
                    section='B',
                    is_active=True
                )
                db.session.add(foreign_student)
                db.session.commit()
            foreign_id = foreign_student.id

        self.login_as(username='shivani', password='bms123')
        # Attempt to post foreign_id
        res = self.client.post(f'/academic-attendance/take/{tt_id}', data={
            'actual_subject': actual_subject,
            'student_ids': [str(foreign_id)],
            f'status_{foreign_id}': 'Present'
        }, follow_redirects=True)

        with app.app_context():
            cs = ClassSession.query.filter_by(timetable_id=tt_id, date=today).first()
            self.assertIsNotNone(cs)
            # Foreign student must NOT have an attendance record
            foreign_att = StudentAttendance.query.filter_by(class_session_id=cs.id, student_id=foreign_id).first()
            self.assertIsNone(foreign_att, "Foreign student must not be inserted")

            # Cleanup dummy foreign student
            db.session.delete(cs)
            db.session.delete(foreign_student)
            db.session.commit()

    def test_07_absence_notifications_logged(self):
        """Absent students generate student_absence_notification in NotificationLog"""
        time.sleep(0.5)
        with app.app_context():
            logs = NotificationLog.query.filter_by(event='student_absence_notification').all()
            self.assertGreater(len(logs), 0, "NotificationLog should record student absence notification")
            log = logs[-1]
            self.assertEqual(log.channel, 'email')
            self.assertIn(log.status, ['SENT', 'SKIPPED', 'FAILED'])
            self.assertIn("Student:", log.detail)

    def test_08_attendance_history_and_summary_view(self):
        """Attendance History page renders correctly with summary statistics"""
        self.login_as(username='balram', password='bms123')
        res = self.client.get('/academic-attendance/history')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("Student Academic Attendance History", html)
        self.assertIn("Matching Sessions", html)
        self.assertIn("Average Attendance Rate", html)

    def test_09_historical_immutability(self):
        """Modifying timetable afterwards must not alter historical ClassSession details"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            tt = Timetable.query.filter_by(user_id=balram.id, course='BCA', semester='Sem V').order_by(Timetable.id).first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(timetable_id=tt.id, date=today).first()
            self.assertIsNotNone(cs)
            original_session_room = cs.room_no
            original_session_subject = cs.scheduled_subject
            cs_id = cs.id
            tt_id = tt.id

            # Simulate someone editing the timetable in the future
            old_tt_room = tt.room_no
            tt.room_no = 'Room 999 Changed'
            db.session.commit()

            # Verify ClassSession historical values remain untouched
            reloaded_cs = ClassSession.query.get(cs_id)
            self.assertEqual(reloaded_cs.room_no, original_session_room)
            self.assertEqual(reloaded_cs.scheduled_subject, original_session_subject)

            # Revert timetable
            reloaded_tt = Timetable.query.get(tt_id)
            reloaded_tt.room_no = old_tt_room
            db.session.commit()

    def test_10_modify_attendance_authorization(self):
        """Only the conducting faculty, scheduled faculty, or Admin/HOD can edit attendance"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            shivani = User.query.filter_by(username='shivani').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs, "Balram session must exist")
            cs_id = cs.id

        # Shivani (unauthorized teacher) tries to access GET edit
        self.login_as(username='shivani', password='bms123')
        res = self.client.get(f'/academic-attendance/edit/{cs_id}', follow_redirects=True)
        self.assertIn("not authorized", res.get_data(as_text=True).lower())

        # Shivani tries to POST edit
        res_post = self.client.post(f'/academic-attendance/edit/{cs_id}', data={
            'actual_subject': 'Hacked Subject',
            'student_ids': ['1']
        }, follow_redirects=True)
        self.assertIn("not authorized", res_post.get_data(as_text=True).lower())

        # Balram (authorized) can access GET edit
        self.login_as(username='balram', password='bms123')
        res_balram = self.client.get(f'/academic-attendance/edit/{cs_id}')
        self.assertEqual(res_balram.status_code, 200)
        self.assertIn("Edit Previous Academic Attendance", res_balram.get_data(as_text=True))

    def test_11_modify_attendance_get_view_data(self):
        """GET /academic-attendance/edit/<session_id> pre-populates current attendance and roster"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)
            cs_id = cs.id
            actual_subject = cs.actual_subject

        self.login_as(username='balram', password='bms123')
        res = self.client.get(f'/academic-attendance/edit/{cs_id}')
        html = res.get_data(as_text=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(actual_subject, html)
        self.assertIn("U18IN24S0001", html)
        self.assertIn("17 Students", html)
        self.assertIn("15 P", html)
        self.assertIn("2 A", html)
        self.assertIn("Review Changes Before Saving", html)

    def test_12_modify_attendance_post_updates_persistence(self):
        """POST /academic-attendance/edit/<session_id> successfully modifies attendance, updates DB and notifies newly absent students"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)
            cs_id = cs.id

            students = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).order_by(Student.id).all()
            student_ids = [s.id for s in students]

            # In test_04, absent_ids were [student_ids[2], student_ids[5]]
            # Now let's change: student_ids[2] -> Present (cured absence)
            # student_ids[3] -> Absent (newly absent)
            # student_ids[5] remains Absent
            s2_id = student_ids[2]
            s3_id = student_ids[3]
            s5_id = student_ids[5]

        self.login_as(username='balram', password='bms123')

        post_data = {
            'actual_subject': 'Advanced Python - Module 4 Complete (Edited)',
            'remarks': 'Updated: student on-duty slip approved for student 2',
            'reason': 'Student 2 presented approved on-duty slip; student 3 confirmed absent',
            'version': 1,
            'student_ids': [str(sid) for sid in student_ids]
        }
        for sid in student_ids:
            if sid in [s3_id, s5_id]:
                post_data[f'status_{sid}'] = 'Absent'
            else:
                post_data[f'status_{sid}'] = 'Present'

        res = self.client.post(f'/academic-attendance/edit/{cs_id}', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("updated successfully", html.lower())
        self.assertIn("15 Present", html)
        self.assertIn("2 Absent", html)

        # Allow async email worker thread to run
        time.sleep(0.5)

        # Direct Database Assertions
        with app.app_context():
            updated_cs = ClassSession.query.get(cs_id)
            self.assertEqual(updated_cs.actual_subject, 'Advanced Python - Module 4 Complete (Edited)')
            self.assertEqual(updated_cs.remarks, 'Updated: student on-duty slip approved for student 2')

            att_s2 = StudentAttendance.query.filter_by(class_session_id=cs_id, student_id=s2_id).first()
            self.assertEqual(att_s2.status, 'Present', "Student 2 should now be marked Present")

            att_s3 = StudentAttendance.query.filter_by(class_session_id=cs_id, student_id=s3_id).first()
            self.assertEqual(att_s3.status, 'Absent', "Student 3 should now be marked Absent")

            att_s5 = StudentAttendance.query.filter_by(class_session_id=cs_id, student_id=s5_id).first()
            self.assertEqual(att_s5.status, 'Absent', "Student 5 should remain Absent")

            # Notification verification for s3 (newly marked absent)
            student3_obj = Student.query.get(s3_id)
            logs = NotificationLog.query.filter_by(event='student_absence_notification').all()
            matching_logs = [l for l in logs if student3_obj.name in l.detail]
            self.assertGreater(len(matching_logs), 0, f"NotificationLog must contain entry for newly absent student {student3_obj.name}")

    def test_13_history_filtering_by_date_and_range(self):
        """History filtering works accurately for specific date and date ranges"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)

        self.login_as(username='balram', password='bms123')

        # Filter by today's specific date
        res = self.client.get(f'/academic-attendance/history?date={today.strftime("%Y-%m-%d")}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(cs.actual_subject, res.get_data(as_text=True))

        # Filter by a future date where no session exists
        res_future = self.client.get('/academic-attendance/history?date=2029-01-01')
        self.assertEqual(res_future.status_code, 200)
        self.assertIn("No attendance history found", res_future.get_data(as_text=True))

        # Filter by date range covering today
        res_range = self.client.get(f'/academic-attendance/history?start_date=2026-01-01&end_date={today.strftime("%Y-%m-%d")}')
        self.assertEqual(res_range.status_code, 200)
        self.assertIn(cs.actual_subject, res_range.get_data(as_text=True))

    def test_14_history_filtering_by_month_and_calendar_boundaries(self):
        """Month filtering correctly isolates current month and handles leap years"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)

        self.login_as(username='balram', password='bms123')

        # Current month query
        res = self.client.get(f'/academic-attendance/history?month={today.strftime("%Y-%m")}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(cs.actual_subject, res.get_data(as_text=True))

        # Other month query (e.g. 2025-02)
        res_other = self.client.get('/academic-attendance/history?month=2025-02')
        self.assertEqual(res_other.status_code, 200)
        self.assertIn("No attendance history found", res_other.get_data(as_text=True))

    def test_15_mandatory_correction_reason_enforced(self):
        """Attempting to edit attendance statuses without providing a reason is rejected"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)
            cs_id = cs.id
            students = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).all()
            student_ids = [s.id for s in students]

        self.login_as(username='balram', password='bms123')

        # Post data with empty reason
        post_data = {
            'actual_subject': cs.actual_subject,
            'remarks': cs.remarks or '',
            'reason': '',  # EMPTY REASON
            'version': cs.version or 1,
            'student_ids': [str(sid) for sid in student_ids]
        }
        for sid in student_ids:
            post_data[f'status_{sid}'] = 'Present'

        res = self.client.post(f'/academic-attendance/edit/{cs_id}', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn("correction reason is required", res.get_data(as_text=True).lower())

    def test_16_unchanged_submission_creates_no_audit_entries(self):
        """Submitting an unchanged form generates 0 new audit entries"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)
            cs_id = cs.id

            initial_audit_count = StudentAttendanceAudit.query.filter_by(class_session_id=cs_id).count()

            existing_att = {a.student_id: a.status for a in StudentAttendance.query.filter_by(class_session_id=cs_id).all()}
            students = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).all()
            student_ids = [s.id for s in students]

        self.login_as(username='balram', password='bms123')

        post_data = {
            'actual_subject': cs.actual_subject,
            'remarks': cs.remarks or '',
            'reason': 'No change test',
            'version': cs.version or 1,
            'student_ids': [str(sid) for sid in student_ids]
        }
        for sid in student_ids:
            post_data[f'status_{sid}'] = existing_att.get(sid, 'Present')

        res = self.client.post(f'/academic-attendance/edit/{cs_id}', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn("no changes detected", res.get_data(as_text=True).lower())

        with app.app_context():
            final_audit_count = StudentAttendanceAudit.query.filter_by(class_session_id=cs_id).count()
            self.assertEqual(final_audit_count, initial_audit_count, "Unchanged submission must not create fake audit entries")

    def test_17_audit_trail_captures_all_status_changes_and_actors(self):
        """Every actual change is persisted in StudentAttendanceAudit with actor, old & new values, and reason"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)
            audits = StudentAttendanceAudit.query.filter_by(class_session_id=cs.id).all()
            self.assertGreater(len(audits), 0, "Audit trail records must exist from previous edits")
            sample_audit = audits[0]
            self.assertEqual(sample_audit.changed_by, balram.id)
            self.assertIsNotNone(sample_audit.reason)
            self.assertIsNotNone(sample_audit.created_at)

    def test_18_optimistic_concurrency_conflict_detected(self):
        """Submitting an outdated version token triggers concurrency conflict detection"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)
            cs_id = cs.id
            students = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).all()
            student_ids = [s.id for s in students]

        self.login_as(username='balram', password='bms123')

        post_data = {
            'actual_subject': 'Conflicting Edit',
            'remarks': 'Testing concurrency',
            'reason': 'Conflict test reason',
            'version': 99999,  # OUTDATED / MISMATCHED VERSION
            'student_ids': [str(sid) for sid in student_ids]
        }
        for sid in student_ids:
            post_data[f'status_{sid}'] = 'Present'

        res = self.client.post(f'/academic-attendance/edit/{cs_id}', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn("concurrency conflict", res.get_data(as_text=True).lower())

    def test_19_foreign_student_ids_and_invalid_statuses_sanitized(self):
        """Submitting foreign student IDs or invalid status strings is safely sanitized"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)
            cs_id = cs.id

        self.login_as(username='balram', password='bms123')

        post_data = {
            'actual_subject': cs.actual_subject,
            'remarks': cs.remarks or '',
            'reason': 'Foreign ID injection test',
            'version': cs.version or 1,
            'student_ids': ['999999']  # Foreign ID not in class
        }
        post_data['status_999999'] = 'HackedStatus'

        res = self.client.post(f'/academic-attendance/edit/{cs_id}', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        # Server must not crash and foreign student must not be created
        with app.app_context():
            att = StudentAttendance.query.filter_by(class_session_id=cs_id, student_id=999999).first()
            self.assertIsNone(att, "Foreign student must not be inserted into attendance")

    def test_20_email_policy_on_absent_to_present(self):
        """Correcting a student from Absent to Present does NOT dispatch an absence notification"""
        with app.app_context():
            balram = User.query.filter_by(username='balram').first()
            today = get_ist_time().date()
            cs = ClassSession.query.filter_by(actual_faculty_id=balram.id, date=today).first()
            self.assertIsNotNone(cs)
            cs_id = cs.id

            # Find a student who is currently Absent
            absent_att = StudentAttendance.query.filter_by(class_session_id=cs_id, status='Absent').first()
            self.assertIsNotNone(absent_att)
            absent_sid = absent_att.student_id

            initial_notif_count = NotificationLog.query.filter_by(event='student_absence_notification').count()

            students = Student.query.filter_by(course='BCA', semester='Sem V', section='A', is_active=True).all()
            student_ids = [s.id for s in students]

        self.login_as(username='balram', password='bms123')

        post_data = {
            'actual_subject': cs.actual_subject,
            'remarks': cs.remarks or '',
            'reason': 'Correcting absence to present - approved medical certificate',
            'version': cs.version or 1,
            'student_ids': [str(sid) for sid in student_ids]
        }
        for sid in student_ids:
            # Mark all as Present, curing the absent student
            post_data[f'status_{sid}'] = 'Present'

        res = self.client.post(f'/academic-attendance/edit/{cs_id}', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        time.sleep(0.5)

        with app.app_context():
            final_notif_count = NotificationLog.query.filter_by(event='student_absence_notification').count()
            self.assertEqual(final_notif_count, initial_notif_count, "No new absence notification should be sent when absent student is marked Present")

if __name__ == '__main__':
    unittest.main()
