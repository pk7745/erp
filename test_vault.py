import urllib.request, urllib.parse, http.cookiejar, sys, io
sys.stdout.reconfigure(encoding='utf-8')

from PIL import Image, ImageDraw
img = Image.new('RGB', (300, 150), color=(255, 255, 255))
d = ImageDraw.Draw(img)
d.text((10,10), 'BMS College ID Card', fill=(0,0,0))
d.text((10,40), 'Name: Dr. Ramesh Kumar', fill=(0,0,0))
buf = io.BytesIO()
img.save(buf, format='JPEG')
img_bytes = buf.getvalue()

def test_vault(username, password, role_name):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    login_data = urllib.parse.urlencode({'username': username, 'password': password}).encode('utf-8')
    opener.open('http://127.0.0.1:9000/login', data=login_data)
    
    res = opener.open('http://127.0.0.1:9000/digital_vault').read().decode('utf-8')
    has_vault_access = 'Digital Document Vault' in res
    
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    header = f'--{boundary}\r\nContent-Disposition: form-data; name="doc_image"; filename="staff_id_ramesh.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
    footer = f'\r\n--{boundary}--\r\n'
    body = header.encode('utf-8') + img_bytes + footer.encode('utf-8')
    
    req = urllib.request.Request('http://127.0.0.1:9000/scan_and_import', data=body)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    
    try:
        scan_res = opener.open(req).read().decode('utf-8')
        print(f'👤 {role_name:<20} | Vault Access: {has_vault_access!s:<5} | OCR Response: {scan_res[:70]}...')
    except urllib.error.HTTPError as e:
        print(f'👤 {role_name:<20} | Vault Access: {has_vault_access!s:<5} | OCR Scan Restricted (HTTP {e.code})')

print('🧪 TESTING DIGITAL VAULT & AI OCR SCAN ENGINE:\n')
test_vault('admin', 'admin123', 'HR / Admin')
test_vault('pankaj', 'pankaj123', 'Principal')
test_vault('balram', 'balram123', 'Faculty Member')
