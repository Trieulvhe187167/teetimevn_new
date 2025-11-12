# Booking Flexibility Rollout

This document summarizes the follow-up steps required after enabling customer self-service cancellation and rescheduling.

## Database upgrade

1. Back up your `teetimevn_dev.db` database.
2. Run `python data/upgrade_booking_table_flexible_cancel.py` to add the new cancellation/payment columns.
3. (Optional) Inspect the schema with `sqlite3 data/teetimevn_dev.db "PRAGMA table_info(bookings);"` to confirm the fields were added.

## Configuration

- `BOOKING_CANCEL_WINDOW_HOURS` (default `24`) controls how many hours before tee time users can cancel online.
- `BOOKING_RESCHEDULE_WINDOW_HOURS` (default `12`) controls the reschedule window.
- `BOOKING_ALERT_EMAIL` defaults to the mail sender and is used for admin notifications.

Override these values via environment variables or directly in `app.py` before deploying.

## Translations

New strings were introduced in templates and backend flashes. Regenerate catalogues when convenient:

```bash
pybabel extract -F babel.cfg -o messages.pot .
pybabel update -i messages.pot -d translations
```

Review and translate the new entries for each locale, then compile (`pybabel compile -d translations`).

## Recommended testing

- Create a booking, then reschedule it within the permitted window.
- Cancel a paid and an unpaid booking to confirm refund vs. credit messaging.
- Attempt to cancel or reschedule within the restricted window and verify the UI prevents it.

## Tee-time availability UI

- `BOOKING_SLOT_CAPACITY` (default `4`) controls how many seats each tee time exposes to players.
- The booking page now surfaces a live availability grid fed by `/<lang>/booking/availability?course_id=...&play_date=...`.
- Filters for location, hole count, and a max-price heuristic (based on the lowest tier price) operate entirely client-side; keep course metadata up to date for best results.

### Suggested testing

- Pick a busy day and create overlapping bookings to confirm the remaining-slot counter decrements correctly.
- Try booking more players than the remaining capacity and ensure the form blocks the submission.
- Reschedule a booking into a nearly full slot and verify the capacity check prevents oversubscription.
- Exercise the course filters and confirm the availability grid refreshes as the selected course changes.




## VNPay deposit & payment automation

- Run `python data/upgrade_booking_table_deposit.py` after pulling these changes so the new deposit, balance, and payment reference columns exist.
- Configure the following environment variables (or override in `app.py`) before enabling VNPay in production:
  - `VNPAY_TMN_CODE`, `VNPAY_HASH_SECRET`, and `VNPAY_PAYMENT_URL` from your merchant dashboard.
  - `VNPAY_RETURN_URL` and `VNPAY_IPN_URL` if you need to override the auto-generated callback URLs.
  - `BOOKING_DEPOSIT_PERCENT` to adjust how much of the total is collected upfront (default `20`).
- VNPay redirects are generated from `/<lang>/booking` and callbacks are handled by `/payment/vnpay/return` (browser) and `/payment/vnpay/ipn` (server-to-server). Make sure these endpoints are reachable from VNPay.
- Successful deposits automatically flip the booking status to `confirmed`, mark the payment as `partially_paid`, and log the payment reference.

### Suggested testing

- Create a booking choosing the VNPay deposit option and verify the app redirects to VNPay with the expected amount.
- Simulate a successful IPN callback (or complete a sandbox payment) and confirm the booking shows `Deposit paid`, the balance reflects the remainder, and the detail page instructs guests to settle at the course.
- Test the "pay at course" option to ensure bookings stay in `Pending` and the balance equals the total.
- Attempt to reschedule and cancel bookings with partial payments to check that refund logic still behaves as expected.
