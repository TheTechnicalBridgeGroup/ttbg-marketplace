# Deploy this beta to Render

Use a **new GitHub repository and a new Render service** for the marketplace. Do not replace the mentor portal or help desk. Squarespace and Acuity stay in place.

## 1. Prepare GitHub

Extract the project and upload the contents of `ttbg-marketplace` to the repository root. `run.py`, `requirements.txt`, and `render.yaml` should be at the root. Do not upload `.env`, `.venv`, `instance`, database files, or cache folders. The included `.gitignore` covers them when using Git.

## 2. Choose a database

Use a dedicated database or database branch for this application so you can test without affecting the existing apps. The application uses `market_` table prefixes and never imports or alters the portal/help desk models.

Copy a SQLAlchemy-compatible connection string from your database provider; URL-encode special characters in the username/password. Both database drivers are included:

- PostgreSQL: `postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require`
- MySQL: `mysql+pymysql://USER:PASSWORD@HOST:3306/DATABASE?ssl_verify_cert=true&ssl_verify_identity=true`

Choose the string that matches the actual database engine. PlanetScale branding alone does not determine which driver to use. Use the provider's documented CA/TLS settings if it requires a particular certificate path. A certificate file must exist on the host if referenced.

**Do not use the default SQLite URL on an ephemeral Render filesystem.** The service will otherwise lose data on redeployment/restart. Production database connectivity and TLS must be verified in your account.

## 3. Create the web service

Use the included Render Blueprint, or create a Python web service manually:

- Build command: `pip install -r requirements.txt`
- Start command: `flask --app run init-db && gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60`
- Health check: `/health`
- Python: 3.12

Set environment variables:

| Name | Value |
| --- | --- |
| `SECRET_KEY` | A newly generated random secret, at least 32 characters |
| `DATABASE_URL` | Your dedicated external database connection string |
| `COOKIE_SECURE` | `true` |
| `DEMO_BOOKING_ENABLED` | `true` for demo testing |

The Blueprint can generate `SECRET_KEY` and prompts for `DATABASE_URL`. Select the Render service plan appropriate to your account; no price assumptions are built into this package.

## 4. Create the administrator

After the first successful deployment, open an authorized terminal for the service and run:

```bash
flask --app run create-admin
```

Use your own email and a unique password. If your service does not offer a host shell, run this CLI locally with the same dedicated remote `DATABASE_URL` in a private `.env`. Do not put a password in source code or command-line arguments.

Optionally run `flask --app run seed-demo` in your test database. Sample profiles are not real TTBG personnel. To hide a sample, open its admin review and change it from Approved to Declined.

## 5. Verify the hosted beta

- Open the directory and sign in with your admin.
- Create separate mentor and student test accounts.
- Submit, review, approve, and publish a mentor/service.
- Create and cancel one demo reservation and check all three dashboards.
- Restart the service and verify the records remain.
- Keep the original portal and help desk running independently.

## 6. Custom domain

Once you are happy with the beta, add `app.thetechnicalbridgegroup.com` in Render's custom-domain settings. Use the DNS record and exact target Render supplies to create the corresponding record in your domain's DNS manager. Keep `www` pointing to Squarespace. Wait for domain verification and HTTPS before linking the app from Squarespace.

No DNS, production data, GitHub repository, or Render service was changed while creating this project.

## v0.2 upgrade and onboarding access

Back up your existing marketplace database, deploy the v0.2 source, and run `flask --app run init-db` (already included in the start command). Three additive tables hold extended mentor profiles, activation tokens, and audit events. Existing v0.1 users, services, and reservations are retained.

Set `PUBLIC_BASE_URL` to the HTTPS origin you actually use, with no trailing path, for example `https://app.thetechnicalbridgegroup.com`. It controls activation-link generation. If unset, links use the current request's origin; configure it explicitly on hosting.

Create a delegated onboarding account using `flask --app run create-onboarding-user`. Each staff member gets separate credentials. They have workspace access to mentor profiles, services, and demo sessions. The owner field is a coordination tool, not an access restriction.

All application CTAs now link to the existing mentor portal. Use **Workspace → Create mentor profile** to onboard an accepted applicant. Generate a one-time setup link and share it privately yourself; the app does not send messages or email.

Do not seed fictional profiles into a public launch database. Existing sample profiles can be deleted through the v0.2 profile controls.
