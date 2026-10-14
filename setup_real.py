#!/usr/bin/env python3
"""
One-time setup script: wipes hrms.db and creates the two real HR accounts.
Run ONCE before starting the server:
    py setup_real.py
"""
import os, sys, sqlite3, hashlib, secrets, time

ROOT = os.path.dirname(os.path.abspath(__file__))
DBP  = os.path.join(ROOT, 'hrms.db')

# ── 1. Delete old database ────────────────────────────────────────────────────
if os.path.exists(DBP):
    os.remove(DBP)
    print('Deleted old hrms.db')

# ── 2. Bootstrap the new database via server helpers ─────────────────────────
sys.path.insert(0, ROOT)
import server                       # import the HRMS server module

server.init_db()                    # creates schema + holidays + leave types

c = server.db()

import datetime as dt, calendar

def addm(s, n):
    d = dt.date.fromisoformat(s); m = d.month - 1 + n
    y = d.year + m // 12; m = m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()

today = dt.date.today().isoformat()

HR_ACCOUNTS = [
    # (name, gender, company, dept, desig, manager, doj, status, role, scope, oEmail, pEmail)
    ('Nidhi Parikh',  'Female', 'Internovo',   'HR', 'HR Manager',  0, today, 'Active', 'hr', 'all',         'hr@internovo.in',  'hr@internovo.in'),
    ('Shrishty Jha',  'Female', 'OB Services', 'HR', 'HR Executive',0, today, 'Active', 'hr', 'OB Services', 'hr@onebharat.co',  'hr@onebharat.co'),
]

print('\nCreating HR accounts...')
for row in HR_ACCOUNTS:
    name, gender, company, dept, desig, manager, doj, status, role, scope, oemail, pemail = row
    eid = server.new_emp(c, name, gender, company, dept, desig, manager, doj,
                         status=status, role=role, scope=scope,
                         oemail=oemail, pemail=pemail)
    emp = server.one(c, 'select * from emp where id=?', (eid,))
    c.execute('insert into usr(id,pend) values(?,1)', (eid,))
    tok = server.queue_mail(c, emp, 'invite')
    print(f'  ✓  {name} ({oemail})  [scope: {scope}]')

c.commit()
c.close()

print("""
Done! Two HR accounts created (both need to set their passwords).

Next steps:
  1. Start the server:      py server.py
  2. Check the dev inbox at http://localhost:8000  (sign-in page → Dev inbox)
     to get the invitation links for both accounts.
  3. Each person clicks their link to create a password and sign in.
""")
