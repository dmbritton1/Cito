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
    r"return only [^.\n]*(json|xml|html|markdown|code)|system prompt|</?say>)",
    re.IGNORECASE,
)


def validate_voice(text: str) -> str:
    """Strip injection attempts and clip to the length cap. Guidance, not a peer."""
    cleaned = _INJECTION_RE.sub("", text or "").strip()
    return cleaned[:MAX_VOICE_CHARS]


def load_config(path: Path = CONFIG_PATH) -> dict:
    base = {"voice": "", "preset": DEFAULT_PRESET, "calendar_url": ""}
    if Path(path).exists():
        base.update(json.loads(Path(path).read_text()))
    return base


def save_config(updates: dict, path: Path = CONFIG_PATH) -> dict:
    """Merge `updates` over the existing config so settings don't clobber each other."""
    cfg = load_config(path)
    cfg.update(updates)
    cfg["voice"] = validate_voice(cfg.get("voice", ""))
    cfg["calendar_url"] = (cfg.get("calendar_url") or "").strip()
    Path(path).write_text(json.dumps(cfg, indent=2))
    return cfg
