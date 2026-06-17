#!/usr/bin/env python3
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests


BASE_URL = "https://telapo-946260728277.asia-northeast1.run.app"
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


def build_targets(prefectures):
    targets = {}
    baselines = {}
    for prefecture in prefectures:
        current = get_count(prefecture)
        baselines[prefecture] = current
        if prefecture in ORDINANCE_DESIGNATED_PREFECTURES:
            targets[prefecture] = max(current, ORDINANCE_PREFECTURE_TARGET)
        else:
            targets[prefecture] = current + NORMAL_PREFECTURE_ADDITION
    return baselines, targets


def main():
    prefectures, municipalities_by_prefecture = load_municipalities_by_prefecture()
    baselines, targets = build_targets(prefectures)

    log("===== PREFECTURE BOOST START =====")
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
        log(f"===== PASS {pass_no} START =====")
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
