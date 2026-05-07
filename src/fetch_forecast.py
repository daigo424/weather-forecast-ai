from __future__ import annotations

import random
import time
from datetime import date, timedelta
from typing import Any

import pandas as pd
import requests

from src.config import HOURLY_COLUMNS, LOCATIONS, NWP_FORECAST_API_URL, NWP_HISTORICAL_API_URL
from src.db import SessionLocal


def _iter_chunks(start: date, end: date, chunk_days: int = 30):
    current = start
    while current <= end:
        yield current, min(current + timedelta(days=chunk_days - 1), end)
        current += timedelta(days=chunk_days)


def _call_api(
    start: date,
    end: date,
    api_url: str,
    max_retries: int = 5,
) -> list[dict[str, Any]]:
    params = {
        "latitude":   ",".join(str(loc["lat"]) for loc in LOCATIONS),
        "longitude":  ",".join(str(loc["lon"]) for loc in LOCATIONS),
        "start_date": start.isoformat(),
        "end_date":   end.isoformat(),
        "hourly":     ",".join(HOURLY_COLUMNS),
        "timezone":   "Asia/Tokyo",
    }
    for attempt in range(max_retries):
        resp = requests.get(api_url, params=params, timeout=60)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", min(60, 2 ** attempt))) + random.uniform(0, 1)
            print(f"429 rate-limited — waiting {wait:.1f}s (attempt {attempt + 1})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]
    raise RuntimeError(f"NWP API failed after {max_retries} retries: {start} – {end}")


def _call_forecast_api(hours: int, max_retries: int = 5) -> list[dict[str, Any]]:
    forecast_days = min((hours // 24) + 2, 16)
    params = {
        "latitude":      ",".join(str(loc["lat"]) for loc in LOCATIONS),
        "longitude":     ",".join(str(loc["lon"]) for loc in LOCATIONS),
        "forecast_days": forecast_days,
        "hourly":        ",".join(HOURLY_COLUMNS),
        "timezone":      "Asia/Tokyo",
    }
    for attempt in range(max_retries):
        resp = requests.get(NWP_FORECAST_API_URL, params=params, timeout=60)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", min(60, 2 ** attempt))) + random.uniform(0, 1)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]
    raise RuntimeError(f"NWP forecast API failed after {max_retries} retries")


def _to_dataframe(api_response: list[dict[str, Any]]) -> pd.DataFrame:
    frames = []
    for i, item in enumerate(api_response):
        loc = LOCATIONS[i]
        df = pd.DataFrame(item["hourly"])
        df["location_name"] = loc["name"]
        frames.append(df)
    result = pd.concat(frames, ignore_index=True)
    return result.rename(columns={"time": "datetime"})


def run_historical(start: date | None = None, end: date | None = None) -> None:
    """過去NWP予報を historical-forecast-api から取得してDBに保存。"""
    from src.save_to_db import save_nwp_forecast

    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=365)

    with SessionLocal() as session:
        for chunk_start, chunk_end in _iter_chunks(start, end):
            print(f"[fetch_forecast] fetching NWP {chunk_start} – {chunk_end}")
            try:
                data = _call_api(chunk_start, chunk_end, NWP_HISTORICAL_API_URL)
                df   = _to_dataframe(data)
                save_nwp_forecast(session, df)
                session.commit()
            except Exception as e:
                print(f"[fetch_forecast] error: {e}")
                session.rollback()
            time.sleep(2)

    print("[fetch_forecast] historical NWP done")


def fetch_for_inference(hours: int = 168) -> pd.DataFrame:
    """現在のNWP予報を取得して long format DataFrame で返す（DB保存なし）。"""
    data = _call_forecast_api(hours)
    df = _to_dataframe(data)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


if __name__ == "__main__":
    run_historical()
