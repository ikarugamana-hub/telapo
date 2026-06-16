"""企業情報の自動収集モジュール。

業種・都道府県・市区町村を指定すると、その条件に合う企業候補のリストを生成する。

- GBIZINFO_API_TOKEN 環境変数が設定されている場合は gBizINFO API
  (https://info.gbiz.go.jp/) から実データを取得する。
  ※ gBizINFO は無料のAPIトークン登録が必要で、電話番号等は提供されないため
    取得できた項目のみ埋め、残りは手動で補完することを想定。
- 未設定の場合は、業種・地域に応じたサンプル企業データを自動生成する
  (デモ・動作確認用)。
"""

import json
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import requests

GBIZINFO_API_TOKEN = os.environ.get("GBIZINFO_API_TOKEN")
GBIZINFO_ENDPOINT = "https://info.gbiz.go.jp/hojin/v1/hojin"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_MESSAGES_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_INDUSTRY_CHARS = 10
ANTHROPIC_SUMMARY_WORKERS = 5

# 株式会社・有限会社・合名会社・合資会社・合同会社
GBIZINFO_CORPORATE_TYPES = "301,302,303,304,305"

_AREA_CODES_PATH = Path(__file__).parent / "area_codes.json"
with open(_AREA_CODES_PATH, encoding="utf-8") as f:
    _AREA_CODES = json.load(f)

PREFECTURE_CODES = _AREA_CODES["prefecture_codes"]
CITY_CODES = _AREA_CODES["city_codes"]

INDUSTRY_KEYWORDS = {
    "IT・ソフトウェア": ["システムズ", "ソリューションズ", "テクノロジー", "ソフト", "デジタル"],
    "製造業": ["製作所", "工業", "製造", "精機", "金属"],
    "商社": ["商事", "物産", "貿易"],
    "食品・飲食": ["フーズ", "食品", "ベーカリー", "フードサービス"],
    "建設業": ["建設", "工務店", "建築", "土木"],
    "運輸・物流": ["運輸", "物流", "ロジスティクス", "急便"],
    "医療・福祉": ["メディカル", "ケア", "ヘルスケア", "クリニック"],
    "金融・保険": ["フィナンシャル", "保険", "ファイナンス"],
    "不動産": ["不動産", "ハウジング", "エステート"],
    "小売業": ["商店", "ストア", "マーケット"],
    "農業・林業・水産業": ["農園", "アグリ", "ファーム"],
    "エネルギー": ["エネルギー", "電力", "ガス"],
    "観光・宿泊": ["観光", "リゾート", "ホテル"],
    "教育": ["教育", "アカデミー", "スクール"],
    "サービス業": ["サービス", "コンサルティング", "プランニング"],
    "その他": ["商会", "企画", "事務所"],
}

INDUSTRY_CHOICES = list(INDUSTRY_KEYWORDS.keys())

COMPANY_PREFIXES = ["株式会社", "有限会社", "合同会社"]

DEPARTMENTS = ["営業部", "総務部", "企画部", "管理部", "経営企画部", "購買部", "代表"]

# 都道府県ごとの代表的な市外局番(デモ用の電話番号生成に使用)
AREA_CODES = {
    "北海道": "011", "青森県": "017", "岩手県": "019", "宮城県": "022", "秋田県": "018",
    "山形県": "023", "福島県": "024", "茨城県": "029", "栃木県": "028", "群馬県": "027",
    "埼玉県": "048", "千葉県": "043", "東京都": "03", "神奈川県": "045", "新潟県": "025",
    "富山県": "076", "石川県": "076", "福井県": "0776", "山梨県": "055", "長野県": "026",
    "岐阜県": "058", "静岡県": "054", "愛知県": "052", "三重県": "059", "滋賀県": "077",
    "京都府": "075", "大阪府": "06", "兵庫県": "078", "奈良県": "0742", "和歌山県": "073",
    "鳥取県": "0857", "島根県": "0852", "岡山県": "086", "広島県": "082", "山口県": "083",
    "徳島県": "088", "香川県": "087", "愛媛県": "089", "高知県": "088", "福岡県": "092",
    "佐賀県": "0952", "長崎県": "095", "熊本県": "096", "大分県": "097", "宮崎県": "0985",
    "鹿児島県": "099", "沖縄県": "098",
}


def _municipality_base_name(municipality):
    """市区町村名から「市」「区」「町」「村」「郡」を除いた呼称を抜き出す。"""
    match = re.match(r"^(.+?)(市|区|町|村|郡)", municipality)
    if match:
        return match.group(1)
    return municipality


def _generate_phone(prefecture):
    area_code = AREA_CODES.get(prefecture, "03")
    local = random.randint(100, 999)
    number = random.randint(1000, 9999)
    return f"{area_code}-{local}-{number}"


def _clean_industry_label(label):
    label = re.sub(r"[\s　、。・/／]+", "", (label or "").strip().strip("「」『』\"'"))
    return label[:MAX_INDUSTRY_CHARS] if label else "業種不明"


@lru_cache(maxsize=2048)
def summarize_industry_with_claude(business_summary):
    """gBizINFOの事業概要をClaude Haikuで10文字以内の業種名に要約する。"""
    business_summary = (business_summary or "").strip()
    if not business_summary:
        return "業種不明"
    if len(business_summary) <= MAX_INDUSTRY_CHARS:
        return business_summary
    if not ANTHROPIC_API_KEY:
        return _clean_industry_label(business_summary)

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 32,
        "temperature": 0,
        "system": "あなたはB2B営業リスト用の業種分類器です。回答は日本語の業種名だけにしてください。",
        "messages": [
            {
                "role": "user",
                "content": (
                    "次の事業概要を、営業リストの「業種」欄に入れる短い業種名へ要約してください。\n"
                    "条件:\n"
                    "- 10文字以内\n"
                    "- 会社名ではなく業種名\n"
                    "- 説明文、句読点、引用符は不要\n"
                    "- 判断できない場合は「業種不明」\n\n"
                    f"事業概要: {business_summary}"
                ),
            }
        ],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    try:
        response = requests.post(
            ANTHROPIC_MESSAGES_ENDPOINT, headers=headers, json=payload, timeout=20
        )
        response.raise_for_status()
        content = response.json().get("content", [])
        if content and content[0].get("type") == "text":
            return _clean_industry_label(content[0].get("text", ""))
    except requests.RequestException:
        pass
    return _clean_industry_label(business_summary)


def generate_sample_companies(industry, prefecture, municipality, count):
    """業種・都道府県・市区町村に応じたサンプル企業データを生成する。"""
    keywords = INDUSTRY_KEYWORDS.get(industry, INDUSTRY_KEYWORDS["その他"])
    base_name = _municipality_base_name(municipality)

    companies = []
    for _ in range(count):
        keyword = random.choice(keywords)
        prefix = random.choice(COMPANY_PREFIXES)
        if random.random() < 0.5:
            company_name = f"{prefix}{base_name}{keyword}"
        else:
            company_name = f"{base_name}{keyword}{prefix}"

        companies.append(
            {
                "company_name": company_name,
                "industry": industry,
                "prefecture": prefecture,
                "municipality": municipality,
                "employees": random.choice([5, 10, 20, 30, 50, 80, 120, 200, 350, 500]),
                "phone": _generate_phone(prefecture),
                "department": random.choice(DEPARTMENTS),
                "status": "未架電",
                "memo": "自動収集(サンプルデータ)",
            }
        )
    return companies


def _fetch_gbizinfo_detail(corporate_number, headers):
    """法人番号から詳細情報(従業員数・代表者名・事業概要等)を取得する。

    取得失敗時は None を返す(基本情報のみで登録を続ける)。
    """
    try:
        response = requests.get(
            f"{GBIZINFO_ENDPOINT}/{corporate_number}", headers=headers, timeout=10
        )
        response.raise_for_status()
        infos = response.json().get("hojin-infos", [])
        return infos[0] if infos else None
    except requests.RequestException:
        return None


# 1ページあたりの取得件数(APIの上限)
GBIZINFO_PAGE_LIMIT = 100
# 1回の収集で走査するページ数の上限(これを超えて候補を探さない)
GBIZINFO_MAX_PAGES = 10
# 詳細API(従業員数等)を問い合わせる候補数の上限
GBIZINFO_DETAIL_CAP = 150
# 詳細APIの並列リクエスト数
GBIZINFO_DETAIL_WORKERS = 5


def fetch_from_gbizinfo(industry, prefecture, municipality, count, exclude_corporate_numbers=None, exclude_names=None):
    """gBizINFO APIから企業情報を取得する(要 GBIZINFO_API_TOKEN)。

    検索APIをページネーションしながら呼び出し、既に登録済みの企業
    (法人番号・会社名で判定)を除外しつつ候補を集める。法人番号ごとに
    詳細APIを並列で呼んで従業員数・代表者名・事業概要・企業URLを補完し、
    従業員数が多い企業を優先して上位 count 件を返す。
    ただし電話番号・部署・担当者部署名は gBizINFO に存在しないため空欄
    (要手動調査)とする。
    """
    exclude_corporate_numbers = exclude_corporate_numbers or set()
    exclude_names = exclude_names or set()

    prefecture_code = PREFECTURE_CODES.get(prefecture)
    city_code = CITY_CODES.get(f"{prefecture}|{municipality}")
    if prefecture_code is None or city_code is None:
        return []

    headers = {"X-hojinInfo-api-token": GBIZINFO_API_TOKEN, "Accept": "application/json"}

    candidates = []
    for page in range(1, GBIZINFO_MAX_PAGES + 1):
        params = {
            "prefecture": prefecture_code,
            "city": city_code,
            "corporate_type": GBIZINFO_CORPORATE_TYPES,
            "page": page,
            "limit": GBIZINFO_PAGE_LIMIT,
        }
        try:
            response = requests.get(GBIZINFO_ENDPOINT, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            items = response.json().get("hojin-infos", [])
        except requests.RequestException:
            # レート制限等で検索APIが失敗した場合は、それまでに集めた候補で処理を続ける
            break

        for item in items:
            corporate_number = item.get("corporate_number", "")
            name = item.get("name", "")
            if corporate_number in exclude_corporate_numbers or name in exclude_names:
                continue
            candidates.append(item)

        if len(items) < GBIZINFO_PAGE_LIMIT or len(candidates) >= count:
            break

    detail_pool = candidates[:max(count, GBIZINFO_DETAIL_CAP)]

    def _with_detail(item):
        corporate_number = item.get("corporate_number", "")
        detail = _fetch_gbizinfo_detail(corporate_number, headers) if corporate_number else None
        return (item, detail)

    if detail_pool:
        with ThreadPoolExecutor(max_workers=GBIZINFO_DETAIL_WORKERS) as executor:
            detailed = list(executor.map(_with_detail, detail_pool))
    else:
        detailed = []

    # 従業員数が判明している企業を優先(従業員数の多い順)し、不明な企業は最後に回す
    detailed.sort(key=lambda pair: pair[1].get("employee_number") if pair[1] and pair[1].get("employee_number") is not None else -1, reverse=True)

    selected = detailed[:count]
    business_summaries = {
        pair[1].get("business_summary")
        for pair in selected
        if pair[1] and pair[1].get("business_summary")
    }
    if business_summaries:
        with ThreadPoolExecutor(max_workers=ANTHROPIC_SUMMARY_WORKERS) as executor:
            industry_summaries = dict(
                zip(
                    business_summaries,
                    executor.map(summarize_industry_with_claude, business_summaries),
                )
            )
    else:
        industry_summaries = {}

    companies = []
    for item, detail in selected:
        corporate_number = item.get("corporate_number", "")

        employees = None
        department = ""
        actual_industry = "業種不明(要確認)"
        memo_parts = [f"自動収集(gBizINFO) 法人番号:{corporate_number}"]

        if detail:
            employees = detail.get("employee_number")
            department = (detail.get("representative_position") or "").strip()
            business_summary = detail.get("business_summary")
            if business_summary:
                actual_industry = industry_summaries.get(
                    business_summary, summarize_industry_with_claude(business_summary)
                )
                memo_parts.append(f"事業概要:{business_summary}")
            company_url = detail.get("company_url")
            if company_url:
                memo_parts.append(f"URL:{company_url}")

        memo_parts.append(f"検索時の指定業種:{industry}")
        memo_parts.append("※電話番号は要調査")

        companies.append(
            {
                "company_name": item.get("name", ""),
                "industry": actual_industry,
                "prefecture": prefecture,
                "municipality": municipality,
                "employees": employees,
                "phone": "",
                "department": department,
                "status": "未架電",
                "memo": " / ".join(memo_parts),
            }
        )
    return companies


def collect_companies(industry, prefecture, municipality, count, exclude_corporate_numbers=None, exclude_names=None):
    """企業情報を収集する。APIトークンがあれば実データ、無ければサンプルデータを返す。

    APIトークンが設定されている場合は実データのみを返す(該当企業が無ければ0件)。
    架空のサンプルデータで件数を埋めることはしない。
    """
    if GBIZINFO_API_TOKEN:
        try:
            return fetch_from_gbizinfo(industry, prefecture, municipality, count, exclude_corporate_numbers, exclude_names)
        except requests.RequestException:
            return []
    return generate_sample_companies(industry, prefecture, municipality, count)
