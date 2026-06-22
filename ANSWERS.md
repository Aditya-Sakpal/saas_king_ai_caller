# Spice Garden — Voice AI Agent: Written Answers

A fully self-hosted LiveKit voice agent for restaurant table bookings and menu queries.
**Restaurant:** *Spice Garden* — North Indian + Indo-Chinese · open 12:00–23:00 daily · max party 12.

**Self-hosted stack:** LiveKit (media/transport) · LiveKit Agents (Python) · Silero VAD · **Whisper** (faster-distil-whisper-small via Speaches) · **Ollama** (qwen2.5:3b) · **Kokoro** TTS · **PostgreSQL**.

> **Scope note (deviation):** the live *phone* demo uses **LiveKit Cloud purely as the SIP/telephony pipe** (a Vobiz PSTN number → Cloud SIP → our worker). All intelligence (STT/LLM/TTS) stays self-hosted on localhost. The `docker compose` variant is fully self-hosted with a self-hosted `livekit-server`.

---

## Q1 — System Architecture

### Diagram (protocols labelled)

```
   ☎  Caller (PSTN phone)
   │   SIP signalling + RTP/SRTP media
   ▼
 ┌─────────────────────┐
 │  SIP trunk (Vobiz)  │
 └─────────────────────┘
   │   SIP over TLS :5061  +  RTP media
   ▼
 ┌──────────────────────────────────────────────┐
 │  LiveKit  (SIP service + SFU media server)    │  cloud in demo / self-hosted (livekit-server) in compose
 │  bridges SIP/RTP  ⇄  WebRTC ; hosts the "room" │  ── coordinates via Redis in multi-node ──
 └──────────────────────────────────────────────┘
   ▲ WebRTC/Opus (agent voice out)   │ WebRTC/Opus (caller audio in)
   │                                 ▼
 ┌──────────────────────────────────────────────┐
 │  Agent worker  (LiveKit Agents, Python)        │  connects out via WebSocket (wss) + WebRTC
 │  loop:  VAD → STT → LLM (+tools) → TTS          │
 └──────────────────────────────────────────────┘
   │ HTTP REST           │ HTTP REST            │ HTTP REST
   │ (OpenAI-compatible) │ (OpenAI-compatible)  │ (OpenAI-compatible)
   ▼                     ▼                      ▼
 ┌──────────┐      ┌────────────┐        ┌────────────┐
 │  STT     │      │   LLM      │        │   TTS      │
 │ Speaches │      │  Ollama    │        │  Kokoro    │
 │ Whisper  │      │ qwen2.5:3b │        │  af_bella  │
 │ (CPU)    │      │ (GPU)      │        │  (CPU)     │
 └──────────┘      └────────────┘        └────────────┘
                                    
 ┌──────────────────────────────────────────────┐        ┌─────────────────────┐
 │  PostgreSQL  (SQL over TCP)                    │◀──────▶│  Agent              │
 │  menu_items · restaurant_tables · bookings     │  SQL   │  (tools + call log) │
 │  call_logs (transcript + metrics, JSONB)       │        └─────────────────────┘
 └──────────────────────────────────────────────┘                  │ HTTPS REST (on booking)
        ▲ SQL/TCP                                                   ▼
 ┌──────────────────────┐                                ┌─────────────────────┐
 │ Dashboard (FastAPI)  │  admin + call log + transcripts │  Twilio WhatsApp     │
 └──────────────────────┘                                └─────────────────────┘
```

### One-turn data flow
1. Caller speaks → audio reaches LiveKit as **WebRTC/Opus** (bridged from SIP/RTP).
2. The agent receives Opus frames; **Silero VAD** detects end-of-utterance (0.55 s silence).
3. The buffered utterance is POSTed to **Whisper** (`/v1/audio/transcriptions`, HTTP) → text.
4. Text + chat history go to **Ollama** (`/v1/chat/completions`, HTTP); the LLM may emit a **tool call** (`check_availability`, `create_booking`, `get_menu`, `check_date`) which runs **SQL** against Postgres; the tool result is fed back and the LLM produces the reply.
5. Reply text → **Kokoro** (`/v1/audio/speech`, HTTP) → audio → published to the room as **WebRTC/Opus** → bridged back through SIP/RTP to the caller.
6. On `create_booking`, the agent fires a **Twilio WhatsApp** confirmation (HTTPS REST). At call end, the full transcript + per-turn metrics are written to `call_logs` in **one atomic SQL INSERT**.

### Retry paths
| Hop | Failure | Behaviour |
|---|---|---|
| STT (Whisper) | timeout / connection error | LiveKit STT node retries (≈4 attempts, backoff); persistent failure → session asks the caller to repeat |
| LLM (Ollama) | timeout / 5xx | LiveKit LLM node retries up to **4 attempts** with backoff (see below) |
| TTS (Kokoro) | connection error | retry up to 4 attempts; on hard failure the turn is dropped and the agent re-prompts |
| DB | connection error | tool returns a safe "let me try again" string; the LLM does **not** claim success |
| WhatsApp | any error | swallowed and logged — a failed notification **never** blocks the booking |

### What happens when the LLM call fails mid-conversation
The LiveKit LLM node **retries the request up to 4 times** with exponential backoff. While retrying, the agent stays in its "thinking" state (we can play a brief filler/hold line). If all 4 attempts fail it raises `APIConnectionError`; the agent then either (a) speaks a graceful fallback — *"I'm so sorry, I'm having a brief technical hiccup — could you say that once more?"* — and re-prompts, or (b) for an unrecoverable error, closes the `AgentSession` cleanly via the `close`/`error` events, and the **call_log is still written** by the shutdown callback (so no data is lost). Because the conversation state lives in the re-sent chat context (not the model), a transient failure loses **nothing** — the next successful call replays the full history.

---

## Q2 — Component Selection Justification

| Layer | Choice | Why (latency · domain accuracy · footprint) |
|---|---|---|
| **livekit-server** | LiveKit (OSS) | Industry-standard WebRTC SFU with first-class **SIP** + a Python **Agents** SDK; sub-150 ms media path; tiny footprint (single Go binary). |
| **agent worker** | LiveKit Agents (Python) 1.6.x | Built-in VAD/STT/LLM/TTS orchestration, interruption handling, metrics + transcript events; we use the **plugin pattern** (not the cloud `inference.*` helpers) to stay self-hosted. |
| **STT** | **faster-distil-whisper-small.en** via **Speaches** | see below |
| **LLM** | **Ollama + qwen2.5:3b** (GPU) | Strong instruction-following + tool-calling for its size; **~0.7–1.2 s** time-to-first-token on a 6 GB RTX 3050 (Q4, ~2 GB VRAM). Grounded entirely in DB tool results so domain accuracy = the data, not the model's memory. |
| **TTS** | **Kokoro** (kokoro-fastapi), voice `af_bella` | see below |
| **Booking DB** | **PostgreSQL** | Transactional integrity for availability/booking (no double-booking), `JSONB` for transcripts, trivial to self-host; the one store doubles as the log store. |
| **Transcript / call-log store** | **PostgreSQL `call_logs`** (JSONB) | Same DB → a call record + all its turns write in **one atomic INSERT**; `JSONB` indexes/queries power the dashboard without a second datastore. |

### STT — faster-distil-whisper-small.en (Speaches, CPU)
- **Latency:** `distil-small.en` runs at several-times-realtime on the 6-core Ryzen; ~0.5–2 s per utterance. (It is, honestly, our latency bottleneck at ~3.5 s including VAD endpointing — a GPU or `base.en` would cut this.)
- **Domain accuracy:** Whisper is robust on **numbers, dates and times** (table sizes, "seven thirty PM") and handles Indian-English far better than Vosk/Sherpa small models; it can still mishear similar names ("Aaron"/"Erin") — addressed by a read-back step (Q13).
- **Footprint:** runs on **CPU**, leaving the 6 GB GPU entirely for the LLM. Speaches gives us an OpenAI-compatible REST surface so one plugin drives STT, LLM and TTS.

### TTS — Kokoro (af_bella, CPU)
- **Latency:** Kokoro-82M is tiny; ~1.2–2.0 s time-to-first-byte on CPU — acceptable for a phone host.
- **Domain accuracy:** clear, natural English diction; we add spoken-form normalisation in the prompt (prices → "two hundred and eighty rupees", times → "seven thirty PM") so it never reads symbols.
- **Footprint:** CPU-only and OpenAI-compatible (drop-in via the same plugin). We chose it over **Piper** because Piper needs a custom wrapper, and over **Coqui** because Coqui is far heavier — Kokoro hits the sweet spot of quality vs. footprint for a self-hosted box.

---

## Q3 — Latency Budget

From "caller stops speaking" → "agent starts speaking":

| Stage | Ideal target | Our measured (this build) | Notes |
|---|---|---|---|
| 1. VAD silence detection | 150–300 ms | **~550 ms** | `min_silence_duration=0.55 s` (tunable down) |
| 2. STT transcription | 150–400 ms | **~3.3–4.9 s** | Whisper on **CPU** — the dominant cost |
| 3. LLM time-to-first-token | 200–500 ms | **~0.7–1.2 s** (warm) | qwen2.5:3b on GPU; ~8–20 s only on a cold load |
| 4. TTS time-to-first-chunk | 150–400 ms | **~1.2–2.0 s** | Kokoro on CPU |
| 5. LiveKit packet delivery | 50–150 ms | **~50–150 ms** | WebRTC; +1 RTT to Cloud region (India West) on the phone demo |
| **Total** | **~1.2–2.5 s** | **~6–7 s observed** | |

**Maximum acceptable:** **~1.5 s** to first audio is the gold standard for a natural phone conversation; up to **~2.5 s** is tolerable if the agent emits a quick acknowledgement ("sure, let me check…") to cover the gap. Beyond ~3 s callers start talking over the agent.

**Why ours is higher and how to close it:** the gap is almost entirely **CPU Whisper (~3.5 s)**. Fixes, in order of impact: (a) move STT to the **GPU** (or `base.en`/`large-v3-turbo` int8) → STT to sub-second; (b) shrink `min_silence_duration` to ~0.35 s; (c) keep the LLM **pinned in VRAM** (we do — `keep_alive`) so TTFT stays ~0.7 s; (d) for the phone demo, host LiveKit in-region. With STT on GPU the budget lands around **2–2.5 s**, inside the acceptable band.

---

## Q8 — Booking Conversation State Machine

```mermaid
stateDiagram-v2
    [*] --> greeting
    greeting --> collecting_party_size
    collecting_party_size --> collecting_date
    collecting_date --> collecting_time
    collecting_time --> availability_check
    availability_check --> confirmation_pending: available
    availability_check --> collecting_time: unavailable (offer another time)
    availability_check --> confirmation_pending: partial_availability (nearest slot)
    confirmation_pending --> confirmed: caller says "yes" + name present
    confirmation_pending --> collecting_time: caller changes details
    confirmed --> call_ended
    cancelled --> call_ended

    menu_query --> menu_query: (enterable from ANY state; returns to prior state)
    unexpected_input --> unexpected_input: (fallback from ANY state; re-prompts)
    greeting --> cancelled: caller declines
```

ASCII fallback: `greeting → collecting_party_size → collecting_date → collecting_time → availability_check →{available→confirmation_pending→confirmed | unavailable→collecting_time} → call_ended`. `menu_query` and `unexpected_input/fallback` are **cross-cutting** — reachable from any state and returning to it.

| State | Purpose | Entry trigger | Exits | How implemented |
|---|---|---|---|---|
| greeting | welcome, establish intent | call connects | → collecting_party_size | `generate_reply` opening line |
| collecting_party_size | get # people | intent = booking | → collecting_date | prompt asks one thing; held in chat context |
| collecting_date | get day | size captured | → collecting_time | prompt; `check_date` if needed |
| collecting_time | get time | date captured | → availability_check | prompt |
| availability_check | DB lookup | size+day+time known | available / unavailable / partial | **`check_availability(party_size, when)`** tool → SQL |
| confirmation_pending | read back, await yes | table free | → confirmed / collecting_time | prompt reads details back |
| confirmed | write booking | "yes" + name present | → call_ended | **`create_booking(...)`** (atomic INSERT) + WhatsApp |
| cancelled | caller backs out | decline | → call_ended | outcome=`cancelled` |
| menu_query | answer food Q | "what's on the menu?" (any state) | → prior state | **`get_menu(category)`** tool; outcome=`menu_only` if no booking |
| unexpected_input / fallback | recover | off-topic / low-confidence | → re-prompt prior state | prompt guard + re-ask |
| call_ended | hang up, log | goodbye / disconnect | → [*] | shutdown callback writes `call_logs` |

The flow is **prompt-driven** (the system prompt in `prompt.txt` encodes the ordered steps and the "one question at a time / don't re-ask / only confirm after the tool returns" rules) and **tool-gated** (state advances only on real DB results, never on the model's say-so).

---

## Q9 — Edge Case Handling

| Scenario | Immediate action | What it says (template) | Recovery |
|---|---|---|---|
| **(a) Caller interrupts the agent** | VAD detects barge-in → `AgentSession` **stops TTS instantly** (`allow_interruptions`, on by default) and starts capturing the new utterance | *(stops talking; listens)* | The interrupted agent turn is marked `interrupted` in the transcript; the new input is transcribed and answered — natural barge-in. |
| **(b) 8 s of silence** | An inactivity timer fires a gentle re-prompt; after a second timeout, the agent offers to end | "Are you still there? … Take your time — would you like to continue with the booking?" then "I'll let you go for now — call back anytime. Goodbye!" | If they respond, resume the prior state; otherwise end gracefully and log `booking_outcome` accordingly. |
| **(c) STT confidence < 0.6 on a date** | Treat the field as **unconfirmed**; read it back for confirmation instead of acting | "Just to confirm — that's **Saturday the 27th**, is that right?" | On "yes" proceed; on "no" re-collect. *(Our local Whisper often returns no confidence at all, so we **confirm critical fields by default** — same safety net.)* |
| **(d) LLM > 3 s to first token** | Cover the gap with a short filler while the 4-attempt retry runs | "Sure — let me check that for you…" | If a token arrives, continue normally; if all retries fail, apologise and re-prompt (see Q1). |
| **(e) Off-topic ("what's the weather?")** | Don't answer; politely redirect to scope | "Ah, I'm just the booking host for Spice Garden, so I can't help with that — but I'd be happy to take a reservation or tell you about the menu!" | Return to the prior state and continue. |

---

## Q10 — Complex Utterance Walk-Through

**Caller:** *"I want a table for eight next Saturday evening, but actually no — make it six. And we need a high chair. Oh also, is your lamb dish still on the menu?"*

1. **STT output:** Whisper transcribes the full run, including the self-correction, e.g. `"i want a table for eight next saturday evening but actually no make it six and we need a high chair oh also is your lamb dish still on the menu"`. The number words ("eight", "six") are high-confidence; "high chair" is reliable. (If the audio were noisy, "six" is the kind of short word we'd confirm.)
2. **LLM parsing of eight → six:** the model reads the correction "actually no — make it six" and sets **`party_size = 6`** (the later value wins). It also extracts three intents: a **booking** (6, next Saturday evening), a **special request** (high chair), and a **menu question** (lamb).
3. **Tools called, in order:**
   - `get_menu(category="Mains")` → returns the live mains incl. **"Rogan Josh"** (our lamb curry) → the agent confirms the lamb dish is available.
   - `check_availability(party_size=6, when="next Saturday evening")` → our Python parser maps "next Saturday evening" → the upcoming Saturday's date at the **19:00** default → SQL finds a free 6+ table → "available".
   - (after the caller confirms) `create_booking(customer_name=<asked>, party_size=6, when="next Saturday evening", special_requests="high chair")`.
4. **High-chair storage:** carried in the `special_requests` argument → written to the `bookings.special_requests` column (and surfaced on the dashboard / WhatsApp).
5. **Agent speaks back:** *"Good news — yes, our Rogan Josh lamb is on tonight. And I can do a table for six this Saturday evening at seven, with a high chair set up for you. Could I get a name for the booking?"* — answering the menu question, confirming the corrected party size, acknowledging the high chair, and moving to capture the name before booking.

---

## Q12 — Observability & Metrics

| Metric | Type | Signal | Alert threshold |
|---|---|---|---|
| `stt_latency_ms` | histogram | Whisper transcription time | p95 > 800 ms |
| `llm_ttft_ms` | histogram | LLM time-to-first-token | p95 > 1500 ms |
| `tts_ttfb_ms` | histogram | TTS time-to-first-byte | p95 > 1000 ms |
| `e2e_response_ms` | histogram | caller-stop → agent-speak | p95 > 2500 ms |
| `vad_endpoint_ms` | histogram | end-of-turn detection | p95 > 700 ms |
| `asr_confidence` | gauge/hist | STT confidence per turn | p10 < 0.6 (rising mis-recognition) |
| `tool_call_success_rate` | gauge | % tool calls that executed | < 95 % |
| `booking_success_rate` | gauge | booked / total calls (7-day) | < 60 % (investigate funnel) |
| `call_error_or_drop_rate` | counter→rate | sessions ended in error | > 2 % |
| `active_concurrent_calls` | gauge | live sessions | > worker capacity |
| `cpu_pct` / `ram_pct` | gauge | host load | > 90 % (jitter risk) |
| `gpu_vram_pct` | gauge | LLM VRAM | > 90 % (OOM risk) |

**How we collect them here:** LiveKit emits per-turn `metrics_collected` events carrying `STTMetrics`, `LLMMetrics(ttft)` and `TTSMetrics(ttfb)`; the agent stores them in **`call_logs.metrics`** (JSONB), and the dashboard renders the per-call **latency bar chart** from that. For production you'd export the same series to **Prometheus** and graph p50/p95/p99 + the funnel in **Grafana**, with Alertmanager on the thresholds above.

---

## Q13 — Debugging Scenario: "Aaron" booked instead of "Erin"

**1. Reproduce from our data.** Query tonight's calls and open the transcripts:
```sql
SELECT call_id, start_time, booking_outcome, transcript
FROM call_logs
WHERE start_time::date = CURRENT_DATE AND booking_outcome = 'booked';
```
Read each `transcript` turn — compare what the **caller said** (the `caller` turns + `asr_confidence`) vs the **name the agent booked** (`create_booking`'s `customer_name`, also visible in `bookings`). This shows whether the error is **STT mishearing** ("Erin"→"Aaron") or **LLM/booking** drift.

**2. Logs/metrics to examine first:** the `user_input_transcribed` text for the name turn; `asr_confidence` on that turn (low confidence on names = STT root cause); the exact `customer_name` argument passed to `create_booking`; and the STT model in use. If recorded audio is kept, listen to the name segment.

**3. Pipeline changes (root cause = homophone STT):**
- **Name read-back + confirm** before booking: "I have that under **E-r-i-n**, is that right?" (cheapest, highest-impact fix).
- **Phonetic/alias post-processing** or a small custom-vocabulary bias for common local names.
- Optionally a **larger/GPU Whisper** model (`large-v3-turbo`) for better name fidelity.
- Spell-on-mismatch fallback ("could you spell that for me?").

**4. Verify + fix without downtime:**
- The name read-back lives in **`prompt.txt`**, which is read at **session start** — edit it and the *next* call uses it, **no redeploy**.
- Correct the wrong rows live (after confirming with guests):
  ```sql
  UPDATE bookings SET customer_name = 'Erin'
  WHERE booking_date = CURRENT_DATE AND customer_name = 'Aaron' AND id IN (...);
  ```
- **Verify:** watch the next calls' `asr_confidence` on name turns and confirm the read-back step appears in transcripts; booking-name accuracy should recover immediately, with zero interruption to in-flight calls.
