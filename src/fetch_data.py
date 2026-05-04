from __future__ import annotations

import random
import time
from datetime import date, timedelta
from typing import Any

import pandas as pd
import requests

from src.config import HOURLY_COLUMNS, LOCATIONS, OPEN_METEO_API_URL
from src.db import SessionLocal


def _iter_chunks(start: date, end: date, chunk_days: int = 30):
    current = start
    while current <= end:
        yield current, min(current + timedelta(days=chunk_days - 1), end)
        current += timedelta(days=chunk_days)


def _call_api(start: date, end: date, max_retries: int = 5) -> list[dict[str, Any]]:
    params = {
        "latitude":   ",".join(str(loc["lat"]) for loc in LOCATIONS),
        "longitude":  ",".join(str(loc["lon"]) for loc in LOCATIONS),
        "start_date": start.isoformat(),
        "end_date":   end.isoformat(),
        "hourly":     ",".join(HOURLY_COLUMNS),
        "timezone":   "Asia/Tokyo",
    }

    for attempt in range(max_retries):
        resp = requests.get(OPEN_METEO_API_URL, params=params, timeout=60)

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after else min(60, 2 ** attempt) + random.uniform(0, 1)
            print(f"429 rate-limited — waiting {wait:.1f}s (attempt {attempt + 1})")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]

    raise RuntimeError(f"Open-Meteo API failed after {max_retries} retries: {start} – {end}")


def _to_dataframe(api_response: list[dict[str, Any]]) -> pd.DataFrame:
    frames = []
    for i, item in enumerate(api_response):
        loc = LOCATIONS[i]
        df = pd.DataFrame(item["hourly"])
        df["location_name"]       = loc["name"]
        df["requested_latitude"]  = loc["lat"]
        df["requested_longitude"] = loc["lon"]
        df["actual_latitude"]     = item.get("latitude")
        df["actual_longitude"]    = item.get("longitude")
        df["timezone"]            = item.get("timezone")
        frames.append(df)

    result = pd.concat(frames, ignore_index=True)
    return result.rename(columns={"time": "datetime"})


def run(start: date | None = None, end: date | None = None) -> None:
    """Airflow から呼ぶエントリーポイント。取得→DB保存をチャンク単位で行う。"""
    from src.save_to_db import is_date_range_imported, save_import_log, save_raw_weather

    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=365)

    with SessionLocal() as session:
        for chunk_start, chunk_end in _iter_chunks(start, end):
            if is_date_range_imported(session, chunk_start, chunk_end):
                print(f"[fetch_data] skip (already imported): {chunk_start} – {chunk_end}")
                continue

            print(f"[fetch_data] fetching {chunk_start} – {chunk_end}")
            data = _call_api(chunk_start, chunk_end)
            df   = _to_dataframe(data)

            save_raw_weather(session, df)
            save_import_log(session, chunk_start, chunk_end)
            session.commit()

            time.sleep(3)

    print("[fetch_data] done")


if __name__ == "__main__":
    run()
