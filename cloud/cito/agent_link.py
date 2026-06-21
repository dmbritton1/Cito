"""Track the connected on-prem agent and push finished audio to it over WSS.

`deliver` is called from sync code (scheduler thread, request handlers) but the agent
socket lives on the asyncio loop, so we bridge with run_coroutine_threadsafe.
"""

import asyncio
import base64
import logging
import threading
from pathlib import Path

logger = logging.getLogger("cito.agent_link")

_agent = None  # the connected WebSocket (single agent for now)
_loop = None   # the asyncio loop the socket lives on

ACK_TIMEOUT = 5.0
_ack = threading.Event()


def register(ws, loop) -> None:
    global _agent, _loop
    _agent, _loop = ws, loop
    logger.info("agent connected")


def unregister(ws) -> None:
    """Clear the agent if `ws` is the current one (or always, when passed None)."""
    global _agent, _loop
    if ws is None or _agent is ws:
        _agent, _loop = None, None
        logger.info("agent disconnected")


def has_agent() -> bool:
    return _agent is not None


def note_ack() -> None:
    _ack.set()


def deliver(ulaw_path, addr: str, port: int) -> bool:
    """Push finished µ-law to the agent and wait for its ack. True only if acked."""
    if _agent is None or _loop is None:
        return False
    audio_b64 = base64.b64encode(Path(ulaw_path).read_bytes()).decode("ascii")
    msg = {"type": "announce", "codec": "pcmu", "addr": addr, "port": port,
           "audio_b64": audio_b64}
    _ack.clear()
    try:
        asyncio.run_coroutine_threadsafe(_agent.send_json(msg), _loop)
    except Exception:
        logger.warning("agent send failed; will fall back")
        return False
    if _ack.wait(ACK_TIMEOUT):
        return True
    logger.warning("no ack from agent within %ss; will fall back", ACK_TIMEOUT)
    return False
