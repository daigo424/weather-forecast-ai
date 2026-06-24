# Weather Forecast AI — MLOps パイプライン

東京の気象データを Open-Meteo から取得し、NWP（数値天気予報）に対して LightGBM による誤差補正モデルを学習し、REST API と Streamlit ダッシュボードで 7 日間予報を提供するエンドツーエンドの MLOps パイプラインです。

## 概要

中核的なアイデアは **NWP バイアス補正** です。ゼロから気象を予測するのではなく、NWP モデルの出力と ERA5 再解析データ（実測値）との系統的な誤差を学習し、推論時に NWP 予報を補正します。

**補正対象:**

| 対象 | 単位 |
|---|---|
| 気温 | °C |
| 降水量 | mm |
| 全雲量 | % |
| 下層雲量 | % |

天気コード（WMO）は NWP からそのまま使うのではなく、補正後の値（雲量・降水量・気温）と CAPE を使って推論時にルールベースで再生成します。これにより、表示される天気アイコンが補正済み予報と整合します。

## アーキテクチャ

```
Open-Meteo Archive API               Open-Meteo Previous-Runs API
（ERA5 実測値）                        （過去 NWP 予報）
       │                                       │
       ▼                                       ▼
  01_raw/actual/                         01_raw/forecast/
       │                                       │
       ▼                                       ▼
  02_processed/actual/                   02_processed/forecast/
                        │           │
                        └─── 結合 ──┘
                               │
                    誤差 = 実測値 − NWP
                               │
                    build_features() [ラグ/ローリング]
                               │
                        03_features/
                               │
                    LightGBM × 4 モデル
                    （補正対象ごとに 1 本）
                               │
                    WeatherForecastPyfunc
                    （4 モデルをまとめてバンドル）
                               │
                     MLflow モデルレジストリ
                      ┌────────┴────────┐
                      ▼                 ▼
              Feast（Redis）          FastAPI
          [誤差ラグ特徴量]         /forecast /today
                      │              /model-info
                      └────────┬────────┘
                               ▼
                           Streamlit
                      （7 日間ダッシュボード）
```

### サービス一覧

| サービス | ポート | 説明 |
|---|---|---|
| PostgreSQL | 5432 | MLflow バックエンドストア + Airflow メタデータ + Feast オフラインストア |
| MLflow | 5000 | 実験トラッキング + モデルレジストリ |
| Redis | 6379 | Feast オンラインストア（誤差ラグ特徴量） |
| Airflow | 8080 | 日次パイプラインのオーケストレーション |
| FastAPI | 8000 | 予測 REST API |
| Streamlit | 8501 | 7 日間予報ダッシュボード |
| Evidently UI | 8088 | モデル評価レポート |
| Feast UI | 8888 | フィーチャーストア ブラウザ |

## 技術スタック

| カテゴリ | ツール |
|---|---|
| 言語 | Python 3.13 |
| ML | LightGBM |
| MLOps | MLflow（トラッキング + レジストリ）、Evidently AI（評価） |
| フィーチャーストア | Feast（Redis オンラインストア + PostgreSQL オフラインストア） |
| オーケストレーション | Apache Airflow 3.x（日次スケジュール） |
| API | FastAPI + Uvicorn |
| フロントエンド | Streamlit + Plotly |
| データベース | PostgreSQL |
| インフラ | Docker Compose |
| パッケージ管理 | uv |
| データバージョン管理 | DVC + S3（ゴールデンデータセット） |

## ML パイプライン

### 学習フロー

```
fetch_data → train_model → evaluate_model → materialize_features
```

1. **fetch_data** — ERA5 実測値と NWP 過去予報を Open-Meteo から増分取得し、`01_raw/` に JSON で保存した後、`02_processed/` に parquet として処理する
2. **train_model** — 実測値/予報をマージし、ターゲットごとの誤差（`実測値 − NWP`）を計算し、ラグ/ローリング特徴量を生成し、4 本の LightGBM 回帰モデルを学習し、`WeatherForecastPyfunc` としてバンドルして MLflow モデルレジストリに `evaluated_successful=0` で登録する
3. **evaluate_model** — 登録済みモデルをロードし、Evidently AI を使ってターゲットごとに MAE/RMSE/Bias を評価し、全ターゲットが閾値を通過すれば `evaluated_successful=1` タグを設定する
4. **materialize_features** — Feast フィーチャー定義を適用し、直近の誤差ラグ特徴量を Redis（オンラインストア）に低レイテンシ推論のためプッシュする

### 推論フロー

1. Open-Meteo `/v1/forecast` から未来の NWP 予報を取得（CAPE 含む）
2. `WeatherForecastPyfunc.predict()` を呼び出す:
   - NWP 入力から特徴量を生成
   - Feast オンラインストア（Redis）から誤差ラグ特徴量を取得
   - 各 LightGBM モデルを適用: `補正値 = NWP値 + 予測誤差`
3. 補正済み値 + CAPE から天気コードを再マップ
4. 補正済み予報の DataFrame を返す

## バージョン管理

独立した 2 軸のバージョン体系:

| バージョン | 変更トリガー | 採番 | 管理場所 |
|---|---|---|---|
| `model_interface_version` | API スキーマ / 特徴量構造の変更 | 手動インクリメント | `deployment/versions.yaml` |
| `training_version` | 再学習のたびに | 自動採番（interface version 変更時にリセット） | MLflow モデルバージョンタグ |

### アクティブモデルの選択ロジック

```
max(training_version) where
  name = weather_forecast_{location}
  AND model_interface_version = <deployment/versions.yaml の値>
  AND evaluated_successful = "1"
```

条件に一致するモデルが見つからない場合、API はクラッシュせずに HTTP 503（モデル未準備）を返します。これにより、旧 Pod が有効なまま残る Blue/Green デプロイメントが実現します。

## はじめかた

### 前提条件

- Docker Desktop
- `uv`（`pip install uv`）

### 1. 環境設定

```bash
cp .env.example .env
# 必要に応じて .env を編集（ローカル Docker ではデフォルト値で動作します）
```

### 2. サービス起動

```bash
make build
make up
```

| UI | URL | 認証情報 |
|---|---|---|
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| ダッシュボード | http://localhost:8501 | — |
| Evidently | http://localhost:8088 | — |
| Feast UI | http://localhost:8888 | — |

### 3. 初回データ取得（初回のみ）

```bash
make fetch-all-params    # ERA5 実測値 + NWP 予報を 2023-01-01 から取得
make process-all-params  # 生 JSON → parquet に変換
```

ネットワーク速度により 30〜60 分かかります。

### 4. モデル学習

```bash
make train      # 特徴量生成 + 学習 + MLflow 登録
make evaluate   # 評価 + evaluated_successful タグ設定
```

または Airflow の `weather_forecast_pipeline` DAG を有効化すると、データ取得・学習・評価・マテリアライズを日次で自動実行します。

### 5. ダッシュボード確認

http://localhost:8501 を開きます。モデルがまだ準備できていない場合は、学習方法を説明するバナーが表示されます。

## Make ターゲット一覧

| ターゲット | 説明 |
|---|---|
| `make build` | 全 Docker イメージをビルド |
| `make up` / `make down` | 全サービスを起動 / 停止 |
| `make fetch-all-params` | ERA5 実測値 + NWP 予報を取得（2023-01-01 〜 現在） |
| `make process-all-params` | 生 JSON → parquet に変換（同日付範囲） |
| `make fetch-actual-all-params` | ERA5 実測値のみ取得（増分） |
| `make fetch-forecast-all-params` | NWP 予報のみ取得（増分） |
| `make train` | ローカルで学習パイプラインを実行 |
| `make evaluate` | ローカルで評価 + プロモーションを実行 |
| `make materialize` | Feast フィーチャー定義を適用 + Redis にマテリアライズ |
| `make s3-upload-raw` | `01_raw/` を S3 にアップロード |
| `make s3-download-raw` | `01_raw/` を S3 からダウンロード |
| `make golden-dataset-push` | DVC 経由でゴールデンデータセットを S3 にプッシュ |
| `make golden-dataset-pull` | DVC 経由でゴールデンデータセットを S3 からプル |
| `make logs` | 全サービスのログをテール表示 |
| `make ps` | コンテナの状態を表示 |
| `make db` | psql シェルを開く |

## API エンドポイント

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `GET /health` | — | ロケーションごとのモデル準備状態 |
| `GET /forecast` | `?hours=168&location=tokyo` | 補正済み時間単位予報（168 時間） |
| `GET /model-info` | — | アクティブモデルのバージョンと学習メタデータ |
| `GET /today` | `?location=tokyo` | Open-Meteo からの現在の観測値 |
| `GET /historical-comparison` | `?days=7&location=tokyo` | 過去 N 日間の NWP vs 補正済み vs ERA5 比較 |
| `POST /predict` | `{"hours": 168, "location": "tokyo"}` | GET /forecast と同等（POST 形式） |

学習済みモデルが存在しない場合、全エンドポイントは HTTP 503 と説明メッセージを返します。

## 環境変数

説明付きの完全なリストは `.env.example` を参照してください。
