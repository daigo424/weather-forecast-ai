from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/app")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", f"sqlite:///{BASE_DIR / 'data' / 'mlflow.db'}")
MLFLOW_EXPERIMENT_NAME = "weather-forecast"
REG_MODEL_NAME = "weather_regression"
CLS_MODEL_NAME = "weather_classifier"

OPEN_METEO_API_URL = "https://archive-api.open-meteo.com/v1/archive"

LOCATIONS = [
    {"name": "tokyo_center", "lat": 35.6812, "lon": 139.7671},
    {"name": "tokyo_north",  "lat": 36.05,   "lon": 139.77},
    {"name": "tokyo_south",  "lat": 35.30,   "lon": 139.77},
    {"name": "tokyo_east",   "lat": 35.68,   "lon": 140.20},
    {"name": "tokyo_west",   "lat": 35.68,   "lon": 139.30},
]

HOURLY_COLUMNS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation",
    "rain",
    "weather_code",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
]

REG_FEATURES = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation",
    "rain",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
]

RAW_FEATURES = [*REG_FEATURES, "weather_code"]
CENTER_LOCATION = "tokyo_center"
