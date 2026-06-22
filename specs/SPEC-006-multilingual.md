# SPEC-006 — Multilingual support (B1)

| | |
|---|---|
| **Status** | Implemented (partial — see §7) |
| **Owner** | Aditya Sakpal |
| **Version** | 1 |
| **Satisfies** | B1 (multilingual: auto-detect + per-turn language labels) |
| **Related specs** | SPEC-002, SPEC-003 |
| **Code** | `agent.py` (`STT_LANGUAGE`, `user_input_transcribed` handler, `CallLogger.last_user_language`), `prompts/prompt.txt` |

## 1. Summary
The agent can take a call in more than one language: Whisper auto-detects the spoken language
per turn, the detected language is recorded on each caller transcript turn, and the LLM is
instructed to reply in the caller's language and follow them if they switch mid-call.

## 2. Problem & goals
- **Problem:** Spice Garden's callers may speak Hindi, Telugu, or Tamil, not just English.
- **Goals:** detect the caller's language automatically (no menu/prompt for it); reply in the
  same language; switch naturally if the caller switches; label each caller turn with its
  detected language in the transcript for review.
- **Non-goals:** full spoken TTS in every language (constrained by the TTS voice set — see §7);
  translation of the menu data itself.

## 3. Design
- **STT auto-detect:** `STT_LANGUAGE` defaults to `"en"`; set it to `""` to omit the `language`
  arg so Whisper auto-detects. `agent.py` only passes `language` when `STT_LANGUAGE` is
  non-empty (`**({"language": STT_LANGUAGE} if STT_LANGUAGE else {})`).
- **Per-turn language label:** the `user_input_transcribed` handler stores
  `ev.language` on `call_log.last_user_language` for each final caller transcript; the
  `conversation_item_added` handler tags the caller turn with that language when logging it
  (so the transcript shows the language per turn — SPEC-003).
- **In-language replies:** `prompts/prompt.txt` instructs Aria to detect Hindi/Telugu/Tamil and
  reply in that same language, switching naturally if the caller switches.

## 4. Data & interfaces
- Env: `STT_LANGUAGE` (`""` = auto-detect), and a multilingual `STT_MODEL` for non-English
  (the default `…-small.en` is English-only).
- `call_logs.transcript[].language` carries the detected language for caller turns.

## 5. Edge cases & failure handling
- If detection returns nothing, the turn is logged with `language=None` (rendered as `en`),
  which is a safe default and never blocks the call.
- Mixed-language turns: each turn is labelled independently, so a mid-call switch is captured.

## 6. Verification
- Set `STT_LANGUAGE=""` and a multilingual `STT_MODEL`; speak Hindi → the LLM replies in Hindi
  and the caller turns in `call_logs.transcript` carry the detected language.

## 7. Open questions / future work
- **Spoken output is the gap:** Kokoro `af_bella` has no Telugu/Tamil voice, so spoken replies
  are English/Hindi only. For Hindi TTS use `TTS_VOICE=hf_alpha`; full Telugu/Tamil speech needs
  a different TTS engine/voice. Text detection + in-language LLM replies + transcript labels are
  done; this is why the README marks B1 "partial".
