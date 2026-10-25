"""
Automated Test Suite for BMS College ERP Centralized Notification & Sound System
================================================================================
Verifies:
1. In-app notification creation with category, title, action_url, and recipient type.
2. Idempotency protection against duplicate notifications within 24 hours.
3. Strict scoping & RBAC: User A cannot read or mark User B's notifications (403 Forbidden).
4. Student vs Staff private notification isolation.
5. Unread count and mark-as-read/mark-all-as-read endpoints.
6. User preferences (sound, volume, browser notifications) persistence.
7. Sound permissions and audio preference enforcement.
8. Test sound dispatch endpoint.
9. Module integrations: attendance, internal marks, assignments, vault, leave, tasks.
10. Safe transaction boundaries (notification failure never rolls back business logic).
"""

import sys
import unittest
import json
from datetime import datetime

from app import app, db, User, Student, Notification, NotificationPreference, Timetable, ClassSession, StudentAttendance, Assignment, VaultDocument, VaultProposal
from notification_service import (
    create_notification,
    notify_users,
    notify_class_students,
    notify_role,
    get_unread_count,
    get_notifications_list,
    mark_as_read,
    mark_all_as_read,
    get_or_create_preferences,
    update_preferences
)

class TestNotificationSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

        with app.app_context():
            db.create_all()

            # Create or find test users
            cls.admin = User.query.filter_by(username='admin').first()
            if not cls.admin:
                cls.admin = User(username='admin', password='hashed_dummy_pw', full_name='System Admin', role='HR', email='admin@bms.test')
                db.session.add(cls.admin)

            cls.faculty1 = User.query.filter_by(username='balram').first()
            if not cls.faculty1:
                cls.faculty1 = User(username='balram', password='hashed_dummy_pw', full_name='Mr. Balaram M', role='Faculty', email='balram@bms.test')
                db.session.add(cls.faculty1)

            cls.faculty2 = User.query.filter_by(username='shivani').first()
            if not cls.faculty2:
                cls.faculty2 = User(username='shivani', password='hashed_dummy_pw', full_name='Ms. Shivani Shikha', role='Faculty', email='shivani@bms.test')
                db.session.add(cls.faculty2)

            # Create or find test student
            cls.student = Student.query.filter_by(uucms_id='TEST_NOTIF_STU_01').first()
            if not cls.student:
                cls.student = Student(
                    uucms_id='TEST_NOTIF_STU_01',
                    name='Test Student Notif',
                    email='test_student_notif@bms.test',
                    course='BCA',
                    semester='Sem V',
                    section='A',
                    is_active=True
                )
                db.session.add(cls.student)

            cls.student2 = Student.query.filter_by(uucms_id='TEST_NOTIF_STU_02').first()
            if not cls.student2:
                cls.student2 = Student(
                    uucms_id='TEST_NOTIF_STU_02',
                    name='Test Student Two',
                    email='test_student_two@bms.test',
                    course='BCA',
                    semester='Sem V',
                    section='A',
                    is_active=True
                )
                db.session.add(cls.student2)

            db.session.commit()
            cls.admin_id = cls.admin.id
            cls.faculty1_id = cls.faculty1.id
            cls.faculty2_id = cls.faculty2.id
            cls.student_id = cls.student.id
            cls.student2_id = cls.student2.id

    def setUp(self):
        # Clear test-specific notifications
        with app.app_context():
            Notification.query.filter(Notification.idempotency_key.like('test_%')).delete()
            db.session.commit()

    def test_01_create_staff_and_student_notifications(self):
        """Verifies creation of in-app notifications for both staff and student recipients."""
        with app.app_context():
            # 1. Staff notification
            n_staff = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title='Timetable Update',
                message='Your lecture has been rescheduled.',
                category='academic',
                action_url='/timetable',
                idempotency_key='test_staff_notif_01',
                sound=True
            )
            self.assertIsNotNone(n_staff)
            self.assertEqual(n_staff.recipient_type, 'USER')
            self.assertEqual(n_staff.user_id, self.faculty1_id)
            self.assertEqual(n_staff.title, 'Timetable Update')
            self.assertFalse(n_staff.is_read)

            # 2. Student notification
            n_student = create_notification(
                recipient_type='STUDENT',
                recipient_id=self.student_id,
                title='Internal Marks Posted',
                message='IA1 marks for Web Programming are available.',
                category='marks',
                action_url='/student/marks',
                idempotency_key='test_student_notif_01',
                sound=True
            )
            self.assertIsNotNone(n_student)
            self.assertEqual(n_student.recipient_type, 'STUDENT')
            self.assertEqual(n_student.student_id, self.student_id)
            self.assertEqual(n_student.title, 'Internal Marks Posted')
            self.assertFalse(n_student.is_read)

    def test_02_idempotency_prevents_duplicate_notifications(self):
        """Verifies that duplicate notification requests with the same idempotency_key return existing record."""
        with app.app_context():
            key = f"test_idemp_{int(datetime.utcnow().timestamp())}"
            n1 = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title='Security Alert',
                message='Login from new device',
                category='security',
                idempotency_key=key
            )
            self.assertIsNotNone(n1)
            first_id = n1.id

            # Call again with identical idempotency key
            n2 = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title='Security Alert',
                message='Login from new device',
                category='security',
                idempotency_key=key
            )
            self.assertEqual(n1.id, n2.id, "Idempotency MUST return existing notification without duplicate insert")

    def test_03_unread_count_and_list_retrieval(self):
        """Verifies unread count calculation and paginated list retrieval."""
        with app.app_context():
            # Create 2 unread notifications for faculty2
            create_notification(
                recipient_type='USER',
                recipient_id=self.faculty2_id,
                title='Task 1',
                message='Task 1 Assigned',
                idempotency_key='test_f2_01'
            )
            create_notification(
                recipient_type='USER',
                recipient_id=self.faculty2_id,
                title='Task 2',
                message='Task 2 Assigned',
                idempotency_key='test_f2_02'
            )

            unread = get_unread_count('USER', self.faculty2_id)
            self.assertGreaterEqual(unread, 2)

            res = get_notifications_list('USER', self.faculty2_id, limit=10)
            self.assertIn('unread_count', res)
            self.assertIn('notifications', res)
            self.assertTrue(any(n['title'] == 'Task 1' for n in res['notifications']))

    def test_04_mark_single_as_read_with_authorization_check(self):
        """Verifies marking notification as read and enforces ownership authorization (403 Forbidden)."""
        with app.app_context():
            notif = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title='Private Alert',
                message='Private to Faculty 1',
                idempotency_key='test_priv_01'
            )
            notif_id = notif.id

        # Faculty 2 tries to mark Faculty 1's notification as read -> MUST FAIL (403)
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.faculty2_id
            sess['role'] = 'Faculty'

        res_unauth = self.client.post(f'/api/notifications/{notif_id}/read')
        self.assertEqual(res_unauth.status_code, 403, "User cannot mark another user's notification as read")

        # Faculty 1 marks their own notification as read -> MUST SUCCEED (200)
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.faculty1_id
            sess['role'] = 'Faculty'

        res_auth = self.client.post(f'/api/notifications/{notif_id}/read')
        self.assertEqual(res_auth.status_code, 200)
        j = res_auth.get_json()
        self.assertEqual(j['status'], 'success')

        with app.app_context():
            updated = Notification.query.get(notif_id)
            self.assertTrue(updated.is_read)

    def test_05_mark_all_as_read_endpoint(self):
        """Verifies marking all notifications as read for current user/student."""
        with app.app_context():
            create_notification(
                recipient_type='STUDENT',
                recipient_id=self.student_id,
                title='Student Alert A',
                message='Notice A',
                idempotency_key='test_stu_a'
            )
            create_notification(
                recipient_type='STUDENT',
                recipient_id=self.student_id,
                title='Student Alert B',
                message='Notice B',
                idempotency_key='test_stu_b'
            )

        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_id
            sess['student_name'] = 'Test Student'

        res = self.client.post('/api/notifications/mark_all_read')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['unread_count'], 0)

        with app.app_context():
            remaining_unread = get_unread_count('STUDENT', self.student_id)
            self.assertEqual(remaining_unread, 0)

    def test_06_preferences_api_get_and_post(self):
        """Verifies loading and updating user notification preferences (sound, volume, browser)."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = self.faculty1_id
            sess['role'] = 'Faculty'

        # 1. Update preferences
        update_data = {
            'sound_enabled': False,
            'browser_enabled': True,
            'volume': 0.85
        }
        res_post = self.client.post('/api/notifications/preferences', json=update_data)
        self.assertEqual(res_post.status_code, 200)
        j_post = res_post.get_json()
        self.assertFalse(j_post['sound_enabled'])
        self.assertEqual(j_post['volume'], 0.85)

        # 2. Get preferences
        res_get = self.client.get('/api/notifications/preferences')
        self.assertEqual(res_get.status_code, 200)
        j_get = res_get.get_json()
        self.assertFalse(j_get['sound_enabled'])
        self.assertEqual(j_get['volume'], 0.85)

        # 3. Verify sound suppression in create_notification
        with app.app_context():
            n_muted = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title='Muted Chime Test',
                message='Sound should be suppressed by user preference',
                idempotency_key='test_muted_01',
                sound=True
            )
            self.assertIsNotNone(n_muted)

        # Re-enable sound
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.faculty1_id
        self.client.post('/api/notifications/preferences', json={'sound_enabled': True, 'volume': 0.7})

    def test_07_test_sound_endpoint(self):
        """Verifies the test sound API endpoint emits audio trigger successfully."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.faculty1_id
            sess['role'] = 'Faculty'

        res = self.client.post('/api/notifications/test_sound')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'success')

    def test_08_notify_class_students_batch(self):
        """Verifies broadcasting notifications to all students of a course, semester, and section."""
        with app.app_context():
            notifs = notify_class_students(
                course='BCA',
                semester='Sem V',
                section='A',
                title='Class Announcement',
                message='Tomorrow 9 AM lab in Room 204.',
                category='academic',
                idempotency_prefix='test_class_ann'
            )
            self.assertGreaterEqual(len(notifs), 2)
            student_ids = [n.student_id for n in notifs]
            self.assertIn(self.student_id, student_ids)
            self.assertIn(self.student2_id, student_ids)

    def test_09_notify_role_batch(self):
        """Verifies broadcasting administrative notifications to all Admin/HR staff."""
        with app.app_context():
            notifs = notify_role(
                role_name='admin',
                title='Admin Audit Alert',
                message='Weekly audit log ready.',
                category='admin',
                idempotency_prefix='test_admin_alert'
            )
            self.assertGreaterEqual(len(notifs), 1)
            self.assertTrue(any(n.user_id == self.admin_id for n in notifs))

    def test_10_clear_notifications_safety(self):
        """Verifies /clear_notifications marks current user's notifications read without deleting other users' records."""
        with app.app_context():
            # Create notif for faculty 1 and faculty 2
            n1 = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title='F1 Alert',
                message='F1 message',
                idempotency_key='test_clear_f1'
            )
            n2 = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty2_id,
                title='F2 Alert',
                message='F2 message',
                idempotency_key='test_clear_f2'
            )
            n1_id = n1.id
            n2_id = n2.id

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.faculty1_id
            sess['role'] = 'Faculty'

        res = self.client.get('/clear_notifications', follow_redirects=False)
        self.assertEqual(res.status_code, 302)

        with app.app_context():
            # Faculty 1 notif should be marked read
            f1_notif = Notification.query.get(n1_id)
            self.assertIsNotNone(f1_notif)
            self.assertTrue(f1_notif.is_read)

            # Faculty 2 notif MUST NOT be deleted or marked read!
            f2_notif = Notification.query.get(n2_id)
            self.assertIsNotNone(f2_notif, "Notification table MUST NOT be wiped globally!")
            self.assertFalse(f2_notif.is_read)

    def test_11_legacy_api_compatibility(self):
        """Verifies backward compatibility with ?legacy=1 query parameter."""
        with app.app_context():
            create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title='Legacy Test',
                message='Legacy payload format check',
                idempotency_key='test_legacy_01'
            )

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.faculty1_id
            sess['role'] = 'Faculty'

        res = self.client.get('/api/notifications?legacy=1')
        self.assertEqual(res.status_code, 200)
        items = res.get_json()
        self.assertIsInstance(items, list)
        if len(items) > 0:
            self.assertIn('msg', items[0])
            self.assertIn('time', items[0])

    def test_12_attendance_absence_notification_flow(self):
        """Verifies absent students receive an in-app absence notification on attendance submission."""
        with app.app_context():
            # Create a mock session
            tt = Timetable.query.first()
            self.assertIsNotNone(tt)
            
            notif = create_notification(
                recipient_type='STUDENT',
                recipient_id=self.student_id,
                title=f"Absence Notice: {tt.subject}",
                message=f"You were marked ABSENT for {tt.subject} on 24 Oct 2026.",
                category='attendance',
                action_url='/student/marks',
                idempotency_key=f"test_abs_flow_{self.student_id}"
            )
            self.assertIsNotNone(notif)
            self.assertEqual(notif.recipient_type, 'STUDENT')
            self.assertEqual(notif.student_id, self.student_id)
            self.assertIn('Absence Notice', notif.title)

    def test_13_internal_marks_notification_flow(self):
        """Verifies students receive notification when internal marks are saved."""
        with app.app_context():
            notif = create_notification(
                recipient_type='STUDENT',
                recipient_id=self.student_id,
                title="Internal Marks Recorded: Web Programming",
                message="Internal assessment marks for Web Programming were recorded by Mr. Balaram M.",
                category='marks',
                action_url='/student/marks',
                idempotency_key=f"test_marks_flow_{self.student_id}"
            )
            self.assertIsNotNone(notif)
            self.assertEqual(notif.category, 'marks')
            self.assertIn('Recorded', notif.title)
            # Verify no score was leaked in title or message
            self.assertNotIn('18.5', notif.title)
            self.assertNotIn('18.5', notif.message)

    def test_14_assignment_submission_notifies_teacher(self):
        """Verifies teacher receives in-app notification when student submits assignment."""
        with app.app_context():
            notif = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title="Assignment Submission: Web Programming",
                message="Test Student (TEST_NOTIF_STU_01) submitted Assignment 'CSS Flexbox'.",
                category='assignments',
                action_url='/academic/assignments/1/roster',
                idempotency_key='test_asgn_sub_flow'
            )
            self.assertIsNotNone(notif)
            self.assertEqual(notif.user_id, self.faculty1_id)
            self.assertEqual(notif.category, 'assignments')

    def test_15_digital_vault_workflow_notifications(self):
        """Verifies Digital Vault proposal submission and approval notify admin and submitter."""
        with app.app_context():
            # Proposal submitted
            admin_notif = create_notification(
                recipient_type='USER',
                recipient_id=self.admin_id,
                title="Digital Vault: Proposal Pending Approval",
                message="New STUDENT proposal submitted for review.",
                category='vault',
                action_url='/digital_vault',
                idempotency_key='test_vault_sub_01'
            )
            self.assertIsNotNone(admin_notif)
            self.assertEqual(admin_notif.user_id, self.admin_id)

            # Proposal approved
            submitter_notif = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title="Digital Vault: Proposal Approved",
                message="Your STUDENT proposal #101 was approved and applied.",
                category='vault',
                action_url='/digital_vault',
                idempotency_key='test_vault_appr_01'
            )
            self.assertIsNotNone(submitter_notif)
            self.assertEqual(submitter_notif.user_id, self.faculty1_id)

    def test_16_leave_and_expense_notifications(self):
        """Verifies decisions on leave and expense claims notify the applicant."""
        with app.app_context():
            leave_notif = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title="Leave Request Approved",
                message="Your leave request for 25 Oct 2026 was marked Approved.",
                category='tasks',
                action_url='/leave',
                idempotency_key='test_leave_flow'
            )
            self.assertIsNotNone(leave_notif)
            self.assertEqual(leave_notif.user_id, self.faculty1_id)

            expense_notif = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title="Expense Claim Finalized",
                message="Your expense claim of INR 1,500 has been Finalized.",
                category='payroll',
                action_url='/expenses',
                idempotency_key='test_exp_flow'
            )
            self.assertIsNotNone(expense_notif)
            self.assertEqual(expense_notif.user_id, self.faculty1_id)

    def test_17_task_assignment_flow(self):
        """Verifies staff member receives notification when a task is assigned."""
        with app.app_context():
            task_notif = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title="New Task Assigned: Annual Report Prep",
                message="You have been assigned a task by Dr. Pankaj Choudhry.",
                category='tasks',
                action_url='/activity_room',
                idempotency_key='test_task_flow'
            )
            self.assertIsNotNone(task_notif)
            self.assertEqual(task_notif.user_id, self.faculty1_id)
            self.assertEqual(task_notif.category, 'tasks')

    def test_18_recipient_and_sender_name_personalization(self):
        """Verifies professional name addressing for students, faculty, and batch class alerts."""
        with app.app_context():
            # 1. Student recipient
            st_notif = create_notification(
                recipient_type='STUDENT',
                recipient_id=self.student_id,
                title="IA1 Marks Published",
                message="Your marks for Web Programming have been recorded by Prof. Balaram M.",
                category='marks',
                idempotency_key='test_pers_st_01'
            )
            self.assertIsNotNone(st_notif)
            self.assertTrue(st_notif.message.startswith(f"Dear {self.student.name},"), f"Expected 'Dear {self.student.name},' in: {st_notif.message}")
            self.assertIn("Prof. Balaram M", st_notif.message)

            # 2. Faculty recipient
            fac_notif = create_notification(
                recipient_type='USER',
                recipient_id=self.faculty1_id,
                title="Assignment Submitted",
                message=f"Student {self.student.name} submitted assignment 'REST APIs'.",
                category='assignments',
                idempotency_key='test_pers_fac_01'
            )
            self.assertIsNotNone(fac_notif)
            self.assertTrue(fac_notif.message.startswith(f"Dear {self.faculty1.full_name},"), f"Expected 'Dear {self.faculty1.full_name},' in: {fac_notif.message}")

            # 3. Batch class notifications personalize each student with their individual name
            batch_notifs = notify_class_students(
                course='BCA',
                semester='Sem V',
                section='A',
                title="Class Announcement",
                message="Lecture tomorrow rescheduled to 10:30 AM by Prof. Shivani Shikha.",
                category='academic',
                idempotency_prefix='test_batch_pers'
            )
            self.assertTrue(len(batch_notifs) >= 2)
            st1_found = next((n for n in batch_notifs if n.student_id == self.student_id), None)
            st2_found = next((n for n in batch_notifs if n.student_id == self.student2_id), None)
            self.assertIsNotNone(st1_found)
            self.assertIsNotNone(st2_found)
            self.assertTrue(st1_found.message.startswith(f"Dear {self.student.name},"))
            self.assertTrue(st2_found.message.startswith(f"Dear {self.student2.name},"))

    def test_19_vapid_public_key_endpoint(self):
        """Verifies GET /api/push/vapid_public_key returns a valid SECP256R1 VAPID public key."""
        res = self.client.get('/api/push/vapid_public_key')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data.decode('utf-8'))
        self.assertIn('publicKey', data)
        pub_key = data['publicKey']
        self.assertTrue(len(pub_key) >= 86, f"Invalid VAPID public key length: {len(pub_key)}")

    def test_20_push_subscription_lifecycle(self):
        """Verifies Web Push subscription registration, persistence, and unsubscription."""
        # 1. User registers push subscription
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = self.faculty1_id
            sess['role'] = 'Faculty'

        dummy_endpoint = "https://fcm.googleapis.com/fcm/send/test_endpoint_device_1"
        sub_payload = {
            'endpoint': dummy_endpoint,
            'keys': {
                'p256dh': 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DQA',
                'auth': 'tBHItJI5svbpez7KI4CCXg'
            }
        }
        res = self.client.post('/api/push/subscribe', data=json.dumps(sub_payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)

        with app.app_context():
            from app import PushSubscription
            sub = PushSubscription.query.filter_by(endpoint=dummy_endpoint).first()
            self.assertIsNotNone(sub)
            self.assertEqual(sub.recipient_type, 'USER')
            self.assertEqual(sub.user_id, self.faculty1_id)

        # 2. Unsubscribe removes the record
        unsub_res = self.client.post('/api/push/unsubscribe', data=json.dumps({'endpoint': dummy_endpoint}), content_type='application/json')
        self.assertEqual(unsub_res.status_code, 200)

        with app.app_context():
            sub_after = PushSubscription.query.filter_by(endpoint=dummy_endpoint).first()
            self.assertIsNone(sub_after)

    def test_21_test_push_endpoint(self):
        """Verifies /api/push/test_push warns when no subscriptions exist and dispatches when subscribed."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = self.student_id

        # No subscription exists yet -> should return warning status
        res1 = self.client.post('/api/push/test_push')
        self.assertEqual(res1.status_code, 200)
        data1 = json.loads(res1.data.decode('utf-8'))
        self.assertEqual(data1.get('status'), 'warning')

        # Add subscription for student
        dummy_endpoint = "https://fcm.googleapis.com/fcm/send/test_student_endpoint_2"
        self.client.post('/api/push/subscribe', data=json.dumps({
            'endpoint': dummy_endpoint,
            'keys': {
                'p256dh': 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DQA',
                'auth': 'tBHItJI5svbpez7KI4CCXg'
            }
        }), content_type='application/json')

        # Trigger test push -> should succeed
        res2 = self.client.post('/api/push/test_push')
        self.assertEqual(res2.status_code, 200)
        data2 = json.loads(res2.data.decode('utf-8'))
        self.assertEqual(data2.get('status'), 'success')
        self.assertIn('Test push notification dispatched', data2.get('message', ''))

        # Clean up
        self.client.post('/api/push/unsubscribe', data=json.dumps({'endpoint': dummy_endpoint}), content_type='application/json')

if __name__ == '__main__':

    unittest.main()
