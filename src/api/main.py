from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from apps.predict import ModelNotReadyError
from packages.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    from apps.predict import initialize
    initialize()
    yield


app = FastAPI(title="Weather Forecast API", version="1.0.0", lifespan=lifespan)


class PredictRequest(BaseModel):
    hours: int = Field(default=168, ge=1, le=384, description="予測する時間数")
    location: str = Field(default="tokyo", description="予測する地点名")


class PredictResponse(BaseModel):
    location: str
    hours: int
    predictions: list[dict]


@app.get("/health")
def health() -> dict:
    from apps.predict import _model_errors, _loaded_models
    return {
        "status": "ok",
        "models": {
            loc: ("ready" if loc in _loaded_models else f"not_ready: {_model_errors.get(loc, 'unknown')}")
            for loc in {**_loaded_models, **_model_errors}
        },
    }


@app.get("/forecast")
def forecast(hours: int = 168, location: str = "tokyo") -> dict:
    """全列の予測データを返す（フロントエンド向け）。"""
    try:
        from apps.predict import predict_weekly
        df = predict_weekly(hours=hours, location=location)
    except ModelNotReadyError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"API /forecast failed hours={hours}, location={location}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    df["datetime"] = df["datetime"].astype(str)
    return {"predictions": df.to_dict(orient="records")}


@app.get("/model-info")
def model_info() -> dict:
    """現在使用中のモデルのバージョン・Run Name などを返す。"""
    try:
        from apps.predict import get_model_info
        return get_model_info()
    except ModelNotReadyError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"API /model-info failed : {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/today")
def today_weather(location: str = "tokyo") -> dict:
    """本日の実況天気を返す。"""
    try:
        from apps.predict import get_today_weather
        result = get_today_weather(location=location)
    except Exception as e:
        logger.error(f"API /today failed location={location}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    if result is None:
        raise HTTPException(status_code=503, detail="Today's weather data not available")
    return {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in result.items() if v is not None}


@app.get("/historical-comparison")
def historical_comparison(location: str = "tokyo", days: int = 7) -> dict:
    """過去 days 日間の NWP 生予報・補正済み予報・ERA5 実績の比較データを返す。"""
    try:
        from packages.compare import get_historical_comparison
        return get_historical_comparison(location=location, days=days)
    except Exception as e:
        logger.error(f"API /historical-comparison failed location={location}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest) -> PredictResponse:
    try:
        from apps.predict import predict_weekly
        df = predict_weekly(hours=request.hours, location=request.location)
    except ModelNotReadyError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"API /predict failed request={request}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    df["datetime"] = df["datetime"].astype(str)
    return PredictResponse(
        location=request.location,
        hours=request.hours,
        predictions=df.to_dict(orient="records"),
    )
