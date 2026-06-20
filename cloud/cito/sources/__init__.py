"""Registry mapping a source key to its instance. Adding a source = one entry here."""

from cito.sources.weather import WeatherSource
from cito.sources.stocks import StockSource

SOURCES = {
    "weather": WeatherSource(),
    "stocks": StockSource(),
}
