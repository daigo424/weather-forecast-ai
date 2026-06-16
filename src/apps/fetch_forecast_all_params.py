"""
OpenMeteo previous-runs APIから全パラメータを取得し、以下に保存する。
  01_raw: data/01_raw/open-meteo/forecast/location=<name>/year=<Y>/month=<MM>/day=<DD>/raw_forecast.json

APIコールは1日単位で行い、レスポンスをそのまま 01_raw に保存する。
使用API: https://previous-runs-api.open-meteo.com/v1/forecast
  - ERA5 アーカイブ (actual) とは異なり NWP モデルの過去予報ランを取得する
  - 公式ドキュメント: https://open-meteo.com/en/docs/previous-runs-api で要確認
  - モデルによって取得できない変数がある点に注意
"""
from __future__ import annotations

import json
import random
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from packages.config import OPEN_METEO_API_KEY, PREVIOUS_RUNS_API_URL, RAW_DIR, LOCATIONS
from packages.logger import AppLogger

logger = AppLogger("fetch_forecast")

# forecast / previous-runs API で利用可能なパラメータ
# ERA5 archive より多い（複数高度の風・気温、CAPE、UV等が使える）
# 参照: https://open-meteo.com/en/docs/previous-runs-api
# ※ モデルによって取得できない変数がある。APIエラー時は該当変数を除外して再試行すること。
ALL_HOURLY_PARAMS = [
    # 気温・体感（複数高度）
    "temperature_2m",
    "temperature_80m",
    "temperature_120m",
    "temperature_180m",
    "apparent_temperature",
    # 湿度・露点・飽差
    "relative_humidity_2m",
    "dew_point_2m",
    "vapour_pressure_deficit",
    # 降水・積雪
    "precipitation",
    "rain",
    "showers",        # All Zero
    "snowfall",       # All Zero
    "snow_depth",     # All Zero
    "freezing_level_height",
    # 気圧・雲
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    # 視程
    "visibility",
    # 風（複数高度）
    "wind_speed_10m",
    "wind_speed_80m",
    "wind_speed_120m",
    "wind_speed_180m",
    "wind_direction_10m",
    "wind_direction_80m",
    "wind_direction_120m",
    "wind_direction_180m",
    "wind_gusts_10m",
    # 日射・紫外線
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "direct_normal_irradiance",
    "global_tilted_irradiance",
    "terrestrial_radiation",
    "shortwave_radiation_instant",
    "direct_radiation_instant",
    "diffuse_radiation_instant",
    "direct_normal_irradiance_instant",
    "global_tilted_irradiance_instant",
    "terrestrial_radiation_instant",
    "sunshine_duration",
    "uv_index",
    "uv_index_clear_sky",
    # 蒸発散
    "et0_fao_evapotranspiration",
    "evapotranspiration",
    # 土壌温度・水分（モデル依存）
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
    "cape",
    "is_day",
]


def _raw_day_path(location_name: str, year: int, month: int, day: int) -> Path:
    return (
        RAW_DIR / "open-meteo" / "forecast"
        / f"location={location_name}"
        / f"year={year}"
        / f"month={month:02d}"
        / f"day={day:02d}"
        / "raw_forecast.json"
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
        resp = requests.get(PREVIOUS_RUNS_API_URL, params=params, timeout=60)

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else min(60, 2 ** attempt) + random.uniform(0, 1)
            logger.warning("rate-limited", wait=f"{wait:.1f}s", attempt=attempt + 1)
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError(f"previous-runs API failed after {max_retries} retries: {target}")


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

    parser = argparse.ArgumentParser(description="Fetch all previous-runs forecast params to data/01_raw")
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end",   type=date.fromisoformat, default=None)
    args = parser.parse_args()

    run(start=args.start, end=args.end)
