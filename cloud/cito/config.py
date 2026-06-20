"""Persisted app config (voice/personality), stored in a gitignored JSON file."""

import json
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "cito_config.json"  # cloud/cito_config.json
MAX_VOICE_CHARS = 500
DEFAULT_PRESET = "Friendly"

PRESETS = {
    "Professional": "Use a polished, professional tone. Be clear, calm, and concise.",
    "Friendly": "Keep it upbeat, warm, and friendly. A little light humor is welcome.",
    "Concise": "Be brief and to the point — one short sentence per topic, no filler.",
}

_INJECTION_RE = re.compile(
    r"(ignore (all )?previous instructions|disregard the above|"
    r"return only|system prompt|</?say>)",
    re.IGNORECASE,
)


def validate_voice(text: str) -> str:
    """Strip injection attempts and clip to the length cap. Guidance, not a peer."""
    cleaned = _INJECTION_RE.sub("", text or "").strip()
    return cleaned[:MAX_VOICE_CHARS]


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not Path(path).exists():
        return {"voice": "", "preset": DEFAULT_PRESET}
    return json.loads(Path(path).read_text())


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> dict:
    clean_cfg = {
        "voice": validate_voice(cfg.get("voice", "")),
        "preset": cfg.get("preset", DEFAULT_PRESET),
    }
    Path(path).write_text(json.dumps(clean_cfg, indent=2))
    return clean_cfg
