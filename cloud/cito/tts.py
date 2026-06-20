"""Text-to-speech behind a tiny interface. gTTS now; ElevenLabs/Polly later drop-ins."""

from pathlib import Path

from gtts import gTTS


def synthesize(text: str, out: Path = Path("announcement.mp3")) -> Path:
    """Render `text` to an audio file and return its path."""
    gTTS(text).save(str(out))
    return out
