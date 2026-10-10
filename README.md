# TTBG Mentor Portal

The TTBG Mentor Portal is the production application portal for
The Technical Bridge Group. It supports the mentor-application workflow:

1. A mentor submits the public application form.
2. The application is committed to the database.
3. The logistics team receives an optional email notification.
4. An authorized administrator or logistics user signs in.
5. The team reviews the application and updates its status and internal notes.

## Local setup on Windows

```powershell
cd ttbg-mentor-portal
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and replace the example secret, administrator email, and password.

Then run:

```powershell
python run.py
```

Open:

- Public form: http://127.0.0.1:5000/apply
- Team login: http://127.0.0.1:5000/login
- Dashboard: http://127.0.0.1:5000/admin

## Email notifications

Email is optional. Applications are saved successfully even when email is
disabled or temporarily fails.

To enable notifications, set these values in `.env`:

```text
NOTIFICATION_EMAIL=logistics@thetechnicalbridgegroup.com
PORTAL_BASE_URL=http://127.0.0.1:5000
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=notifications@thetechnicalbridgegroup.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=notifications@thetechnicalbridgegroup.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

For a Google account using SMTP authentication, do not place the normal Google
account password in this file. Use an application-specific credential where
the account and Workspace security settings permit it.

Keep `.env` private. It is excluded by `.gitignore` and must never be committed.

## Current public application

- Full name
- Email
- Phone
- Years of experience
- Preferred contact method
- Industry / area of expertise
- Tell us about yourself
- Mentorship support areas
- Required acknowledgement

## Database

Local development defaults to SQLite. The same SQLAlchemy models can use
PostgreSQL in production through `DATABASE_URL`.

Example production format:

```text
postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
```

## Portal features

- Public mentor application
- Server-side validation and CSRF protection
- Honeypot spam check
- Secure administrator login
- Application counts and review table
- Application detail view
- Status updates
- Internal notes
- Optional logistics email notification

Not included yet:

- Resume uploads
- Acuity integration
- Stripe Connect onboarding
- Mentor-facing accounts

## Production deployment

The portal runs on Render with a PlanetScale PostgreSQL database configured
through `DATABASE_URL`. The included `render.yaml` defines the web service;
it does not create a database. See `DEPLOYMENT.md` for setup and release
verification instructions.

Set `PORTAL_BASE_URL` to the portal's public HTTPS address so notification
emails link to the production dashboard. Local setup instructions and example
credentials in this repository are for development only.
