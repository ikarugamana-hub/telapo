#!/usr/bin/env python3
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests


BASE_URL = "https://telapo-946260728277.asia-northeast1.run.app"
COLLECT_API_TOKEN = os.environ.get("COLLECT_API_TOKEN", "")
AREA_CODES_PATH = Path(__file__).resolve().parents[1] / "area_codes.json"
TARGET_PER_PREFECTURE = 10_000
MAX_PASSES = 10
REQUEST_INTERVAL_SECONDS = 2
COUNT_TIMEOUT_SECONDS = 120
COLLECT_TIMEOUT_SECONDS = 330
MAX_RETRIES = 4
RETRYABLE_STATUS_CODES = {408, 429}


def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def load_municipalities_by_prefecture():
    area_codes = json.loads(AREA_CODES_PATH.read_text(encoding="utf-8"))
    municipalities = defaultdict(list)
    for key in area_codes["city_codes"]:
        prefecture, municipality = key.split("|", 1)
        municipalities[prefecture].append(municipality)
    return list(area_codes["prefecture_codes"].keys()), municipalities


def request_with_retries(method, url, **kwargs):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else None
            retryable = status is None or status in RETRYABLE_STATUS_CODES or status >= 500
            if not retryable or attempt == MAX_RETRIES:
                break
            wait = min(60, attempt * 5)
            log(f"retry {attempt}/{MAX_RETRIES} after {type(exc).__name__}: {exc}")
            time.sleep(wait)
    raise last_error


def is_permanent_http_error(exc):
    if exc.response is None:
        return False
    status = exc.response.status_code
    return 400 <= status < 500 and status not in RETRYABLE_STATUS_CODES


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
        headers={"X-Collect-Token": COLLECT_API_TOKEN},
        allow_redirects=False,
        timeout=COLLECT_TIMEOUT_SECONDS,
    )
    return response.status_code


def main():
    if not COLLECT_API_TOKEN:
        raise RuntimeError("COLLECT_API_TOKEN is required")
    prefectures, municipalities_by_prefecture = load_municipalities_by_prefecture()
    log("===== RESUME START =====")
    log(f"total_before={get_count()}")

    for pass_no in range(1, MAX_PASSES + 1):
        log(f"===== PASS {pass_no} START =====")
        progressed = False

        for prefecture in prefectures:
            current = get_count(prefecture)
            municipalities = municipalities_by_prefecture[prefecture]
            log(
                f"[{prefecture}] start "
                f"(current={current}, target={TARGET_PER_PREFECTURE}, municipalities={len(municipalities)})"
            )

            if current >= TARGET_PER_PREFECTURE:
                log(f"[{prefecture}] skip target reached")
                continue

            for municipality in municipalities:
                current = get_count(prefecture)
                if current >= TARGET_PER_PREFECTURE:
                    log(f"[{prefecture}] target reached (current={current})")
                    break

                request_count = min(1000, TARGET_PER_PREFECTURE - current)
                try:
                    status = collect(prefecture, municipality, request_count)
                    progressed = True
                    log(
                        f"[{prefecture}/{municipality}] status={status} "
                        f"(count_before={current}, requested={request_count})"
                    )
                except requests.HTTPError as exc:
                    if is_permanent_http_error(exc):
                        raise
                    log(f"[{prefecture}/{municipality}] ERROR {type(exc).__name__}: {exc}")
                    raise
                except requests.RequestException as exc:
                    log(f"[{prefecture}/{municipality}] ERROR {type(exc).__name__}: {exc}")
                    raise

                time.sleep(REQUEST_INTERVAL_SECONDS)

        total = get_count()
        log(f"===== PASS {pass_no} END total={total} =====")
        if not progressed:
            log("no progress candidates remained; stopping")
            break

    log(f"===== RESUME END total_after={get_count()} =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
