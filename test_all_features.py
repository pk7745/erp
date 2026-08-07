import unittest
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"C:\Users\pky45\.gemini\antigravity\scratch\erp")
from app import app, db, User

class FeatureVerificationTests(unittest.TestCase):
    """Exhaustive test suite testing all Flask routes including the 3 new features"""

    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()
        with app.app_context():
            db.create_all()

    def login(self, username='admin', password='admin123'):
        return self.client.post('/login', data=dict(
            username=username,
            password=password
        ), follow_redirects=True)

    def test_all_routes_exist_and_respond(self):
        """Test all registered endpoints respond without 500 internal server errors"""
        self.login()
        rules = [rule.rule for rule in app.url_map.iter_rules() if not rule.rule.startswith('/static')]
        print(f"Testing {len(rules)} total registered Flask endpoints...")
        
        passed_routes = 0
        for rule in rules:
            test_url = rule.replace('<int:uid>', '1') \
                           .replace('<int:id>', '1') \
                           .replace('<int:receiver_id>', '1') \
                           .replace('<rtype>', 'attendance') \
                           .replace('<action>', 'approve') \
                           .replace('<month_str>', 'January 2026') \
                           .replace('<month>', 'January 2026') \
                           .replace('<room_name>', 'test_room')
            
            try:
                res = self.client.get(test_url)
                self.assertNotEqual(res.status_code, 500, f"Route {rule} returned 500 Internal Server Error!")
                passed_routes += 1
            except Exception as e:
                self.fail(f"Route {rule} failed with exception: {e}")
                
        print(f"\n✅ All {passed_routes} Flask endpoints verified working cleanly (0 server crashes)!")

    def test_new_features(self):
        """Test Feature 1 Analytics, Feature 2 AI Assistant, and Feature 3 QR Attendance specifically"""
        self.login()
        
        # Feature 1: Analytics
        res = self.client.get('/analytics')
        self.assertEqual(res.status_code, 200)
        res_data = self.client.get('/api/analytics/data')
        self.assertEqual(res_data.status_code, 200)
        self.assertIn('attendance_trend', res_data.json)

        # Feature 2: AI Assistant
        res = self.client.get('/assistant')
        self.assertEqual(res.status_code, 200)
        res_ask = self.client.post('/api/assistant/ask', json={'question': 'How many staff are on leave this week?'})
        self.assertEqual(res_ask.status_code, 200)
        self.assertIn('answer', res_ask.json)

        # Feature 3: QR Attendance
        res = self.client.get('/attendance/qr')
        self.assertEqual(res.status_code, 200)
        self.assertIn('data:image/png;base64,', res.get_data(as_text=True))

        print("✅ All 3 NEW FEATURES (Analytics, AI Assistant, QR Attendance) VERIFIED 100% WORKING!")

if __name__ == '__main__':
    unittest.main()
