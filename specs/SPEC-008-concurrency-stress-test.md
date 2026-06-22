# SPEC-008 — Concurrency stress test (B3)

| | |
|---|---|
| **Status** | Implemented |
| **Owner** | Aditya Sakpal |
| **Version** | 1 |
| **Satisfies** | B3 (concurrency stress test, 20 concurrent calls) |
| **Related specs** | SPEC-001 |
| **Code** | `scripts/stress_test.py`; output `docs/STRESS_TEST.md` |

## 1. Summary
A load tool that fires N concurrent "calls" — each call = one STT + one LLM + one TTS request —
at the local services and reports latency percentiles per stage plus peak per-service resource
usage, writing a results table to `docs/STRESS_TEST.md`.

## 2. Problem & goals
- **Problem:** understand how the single-box self-hosted pipeline behaves under simultaneous
  load before trusting it with concurrent calls.
- **Goals:** drive a configurable concurrency × rounds; measure STT, LLM time-to-first-token,
  and TTS latency (p50/p95/p99/max); sample peak host CPU/RAM, GPU VRAM, and per-container
  CPU/RAM during the run; emit a reproducible markdown report.
- **Non-goals:** simulating full WebRTC/SIP media sessions; testing the booking logic itself.

## 3. Design
- Generates a test WAV once via Kokoro, then for each call runs STT → LLM(streaming TTFT) →
  TTS against the local endpoints, timing each stage with `perf_counter`.
- `asyncio.gather` fires `concurrency` calls at once, repeated for `rounds` (default 20 × 2).
- A background `Sampler` thread polls once a second: host CPU/RAM via `psutil`, GPU VRAM via
  `nvidia-smi`, and per-container CPU/RAM via `docker stats` for `speaches`/`kokoro`.
- `pct()`/`summary()` compute percentiles; the report (latency table + peak-resource table) is
  printed and written to `docs/STRESS_TEST.md`.

## 4. Data & interfaces
- CLI: `python scripts/stress_test.py --concurrency 20 --rounds 2`.
- Endpoints: STT `:8000`, LLM `:11434`, TTS `:8880` (must be running).
- Output: `docs/STRESS_TEST.md` — run metadata, latency table (ms), peak-resource table.

## 5. Edge cases & failure handling
- Per-request exceptions increment an `errors` counter instead of aborting the run.
- GPU/`docker stats` sampling is wrapped in try/except so the test still runs without an NVIDIA
  GPU or without those containers.

## 6. Verification
- With the services up, run the command; confirm `docs/STRESS_TEST.md` is written with non-empty
  latency percentiles and a sensible error count.

## 7. Open questions / future work
- Add an end-to-end variant that drives real LiveKit sessions (not just the AI endpoints) to
  measure media-path concurrency.
- Capture sustained-throughput (calls/min) in addition to per-stage latency.
