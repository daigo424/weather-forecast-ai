"""
data/01_raw の forecast JSON を読み込み、data/02_processed に月単位 Parquet として保存する。
  input:  data/01_raw/open-meteo/forecast/location=<name>/year=<Y>/month=<MM>/day=<DD>/raw_forecast.json
  output: data/02_processed/open-meteo/forecast/location=<name>/year=<Y>/month=<MM>/data_forecast.parquet
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from packages.config import LOCATIONS, PROCESSED_DIR, RAW_DIR
from packages.logger import AppLogger

logger = AppLogger("process_forecast")


def _raw_day_path(location_name: str, year: int, month: int, day: int) -> Path:
    return (
        RAW_DIR / "open-meteo" / "forecast"
        / f"location={location_name}"
        / f"year={year}"
        / f"month={month:02d}"
        / f"day={day:02d}"
        / "raw_forecast.json"
    )


def _processed_month_path(location_name: str, year: int, month: int) -> Path:
    return (
        PROCESSED_DIR / "open-meteo" / "forecast"
        / f"location={location_name}"
        / f"year={year}"
        / f"month={month:02d}"
        / "data_forecast.parquet"
    )


def _iter_months(start: date, end: date):
    current = date(start.year, start.month, 1)
    while current <= end:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(days=1)
        yield current.year, current.month, current, min(month_end, end)
        current = next_month


def _process_month(
    path: Path, location_name: str, year: int, month: int, m_start: date, m_end: date, loc: dict
) -> bool:
    frames = []
    d = m_start
    while d <= m_end:
        day_path = _raw_day_path(location_name, year, month, d.day)
        if day_path.exists():
            raw: dict[str, Any] = json.loads(day_path.read_text(encoding="utf-8"))
            df = pd.DataFrame(raw["hourly"]).rename(columns={"time": "datetime"})
            df["actual_latitude"]  = raw.get("latitude")
            df["actual_longitude"] = raw.get("longitude")
            df["timezone"]         = raw.get("timezone")
            frames.append(df)
        d += timedelta(days=1)

    if not frames:
        return False

    combined = pd.concat(frames, ignore_index=True)
    combined["datetime"]            = pd.to_datetime(combined["datetime"])
    combined["location_name"]       = loc["name"]
    combined["requested_latitude"]  = loc["lat"]
    combined["requested_longitude"] = loc["lon"]
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(str(path), index=False)
    return True


def run(start: date | None = None, end: date | None = None) -> None:
    if end is None:
        end = date.today() - timedelta(days=1)
    if start is None:
        start = end - timedelta(days=365)

    logger.info("process started", start=str(start), end=str(end), locations=len(LOCATIONS))

    for loc in LOCATIONS:
        logger.info("processing location", location=loc["name"])
        for year, month, m_start, m_end in _iter_months(start, end):
            logger.info("processing month", location=loc["name"], year=year, month=f"{month:02d}")
            path = _processed_month_path(loc["name"], year, month)
            saved = _process_month(path, loc["name"], year, month, m_start, m_end, loc)
            if not saved:
                logger.warning("no raw data found, skipping", location=loc["name"], year=year, month=f"{month:02d}")

    logger.info("process done")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Process forecast raw JSON to Parquet in data/02_processed")
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end",   type=date.fromisoformat, default=None)
    args = parser.parse_args()

    run(start=args.start, end=args.end)
