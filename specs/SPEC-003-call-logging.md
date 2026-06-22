# SPEC-003 — Call logging & transcript persistence

| | |
|---|---|
| **Status** | Implemented |
| **Owner** | Aditya Sakpal |
| **Version** | 1 |
| **Satisfies** | Q6 (call logging + transcript storage, atomic), Q13 (debugging scenario) |
| **Related specs** | SPEC-002, SPEC-004 |
| **Code** | `agent.py` (`CallLogger`, session event handlers, `anonymize`), `dashboard/sql/schema.sql` (`call_logs`) |

## 1. Summary
Every call is logged to PostgreSQL: an anonymized caller id, start/end/duration, the booking
outcome, the full turn-by-turn transcript, and per-turn STT/LLM/TTS latency metrics. The whole
record — call + all turns + all metrics — is written in a **single atomic INSERT** at call end.

## 2. Problem & goals
- **Problem:** persist enough per-call detail to power the dashboard and to debug recognition
  errors, without leaking PII or risking partial/torn writes.
- **Goals:** one row per call; transcript and metrics captured turn by turn in memory and
  flushed atomically; no raw phone number stored at rest.
- **Non-goals:** storing raw call audio; real-time streaming of turns to the DB mid-call.

## 3. Design
`CallLogger` accumulates state for one call in memory:
- `add_turn(speaker, text, confidence, language)` — appends `{turn_id, speaker, text,
  started_at, ended_at, confidence, language}`; fed by the `conversation_item_added` event
  (caller/agent text) and tagged with the language from `user_input_transcribed` (see SPEC-006).
- `add_metric(kind, value)` — appends `{type, value, at}` for `llm.ttft`, `tts.ttfb`,
  `stt.duration`; fed by `metrics_collected`.
- `outcome` / `booking_summary` — set by the tools (`menu_only`, `booked`, …).

`save()` runs once, in a `ctx.add_shutdown_callback`, computing duration and doing a single
INSERT with the transcript and metrics serialized as JSONB. Because everything lands in one
statement, the call record and all its turns are consistent — there are no half-written calls.

**Privacy:** `anonymize()` stores `"anon-" + sha256(raw_phone)[:12]` — never the raw number.
The raw number is held only in memory during the call so the WhatsApp confirmation can reach
the caller (SPEC-007).

## 4. Data & interfaces
`call_logs` (`dashboard/sql/schema.sql`):
`call_id UUID PK · caller_id TEXT (hash) · start_time · end_time · duration_seconds ·
booking_outcome (checked enum: booked/failed/cancelled/menu_only/transferred/unknown) ·
transcript JSONB · metrics JSONB · created_at`. Index on `start_time DESC` for the dashboard.

## 5. Edge cases & failure handling
- A `save()` failure is caught and logged — it must not crash worker shutdown.
- Event-handler exceptions (transcript/metrics logging) are caught so a logging hiccup never
  breaks the live call.
- Empty-text turns are ignored.

## 6. Verification
- Place a call, hang up, then `SELECT call_id, booking_outcome, jsonb_array_length(transcript)
  FROM call_logs ORDER BY start_time DESC LIMIT 1;` — one row, turns > 0, sensible outcome.
- Confirm `caller_id` is an `anon-…` hash, not a phone number.
- **Q13 debugging:** the transcript + per-turn `confidence`/`language` let you compare what the
  caller said vs. the booked `customer_name` to tell STT mishearing from LLM drift.

## 7. Open questions / future work
- Optionally retain name-segment audio (opt-in) to debug homophone errors.
- Export metrics to Prometheus for cross-call p50/p95/p99 (see SPEC-004 §future).
