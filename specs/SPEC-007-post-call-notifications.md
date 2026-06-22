# SPEC-007 — Post-call notifications: WhatsApp + manager email PDF (B2)

| | |
|---|---|
| **Status** | Implemented |
| **Owner** | Aditya Sakpal |
| **Version** | 1 |
| **Satisfies** | B2 (post-call notifications) |
| **Related specs** | SPEC-002, SPEC-003 |
| **Code** | `agent.py` (`send_whatsapp`, `send_manager_email`, `build_call_pdf`, `_latin1`) |

## 1. Summary
On a confirmed booking the agent sends the caller a WhatsApp confirmation (Twilio), and at call
end it emails the manager a call summary with the full transcript and booking details rendered
as a PDF attachment. Both are best-effort: a notification failure must never affect the booking.

## 2. Problem & goals
- **Problem:** the caller wants a written confirmation; the manager wants a record of each call.
- **Goals:** WhatsApp the caller their booking the moment `create_booking` succeeds; email the
  manager a PDF summary (transcript + booking) when the call ends; skip gracefully when
  unconfigured; never raise into the booking path.
- **Non-goals:** SMS/voice callbacks, templated marketing, delivery-receipt tracking.

## 3. Design
- **WhatsApp** (`send_whatsapp`): POST to Twilio's REST API. Delivers to the caller's own number
  when known (`to_number` = the raw caller phone held in memory for the call), else the
  `BOOKING_NOTIFY_WHATSAPP` fallback. Fired from `create_booking` with the booking details.
- **Manager email** (`send_manager_email`): builds an `EmailMessage` with a text body and a PDF
  attachment, sends via SMTP with STARTTLS. Called from the shutdown callback **only when
  `outcome == "booked"`**, off the event loop via `asyncio.to_thread`.
- **PDF** (`build_call_pdf`): one page — call id/caller/outcome, the booking summary, and the
  full transcript — via `fpdf`. `_latin1()` replaces glyphs the core fonts can't encode so PDF
  generation never crashes on non-latin transcript text.

Both readers pull all config from env and **return `False` (logged) instead of raising** on any
error — the booking and call log are never affected by a notification failure.

## 4. Data & interfaces
- WhatsApp env: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`,
  `BOOKING_NOTIFY_WHATSAPP` (fallback recipient).
- Email env: `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`,
  `MANAGER_EMAIL`. `SMTP_PASS` is stripped of spaces (Gmail app passwords display with spaces).

## 5. Edge cases & failure handling
- **Unconfigured:** both functions detect missing config and skip with an info log.
- **Twilio sandbox:** delivery fails with error `63015` unless the recipient has joined the
  sandbox, even though the API returns 201 — documented in the code comment.
- **Non-latin transcript:** handled by `_latin1()` so the PDF never crashes.
- All exceptions are caught and logged; the booking always completes.

## 6. Verification
- Configure Twilio + a joined sandbox number; complete a booking → caller receives WhatsApp.
- Configure SMTP + `MANAGER_EMAIL`; complete a booking → manager receives an email with a
  `call-<id>.pdf` containing the booking + transcript.
- Remove the env vars → booking still succeeds, logs show the "not configured; skipping" lines.

## 7. Open questions / future work
- Retry/queue for transient SMTP/Twilio failures (currently single attempt, best-effort).
- Promote out of the Twilio sandbox for unrestricted WhatsApp delivery.
