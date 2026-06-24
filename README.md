# Weather Forecast AI — MLOps Pipeline

An end-to-end MLOps pipeline that fetches Tokyo weather data from Open-Meteo, trains LightGBM error-correction models on top of NWP (Numerical Weather Prediction) forecasts, and serves 7-day predictions through a REST API and Streamlit dashboard.

## Overview

The core idea is **NWP bias correction**: rather than predicting weather from scratch, the system learns the systematic error between NWP model output and ERA5 reanalysis actuals, then corrects the NWP forecast at inference time.

**Correction targets:**

| Target | Unit |
|---|---|
| Temperature | °C |
| Precipitation | mm |
| Total cloud cover | % |
| Low cloud cover | % |

Weather code (WMO) is re-derived from corrected values (cloud cover, precipitation, temperature) and CAPE at inference time — not taken from NWP directly. This ensures the displayed weather icon is consistent with the corrected forecast.

## Architecture

```
Open-Meteo Archive API               Open-Meteo Previous-Runs API
(ERA5 actuals)                        (past NWP forecasts)
       │                                       │
       ▼                                       ▼
  01_raw/actual/                         01_raw/forecast/
       │                                       │
       ▼                                       ▼
  02_processed/actual/                   02_processed/forecast/
                        │           │
                        └─── merge ─┘
                               │
                    error = actual − NWP
                               │
                    build_features() [lag/rolling]
                               │
                        03_features/
                               │
                    LightGBM × 4 models
                    (one per correction target)
                               │
                    WeatherForecastPyfunc
                    (bundles all 4 models)
                               │
                     MLflow Model Registry
                      ┌────────┴────────┐
                      ▼                 ▼
              Feast (Redis)          FastAPI
          [error lag features]    /forecast /today
                      │              /model-info
                      └────────┬────────┘
                               ▼
                           Streamlit
                      (7-day dashboard)
```

### Services

| Service | Port | Description |
|---|---|---|
| PostgreSQL | 5432 | MLflow backend store + Airflow metadata + Feast offline store |
| MLflow | 5000 | Experiment tracking + model registry |
| Redis | 6379 | Feast online store (error lag features) |
| Airflow | 8080 | Daily pipeline orchestration |
| FastAPI | 8000 | Prediction REST API |
| Streamlit | 8501 | 7-day forecast dashboard |
| Evidently UI | 8088 | Model evaluation reports |
| Feast UI | 8888 | Feature store browser |

## Tech Stack

| Category | Tools |
|---|---|
| Language | Python 3.13 |
| ML | LightGBM |
| MLOps | MLflow (tracking + registry), Evidently AI (evaluation) |
| Feature Store | Feast (Redis online store + PostgreSQL offline store) |
| Orchestration | Apache Airflow 3.x (daily schedule) |
| API | FastAPI + Uvicorn |
| Frontend | Streamlit + Plotly |
| Database | PostgreSQL |
| Infrastructure | Docker Compose |
| Package manager | uv |
| Data versioning | DVC + S3 (golden datasets) |

## ML Pipeline

### Training flow

```
fetch_data → train_model → evaluate_model → materialize_features
```

1. **fetch_data** — Incrementally fetches ERA5 actuals and NWP past forecasts from Open-Meteo, saves as JSON in `01_raw/`, then processes to parquet in `02_processed/`
2. **train_model** — Merges actual/forecast, computes per-target error (`actual − NWP`), builds lag/rolling features, trains 4 LightGBM regressors, bundles into `WeatherForecastPyfunc`, and registers to MLflow Model Registry with `evaluated_successful=0`
3. **evaluate_model** — Loads the registered model, evaluates MAE/RMSE/Bias per target using Evidently AI, sets `evaluated_successful=1` tag if all thresholds pass
4. **materialize_features** — Applies Feast feature definitions and pushes recent error lag features to Redis (online store) for low-latency inference

### Inference flow

1. Fetch future NWP forecast from Open-Meteo `/v1/forecast` (including CAPE)
2. Call `WeatherForecastPyfunc.predict()`:
   - Build features from NWP input
   - Fetch error lag features from Feast online store (Redis)
   - Apply each LightGBM model: `corrected = nwp_value + predicted_error`
3. Remap weather code from corrected values + CAPE
4. Return corrected forecast DataFrame

## Version Management

Two independent version axes:

| Version | Trigger | Numbering | Location |
|---|---|---|---|
| `model_interface_version` | API schema / feature structure change | Manual increment | `deployment/versions.yaml` |
| `training_version` | Each retraining run | Auto (resets when interface version changes) | MLflow model version tag |

### Active model selection

```
max(training_version) where
  name = weather_forecast_{location}
  AND model_interface_version = <value from deployment/versions.yaml>
  AND evaluated_successful = "1"
```

If no model matches, the API returns HTTP 503 (model not ready) instead of crashing — enabling Blue/Green deployment where the old pod remains active.

## Getting Started

### Prerequisites

- Docker Desktop
- `uv` (`pip install uv`)

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env as needed (defaults work for local Docker)
```

### 2. Start services

```bash
make build
make up
```

| UI | URL | Credentials |
|---|---|---|
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| Dashboard | http://localhost:8501 | — |
| Evidently | http://localhost:8088 | — |
| Feast UI | http://localhost:8888 | — |

### 3. Initial data fetch (first time only)

```bash
make fetch-all-params    # Fetch ERA5 actuals + NWP forecasts from 2023-01-01
make process-all-params  # Process raw JSON → parquet
```

This takes 30–60 minutes depending on network speed.

### 4. Train the model

```bash
make train      # Feature build + training + MLflow registration
make evaluate   # Evaluation + evaluated_successful tag
```

Or activate the `weather_forecast_pipeline` DAG in Airflow — it handles fetch, train, evaluate, and materialize automatically on a daily schedule.

### 5. View the dashboard

Open http://localhost:8501. If no model is ready yet, a banner explains how to train one.

## Make Targets

| Target | Description |
|---|---|
| `make build` | Build all Docker images |
| `make up` / `make down` | Start / stop all services |
| `make fetch-all-params` | Fetch ERA5 actuals + NWP forecasts (2023-01-01 to present) |
| `make process-all-params` | Process raw JSON → parquet (same date range) |
| `make fetch-actual-all-params` | Fetch ERA5 actuals only (incremental) |
| `make fetch-forecast-all-params` | Fetch NWP forecasts only (incremental) |
| `make train` | Run training pipeline locally |
| `make evaluate` | Run evaluation + promotion locally |
| `make materialize` | Apply Feast feature definitions + materialize to Redis |
| `make s3-upload-raw` | Upload `01_raw/` to S3 |
| `make s3-download-raw` | Download `01_raw/` from S3 |
| `make golden-dataset-push` | Push golden dataset to S3 via DVC |
| `make golden-dataset-pull` | Pull golden dataset from S3 via DVC |
| `make logs` | Tail all service logs |
| `make ps` | Show container status |
| `make db` | Open psql shell |

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `GET /health` | — | Model readiness status per location |
| `GET /forecast` | `?hours=168&location=tokyo` | Corrected hourly forecast (168 h) |
| `GET /model-info` | — | Active model version and training metadata |
| `GET /today` | `?location=tokyo` | Current observed conditions from Open-Meteo |
| `GET /historical-comparison` | `?days=7&location=tokyo` | NWP vs corrected vs ERA5 for past N days |
| `POST /predict` | `{"hours": 168, "location": "tokyo"}` | Same as GET /forecast, POST form |

All endpoints return HTTP 503 with a descriptive message when no trained model is available.

## Environment Variables

See `.env.example` for the full list with descriptions.
