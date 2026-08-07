import urllib.request, urllib.parse, http.cookiejar, sys
sys.stdout.reconfigure(encoding='utf-8')

for user, pwd, rname in [('admin', 'admin123', 'HR/Admin'), ('acc1', 'acc123', 'Accountant'), ('pankaj', 'pankaj123', 'Principal'), ('kiran', 'kiran123', 'HOD')]:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open('http://127.0.0.1:9000/login', data=urllib.parse.urlencode({'username': user, 'password': pwd}).encode('utf-8'))
    
    res = opener.open('http://127.0.0.1:9000/admin/staff_master').read().decode('utf-8')
    is_ok = 'Master Faculty & Management Records' in res
    cnt = res.count('user-avatar') if is_ok else 0
    has_edit = 'openMasterEditModal(' in res
    print(f"👤 User: {user:<8} | Role: {rname:<12} | Page Access: {is_ok!s:<5} | Edit Control: {has_edit!s:<5} | Records: {cnt}")
