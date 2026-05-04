SHELL := /bin/bash
-include .env
export

COMPOSE := docker compose -f docker/docker-compose.yml

build:
	$(COMPOSE) build

build-no-cache:
	$(COMPOSE) build --no-cache

up:
	$(COMPOSE) up

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

api-up:
	$(COMPOSE) up -d api

api-down:
	$(COMPOSE) stop api

frontend-up:
	$(COMPOSE) up -d frontend

frontend-down:
	$(COMPOSE) stop frontend

mlflow-up:
	$(COMPOSE) up -d mlflow

airflow-up:
	$(COMPOSE) up -d airflow

# ローカル実行
db-init:
	uv run alembic upgrade head
	uv run python -c "from src.fetch_data import run; from datetime import date; run(start=date(2021, 1, 1))"

fetch:
	uv run python -m src.fetch_data

train:
	uv run python -m src.train_model

predict:
	uv run python -m src.predict

test:
	uv run pytest tests/ -v

api-local:
	uv run uvicorn src.api.main:app --reload --port 8000

streamlit:
	uv run streamlit run src/streamlit_app.py --server.port 8501

mlflow-local:
	uv run mlflow ui --backend-store-uri sqlite:///data/mlflow.db --port 5000
