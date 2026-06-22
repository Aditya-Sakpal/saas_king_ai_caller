# SPEC-002 — Voice booking agent: conversation flow & tools

| | |
|---|---|
| **Status** | Implemented |
| **Owner** | Aditya Sakpal |
| **Version** | 1 |
| **Satisfies** | Q4 (agent loop), Q5 (prompt + typed tools), Q8 (state machine), Q9 (edge cases), Q10 (complex utterance) |
| **Related specs** | SPEC-001, SPEC-003, SPEC-007 |
| **Code** | `agent.py` (`RestaurantHost`, tools, `parse_when`), `prompts/prompt.txt` |

## 1. Summary
The core agent: a warm phone host ("Aria") that collects a booking conversationally, checks
real DB availability, books or offers alternatives, and answers menu questions — all grounded
in the database via function-calling tools. Behaviour is split between code (deterministic
parsing + DB) and the system prompt (persona + ordered conversation rules).

## 2. Problem & goals
- **Problem:** turn free-form spoken requests into correct, non-hallucinated bookings with a
  small local LLM that is only marginal at tool-calling.
- **Goals:** collect party size → date → time → name one question at a time; never invent
  dishes, availability, or confirmation numbers; handle interruptions, self-corrections, and
  multi-intent utterances; keep date/time maths out of the LLM.
- **Non-goals:** payments, modifying/cancelling existing bookings by phone, multi-restaurant
  routing.

## 3. Design
**Loop (Q4):** `AgentSession` wires Silero VAD → Whisper STT → Ollama LLM (+tools) → Kokoro
TTS, with `turn_detection="vad"` and interruptions on by default. VAD is tuned in `prewarm`
(`activation_threshold=0.6`, `min_silence_duration=0.55`) to ignore noise and only trigger on
clear speech.

**State machine (Q8):** prompt-driven and tool-gated —
`greeting → collecting_party_size → collecting_date → collecting_time → availability_check →
{available → confirmation_pending → confirmed | unavailable → collecting_time} → call_ended`.
`menu_query` and `unexpected_input` are cross-cutting (reachable from any state). State only
advances on a real DB result, never on the model's say-so.

**Date/time parsing in code, not the LLM:** `parse_when()` + `_extract_time()` +
`_resolve_date()` turn "tomorrow at 4 PM" / "next Saturday 7:30pm" / "friday evening at 8"
into a concrete `(date, time)`. Weekdays and today/tonight/tomorrow are handled directly;
`dateparser` is the fallback for explicit dates. This keeps the small LLM out of date maths.

**Grounding rules (prompt):** the agent may only state availability after `check_availability`
returns yes, and only give a confirmation number that `create_booking` returned. Voice-style
rules (one question at a time, don't re-ask, no "let me check…" without calling the tool,
spoken-form prices/times) live in `prompts/prompt.txt`, read once at startup so they can be
edited without a redeploy.

## 4. Data & interfaces
Four typed function tools on `RestaurantHost` (Q5):

| Tool | Args | Returns / effect |
|---|---|---|
| `check_date()` | — | today's date/time (only if the caller explicitly asks) |
| `get_menu(category="")` | category ∈ Starters/Mains/Breads/Desserts/Drinks or all | available items from `menu_items`; sets outcome `menu_only` |
| `check_availability(party_size, when)` | int, spoken day+time | smallest free table seating the party at that slot, or "offer another time" |
| `create_booking(customer_name, party_size, when, special_requests="")` | — | atomic INSERT into `bookings`; sets outcome `booked`; fires WhatsApp |

Availability uses `_find_available_table()`: smallest `available` table with `capacity >=
party_size` not already `confirmed` at that date+time. `create_booking` guards against an
empty `customer_name` (the small LLM sometimes books without asking).

## 5. Edge cases & failure handling (Q9, Q10)
- **Barge-in:** TTS stops instantly; new utterance captured and answered.
- **Silence:** gentle re-prompt, then graceful end.
- **Low/again no STT confidence on critical fields:** confirm by read-back before acting.
- **Off-topic:** politely redirect to booking/menu scope.
- **Self-correction ("eight… make it six"):** later value wins (`party_size=6`).
- **Multi-intent utterance:** resolve menu question + booking + special request in order;
  `special_requests` carried through to the `bookings` row and the confirmation.

## 6. Verification
- `python agent.py console` — talk through a full booking via mic; confirm the agent asks one
  thing at a time, only confirms after the tool returns, and reads back the real confirmation #.
- Check the `bookings` row matches the spoken request (party size, date/time, special request).
- Off-topic and self-correction utterances behave per Q9/Q10.

## 7. Open questions / future work
- Name read-back step to cut homophone booking errors (see Q13 / SPEC-003 debugging notes).
- A larger/GPU LLM would reduce the "narrates instead of calling the tool" failure mode.
