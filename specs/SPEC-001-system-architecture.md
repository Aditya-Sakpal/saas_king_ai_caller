# SPEC-001 — System architecture & self-hosted stack

| | |
|---|---|
| **Status** | Implemented |
| **Owner** | Aditya Sakpal |
| **Version** | 2 |
| **Satisfies** | Q1 (architecture), Q2 (component selection), Q3 (latency budget) |
| **Related specs** | SPEC-002, SPEC-003, SPEC-004, SPEC-005 |
| **Code** | `docker/docker-compose.yml`, `agent.py`; write-up in `docs/ANSWERS.md` |

## 1. Summary
Spice Garden is a fully self-hosted LiveKit voice agent for restaurant table bookings and
menu queries. Speech-to-text, the LLM, and text-to-speech all run on the local machine — no
third-party hosted AI APIs. This spec fixes the end-to-end architecture, the component
choices, and the latency budget that everything else is built against.

## 2. Problem & goals
- **Problem:** take a phone-style voice booking from caller audio to a confirmed reservation
  while keeping all AI on-box (privacy + cost) and grounded in a real database.
- **Goals:** one clear media → VAD → STT → LLM(+tools) → TTS loop; every component
  self-hostable on a single 6 GB-GPU laptop; a documented latency budget and the levers to
  hit it; no hosted AI dependency in the default path.
- **Non-goals:** horizontal autoscaling, multi-tenant infra, and managed-cloud STT/LLM/TTS.
  The live *phone* demo may use LiveKit Cloud **purely as the SIP pipe** (documented
  deviation); the `docker compose` stack stays fully self-hosted.

## 3. Design
Single agent worker runs the turn loop and talks to four local services over
OpenAI-compatible HTTP REST, plus PostgreSQL over TCP:

```
Caller ─SIP/RTP─▶ LiveKit (SFU + SIP) ─WebRTC/Opus─▶ Agent worker
   Agent loop: Silero VAD → Whisper STT → Ollama LLM (+SQL tools) → Kokoro TTS
   Agent ─SQL─▶ PostgreSQL (menu, tables, bookings, call_logs)
```

| Layer | Choice | Why |
|---|---|---|
| Media/transport | self-hosted **livekit-server** | OSS WebRTC SFU with first-class SIP + Python Agents SDK |
| Agent | **LiveKit Agents** (Python) | built-in VAD/STT/LLM/TTS orchestration, interruption + metrics events; plugin pattern keeps it self-hosted |
| VAD | **Silero** (tuned) | in-proc, tunable endpointing |
| STT | **Whisper** `faster-distil-whisper-small.en` via **Speaches** | strong on numbers/dates/names; CPU-only, leaves the GPU for the LLM |
| LLM | **Ollama** `qwen2.5:7b` (GPU) | upgraded from `3b` (which was unreliable at tool-calling) for dependable bookings; ~5 GB resident on the 6 GB card, ~1.5–2.5 s warm TTFT. Compose defaults to `3b` for CPU portability. |
| TTS | **Kokoro** `af_bella` | tiny, natural English, OpenAI-compatible, CPU-only |
| DB + logs | **PostgreSQL** | transactional booking integrity + JSONB call logs in one store |

All four AI services expose an OpenAI-compatible REST surface, so a single LiveKit plugin
family (`openai.*`) drives STT, LLM, and TTS just by pointing `*_BASE_URL` at localhost.

## 4. Data & interfaces
- Service endpoints are env-driven with localhost defaults (`STT_BASE_URL`, `LLM_BASE_URL`,
  `TTS_BASE_URL`, `LLM_MODEL`, `STT_MODEL`, `TTS_VOICE`); compose overrides them with service
  names. See `agent.py` top-of-file constants.
- Protocols: SIP/RTP (caller↔LiveKit), WebRTC/Opus (LiveKit↔agent), HTTP REST (agent↔AI
  services), SQL/TCP (agent + dashboard↔Postgres).

## 5. Edge cases & failure handling
Per-hop retry/fallback is specified in `docs/ANSWERS.md` Q1: STT/LLM/TTS nodes retry ~4×
with backoff; DB errors return a safe string so the LLM never claims a success it doesn't
have; a failed WhatsApp/email notification is swallowed and never blocks the booking. On
unrecoverable LLM failure the session closes cleanly and the call log is still written by the
shutdown callback.

## 6. Verification
- `docker compose -f docker/docker-compose.yml config` validates; a full `up` brings every
  service healthy with `depends_on: service_healthy` gates (see SPEC-005).
- Latency budget (Q3): target ~1.5–2.5 s to first audio; current ~7 s dominated by CPU
  Whisper (~3.5 s). STT runs on the CPU **by deliberate tradeoff** — the 6 GB GPU is spent on
  the reliable 7B LLM, so we chose booking correctness over raw speed. Closing it preserves the
  model and adds hardware: STT on its own/larger GPU (sub-second, same accuracy), services split
  across hosts (also kills call jitter), LLM pinned in VRAM (done), shorter VAD silence.

## 7. Open questions / future work
- Give STT its own/larger GPU (or split LLM and STT across hosts) to land inside the acceptable
  latency band **without shrinking the model**.
- Multi-worker concurrency + Redis coordination for >1 simultaneous call (see SPEC-008).
