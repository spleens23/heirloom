"""Talking to Open-Meteo (free weather data, no account needed) and remembering cities.

Search:   https://geocoding-api.open-meteo.com/v1/search   (place names from GeoNames)
Forecast: https://api.open-meteo.com/v1/forecast
"""

from __future__ import annotations

import json
import locale
import os
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "heirloom-weather"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "heirloom-weather"
GEO_URL = os.environ.get("HEIRLOOM_WEATHER_GEO", "https://geocoding-api.open-meteo.com/v1/search")
FORECAST_URL = os.environ.get("HEIRLOOM_WEATHER_API", "https://api.open-meteo.com/v1/forecast")
UA = {"User-Agent": "HeirloomWeather/1.0 (+https://github.com/spleens23/heirloom)"}


def _get(url: str, params: dict, timeout=12) -> dict:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _lang() -> str:
    code = (locale.getlocale()[0] or os.environ.get("LANG") or "en").split("_")[0].split(".")[0].lower()
    return code if code.isalpha() and len(code) == 2 else "en"


def search(name: str) -> list[dict]:
    """Places matching a name ("Springfield", "Paris, Texas", a postcode)."""
    name = name.strip()
    if len(name) < 2:
        return []
    narrow = None
    if "," in name:  # "Springfield, Illinois" → search the city, then prefer that region/country
        name, narrow = [p.strip() for p in name.split(",", 1)]
    data = _get(GEO_URL, {"name": name, "count": 20, "language": _lang(), "format": "json"})
    out = []
    for r in data.get("results") or []:
        place = {
            "id": r.get("id"),
            "name": r.get("name", ""),
            "region": r.get("admin1", ""),
            "country": r.get("country", ""),
            "lat": r["latitude"], "lon": r["longitude"],
            "population": r.get("population") or 0,
        }
        out.append(place)
    if narrow:
        n = narrow.casefold()
        hits = [p for p in out if n in p["region"].casefold() or n in p["country"].casefold()]
        out = hits or out
    return out[:12]


def place_label(p: dict) -> str:
    return ", ".join(x for x in (p.get("name"), p.get("region"), p.get("country")) if x)


def forecast(place: dict, fahrenheit: bool) -> dict:
    data = _get(FORECAST_URL, {
        "latitude": place["lat"], "longitude": place["lon"], "timezone": "auto", "forecast_days": 7,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
        "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        "temperature_unit": "fahrenheit" if fahrenheit else "celsius",
        "wind_speed_unit": "mph" if fahrenheit else "kmh",
    })
    data["_fetched"] = time.time()
    data["_fahrenheit"] = fahrenheit
    _write(CACHE_DIR / f"{key(place)}.json", data)
    return data


def cached(place: dict) -> dict | None:
    try:
        return json.loads((CACHE_DIR / f"{key(place)}.json").read_text())
    except (OSError, ValueError):
        return None


def key(place: dict) -> str:
    return str(place.get("id") or f"{place['lat']:.3f},{place['lon']:.3f}")


# ---- what the weather codes mean (WMO codes, as Open-Meteo uses them) ---------------

def describe(code: int, day: bool = True) -> tuple[str, str]:
    """(words, icon name) for a weather code."""
    c = int(code or 0)
    if c == 0:
        return ("Clear" if not day else "Sunny"), ("weather-clear-symbolic" if day else "weather-clear-night-symbolic")
    if c == 1:
        return "Mostly clear", ("weather-few-clouds-symbolic" if day else "weather-few-clouds-night-symbolic")
    if c == 2:
        return "Partly cloudy", ("weather-few-clouds-symbolic" if day else "weather-few-clouds-night-symbolic")
    if c == 3:
        return "Cloudy", "weather-overcast-symbolic"
    if c in (45, 48):
        return "Fog", "weather-fog-symbolic"
    if c in (51, 53, 55):
        return "Drizzle", "weather-showers-scattered-symbolic"
    if c in (56, 57, 66, 67):
        return "Freezing rain", "weather-freezing-rain-symbolic"
    if c in (61, 63):
        return ("Light rain" if c == 61 else "Rain"), "weather-showers-symbolic"
    if c == 65:
        return "Heavy rain", "weather-showers-symbolic"
    if c in (71, 73, 75, 77):
        return ("Light snow" if c == 71 else "Heavy snow" if c == 75 else "Snow"), "weather-snow-symbolic"
    if c in (80, 81, 82):
        return ("Showers" if c < 82 else "Heavy showers"), "weather-showers-scattered-symbolic"
    if c in (85, 86):
        return "Snow showers", "weather-snow-symbolic"
    if c in (95, 96, 99):
        return ("Thunderstorms" if c == 95 else "Thunderstorms with hail"), "weather-storm-symbolic"
    return "—", "weather-severe-alert-symbolic"


def mood(code: int, day: bool) -> str:
    """Which sky to paint behind the forecast."""
    c = int(code or 0)
    if not day:
        return "night"
    if c in (0, 1):
        return "sunny"
    if c in (2, 3, 45, 48):
        return "cloudy"
    if c >= 95:
        return "storm"
    if c in (71, 73, 75, 77, 85, 86):
        return "snow"
    return "rain"


# ---- settings -------------------------------------------------------------------------

def default_fahrenheit() -> bool:
    loc = (locale.getlocale()[0] or os.environ.get("LC_MEASUREMENT") or os.environ.get("LANG") or "")
    return any(loc.startswith(p) for p in ("en_US", "es_US", "en_LR", "my_MM")) or loc in ("", "C", "C.UTF-8")


class Settings:
    def __init__(self):
        self.places: list[dict] = []
        self.current = 0
        self.fahrenheit = default_fahrenheit()
        try:
            d = json.loads((CONFIG_DIR / "settings.json").read_text())
            self.places = [p for p in d.get("places", []) if "lat" in p and "lon" in p]
            self.current = int(d.get("current", 0))
            self.fahrenheit = bool(d.get("fahrenheit", self.fahrenheit))
        except (OSError, ValueError):
            pass
        self.current = max(0, min(self.current, len(self.places) - 1))

    def save(self):
        _write(CONFIG_DIR / "settings.json",
               {"places": self.places, "current": self.current, "fahrenheit": self.fahrenheit})

    def add(self, place: dict) -> int:
        for i, p in enumerate(self.places):
            if key(p) == key(place):
                self.current = i
                break
        else:
            self.places.append(place)
            self.current = len(self.places) - 1
        self.save()
        return self.current

    def remove(self, i: int):
        if 0 <= i < len(self.places):
            self.places.pop(i)
            self.current = max(0, min(self.current, len(self.places) - 1))
            self.save()


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)
