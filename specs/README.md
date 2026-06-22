# Specs — Spice Garden voice agent

This folder holds the **design specs** for the project. We work spec-first: every feature and
every non-trivial bug fix is designed in a spec here **before** it's implemented, and the spec
is kept in sync with the code. The workflow rules live in [`../CLAUDE.md`](../CLAUDE.md).

## How to use this folder

1. **Read before you design.** Read the central memory and the relevant specs below; reuse
   existing decisions, don't duplicate a spec.
2. **Write the spec.** Copy [`SPEC-TEMPLATE.md`](SPEC-TEMPLATE.md) to the next
   `SPEC-NNN-kebab-title.md` and fill it in. Touching an existing feature? Update its spec and
   bump the `Version` instead of adding a new one.
3. **Review it** before writing code, then **implement against it** and keep both in sync.
4. **Update memory** with any cross-cutting decision or reusable pattern, and push the spec with
   the code.

A spec is the **design** (what/why/how, edge cases, verification) — not a task list.

## Status legend
`Draft` → being written · `Approved` → reviewed, ready to build · `Implemented` → built & in the
code · `Superseded` → replaced by a later spec (links to it).

## Index

| Spec | Title | Satisfies | Status |
|---|---|---|---|
| [SPEC-001](SPEC-001-system-architecture.md) | System architecture & self-hosted stack | Q1–Q3 | Implemented |
| [SPEC-002](SPEC-002-voice-booking-agent.md) | Voice booking agent: conversation flow & tools | Q4, Q5, Q8–Q10 | Implemented |
| [SPEC-003](SPEC-003-call-logging.md) | Call logging & transcript persistence | Q6, Q13 | Implemented |
| [SPEC-004](SPEC-004-dashboard.md) | Admin & call-log dashboard | Q11, Q12 | Implemented |
| [SPEC-005](SPEC-005-self-hosted-deployment.md) | Self-hosted deployment (docker compose) | Q7 | Implemented |
| [SPEC-006](SPEC-006-multilingual.md) | Multilingual support | B1 | Implemented (partial) |
| [SPEC-007](SPEC-007-post-call-notifications.md) | Post-call notifications: WhatsApp + manager email PDF | B2 | Implemented |
| [SPEC-008](SPEC-008-concurrency-stress-test.md) | Concurrency stress test | B3 | Implemented |

The `Q#`/`B#` requirement IDs map to the design write-ups in
[`../docs/ANSWERS.md`](../docs/ANSWERS.md) and the self-assessment checklist in
[`../README.md`](../README.md).
