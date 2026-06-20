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
ROOT_PATH = Path(__file__).resolve().parents[1]
AREA_CODES_PATH = ROOT_PATH / "area_codes.json"
sys.path.insert(0, str(ROOT_PATH))

from collection_targets import (  # noqa: E402
    COLLECTION_EXCLUDED_PREFECTURES,
    PREFECTURE_BOOST_BASELINES,
    iter_collection_scopes,
)

COLLECT_API_TOKEN = os.environ.get("COLLECT_API_TOKEN", "")
MAX_REQUEST_COUNT = 1_000
MAX_PASSES = 12
REQUEST_INTERVAL_SECONDS = 2
COUNT_TIMEOUT_SECONDS = 120
COLLECT_TIMEOUT_SECONDS = 420
MAX_RETRIES = 4
RETRYABLE_STATUS_CODES = {408, 429}


def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def load_municipalities_by_prefecture():
    area_codes = json.loads(AREA_CODES_PATH.read_text(encoding="utf-8"))
    municipalities = defaultdict(list)
    for key in area_codes["city_codes"]:
        prefecture, municipality = key.split("|", 1)
        if prefecture in COLLECTION_EXCLUDED_PREFECTURES:
            continue
        if municipality.endswith("町") or municipality.endswith("村"):
            continue
        municipalities[prefecture].append(municipality)
    prefectures = [
        prefecture
        for prefecture in area_codes["prefecture_codes"]
        if prefecture not in COLLECTION_EXCLUDED_PREFECTURES
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


def get_scope_count(scope):
    return sum(get_count(prefecture) for prefecture in scope["prefectures"])


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
        headers={
            "X-Collect-Token": COLLECT_API_TOKEN,
            "X-Collection-Mode": "prefecture-boost",
        },
        allow_redirects=False,
        timeout=COLLECT_TIMEOUT_SECONDS,
    )
    return response.status_code


def get_worker_config():
    worker_total = os.environ.get("WORKER_TOTAL") or os.environ.get("CLOUD_RUN_TASK_COUNT") or "1"
    worker_index = os.environ.get("WORKER_INDEX") or os.environ.get("CLOUD_RUN_TASK_INDEX") or "0"
    return max(1, int(worker_total)), int(worker_index)


def main():
    prefectures, municipalities_by_prefecture = load_municipalities_by_prefecture()
    if not COLLECT_API_TOKEN:
        raise RuntimeError("COLLECT_API_TOKEN is required")
    worker_total, worker_index = get_worker_config()
    if worker_index < 0 or worker_index >= worker_total:
        raise ValueError("WORKER_INDEX must be between 0 and WORKER_TOTAL - 1")
    scopes = [
        scope
        for index, scope in enumerate(iter_collection_scopes(prefectures))
        if index % worker_total == worker_index
    ]

    log(f"===== PREFECTURE BOOST START worker={worker_index + 1}/{worker_total} =====")
    log(f"total_before={get_count()}")
    log(
        "rules: Okinawa excluded, towns/villages excluded, "
        "normal prefectures baseline+5000, ordinance-designated prefectures total 20000, "
        "Kanto total 800000, Kansai total 100000, Nagoya total 100000"
    )
    for scope in scopes:
        baseline = sum(PREFECTURE_BOOST_BASELINES.get(p, 0) for p in scope["prefectures"])
        log(
            f"[{scope['name']}] baseline={baseline} target={scope['target']} "
            f"prefectures={','.join(scope['prefectures'])}"
        )

    for pass_no in range(1, MAX_PASSES + 1):
        log(f"===== PASS {pass_no} START worker={worker_index + 1}/{worker_total} =====")
        progressed = False

        for scope in scopes:
            target = scope["target"]
            current = get_scope_count(scope)
            if current >= target:
                log(f"[{scope['name']}] skip target reached current={current} target={target}")
                continue

            log(f"[{scope['name']}] start current={current} target={target}")
            for prefecture in scope["prefectures"]:
                municipalities = municipalities_by_prefecture[prefecture]
                if not municipalities:
                    log(f"[{prefecture}] skip no eligible municipalities")
                    continue
                for municipality in municipalities:
                    current = get_scope_count(scope)
                    if current >= target:
                        log(f"[{scope['name']}] target reached current={current} target={target}")
                        break

                    before = current
                    request_count = min(MAX_REQUEST_COUNT, target - current)
                    try:
                        status = collect(prefecture, municipality, request_count)
                        after = get_scope_count(scope)
                        added = after - before
                        progressed = progressed or added > 0
                        log(
                            f"[{prefecture}/{municipality}] status={status} "
                            f"requested={request_count} added={added} "
                            f"scope={scope['name']} current={after}/{target}"
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
                if get_scope_count(scope) >= target:
                    break

        log(f"===== PASS {pass_no} END total={get_count()} =====")
        if not progressed:
            log("no rows were added in this pass; stopping")
            break

        remaining = [scope for scope in scopes if get_scope_count(scope) < scope["target"]]
        if not remaining:
            log("all targets reached")
            break

    log(f"===== PREFECTURE BOOST END total_after={get_count()} =====")
    for scope in scopes:
        log(f"[{scope['name']}] final={get_scope_count(scope)} target={scope['target']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
