# Deploy TTBG Marketplace v0.5.0

Update the existing **ttbg-marketplace** repository and Render service. Do not upload the mentor portal or help desk code into this repository.

Read SECURITY_SETUP.md for SMTP, email verification, and Turnstile configuration. Existing accounts remain accessible, but public registration is unavailable until mail configuration is complete.

## Before deployment

1. Back up the current marketplace database through its provider.
2. Keep the existing `SECRET_KEY`, `DATABASE_URL`, and account credentials.
3. Extract this ZIP and copy the contents of its `ttbg-marketplace` folder to the repository root. `run.py` and `requirements.txt` belong at that root.
4. Do not upload `.env`, local databases, `.venv`, or cache folders.

## Render commands

Build:

```text
pip install -r requirements.txt
```

Start:

```text
flask --app run init-db && gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60
```

Health path: `/health`. Python: 3.12 or newer.

For multiple Render instances, run `flask --app run init-db` once as a controlled pre-deploy step, then start the instances with the Gunicorn portion only. Do not run simultaneous first-time schema creation against the same database.

## Environment

| Variable | Value |
| --- | --- |
| `SECRET_KEY` | Preserve the existing random secret, at least 32 characters |
| `DATABASE_URL` | Existing persistent marketplace database connection |
| `COOKIE_SECURE` | `true` for HTTPS |
| `PUBLIC_BASE_URL` | Exact public HTTPS marketplace origin, without a path or trailing slash |
| `ACUITY_USER_ID` | Numeric Acuity API user ID; optional until availability is enabled |
| `ACUITY_API_KEY` | Acuity API key; backend-only, admin password required to reveal |
| `STRIPE_SECRET_KEY` | Optional future Stripe Connect credential; checkout is not implemented |
| `STRIPE_WEBHOOK_SECRET` | Optional future webhook signing secret; webhook processing is not implemented |

Use the connection string and TLS options required by your database provider:

- PostgreSQL: `postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE` plus provider TLS parameters.
- MySQL: `mysql+pymysql://USER:PASSWORD@HOST:PORT/DATABASE` plus provider CA/TLS parameters.

Do not use SQLite on Render’s ephemeral disk. Photos are stored in the persistent database and are covered by its backup policy. No new runtime dependency is required for v0.5. The v0.3 dependency Pillow is used for image decoding and re-encoding; the existing Flask/database stack is retained.

Render’s forwarded protocol header is trusted only when its `RENDER` environment is present. The app also trusts the configured number of rightmost forwarded-IP hops (TRUSTED_PROXY_HOPS, default 1 on Render) for rate limiting. Verify the actual proxy chain before changing this value; never select an arbitrary leftmost client-supplied IP. Same-origin HTTPS form referrers and CSRF checks remain enabled. No production credentials are included in the ZIP.

## What the first upgrade changes

`init-db` creates the added account-access, password-link, platform-settings, platform-audit, photo-submission, mentor-photo, service-scheduling, mentor-integration, and schema-revision tables. Existing tables retain their columns. v0.5 adds `market_email_identity`, `market_security_rate`, `market_help_settings`, `market_knowledge_page`, and `market_knowledge_image` and marks only accounts already present at that migration as exempt from verification; it does not disable them. v0.4 also creates `market_support_note`, `market_support_incident`, `market_sensitive_attempt`, and `market_availability_request`; no existing production table is rebuilt.

- Existing Admins stay Admins.
- Legacy `onboarding` users become Account Managers.
- Future service commissions become 20% TTBG / 80% mentor.
- Existing users, password hashes, mentor records, and booking amount snapshots stay intact.
- A revision marker prevents subsequent restarts from overwriting an Admin’s later commission configuration.

If the service has no Admin yet, run `flask --app run create-admin` in an authorized shell. For password recovery, use `flask --app run reset-password`. Existing installations do not need another Admin account merely to upgrade.

## After deployment

1. Sign in with your existing Admin. Open **Admin → Platform overview**.
2. Review existing staff roles in **Accounts**. Reassign staff to Account Manager where appropriate.
3. Set support email, site metadata, and registration options in **Settings & booking**.
4. Confirm mentor publication, photo submission/approval, and password setup using designated test accounts.
5. Check that a pending photo is private and the approved photo survives a restart.
6. Confirm Account Managers cannot open Accounts, Database, Settings, Resources, or Audit pages.
7. Verify Support Center is denied to students/mentors and accessible to Admins/Account Managers. Confirm Account Managers cannot reveal keys or reset staff accounts.
8. Confirm credential values are absent from the initial HTML; test the admin confirmation dialog on a private screen using a non-production key first.
9. Keep **Contact TTBG** until Acuity API credentials, calendar IDs, and appointment-type IDs are configured. Check Acuity connectivity in Support Center, inspect one mentor/service's availability, and then enable **Acuity live availability + contact to confirm** if desired.
10. Verify the calendar on a phone and desktop, including dark mode, timezone changes, empty dates, and denied Acuity requests. Compare the results with Acuity directly. The source package was tested with mocked provider responses, not your live account.
11. Keep Stripe checkout and appointment creation as the next integration stage. No automatic payment split, refund, webhook, or mentor account onboarding endpoint is shipped in this release.

The Blueprint service name is `ttbg-marketplace`. Keep the existing service identity when updating; do not accidentally provision a second service or replace the existing database.

## Operations and rollback

Maintenance mode is available under Admin settings. Admin sign-in and health checks remain accessible while maintenance mode is active. Render/PlanetScale consoles remain responsible for server lifecycle, scaling, environment secrets, backups, and billing; no infrastructure API credentials are installed by this update.

The database changes are additive. Before rolling application code backward, account for the new `account_manager` role, future-service commission changes, and security state: older code does not enforce v0.3 disabled-account/session/photo rules. Prefer a forward fix; use your database backup only as part of a deliberate recovery plan, since restoring it can discard newer records.

## Local Windows upgrade

Keep the existing local `instance/marketplace.db` and `.env` if you want to retain local accounts. Back them up before replacing source files, then run `start-windows.bat` from the updated project folder. The launcher runs the additive upgrade and starts http://127.0.0.1:5000. Extracting the ZIP into a separate folder creates a separate local database unless you deliberately copy the existing database and configuration into it. Do not copy a live hosting database URL into a local test configuration unintentionally.

## Support record retention

Support notes, audit records, and incidents persist in the database and its backups. Short-lived verification and availability throttling records are pruned for each account when it uses the corresponding workflow again. Set a retention process before traffic grows; the app does not yet run scheduled global archival. Configure external uptime/error monitoring separately to cover failures before Flask starts or while its database is offline.

## v0.5 deployment checks

1. Back up the database and preserve existing SECRET_KEY/DATABASE_URL. Run `flask --app run init-db` once before starting workers.
2. Confirm existing Admin, Account Manager, mentor and student access still works. Confirm disabled users remain disabled.
3. Configure SMTP and PUBLIC_BASE_URL in Render, then register a mailbox you control. Verify receipt, expiry/resend, and successful confirmation/sign-in. SMTP acceptance alone does not prove inbox delivery.
4. Add Turnstile site/secret keys and exact allowed hostnames; test a valid challenge and a rejected submission on the deployed domain.
5. Use a disposable account to exercise permanent deletion. Confirm the old login fails and shared records remain. This cannot be undone through the app.
6. Run `flask --app run prune-security-records` periodically (for example daily through your hosting scheduler) to remove expired counters and token hashes. This command does not disable or delete accounts.

Old releases do not enforce v0.5 verification and do not understand archive principals. Avoid rolling back to older code without a deliberate recovery plan.

## Documentation and contact setup

After `init-db`, open Documentation as an Admin, Account Manager, and Mentor. Check the three starter guides and edit them for your team. Confirm students cannot access pages or direct image URLs. Backups now include compressed documentation images. If editors see a conflict, have them copy their text, reload the latest page, and reapply it.

Under Admin → Settings, set the public team contact number in international format or leave it blank for ticket/email help. The guide uses built-in responses and needs no AI service. Test the phone link on a phone and the ticket link in your help desk. This is a handoff, not embedded live support.
