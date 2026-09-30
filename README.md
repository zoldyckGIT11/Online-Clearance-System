# Saint Paul College - Surigao Online Clearance

A functional Flask + SQLite clearance workflow for students, office staff, and administrators.

## Run on Windows

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe seed.py
.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000.

## Google student sign-in

Student authentication uses Google OpenID Connect and accepts only verified `@students.spus.edu.ph` accounts. Create a Web application OAuth client in Google Cloud Console and add `http://127.0.0.1:5000/auth/google/callback` as an authorized redirect URI. Copy `.env.example` to `.env`, then fill in the client ID and client secret from Google Cloud Console:

```powershell
Copy-Item .env.example .env
# Edit .env and set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and SECRET_KEY.
python app.py
```

The local `.env` file is ignored by Git. Alternatively, set the same variables in the environment that starts Flask. Restart Flask after changing credentials. Set `GOOGLE_ALLOWED_DOMAINS` to a comma-separated list if the allowed school domains differ. Google verifies student identity; first-time students then complete their profile. Staff and administrators continue to use local credentials.

## Development accounts

- Admin: `admin` / `Admin123!`
- Office staff: usernames follow `<office-name>.staff` and all use `Staff123!` (for example, `registrar.staff`, `accounting.staff`, and `guidance-office.staff`)
- Seeded student: `2026-0001` / sign in with the corresponding school Google account

These credentials are for local development only. Change the secret key and passwords before deployment.

## Features

- Hashed passwords, Flask-Login sessions, CSRF-protected forms, and server-side role authorization
- Student registration and clearance submission
- Students choose which active offices receive each clearance request; offices start unchecked and students can cancel one office request or all unfinished requests at once
- Students can upload PDF, Word, JPG, or PNG proof for each office requirement; assigned staff can securely review the uploaded document
- Office-specific approval, rejection, and requires-action decisions
- Dynamic clearance progress and automatic completion when every active office approves
- In-app notifications, activity logs, admin management views, reports, and CSV export
- Printable completed clearance page
- Responsive green academic interface with mobile navigation

## Database and customization

The database is created at `instance/clearance.db`. Uploaded requirement files are stored in `instance/uploads`. Running `python seed.py` resets it with labeled demo records. Active offices are configurable from Admin > Offices. Property/Equipment Office is not included. Place an approved school logo at `static/images/school-logo.png` if one is available; the printable page intentionally does not fabricate a seal or signature.

Theme variables are in `static/css/style.css`.
