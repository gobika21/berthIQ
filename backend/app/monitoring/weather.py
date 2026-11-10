"""Hourly wind-gust and visibility forecast from Open-Meteo (free, no API key)."""

import logging

import httpx

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


async def fetch_forecast(lat: float, lon: float, hours: int = 12) -> list[dict]:
    params = {
        "latitude": round(lat, 3),
        "longitude": round(lon, 3),
        "hourly": "wind_gusts_10m,visibility",
        "wind_speed_unit": "kn",
        "forecast_hours": hours,
        "timezone": "UTC",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(OPEN_METEO_URL, params=params)
            res.raise_for_status()
            hourly = res.json()["hourly"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Weather fetch failed for %.2f,%.2f: %s", lat, lon, exc)
        return []

    return [
        {"time": t, "gust_kn": g, "visibility_m": v}
        for t, g, v in zip(hourly.get("time", []), hourly.get("wind_gusts_10m", []), hourly.get("visibility", []))
    ]
