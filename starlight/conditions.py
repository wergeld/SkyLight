from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import ephem
import requests

from . import config

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "cloud_cover",
    "wind_speed_10m",
)
REQUEST_TIMEOUT_SECONDS = 20


class ConditionsError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeatherData:
    source: str
    timezone: str
    utc_offset_seconds: int
    local_time: datetime
    cloud_cover: float | None
    temperature_c: float | None
    humidity: float | None
    wind_kmh: float | None
    precipitation_mm: float | None


@dataclass(frozen=True)
class ConditionsLookup:
    moon_text: str
    weather_text: str
    local_time: datetime
    timezone: str
    source: str


def _parse_date(value: str) -> date:
    cleaned = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ConditionsError("Enter a date like 2026-10-22.")


def _parse_time(value: str, label: str) -> time:
    cleaned = str(value or "").strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%H"):
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            continue
    raise ConditionsError(f"Enter a {label} like 21:30:00.")


def observation_midpoint(
    date_local: str, start_local: str, end_local: str
) -> datetime:
    target_date = _parse_date(date_local)
    start = datetime.combine(target_date, _parse_time(start_local, "start time"))
    if not str(end_local or "").strip():
        return start
    end = datetime.combine(target_date, _parse_time(end_local, "end time"))
    if end < start:
        end += timedelta(days=1)
    if end - start > timedelta(hours=24):
        return start
    return start + (end - start) / 2


def _candidate_sources(target_date: date) -> list[tuple[str, str]]:
    today = datetime.now().date()
    if target_date > today:
        return [(FORECAST_URL, "forecast")]
    sources = [(ARCHIVE_URL, "historical reanalysis")]
    if target_date >= date(2022, 1, 1):
        sources.append((HISTORICAL_FORECAST_URL, "historical forecast"))
    sources.append((FORECAST_URL, "forecast"))
    return sources


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nearest_hour_index(times: list[str], local_time: datetime) -> int | None:
    parsed: list[tuple[int, datetime]] = []
    for index, value in enumerate(times):
        try:
            parsed.append((index, datetime.fromisoformat(str(value))))
        except ValueError:
            continue
    if not parsed:
        return None
    return min(
        parsed,
        key=lambda item: abs((item[1] - local_time).total_seconds()),
    )[0]


def _request_source(
    url: str,
    source: str,
    latitude: float,
    longitude: float,
    target_date: date,
    local_time: datetime,
) -> tuple[WeatherData | None, str | None]:
    end_date = max(target_date, local_time.date())
    params = {
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "start_date": target_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ",".join(HOURLY_FIELDS),
        "timezone": "auto",
        "wind_speed_unit": "kmh",
    }
    headers = {"User-Agent": f"StarLight/{config.APP_VERSION}"}
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return None, f"{source}: {exc}"
    try:
        payload = response.json()
    except ValueError:
        return None, f"{source}: invalid response"
    if response.status_code != 200:
        reason = str(payload.get("reason") or f"HTTP {response.status_code}")
        return None, f"{source}: {reason}"
    hourly = payload.get("hourly") or {}
    times = [str(value) for value in hourly.get("time") or []]
    index = _nearest_hour_index(times, local_time)
    if index is None:
        return None, f"{source}: no hourly data"
    values = {
        field: _number((hourly.get(field) or [None] * len(times))[index])
        for field in HOURLY_FIELDS
    }
    if all(value is None for value in values.values()):
        return None, f"{source}: no values for the selected hour"
    try:
        offset = int(payload.get("utc_offset_seconds") or 0)
    except (TypeError, ValueError):
        offset = 0
    return (
        WeatherData(
            source=source,
            timezone=str(payload.get("timezone") or "unknown"),
            utc_offset_seconds=offset,
            local_time=datetime.fromisoformat(times[index]),
            cloud_cover=values["cloud_cover"],
            temperature_c=values["temperature_2m"],
            humidity=values["relative_humidity_2m"],
            wind_kmh=values["wind_speed_10m"],
            precipitation_mm=values["precipitation"],
        ),
        None,
    )


def fetch_weather(
    latitude: float,
    longitude: float,
    target_date: date,
    local_time: datetime,
) -> WeatherData:
    errors: list[str] = []
    for url, source in _candidate_sources(target_date):
        weather, error = _request_source(
            url, source, latitude, longitude, target_date, local_time
        )
        if weather is not None:
            return weather
        if error:
            errors.append(error)
    detail = errors[-1] if errors else "no weather source responded"
    raise ConditionsError(f"Weather lookup failed: {detail}")


def _phase_name(illumination_percent: float, waxing: bool) -> str:
    fraction = illumination_percent / 100
    if fraction < 0.02:
        return "New Moon"
    if fraction > 0.98:
        return "Full Moon"
    if 0.45 <= fraction <= 0.55:
        return "First quarter" if waxing else "Last quarter"
    if fraction < 0.45:
        return "Waxing crescent" if waxing else "Waning crescent"
    return "Waxing gibbous" if waxing else "Waning gibbous"


def moon_context(
    latitude: float,
    longitude: float,
    local_time: datetime,
    utc_offset_seconds: int,
) -> str:
    utc_time = local_time - timedelta(seconds=utc_offset_seconds)
    observer = ephem.Observer()
    observer.lat = f"{latitude:.6f}"
    observer.lon = f"{longitude:.6f}"
    observer.elevation = 0
    observer.pressure = 0
    observer.date = ephem.Date(utc_time.replace(tzinfo=None))
    moon = ephem.Moon(observer)
    waxing = ephem.next_full_moon(observer.date) < ephem.next_new_moon(observer.date)
    altitude = math.degrees(moon.alt)
    altitude_text = (
        f"{altitude:.0f}° above horizon"
        if altitude >= 0
        else f"{abs(altitude):.0f}° below horizon"
    )
    return (
        f"{_phase_name(float(moon.phase), waxing)}, {float(moon.phase):.0f}% "
        f"illuminated, {altitude_text}"
    )


def format_weather(weather: WeatherData) -> str:
    parts: list[str] = []
    if weather.cloud_cover is not None:
        parts.append(f"cloud {weather.cloud_cover:.0f}%")
    if weather.temperature_c is not None:
        parts.append(f"{weather.temperature_c:.1f}°C")
    if weather.humidity is not None:
        parts.append(f"RH {weather.humidity:.0f}%")
    if weather.wind_kmh is not None:
        parts.append(f"wind {weather.wind_kmh:.0f} km/h")
    if weather.precipitation_mm is not None:
        parts.append(f"precip {weather.precipitation_mm:.1f} mm")
    if not parts:
        parts.append("no hourly values returned")
    return f"{' · '.join(parts)} ({weather.source}; Open-Meteo)"


def lookup_conditions(
    latitude: float,
    longitude: float,
    date_local: str,
    start_local: str,
    end_local: str,
) -> ConditionsLookup:
    if not -90 <= latitude <= 90:
        raise ConditionsError("Latitude must be between -90 and 90.")
    if not -180 <= longitude <= 180:
        raise ConditionsError("Longitude must be between -180 and 180.")
    target_date = _parse_date(date_local)
    local_time = observation_midpoint(date_local, start_local, end_local)
    weather = fetch_weather(latitude, longitude, target_date, local_time)
    return ConditionsLookup(
        moon_text=moon_context(
            latitude,
            longitude,
            local_time,
            weather.utc_offset_seconds,
        ),
        weather_text=format_weather(weather),
        local_time=weather.local_time,
        timezone=weather.timezone,
        source=weather.source,
    )


def conditions_text(result: ConditionsLookup) -> str:
    return f"Moon: {result.moon_text}\nWeather: {result.weather_text}"
