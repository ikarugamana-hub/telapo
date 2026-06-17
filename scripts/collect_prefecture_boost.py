#!/usr/bin/env python3
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests


BASE_URL = os.environ.get("BASE_URL", "https://telapo-946260728277.asia-northeast1.run.app")
AREA_CODES_PATH = Path(__file__).resolve().parents[1] / "area_codes.json"

EXCLUDED_PREFECTURES = {"沖縄県"}
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

NORMAL_PREFECTURE_ADDITION = 5_000
ORDINANCE_PREFECTURE_TARGET = 20_000
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
MAX_REQUEST_COUNT = 1_000
MAX_PASSES = 12
REQUEST_INTERVAL_SECONDS = 2
COUNT_TIMEOUT_SECONDS = 120
COLLECT_TIMEOUT_SECONDS = 420
MAX_RETRIES = 4


def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def load_municipalities_by_prefecture():
    area_codes = json.loads(AREA_CODES_PATH.read_text(encoding="utf-8"))
    municipalities = defaultdict(list)
    for key in area_codes["city_codes"]:
        prefecture, municipality = key.split("|", 1)
        if prefecture in EXCLUDED_PREFECTURES:
            continue
        if municipality.endswith("町") or municipality.endswith("村"):
            continue
        municipalities[prefecture].append(municipality)
    prefectures = [
        prefecture
        for prefecture in area_codes["prefecture_codes"]
        if prefecture not in EXCLUDED_PREFECTURES
    ]
    return prefectures, municipalities


def request_with_retries(method, url, **kwargs):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            wait = min(60, attempt * 5)
            log(f"retry {attempt}/{MAX_RETRIES} after {type(exc).__name__}: {exc}")
            time.sleep(wait)
    raise last_error


def get_count(prefecture=None):
    params = {"prefecture": prefecture} if prefecture else {}
    response = request_with_retries(
        "GET",
        f"{BASE_URL}/api/count",
        params=params,
        timeout=COUNT_TIMEOUT_SECONDS,
    )
    return int(response.json()["count"])


def collect(prefecture, municipality, count):
    response = request_with_retries(
        "POST",
        f"{BASE_URL}/collect",
        data={
            "industry": "その他",
            "prefecture": prefecture,
            "municipality": municipality,
            "count": str(count),
            "assigned_to": "",
        },
        allow_redirects=False,
        timeout=COLLECT_TIMEOUT_SECONDS,
    )
    return response.status_code


def get_worker_config():
    worker_total = os.environ.get("WORKER_TOTAL") or os.environ.get("CLOUD_RUN_TASK_COUNT") or "1"
    worker_index = os.environ.get("WORKER_INDEX") or os.environ.get("CLOUD_RUN_TASK_INDEX") or "0"
    return max(1, int(worker_total)), int(worker_index)


def build_targets(prefectures):
    targets = {}
    baselines = {}
    for prefecture in prefectures:
        if prefecture in PREFECTURE_BOOST_BASELINES:
            baseline = PREFECTURE_BOOST_BASELINES[prefecture]
        else:
            baseline = get_count(prefecture)
        baselines[prefecture] = baseline
        if prefecture in ORDINANCE_DESIGNATED_PREFECTURES:
            targets[prefecture] = max(baseline, ORDINANCE_PREFECTURE_TARGET)
        else:
            targets[prefecture] = baseline + NORMAL_PREFECTURE_ADDITION
    return baselines, targets


def main():
    prefectures, municipalities_by_prefecture = load_municipalities_by_prefecture()
    worker_total, worker_index = get_worker_config()
    if worker_index < 0 or worker_index >= worker_total:
        raise ValueError("WORKER_INDEX must be between 0 and WORKER_TOTAL - 1")
    prefectures = [
        prefecture
        for index, prefecture in enumerate(prefectures)
        if index % worker_total == worker_index
    ]
    baselines, targets = build_targets(prefectures)

    log(f"===== PREFECTURE BOOST START worker={worker_index + 1}/{worker_total} =====")
    log(f"total_before={get_count()}")
    log(
        "rules: Okinawa excluded, towns/villages excluded, "
        "normal prefectures baseline+5000, ordinance-designated prefectures total 20000"
    )
    for prefecture in prefectures:
        log(
            f"[{prefecture}] baseline={baselines[prefecture]} target={targets[prefecture]} "
            f"municipalities={len(municipalities_by_prefecture[prefecture])}"
        )

    for pass_no in range(1, MAX_PASSES + 1):
        log(f"===== PASS {pass_no} START worker={worker_index + 1}/{worker_total} =====")
        progressed = False

        for prefecture in prefectures:
            target = targets[prefecture]
            current = get_count(prefecture)
            if current >= target:
                log(f"[{prefecture}] skip target reached current={current} target={target}")
                continue

            municipalities = municipalities_by_prefecture[prefecture]
            if not municipalities:
                log(f"[{prefecture}] skip no eligible municipalities")
                continue

            log(f"[{prefecture}] start current={current} target={target}")
            for municipality in municipalities:
                current = get_count(prefecture)
                if current >= target:
                    log(f"[{prefecture}] target reached current={current} target={target}")
                    break

                before = current
                request_count = min(MAX_REQUEST_COUNT, target - current)
                try:
                    status = collect(prefecture, municipality, request_count)
                    after = get_count(prefecture)
                    added = after - before
                    progressed = progressed or added > 0
                    log(
                        f"[{prefecture}/{municipality}] status={status} "
                        f"requested={request_count} added={added} current={after}/{target}"
                    )
                except requests.RequestException as exc:
                    log(f"[{prefecture}/{municipality}] ERROR {type(exc).__name__}: {exc}")

                time.sleep(REQUEST_INTERVAL_SECONDS)

        log(f"===== PASS {pass_no} END total={get_count()} =====")
        if not progressed:
            log("no rows were added in this pass; stopping")
            break

        remaining = [p for p in prefectures if get_count(p) < targets[p]]
        if not remaining:
            log("all targets reached")
            break

    log(f"===== PREFECTURE BOOST END total_after={get_count()} =====")
    for prefecture in prefectures:
        log(f"[{prefecture}] final={get_count(prefecture)} target={targets[prefecture]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
