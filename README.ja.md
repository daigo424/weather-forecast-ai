# 天気予報 AI — MLOps パイプライン

東京の気象データを自動取得し、LightGBM による予測モデルを学習・提供する End-to-End MLOps パイプラインです。REST API と Streamlit ダッシュボードから 7 日間の予報を参照できます。

## 概要

東京都内 5 地点の今後 168 時間（7 日間）の気象を 1 時間ごとに予測します。データ取得 → モデル学習 → 評価 → モデル登録まで、Airflow による日次パイプラインが自動的に行います。

**予測対象（1 時間後, tokyo\_center）:**

| 種別 | 対象変数 |
|---|---|
| 回帰 | 気温・湿度・露点温度・海面気圧・地表気圧・雲量（低/中/高/全天）・降水量・雨量・風速・風向・最大瞬間風速 |
| 分類 | WMO 天気コード（5 クラス：晴天 / 曇天 / 雨 / 雪・氷 / 雷雨） |

## アーキテクチャ

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
            evaluate_model  (MAE 閾値チェック)
                  │
            register_model  (MLflow Model Registry)
                  │
          ┌───────┴───────┐
          ▼               ▼
       FastAPI        Streamlit
    /forecast          ダッシュボード
    /today
    /predict
```

### サービス一覧

| サービス | ポート | 説明 |
|---|---|---|
| PostgreSQL | 5432 | 気象観測・予測データの保存 |
| MLflow | 5000 | 実験管理・モデルレジストリ |
| Airflow | 8080 | 日次パイプラインのオーケストレーション |
| FastAPI | 8000 | 予測 REST API |
| Streamlit | 8501 | 7 日間予報ダッシュボード |

## 技術スタック

- **言語:** Python 3.12
- **ML:** LightGBM、scikit-learn (MultiOutputRegressor / MultiOutputClassifier)
- **MLOps:** MLflow（実験管理、モデルレジストリ）
- **オーケストレーション:** Apache Airflow 3.x（日次スケジュール）
- **API:** FastAPI + Uvicorn
- **フロントエンド:** Streamlit + Plotly
- **データベース:** PostgreSQL + SQLAlchemy + Alembic
- **インフラ:** Docker Compose
- **パッケージマネージャ:** uv

## リポジトリ構成

```
weather-forecast-ai/
├── src/
│   ├── api/
│   │   └── main.py              # FastAPI エンドポイント
│   ├── config.py                # 設定値（環境変数対応）
│   ├── models.py                # SQLAlchemy ORM モデル
│   ├── db.py                    # DB エンジン・セッション
│   ├── fetch_data.py            # Open-Meteo Archive API からのデータ取得
│   ├── fetch_today.py           # 本日の実況天気取得（DB → API フォールバック）
│   ├── feature_engineering.py   # ラグ・差分・移動平均特徴量生成
│   ├── train_model.py           # LightGBM 学習 + MLflow 記録
│   ├── evaluate_model.py        # MAE / RMSE / F1 評価
│   ├── predict.py               # 168 ステップ再帰予測
│   ├── load_model.py            # レジストリから最新モデルをロード
│   ├── save_model.py            # Run をモデルレジストリに登録
│   └── streamlit_app.py         # ダッシュボード
├── dags/
│   └── weather_pipeline_dag.py  # Airflow DAG（fetch → train → eval → register）
├── alembic/                     # DB マイグレーション
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.api
│   ├── Dockerfile.airflow
│   └── Dockerfile.mlflow
├── notebooks/                   # 実験・分析（後述）
├── data/                        # MLflow DB・アーティファクト（.gitignore 対象）
├── Makefile
└── pyproject.toml
```

## notebooks/ について

`notebooks/` は、本番パイプラインで使う特徴量・モデルを決定するための実験の軌跡です。

| Notebook | 内容                              |
|---|---------------------------------|
| `01_eda.ipynb` | 東京気象データの探索的データ分析                |
| `02_feature_engineering.ipynb` | ラグ・差分・空間特徴量の有効性検証               |
| `03_baseline_model.ipynb` | 線形回帰・決定木によるベースライン構築             |
| `04_model_improvement.ipynb` | LightGBM のハイパーパラメータチューニング       |
| `05_model_comparison.ipynb` | LightGBM vs XGBoost vs その他の最終比較 |

元データ（気象庁 CSV、2021–2025 年）は `notebooks/data/original/` に格納しています。

## 特徴量エンジニアリング

東京都内 5 地点に対して以下の特徴量を生成します：

- **生の気象値:** 15 種類の時間別観測値
- **時間特徴量:** 時刻・年間通し日・月（sin/cos エンコーディング）
- **空間特徴量:** 各地点と tokyo\_center との差分
- **ラグ特徴量:** t−1、t−6、t−24 時間
- **差分特徴量:** t−(t−1)、t−(t−3)
- **移動平均:** 6 時間・24 時間ウィンドウ

合計: **1 サンプルあたり 663 特徴量**

## クイックスタート

### 前提条件

- Docker Desktop
- `uv`（`pip install uv`）
- （任意）NVIDIA GPU + CUDA ドライバ（学習高速化）

### 1. 環境設定

```bash
cp .env.example .env
# 必要に応じて .env を編集（Docker 環境ではデフォルト値で動作します）
```

### 2. 全サービスを起動

```bash
make build
make up
```

| UI | URL | 認証情報 |
|---|---|---|
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| ダッシュボード | http://localhost:8501 | — |

### 3. DB の初期化とデータ取得

初回のみ実行します（2021 年以降のデータを取得、30〜60 分程度）：

```bash
make db-init
```

### 4. 初回モデル学習

```bash
make train
```

学習済みモデルは MLflow に登録され、API・ダッシュボードから即時利用できます。

### 5. Airflow 日次パイプラインの有効化

Airflow UI で `weather_forecast_pipeline` DAG を有効化します。以降は毎日自動でデータ更新・再学習・モデル登録が実行されます。

## Airflow パイプライン

```
fetch_data → train_model → evaluate_model → register_model
```

| タスク | 説明 |
|---|---|
| `fetch_data` | 過去 365 日分を Open-Meteo Archive API から取得（取得済み範囲はスキップ） |
| `train_model` | LightGBM モデルを学習し、メトリクス・アーティファクトを MLflow に記録 |
| `evaluate_model` | `reg_mae > 10.0` の場合は登録をブロック |
| `register_model` | 検証済み Run を MLflow Model Registry に登録 |

## Make コマンド一覧

| コマンド | 説明 |
|---|---|
| `make build` | Docker イメージをビルド |
| `make up` / `make down` | 全サービスの起動 / 停止 |
| `make db-init` | DB スキーマ作成 + 2021 年以降のデータ取得（初回のみ） |
| `make fetch` | 最新 365 日分のデータ取得 |
| `make train` | ローカルでモデル学習 |
| `make predict` | ローカルで予測実行 |
| `make test` | pytest 実行 |
| `make api-local` | FastAPI をローカル起動（port 8000） |
| `make streamlit` | Streamlit をローカル起動（port 8501） |
| `make mlflow-local` | MLflow UI をローカル起動（port 5000） |

## API エンドポイント

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `GET /health` | — | ヘルスチェック |
| `GET /forecast?hours=168` | — | 時間別予測データ（全列） |
| `GET /today` | — | 本日の実況天気 |
| `POST /predict` | `{"hours": 168, "location": "tokyo_center"}` | 特定地点の予測 |

## 環境変数

| 変数名 | デフォルト値 | 説明 |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/app` | PostgreSQL 接続文字列 |
| `MLFLOW_TRACKING_URI` | `sqlite:///data/mlflow.db` | MLflow トラッキングバックエンド |
| `LGBM_N_JOBS` | `-1` | LightGBM スレッド数（Docker 内では `1` 推奨） |
