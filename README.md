# 🍽️ Spice Garden — Self-Hosted Voice AI Restaurant Agent

A **fully self-hosted** LiveKit voice agent that takes restaurant table bookings and answers
menu queries over a phone-like voice interface. Speech-to-text, the LLM, and text-to-speech all
run **on your own machine** — no third-party hosted AI APIs. Call logs and transcripts are
persisted locally in PostgreSQL.

> **Restaurant:** *Spice Garden* — North Indian + Indo-Chinese · 12:00–23:00 daily · max party 12.

📄 **Design write-ups (Q1–Q3, Q8–Q10, Q12–Q13):** see [`docs/ANSWERS.md`](docs/ANSWERS.md).

---

## What it does
- Greets the caller, collects **party size → date → time → name**, checks **real DB availability**, books (or offers alternatives), and answers **menu** questions — all grounded in the database (no hallucinated dishes/availability).
- **Function-calling tools:** `check_date`, `get_menu`, `check_availability`, `create_booking`.
- **Logs every call** (anonymized caller id, duration, outcome, turn-by-turn transcript, per-turn STT/LLM/TTS latency) to `call_logs`.
- **Admin dashboard** to toggle table allocation + menu availability, and a **call-log dashboard** with transcripts, a latency chart, and a 7-day success rate.
- **WhatsApp** booking confirmation via Twilio (bonus B2).
- Optional **restaurant ambience** under the agent's voice on real calls.

## The self-hosted stack
| Layer | Tech | Port |
|---|---|---|
| Media / transport | **LiveKit** (`livekit-server`, self-hosted) | 7880/1/2 |
| Agent | **LiveKit Agents** (Python) | — |
| VAD | **Silero** (tuned) | in-proc |
| STT | **Whisper** `faster-distil-whisper-small.en` via **Speaches** | 8000 |
| LLM | **Ollama** `qwen2.5:3b` (GPU) | 11434 |
| TTS | **Kokoro** (`kokoro-fastapi`, voice `af_bella`) | 8880 |
| DB + logs | **PostgreSQL** (`restaurant_db`) | 5432 |
| Dashboards | **FastAPI** (admin + call log) | 8001 |

---

## Quick start — Option A: `docker compose` (fully self-hosted, one command)

```bash
cp .env.example .env          # defaults work out of the box for compose
docker compose -f docker/docker-compose.yml up --build
```
> The compose file lives in `docker/`; run it from the repo root with `-f docker/docker-compose.yml`
> (its build context and bind mounts already point up to the repo root).
This brings up **livekit-server, the agent, Ollama (LLM), Whisper (STT), Kokoro (TTS), Postgres**,
and the dashboard — each with a health check and `depends_on: condition: service_healthy`, plus
one-shot jobs that pull the Whisper + LLM models. First boot downloads several GB of images/models.

- Dashboards: **http://localhost:8001** (admin) and **http://localhost:8001/calls** (call log).
- **Place a test call:** connect a LiveKit web client (e.g. the
  [Agents Playground](https://agents-playground.livekit.io)) to `ws://localhost:7880`
  with the dev key/secret `devkey` / `secret`, join a room, and speak — the agent auto-dispatches.

> GPU: Ollama runs on CPU by default in compose. To use an NVIDIA GPU, uncomment the `deploy.resources`
> block under the `ollama` service (requires the NVIDIA Container Toolkit).

## Quick start — Option B: local dev (fastest to iterate; talk via your mic)

**Prerequisites:** Python 3.10–3.12, Docker Desktop, [Ollama](https://ollama.com), PostgreSQL 16.

```bash
# 1) Python env + deps
python -m venv .venv && .venv/Scripts/activate        # (Windows) ; or source .venv/bin/activate
pip install -r requirements.txt
python -m livekit.agents download-files                # Silero VAD model

# 2) Self-hosted model servers
ollama pull qwen2.5:3b
docker run -d --name speaches -p 8000:8000 ghcr.io/speaches-ai/speaches:latest-cpu
curl -X POST "http://localhost:8000/v1/models/Systran/faster-distil-whisper-small.en"   # install STT model
docker run -d --name kokoro   -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu:v0.5.0

# 3) Database (point DATABASE_URL in .env at your Postgres) + seed
cp .env.example .env
python dashboard/init_db.py                            # creates schema + loads seed data

# 4) Run the dashboard (separate terminal)
python dashboard/app.py                                # http://localhost:8001

# 5) Talk to the agent through your microphone (no LiveKit server needed)
python agent.py console
```

**Place a test call (real phone, via LiveKit Cloud SIP):** point `LIVEKIT_URL/API_KEY/API_SECRET`
in `.env` at a LiveKit Cloud project with an inbound SIP trunk + dispatch rule, set `AGENT_NAME` to
the dispatched agent name, run `python agent.py dev`, then dial your provisioned number. (This is a
documented deviation — cloud is used **only** as the SIP pipe; STT/LLM/TTS stay local.)

---

## Required env vars
See [`.env.example`](.env.example). Key ones: `DATABASE_URL`, the `LIVEKIT_*` trio, the
`*_BASE_URL` / `*_MODEL` endpoints, and (optional) `TWILIO_*` + `BOOKING_NOTIFY_WHATSAPP` for
WhatsApp, `BACKGROUND_AUDIO=1` for ambience. **Secrets live only in `.env`, which is git-ignored.**

## Seed data
[`dashboard/sql/seed.sql`](dashboard/sql/seed.sql) — **18 menu items** (incl. *Rogan Josh*, the lamb dish),
**10 tables**, and **6 bookings** (5 confirmed + 1 cancelled). Reset anytime with
`python dashboard/init_db.py`.

---

## Repository layout

```
spice-garden/
├── agent.py              # LiveKit voice agent worker (VAD → STT → LLM → TTS, tools, call logging)
├── prompts/
│   └── prompt.txt        # Aria's persona + conversation rules (read at startup)
├── dashboard/            # FastAPI web app
│   ├── app.py            #   routes: admin (/), call log (/calls, /calls/{id})
│   ├── db.py             #   PostgreSQL connection helper
│   ├── init_db.py        #   create schema + load seed data
│   ├── sql/              #   schema.sql + seed.sql
│   └── templates/        #   admin.html, calls.html, call_detail.html
├── scripts/              # one-off operational tools
│   ├── sip_check.py      #   verify LiveKit Cloud SIP trunk + dispatch rule
│   └── stress_test.py    #   B3 concurrency stress test → writes docs/STRESS_TEST.md
├── docs/                 # design write-ups
│   ├── ANSWERS.md        #   Q1–Q3, Q8–Q10, Q12–Q13
│   └── STRESS_TEST.md    #   stress-test results
├── docker/
│   ├── docker-compose.yml  # full self-hosted stack (run: docker compose -f docker/docker-compose.yml up)
│   └── Dockerfile          # shared image for the agent worker + dashboard
├── .dockerignore         # keeps .venv/.git/etc. out of the build context
├── requirements.txt
└── .env.example
```

---

## ✅ Self-assessment checklist

| Feature | Status | Where |
|---|---|---|
| **Q1** System architecture diagram + protocols + retry + LLM-failure | ✅ Done | `docs/ANSWERS.md` |
| **Q2** Component selection justification | ✅ Done | `docs/ANSWERS.md` |
| **Q3** Latency budget | ✅ Done | `docs/ANSWERS.md` |
| **Q4** Agent: full booking flow, menu, DB availability, VAD, interruptions, turn events, logging | ✅ Done | `agent.py` |
| **Q5** System prompt + ≥3 typed tool schemas (4 tools) | ✅ Done | `prompts/prompt.txt`, `agent.py` |
| **Q6** Call logging + transcript storage (atomic) | ✅ Done | `dashboard/sql/schema.sql`, `agent.py` (`CallLogger`) |
| **Q7** `docker compose up` (all services, health checks, depends_on) | ✅ Done* | `docker/docker-compose.yml`, `docker/Dockerfile` |
| **Q8** Booking state machine | ✅ Done | `docs/ANSWERS.md` |
| **Q9** Edge-case handling | ✅ Done | `docs/ANSWERS.md` |
| **Q10** Complex-utterance walkthrough | ✅ Done | `docs/ANSWERS.md` |
| **Q11** Call-log dashboard (calls, transcripts, latency chart, 7-day success) | ✅ Done | `dashboard/app.py`, `templates/calls.html`, `call_detail.html` |
| **Q12** Observability / metrics design | ✅ Done | `docs/ANSWERS.md` |
| **Q13** Debugging scenario (Aaron/Erin) | ✅ Done | `docs/ANSWERS.md` |
| Seed file (SQL) | ✅ Done | `dashboard/sql/seed.sql` |
| README + setup + self-assessment | ✅ Done | this file |
| **Bonus B2** Post-call notifications (WhatsApp + email PDF) | ✅ Done | `send_whatsapp` + `send_manager_email`/`build_call_pdf` in `agent.py` |
| **Bonus B1** Multilingual (auto-detect + per-turn language labels) | 🟡 Partial | Whisper auto-detect + LLM in-language + transcript language labels ✅; Kokoro TTS has no Telugu/Tamil voice, so spoken output is English/Hindi only (set `STT_LANGUAGE=""` + a multilingual `STT_MODEL`, and `TTS_VOICE=hf_alpha` for Hindi) |
| **Bonus B3** Concurrency stress test (20 concurrent calls) | ✅ Done | `scripts/stress_test.py`, `docs/STRESS_TEST.md` |
| Loom video | ⏺️ To record | — |

\* `docker/docker-compose.yml` is validated (`docker compose -f docker/docker-compose.yml config`
passes); a full `up` pulls several GB of images/models so it's the run-path rather than something executed in CI.

## Known limitations / honest notes
- **LLM reliability:** `qwen2.5:3b` is marginal at tool-calling (occasionally narrates "let me check"
  instead of calling the tool, or over-confirms). Mitigated with strict prompt rules + a code guard
  that rejects empty `customer_name`. A 7B model is more reliable but VRAM-tight on a 6 GB GPU.
- **Latency:** Whisper on CPU is the bottleneck (~3.5 s); moving STT to GPU closes most of the gap.
- **Real-phone jitter:** running STT+LLM+TTS+WebRTC on one laptop can starve the audio threads;
  free CPU/RAM (and keep ambience off) for the smoothest call.
- **Scope deviation:** the live phone demo uses LiveKit **Cloud** as the SIP transport only; all AI
  is self-hosted. The `docker compose` stack is fully self-hosted (self-hosted `livekit-server`).
