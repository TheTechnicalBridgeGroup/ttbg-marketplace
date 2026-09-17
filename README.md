# TTBG Marketplace — v0.2.1 beta

The TTBG mentor marketplace now has team-led onboarding and mentor-controlled pricing. The navy-and-gold design, supplied logo, and existing booking experience are retained.

**All booking activity is still demo-only.** No Acuity appointments, charges, emails, or payouts are created.

## What changed in v0.2

- Every **Become a mentor** link opens https://ttbg-mentor-portal.onrender.com/apply. The marketplace does not accept new mentor applications.
- Admins and the onboarding team can create and update mentor profiles, assign an owner, record private notes, and track publication readiness.
- Profiles have draft, review, approved, suspended, and deleted states. Suspension blocks sign-in and new reservations immediately, including already signed-in sessions.
- Delete removes a profile from the public directory and normal workspace listing. It is a recoverable deletion: account and booking history remain, and deleted profiles can be restored to draft.
- Mentors change their own service prices in dollars from their dashboard. They cannot change TTBG commission or another mentor’s rates. Existing bookings keep their original price/fee; a price changed during checkout requires the student to review the new price.
- New admin-created accounts use one-time activation links. The mentor chooses their password. Links expire in seven days; replacement links invalidate older links.
- An onboarding staff role lets your team do this work without using your admin account.

## Quick start on Windows

1. Extract the folder. Install Python 3.12 or newer if necessary.
2. Double-click `start-windows.bat`. It prepares the local environment and starts the app.
3. Open http://127.0.0.1:5000. Keep the terminal open.
4. In a second terminal inside the project folder, create your administrator:

```powershell
.venv\Scripts\python.exe -m flask --app run create-admin
```

The command prompts for your name, email, and password (at least 12 characters). No shared/default administrator password is shipped.

For optional fictional directory profiles:

```powershell
.venv\Scripts\python.exe -m flask --app run seed-demo
```

For an onboarding team member:

```powershell
.venv\Scripts\python.exe -m flask --app run create-onboarding-user
```

Each staff member should have their own account. Staff accounts access the team workspace, mentor profiles, services, and demo booking records. There is no team-account management UI in this release; creation is through the authorized CLI.

## Existing v0.1 installation

Back up your database first. Replace the application source with v0.2, keeping your private `.env` and existing database. Run:

```bash
pip install -r requirements.txt
flask --app run init-db
```

The upgrade adds three tables for profile details, invitations, and activity history. It does not change or drop existing v0.1 columns. Existing users, passwords, mentor profiles, services, and bookings remain. The Windows launcher performs this initialization; the included Render start command does as well.

Existing approved profiles stay published. New publication decisions require the readiness checklist. Editing an approved profile to remove required information/checklist items returns it to review. Existing mentors keep their sign-in and gain price controls.

## The onboarding workflow

1. **Application:** The mentor applies through the existing portal. Review their application there using your current process. Data does not import automatically.
2. **Create draft:** In Workspace, select **Create mentor profile**. Enter public display name, account email, primary lane, and professional title. Save incomplete drafts as work progresses.
3. **Build profile:** Complete biography, credentials, education, years of experience, specialties, languages, timezone, and approach to sessions. Contact phone, application reference, owner, and team notes are private.
4. **Prepare services:** Add mentor-specific offerings, duration, starting price in USD, TTBG commission percentage, and optional Acuity IDs. Agree on the starting price with the mentor; they can change it after activation.
5. **Track readiness:** Record application review, credential review, agreement receipt, orientation completion, and consent to publish. These are team attestations, not automatic verification. A complete biography, experience, and an active service are also required to publish.
6. **Handoff account:** Generate an activation link from the overview, copy it, and send it privately through your usual onboarding channel. The app does not send it for you. The mentor sets their password and can review their profile and update rates.
7. **Publish:** Choose Approved in the review decision. The profile appears in the public directory once all readiness checks pass.
8. **Manage:** Update the profile, suspend access, or delete it through the controls. Suspend/delete require a reason and typed confirmation of the mentor’s name. Existing reservations are not automatically cancelled.

An existing student email can be linked only after the team confirms that the account belongs to the approved applicant. It keeps its existing password and does not receive an activation link. Staff and existing mentor emails cannot be reused to create another profile.

## Mentor pricing

Mentors open **My dashboard → Set my price**. Amounts are USD, from $1.00 to $1,000.00 per service. Commission remains controlled by the team. Saving a price changes future reservations only and records the change in the team activity history. The beta does not accrue real earnings.

## macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python setup_local.py
flask --app run create-admin
python run.py
```

## Configuration and account recovery

See `.env.example`. Do not commit `.env`, local databases, or `.venv`. Use a dedicated persistent external database on Render. Set `COOKIE_SECURE=true` under HTTPS. Set `PUBLIC_BASE_URL` to your hosted origin so activation links use the intended domain. Leave it empty for local development.

`DEMO_BOOKING_ENABLED=false` disables demo reservation creation; it does not turn on real scheduling.

For an authorized password reset:

```bash
flask --app run reset-password
```

A reset revokes outstanding activation links. Suspension/deletion still blocks access regardless of password changes.

## Current boundaries

- Acuity IDs are stored only. Availability, reservations, fees, and balances remain demo-only.
- No automatic portal import, help desk ticket creation, emails, file uploads, photo uploads, checkout, refunds, or payouts.
- All staff share workspace visibility; assigned owners help coordination and do not restrict access.
- A mentor account cannot make new student reservations in this beta. Existing student booking records remain accessible by their detail links after conversion.
- Deletion is recoverable removal, not permanent personal-data erasure. Reservations and audit records remain for continuity.
- Database upgrade has been tested on SQLite. Actual Render and PlanetScale connections were not accessed or deployed.

## Tests and previews

```bash
pip install pytest
python -m pytest -q
```

See `VALIDATION.md` for results, `preview/` for screenshots, `DEPLOYMENT.md` for hosting, and `ARCHITECTURE.md` for the model and live integration plan.

## v0.2.1 — light and dark mode

Use the **Light mode / Dark mode** selector in the top bar on any page. The existing light appearance is the default, including on devices set to dark mode. Dark mode uses deep navy surfaces, gold actions, readable light text, and a white logo tile that preserves the original logo.

The selection is remembered in this browser’s local storage across pages and visits, and syncs across open tabs on the same origin. It is a browser preference, not an account setting. If storage is blocked, switching still works for the current page; if JavaScript is disabled, the app remains in light mode and hides the selector.

Upgrade from v0.2 by replacing the application files while keeping your `.env` and database. No database schema or dependency changes are required for v0.2.1.
