"""The shared spine: both the CLI and the web console call these two functions."""

import logging
from dataclasses import dataclass
from pathlib import Path

from cito import agent_link, audio, config, documents, tts
from cito.delivery import MulticastRTPSender
from cito.engine import generate_script
from cito.sources import SOURCES

logger = logging.getLogger("cito.pipeline")
DELIVERY_ADDR = "224.0.1.75"
DELIVERY_PORT = 10000


@dataclass
class SendResult:
    packets: int


def generate_announcement(
    source_keys: list[str], voice: str | None = None, document_text: str = ""
) -> str:
    """Combine toggled sources (and an optional document) into a clean script.

    `voice` overrides the saved personality; when None, the saved voice is loaded.
    `document_text` is already-extracted text — when present it is added as one
    more context fragment.
    """
    if voice is None:
        voice = config.load_config().get("voice", "")
    fragments = []
    for key in source_keys:
        source = SOURCES.get(key)
        if source is None:
            continue
        try:
            data = source.fetch()
            fragments.append(source.prompt_fragment(data))
        except Exception:  # a flaky source must not sink the whole announcement
            continue
    if document_text.strip():
        fragments.append(documents.document_fragment(document_text))
    return generate_script(fragments, voice=voice)


def send_announcement(text: str) -> SendResult:
    """Speak `text`: TTS -> µ-law -> deliver via the agent if connected, else locally."""
    if not text or not text.strip():
        raise ValueError("cannot send an empty announcement")
    mp3 = tts.synthesize(text.strip())
    ulaw = Path(audio.encode_mulaw(Path(mp3)))
    if agent_link.deliver(ulaw, DELIVERY_ADDR, DELIVERY_PORT):
        packets = (ulaw.stat().st_size + 159) // 160
        logger.info("delivered via agent (%d packets)", packets)
        return SendResult(packets=packets)
    logger.info("no agent — local fallback")
    packets = MulticastRTPSender(DELIVERY_ADDR, DELIVERY_PORT).send(ulaw)
    return SendResult(packets=packets)
