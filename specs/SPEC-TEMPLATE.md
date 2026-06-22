# SPEC-NNN — <Title>

| | |
|---|---|
| **Status** | Draft \| Approved \| Implemented \| Superseded |
| **Owner** | <name> |
| **Version** | 1 |
| **Satisfies** | <requirement IDs, e.g. Q4, Q5, B1> |
| **Related specs** | <SPEC-NNN, …> |
| **Code** | <files/paths that implement this> |

## 1. Summary
One paragraph: what this is and why it exists.

## 2. Problem & goals
- **Problem:** what need or gap this addresses.
- **Goals:** the outcomes this must achieve.
- **Non-goals:** what is explicitly out of scope (so reviewers don't expect it).

## 3. Design
The actual design. How it works, the key decisions, and why each was chosen over the
alternatives considered. Diagrams/tables where they clarify.

## 4. Data & interfaces
Schemas, tool/function signatures, env vars, API surfaces, message formats — whatever this
feature reads or writes.

## 5. Edge cases & failure handling
What can go wrong and what happens when it does. A notification failing must never break the
core flow; the agent must never claim success it can't back with a tool result.

## 6. Verification
How we know it works: tests, manual steps, queries to run, what "done" looks like.

## 7. Open questions / future work
Known gaps, deferred decisions, and follow-ups.
