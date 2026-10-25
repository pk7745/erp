"""
Test Suite: Campus-Only Teacher Attendance Geofence & Anti-Spoofing Verification
================================================================================
Institution: BMS College of Commerce & Management (BMSCCM)
Address: No. 97, Kavi Lakshmisha Road, Parvathi Nagar / V.V. Puram, Bengaluru - 560004
(Distinct from BMS College of Engineering, Basavanagudi)

Verifies all 14 mandatory acceptance test scenarios:
1. Location inside verified geofence — accepted.
2. Location outside geofence — rejected.
3. Location at/near boundary — follows documented boundary uncertainty policy.
4. Missing coordinates — rejected.
5. Invalid latitude or longitude — rejected.
6. Unacceptable GPS accuracy — rejected.
7. Stale location reading — rejected.
8. Client-supplied fake is_inside_campus=true — cannot bypass server verification.
9. Direct API request outside campus — rejected.
10. QR attendance cannot bypass location rule where campus presence is required.
11. Unauthorized users cannot modify geofence configuration.
12. Existing staff attendance, device-binding, and legitimate administrative correction workflows continue to work.
13. Student academic attendance remains unaffected.
14. Disabled enforcement during initial configuration behaves safely and does not falsely report verified location.
"""

import time
from datetime import datetime, timezone
import unittest

from app import (
    app, db, User, Attendance, RegisteredDevice, AuditLog,
    generate_rotating_qr_token, get_ist_time
)
from campus_geofence import (
    verify_campus_presence,
    get_geofence_config,
    update_geofence_config,
    haversine_distance,
    DEFAULT_CAMPUS_LAT,
    DEFAULT_CAMPUS_LON,
    DEFAULT_CAMPUS_RADIUS_METERS
)


class TestCampusGeofenceAttendance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

        with app.app_context():
            cls.teacher = User.query.filter_by(username='balram').first()
            assert cls.teacher, "Teacher balram required for tests"
            cls.teacher_id = cls.teacher.id

            cls.admin = User.query.filter_by(username='admin').first()
            assert cls.admin, "Admin required for tests"
            cls.admin_id = cls.admin.id

            cls.faculty_kiran = User.query.filter_by(username='kiran').first()
            assert cls.faculty_kiran, "Faculty kiran required for tests"
            cls.kiran_id = cls.faculty_kiran.id

            # Save initial geofence configuration to restore later
            cls.original_geofence_cfg = get_geofence_config()

    @classmethod
    def tearDownClass(cls):
        # Restore original configuration
        update_geofence_config(cls.original_geofence_cfg)

    def setUp(self):
        # Ensure standard geofence configuration is active for tests
        update_geofence_config({
            'enabled': True,
            'mode': 'RADIUS',
            'center_lat': DEFAULT_CAMPUS_LAT,
            'center_lon': DEFAULT_CAMPUS_LON,
            'radius_meters': DEFAULT_CAMPUS_RADIUS_METERS,
            'max_accuracy_meters': 50.0,
            'max_age_seconds': 120,
            'boundary_buffer_meters': 10.0
        })

    def tearDown(self):
        # Clean any test-created attendance or audit entries
        with app.app_context():
            today_str = get_ist_time().strftime("%Y-%m-%d")
            Attendance.query.filter_by(user_id=self.teacher_id, date=today_str).delete()
            db.session.commit()

    # --------------------------------------------------------------------------
    # 1. Location Inside Geofence — Accepted
    # --------------------------------------------------------------------------
    def test_01_location_inside_geofence_accepted(self):
        """Verifies teacher check-in with GPS coordinates inside campus boundary is accepted."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = self.teacher.full_name

        # Coordinates 30m from BMSCCM center
        res = self.client.post('/attendance', data={
            'lat': '12.951700',
            'lon': '77.576200',
            'accuracy': '12.5',
            'client_timestamp': str(time.time()),
            'work_mode': 'Office'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        with app.app_context():
            today_str = get_ist_time().strftime("%Y-%m-%d")
            att = Attendance.query.filter_by(user_id=self.teacher_id, date=today_str).first()
            self.assertIsNotNone(att)
            self.assertEqual(att.work_mode, 'Office')
            self.assertEqual(att.location_status, 'CAMPUS_VERIFIED')
            self.assertAlmostEqual(att.lat, 12.951700, places=4)
            self.assertAlmostEqual(att.lon, 77.576200, places=4)
            self.assertEqual(att.accuracy, 12.5)

    # --------------------------------------------------------------------------
    # 2. Location Outside Geofence — Rejected
    # --------------------------------------------------------------------------
    def test_02_location_outside_geofence_rejected(self):
        """Verifies teacher check-in with GPS coordinates outside campus is rejected."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = self.teacher.full_name

        # Coordinates ~500m away (north near Lalbagh)
        res = self.client.post('/attendance', data={
            'lat': '12.956000',
            'lon': '77.576200',
            'accuracy': '15.0',
            'client_timestamp': str(time.time()),
            'work_mode': 'Office'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        # Verify no attendance record was created
        with app.app_context():
            today_str = get_ist_time().strftime("%Y-%m-%d")
            att = Attendance.query.filter_by(user_id=self.teacher_id, date=today_str).first()
            self.assertIsNone(att)

    # --------------------------------------------------------------------------
    # 3. Location Near Boundary — Boundary Uncertainty Policy Enforced
    # --------------------------------------------------------------------------
    def test_03_boundary_uncertainty_policy_enforced(self):
        """
        Verifies that when a location is near the campus boundary and accuracy circle
        overlaps outside the buffer (distance + accuracy > radius + buffer),
        it is rejected with BOUNDARY_UNCERTAIN to prevent boundary gaming.
        """
        # Distance ~ 140m from center (0.00126 deg lat approx 140m)
        border_lat = DEFAULT_CAMPUS_LAT + 0.00126
        border_lon = DEFAULT_CAMPUS_LON
        # Accuracy error margin ±30m -> 140 + 30 = 170m > (150m + 10m buffer = 160m)
        is_valid, code, msg, details = verify_campus_presence(
            lat=border_lat,
            lon=border_lon,
            accuracy=30.0,
            client_timestamp=time.time()
        )
        self.assertFalse(is_valid)
        self.assertEqual(code, 'BOUNDARY_UNCERTAIN')
        self.assertIn("extends beyond", msg)

    # --------------------------------------------------------------------------
    # 4. Missing Coordinates — Rejected
    # --------------------------------------------------------------------------
    def test_04_missing_coordinates_rejected(self):
        """Verifies rejection when lat or lon is missing."""
        is_valid_none, code_none, msg, _ = verify_campus_presence(None, None)
        self.assertFalse(is_valid_none)
        self.assertEqual(code_none, 'MISSING_COORDINATES')

        is_valid_empty, code_empty, _, _ = verify_campus_presence('', '')
        self.assertFalse(is_valid_empty)
        self.assertEqual(code_empty, 'MISSING_COORDINATES')

    # --------------------------------------------------------------------------
    # 5. Invalid Latitude or Longitude — Rejected
    # --------------------------------------------------------------------------
    def test_05_invalid_latitude_or_longitude_rejected(self):
        """Verifies rejection of non-numeric, out-of-range, and Null Island (0,0) coordinates."""
        # Non-numeric
        ok_str, code_str, _, _ = verify_campus_presence("bad_lat", "bad_lon")
        self.assertFalse(ok_str)
        self.assertEqual(code_str, 'INVALID_COORDINATES')

        # Out of geographic range
        ok_range, code_range, _, _ = verify_campus_presence(95.0, 77.0)
        self.assertFalse(ok_range)
        self.assertEqual(code_range, 'INVALID_COORDINATES')

        # Null Island (0.0, 0.0)
        ok_zero, code_zero, _, _ = verify_campus_presence(0.0, 0.0)
        self.assertFalse(ok_zero)
        self.assertEqual(code_zero, 'INVALID_COORDINATES')

    # --------------------------------------------------------------------------
    # 6. Unacceptable GPS Accuracy — Rejected
    # --------------------------------------------------------------------------
    def test_06_unacceptable_gps_accuracy_rejected(self):
        """Verifies rejection when device reports excessive uncertainty (> 50m)."""
        is_valid, code, msg, details = verify_campus_presence(
            lat=DEFAULT_CAMPUS_LAT,
            lon=DEFAULT_CAMPUS_LON,
            accuracy=125.0  # 125m error margin
        )
        self.assertFalse(is_valid)
        self.assertEqual(code, 'UNACCEPTABLE_ACCURACY')
        self.assertIn("High Accuracy GPS", msg)

    # --------------------------------------------------------------------------
    # 7. Stale Location Reading — Rejected
    # --------------------------------------------------------------------------
    def test_07_stale_location_reading_rejected(self):
        """Verifies rejection when location timestamp is older than max_age_seconds (120s)."""
        stale_epoch = time.time() - 300  # 5 minutes old
        is_valid, code, msg, details = verify_campus_presence(
            lat=DEFAULT_CAMPUS_LAT,
            lon=DEFAULT_CAMPUS_LON,
            accuracy=10.0,
            client_timestamp=stale_epoch
        )
        self.assertFalse(is_valid)
        self.assertEqual(code, 'STALE_LOCATION')
        self.assertIn("Stale", msg)

    # --------------------------------------------------------------------------
    # 8. Client-Supplied Fake is_inside_campus=true — Cannot Bypass Server
    # --------------------------------------------------------------------------
    def test_08_client_supplied_fake_flag_cannot_bypass_server(self):
        """Verifies that client passing is_inside_campus=true while outside cannot bypass backend."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = self.teacher.full_name

        # Coordinates in Basavanagudi / Bull Temple Road (~1.5 km away), with fake flag
        res = self.client.post('/attendance', data={
            'lat': '12.941305',
            'lon': '77.565467',
            'accuracy': '10.0',
            'is_inside_campus': 'true',  # FAKE CLIENT FLAG
            'client_timestamp': str(time.time()),
            'work_mode': 'Office'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        with app.app_context():
            today_str = get_ist_time().strftime("%Y-%m-%d")
            att = Attendance.query.filter_by(user_id=self.teacher_id, date=today_str).first()
            self.assertIsNone(att, "Spoofed client flag must NOT create attendance")

    # --------------------------------------------------------------------------
    # 9. Direct API Request Outside Campus — Rejected with 400
    # --------------------------------------------------------------------------
    def test_09_direct_api_request_outside_campus_rejected(self):
        """Verifies direct JSON/API request outside campus returns HTTP 400 with error details."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = self.teacher.full_name

        res = self.client.post('/attendance', json={
            'lat': 12.970000,
            'lon': 77.580000,
            'accuracy': 15.0,
            'client_timestamp': time.time()
        })

        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data['success'])
        self.assertEqual(data['reason_code'], 'OUTSIDE_CAMPUS')
        self.assertIn("BMS College of Commerce & Management", data['error'])

    # --------------------------------------------------------------------------
    # 10. QR Attendance Cannot Bypass Campus Geofence
    # --------------------------------------------------------------------------
    def test_10_qr_attendance_enforces_campus_geofence(self):
        """Verifies that scanning a QR code while off-campus is strictly rejected."""
        token = generate_rotating_qr_token(window_offset=0)

        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = self.teacher.full_name

        # 1. Off-campus coordinates with valid token -> REJECTED
        res_reject = self.client.post('/attendance/checkin', data={
            'token': token,
            'lat': '12.975000',
            'lon': '77.590000',
            'accuracy': '15.0',
            'client_timestamp': str(time.time())
        }, follow_redirects=True)

        self.assertEqual(res_reject.status_code, 200)
        with app.app_context():
            today_str = get_ist_time().strftime("%Y-%m-%d")
            att = Attendance.query.filter_by(user_id=self.teacher_id, date=today_str).first()
            self.assertIsNone(att, "Off-campus QR check-in must be rejected")

        # 2. On-campus coordinates with valid token -> ACCEPTED
        res_accept = self.client.post('/attendance/checkin', data={
            'token': token,
            'lat': str(DEFAULT_CAMPUS_LAT),
            'lon': str(DEFAULT_CAMPUS_LON),
            'accuracy': '10.0',
            'client_timestamp': str(time.time())
        }, follow_redirects=True)

        self.assertEqual(res_accept.status_code, 200)
        with app.app_context():
            today_str = get_ist_time().strftime("%Y-%m-%d")
            att_accept = Attendance.query.filter_by(user_id=self.teacher_id, date=today_str).first()
            self.assertIsNotNone(att_accept)
            self.assertEqual(att_accept.location_status, 'CAMPUS_VERIFIED')

    # --------------------------------------------------------------------------
    # 11. Unauthorized Users Cannot Modify Geofence Configuration
    # --------------------------------------------------------------------------
    def test_11_unauthorized_users_cannot_modify_geofence_configuration(self):
        """Verifies that non-admin faculty cannot alter campus geofence configuration (HTTP 403)."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.kiran_id)
            sess['user_id'] = self.kiran_id
            sess['role'] = 'Faculty'
            sess['name'] = self.faculty_kiran.full_name

        res = self.client.post('/admin/geofence/update', json={
            'radius_meters': 5000.0,
            'enabled': False
        })

        self.assertEqual(res.status_code, 403)
        # Verify configuration remained unaffected
        cfg = get_geofence_config()
        self.assertEqual(cfg['radius_meters'], DEFAULT_CAMPUS_RADIUS_METERS)
        self.assertTrue(cfg['enabled'])

    # --------------------------------------------------------------------------
    # 12. Existing Staff Workflows & Administrative Corrections Preserved
    # --------------------------------------------------------------------------
    def test_12_admin_manual_attendance_correction_preserved_with_audit(self):
        """Verifies authorized admin/HR can record manual attendance with justification & audit log."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.admin_id)
            sess['user_id'] = self.admin_id
            sess['role'] = 'admin'
            sess['name'] = self.admin.full_name

        test_date = '2026-10-20'
        res = self.client.post('/attendance/admin/manual-record', data={
            'user_id': str(self.teacher_id),
            'date': test_date,
            'check_in': '09:05 AM',
            'check_out': '05:15 PM',
            'reason': 'Official Academic Deputation at Bangalore City University'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)

        with app.app_context():
            att = Attendance.query.filter_by(user_id=self.teacher_id, date=test_date).first()
            self.assertIsNotNone(att)
            self.assertEqual(att.check_in, '09:05 AM')
            self.assertEqual(att.check_out, '05:15 PM')
            self.assertEqual(att.work_mode, 'Manual Correction')
            self.assertEqual(att.location_status, 'ADMIN_MANUAL_CORRECTION')

            # Verify audit trail record
            audit = AuditLog.query.filter(
                AuditLog.action.like('%Official Academic Deputation%')
            ).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(audit)
            self.assertIn(self.teacher.full_name, audit.action)

            # Clean test record
            db.session.delete(att)
            db.session.commit()

    # --------------------------------------------------------------------------
    # 13. Student Academic Attendance Remains Strictly Unaffected
    # --------------------------------------------------------------------------
    def test_13_student_academic_attendance_remains_unaffected(self):
        """Verifies that student academic attendance routes are untouched and require no GPS."""
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_user_id'] = str(self.teacher_id)
            sess['user_id'] = self.teacher_id
            sess['role'] = 'Faculty'
            sess['name'] = self.teacher.full_name

        # History route operates without GPS
        res = self.client.get('/academic-attendance/history')
        self.assertEqual(res.status_code, 200)

    # --------------------------------------------------------------------------
    # 14. Disabled Enforcement Safe Behavior
    # --------------------------------------------------------------------------
    def test_14_disabled_enforcement_safe_behavior(self):
        """Verifies that when geofence is disabled, it does not falsely report CAMPUS_VERIFIED."""
        update_geofence_config({'enabled': False})

        is_valid, code, msg, details = verify_campus_presence(
            lat=12.980000,
            lon=77.600000,
            accuracy=20.0
        )

        self.assertTrue(is_valid)
        self.assertEqual(code, 'GEOFENCE_UNENFORCED')
        self.assertFalse(details['enforced'])
        self.assertIn("disabled", msg)


if __name__ == '__main__':
    unittest.main()
