"""Verify the LiveKit Cloud SIP trunk + dispatch rule binding.
Reads LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET from .env.

    python scripts/sip_check.py
"""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit import api
from livekit.protocol.sip import (
    ListSIPInboundTrunkRequest,
    ListSIPDispatchRuleRequest,
)

# Load the project's .env from the repo root (one level up from scripts/).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# The HTTP API wants https, not wss.
_url = os.environ.get("LIVEKIT_URL", "").replace("wss://", "https://").replace("ws://", "http://")


async def main():
    lkapi = api.LiveKitAPI(url=_url) if _url else api.LiveKitAPI()
    try:
        print("=========== INBOUND SIP TRUNKS ===========")
        print(await lkapi.sip.list_inbound_trunk(ListSIPInboundTrunkRequest()))
        print("=========== SIP DISPATCH RULES ===========")
        print(await lkapi.sip.list_dispatch_rule(ListSIPDispatchRuleRequest()))
    finally:
        await lkapi.aclose()


asyncio.run(main())
