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
| Secret Manager | `telapo-db-pass` (DBパスワード)、`telapo-gbizinfo-token` (gBizINFOトークン) |
| GCPプロジェクト | `telapo-app-20260615` |

## デプロイ手順

```bash
export PATH=/opt/homebrew/share/google-cloud-sdk/bin:"$PATH"
cd ~/telecall-list-app
gcloud run deploy telapo --source . --region asia-northeast1 \
  --add-cloudsql-instances=telapo-app-20260615:asia-northeast1:telapo-db \
  --set-env-vars=DB_USER=telapo_app,DB_NAME=telapo,INSTANCE_UNIX_SOCKET=/cloudsql/telapo-app-20260615:asia-northeast1:telapo-db \
  --set-secrets=DB_PASS=telapo-db-pass:latest,GBIZINFO_API_TOKEN=telapo-gbizinfo-token:latest \
  --timeout=300 --quiet
```

## 主なファイル

- `app.py` — Flaskアプリ本体。ルート一覧:
  - `/` — 企業一覧・絞り込み
  - `/add`, `/edit/<id>`, `/delete/<id>` — CRUD
  - `/export` — CSVエクスポート
  - `/collect` — gBizINFO APIで企業を自動収集 (POST)
  - `/api/count?prefecture=XX` — 軽量カウントAPI(JSON)
- `collector.py` — gBizINFO連携。`fetch_from_gbizinfo()` がページネーション(最大10ページ×100件=1000件/市区町村)＋詳細API並列取得(ThreadPoolExecutor、5worker)を実装
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
  last_visit_date TEXT,
  reminder_date TEXT
);
```

## gBizINFO 自動収集の仕組み

`/collect` (POST) に `prefecture`, `municipality`, `count`(最大1000) を渡すと:
1. `collector.py` の `fetch_from_gbizinfo()` が検索API(ページネーション)で法人一覧を取得
2. 既存登録企業(法人番号・会社名)を除外してデュプリケーション回避
3. 詳細APIを並列取得(ThreadPoolExecutor)して従業員数・事業概要等を補完
4. 従業員数が多い順にソートして上位 `count` 件をDBに挿入

**レート制限について**: gBizINFO には1分あたりのリクエスト上限がある。大量収集時に `429 Too Many Requests` が返った場合、例外をキャッチして空リスト返却(デグレなし)。

## 47都道府県一括収集スクリプト

`/tmp/collect_all_japan.py` — 47都道府県×全市区町村を最大10パス繰り返し、各県10,000社を目標に収集。2秒インターバル付きで順次実行。

現在バックグラウンドで実行中 (PID 28291)、ログ: `~/telecall-list-app/collect_all_japan.log`

```bash
# 状況確認
tail -f ~/telecall-list-app/collect_all_japan.log

# 停止する場合
pkill -f collect_all_japan.py
```

## 現在のデータ状況 (2026-06-16 時点)

| 都道府県 | 件数 |
|---|---|
| 石川県 | 12,484 (目標達成) |
| 富山県 | 6,172 |
| 福井県 | 2,490 |
| 北海道 | 収集中 |
| その他 | 未収集 |
| **合計** | **21,146** |

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
