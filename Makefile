-include .env
export

# src/ をモジュール検索パスに追加することで
# apps.* / packages.* を src. プレフィックスなしで import できるようにする
export PYTHONPATH := src

COMPOSE := docker compose -f infra/docker/docker-compose.local.yml
RUN := $(COMPOSE) run --rm --remove-orphans
EXEC := $(COMPOSE) exec
DB_URL := postgresql://$(DB_USERNAME):$(DB_PASSWORD)@$(DB_HOST):$(DB_PORT)/$(MLFLOW_DB_NAME)?sslmode=$(DB_SSLMODE)

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

rm-volumes:
	$(COMPOSE) down --volumes

fetch-actual-all-params:
	uv run python -m apps.fetch_actual_all_params

fetch-forecast-all-params:
	uv run python -m apps.fetch_forecast_all_params

fetch-all-params:
	uv run python -m apps.fetch_actual_all_params --start 2023-01-01 --end 2025-12-31
	uv run python -m apps.fetch_forecast_all_params --start 2023-01-01 --end 2025-12-31

process-actual-all-params:
	uv run python -m apps.process_actual_all_params

process-forecast-all-params:
	uv run python -m apps.process_forecast_all_params

process-all-params:
	uv run python -m apps.process_actual_all_params --start 2023-01-01 --end 2025-12-31
	uv run python -m apps.process_forecast_all_params --start 2023-01-01 --end 2025-12-31

# --- S3 データ同期 ---

s3-upload-raw:
	uv run python scripts/s3_sync_raw.py upload

s3-download-raw:
	uv run python scripts/s3_sync_raw.py download

# --- ゴールデンデータセット管理 (DVC) ---
# DVC の S3 接続設定は .dvc/config.local に記載（.dvc/config.local.example を参照）。
# AWS_PROFILE は誤操作防止のゲートとして要求する（実際の認証には使わない）。
# 使用例: AWS_PROFILE=your-aws-profile make golden-dataset-push

golden-dataset-push:
	uv run python scripts/dvc_golden_dataset.py push

golden-dataset-pull:
	uv run python scripts/dvc_golden_dataset.py pull

golden-dataset-status:
	uv run dvc status data/golden-dataset.dvc

train:
	uv run python -m apps.train_pipeline

evaluate:
	uv run python -m apps.evaluate_and_promote

materialize:
	uv run python -m apps.materialize_features

# --- 補助 ---

ps:
	$(COMPOSE) ps

shell-%:
	$(EXEC) $* bash || $(EXEC) $* sh || $(EXEC) $* ash

shell-run-%:
	$(RUN) --entrypoint bash $* || $(RUN) --entrypoint sh $* || $(RUN) --entrypoint ash $*

db:
	$(EXEC) db psql "$(DB_URL)"

# --- AWS / EKS / ArgoCD ---

ENV ?= test

get-caller-identity:
	aws sts get-caller-identity


check-aws-profile:
ifndef AWS_PROFILE
	$(error AWS_PROFILE が未設定です。export AWS_PROFILE=<profile> を実行するか、.env に AWS_PROFILE=<profile> を追記してください)
endif

kubeconfig: check-aws-profile
	aws eks update-kubeconfig --name $(shell aws eks list-clusters --query 'clusters[0]' --output text) --region ap-northeast-1 --role-arn arn:aws:iam::$(shell aws sts get-caller-identity --query Account --output text):role/$(shell aws eks list-clusters --query 'clusters[0]' --output text)-eks-developer

argocd-password:
	kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | python -c "import sys,base64; print(base64.b64decode(sys.stdin.read().strip()).decode())"

argocd-port-forward:
	kubectl port-forward svc/argocd-server -n argocd 18080:80

# ArgoCD を HTTP モードに切り替える（初回のみ実行）
argocd-enable-http:
	kubectl patch configmap argocd-cmd-params-cm -n argocd --type merge -p "{\"data\":{\"server.insecure\":\"true\"}}"
	kubectl rollout restart deployment/argocd-server -n argocd
	kubectl rollout status deployment/argocd-server -n argocd --timeout=3m

# aws sso login --profile <profile> を先に実行しておくこと
argocd-ui: kubeconfig
	@echo -----------------------------
	@echo ArgoCD UI: http://localhost:18080
	@echo Username:  admin
	kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | python -c "import sys,base64; print('Password:  ' + base64.b64decode(sys.stdin.read().strip()).decode())"
	@echo -----------------------------
	@echo Port-forward starting... Ctrl+C to stop
	kubectl port-forward svc/argocd-server -n argocd 18080:80

# --- Coding ---

terraform-fmt:
	terraform fmt -recursive ./infra/terraform
