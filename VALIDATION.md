# TTBG Marketplace v0.8.0 validation

Validated locally on October 15, 2026, using the supplied v0.7.1 source. **191 automated tests validated: 163 retained tests and 28 v0.8 tests.** A full 189-test regression run passed. Two additional verification-time/attendance-correction tests were then added; all 53 v0.7/v0.8 payment tests passed together after those refinements. The final two focused cancellation/refund-history tests passed after distinguishing pending refund submission from financial success in the audit timeline.

## Financial operations

- Admin cancellation records the exact account ID, name, role, reason, approval, and confirmed timestamp; account rename does not rewrite the evidence.
- Mentee unpaid Checkout closes only after Stripe confirms it is unpaid/expired. Natural expiry does not fabricate a cancellation actor. Payment completing during cancellation requires review and can be closed/refunded by an Admin without creating an appointment.
- Mentor and Account Manager requests hold earnings and do not cancel paid appointments or move money. Requests retain the person's exact identity; a processing Admin is separately attributed.
- Paid cancellation with no approved refund remains Paid + Cancelled + Held. With explicit refund approval, provider refund state and actual refunded amount are tracked independently.
- Unknown Acuity cancellation response recovers by reading the provider, without another cancellation write. Completed sessions require post-session refund review.
- External Acuity cancellation identifies an unverified initiator and holds earnings. No-show status/corrections come from Acuity and append history rather than erase prior evidence.
- Full refund history preserves requester, approver, amount, provider reference, pending/failed/succeeded states, and original charge. Failed refunds create a separate retry operation/history record. Pending submission is not labeled a succeeded refund in the financial audit.
- External pending partial refunds do not silently expand into full refunds. Transfer reversal failure does not undo a confirmed customer refund.
- Friendly and Stripe/Acuity ID search; combined filters; explicit local date boundaries; sorting/pagination; full-filter totals; scope isolation; non-sensitive formula-safe CSV.
- Customer payment pages hide internal allocation/reference cards and retain status, amount, refund information, support, and access-controlled receipt links. Unsafe receipt destinations are rejected.
- Append-only financial events reject ORM update/delete. Failed financial authorization attempts and provider failures remain recorded. Original financial amounts and provider IDs survive repeated upgrade/backfill.
- Worker heartbeat and local financial notice suppression; authenticated mentor Stripe management; Admin-only review of ambiguous notices.
- Operation lease is claimed before provider submission; an interleaved attempt cannot issue a second money write. Original Stripe idempotency prefixes remain unchanged.
- Successful Stripe/Acuity verification timestamps are independent of refresh attempts. A failed check does not advance the displayed successful verification time.

## Retained regression coverage

Acuity import/booking/intake/synchronization, FREE consultations, Stripe allocation and recovery, onboarding readiness, completion/transfer/refund restrictions, signed webhook replay/out-of-order behavior, account management/deletion, session revocation, verification, Turnstile, profile photo processing, documentation, and support tools remain covered.

The actual v0.7.1 Checkout parameter and narrow CSP fixes are explicitly checked. Source comparison confirms all 38 original model class declarations are unchanged. Six new models bring the application to 44 tables. PostgreSQL/MySQL table/index definitions compile; SQLite workflow tests use foreign-key enforcement. This is not a live PostgreSQL/PlanetScale migration test.

All Python sources and Jinja templates compile. Financial screens render through Flask test clients. No visual mobile/browser screenshot QA was performed. Packaging excludes credentials, local runtime databases, virtual environments, caches, and git metadata; a source scan found no unexpected embedded provider-key patterns.

## Operator verification still required

No live Stripe/Acuity request, production database migration, deployment, real provider email, account change, or money movement was performed during the build. Test TTBG's actual Stripe Sandbox/Connect eligibility, public webhooks, controlled Acuity calendars, SMTP acceptance/inbox delivery, worker restart/monitoring, database backup restoration, and the pilot's final live flow before production activation.

Read FINANCIAL_OPERATIONS_V08.md. Partial-refund creation, automatic cancellation/no-show entitlement, Accounts v2 migration, and scheduled daily financial reporting are not included. Refund eligibility remains an explicit Admin policy decision. A transfer is described as Transferred to Stripe, not paid to a bank. Direct database-owner privileges remain outside application append-only controls.
