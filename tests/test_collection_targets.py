import os
import unittest
from unittest.mock import Mock, patch

import collector
from collection_targets import get_collection_scope, iter_collection_scopes


class CollectionTargetTests(unittest.TestCase):
    def test_regional_targets_are_aggregate_scopes(self):
        kanto = get_collection_scope("東京都")
        kansai = get_collection_scope("大阪府")
        nagoya = get_collection_scope("愛知県")

        self.assertEqual(kanto["target"], 800_000)
        self.assertEqual(
            kanto["prefectures"],
            ("東京都", "神奈川県", "埼玉県", "千葉県"),
        )
        self.assertEqual(kansai["target"], 100_000)
        self.assertEqual(nagoya["target"], 100_000)

    def test_each_region_is_emitted_once(self):
        scopes = list(
            iter_collection_scopes(
                ["東京都", "神奈川県", "埼玉県", "千葉県", "大阪府", "京都府", "兵庫県"]
            )
        )
        self.assertEqual([scope["name"] for scope in scopes], ["関東エリア", "関西エリア"])

    def test_non_regional_targets_keep_existing_rules(self):
        self.assertEqual(get_collection_scope("青森県")["target"], 15_000)
        self.assertEqual(get_collection_scope("北海道")["target"], 20_000)


class CollectorCredentialTests(unittest.TestCase):
    def test_missing_api_token_fails_closed(self):
        with patch.object(collector, "GBIZINFO_API_TOKEN", None), patch.dict(
            os.environ, {}, clear=True
        ):
            with self.assertRaisesRegex(RuntimeError, "GBIZINFO_API_TOKEN"):
                collector.collect_companies("不明", "東京都", "千代田区", 1)

    def test_sample_data_requires_explicit_opt_in(self):
        with patch.object(collector, "GBIZINFO_API_TOKEN", None), patch.dict(
            os.environ, {"ALLOW_SAMPLE_DATA": "true"}, clear=True
        ):
            companies = collector.collect_companies("不明", "東京都", "千代田区", 1)
        self.assertEqual(len(companies), 1)

    def test_first_page_api_failure_is_propagated(self):
        failed_response = Mock()
        failed_response.raise_for_status.side_effect = __import__("requests").HTTPError("401")
        with patch.object(collector, "GBIZINFO_API_TOKEN", "invalid"), patch.object(
            collector.requests, "get", return_value=failed_response
        ):
            with self.assertRaises(__import__("requests").HTTPError):
                collector.collect_companies("不明", "東京都", "千代田区", 1)

    def test_v2_search_uses_three_digit_city_code(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"hojin-infos": []}
        with patch.object(collector, "GBIZINFO_API_TOKEN", "token"), patch.object(
            collector.requests, "get", return_value=response
        ) as get_mock:
            companies = collector.collect_companies("不明", "東京都", "千代田区", 1)
        self.assertEqual(companies, [])
        self.assertEqual(get_mock.call_args.args[0], "https://api.info.gbiz.go.jp/hojin/v2/hojin")
        self.assertEqual(get_mock.call_args.kwargs["params"]["city"], "101")


class DuplicateFilterTests(unittest.TestCase):
    def test_filters_existing_and_in_batch_duplicates(self):
        existing = [{"company_name": "既存株式会社", "memo": "法人番号:111"}]
        candidates = [
            {"company_name": "既存株式会社", "memo": "法人番号:111"},
            {"company_name": "新規株式会社", "memo": "法人番号:222"},
            {"company_name": "別名重複株式会社", "memo": "法人番号:222"},
            {"company_name": "新規株式会社", "memo": "法人番号:333"},
        ]

        filtered = collector.filter_new_companies(candidates, existing)

        self.assertEqual(filtered, [{"company_name": "新規株式会社", "memo": "法人番号:222"}])


if __name__ == "__main__":
    unittest.main()
