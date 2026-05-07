from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import requests
from sqlalchemy import text

from src.config import LOCATIONS
from src.db import engine

FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"

CURRENT_PARAMS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
    "cloud_cover",
]


def fetch_current_weather(location: dict) -> dict | None:
    """Open-Meteo forecast API から現在の気象データを取得。"""
    params = {
        "latitude":  location["lat"],
        "longitude": location["lon"],
        "current":   ",".join(CURRENT_PARAMS),
        "timezone":  "Asia/Tokyo",
    }
    try:
        resp = requests.get(FORECAST_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})
        return {
            "time":                 current.get("time"),
            "temperature_2m":       current.get("temperature_2m"),
            "relative_humidity_2m": current.get("relative_humidity_2m"),
            "precipitation":        current.get("precipitation"),
            "weather_code":         current.get("weather_code"),
            "wind_speed_10m":       current.get("wind_speed_10m"),
            "cloud_cover":          current.get("cloud_cover"),
        }
    except Exception:
        return None


def get_today_weather(location_name: str = "tokyo_center") -> dict | None:
    """DBに当日データがあればそれを、なければ forecast API から取得。"""
    now = datetime.now().isoformat()
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(
                "SELECT * FROM weather_hourly"
                " WHERE location_name = :name AND datetime <= :now"
                " ORDER BY datetime DESC LIMIT 1"
            ),
            conn,
            params={"name": location_name, "now": now},
        )

    if not df.empty:
        return df.iloc[0].to_dict()

    loc = next((l for l in LOCATIONS if l["name"] == location_name), LOCATIONS[0])
    return fetch_current_weather(loc)
