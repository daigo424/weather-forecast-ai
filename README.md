# Weather Forecast AI — MLOps Pipeline

An end-to-end MLOps pipeline that fetches Tokyo weather data, trains a LightGBM model with NWP bias correction, and serves 7-day predictions (precipitation probability, temperature, weather conditions) through a REST API and Streamlit dashboard.

## Overview

The system predicts hourly weather for the next 168 hours (7 days) across five Tokyo locations. A daily Airflow pipeline handles data ingestion, NWP forecast fetching, model training, evaluation, and promotion to the model registry — with no manual intervention required.

**Prediction targets (tokyo\_center):**

| Type | Targets |
|---|---|
| Regression | Temperature, humidity, dew point, pressure, cloud cover (low/mid/high/total), precipitation, rain, wind speed/direction/gusts |
| Classification | WMO weather code (5 classes: clear / cloudy / rain / snow-ice / thunderstorm), precipitation binary |

The frontend displays temperature, weather icons, and **precipitation probability (10% intervals)** derived from the binary precipitation classifier's `predict_proba`.

## Architecture

```
Open-Meteo Archive API          Open-Meteo Historical Forecast API
 (ERA5 actuals, initial only)       (past NWP forecasts, daily)
        │                                    │
        ▼                                    ▼
  weather_hourly  ◄──── forecast API ──►  weather_nwp_forecast
  (actual data)      (past_days sync)       (NWP forecast data)
        │                                    │
        └──────────────┬─────────────────────┘
                       ▼
                 train_model  (LightGBM MultiOutput + NWP bias correction)
                       │
                 MLflow Tracking
                       │
                 evaluate_model  (MAE threshold check)
                       │
                 register_model  (MLflow Model Registry)
                       │
               ┌───────┴───────┐
               ▼               ▼
            FastAPI        Streamlit
         /forecast          Dashboard
         /model-info
         /today
```

### Services

| Service | Port | Description |
|---|---|---|
| PostgreSQL | 5432 | Weather observation, NWP forecast & prediction store |
| MLflow | 5000 | Experiment tracking + model registry (local Docker) |
| Airflow | 8080 | Daily pipeline orchestration |
| FastAPI | 8000 | Prediction REST API |
| Streamlit | 8501 | 7-day forecast dashboard |

## Tech Stack

- **Language:** Python 3.12
- **ML:** LightGBM, scikit-learn (MultiOutputRegressor / MultiOutputClassifier)
- **MLOps:** MLflow (experiment tracking, model registry)
- **Orchestration:** Apache Airflow 3.x (daily schedule)
- **API:** FastAPI + Uvicorn
- **Frontend:** Streamlit + Plotly
- **Database:** PostgreSQL + SQLAlchemy + Alembic
- **Infrastructure:** Docker Compose
- **Package manager:** uv

## Repository Structure

```
weather-forecast-ai/
├── src/
│   ├── api/
│   │   └── main.py              # FastAPI endpoints
│   ├── config.py                # Env-var backed configuration
│   ├── models.py                # SQLAlchemy ORM models
│   ├── db.py                    # DB engine / session
│   ├── fetch_data.py            # Actual weather ingestion (ERA5 initial / forecast API daily)
│   ├── fetch_forecast.py        # NWP forecast ingestion (historical / inference)
│   ├── fetch_today.py           # Current conditions (DB → API fallback)
│   ├── feature_engineering.py   # Lag / diff / rolling / NWP features
│   ├── train_model.py           # LightGBM training + MLflow logging
│   ├── evaluate_model.py        # MAE / RMSE / F1 metrics
│   ├── predict.py               # Non-recursive 168-step direct forecast
│   ├── load_model.py            # Load latest model from registry
│   ├── save_model.py            # Promote run to model registry
│   └── streamlit_app.py         # Dashboard
├── dags/
│   └── weather_pipeline_dag.py  # Airflow DAG
├── alembic/                     # DB migrations
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.api
│   ├── Dockerfile.airflow
│   └── Dockerfile.mlflow
├── notebooks/                   # Research & experimentation (see below)
├── data/                        # MLflow DB + artifacts (git-ignored)
├── Makefile
└── pyproject.toml
```

## Notebooks

The `notebooks/` directory documents the research phase that informed the production pipeline:

| Notebook | Description |
|---|---|
| `01_eda.ipynb` | Exploratory data analysis of Tokyo weather data |
| `02_feature_engineering.ipynb` | Evaluating lag / diff / spatial feature strategies |
| `03_baseline_model.ipynb` | Linear regression and decision tree baselines |
| `04_model_improvement.ipynb` | LightGBM hyperparameter tuning |
| `05_model_comparison.ipynb` | LightGBM vs XGBoost final comparison |

Raw source data (JMA CSVs, 2021–2025) lives in `notebooks/data/original/`.

## Feature Engineering

For each of five Tokyo locations the pipeline generates:

- **Raw features:** 15 hourly meteorological variables
- **Time features:** hour, day-of-year, month (sin/cos encoded)
- **Spatial features:** difference from tokyo\_center per variable
- **Wind direction features:** sin/cos components (treats 0°/360° correctly as circular)
- **NWP features:** same-time NWP value, bias (actual − NWP), T+1 NWP forecast value
- **Lag features:** t−1, t−6, t−24
- **Diff features:** t−(t−1), t−(t−3)
- **Rolling mean:** 6 h and 24 h windows

### NWP Bias Correction

During training the model learns the regional bias between NWP forecasts and actuals (`actual − NWP`). At inference time, the T_now feature vector is computed once, then for each step k=1…168 the `nwp_next_*` columns are overridden with the actual future NWP forecast for that timestep. This non-recursive approach eliminates error accumulation across steps.

## Getting Started

### Prerequisites

- Docker Desktop
- `uv` (`pip install uv`)
- (Optional) NVIDIA GPU + CUDA drivers for accelerated training

### 1. Configure environment

```bash
cp .env.example .env
# Default: local Docker MLflow at http://mlflow:5000
# To use DagsHub instead, swap the MLFLOW_TRACKING_URI in .env and add credentials
```

### 2. Start all services

```bash
make build
make up
```

| UI | URL | Credentials |
|---|---|---|
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| Dashboard | http://localhost:8501 | — |

### 3. Initialize the database

Run once to populate the DB with historical data (30–60 min):

```bash
make db-migrate   # Create tables (including weather_nwp_forecast)
make db-init      # ERA5 actuals (2021–) + NWP forecast backfill (past 1 year)
```

### 4. Enable the daily Airflow pipeline

Activate the `weather_forecast_pipeline` DAG in the Airflow UI. The first run trains and registers the model automatically. After that, the pipeline runs every day and handles data refresh, retraining, and model promotion.

## Airflow Pipeline

```
fetch_data → fetch_nwp_forecast → train_model → evaluate_model → register_model
```

| Task | Description |
|---|---|
| `fetch_data` | Syncs the past 14 days of actual weather via forecast API `past_days` (no ERA5 lag) |
| `fetch_nwp_forecast` | Backfills the past 1 year of NWP forecasts from historical-forecast-api |
| `train_model` | Trains LightGBM models with NWP features and logs metrics / artifacts to MLflow |
| `evaluate_model` | Blocks registration if `reg_mae > 10.0` |
| `register_model` | Promotes the validated run to MLflow Model Registry |

## Make Targets

| Target | Description |
|---|---|
| `make build` | Build Docker images |
| `make up` / `make down` | Start / stop all services |
| `make db-migrate` | Run Alembic migrations only (create / alter tables) |
| `make db-init` | Migration + ERA5 backfill (2021–) + NWP backfill (initial setup) |
| `make fetch` | Sync past 14 days of actual weather via forecast API (no ERA5 lag) |
| `make fetch-nwp` | Sync past 1 year of NWP forecasts from historical-forecast-api |
| `make train` | Train model locally |
| `make predict` | Run prediction locally |
| `make test` | Run pytest |
| `make api-local` | Start FastAPI locally (port 8000) |
| `make streamlit` | Start Streamlit locally (port 8501) |
| `make mlflow-local` | Start MLflow UI locally (port 5000) |

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `GET /health` | — | Health check |
| `GET /forecast?hours=168` | — | Full hourly forecast including precipitation probability |
| `GET /model-info` | — | Current model version, run name, and training metadata |
| `GET /today` | — | Current observed conditions |
| `POST /predict` | `{"hours": 168, "location": "tokyo_center"}` | Forecast for a specific location |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/app` | PostgreSQL connection string |
| `MLFLOW_TRACKING_URI` | `http://mlflow:5000` | MLflow backend — local Docker or DagsHub URL |
| `MLFLOW_TRACKING_USERNAME` | — | DagsHub username (DagsHub only) |
| `MLFLOW_TRACKING_PASSWORD` | — | DagsHub access token (DagsHub only) |
| `LGBM_N_JOBS` | `-1` | LightGBM thread count (set to `1` in Docker to avoid contention) |
