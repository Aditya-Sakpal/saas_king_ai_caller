# SPEC-004 — Admin & call-log dashboard

| | |
|---|---|
| **Status** | Implemented |
| **Owner** | Aditya Sakpal |
| **Version** | 1 |
| **Satisfies** | Q11 (call-log dashboard), Q12 (observability/metrics design) |
| **Related specs** | SPEC-002, SPEC-003 |
| **Code** | `dashboard/app.py`, `dashboard/db.py`, `dashboard/templates/{admin,calls,call_detail}.html` |

## 1. Summary
A small FastAPI app with two faces: an **admin** view to toggle table allocation and menu-item
availability (the same data the agent's tools read), and a **call-log** view listing today's
calls with a 7-day booking success rate, plus a per-call detail page with the full transcript
and a per-turn latency chart.

## 2. Problem & goals
- **Problem:** operators need to manage availability and review what calls did, without
  touching the database by hand.
- **Goals:** toggles write straight to Postgres so the agent sees them immediately; call list +
  success rate + transcript + latency chart from `call_logs`.
- **Non-goals:** auth/RBAC, editing bookings, multi-restaurant views.

## 3. Design
Routes in `dashboard/app.py`:
- `GET /` — admin: menu items + tables.
- `POST /menu/{id}/toggle` — flip `is_available`. `POST /table/{id}/toggle` — flip
  `available`⇄`allocated`. Both write directly and 303-redirect back.
- `GET /calls` — today's calls (`start_time::date = CURRENT_DATE`) + 7-day success rate
  (`booked / total` over the last 7 days).
- `GET /calls/{call_id}` — one call: full transcript + the `metrics` JSON passed to the
  template, which renders the per-turn STT/LLM/TTS latency bar chart.

Server-rendered Jinja2 templates; no JS framework. The dashboard and the agent share the same
`DATABASE_URL`, so admin toggles take effect on the agent's next tool call with no sync step.

## 4. Data & interfaces
Reads `menu_items`, `restaurant_tables`, and `call_logs` (SPEC-003 schema). `jsonb_array_length`
gives the turn count per call; the success-rate query uses
`count(*) FILTER (WHERE booking_outcome = 'booked')`.

## 5. Edge cases & failure handling
- Unknown `call_id` → 404 "Call not found".
- Zero calls in the window → success rate shows 0.0 rather than dividing by zero.

## 6. Verification
- `python dashboard/app.py` → http://localhost:8001 (admin) and `/calls`.
- Toggle a menu item off, ask the agent for it — it should no longer be offered.
- Open a call detail page after a real call — transcript renders and the latency chart shows
  per-turn `llm.ttft` / `tts.ttfb` / `stt.duration`.

## 7. Observability design (Q12) & future work
- Today, per-turn metrics live in `call_logs.metrics` and the dashboard charts them per call.
- For production, export the same series (`stt_latency_ms`, `llm_ttft_ms`, `tts_ttfb_ms`,
  `e2e_response_ms`, `booking_success_rate`, `call_error_or_drop_rate`, host CPU/RAM, GPU VRAM)
  to Prometheus and graph p50/p95/p99 + the booking funnel in Grafana, with alerts on the
  thresholds in `docs/ANSWERS.md` Q12.
