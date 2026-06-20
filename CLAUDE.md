# テレアポリスト作成アプリ

## 概要
営業テレアポ用の企業リストを自動収集・管理するWebアプリ。

- **本番URL**: https://telapo-946260728277.asia-northeast1.run.app
- **Gitリポジトリ**: https://github.com/ikarugamana-hub/telapo
- **スタック**: Flask + PostgreSQL (Cloud Run + Cloud SQL)

## インフラ構成

| リソース | 詳細 |
|---|---|
| Cloud Run サービス | `telapo`、リージョン `asia-northeast1` |
| Cloud SQL インスタンス | `telapo-app-20260615:asia-northeast1:telapo-db` (db-f1-micro, PostgreSQL) |
| DBユーザー/DB | `telapo_app` / `telapo` |
| Secret Manager | `telapo-db-pass` (DBパスワード)、`telapo-gbizinfo-token` (gBizINFOトークン)、`telapo-collect-api-token` (収集Job認証) |
| GCPプロジェクト | `telapo-app-20260615` |

## デプロイ手順

```bash
export PATH=/opt/homebrew/share/google-cloud-sdk/bin:"$PATH"
cd ~/telecall-list-app
PROJECT_ID=telapo-app-20260615
REGION=asia-northeast1
RUNTIME_SA=telapo-runtime@${PROJECT_ID}.iam.gserviceaccount.com

gcloud iam service-accounts describe "$RUNTIME_SA" --project "$PROJECT_ID" >/dev/null 2>&1 || \
  gcloud iam service-accounts create telapo-runtime --project "$PROJECT_ID"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/cloudsql.client

TOKEN=$(openssl rand -hex 32)
gcloud secrets describe telapo-collect-api-token --project "$PROJECT_ID" >/dev/null 2>&1 || \
  printf %s "$TOKEN" | gcloud secrets create telapo-collect-api-token \
    --project "$PROJECT_ID" --replication-policy=automatic --data-file=-
unset TOKEN

for SECRET in telapo-db-pass telapo-gbizinfo-token telapo-collect-api-token; do
  gcloud secrets add-iam-policy-binding "$SECRET" --project "$PROJECT_ID" \
    --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor
done

gcloud run deploy telapo --source . --region asia-northeast1 \
  --project="$PROJECT_ID" --service-account="$RUNTIME_SA" --allow-unauthenticated \
  --add-cloudsql-instances=telapo-app-20260615:asia-northeast1:telapo-db \
  --set-env-vars=DB_USER=telapo_app,DB_NAME=telapo,INSTANCE_UNIX_SOCKET=/cloudsql/telapo-app-20260615:asia-northeast1:telapo-db \
  --set-secrets=DB_PASS=telapo-db-pass:latest,GBIZINFO_API_TOKEN=telapo-gbizinfo-token:latest,COLLECT_API_TOKEN=telapo-collect-api-token:latest \
  --timeout=300 --quiet

SERVICE_URL=$(gcloud run services describe telapo --project "$PROJECT_ID" \
  --region "$REGION" --format='value(status.url)')
gcloud run jobs deploy telapo-prefecture-boost --source . --project "$PROJECT_ID" \
  --region "$REGION" --service-account="$RUNTIME_SA" \
  --command=python --args=scripts/collect_prefecture_boost.py \
  --set-env-vars="BASE_URL=$SERVICE_URL" \
  --set-secrets=COLLECT_API_TOKEN=telapo-collect-api-token:latest \
  --tasks=5 --parallelism=5 --task-timeout=14400 --max-retries=1

gcloud run jobs execute telapo-prefecture-boost --project "$PROJECT_ID" \
  --region "$REGION"
```

`telapo-collect-api-token` はServiceと収集Jobだけへ注入する。ローテーション時も
`openssl rand -hex 32` と `printf %s` を使って改行なしのSecret versionを追加し、
ServiceとJobを再デプロイする。

## 主なファイル

- `app.py` — Flaskアプリ本体。ルート一覧:
  - `/` — 企業一覧・絞り込み
  - `/add`, `/edit/<id>`, `/delete/<id>` — CRUD
  - `/export` — CSVエクスポート
  - `/collect` — gBizINFO APIで企業を自動収集するJob専用POST。`X-Collect-Token`必須
  - `/api/count?prefecture=XX` — 軽量カウントAPI(JSON)
- `collector.py` — gBizINFO REST API v2連携。`fetch_from_gbizinfo()` がページネーション(最大10ページ×100件=1000件/市区町村)＋詳細API並列取得(ThreadPoolExecutor、5worker)を実装
- `area_codes.json` — 都道府県コード・市区町村コード(gBizINFO用)
- `Dockerfile` — gunicorn、`--workers 1 --threads 8 --timeout 300`

## DB スキーマ

```sql
CREATE TABLE companies (
  id SERIAL PRIMARY KEY,
  company_name TEXT NOT NULL,
  industry TEXT,
  prefecture TEXT,
  municipality TEXT,
  employees INTEGER,
  phone TEXT,
  department TEXT,
  status TEXT DEFAULT '未架電',
  memo TEXT,
  assigned_to TEXT,
  sales_department TEXT,
  last_visit_date TEXT,
  reminder_date TEXT,
  last_approach_date TEXT
);
```

## gBizINFO 自動収集の仕組み

収集Jobが`X-Collect-Token`を付けて`/collect` (POST) に
`prefecture`, `municipality`, `count`(最大1000) を渡すと:
1. `collector.py` の `fetch_from_gbizinfo()` が検索API(ページネーション)で法人一覧を取得
2. 既存登録企業(法人番号・会社名)を除外してデュプリケーション回避
3. 詳細APIを並列取得(ThreadPoolExecutor)して従業員数・事業概要等を補完
4. 従業員数が多い順にソートして上位 `count` 件をDBに挿入

**レート制限について**: gBizINFO には1分あたりのリクエスト上限がある。初回検索の
`429 Too Many Requests` や通信失敗はServiceが502を返し、Job側で再試行する。

## 収集Jobの状況確認

```bash
gcloud run jobs executions list --job=telapo-prefecture-boost \
  --project=telapo-app-20260615 --region=asia-northeast1
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="telapo-prefecture-boost"' \
  --project=telapo-app-20260615 --limit=100
```

## 接続情報 (ローカル開発用)

Cloud SQL Auth Proxy 経由でローカル接続する場合:

```bash
export PATH=/opt/homebrew/share/google-cloud-sdk/bin:"$PATH"
# ADC認証(初回のみ)
gcloud auth application-default login

# Proxy起動
cloud-sql-proxy telapo-app-20260615:asia-northeast1:telapo-db &

# psql接続
export PATH=/opt/homebrew/opt/libpq/bin:$PATH
PGPASSWORD="<DB_PASS>" psql -h 127.0.0.1 -p 5432 -U telapo_app -d telapo
```
