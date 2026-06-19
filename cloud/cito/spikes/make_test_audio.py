"""Generate the spoken test audio for the RTP spike.

Produces test.wav (double-click to verify quality) and test.ulaw (raw headerless
G.711 µ-law, 8 kHz mono) — the artifact rtp_send.py streams.

Usage:  uv run python -m cito.spikes.make_test_audio
"""

import subprocess
from pathlib import Path

from gtts import gTTS

TEST_SENTENCE = "This is a test of the Cito paging system."


def main() -> None:
    mp3 = Path("test.mp3")
    wav = Path("test.wav")
    ulaw = Path("test.ulaw")

    gTTS(TEST_SENTENCE).save(str(mp3))

    # Normal WAV for double-click listening.
    subprocess.run(["ffmpeg", "-y", "-i", str(mp3), str(wav)], check=True)

    # Raw headerless G.711 µ-law, 8 kHz mono — what a phone expects.
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3),
         "-ar", "8000", "-ac", "1", "-f", "mulaw", str(ulaw)],
        check=True,
    )

    size = ulaw.stat().st_size
    print(f"Wrote {wav} and {ulaw} ({size} bytes ~= {size / 8000:.1f}s of audio)")


if __name__ == "__main__":
    main()
