from unittest.mock import MagicMock, patch

from cito.sources.stocks import StockSource
from cito.sources.weather import WeatherSource


WTTR_SAMPLE = {
    "current_condition": [
        {"temp_F": "72", "temp_C": "22", "weatherDesc": [{"value": "Sunny"}]}
    ],
    "weather": [
        {"maxtempF": "80", "mintempF": "60", "maxtempC": "27", "mintempC": "16"}
    ],
    "nearest_area": [{"areaName": [{"value": "Austin"}]}],
}


def test_weather_fetch_shape():
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return WTTR_SAMPLE

    with patch("cito.sources.weather.httpx.get", return_value=FakeResp()):
        data = WeatherSource().fetch()

    assert data["location"] == "Austin"
    assert data["condition"] == "Sunny"
    assert data["high_f"] == 80
    assert data["low_f"] == 60


def test_weather_prompt_fragment_mentions_condition_and_location():
    data = {"location": "Austin", "condition": "Sunny", "high_f": 80, "low_f": 60}
    frag = WeatherSource().prompt_fragment(data)
    assert "Austin" in frag
    assert "Sunny" in frag
    assert "80" in frag


def test_stocks_fetch_emits_change_and_percent():
    fake_ticker = MagicMock()
    fake_ticker.fast_info = {"last_price": 101.0, "previous_close": 100.0}
    fake_ticker.info = {"shortName": "Apple Inc."}

    with patch("cito.sources.stocks.yf.Ticker", return_value=fake_ticker):
        data = StockSource(tickers=["AAPL"]).fetch()

    quote = data["quotes"][0]
    assert quote["name"] == "Apple Inc."
    assert quote["change_pct"] == 1.0
    assert quote["direction"] == "up"
    assert quote["previous_close"] == 100.0


def test_stocks_prompt_fragment_uses_names_not_tickers():
    data = {"quotes": [
        {"name": "Apple Inc.", "change_pct": 1.2, "direction": "up", "previous_close": 100.0}
    ]}
    frag = StockSource().prompt_fragment(data)
    assert "Apple" in frag
    assert "1.2" in frag
    assert "AAPL" not in frag
