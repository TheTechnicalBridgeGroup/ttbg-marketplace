# v0.2 validation — September 17, 2026

20 automated tests passed (18 in the main workflow run, followed by two targeted credential-review and invitation-expiry tests).

Coverage includes:
- Admin create/read/update, readiness-gated publication, public/private field separation, and activity records.
- Suspension of already authenticated mentors; deleted profile hiding, retained bookings, and restoration to draft.
- Existing student identity confirmation and protection against linking staff/duplicate mentor accounts.
- Delegated onboarding role and student/mentor access boundaries.
- One-time activation, regenerated-token revocation, expiry, and mentor-chosen passwords.
- Mentor-owned price changes, invalid prices, commission tamper protection, and cross-mentor price denial.
- Existing reservation price snapshots and renewed price confirmation after a mid-booking rate change.
- External application routing, credential-change re-review, CSRF, sign-in throttling, booking duplication, filtering, and cancellation.
- Additive upgrade from a v0.1-shaped SQLite database while preserving an existing user.

Chromium browser flow passed: administrator creates a thorough draft profile → adds a service → publishes → generates activation link → mentor activates → mentor changes price → team suspends → existing mentor session is blocked → team restores to draft.

Desktop and mobile screenshots are included in `preview/`. Admin profile creation and mentor dashboard showed no horizontal overflow at 390px. Desktop profile creation and mentor overview were visually inspected. All visible Become a mentor links tested on the public directory target the existing application portal.

Not validated: actual Render deployment, PostgreSQL/MySQL hosting connections, Windows execution, real Acuity data, or payment processing. Live scheduling/payments remain unimplemented.

## v0.2.1 theme verification

Browser checks passed for: light default even with a dark OS preference; switching both ways; persistence after reload and navigation; synchronization between tabs; and working controls when local storage is blocked. No JavaScript errors occurred. Directory and admin form layouts were inspected in dark mode. No directory overflow at 390, 768, 1024, or 1440 pixels; mobile admin forms also fit. Current-release screenshots show light/dark desktop, dark mobile, and dark admin views. No backend/database logic changed other than the reported version.
