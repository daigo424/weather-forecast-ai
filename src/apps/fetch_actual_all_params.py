"""
OpenMeteo アーカイブAPIから全パラメータを取得し、以下に保存する。
  01_raw: data/01_raw/open-meteo/actual/location=<name>/year=<Y>/month=<MM>/day=<DD>/raw_actual.json

APIコールは1日単位で行い、レスポンスをそのまま 01_raw に保存する。
パラメータは ERA5 archive API で確実に取得できるものに絞っている。
公式ドキュメント: https://open-meteo.com/en/docs/historical-weather-api で要確認。
"""
from __future__ import annotations

import json
import random
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from packages.config import OPEN_METEO_API_KEY, OPEN_METEO_API_URL, RAW_DIR, LOCATIONS
from packages.logger import AppLogger

logger = AppLogger("fetch_actual")

# ERA5 archive API で確実に取得できるパラメータのみ
# 参照: https://open-meteo.com/en/docs/historical-weather-api
ALL_HOURLY_PARAMS = [
    # 気温・体感
    "temperature_2m",
    "apparent_temperature",
    # 湿度・露点
    "relative_humidity_2m",
    "dew_point_2m",
    # 降水・積雪
    "precipitation",
    "rain",
    "snowfall",
    "snow_depth",
    # 気圧・雲
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    # 風 (ERA5は10m・100mのみ)
    "wind_speed_10m",
    "wind_speed_100m",
    "wind_direction_10m",
    "wind_direction_100m",
    "wind_gusts_10m",
    # 日射
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "direct_normal_irradiance",
    "terrestrial_radiation",
    "shortwave_radiation_instant",
    "direct_radiation_instant",
    "diffuse_radiation_instant",
    "direct_normal_irradiance_instant",
    "terrestrial_radiation_instant",
    "sunshine_duration",
    # 蒸発散
    "et0_fao_evapotranspiration",
    # 土壌温度・水分
    "soil_temperature_0_to_7cm",
    "soil_temperature_7_to_28cm",
    "soil_temperature_28_to_100cm",
    "soil_temperature_100_to_255cm",
    "soil_moisture_0_to_7cm",
    "soil_moisture_7_to_28cm",
    "soil_moisture_28_to_100cm",
    "soil_moisture_100_to_255cm",
    # その他
    "weather_code",
    "is_day",
]


def _raw_day_path(location_name: str, year: int, month: int, day: int) -> Path:
    return (
        RAW_DIR / "open-meteo" / "actual"
        / f"location={location_name}"
        / f"year={year}"
        / f"month={month:02d}"
        / f"day={day:02d}"
        / "raw_actual.json"
    )


def _iter_months(start: date, end: date):
    current = date(start.year, start.month, 1)
    while current <= end:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(days=1)
        yield current.year, current.month, current, min(month_end, end)
        current = next_month


def _call_api(lat: float, lon: float, target: date, max_retries: int = 5) -> dict[str, Any]:
    params = {
        "latitude":   lat,
        "longitude":  lon,
        "start_date": target.isoformat(),
        "end_date":   target.isoformat(),
        "hourly":     ",".join(ALL_HOURLY_PARAMS),
        "timezone":   "Asia/Tokyo",
    }
    if OPEN_METEO_API_KEY:
        params["apikey"] = OPEN_METEO_API_KEY

    for attempt in range(max_retries):
        resp = requests.get(OPEN_METEO_API_URL, params=params, timeout=60)

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else min(60, 2 ** attempt) + random.uniform(0, 1)
            logger.warning("rate-limited", wait=f"{wait:.1f}s", attempt=attempt + 1)
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError(f"Open-Meteo API failed after {max_retries} retries: {target}")


def run(start: date | None = None, end: date | None = None) -> None:
    if end is None:
        end = date.today() - timedelta(days=1)
    if start is None:
        start = end - timedelta(days=365)

    logger.info("fetch started", start=str(start), end=str(end), locations=len(LOCATIONS), params=len(ALL_HOURLY_PARAMS))

    for loc in LOCATIONS:
        logger.info("fetching location", location=loc["name"])
        for year, month, m_start, m_end in _iter_months(start, end):
            logger.info("fetching month", location=loc["name"], year=year, month=f"{month:02d}")

            d = m_start
            while d <= m_end:
                raw_path = _raw_day_path(loc["name"], year, month, d.day)
                if raw_path.exists():
                    d += timedelta(days=1)
                    continue

                data = _call_api(loc["lat"], loc["lon"], d)
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                time.sleep(1)
                d += timedelta(days=1)

    logger.info("fetch done")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch all OpenMeteo actual params to data/01_raw")
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end",   type=date.fromisoformat, default=None)
    args = parser.parse_args()

    run(start=args.start, end=args.end)
