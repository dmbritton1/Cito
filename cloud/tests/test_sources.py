from unittest.mock import patch

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
