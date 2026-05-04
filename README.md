# Weather Forecast AI — MLOps Pipeline

An end-to-end MLOps pipeline that automatically fetches Tokyo weather data, trains a LightGBM forecasting model, and serves 7-day predictions through a REST API and Streamlit dashboard.

## Overview

The system predicts hourly weather for the next 168 hours (7 days) across five Tokyo locations. A daily Airflow pipeline handles data ingestion, model training, evaluation, and promotion to the model registry — with no manual intervention required.

**Prediction targets (1-hour-ahead, tokyo\_center):**

| Type | Targets |
|---|---|
| Regression | Temperature, humidity, dew point, pressure, cloud cover (low/mid/high/total), precipitation, rain, wind speed/direction/gusts |
| Classification | WMO weather code (5 classes: clear / cloudy / rain / snow-ice / thunderstorm) |

## Architecture

```
Open-Meteo API
      │
      ▼
fetch_data ──► PostgreSQL
                  │
                  ▼
            train_model  (LightGBM MultiOutput)
                  │
                  ▼
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
    /today
    /predict
```

### Services

| Service | Port | Description |
|---|---|---|
| PostgreSQL | 5432 | Weather observation & prediction store |
| MLflow | 5000 | Experiment tracking + model registry |
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
│   ├── fetch_data.py            # Open-Meteo Archive API ingestion
│   ├── fetch_today.py           # Current conditions (DB → API fallback)
│   ├── feature_engineering.py   # Lag / diff / rolling features
│   ├── train_model.py           # LightGBM training + MLflow logging
│   ├── evaluate_model.py        # MAE / RMSE / F1 metrics
│   ├── predict.py               # Recursive 168-step forecast
│   ├── load_model.py            # Load latest model from registry
│   ├── save_model.py            # Promote run to model registry
│   └── streamlit_app.py         # Dashboard
├── dags/
│   └── weather_pipeline_dag.py  # Airflow DAG (fetch → train → eval → register)
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
- **Lag features:** t−1, t−6, t−24
- **Diff features:** t−(t−1), t−(t−3)
- **Rolling mean:** 6 h and 24 h windows

Total: **663 features** per sample.

## Getting Started

### Prerequisites

- Docker Desktop
- `uv` (`pip install uv`)
- (Optional) NVIDIA GPU + CUDA drivers for accelerated training

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env if needed — default values work with Docker
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

Run once to populate the DB with data from 2021 onwards (30–60 min):

```bash
make db-init
```

### 4. Train the initial model

```bash
make train
```

The trained model is registered in MLflow and immediately served by the API.

### 5. Enable the daily Airflow pipeline

Activate the `weather_forecast_pipeline` DAG in the Airflow UI. It runs automatically every day and handles data refresh, retraining, and model promotion.

## Airflow Pipeline

```
fetch_data → train_model → evaluate_model → register_model
```

| Task | Description |
|---|---|
| `fetch_data` | Fetches the past 365 days from Open-Meteo Archive API (skips already-imported ranges) |
| `train_model` | Trains LightGBM models and logs metrics / artifacts to MLflow |
| `evaluate_model` | Blocks registration if `reg_mae > 10.0` |
| `register_model` | Promotes the validated run to MLflow Model Registry |

## Make Targets

| Target | Description |
|---|---|
| `make build` | Build Docker images |
| `make up` / `make down` | Start / stop all services |
| `make db-init` | Init DB schema + fetch historical data from 2021 |
| `make fetch` | Fetch latest 365 days of weather data |
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
| `GET /forecast?hours=168` | — | Full hourly forecast |
| `GET /today` | — | Current observed conditions |
| `POST /predict` | `{"hours": 168, "location": "tokyo_center"}` | Forecast for a specific location |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/app` | PostgreSQL connection string |
| `MLFLOW_TRACKING_URI` | `sqlite:///data/mlflow.db` | MLflow tracking backend |
| `LGBM_N_JOBS` | `-1` | LightGBM thread count (set to `1` in Docker to avoid contention) |
