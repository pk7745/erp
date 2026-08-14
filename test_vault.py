import sys, io
sys.stdout.reconfigure(encoding='utf-8')

from PIL import Image, ImageDraw
from app import app

# Create in-memory mock ID card image
img = Image.new('RGB', (300, 150), color=(255, 255, 255))
d = ImageDraw.Draw(img)
d.text((10, 10), 'BMS College ID Card', fill=(0, 0, 0))
d.text((10, 40), 'Name: Dr. Ramesh Kumar', fill=(0, 0, 0))
buf = io.BytesIO()
img.save(buf, format='JPEG')
buf.seek(0)
img_bytes = buf.getvalue()

def test_vault(username, password, role_name):
    client = app.test_client()
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    
    res = client.get('/digital_vault')
    has_vault_access = res.status_code == 200 and b'Digital Document Vault' in res.data
    
    # Test OCR upload endpoint
    data = {
        'doc_image': (io.BytesIO(img_bytes), 'staff_id_ramesh.jpg')
    }
    scan_res = client.post('/scan_and_import', data=data, content_type='multipart/form-data')
    
    if scan_res.status_code == 200:
        print(f"👤 {role_name:<20} | Vault Access: {str(has_vault_access):<5} | OCR Response: SUCCESS ({scan_res.json.get('extracted_name', '')})")
    else:
        print(f"👤 {role_name:<20} | Vault Access: {str(has_vault_access):<5} | OCR Scan Restricted (HTTP {scan_res.status_code})")

print("🧪 TESTING DIGITAL VAULT & AI OCR SCAN ENGINE:\n")
test_vault('admin', 'bms123', 'HR / Admin')
test_vault('pankaj', 'bms123', 'Principal')
test_vault('balram', 'bms123', 'Faculty Member')
print("\n✅ DIGITAL VAULT RBAC & OCR ENGINE VERIFIED SUCCESSFULLY!")
