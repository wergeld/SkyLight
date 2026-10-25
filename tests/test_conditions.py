from __future__ import annotations

from datetime import date, datetime

import pytest

from starlight import conditions


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def weather_payload() -> dict:
    return {
        "timezone": "America/New_York",
        "utc_offset_seconds": -14400,
        "hourly": {
            "time": [
                "2026-10-22T21:00",
                "2026-10-22T22:00",
                "2026-10-22T23:00",
            ],
            "temperature_2m": [20.0, 21.5, 22.0],
            "relative_humidity_2m": [80, 75, 70],
            "precipitation": [0.0, 0.0, 0.2],
            "cloud_cover": [10, 12, 14],
            "wind_speed_10m": [5.0, 6.0, 7.0],
        },
    }


def test_observation_midpoint_handles_midnight_crossing():
    midpoint = conditions.observation_midpoint("2026-10-22", "23:00:00", "01:00:00")
    assert midpoint == datetime(2026, 10, 23, 0, 0)


def test_observation_midpoint_rejects_missing_start_time():
    with pytest.raises(conditions.ConditionsError, match="start time"):
        conditions.observation_midpoint("2026-10-22", "", "23:00:00")


def test_moon_context_uses_selected_location_and_time():
    text = conditions.moon_context(
        27.95,
        -82.46,
        datetime(2026, 10, 22, 22, 0),
        -14400,
    )
    assert "Waxing gibbous" in text
    assert "89% illuminated" in text
    assert "above horizon" in text


def test_moon_context_reports_waning_phase_after_full_moon():
    text = conditions.moon_context(
        27.95,
        -82.46,
        datetime(2026, 10, 28, 22, 0),
        -14400,
    )
    assert "Waning gibbous" in text


def test_fetch_weather_parses_nearest_hour(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(weather_payload())

    monkeypatch.setattr(conditions.requests, "get", fake_get)
    weather = conditions.fetch_weather(
        27.95,
        -82.46,
        date(2026, 10, 22),
        datetime(2026, 10, 22, 22, 0),
    )

    assert calls[0][0] == conditions.ARCHIVE_URL
    params = calls[0][1]["params"]
    assert params["start_date"] == "2026-10-22"
    assert params["end_date"] == "2026-10-22"
    assert params["timezone"] == "auto"
    assert weather.timezone == "America/New_York"
    assert weather.utc_offset_seconds == -14400
    assert weather.local_time == datetime(2026, 10, 22, 22, 0)
    assert weather.cloud_cover == 12
    assert weather.temperature_c == 21.5
    assert weather.humidity == 75
    assert weather.wind_kmh == 6
    assert weather.precipitation_mm == 0


def test_fetch_weather_falls_back_to_next_source(monkeypatch):
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if url == conditions.ARCHIVE_URL:
            return FakeResponse({"reason": "archive unavailable"}, status_code=400)
        return FakeResponse(weather_payload())

    monkeypatch.setattr(conditions.requests, "get", fake_get)
    weather = conditions.fetch_weather(
        27.95,
        -82.46,
        date(2026, 10, 22),
        datetime(2026, 10, 22, 22, 0),
    )

    assert calls == [conditions.ARCHIVE_URL, conditions.HISTORICAL_FORECAST_URL]
    assert weather.source == "historical forecast"


def test_lookup_conditions_combines_moon_and_weather(monkeypatch):
    weather = conditions.WeatherData(
        source="historical reanalysis",
        timezone="America/New_York",
        utc_offset_seconds=-14400,
        local_time=datetime(2026, 10, 22, 22, 0),
        cloud_cover=12,
        temperature_c=21.5,
        humidity=75,
        wind_kmh=6,
        precipitation_mm=0,
    )
    monkeypatch.setattr(conditions, "fetch_weather", lambda *args, **kwargs: weather)

    result = conditions.lookup_conditions(
        27.95,
        -82.46,
        "2026-10-22",
        "21:00:00",
        "23:00:00",
    )

    assert "Waxing gibbous" in result.moon_text
    assert "cloud 12%" in result.weather_text
    assert "21.5°C" in result.weather_text
    assert "Open-Meteo" in result.weather_text
    assert "Moon:" in conditions.conditions_text(result)
    assert "Weather:" in conditions.conditions_text(result)


def test_fetch_weather_requests_next_day_for_midnight_observation(monkeypatch):
    calls: list[dict] = []

    def fake_get(url, **kwargs):
        calls.append(kwargs["params"])
        payload = weather_payload()
        payload["hourly"]["time"] = [
            "2026-10-22T22:00",
            "2026-10-22T23:00",
            "2026-10-23T00:00",
        ]
        return FakeResponse(payload)

    monkeypatch.setattr(conditions.requests, "get", fake_get)
    weather = conditions.fetch_weather(
        27.95,
        -82.46,
        date(2026, 10, 22),
        datetime(2026, 10, 23, 0, 0),
    )

    assert calls[0]["start_date"] == "2026-10-22"
    assert calls[0]["end_date"] == "2026-10-23"
    assert weather.local_time == datetime(2026, 10, 23, 0, 0)
