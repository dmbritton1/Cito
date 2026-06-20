"""Encode an audio file to raw headerless G.711 µ-law (8 kHz mono) via ffmpeg."""

import subprocess
from pathlib import Path


def encode_mulaw(audio_file: Path, out: Path = Path("announcement.ulaw")) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio_file),
         "-ar", "8000", "-ac", "1", "-f", "mulaw", str(out)],
        check=True,
        capture_output=True,
    )
    return out
