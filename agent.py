from pathlib import Path
import os
import asyncio
import json
import uuid
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

import dateparser
import httpx
import psycopg
from psycopg.rows import dict_row

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import (
    Agent, AgentSession, function_tool, RunContext,
    BackgroundAudioPlayer, AudioConfig, BuiltinAudioClip,
)
from livekit.agents.stt import StreamAdapter
from livekit.plugins import openai, silero


load_dotenv()

# The agent's persona / rules live in prompts/prompt.txt so they can be edited
# without touching code. Read once at startup, relative to THIS file (works from any cwd).
INSTRUCTIONS = (Path(__file__).parent / "prompts" / "prompt.txt").read_text(encoding="utf-8")

logger = logging.getLogger("spice-garden")

# Service endpoints — default to localhost; docker-compose overrides with service names.
STT_BASE_URL = os.getenv("STT_BASE_URL", "http://localhost:8000/v1")
STT_MODEL = os.getenv("STT_MODEL", "Systran/faster-distil-whisper-small.en")
STT_LANGUAGE = os.getenv("STT_LANGUAGE", "en")  # "" = Whisper auto-detect (B1 multilingual)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")
TTS_BASE_URL = os.getenv("TTS_BASE_URL", "http://localhost:8880/v1")
TTS_VOICE = os.getenv("TTS_VOICE", "af_bella")


async def send_whatsapp(body: str, to_number: str | None = None) -> bool:
    """Send a WhatsApp message via Twilio's REST API (sandbox). Never raises —
    a failed notification must not break the booking. Delivers to the caller's own
    number when known (to_number), else the BOOKING_NOTIFY_WHATSAPP fallback.
    NOTE: with the Twilio sandbox the recipient must have joined the sandbox, or
    delivery fails with error 63015 even though the API call returns 201."""
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    sender = os.environ.get("TWILIO_WHATSAPP_FROM")     # e.g. 'whatsapp:+14155238886'
    to = to_number or os.environ.get("BOOKING_NOTIFY_WHATSAPP")
    if not (sid and token and sender and to):
        logger.info("WhatsApp not configured; skipping notification.")
        return False
    recipient = to if to.startswith("whatsapp:") else f"whatsapp:+{to.lstrip('+')}"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url, auth=(sid, token),
                data={"From": sender, "To": recipient, "Body": body},
            )
        if resp.status_code >= 400:
            logger.warning(f"WhatsApp send failed ({resp.status_code}): {resp.text[:300]}")
            return False
        logger.info("WhatsApp confirmation sent.")
        return True
    except Exception as exc:
        logger.warning(f"WhatsApp send error: {exc}")
        return False


def _latin1(s: str) -> str:
    """fpdf core fonts are latin-1; replace unsupported glyphs so the PDF never crashes."""
    return (s or "").encode("latin-1", "replace").decode("latin-1")


def build_call_pdf(call_log) -> bytes:
    """Render a one-page call summary (booking details + full transcript) as PDF bytes."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Spice Garden - Call Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for label, val in [("Call ID", call_log.call_id), ("Caller", call_log.caller_id),
                       ("Outcome", call_log.outcome)]:
        pdf.cell(0, 6, _latin1(f"{label}: {val}"), new_x="LMARGIN", new_y="NEXT")
    if getattr(call_log, "booking_summary", None):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Booking", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for k, v in call_log.booking_summary.items():
            pdf.cell(0, 6, _latin1(f"{k}: {v}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Transcript", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for t in call_log._turns:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 6, _latin1(f"[{t['speaker'].upper()}] {t['text']}"),
                       new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def send_manager_email(call_log) -> bool:
    """B2: email the manager a call summary with the transcript + booking as a PDF.
    Reads SMTP_* + MANAGER_EMAIL from env; skips gracefully if unconfigured. Never raises."""
    host = os.environ.get("SMTP_HOST")
    to = os.environ.get("MANAGER_EMAIL")
    if not (host and to):
        logger.info("SMTP/manager email not configured; skipping email summary.")
        return False
    try:
        import smtplib
        from email.message import EmailMessage
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ.get("SMTP_USER", "")
        pw = os.environ.get("SMTP_PASS", "")
        sender = os.environ.get("SMTP_FROM", user or "noreply@spicegarden.local")
        msg = EmailMessage()
        msg["Subject"] = f"Spice Garden call summary - {call_log.outcome}"
        msg["From"] = sender
        msg["To"] = to
        msg.set_content(
            f"Call {call_log.call_id}\nOutcome: {call_log.outcome}\n"
            f"Caller: {call_log.caller_id}\n\nFull transcript + booking attached as PDF."
        )
        msg.add_attachment(build_call_pdf(call_log), maintype="application",
                           subtype="pdf", filename=f"call-{call_log.call_id[:8]}.pdf")
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            if user:
                s.login(user, pw)
            s.send_message(msg)
        logger.info("manager email sent")
        return True
    except Exception as exc:
        logger.warning(f"manager email failed: {exc}")
        return False


def get_conn():
    """Open a short-lived connection to the restaurant database.
    Reads DATABASE_URL from your .env (same DB the dashboard uses)."""
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def anonymize(raw: str | None) -> str:
    """Q6: never store a raw phone number at rest — keep a short, stable hash."""
    if not raw:
        return "anonymous"
    return "anon-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


class CallLogger:
    """Accumulates the turn-by-turn transcript + per-turn latency metrics for one call,
    then writes the whole record atomically (a single INSERT) when the call ends."""

    def __init__(self, caller_id: str):
        self.call_id = str(uuid.uuid4())
        self.caller_id = caller_id
        self.start_time = datetime.now(timezone.utc)
        self.outcome = "unknown"
        self.booking_summary = None
        self.last_user_language = None
        self._turns: list[dict] = []
        self._metrics: list[dict] = []
        self._n = 0

    def add_turn(self, speaker: str, text: str, confidence=None, language=None):
        if not text:
            return
        self._n += 1
        now = datetime.now(timezone.utc).isoformat()
        self._turns.append({
            "turn_id": self._n,
            "speaker": speaker,          # 'agent' | 'caller'
            "text": text,
            "started_at": now,
            "ended_at": now,
            "confidence": confidence,    # STT confidence for caller turns; null for agent
            "language": language,        # B1: detected language for caller turns
        })

    def add_metric(self, kind: str, value: float):
        self._metrics.append({
            "type": kind,                # 'llm.ttft' | 'tts.ttfb' | 'stt.duration'
            "value": round(float(value), 3),
            "at": datetime.now(timezone.utc).isoformat(),
        })

    def save(self):
        end = datetime.now(timezone.utc)
        duration = int((end - self.start_time).total_seconds())
        # Single atomic INSERT — the call record and all its turns land together.
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO call_logs
                   (call_id, caller_id, start_time, end_time, duration_seconds,
                    booking_outcome, transcript, metrics)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (self.call_id, self.caller_id, self.start_time, end, duration,
                 self.outcome, json.dumps(self._turns), json.dumps(self._metrics)),
            )
            conn.commit()
        return self.call_id, len(self._turns)


_TOD_DEFAULT = {  # default clock time when the caller only says a part of the day
    "morning": (9, 0), "noon": (12, 0), "afternoon": (14, 0),
    "evening": (19, 0), "night": (21, 0),
}


def _extract_time(text: str):
    """Find a clock time in the text. Returns (hour, minute, leftover_text)."""
    # 7:30pm / 7 pm / 7pm
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?", text)
    if m:
        hour = int(m.group(1)) % 12 + (12 if m.group(3) == "p" else 0)
        return hour, int(m.group(2) or 0), text[:m.start()] + " " + text[m.end():]
    # 19:00 / 9:30  (colon time, no am/pm) -> assume PM for 1..11 (dinner context)
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        hour = int(m.group(1))
        hour += 12 if 1 <= hour <= 11 else 0
        return hour, int(m.group(2)), text[:m.start()] + " " + text[m.end():]
    # bare "at 8" / "by 8" -> restaurant context, assume evening for 1..11
    m = re.search(r"\b(?:at|by|around)\s+(\d{1,2})\b", text)
    if m:
        hour = int(m.group(1))
        hour += 12 if 1 <= hour <= 11 else 0
        return hour, 0, text[:m.start()] + " " + text[m.end():]
    # a part-of-day word like "evening"
    for word, (h, mnt) in _TOD_DEFAULT.items():
        if word in text:
            return h, mnt, text.replace(word, " ")
    return None, None, text


_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}


def _resolve_date(text: str):
    """Resolve a day phrase to a real date. Handles today/tonight/tomorrow and
    weekday names directly (dateparser is unreliable on those), and falls back to
    dateparser for explicit dates like '25 June' or '2026-06-25'."""
    t = text.strip()
    today = datetime.now().date()
    if not t or "today" in t or "tonight" in t:
        return today
    if "day after tomorrow" in t:
        return today + timedelta(days=2)
    if "tomorrow" in t:
        return today + timedelta(days=1)
    for name, idx in _WEEKDAYS.items():
        if name in t:
            return today + timedelta(days=(idx - today.weekday()) % 7)
    dt = dateparser.parse(
        t, settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": datetime.now()}
    )
    return dt.date() if dt else None


def parse_when(when: str):
    """Turn a spoken day+time like 'tomorrow at 4 PM', 'next Saturday 7:30pm', or
    'friday evening at 8' into (date, time). We pull out the time ourselves and
    resolve the day relative to today — so the small LLM never does date maths."""
    text = when.strip().lower()
    hour, minute, date_text = _extract_time(text)
    if hour is None:
        raise ValueError(f"no time found in {when!r}")

    # strip filler / part-of-day words so only the day phrase remains
    date_text = re.sub(
        r"\b(at|on|by|around|for|this|the|morning|noon|afternoon|evening|night)\b",
        " ", date_text,
    ).strip()

    d = _resolve_date(date_text)
    if d is None:
        raise ValueError(f"could not understand the day in {when!r}")

    return d, datetime.min.time().replace(hour=hour, minute=minute)


def _find_available_table(cur, party_size: int, d, t):
    """Smallest available table that seats the party and isn't already booked
    at that date+time. Returns a row dict or None."""
    cur.execute(
        """SELECT id, table_number, capacity
           FROM restaurant_tables tbl
           WHERE tbl.status = 'available'
             AND tbl.capacity >= %s
             AND NOT EXISTS (
                 SELECT 1 FROM bookings b
                 WHERE b.table_id = tbl.id
                   AND b.booking_date = %s
                   AND b.booking_time = %s
                   AND b.status = 'confirmed'
             )
           ORDER BY tbl.capacity ASC
           LIMIT 1""",
        (party_size, d, t),
    )
    return cur.fetchone()


def prewarm(proc: agents.JobProcess):
    # Explicit VAD tuning (Q4): a higher activation_threshold + longer min_speech_duration
    # make the agent ignore background noise / faint sounds and trigger only on clear speech.
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.10,     # ignore blips shorter than 100ms (stray noise)
        min_silence_duration=0.55,    # wait 0.55s of silence before deciding the turn ended
        activation_threshold=0.6,     # need 60% speech-confidence to start (default 0.5)
    )


class RestaurantHost(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)

    @function_tool()
    async def check_date(self, context: RunContext) -> str:
        """Tell the caller today's date and the current time. Use this ONLY if the
        caller explicitly asks what today's date or day is. You do NOT need this
        for bookings — the booking tools already understand words like 'tomorrow'."""
        now = datetime.now()
        return now.strftime("Today is %A, %d %B %Y, and the time is now %I:%M %p.")

    @function_tool()
    async def get_menu(self, context: RunContext, category: str = "") -> str:
        """List the dishes that are CURRENTLY AVAILABLE. Use this whenever the
        caller asks about the menu, a dish, or what food you serve. Only mention
        items this returns — never invent dishes or prices.

        Args:
            category: One of 'Starters', 'Mains', 'Breads', 'Desserts', 'Drinks'.
                Leave empty (or 'all') to list the entire available menu.
        """
        log = getattr(self, "_call_log", None)
        if log and log.outcome == "unknown":
            log.outcome = "menu_only"
        known = {"starters", "mains", "breads", "desserts", "drinks"}
        cat = category.strip().lower()
        with get_conn() as conn, conn.cursor() as cur:
            if cat in known:
                cur.execute(
                    "SELECT name, category, price FROM menu_items "
                    "WHERE is_available = TRUE AND lower(category) = %s "
                    "ORDER BY category, name",
                    (cat,),
                )
            else:
                cur.execute(
                    "SELECT name, category, price FROM menu_items "
                    "WHERE is_available = TRUE ORDER BY category, name"
                )
            rows = cur.fetchall()

        if not rows:
            return "Nothing is available in that category right now."
        items = [f"{r['name']} ({r['category']}, rupees {int(r['price'])})" for r in rows]
        return "Currently available: " + "; ".join(items)

    @function_tool()
    async def check_availability(self, context: RunContext,
                                 party_size: int, when: str) -> str:
        """Check whether a table is free. Call this once you know how many people
        and roughly when they want to come.

        Args:
            party_size: Number of people.
            when: The day and time in plain words, exactly as the caller said it,
                e.g. 'tomorrow at 4 PM' or 'Saturday evening at 7:30'.
        """
        try:
            d, t = parse_when(when)
        except ValueError:
            return "I didn't quite catch the day and time, could you say that again?"

        with get_conn() as conn, conn.cursor() as cur:
            table = _find_available_table(cur, party_size, d, t)

        when_str = f"{d:%A %d %B} at {t:%I:%M %p}"
        if table:
            return f"Yes, a table for {party_size} is free on {when_str}."
        return f"No table for {party_size} is free on {when_str}. Offer another time."

    @function_tool()
    async def create_booking(self, context: RunContext,
                             customer_name: str, party_size: int, when: str,
                             special_requests: str = "") -> str:
        """Create a CONFIRMED reservation. Only call this AFTER check_availability
        said yes AND the caller confirmed the details back to you.

        Args:
            customer_name: Name to put the reservation under.
            party_size: Number of people.
            when: The day and time in plain words, e.g. 'tomorrow at 4 PM'.
            special_requests: Optional extras like 'high chair' or 'window seat'.
        """
        if not customer_name.strip():
            return "I don't have the caller's name yet — ask for their name before booking."
        try:
            d, t = parse_when(when)
        except ValueError:
            return "I didn't catch the day and time, could you say that again?"

        with get_conn() as conn, conn.cursor() as cur:
            table = _find_available_table(cur, party_size, d, t)
            if table is None:
                return (f"That slot isn't available for {party_size}. "
                        f"Offer the caller another time.")
            cur.execute(
                """INSERT INTO bookings
                   (customer_name, party_size, booking_date, booking_time,
                    table_id, special_requests, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 'confirmed')
                   RETURNING id""",
                (customer_name, party_size, d, t, table["id"],
                 special_requests or None),
            )
            booking_id = cur.fetchone()["id"]
            conn.commit()

        when_str = f"{d:%A %d %B} at {t:%I:%M %p}"
        log = getattr(self, "_call_log", None)
        if log:
            log.outcome = "booked"
            log.booking_summary = {
                "Name": customer_name,
                "Party size": party_size,
                "When": when_str,
                "Table": table["table_number"],
                "Confirmation #": booking_id,
                "Special requests": special_requests or "-",
            }
        await send_whatsapp(
            "Spice Garden - booking confirmed!\n"
            f"Name: {customer_name}\n"
            f"Party: {party_size}\n"
            f"When: {when_str}\n"
            f"Table: {table['table_number']}\n"
            f"Confirmation #: {booking_id}",
            to_number=getattr(self, "_caller_phone", None),
        )
        return (f"Booking confirmed for {customer_name}, {party_size} people, "
                f"on {when_str}, table {table['table_number']}. "
                f"Confirmation number {booking_id}.")


async def entrypoint(ctx: agents.JobContext):
    await ctx.connect()

    vad = ctx.proc.userdata["vad"]

    session = AgentSession(
        vad=vad,
        turn_detection="vad",
        stt=StreamAdapter(
            stt=openai.STT(
                base_url=STT_BASE_URL,
                api_key="not-needed",
                model=STT_MODEL,
                # B1: omit `language` (STT_LANGUAGE="") so Whisper auto-detects the language.
                **({"language": STT_LANGUAGE} if STT_LANGUAGE else {}),
            ),
            vad=vad,
        ),
        llm=openai.LLM.with_ollama(
            model=LLM_MODEL,
            base_url=LLM_BASE_URL,
        ),
        tts=openai.TTS(
            model="tts-1",
            voice=TTS_VOICE,
            api_key="not-needed",
            base_url=TTS_BASE_URL,
            response_format="wav",
        ),
    )

    # --- Q6: call logging + turn-by-turn transcript ---
    raw_caller = None
    try:
        for p in ctx.room.remote_participants.values():
            if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
                raw_caller = p.attributes.get("sip.phoneNumber")
                break
    except Exception:
        pass

    call_log = CallLogger(anonymize(raw_caller))
    agent = RestaurantHost()
    agent._call_log = call_log
    agent._caller_phone = raw_caller   # WhatsApp: deliver the confirmation to the caller

    @session.on("conversation_item_added")
    def _on_item(ev):
        try:
            item = ev.item
            role = getattr(item, "role", None)
            text = getattr(item, "text_content", None)
            if role in ("user", "assistant") and text:
                speaker = "caller" if role == "user" else "agent"
                lang = call_log.last_user_language if speaker == "caller" else None
                call_log.add_turn(speaker, text, language=lang)
                logger.info(f"turn_end [{speaker}] ({lang or 'en'}): {text[:80]}")
        except Exception as exc:
            logger.warning(f"transcript log error: {exc}")

    @session.on("user_input_transcribed")
    def _on_user_tx(ev):
        if getattr(ev, "is_final", False):
            call_log.last_user_language = getattr(ev, "language", None)
            logger.info(f"turn_start [caller] lang={call_log.last_user_language}")

    @session.on("metrics_collected")
    def _on_metrics(ev):
        try:
            m = ev.metrics
            name = type(m).__name__
            if name == "LLMMetrics":
                call_log.add_metric("llm.ttft", m.ttft)
            elif name == "TTSMetrics":
                call_log.add_metric("tts.ttfb", m.ttfb)
            elif name == "STTMetrics":
                call_log.add_metric("stt.duration", m.duration)
        except Exception as exc:
            logger.warning(f"metrics log error: {exc}")

    async def _save_call_log():
        try:
            cid, n = call_log.save()
            logger.info(f"saved call_log {cid} outcome={call_log.outcome} turns={n}")
            if call_log.outcome == "booked":
                await asyncio.to_thread(send_manager_email, call_log)
        except Exception as exc:
            logger.warning(f"failed to save call log: {exc}")

    ctx.add_shutdown_callback(_save_call_log)

    await session.start(room=ctx.room, agent=agent)

    # Subtle restaurant ambience (real call only; no-op in console). OFF by default:
    # it adds a SECOND always-on audio track to mix + encode, which can cause jitter on
    # a busy machine. Turn on with BACKGROUND_AUDIO=1 in .env once the CPU has headroom.
    if os.getenv("BACKGROUND_AUDIO", "").lower() in ("1", "true", "on", "yes"):
        background = BackgroundAudioPlayer(
            ambient_sound=AudioConfig(BuiltinAudioClip.CROWDED_ROOM, volume=0.2),
        )
        try:
            await background.start(room=ctx.room, agent_session=session)
        except Exception as exc:
            logger.warning(f"background audio not started: {exc}")

    await session.generate_reply(
        instructions="Warmly greet the caller, say you're the host at Spice Garden, and ask how you can help"
    )


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=os.getenv("AGENT_NAME", "natural-icecream"),
        )
    )
