"""Registry mapping a source key to its instance. Adding a source = one entry here."""

from cito.sources.calendar import CalendarSource
from cito.sources.stocks import StockSource
from cito.sources.weather import WeatherSource

SOURCES = {
    "weather": WeatherSource(),
    "stocks": StockSource(),
    "calendar": CalendarSource(),
}
