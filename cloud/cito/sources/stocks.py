"""Stock source — yfinance (prototype). Announce the change, not the absolute price.

End-of-day summary framing; isolated behind the fetcher interface so a licensed
provider can replace yfinance later with no downstream change.
"""

import yfinance as yf

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL"]


class StockSource:
    name = "stocks"

    def __init__(self, tickers: list[str] | None = None):
        # Cap the watchlist — listeners tune out past ~5-6 names.
        self.tickers = (tickers or DEFAULT_TICKERS)[:6]

    def fetch(self) -> dict:
        quotes = []
        for symbol in self.tickers:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            last = float(info["last_price"])
            prev = float(info["previous_close"])
            change_pct = round((last - prev) / prev * 100, 1) if prev else 0.0
            quotes.append({
                "name": ticker.info.get("shortName", symbol),
                "previous_close": prev,
                "change_pct": abs(change_pct),
                "direction": "up" if change_pct >= 0 else "down",
            })
        return {"quotes": quotes}

    def prompt_fragment(self, data: dict) -> str:
        # Speech-ready data: company names (not tickers) + day change, already rounded.
        # No LLM instructions here — the engine's envelope owns the "how"; this also
        # doubles as clean text for the template fallback.
        lines = [
            f"{q['name']} {q['direction']} about {q['change_pct']} percent"
            for q in data["quotes"]
        ]
        return "At today's market close: " + "; ".join(lines) + "."
