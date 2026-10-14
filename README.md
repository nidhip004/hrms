# HRMS Phase 1

Internal HR system for Internovo Ventures, OB Services and Interface Projects.
Backend: Python 3.9+ (standard library only, nothing to install). Database: SQLite file `hrms.db`. Frontend: one HTML page served by the same process.

## Run it

    python3 server.py

Open http://localhost:8000

The first start on an empty database creates demo data. Sign in as `anita@internovo.in` / `Welcome@123` (main HR). Other demo users use the same password; "Isha Nair" is an invited employee who has not set a password yet.

Windows: `py server.py`, or double-click `run.bat`. Mac/Linux: `./run.sh`.

## Start with real data instead of the demo

Delete `hrms.db`, then:

    python3 server.py --admin you@company.com "Your Name" Internovo

This creates only the main HR account and prints a one-time link to set the password. Add everyone else from the Employees screen.

## Configuration (environment variables)

| Variable | Purpose | Default |
|---|---|---|
| PORT | Port to listen on | 8000 |
| HOST | Set to `0.0.0.0` to allow other computers to connect | 127.0.0.1 only |
| HRMS_BASE_URL | Public address used in email links, e.g. https://hr.example.com | http://localhost:PORT |
| HRMS_DB | Path of the SQLite file | ./hrms.db |
| SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM | Send real invitation and reset emails | not set |
| HRMS_REQUIRE_LOCATION | Set to `0` to let people check in without sharing their location | 1 (location required) |
| TZ | Time zone, e.g. `Asia/Kolkata` (affects "today" for attendance) | system |

Without SMTP_HOST the app runs in development mode: emails are not sent, they appear in a "dev inbox" (login page helpers and Settings) and in the console. **Never expose development mode to the internet**, because the inbox shows password-setup links. Set SMTP_HOST in production.

## How it works

- Add employee (HR): the server creates the employee and an invited account, then emails a 72-hour, single-use link to the personal email. The employee creates a password, signs in with the official email, and is asked to confirm their contact details.
- Every employee can edit only their own contact details (personal email, mobile, emergency contact, addresses) and change their own password.
- Access rules are enforced on the server for every request: main HR sees all companies, company HR sees only their company, employees see only themselves, and managers also see their direct reports' leave requests.
- Passwords are hashed with scrypt, sessions are server-side with HttpOnly cookies, accounts lock after 5 wrong attempts, PAN/Aadhaar/bank details are masked until HR reveals them (logged), and changes are written to an audit log.
- Uploaded documents are stored in `uploads/`. Employee download is a Phase 2 feature.

## Check-in location

When an employee checks in or out, the browser asks for permission and the app saves the position (latitude, longitude, accuracy) for that moment only. Nothing is tracked in between. HR sees "In" and "Out" links on the daily attendance screen that open the spot on a map. Location only works on `http://localhost` or an `https://` address (Render provides https). Tell employees about this before launch and keep it to work use.

## Putting it online (summary)

Settings to add on a hosting service: `HOST=0.0.0.0`, `HRMS_DB=/var/data/hrms.db` (a folder on a permanent disk), `HRMS_BASE_URL=https://your-address`, `HRMS_ADMIN_EMAIL`, `HRMS_ADMIN_NAME`, and the `SMTP_*` email settings. The server refuses to start in public mode without SMTP, and it never loads demo data when HRMS_ADMIN_EMAIL is set.

## Production checklist

1. Put it behind HTTPS (nginx, Caddy or a platform proxy) and set HRMS_BASE_URL to the https address.
2. Configure SMTP.
3. Back up `hrms.db` and `uploads/` daily.
4. Run it as a service (systemd, Docker, or your host's process manager).
5. SQLite suits one office-sized team on one server. For many concurrent users, move to PostgreSQL.

## Files

- `server.py`: API, rules, database, email
- `static/index.html`: the interface
- `hrms.db`, `uploads/`: created on first run
