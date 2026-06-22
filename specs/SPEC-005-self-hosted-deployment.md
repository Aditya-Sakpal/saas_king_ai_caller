# SPEC-005 — Self-hosted deployment (docker compose)

| | |
|---|---|
| **Status** | Implemented |
| **Owner** | Aditya Sakpal |
| **Version** | 1 |
| **Satisfies** | Q7 (`docker compose up`: all services, health checks, depends_on) |
| **Related specs** | SPEC-001 |
| **Code** | `docker/docker-compose.yml`, `docker/Dockerfile`, `.dockerignore` |

## 1. Summary
One command brings up the entire self-hosted stack — livekit-server, the agent worker, Ollama
(LLM), Whisper (STT), Kokoro (TTS), Postgres, and the dashboard — each with a health check and
ordered startup, plus one-shot jobs that pull the Whisper and LLM models.

## 2. Problem & goals
- **Problem:** a reviewer should be able to run the whole thing without hand-installing seven
  services in the right order.
- **Goals:** `docker compose -f docker/docker-compose.yml up --build` from the repo root brings
  everything up healthy; the agent only starts once its dependencies are actually ready; models
  are pulled automatically; no hosted AI in this path.
- **Non-goals:** GPU by default (opt-in), production secrets management, the SIP/phone path
  (this compose is the no-cloud, web-client variant).

## 3. Design
The compose file lives in `docker/`, so build contexts and bind mounts point up one level
(`..`) to the repo root; it's meant to be run from the root with `-f docker/docker-compose.yml`.

- **Health checks** on every long-running service (`pg_isready`, livekit HTTP, `ollama list`,
  `/health` for STT/TTS, `pgrep` for the agent, `/` for the dashboard).
- **Ordered startup:** the `agent` `depends_on` each dependency with
  `condition: service_healthy`, and on the two one-shot pull jobs with
  `condition: service_completed_successfully`.
- **One-shot model pulls:** `ollama-pull` pulls `qwen2.5:3b`; `stt-pull` installs
  `faster-distil-whisper-small.en`. Both `restart: "no"` and exit.
- **Postgres** auto-loads `schema.sql` then `seed.sql` via the init-dir mounts, and maps host
  `5433:5432` to avoid clashing with a native Postgres on 5432.
- **GPU** is opt-in: uncomment the `deploy.resources` block on `ollama` (needs NVIDIA Container
  Toolkit); CPU by default.

## 4. Data & interfaces
Agent/dashboard get `DATABASE_URL`, `LIVEKIT_*`, and `*_BASE_URL`/`*_MODEL`/`TTS_VOICE` via
compose `environment` pointing at the in-network service names (`stt`, `ollama`, `tts`,
`postgres`, `livekit`). `.dockerignore` keeps `.venv/.git/__pycache__` out of the build context.

## 5. Edge cases & failure handling
- First boot downloads several GB of images/models — slow but unattended.
- If a dependency is unhealthy the agent simply doesn't start (no crash loop against a
  half-ready service).

## 6. Verification
- `docker compose -f docker/docker-compose.yml config` validates the file.
- A full `up` brings all services healthy; dashboards at http://localhost:8001 and
  `/calls`; connect a LiveKit web client to `ws://localhost:7880` (`devkey`/`secret`) to talk
  to the agent.

## 7. Open questions / future work
- Optionally bake a GPU compose override file for one-flag GPU runs.
- A CI smoke job that runs `compose config` + a lightweight health-gate check.
