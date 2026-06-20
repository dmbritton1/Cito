"""The shared spine: both the CLI and the web console call these two functions."""

from dataclasses import dataclass
from pathlib import Path

from cito import audio, tts
from cito.delivery import MulticastRTPSender
from cito.engine import generate_script
from cito.sources import SOURCES


@dataclass
class SendResult:
    packets: int


def generate_announcement(source_keys: list[str]) -> str:
    """Fetch each enabled source, combine fragments, and produce a clean script."""
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
    return generate_script(fragments)


def send_announcement(text: str) -> SendResult:
    """Speak `text` verbatim: TTS -> µ-law -> RTP multicast."""
    if not text or not text.strip():
        raise ValueError("cannot send an empty announcement")
    mp3 = tts.synthesize(text.strip())
    ulaw = audio.encode_mulaw(Path(mp3))
    packets = MulticastRTPSender().send(Path(ulaw))
    return SendResult(packets=packets)
