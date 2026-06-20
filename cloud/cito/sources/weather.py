"""Weather source — wttr.in (keyless). Dict is shaped around meaning, not wttr.in."""

import httpx

WTTR_URL = "https://wttr.in/?format=j1"


class WeatherSource:
    name = "weather"

    def fetch(self) -> dict:
        resp = httpx.get(WTTR_URL, timeout=15.0, headers={"User-Agent": "curl"})
        resp.raise_for_status()
        raw = resp.json()
        current = raw["current_condition"][0]
        today = raw["weather"][0]
        area = raw["nearest_area"][0]["areaName"][0]["value"]
        return {
            "location": area,
            "condition": current["weatherDesc"][0]["value"],
            "high_f": int(today["maxtempF"]),
            "low_f": int(today["mintempF"]),
        }

    def prompt_fragment(self, data: dict) -> str:
        # A speech-ready data statement (no LLM instructions here — the engine's
        # envelope owns the "how"). This doubles as clean text for the template fallback.
        return (
            f"In {data['location']}, it's {data['condition']} "
            f"with a high of {data['high_f']} degrees and a low of {data['low_f']} degrees."
        )
