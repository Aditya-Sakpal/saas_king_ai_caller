# CLAUDE.md — Spice Garden voice agent

Agent rules for this repo. Read this before designing or changing anything.

## Spec-driven development (required)

Every feature and every non-trivial bug fix gets a **spec** in [`specs/`](specs/) **before**
code is written. A spec is the design — not a plan/to-do list. The flow is:

1. **Read first.** Read the central memory (the agent's `memory/MEMORY.md` index and any
   relevant entries) and the existing specs in [`specs/`](specs/). Reuse what's there;
   don't re-derive a decision that's already recorded or duplicate an existing spec.
2. **Write the spec.** Copy [`specs/SPEC-TEMPLATE.md`](specs/SPEC-TEMPLATE.md) to the next
   `SPEC-NNN-short-title.md`, fill it in, and review it properly before implementing.
   If the change touches an existing feature, **update that feature's spec** instead of
   adding a new one.
3. **Implement against the spec.** Keep code and spec in sync; if the design changes during
   implementation, update the spec in the same change.
4. **Update memory.** If the work established a cross-cutting decision, a reusable pattern,
   or repetition worth capturing, record it in memory so the next task inherits it.
5. **Push the spec and the memory update with the code.** The spec is part of the deliverable.

Don't skip the spec because a change "looks like a one-liner" — the spec is where the
reasoning lives so the next person (or agent) doesn't have to reverse-engineer it.

## Conventions

- **Specs:** `specs/SPEC-NNN-kebab-title.md`, numbered sequentially. Index in
  [`specs/README.md`](specs/README.md). Each spec links the requirement IDs it satisfies
  (the `Q#`/`B#` items in [`docs/ANSWERS.md`](docs/ANSWERS.md) and the README checklist) and
  the code paths that implement it.
- **Folder layout:** `agent.py` (worker), `prompts/` (persona/rules), `dashboard/` (FastAPI +
  SQL + templates), `scripts/` (one-off ops tools), `docs/` (write-ups), `docker/` (compose +
  Dockerfile). Keep new files in the matching folder.
- **Secrets** live only in `.env` (git-ignored). Never hard-code keys; read from env with a
  sensible localhost default, the way `agent.py` does.
- **Grounding:** the agent must never invent menu items, availability, or confirmation
  numbers — those come only from a tool/DB result. Preserve this when changing tools.

## Where things are

- Voice agent + tools + call logging: [`agent.py`](agent.py)
- Persona / conversation rules: [`prompts/prompt.txt`](prompts/prompt.txt)
- Schema + seed: [`dashboard/sql/`](dashboard/sql/)
- Dashboards (admin + call log): [`dashboard/app.py`](dashboard/app.py), [`dashboard/templates/`](dashboard/templates/)
- Design write-ups (Q1–Q13): [`docs/ANSWERS.md`](docs/ANSWERS.md)
- Self-hosted stack: [`docker/docker-compose.yml`](docker/docker-compose.yml)
