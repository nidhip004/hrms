#!/usr/bin/env python3
"""HRMS Phase 1 backend. Python 3.9+, standard library only. Data lives in SQLite (hrms.db).
Run: python3 server.py        (see README.md for configuration)"""
import os, sys, json, re, time, hmac, secrets, hashlib, sqlite3, base64, threading, smtplib, calendar, datetime as dt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from email.message import EmailMessage
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
DBP = os.environ.get('HRMS_DB', os.path.join(ROOT, 'hrms.db'))
UP = os.environ.get('HRMS_UPLOADS', os.path.join(os.path.dirname(DBP), 'uploads'))
PORT = int(os.environ.get('PORT', '8000'))
BASE = os.environ.get('HRMS_BASE_URL', 'http://localhost:%d' % PORT).rstrip('/')
SMTP_HOST = os.environ.get('SMTP_HOST', '')
DEV = not SMTP_HOST            # without SMTP, emails are kept in a dev inbox instead of being sent
CO = ['Internovo', 'OB Services', 'Interface']
EX = ('Resigned', 'Terminated', 'Inactive')
STAT = ('Active', 'On Notice') + EX
AST = ('Present', 'Half Day', 'Work From Home', 'On Leave')
LOCK = threading.Lock()
REQ_LOC = os.environ.get('HRMS_REQUIRE_LOCATION', '1') != '0'   # check-in/out must include the device location

HOLIDAYS_INTERNOVO_INTERFACE = [
    ('2026-01-01', 'New Year Eve', 'Internovo, Interface', 'Fixed'),
    ('2026-01-26', 'Republic day', 'Internovo, Interface', 'Fixed'),
    ('2026-02-19', 'Chhatrapati Shivaji Maharaj Jayanti', 'Internovo, Interface', 'Fixed'),
    ('2026-03-03', 'Holi', 'Internovo, Interface', 'Fixed'),
    ('2026-03-21', 'Ramzan-Id', 'Internovo, Interface', 'Fixed'),
    ('2026-04-03', 'Good Friday', 'Internovo, Interface', 'Fixed'),
    ('2026-05-01', 'Maharashtra day', 'Internovo, Interface', 'Fixed'),
    ('2026-08-15', 'Independence day', 'Internovo, Interface', 'Fixed'),
    ('2026-09-14', 'Ganesh Chaturthi', 'Internovo, Interface', 'Fixed'),
    ('2026-10-02', 'Gandhi Jayanti', 'Internovo, Interface', 'Fixed'),
    ('2026-10-20', 'Dussehra', 'Internovo, Interface', 'Fixed'),
    ('2026-11-09', 'Diwali', 'Internovo, Interface', 'Fixed'),
    ('2026-12-25', 'Christmas', 'Internovo, Interface', 'Fixed'),
]

HOLIDAYS_OB = [
    ('2026-01-14', 'Makar Sankranti', 'OB Services', 'Fixed'),
    ('2026-01-26', 'Republic Day', 'OB Services', 'Fixed'),
    ('2026-03-04', 'Holi', 'OB Services', 'Fixed'),
    ('2026-08-15', 'Independence Day', 'OB Services', 'Fixed'),
    ('2026-09-05', 'Janam Ashtami', 'OB Services', 'Fixed'),
    ('2026-10-02', 'Gandhi Jayanti', 'OB Services', 'Fixed'),
    ('2026-10-20', 'Dussehra', 'OB Services', 'Fixed'),
    ('2026-11-09', 'Diwali / Vishwakarma Day', 'OB Services', 'Fixed'),
    ('2026-12-25', 'Christmas', 'OB Services', 'Fixed'),
    ('2026-03-21', 'Eid', 'OB Services', 'Restricted'),
    ('2026-03-26', 'Ram Navmi', 'OB Services', 'Restricted'),
    ('2026-04-14', 'Baisakhi', 'OB Services', 'Restricted'),
    ('2026-05-27', 'Bakrid', 'OB Services', 'Restricted'),
    ('2026-08-28', 'Raksha Bandhan', 'OB Services', 'Restricted'),
    ('2026-09-14', 'Teej', 'OB Services', 'Restricted'),
    ('2026-09-17', 'Vishwakarma Puja', 'OB Services', 'Restricted'),
    ('2026-10-19', 'Durga Ashtami', 'OB Services', 'Restricted'),
    ('2026-10-26', 'Valmiki Jayanti', 'OB Services', 'Restricted'),
    ('2026-10-29', 'Karwa Chauth', 'OB Services', 'Restricted'),
    ('2026-11-11', 'Bhai Dooj', 'OB Services', 'Restricted'),
    ('2026-11-16', 'Chhat Pooja', 'OB Services', 'Restricted'),
    ('2026-11-24', "Guru Nanak's Birthday", 'OB Services', 'Restricted'),
]

SCHEMA = '''
create table if not exists emp(id integer primary key autoincrement,name text,gender text,dob text,pEmail text,oEmail text unique collate nocase,mobile text,emerg text,cAddr text,pAddr text,company text,dept text,desig text,manager integer default 0,doj text,loc text,prob integer default 3,probEnd text,status text default 'Active',role text default 'emp',scope text,pan text,aadhaar text,bank text,acct text,ifsc text);
create table if not exists usr(id integer primary key references emp(id),salt text,hash text,pend integer default 0,tok text,kind text,exp real,fails integer default 0,locked integer default 0,off integer default 0,onb integer default 0);
create table if not exists sess(tok text primary key,emp integer,exp real);
create table if not exists sal(id integer primary key autoincrement,emp integer,frm text,tto text,gross real,basic real,hra real,sa real,pt real,net real);
create table if not exists att(emp integer,day text,tin text,tout text,st text,late integer default 0,lat_in real,lng_in real,acc_in real,lat_out real,lng_out real,acc_out real,primary key(emp,day));
create table if not exists lv(id integer primary key autoincrement,emp integer,type text,frm text,tto text,days real,half integer default 0,reason text,st text,paid real,lwp real,by integer);
create table if not exists types(name text primary key,kind text);
create table if not exists hol(id integer primary key autoincrement,day text,name text,company text,kind text default 'Fixed');
create table if not exists docs(id integer primary key autoincrement,emp integer,name text,date text,size text,path text);
create table if not exists hist(id integer primary key autoincrement,emp integer,date text,fld text,ov text,nv text,by text);
create table if not exists audit(id integer primary key autoincrement,t text,u text,a text,scope text);
create table if not exists mail(id integer primary key autoincrement,to_ text,subject text,name text,login text,kind text,tok text,at text);
create table if not exists kv(k text primary key,v text);
'''

class Err(Exception):
    def __init__(s, code, msg, fields=None): s.code, s.msg, s.fields = code, msg, fields

def db():
    c = sqlite3.connect(DBP, timeout=10); c.row_factory = sqlite3.Row; c.execute('pragma foreign_keys=on'); return c
def rows(c, sql, a=()): return [dict(r) for r in c.execute(sql, a)]
def one(c, sql, a=()):
    r = c.execute(sql, a).fetchone(); return dict(r) if r else None
def today(): return dt.date.today()
def addm(s, n):
    d = dt.date.fromisoformat(s); m = d.month - 1 + n; y = d.year + m // 12; m = m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()
def isodate(s):
    try: return dt.date.fromisoformat(s).isoformat()
    except Exception: return None
def sha(t): return hashlib.sha256(t.encode()).hexdigest()
def hpw(p, salt): return hashlib.scrypt(p.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32).hex()
def setpw(c, uid, p):
    salt = secrets.token_hex(8); c.execute('update usr set salt=?,hash=? where id=?', (salt, hpw(p, salt), uid))
def okpw(p): return len(p) >= 8 and re.search('[a-z]', p) and re.search('[A-Z]', p) and re.search(r'\d', p)
PWMSG = 'Needs 8+ characters with upper case, lower case and a number'
MAIL = re.compile(r'^\S+@\S+\.\S+$')

def sees(u, e): return u['role'] == 'hr' and (u['scope'] == 'all' or e['company'] == u['scope'])
def can_admin(u, e): return u['id'] != e['id'] and sees(u, e) and not (e['role'] == 'hr' and e['scope'] == 'all' and u['scope'] != 'all')
def audit(c, who, a, scope=''):
    c.execute('insert into audit(t,u,a,scope) values(?,?,?,?)', (time.strftime('%d %b %Y %H:%M'), who if isinstance(who, str) else who['name'], a, scope))
def need(E):
    if E: raise Err(400, 'Please fix the highlighted fields', E)

# ---------- email ----------
def send_smtp(to, sub, body):
    try:
        m = EmailMessage(); m['To'] = to; m['Subject'] = sub; m['From'] = os.environ.get('SMTP_FROM', os.environ.get('SMTP_USER', 'hrms@localhost')); m.set_content(body)
        with smtplib.SMTP(SMTP_HOST, int(os.environ.get('SMTP_PORT', '587')), timeout=20) as s:
            s.starttls()
            if os.environ.get('SMTP_USER'): s.login(os.environ['SMTP_USER'], os.environ.get('SMTP_PASS', ''))
            s.send_message(m)
    except Exception as ex: print('SMTP error:', ex)
def queue_mail(c, e, kind):
    tok = secrets.token_hex(16)
    c.execute('update usr set tok=?,kind=?,exp=? where id=?', (sha(tok), kind, time.time() + 72 * 3600, e['id']))
    to = (e['pEmail'] or e['oEmail']) if kind == 'invite' else e['oEmail']
    sub = 'Welcome to HRMS: create your password' if kind == 'invite' else 'Reset your HRMS password'
    link = '%s/#invite=%s' % (BASE, tok)
    body = ('Hi %s,\n\nHR has created your HRMS account. Create your password using the link below. Your sign-in email will be %s.\n\n%s\n\nThe link is valid for 72 hours.' if kind == 'invite'
            else 'Hi %s,\n\nA password reset was requested for your HRMS account (%s).\n\n%s\n\nThe link is valid for 72 hours. If you did not expect this, contact HR.') % (e['name'], e['oEmail'], link)
    c.execute('insert into mail(to_,subject,name,login,kind,tok,at) values(?,?,?,?,?,?,?)', (to, sub, e['name'], e['oEmail'], kind, tok if DEV else '', time.strftime('%d %b %Y %H:%M')))
    if DEV: print('[dev inbox] %s -> %s' % (sub, link))
    else: threading.Thread(target=send_smtp, args=(to, sub, body), daemon=True).start()
    return to

# ---------- leave helpers ----------
def cnt(c, f, t, half, co=None):
    if half: return 0.5
    if co: hol = {r[0] for r in c.execute("select day from hol where (company like ? or company = 'All') and kind = 'Fixed'", ('%' + co + '%',))}
    else: hol = {r[0] for r in c.execute("select day from hol where kind = 'Fixed'")}
    n = 0; d = dt.date.fromisoformat(f); e = dt.date.fromisoformat(t)
    while d <= e:
        if d.weekday() < 5 and d.isoformat() not in hol: n += 1
        d += dt.timedelta(1)
    return n
def balance(c, e):
    t = today(); s = '%d-04-01' % (t.year if t.month >= 4 else t.year - 1)
    st = max(s, (dt.date.fromisoformat(e['probEnd']) + dt.timedelta(1)).isoformat()); a = dt.date.fromisoformat(st); cr = 0
    if a <= t: cr = min(12, (t.year - a.year) * 12 + t.month - a.month + 1)
    used = c.execute("select coalesce(sum(l.paid),0) from lv l join types y on y.name=l.type where l.emp=? and l.st='Approved' and y.kind='paid' and l.frm>=?", (e['id'], s)).fetchone()[0]
    return cr - used
def set_att(c, emp, day, **kw):
    c.execute('insert or ignore into att(emp,day) values(?,?)', (emp, day))
    for k, v in kw.items(): c.execute('update att set %s=? where emp=? and day=?' % k, (v, emp, day))

# ---------- state (what this user may see) ----------
PUBF = ('id', 'name', 'desig', 'dept', 'company', 'manager', 'status', 'role', 'scope', 'gender')
def mask(e):
    for k in ('pan', 'aadhaar', 'bank', 'acct', 'ifsc'):
        if e.get(k): e[k] = '••••' + e[k][-4:]
    return e
def state(c, u):
    hr = u['role'] == 'hr'; allemp = rows(c, 'select * from emp order by id')
    if hr:
        vis = [e for e in allemp if sees(u, e)]; ids = {e['id'] for e in vis}; lvids = ids
        emps = [dict(e) if e['id'] == u['id'] else mask(dict(e)) for e in vis]
    else:
        team = [e for e in allemp if e['manager'] == u['id']]; mg = [e for e in allemp if e['id'] == u['manager']]
        ids = {u['id']}; lvids = ids | {e['id'] for e in team}
        emps = [dict(u)] + [{k: e[k] for k in PUBF} for e in mg + team if e['id'] != u['id']]
    inn = lambda s: ','.join(str(int(i)) for i in s) or '0'
    cut = (today() - dt.timedelta(100)).isoformat()
    out = {'me': u['id'], 'dev': DEV, 'emps': emps,
        'users': rows(c, 'select id,pend,locked,off,onb from usr where id in (%s)' % inn(ids)),
        'sal': [{'emp': r['emp'], 'from': r['frm'], 'to': r['tto'] or '', 'gross': r['gross'], 'basic': r['basic'], 'hra': r['hra'], 'sa': r['sa'], 'pt': r['pt'], 'net': r['net']} for r in rows(c, 'select * from sal where emp in (%s)' % inn(ids))],
        'att': {'%d|%s' % (r['emp'], r['day']): {'in': r['tin'] or '', 'out': r['tout'] or '', 'st': r['st'], 'late': r['late'], 'li': ({'lat': r['lat_in'], 'lng': r['lng_in'], 'acc': r['acc_in']} if r['lat_in'] is not None else None), 'lo': ({'lat': r['lat_out'], 'lng': r['lng_out'], 'acc': r['acc_out']} if r['lat_out'] is not None else None)} for r in rows(c, 'select * from att where emp in (%s) and day>=?' % inn(ids), (cut,))},
        'lv': [{'id': r['id'], 'emp': r['emp'], 'type': r['type'], 'from': r['frm'], 'to': r['tto'], 'days': r['days'], 'half': r['half'], 'reason': r['reason'], 'st': r['st'], 'paid': r['paid'], 'lwp': r['lwp']} for r in rows(c, 'select * from lv where emp in (%s) order by id desc' % inn(lvids))],
        'docs': rows(c, 'select emp,name,date,size from docs where emp in (%s) order by id' % inn(ids)),
        'hist': [{'emp': r['emp'], 'date': r['date'], 'field': r['fld'], 'old': r['ov'], 'new': r['nv'], 'by': r['by']} for r in rows(c, 'select * from hist where emp in (%s) order by id desc' % inn(ids))] if hr else [],
        'types': rows(c, 'select name,kind from types order by rowid'), 'hol': rows(c, 'select id, day, coalesce(name, "") as name, coalesce(company, "All") as company, coalesce(kind, "Fixed") as kind from hol order by day'), 'hol_days': [r['day'] for r in rows(c, "select day from hol where kind = 'Fixed' order by day")],
        'audit': [], 'mail': []}
    if hr:
        out['audit'] = rows(c, 'select t,u,a from audit order by id desc limit 60') if u['scope'] == 'all' else rows(c, 'select t,u,a from audit where scope=? order by id desc limit 60', (u['scope'],))
        if DEV:
            names = {e['oEmail'] for e in vis}
            out['mail'] = [{'to': m['to_'], 'subject': m['subject'], 'name': m['name'], 'login': m['login'], 'kind': m['kind'], 'tok': m['tok'], 'at': m['at']} for m in rows(c, 'select * from mail order by id desc limit 30') if m['login'] in names]
    return out

# ---------- routes ----------
ROUTES = []
def R(method, pat, pub=False):
    def d(fn): ROUTES.append((method, re.compile('^' + pat + '$'), fn, pub)); return fn
    return d

@R('GET', '/api/public', True)
def h_public(c, u, b, q):
    if not DEV: return {'dev': False}
    live = {x['tok'] for x in rows(c, "select tok from usr where tok is not null and tok!='' and exp>?", (time.time(),))}
    demo = [{'email': e['oEmail'], 'role': 'HR' if e['role'] == 'hr' else 'Employee', 'pend': bool(e['pend'])} for e in rows(c, "select e.oEmail,e.role,u.pend from emp e join usr u on u.id=e.id where e.status not in ('Resigned','Terminated','Inactive')")] if one(c, "select v from kv where k='demo'") else []
    mails = [{'to': m['to_'], 'subject': m['subject'], 'name': m['name'], 'login': m['login'], 'kind': m['kind'], 'tok': m['tok'], 'at': m['at']} for m in rows(c, 'select * from mail order by id desc limit 20') if sha(m['tok']) in live]
    return {'dev': True, 'demo': demo, 'mail': mails}

@R('POST', '/api/login', True)
def h_login(c, u, b, q):
    em = (b.get('email') or '').strip().lower(); pw = b.get('password') or ''
    e = one(c, 'select * from emp where lower(oEmail)=?', (em,)); x = one(c, 'select * from usr where id=?', (e['id'],)) if e else None
    if not e or not x or (not x['hash'] and not x['pend']): raise Err(401, 'Incorrect email or password')
    if x['off'] or e['status'] in EX: raise Err(403, 'This account is disabled. Contact HR.')
    if x['pend']: raise Err(403, 'Your account is not activated yet. Use the link in your invitation email to create a password.')
    if x['locked']: raise Err(403, 'Account locked after too many attempts. Ask HR to reset your password.')
    if not hmac.compare_digest(hpw(pw, x['salt']), x['hash']):
        n = x['fails'] + 1; c.execute('update usr set fails=?,locked=? where id=?', (n, 1 if n >= 5 else 0, e['id'])); c.commit()
        raise Err(401, 'Too many attempts. Account locked; ask HR to reset your password.' if n >= 5 else 'Incorrect email or password')
    sid = secrets.token_hex(24); c.execute('update usr set fails=0 where id=?', (e['id'],)); c.execute('insert into sess values(?,?,?)', (sid, e['id'], time.time() + 8 * 3600))
    return {'ok': True, '_cookie': sid}

@R('POST', '/api/logout', True)
def h_logout(c, u, b, q):
    return {'ok': True, '_logout': True}

@R('GET', '/api/state')
def h_state(c, u, b, q): return state(c, u)

def token_user(c, tok):
    x = one(c, "select * from usr where tok=? and tok!='' and exp>?", (sha(tok or ''), time.time()))
    if not x: raise Err(410, 'This link is invalid or has expired. Ask HR to send a new one.')
    return x
@R('GET', '/api/invite/(\\w+)', True)
def h_invite(c, u, b, q, tok):
    x = token_user(c, tok); e = one(c, 'select name,oEmail from emp where id=?', (x['id'],)); return {'name': e['name'], 'login': e['oEmail'], 'kind': x['kind']}
@R('POST', '/api/setup', True)
def h_setup(c, u, b, q):
    x = token_user(c, b.get('token')); p = b.get('password') or ''; E = {}
    if not okpw(p): E['password'] = PWMSG
    if p != (b.get('confirm') or ''): E['confirm'] = 'Passwords do not match'
    need(E); setpw(c, x['id'], p)
    c.execute("update usr set tok='',pend=0,fails=0,locked=0,onb=? where id=?", (1 if x['kind'] == 'invite' else x['onb'], x['id']))
    e = one(c, 'select * from emp where id=?', (x['id'],)); audit(c, e['name'], 'Accepted invitation and created password' if x['kind'] == 'invite' else 'Reset own password', e['company'])
    return {'login': e['oEmail']}

@R('POST', '/api/me/password')
def h_mepw(c, u, b, q):
    x = one(c, 'select * from usr where id=?', (u['id'],)); E = {}; p = b.get('password') or ''
    if not hmac.compare_digest(hpw(b.get('current') or '', x['salt']), x['hash']): E['current'] = 'Current password is incorrect'
    if not okpw(p): E['password'] = PWMSG
    elif p == b.get('current'): E['password'] = 'Choose a different password'
    if p != (b.get('confirm') or ''): E['confirm'] = 'Passwords do not match'
    need(E); setpw(c, u['id'], p); audit(c, u, 'Changed own password', u['company']); return {'msg': 'Password updated'}

SELFK = ('pEmail', 'mobile', 'emerg', 'cAddr', 'pAddr')
@R('POST', '/api/me/profile')
def h_meprofile(c, u, b, q):
    o = {k: (b.get(k) or '').strip() for k in SELFK}; E = {}
    if not MAIL.match(o['pEmail']): E['pEmail'] = 'Enter a valid email'
    if not re.match(r'^\d{10}$', o['mobile']): E['mobile'] = 'Enter 10 digits'
    if not re.match(r'^\d{10}$', o['emerg']): E['emerg'] = 'Enter 10 digits'
    if not o['cAddr']: E['cAddr'] = 'Required'
    need(E); c.execute('update emp set pEmail=?,mobile=?,emerg=?,cAddr=?,pAddr=? where id=?', (*[o[k] for k in SELFK], u['id']))
    onb = one(c, 'select onb from usr where id=?', (u['id'],))['onb']; c.execute('update usr set onb=0 where id=?', (u['id'],)); audit(c, u, 'Updated own contact details', u['company'])
    return {'msg': 'You are all set. Welcome aboard!' if onb else 'Details updated'}
@R('POST', '/api/me/skip-onboarding')
def h_skip(c, u, b, q): c.execute('update usr set onb=0 where id=?', (u['id'],)); return {}

# employees
EF = ['name', 'dob', 'gender', 'pEmail', 'oEmail', 'mobile', 'emerg', 'cAddr', 'pAddr', 'company', 'dept', 'desig', 'manager', 'doj', 'loc', 'prob', 'status']
SF = ['pan', 'aadhaar', 'bank', 'acct', 'ifsc']
def clean_emp(c, u, b, cur):
    o = dict(cur) if cur else {'manager': 0, 'prob': 3, 'status': 'Active', 'gender': 'Male', 'company': CO[0]}
    for k in EF + SF:
        if k in b: o[k] = b[k].strip() if isinstance(b[k], str) else b[k]
    E = {}; req = lambda k, m: E.__setitem__(k, m) if not o.get(k) else None
    req('name', 'Name is required'); req('doj', 'Date of joining is required')
    if not o.get('oEmail'): E['oEmail'] = 'Official email is required'
    elif not MAIL.match(o['oEmail']): E['oEmail'] = 'Enter a valid email'
    elif one(c, 'select id from emp where lower(oEmail)=? and id!=?', (o['oEmail'].lower(), cur['id'] if cur else 0)): E['oEmail'] = 'This email is already in use'
    if not cur and not o.get('pEmail'): E['pEmail'] = 'Required to send the invitation'
    elif o.get('pEmail') and not MAIL.match(o['pEmail']): E['pEmail'] = 'Enter a valid email'
    for k in ('mobile', 'emerg'):
        if o.get(k) and not re.match(r'^\d{10}$', str(o[k])): E[k] = 'Enter 10 digits'
    if o.get('doj') and not isodate(o['doj']): E['doj'] = 'Invalid date'
    if o.get('dob') and not isodate(o['dob']): E['dob'] = 'Invalid date'
    if o.get('gender') not in ('Male', 'Female'): E['gender'] = 'Choose Male or Female'
    if o.get('company') not in CO or (u['scope'] != 'all' and o['company'] != u['scope']): E['company'] = 'Company not allowed'
    if o.get('status') not in STAT: E['status'] = 'Invalid status'
    try: o['prob'] = int(o.get('prob') or 0); o['manager'] = int(o.get('manager') or 0)
    except Exception: E['prob'] = 'Enter a number'
    if not E.get('prob') and not 0 <= o['prob'] <= 12: E['prob'] = 'Between 0 and 12'
    if o['manager'] and (not one(c, 'select id from emp where id=?', (o['manager'],)) or (cur and o['manager'] == cur['id'])): E['manager'] = 'Invalid manager'
    if o.get('pan') and not re.match(r'^[A-Z]{5}\d{4}[A-Z]$', o['pan']): E['pan'] = 'Format: ABCDE1234F'
    if o.get('aadhaar') and not re.match(r'^\d{12}$', o['aadhaar']): E['aadhaar'] = 'Enter 12 digits'
    if o.get('ifsc') and not re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', o['ifsc']): E['ifsc'] = 'Format: HDFC0001234'
    need(E)
    if not E: o['probEnd'] = addm(o['doj'], o['prob'])
    return o
COLS = EF + SF + ['probEnd', 'role', 'scope']
@R('POST', '/api/employees')
def h_emp_new(c, u, b, q):
    if u['role'] != 'hr': raise Err(403, 'HR access required')
    o = clean_emp(c, u, b, None); o['role'] = 'emp'; o['scope'] = o['company']
    cur = c.execute('insert into emp(%s) values(%s)' % (','.join(COLS), ','.join('?' * len(COLS))), [o.get(k) for k in COLS]); eid = cur.lastrowid
    c.execute('insert into usr(id,pend) values(?,1)', (eid,)); e = one(c, 'select * from emp where id=?', (eid,)); to = queue_mail(c, e, 'invite')
    audit(c, u, 'Added employee ' + o['name'], o['company']); return {'id': eid, 'to': to, 'msg': 'Employee added. Invitation emailed to ' + to}
@R('POST', '/api/employees/(\\d+)')
def h_emp_edit(c, u, b, q, i):
    e = one(c, 'select * from emp where id=?', (int(i),))
    if not e or not sees(u, e): raise Err(404, 'Employee not found')
    o = clean_emp(c, u, b, e)
    if e['role'] == 'hr': o['scope'] = e['scope']
    elif o['company'] != e['company']: o['scope'] = o['company']
    nm = lambda x: (one(c, 'select name from emp where id=?', (x,)) or {'name': 'None'})['name'] if x else 'None'
    for k in ('status', 'company', 'dept', 'desig', 'manager'):
        if e[k] != o[k]: c.execute('insert into hist(emp,date,fld,ov,nv,by) values(?,?,?,?,?,?)', (e['id'], today().isoformat(), k, nm(e[k]) if k == 'manager' else e[k], nm(o[k]) if k == 'manager' else o[k], u['name']))
    cols = [k for k in COLS if k != 'role']; c.execute('update emp set %s where id=?' % ','.join(k + '=?' for k in cols), [o.get(k) for k in cols] + [e['id']])
    if o['status'] in EX: c.execute('delete from sess where emp=?', (e['id'],))
    audit(c, u, 'Updated ' + o['name'], o['company']); return {'msg': 'Saved'}
@R('POST', '/api/employees/(\\d+)/reveal')
def h_reveal(c, u, b, q, i):
    e = one(c, 'select * from emp where id=?', (int(i),))
    if not e or not sees(u, e): raise Err(404, 'Employee not found')
    audit(c, u, 'Viewed statutory data of ' + e['name'], e['company']); return {k: e[k] or '' for k in SF}

# account administration
@R('POST', '/api/users/(\\d+)/(reset|resend|unlock|toggle|role)')
def h_user(c, u, b, q, i, act):
    e = one(c, 'select * from emp where id=?', (int(i),))
    if not e or not can_admin(u, e): raise Err(403, 'You cannot manage this account')
    x = one(c, 'select * from usr where id=?', (e['id'],)); sc = e['company']
    if act == 'reset':
        to = queue_mail(c, e, 'reset'); audit(c, u, 'Sent password reset email to ' + e['name'], sc); return {'msg': 'Password reset email sent to ' + to}
    if act == 'resend':
        if not x['pend']: raise Err(400, 'Account is already active')
        to = queue_mail(c, e, 'invite'); audit(c, u, 'Resent invitation to ' + e['name'], sc); return {'msg': 'Invitation resent to ' + to}
    if act == 'unlock': c.execute('update usr set locked=0,fails=0 where id=?', (e['id'],)); audit(c, u, 'Unlocked ' + e['name'], sc); return {'msg': 'Account unlocked'}
    if act == 'toggle':
        off = 0 if x['off'] else 1; c.execute('update usr set off=? where id=?', (off, e['id']))
        if off: c.execute('delete from sess where emp=?', (e['id'],))
        audit(c, u, ('Disabled ' if off else 'Enabled ') + e['name'], sc); return {'msg': 'Account disabled' if off else 'Account enabled'}
    if u['scope'] != 'all': raise Err(403, 'Only the main HR can change access')
    v = b.get('access')
    if v not in ['emp'] + CO + ['all']: raise Err(400, 'Invalid access level')
    if e['role'] == 'hr' and e['scope'] == 'all' and v != 'all' and c.execute("select count(*) from emp where role='hr' and scope='all' and status not in ('Resigned','Terminated','Inactive')").fetchone()[0] < 2: raise Err(400, 'At least one main HR must remain')
    role = 'emp' if v == 'emp' else 'hr'; scope = e['company'] if v == 'emp' else v
    c.execute('update emp set role=?,scope=? where id=?', (role, scope, e['id'])); audit(c, u, 'Access for %s: %s' % (e['name'], 'Employee' if v == 'emp' else 'HR ' + v), sc); return {'msg': 'Access updated'}

# salary
@R('POST', '/api/salary')
def h_salary(c, u, b, q):
    e = one(c, 'select * from emp where id=?', (int(b.get('emp') or 0),))
    if not e or not sees(u, e) or e['id'] == u['id']: raise Err(403, 'You cannot change this salary record')
    f = isodate(b.get('from') or ''); E = {}
    try: g = float(b.get('gross'))
    except Exception: g = 0
    prev = one(c, "select * from sal where emp=? and (tto is null or tto='') order by frm desc limit 1", (e['id'],))
    if not f: E['from'] = 'Choose a date'
    elif prev and f <= prev['frm']: E['from'] = 'Must be after ' + prev['frm']
    if g <= 0: E['gross'] = 'Enter the gross amount'
    need(E); n = lambda k: float(b.get(k) or 0)
    if prev: c.execute('update sal set tto=? where id=?', ((dt.date.fromisoformat(f) - dt.timedelta(1)).isoformat(), prev['id']))
    c.execute('insert into sal(emp,frm,tto,gross,basic,hra,sa,pt,net) values(?,?,?,?,?,?,?,?,?)', (e['id'], f, '', g, n('basic'), n('hra'), n('sa'), n('pt'), float(b['net']) if b.get('net') not in (None, '') else g - n('pt')))
    audit(c, u, 'Salary revision for ' + e['name'], e['company']); return {'msg': 'Revision added'}

# attendance
def read_loc(b):
    try: lat = float(b.get('lat')); lng = float(b.get('lng')); acc = float(b.get('acc') or 0)
    except Exception: return None
    return (lat, lng, acc) if -90 <= lat <= 90 and -180 <= lng <= 180 and acc >= 0 else None
@R('POST', '/api/attendance/(checkin|checkout)')
def h_clock(c, u, b, q, act):
    d = today().isoformat(); a = one(c, 'select * from att where emp=? and day=?', (u['id'], d)) or {}; now = time.strftime('%H:%M'); loc = read_loc(b)
    if not loc and REQ_LOC: raise Err(400, 'Your location is required. Allow location access in your browser and try again.')
    lc = (lambda k: {'lat_' + k: loc[0], 'lng_' + k: loc[1], 'acc_' + k: loc[2]} if loc else {})
    if act == 'checkin':
        if a.get('tin'): raise Err(400, 'Already checked in at ' + a['tin'])
        set_att(c, u['id'], d, tin=now, tout='', st=a.get('st') or 'Present', **lc('in')); return {'msg': 'Checked in. Location recorded.'}
    if not a.get('tin'): raise Err(400, 'Check in first')
    if a.get('tout'): raise Err(400, 'Already checked out at ' + a['tout'])
    set_att(c, u['id'], d, tout=now, **lc('out')); return {'msg': 'Checked out. Location recorded.'}
@R('POST', '/api/attendance/mark')
def h_mark(c, u, b, q):
    e = one(c, 'select * from emp where id=?', (int(b.get('emp') or 0),)); day = isodate(b.get('date') or '')
    if not e or not sees(u, e) or not day: raise Err(404, 'Not found')
    if not (b.get('reason') or '').strip(): raise Err(400, 'Enter a reason before correcting attendance')
    if 'status' in b:
        if b['status'] not in AST + ('', None): raise Err(400, 'Invalid status')
        set_att(c, e['id'], day, st=b['status'] or None)
    if 'late' in b: set_att(c, e['id'], day, late=1 if b['late'] else 0)
    audit(c, u, 'Attendance %s %s: %s (%s)' % (day, e['name'], b.get('status', 'late %s' % b.get('late')), b['reason'].strip()), e['company']); return {}

# leave
@R('POST', '/api/leaves')
def h_apply(c, u, b, q):
    ty = one(c, 'select * from types where name=?', (b.get('type'),)); f = isodate(b.get('from') or ''); t = isodate(b.get('to') or '') or f; half = 1 if b.get('half') else 0; E = {}
    if not ty: E['type'] = 'Choose a type'
    if not f: E['from'] = 'Choose a date'
    elif t < f: E['to'] = 'End date is before the start'
    if half and f != t: E['half'] = 'Half day needs a single date'
    if not (b.get('reason') or '').strip(): E['reason'] = 'Reason is required'
    days = cnt(c, f, t, half, u.get('company')) if f and t >= f else 0
    if f and t >= f and not half and not days: E['from'] = 'No working days in this range'
    need(E); c.execute("insert into lv(emp,type,frm,tto,days,half,reason,st) values(?,?,?,?,?,?,?,'Pending')", (u['id'], ty['name'], f, t, days, half, b['reason'].strip()))
    low = ty['kind'] == 'paid' and days > balance(c, u)
    return {'msg': 'Submitted. Your balance is lower than the days requested; the excess will be treated as LWP at approval.' if low else 'Request submitted for approval'}
@R('POST', '/api/leaves/(\\d+)/(decide|cancel)')
def h_leave(c, u, b, q, i, act):
    l = one(c, 'select * from lv where id=?', (int(i),)); e = one(c, 'select * from emp where id=?', (l['emp'],)) if l else None
    if not l: raise Err(404, 'Request not found')
    if act == 'cancel':
        if l['emp'] != u['id'] or l['st'] != 'Pending': raise Err(403, 'Cannot cancel this request')
        c.execute("update lv set st='Cancelled' where id=?", (l['id'],)); return {'msg': 'Request cancelled'}
    if l['st'] != 'Pending' or e['id'] == u['id'] or not (e['manager'] == u['id'] or sees(u, e)): raise Err(403, 'You cannot decide this request')
    ovr = u['role'] == 'hr' and e['manager'] and e['manager'] != u['id']
    if not b.get('approve'):
        c.execute("update lv set st='Rejected',by=? where id=?", (u['id'], l['id'])); audit(c, u, 'Rejected %s for %s%s' % (l['type'], e['name'], ' (HR override)' if ovr else ''), e['company']); return {'msg': 'Rejected'}
    k = one(c, 'select kind from types where name=?', (l['type'],))['kind']; paid = lwp = 0
    if k == 'paid': paid = max(0, min(l['days'], balance(c, e))); lwp = l['days'] - paid
    c.execute("update lv set st='Approved',by=?,paid=?,lwp=? where id=?", (u['id'], paid, lwp, l['id']))
    hol = {r[0] for r in c.execute("select day from hol where (company like ? or company = 'All') and kind = 'Fixed'", ('%' + (e['company'] or '') + '%',))}
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in hol: set_att(c, e['id'], d.isoformat(), st='Work From Home' if k == 'wfh' else 'Half Day' if l['half'] else 'On Leave')
        d += dt.timedelta(1)
    audit(c, u, 'Approved %s for %s%s' % (l['type'], e['name'], ' (HR override)' if ovr else ''), e['company'])
    return {'msg': 'Approved. %s day(s) beyond balance treated as LWP.' % lwp if lwp else 'Approved. Balance updated.'}

# documents (stored on disk; employee download is a Phase 2 feature)
@R('POST', '/api/docs')
def h_doc(c, u, b, q):
    e = one(c, 'select * from emp where id=?', (int(b.get('emp') or u['id']),))
    if not e or not (e['id'] == u['id'] or sees(u, e)): raise Err(403, 'Not allowed')
    name = re.sub(r'[^\w.\- ]', '_', (b.get('name') or 'document'))[:80]
    if name.rsplit('.', 1)[-1].lower() not in ('pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx'): raise Err(400, 'Allowed types: PDF, PNG, JPG, DOC, DOCX')
    try: raw = base64.b64decode(b.get('data') or '', validate=True)
    except Exception: raise Err(400, 'Invalid file')
    if not raw or len(raw) > 4 * 1024 * 1024: raise Err(400, 'File must be under 4 MB')
    os.makedirs(UP, exist_ok=True); p = os.path.join(UP, secrets.token_hex(12))
    with open(p, 'wb') as f: f.write(raw)
    c.execute('insert into docs(emp,name,date,size,path) values(?,?,?,?,?)', (e['id'], name, today().isoformat(), '%d KB' % max(1, len(raw) // 1024), p)); audit(c, u, 'Document uploaded for ' + e['name'], e['company']); return {'msg': 'Document uploaded'}

# settings (main HR only: they affect every company)
@R('POST', '/api/types')
def h_type(c, u, b, q):
    if u['scope'] != 'all' or u['role'] != 'hr': raise Err(403, 'Only the main HR can change this')
    n = (b.get('name') or '').strip()
    if not n or one(c, 'select name from types where lower(name)=?', (n.lower(),)) or b.get('kind') not in ('paid', 'lwp', 'wfh'): raise Err(400, 'Enter a new, unique name', {'name': 'Enter a new, unique name'})
    c.execute('insert into types values(?,?)', (n, b['kind'])); audit(c, u, 'Added leave type ' + n); return {}
@R('POST', '/api/holidays')
def h_hol(c, u, b, q):
    if u['scope'] != 'all' and u['role'] != 'hr': raise Err(403, 'Only HR can change this')
    d = isodate(b.get('day') or '')
    if not d: raise Err(400, 'Choose a date')
    name = (b.get('name') or '').strip()
    co = (b.get('company') or 'All').strip()
    kind = (b.get('kind') or 'Fixed').strip()
    c.execute('insert into hol(day,name,company,kind) values(?,?,?,?)', (d, name, co, kind))
    audit(c, u, 'Added holiday %s (%s, %s, %s)' % (d, name, co, kind))
    return {}

@R('POST', '/api/holidays/delete')
def h_del_hol(c, u, b, q):
    if u['scope'] != 'all' and u['role'] != 'hr': raise Err(403, 'Only HR can change this')
    hid = b.get('id')
    day = b.get('day')
    if hid: c.execute('delete from hol where id=?', (hid,))
    elif day: c.execute('delete from hol where day=?', (day,))
    audit(c, u, 'Deleted holiday %s' % (hid or day))
    return {}

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    server_version = 'HRMS'
    def log_message(s, f, *a): pass
    def reply(s, code, body, ctype='application/json', cookie=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        s.send_response(code); s.send_header('Content-Type', ctype); s.send_header('Content-Length', str(len(data))); s.send_header('Cache-Control', 'no-store')
        s.send_header('X-Content-Type-Options', 'nosniff'); s.send_header('X-Frame-Options', 'DENY'); s.send_header('Referrer-Policy', 'no-referrer')
        s.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")
        if cookie: s.send_header('Set-Cookie', cookie)
        s.end_headers(); s.wfile.write(data)
    def do_GET(s): s.go('GET')
    def do_POST(s): s.go('POST')
    def go(s, method):
        url = urlparse(s.path); path = url.path
        if not path.startswith('/api/'):
            if method == 'GET' and path in ('/', '/index.html'):
                with open(os.path.join(ROOT, 'static', 'index.html'), 'rb') as f: return s.reply(200, f.read(), 'text/html; charset=utf-8')
            return s.reply(404, {'error': 'Not found'})
        if method == 'POST' and s.headers.get('X-Requested-With') != 'hrms': return s.reply(403, {'error': 'Forbidden'})
        try:
            n = int(s.headers.get('Content-Length') or 0)
            if n > 8_000_000: return s.reply(413, {'error': 'Request too large'})
            body = json.loads(s.rfile.read(n) or b'{}') if method == 'POST' else {}
            if not isinstance(body, dict): raise ValueError
        except Exception: return s.reply(400, {'error': 'Invalid request'})
        with LOCK:
            c = db()
            try:
                ck = SimpleCookie(s.headers.get('Cookie') or ''); sid = ck['hrms_sid'].value if 'hrms_sid' in ck else ''
                c.execute('delete from sess where exp<?', (time.time(),)); user = None
                r = one(c, 'select e.*,x.off,x.locked from sess s join emp e on e.id=s.emp join usr x on x.id=e.id where s.tok=? and s.exp>?', (sid, time.time())) if sid else None
                if r and not r['off'] and r['status'] not in EX: user = r
                for m, pat, fn, pub in ROUTES:
                    mt = pat.match(path)
                    if m == method and mt:
                        if not pub and not user: raise Err(401, 'Please sign in')
                        res = fn(c, user, body, parse_qs(url.query), *mt.groups()); c.commit(); res = dict(res or {})
                        sec = '; Secure' if BASE.startswith('https') else ''
                        if '_cookie' in res: return s.reply(200, res, cookie='hrms_sid=%s; HttpOnly; SameSite=Lax; Path=/; Max-Age=%d%s' % (res.pop('_cookie'), 8 * 3600, sec))
                        if res.pop('_logout', None):
                            if sid: c.execute('delete from sess where tok=?', (sid,)); c.commit()
                            return s.reply(200, res, cookie='hrms_sid=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0' + sec)
                        return s.reply(200, res)
                raise Err(404, 'Not found')
            except Err as e:
                c.rollback(); s.reply(e.code, {'error': e.msg, 'fields': e.fields})
            except Exception as ex:
                c.rollback(); print('ERROR', method, path, repr(ex)); s.reply(500, {'error': 'Server error'})
            finally: c.close()

# ---------- setup / seed ----------
def ptfor(co, g, sal, m):
    if co == 'OB Services': return 0
    p = (200 if sal > 25000 else 0) if g == 'Female' else (0 if sal <= 7500 else 175 if sal <= 10000 else 200)
    return 300 if p == 200 and m == 2 else p
def init_db():
    c = db(); c.executescript(SCHEMA)
    for col in ('lat_in', 'lng_in', 'acc_in', 'lat_out', 'lng_out', 'acc_out'):
        try: c.execute('alter table att add column %s real' % col)
        except sqlite3.OperationalError: pass
    cols = [r[1] for r in c.execute('pragma table_info(hol)').fetchall()]
    if 'company' not in cols or 'id' not in cols:
        c.execute('drop table if exists hol')
        c.execute('create table hol(id integer primary key autoincrement, day text, name text, company text, kind text default "Fixed")')
    if not one(c, 'select name from types'): c.executemany('insert into types values(?,?)', [('Paid Leave', 'paid'), ('Leave Without Pay', 'lwp'), ('Work From Home', 'wfh'), ('Restricted Holiday', 'paid')])
    elif not one(c, "select name from types where name = 'Restricted Holiday'"): c.execute("insert into types values('Restricted Holiday', 'paid')")
    if not one(c, "select id from hol where company = 'OB Services'"):
        c.execute('delete from hol')
        c.executemany('insert into hol(day,name,company,kind) values(?,?,?,?)', HOLIDAYS_INTERNOVO_INTERFACE + HOLIDAYS_OB)
    c.commit(); c.close()
def new_emp(c, name, gender, company, dept, desig, manager, doj, status='Active', role='emp', scope=None, oemail=None, pemail=None):
    f = name.split()[0].lower(); i = c.execute('select count(*) from emp').fetchone()[0] + 1
    c.execute('insert into emp(name,gender,dob,pEmail,oEmail,mobile,emerg,cAddr,pAddr,company,dept,desig,manager,doj,loc,prob,probEnd,status,role,scope) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (name, gender, '1990-05-1%d' % (i % 9), pemail or f + '@mail.com', oemail or '%s@%s.in' % (f, company.split()[0].lower()), '982000%04d' % (1000 + i), '982001%04d' % (1000 + i), 'Mumbai', 'Pune', company, dept, desig, manager, doj, 'Delhi' if company == 'OB Services' else 'Mumbai', 3, addm(doj, 3), status, role, scope or company))
    return c.execute('select last_insert_rowid()').fetchone()[0]
def seed_demo(c):
    T = today(); iso = lambda d: d.isoformat()
    R_ = [('Anita Rao', 'Female', 'Internovo', 'HR', 'HR Manager', 0, '2021-04-12', 'Active', 'hr', 'all'), ('Rohit Mehta', 'Male', 'OB Services', 'HR', 'HR Executive', 0, '2022-06-01', 'Active', 'hr', None),
          ('Sneha Kulkarni', 'Female', 'Internovo', 'Engineering', 'Engineering Manager', 0, '2020-01-15', 'Active', 'emp', None), ('Arjun Patil', 'Male', 'Internovo', 'Engineering', 'Developer', 3, '2023-08-21', 'Active', 'emp', None),
          ('Vikram Joshi', 'Male', 'Interface', 'Projects', 'Project Manager', 0, '2019-11-04', 'Active', 'emp', None), ('Priya Sharma', 'Female', 'Interface', 'Projects', 'Site Engineer', 5, '2026-08-10', 'Active', 'emp', None),
          ('Amit Verma', 'Male', 'OB Services', 'Operations', 'Operations Manager', 0, '2020-09-01', 'Active', 'emp', None), ('Neha Singh', 'Female', 'OB Services', 'Operations', 'Executive', 7, '2024-02-12', 'On Notice', 'emp', None),
          ('Karan Desai', 'Male', 'Internovo', 'Engineering', 'Developer', 3, '2022-03-07', 'Resigned', 'emp', None), ('Isha Nair', 'Female', 'Interface', 'Projects', 'Site Engineer', 5, iso(T), 'Active', 'emp', None)]
    ids = []
    for r in R_:
        i = new_emp(c, *r[:8], role=r[8], scope=r[9]); ids.append(i)
        e = one(c, 'select * from emp where id=?', (i,)); g = 25000 + i * 4000; pt = ptfor(e['company'], e['gender'], g, 1); b = round(g * .5); h = round(g * .2)
        c.execute('update emp set pan=?,aadhaar=?,bank=?,acct=?,ifsc=? where id=?', ('ABCPK%dF' % (1000 + i), '23450000%04d' % (1000 + i), 'HDFC Bank', '5010%d' % (100000 + i * 7), 'HDFC0001234', i))
        if i == 4: c.executemany('insert into sal(emp,frm,tto,gross,basic,hra,sa,pt,net) values(?,?,?,?,?,?,?,?,?)', [(i, e['doj'], '2025-03-31', 40000, 20000, 8000, 12000, 200, 39800), (i, '2025-04-01', '', 46000, 23000, 9200, 13800, 200, 45800)])
        else: c.execute('insert into sal(emp,frm,tto,gross,basic,hra,sa,pt,net) values(?,?,?,?,?,?,?,?,?)', (i, e['doj'], '', g, b, h, g - b - h, pt, g - pt))
        if i == 10: c.execute('insert into usr(id,pend) values(?,1)', (i,)); queue_mail(c, e, 'invite')
        else: c.execute('insert into usr(id) values(?)', (i,)); setpw(c, i, 'Welcome@123')
    days = []; k = 0
    while len(days) < 6:
        d = T - dt.timedelta(k); k += 1
        if d.weekday() < 5: days.append(d)
    for i in ids:
        e = one(c, 'select * from emp where id=?', (i,))
        if e['status'] in EX or i == 10: continue
        for n, d in enumerate(days):
            t = d == T
            if t and i % 2 == 0: continue
            kk = (i * 7 + n) % 9
            if kk == 2: continue
            if kk == 0: set_att(c, i, iso(d), tin='10:52', tout='' if t else '18:40', st='Present', late=1)
            elif kk == 1: set_att(c, i, iso(d), tin='09:30', tout='' if t else '18:00', st='Work From Home')
            else: set_att(c, i, iso(d), tin='09:%02d' % (10 + (i * 3 + n) % 30), tout='' if t else '18:15', st='Present')
    ins = lambda *a: c.execute("insert into lv(emp,type,frm,tto,days,half,reason,st,paid,lwp) values(?,?,?,?,?,0,?,?,?,?)", a)
    ins(4, 'Paid Leave', iso(T + dt.timedelta(10)), iso(T + dt.timedelta(11)), 2, 'Family function', 'Pending', None, None); ins(6, 'Work From Home', iso(T + dt.timedelta(10)), iso(T + dt.timedelta(10)), 1, 'Plumber visit', 'Pending', None, None)
    ins(3, 'Paid Leave', iso(T + dt.timedelta(17)), iso(T + dt.timedelta(17)), 1, 'Personal', 'Pending', None, None); ins(8, 'Leave Without Pay', iso(T - dt.timedelta(20)), iso(T - dt.timedelta(19)), 2, 'Personal', 'Approved', 0, 2)
    c.execute('delete from hol'); c.executemany('insert into hol(day,name,company,kind) values(?,?,?,?)', HOLIDAYS_INTERNOVO_INTERFACE + HOLIDAYS_OB); c.execute("insert into kv values('demo','1')")
    c.execute("insert into hist(emp,date,fld,ov,nv,by) values(9,?,'status','Active','Resigned','Anita Rao')", (iso(T - dt.timedelta(9)),))
    c.commit()
def main():
    init_db(); c = db(); a = sys.argv
    aemail = os.environ.get('HRMS_ADMIN_EMAIL'); aname = os.environ.get('HRMS_ADMIN_NAME', 'Main HR'); aco = os.environ.get('HRMS_ADMIN_COMPANY', CO[0])
    if '--admin' in a:
        i = a.index('--admin'); aemail, aname = a[i + 1], a[i + 2]; aco = a[i + 3] if len(a) > i + 3 else aco
    host = '0.0.0.0' if os.environ.get('HOST') == '0.0.0.0' else '127.0.0.1'
    if DEV and host != '127.0.0.1' and not os.environ.get('HRMS_ALLOW_DEV'):
        sys.exit('Refusing to start: this server is reachable from other computers but SMTP_HOST is not set. Without email settings, password-setup links would be visible to anyone. Set SMTP_HOST (see README).')
    if aco not in CO: sys.exit('HRMS_ADMIN_COMPANY must be one of: ' + ', '.join(CO))
    if not one(c, 'select id from emp'):
        if aemail:
            eid = new_emp(c, aname, 'Male', aco, 'HR', 'HR Manager', 0, today().isoformat(), role='hr', scope='all', oemail=aemail, pemail=aemail)
            c.execute('insert into usr(id,pend) values(?,1)', (eid,)); queue_mail(c, one(c, 'select * from emp where id=?', (eid,)), 'invite'); c.commit()
            print('Main HR account created for %s. An invitation email was sent to set the password.' % aemail)
        elif DEV: seed_demo(c); print('Demo data created. Sign in as anita@internovo.in / Welcome@123')
        else: sys.exit('No data yet. Set HRMS_ADMIN_EMAIL (and HRMS_ADMIN_NAME) so the first main HR account can be created.')
    elif aemail:
        e = one(c, 'select e.* from emp e join usr u on u.id=e.id where lower(e.oEmail)=? and u.pend=1', (aemail.lower(),))
        if e: queue_mail(c, e, 'invite'); c.commit(); print('Main HR has not set a password yet: invitation sent again.')
    c.close()
    print('HRMS running at http://%s:%d  (dev inbox: %s)' % (host, PORT, 'on' if DEV else 'off, using SMTP'))
    ThreadingHTTPServer((host, PORT), H).serve_forever()
if __name__ == '__main__': main()
