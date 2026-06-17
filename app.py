import csv
import io
import os
import re
from datetime import date
from urllib.parse import quote_plus

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, send_file, url_for

load_dotenv()

from collector import INDUSTRY_CHOICES, PREFECTURE_CODES, collect_companies

app = Flask(__name__)

STATUS_CHOICES = [
    "未架電",
    "資料送付",
    "訪問/面談",
    "引合/見積",
    "成約",
    "失注",
    "ﾍﾟﾝﾃﾞｨﾝｸﾞ",
    "難攻/NG",
    "HPｴﾝﾄﾘｰ",
    "既存",
    "不在/再TEL",
]
STATUS_MIGRATIONS = {
    "架電中": "不在/再TEL",
    "通話済み": "資料送付",
    "アポ獲得": "訪問/面談",
    "NG": "難攻/NG",
    "不通": "不在/再TEL",
}
SALES_REP_CHOICES = [
    "藤田　慎也",
    "佐藤　正樹",
    "山田　英男",
    "野澤　松人",
    "永濵　紀仁",
    "髙杉　昌郎",
    "小島　美紀",
    "伊藤　富雄",
    "青　武伸",
    "大槻　勝己",
    "神野　訓",
    "佐藤　和憲",
    "井上　英史",
    "山根　直樹",
    "古島　健",
    "山﨑　高光",
    "曽谷　太郎",
    "関塚　良幸",
    "成田　良平",
    "佐々木　功朗",
    "梶本　秀樹",
    "甲斐　浩介",
    "橋田　知穂",
    "中西　宏文",
    "宮本　憲一朗",
    "久須美　秀樹",
    "鶴巻　学",
    "小林　雅裕",
    "吉田　和泉",
    "佐藤　元治",
    "倉光　隆尚",
    "中川　一彦",
    "中島　祐典",
    "加藤　陽介",
    "八重樫　千佳江",
    "齋藤　加奈子",
    "山根　伊佐夫",
    "藤田　光",
    "大庭　拓真",
    "米倉　和馬",
    "河地　明衣",
    "山田　優介",
    "営業２部新規予定",
    "檜田　早由歌",
    "井上　永矢",
]
SALES_DEPARTMENT_CHOICES = [
    "営業本部/営業１部",
    "営業本部/営業２部",
    "営業本部/営業３部",
    "営業本部/営業４部",
    "営業本部/営業５部",
    "営業本部/営業６部",
    "営業本部/営業７部",
]
LEGACY_ASSIGNED_TO_DEPARTMENT_MIGRATIONS = {
    "営業1部": "営業本部/営業１部",
    "営業2部": "営業本部/営業２部",
    "営業3部": "営業本部/営業３部",
    "営業4部": "営業本部/営業４部",
    "営業5部": "営業本部/営業５部",
    "営業6部": "営業本部/営業６部",
    "営業7部": "営業本部/営業７部",
}
ASSIGNED_TO_CHOICES = SALES_DEPARTMENT_CHOICES
CSV_COLUMNS = [
    "ID",
    "会社名",
    "Google検索",
    "業種",
    "都道府県",
    "市区町村",
    "従業員数",
    "営業部",
    "当社担当者",
    "状況",
    "最終アプローチ日",
    "メモ",
]

SORT_OPTIONS = {
    "id_desc": ("id", "DESC", "新着順"),
    "status": ("status", "ASC", "状況順"),
    "last_approach_date": ("last_approach_date", "DESC", "最終アプローチ日順"),
    "company_name": ("company_name", "ASC", "会社名順"),
    "employees_asc": ("employees", "ASC", "従業員数 少ない順"),
    "employees_desc": ("employees", "DESC", "従業員数 多い順"),
}

PER_PAGE = 100
COLLECTION_TARGET_PER_PREFECTURE = 10_000
COLLECTION_EXCLUDED_PREFECTURES = {"沖縄県"}
ORDINANCE_DESIGNATED_PREFECTURES = {
    "北海道",
    "宮城県",
    "埼玉県",
    "千葉県",
    "神奈川県",
    "新潟県",
    "静岡県",
    "愛知県",
    "京都府",
    "大阪府",
    "兵庫県",
    "岡山県",
    "広島県",
    "福岡県",
    "熊本県",
}
PREFECTURE_BOOST_BASELINES = {
    "北海道": 10000,
    "青森県": 10000,
    "岩手県": 10000,
    "宮城県": 10000,
    "秋田県": 10000,
    "山形県": 10000,
    "福島県": 10000,
    "茨城県": 10000,
    "栃木県": 10000,
    "群馬県": 10000,
    "埼玉県": 10000,
    "千葉県": 10000,
    "東京都": 10000,
    "神奈川県": 10000,
    "新潟県": 10100,
    "富山県": 10000,
    "石川県": 12484,
    "福井県": 10000,
    "山梨県": 10000,
    "長野県": 10000,
    "岐阜県": 10000,
    "静岡県": 10000,
    "愛知県": 10000,
    "三重県": 10000,
    "滋賀県": 10000,
    "京都府": 10000,
    "大阪府": 10000,
    "兵庫県": 10000,
    "奈良県": 10000,
    "和歌山県": 10000,
    "鳥取県": 6963,
    "島根県": 8677,
    "岡山県": 10000,
    "広島県": 10000,
    "山口県": 10000,
    "徳島県": 10000,
    "香川県": 10000,
    "愛媛県": 10000,
    "高知県": 9261,
    "福岡県": 10000,
    "佐賀県": 10000,
    "長崎県": 10000,
    "熊本県": 10000,
    "大分県": 10000,
    "宮崎県": 10000,
    "鹿児島県": 10000,
}
NORMAL_PREFECTURE_ADDITION = 5_000
ORDINANCE_PREFECTURE_TARGET = 20_000


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
        ("sales_department", "TEXT"),
        ("assigned_to", "TEXT"),
        ("last_visit_date", "TEXT"),
        ("reminder_date", "TEXT"),
        ("last_approach_date", "TEXT"),
    ]:
        db.execute(f"ALTER TABLE companies ADD COLUMN IF NOT EXISTS {column} {col_type}")

    db.execute("ALTER TABLE companies DROP COLUMN IF EXISTS contact_person")
    db.commit()

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

    if args.get("hide_unknown_employees") == "1":
        conditions.append("employees IS NOT NULL")

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


def return_to_index():
    next_url = request.form.get("next") or url_for("index")
    return redirect(next_url)


def parse_optional_int(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def get_row_value(row, *names):
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            return value
    return ""


def normalize_csv_row(row):
    status = get_row_value(row, "状況", "status") or "未架電"
    status = STATUS_MIGRATIONS.get(status, status)
    if status not in STATUS_CHOICES:
        status = "未架電"
    return {
        "company_name": get_row_value(row, "会社名", "company_name"),
        "industry": get_row_value(row, "業種", "industry"),
        "prefecture": get_row_value(row, "都道府県", "prefecture"),
        "municipality": get_row_value(row, "市区町村", "municipality"),
        "employees": parse_optional_int(get_row_value(row, "従業員数", "employees")),
        "sales_department": get_row_value(row, "営業部", "sales_department"),
        "assigned_to": get_row_value(row, "当社担当者", "assigned_to"),
        "status": status,
        "last_approach_date": get_row_value(row, "最終アプローチ日", "last_approach_date"),
        "memo": get_row_value(row, "メモ", "memo"),
    }


def find_company_id_for_csv_row(db, row):
    raw_id = get_row_value(row, "ID", "id")
    if raw_id:
        try:
            company_id = int(raw_id)
        except ValueError:
            return None
        existing = db.execute("SELECT id FROM companies WHERE id=?", (company_id,)).fetchone()
        return existing["id"] if existing else None

    company_name = get_row_value(row, "会社名", "company_name")
    prefecture = get_row_value(row, "都道府県", "prefecture")
    municipality = get_row_value(row, "市区町村", "municipality")
    if not company_name:
        return None
    existing = db.execute(
        """
        SELECT id FROM companies
        WHERE company_name=? AND COALESCE(prefecture, '')=? AND COALESCE(municipality, '')=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (company_name, prefecture, municipality),
    ).fetchone()
    return existing["id"] if existing else None


def update_company(db, company_id, values):
    db.execute(
        """
        UPDATE companies
        SET company_name=?, industry=?, prefecture=?, municipality=?, employees=?,
            sales_department=?, assigned_to=?, status=?, last_approach_date=?, memo=?
        WHERE id=?
        """,
        (
            values["company_name"],
            values["industry"],
            values["prefecture"],
            values["municipality"],
            values["employees"],
            values["sales_department"],
            values["assigned_to"],
            values["status"],
            values["last_approach_date"],
            values["memo"],
            company_id,
        ),
    )


def insert_company(db, values):
    db.execute(
        """
        INSERT INTO companies
            (company_name, industry, prefecture, municipality, employees,
             sales_department, assigned_to, status, last_approach_date, memo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            values["company_name"],
            values["industry"],
            values["prefecture"],
            values["municipality"],
            values["employees"],
            values["sales_department"],
            values["assigned_to"],
            values["status"],
            values["last_approach_date"],
            values["memo"],
        ),
    )


@app.route("/")
def index():
    db = get_db()
    where, params = build_filters(request.args)
    page = get_current_page(request.args)

    sort = request.args.get("sort", "id_desc")
    if sort not in SORT_OPTIONS:
        sort = "id_desc"
    sort_column, sort_dir, _ = SORT_OPTIONS[sort]
    nulls_position = "NULLS LAST" if sort_column == "employees" else ""

    total = db.execute(f"SELECT COUNT(*) AS cnt FROM companies {where}", params).fetchone()["cnt"]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * PER_PAGE

    rows = db.execute(
        f"""
        SELECT * FROM companies {where}
        ORDER BY {sort_column} {sort_dir} {nulls_position}, id DESC
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
        sales_department_choices=SALES_DEPARTMENT_CHOICES,
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
        insert_company(db, normalize_csv_row(request.form))
        db.commit()
        return redirect(url_for("index"))

    return render_template(
        "form.html",
        company=None,
        statuses=STATUS_CHOICES,
        industries=INDUSTRY_CHOICES,
        assigned_to_choices=ASSIGNED_TO_CHOICES,
        sales_department_choices=SALES_DEPARTMENT_CHOICES,
    )


@app.route("/edit/<int:company_id>", methods=["GET", "POST"])
def edit(company_id):
    db = get_db()
    if request.method == "POST":
        update_company(db, company_id, normalize_csv_row(request.form))
        db.commit()
        return redirect(url_for("index"))

    company = db.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
    return render_template(
        "form.html",
        company=company,
        statuses=STATUS_CHOICES,
        industries=INDUSTRY_CHOICES,
        assigned_to_choices=ASSIGNED_TO_CHOICES,
        sales_department_choices=SALES_DEPARTMENT_CHOICES,
    )


@app.route("/inline-update/<int:company_id>", methods=["POST"])
def inline_update(company_id):
    db = get_db()
    update_company(db, company_id, normalize_csv_row(request.form))
    db.commit()
    return return_to_index()


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
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        google_search_url = f"https://www.google.com/search?q={quote_plus(r['company_name'] or '')}"
        writer.writerow(
            [
                r["id"],
                r["company_name"],
                f'=HYPERLINK("{google_search_url}","検索")',
                r["industry"],
                r["prefecture"],
                r["municipality"],
                r["employees"],
                r["sales_department"],
                r["assigned_to"],
                r["status"],
                r["last_approach_date"],
                r["memo"],
            ]
        )

    csv_bytes = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(
        csv_bytes,
        mimetype="text/csv",
        as_attachment=True,
        download_name="telecall_list.csv",
    )


@app.route("/upload", methods=["POST"])
def upload_csv():
    uploaded = request.files.get("csv_file")
    if not uploaded or not uploaded.filename:
        return redirect(url_for("index", upload_message="CSVファイルを選択してください"))

    content = uploaded.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    db = get_db()
    inserted = 0
    updated = 0
    skipped = 0

    for row in reader:
        values = normalize_csv_row(row)
        if not values["company_name"]:
            skipped += 1
            continue

        company_id = find_company_id_for_csv_row(db, row)
        if company_id:
            update_company(db, company_id, values)
            updated += 1
        else:
            insert_company(db, values)
            inserted += 1

    db.commit()
    return redirect(
        url_for(
            "index",
            upload_message=f"CSV取込完了: 更新 {updated} 件 / 追加 {inserted} 件 / スキップ {skipped} 件",
        )
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


def get_collection_target(prefecture):
    if prefecture in COLLECTION_EXCLUDED_PREFECTURES:
        return None
    baseline = PREFECTURE_BOOST_BASELINES.get(prefecture, 0)
    if prefecture in ORDINANCE_DESIGNATED_PREFECTURES:
        return max(baseline, ORDINANCE_PREFECTURE_TARGET)
    return baseline + NORMAL_PREFECTURE_ADDITION


@app.route("/api/progress")
def api_progress():
    db = get_db()
    rows = db.execute(
        """
        SELECT prefecture, COUNT(*) AS cnt
        FROM companies
        WHERE prefecture IS NOT NULL AND prefecture != ''
        GROUP BY prefecture
        """
    ).fetchall()
    counts = {r["prefecture"]: int(r["cnt"]) for r in rows}
    latest = db.execute(
        """
        SELECT prefecture, municipality
        FROM companies
        WHERE prefecture IS NOT NULL AND prefecture != '' AND prefecture != '沖縄県'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    prefectures = []
    collected_total = 0
    capped_total = 0
    completed_count = 0
    for prefecture in PREFECTURE_CODES.keys():
        target = get_collection_target(prefecture)
        if target is None:
            continue
        count = counts.get(prefecture, 0)
        collected_total += count
        capped_count = min(count, target)
        capped_total += capped_count
        if count >= target:
            completed_count += 1
        baseline = PREFECTURE_BOOST_BASELINES.get(prefecture, 0)
        prefectures.append(
            {
                "name": prefecture,
                "count": count,
                "baseline": baseline,
                "added": max(count - baseline, 0),
                "target": target,
                "remaining": max(target - count, 0),
                "percent": round(capped_count / target * 100, 1) if target else 0,
                "completed": count >= target,
                "target_type": "政令指定都市県" if prefecture in ORDINANCE_DESIGNATED_PREFECTURES else "追加5000県",
            }
        )

    target_total = sum(pref["target"] for pref in prefectures)
    overall_percent = round(capped_total / target_total * 100, 1) if target_total else 0
    return jsonify(
        {
            "total": collected_total,
            "target_total": target_total,
            "overall_percent": overall_percent,
            "completed_prefectures": completed_count,
            "prefecture_total": len(prefectures),
            "mode": "都道府県追加収集",
            "description": "沖縄県・町・村を除外。通常県は開始時点から+5000社、政令指定都市がある県は合計20000社まで。",
            "excluded_prefectures": sorted(COLLECTION_EXCLUDED_PREFECTURES),
            "latest": latest or {},
            "prefectures": prefectures,
        }
    )


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
                (company_name, industry, prefecture, municipality, employees, phone,
                 department, sales_department, assigned_to, status, last_approach_date, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c["company_name"], c["industry"], c["prefecture"], c["municipality"],
                    c["employees"], c["phone"], c["department"], "",
                    assigned_to, c["status"], "", c["memo"],
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
        sales_department_choices=SALES_DEPARTMENT_CHOICES,
        using_real_api=bool(os.environ.get("GBIZINFO_API_TOKEN")),
    )


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5050)
