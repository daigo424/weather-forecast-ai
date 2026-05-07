from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Weather Forecast API", version="1.0.0")


class PredictRequest(BaseModel):
    hours: int = Field(default=168, ge=1, le=720, description="予測する時間数 (最大 720 = 30日)")
    location: str = Field(default="tokyo_center", description="表示する地点名")


class PredictResponse(BaseModel):
    location: str
    hours: int
    predictions: list[dict]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/forecast")
def forecast(hours: int = 168) -> dict:
    """全列の予測データを返す（フロントエンド向け）。"""
    try:
        from src.predict import predict_weekly
        df = predict_weekly(hours=hours)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    df["datetime"] = df["datetime"].astype(str)
    return {"predictions": df.to_dict(orient="records")}


@app.get("/model-info")
def model_info() -> dict:
    """現在使用中のモデルのバージョン・Run Name などを返す。"""
    try:
        from src.load_model import get_model_info
        return get_model_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/today")
def today_weather() -> dict:
    """本日の実況天気を返す（DB → forecast API フォールバック）。"""
    try:
        from src.fetch_today import get_today_weather
        result = get_today_weather()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if result is None:
        raise HTTPException(status_code=503, detail="Today's weather data not available")
    return {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in result.items() if v is not None}


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest) -> PredictResponse:
    try:
        from src.predict import predict_weekly
        df = predict_weekly(hours=request.hours)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    location = request.location
    loc_cols = [c for c in df.columns if c.endswith(f"_{location}") or c in ("datetime", "step_hour")]
    subset   = df[loc_cols].copy()

    subset.columns = [
        c.replace(f"_{location}", "") if c.endswith(f"_{location}") else c
        for c in subset.columns
    ]

    subset["datetime"] = subset["datetime"].astype(str)

    return PredictResponse(
        location=location,
        hours=request.hours,
        predictions=subset.to_dict(orient="records"),
    )
