import csv
import io
import os
import re
from datetime import date

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, send_file, url_for

load_dotenv()

from collector import INDUSTRY_CHOICES, collect_companies

app = Flask(__name__)

STATUS_CHOICES = ["未架電", "架電中", "通話済み", "アポ獲得", "NG", "不通"]
ASSIGNED_TO_CHOICES = [f"営業{i}部" for i in range(1, 8)]

SORT_OPTIONS = {
    "id_desc": ("id", "DESC", "新着順"),
    "status": ("status", "ASC", "状況順"),
    "reminder_date": ("reminder_date", "ASC", "リマインダー日順"),
    "company_name": ("company_name", "ASC", "会社名順"),
}

PER_PAGE = 100


def get_db_connection():
    """Cloud SQL (PostgreSQL) への接続を作成する。

    Cloud Run上では INSTANCE_UNIX_SOCKET (/cloudsql/PROJECT:REGION:INSTANCE) 経由、
    ローカル開発では Cloud SQL Auth Proxy 等を介した DB_HOST/DB_PORT 経由で接続する。
    """
    db_user = os.environ["DB_USER"]
    db_pass = os.environ["DB_PASS"]
    db_name = os.environ["DB_NAME"]
    unix_socket = os.environ.get("INSTANCE_UNIX_SOCKET")
    if unix_socket:
        return psycopg2.connect(user=db_user, password=db_pass, dbname=db_name, host=unix_socket)
    return psycopg2.connect(
        user=db_user,
        password=db_pass,
        dbname=db_name,
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=os.environ.get("DB_PORT", "5432"),
    )


class Db:
    """sqlite3.Connection に似たインターフェースを提供する psycopg2 のラッパー。"""

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def executemany(self, sql, seq_of_params):
        cur = self.conn.cursor()
        cur.executemany(sql.replace("?", "%s"), list(seq_of_params))
        return cur

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_db():
    if "db" not in g:
        g.db = Db(get_db_connection())
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = Db(get_db_connection())
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            company_name TEXT NOT NULL,
            industry TEXT,
            prefecture TEXT,
            municipality TEXT,
            employees INTEGER,
            phone TEXT,
            department TEXT,
            status TEXT NOT NULL DEFAULT '未架電',
            memo TEXT
        )
        """
    )

    for column, col_type in [
        ("municipality", "TEXT"),
        ("assigned_to", "TEXT"),
        ("last_visit_date", "TEXT"),
        ("reminder_date", "TEXT"),
    ]:
        db.execute(f"ALTER TABLE companies ADD COLUMN IF NOT EXISTS {column} {col_type}")

    db.execute("ALTER TABLE companies DROP COLUMN IF EXISTS contact_person")

    count = db.execute("SELECT COUNT(*) AS cnt FROM companies").fetchone()["cnt"]
    if count == 0:
        sample = [
            ("株式会社サンプル商事", "商社", "東京都", "千代田区", 120, "03-1234-5678", "営業部", "未架電", ""),
            ("テックイノベーション株式会社", "IT・ソフトウェア", "東京都", "渋谷区", 45, "03-2345-6789", "開発部", "未架電", ""),
            ("関西フードサービス株式会社", "食品・飲食", "大阪府", "大阪市中央区", 300, "06-1234-5678", "総務部", "通話済み", "後日再架電希望"),
            ("中部製造工業株式会社", "製造業", "愛知県", "名古屋市中村区", 850, "052-123-4567", "購買部", "未架電", ""),
            ("北海道アグリ株式会社", "農業・林業・水産業", "北海道", "札幌市中央区", 30, "011-123-4567", "経営企画部", "アポ獲得", "来週水曜14時訪問予定"),
            ("九州メディカル株式会社", "医療・福祉", "福岡県", "福岡市博多区", 210, "092-123-4567", "総務部", "NG", "他社サービス利用中"),
            ("湘南リゾート株式会社", "観光・宿泊", "神奈川県", "藤沢市", 95, "0466-12-3456", "企画部", "未架電", ""),
            ("みらい建設株式会社", "建設業", "埼玉県", "さいたま市大宮区", 430, "048-123-4567", "資材部", "不通", "3回コール後つながらず"),
            ("グリーンエナジー株式会社", "エネルギー", "千葉県", "千葉市中央区", 60, "043-123-4567", "営業企画部", "未架電", ""),
            ("関東物流株式会社", "運輸・物流", "東京都", "大田区", 520, "03-3456-7890", "総務部", "架電中", "担当者不在のため再架電"),
            ("ウェルネスケア株式会社", "医療・福祉", "大阪府", "大阪市北区", 18, "06-2345-6789", "代表", "未架電", ""),
            ("信州精密機械株式会社", "製造業", "長野県", "松本市", 150, "0263-12-3456", "技術部", "未架電", ""),
            ("クラウドソリューションズ株式会社", "IT・ソフトウェア", "東京都", "港区", 28, "03-4567-8901", "管理部", "アポ獲得", "オンライン商談を設定済み"),
            ("瀬戸内造船株式会社", "製造業", "広島県", "広島市西区", 980, "082-123-4567", "調達部", "未架電", ""),
            ("札幌ITサービス株式会社", "IT・ソフトウェア", "北海道", "札幌市中央区", 75, "011-234-5678", "営業部", "通話済み", "資料送付済み、来月フォロー"),
        ]
        db.executemany(
            """
            INSERT INTO companies
                (company_name, industry, prefecture, municipality, employees, phone, department, status, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample,
        )
        db.commit()
    db.close()


def build_filters(args):
    """Build SQL WHERE clause and params from query args."""
    conditions = []
    params = []

    keyword = args.get("keyword", "").strip()
    if keyword:
        conditions.append("company_name LIKE ?")
        params.append(f"%{keyword}%")

    industry = args.get("industry", "").strip()
    if industry:
        conditions.append("industry = ?")
        params.append(industry)

    prefecture = args.get("prefecture", "").strip()
    if prefecture:
        conditions.append("prefecture = ?")
        params.append(prefecture)

    municipality = args.get("municipality", "").strip()
    if municipality:
        conditions.append("municipality = ?")
        params.append(municipality)

    status = args.get("status", "").strip()
    if status:
        conditions.append("status = ?")
        params.append(status)

    assigned_to = args.get("assigned_to", "").strip()
    if assigned_to:
        conditions.append("assigned_to = ?")
        params.append(assigned_to)

    employees_min = args.get("employees_min", "").strip()
    if employees_min:
        conditions.append("employees >= ?")
        params.append(int(employees_min))

    employees_max = args.get("employees_max", "").strip()
    if employees_max:
        conditions.append("employees <= ?")
        params.append(int(employees_max))

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)
    return where, params


def get_current_page(args):
    try:
        return max(1, int(args.get("page", 1)))
    except ValueError:
        return 1


def page_url_args(page):
    args = request.args.to_dict(flat=True)
    args["page"] = page
    return args


@app.route("/")
def index():
    db = get_db()
    where, params = build_filters(request.args)
    page = get_current_page(request.args)

    sort = request.args.get("sort", "id_desc")
    if sort not in SORT_OPTIONS:
        sort = "id_desc"
    sort_column, sort_dir, _ = SORT_OPTIONS[sort]

    total = db.execute(f"SELECT COUNT(*) AS cnt FROM companies {where}", params).fetchone()["cnt"]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * PER_PAGE

    rows = db.execute(
        f"""
        SELECT * FROM companies {where}
        ORDER BY {sort_column} {sort_dir}, id DESC
        LIMIT ? OFFSET ?
        """,
        params + [PER_PAGE, offset],
    ).fetchall()

    industries = [r["industry"] for r in db.execute("SELECT DISTINCT industry FROM companies ORDER BY industry").fetchall()]
    prefectures = [r["prefecture"] for r in db.execute("SELECT DISTINCT prefecture FROM companies ORDER BY prefecture").fetchall()]
    municipalities = [r["municipality"] for r in db.execute("SELECT DISTINCT municipality FROM companies WHERE municipality IS NOT NULL ORDER BY municipality").fetchall()]

    return render_template(
        "index.html",
        companies=rows,
        industries=industries,
        prefectures=prefectures,
        municipalities=municipalities,
        statuses=STATUS_CHOICES,
        assigned_to_choices=ASSIGNED_TO_CHOICES,
        sort_options=SORT_OPTIONS,
        current_sort=sort,
        filters=request.args,
        total=total,
        page=page,
        per_page=PER_PAGE,
        total_pages=total_pages,
        start_item=offset + 1 if total else 0,
        end_item=min(offset + len(rows), total),
        prev_page_args=page_url_args(page - 1) if page > 1 else None,
        next_page_args=page_url_args(page + 1) if page < total_pages else None,
        today=date.today().isoformat(),
    )


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        db = get_db()
        db.execute(
            """
            INSERT INTO companies
                (company_name, industry, prefecture, municipality, employees, phone, department, status, memo, assigned_to, last_visit_date, reminder_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.form["company_name"],
                request.form.get("industry", ""),
                request.form.get("prefecture", ""),
                request.form.get("municipality", ""),
                int(request.form["employees"]) if request.form.get("employees") else None,
                request.form.get("phone", ""),
                request.form.get("department", ""),
                request.form.get("status", "未架電"),
                request.form.get("memo", ""),
                request.form.get("assigned_to", ""),
                request.form.get("last_visit_date", ""),
                request.form.get("reminder_date", ""),
            ),
        )
        db.commit()
        return redirect(url_for("index"))

    return render_template("form.html", company=None, statuses=STATUS_CHOICES, industries=INDUSTRY_CHOICES, assigned_to_choices=ASSIGNED_TO_CHOICES)


@app.route("/edit/<int:company_id>", methods=["GET", "POST"])
def edit(company_id):
    db = get_db()
    if request.method == "POST":
        db.execute(
            """
            UPDATE companies
            SET company_name=?, industry=?, prefecture=?, municipality=?, employees=?, phone=?,
                department=?, status=?, memo=?, assigned_to=?, last_visit_date=?, reminder_date=?
            WHERE id=?
            """,
            (
                request.form["company_name"],
                request.form.get("industry", ""),
                request.form.get("prefecture", ""),
                request.form.get("municipality", ""),
                int(request.form["employees"]) if request.form.get("employees") else None,
                request.form.get("phone", ""),
                request.form.get("department", ""),
                request.form.get("status", "未架電"),
                request.form.get("memo", ""),
                request.form.get("assigned_to", ""),
                request.form.get("last_visit_date", ""),
                request.form.get("reminder_date", ""),
                company_id,
            ),
        )
        db.commit()
        return redirect(url_for("index"))

    company = db.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
    return render_template("form.html", company=company, statuses=STATUS_CHOICES, industries=INDUSTRY_CHOICES, assigned_to_choices=ASSIGNED_TO_CHOICES)


@app.route("/delete/<int:company_id>", methods=["POST"])
def delete(company_id):
    db = get_db()
    db.execute("DELETE FROM companies WHERE id=?", (company_id,))
    db.commit()
    return redirect(url_for("index"))


@app.route("/export")
def export():
    db = get_db()
    where, params = build_filters(request.args)
    rows = db.execute(
        f"SELECT * FROM companies {where} ORDER BY id DESC", params
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["会社名", "業種", "都道府県", "市区町村", "従業員数", "電話番号", "部署", "状況", "メモ", "当社担当者", "最新訪問日", "リマインダー日"])
    for r in rows:
        writer.writerow(
            [r["company_name"], r["industry"], r["prefecture"], r["municipality"], r["employees"],
             r["phone"], r["department"], r["status"], r["memo"], r["assigned_to"],
             r["last_visit_date"], r["reminder_date"]]
        )

    csv_bytes = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(
        csv_bytes,
        mimetype="text/csv",
        as_attachment=True,
        download_name="telecall_list.csv",
    )


@app.route("/api/count")
def api_count():
    db = get_db()
    prefecture = request.args.get("prefecture", "")
    if prefecture:
        row = db.execute("SELECT COUNT(*) AS cnt FROM companies WHERE prefecture=?", (prefecture,)).fetchone()
    else:
        row = db.execute("SELECT COUNT(*) AS cnt FROM companies").fetchone()
    return jsonify({"count": row["cnt"]})


@app.route("/collect", methods=["GET", "POST"])
def collect():
    if request.method == "POST":
        industry = request.form["industry"]
        prefecture = request.form["prefecture"]
        municipality = request.form["municipality"]
        count = max(1, min(1000, int(request.form.get("count", 10))))
        assigned_to = request.form.get("assigned_to", "")

        db = get_db()

        # 同じ地域で既に登録済みの企業を法人番号・会社名で除外し、重複登録を防ぐ
        existing_rows = db.execute(
            "SELECT company_name, memo FROM companies WHERE prefecture=? AND municipality=?",
            (prefecture, municipality),
        ).fetchall()
        exclude_names = {r["company_name"] for r in existing_rows}
        exclude_corporate_numbers = set()
        for r in existing_rows:
            m = re.search(r"法人番号:(\d+)", r["memo"] or "")
            if m:
                exclude_corporate_numbers.add(m.group(1))

        results = collect_companies(
            industry, prefecture, municipality, count,
            exclude_corporate_numbers=exclude_corporate_numbers,
            exclude_names=exclude_names,
        )

        db.executemany(
            """
            INSERT INTO companies
                (company_name, industry, prefecture, municipality, employees, phone, department, status, memo, assigned_to)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c["company_name"], c["industry"], c["prefecture"], c["municipality"],
                    c["employees"], c["phone"], c["department"],
                    c["status"], c["memo"], assigned_to,
                )
                for c in results
            ],
        )
        db.commit()

        return redirect(url_for(
            "index",
            prefecture=prefecture,
            municipality=municipality,
        ))

    return render_template(
        "collect.html",
        industries=INDUSTRY_CHOICES,
        assigned_to_choices=ASSIGNED_TO_CHOICES,
        using_real_api=bool(os.environ.get("GBIZINFO_API_TOKEN")),
    )


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5050)
