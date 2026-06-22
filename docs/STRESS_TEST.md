# B3 — Concurrency Stress Test Results

_Run 2026-06-22 15:41 · 20 concurrent × 2 rounds = 40 calls · wall time 173.7s · errors/dropped: 0_

## Latency (milliseconds)

| Stage | samples | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| STT (Whisper) | 40 | 66850 | 78755 | 79749 | 79951 |
| LLM time-to-first-token | 40 | 1372 | 9379 | 10003 | 10109 |
| TTS | 40 | 12517 | 19051 | 19138 | 19159 |

## Peak resource usage

| Resource | Peak |
|---|---|
| Host CPU | 100% |
| Host RAM | 97% |
| GPU VRAM (Ollama/LLM) | 2904 MiB |
| speaches container CPU / RAM | 410% / 1.596GiB |
| kokoro container CPU / RAM | 587% / 2.33GiB |

## Interpretation

- **Everything runs on one 6-core laptop** that is simultaneously the STT server, LLM, TTS server *and* the load generator. Host CPU saturates at 100% and RAM at 97%.
- **CPU STT is the hard bottleneck.** Whisper-on-CPU serialises under load — 20 concurrent transcriptions queue behind ~6 cores, so p50 balloons to ~67 s. The speaches + kokoro containers together demand ~10 cores of work on a 12-thread chip.
- **The GPU LLM holds up best.** Time-to-first-token stays at p50 ~1.4 s even under load (VRAM peak ~2.9 GB, well inside 6 GB); the p95/p99 of ~9–10 s reflect Ollama **queuing** concurrent requests, not GPU exhaustion.
- **0 dropped / 0 errored** — the system degrades *gracefully* (slower), it does not crash.

### What this implies for scaling
A single box comfortably handles ~2–4 truly-concurrent calls; beyond that, latency explodes because STT/TTS are CPU-bound. To serve 20 concurrent calls in production: (1) move **STT and TTS to the GPU** or dedicated nodes; (2) run **multiple agent workers** behind LiveKit (horizontal scale, coordinated via Redis); (3) scale the model servers independently — a pool of Whisper/Kokoro replicas plus a batched LLM server (e.g. vLLM). The architecture already supports this: every component is a separate, independently-scalable service.

### Reproduce
```bash
python scripts/stress_test.py --concurrency 20 --rounds 2
```
