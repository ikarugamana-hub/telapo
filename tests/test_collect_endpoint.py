import os
import unittest
from unittest.mock import patch

os.environ["SKIP_DB_INIT"] = "1"

import app as app_module


VALID_FORM = {
    "industry": "その他",
    "prefecture": "東京都",
    "municipality": "千代田区",
    "count": "2",
}


class FakeCursor:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class FakeDb:
    def __init__(self, scope_count=799_999, existing_rows=None):
        self.scope_count = scope_count
        self.existing_rows = existing_rows or []
        self.inserted = []
        self.committed = False

    def execute(self, sql, params=()):
        if "COUNT(*)" in sql:
            return FakeCursor(row={"cnt": self.scope_count})
        if "SELECT company_name, memo" in sql:
            return FakeCursor(rows=self.existing_rows)
        return FakeCursor()

    def executemany(self, sql, rows):
        self.inserted.extend(rows)

    def commit(self):
        self.committed = True


class CollectEndpointTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def test_missing_server_token_returns_503(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post("/collect", data=VALID_FORM)
        self.assertEqual(response.status_code, 503)

    def test_invalid_token_returns_403_before_collection(self):
        with patch.dict(os.environ, {"COLLECT_API_TOKEN": "secret"}, clear=True), patch.object(
            app_module, "collect_companies"
        ) as collect_mock:
            response = self.client.post(
                "/collect", data=VALID_FORM, headers={"X-Collect-Token": "wrong"}
            )
        self.assertEqual(response.status_code, 403)
        collect_mock.assert_not_called()

    def test_invalid_request_returns_400_before_collection(self):
        with patch.dict(os.environ, {"COLLECT_API_TOKEN": "secret"}, clear=True), patch.object(
            app_module, "collect_companies"
        ) as collect_mock:
            response = self.client.post(
                "/collect",
                data={**VALID_FORM, "count": "not-a-number"},
                headers={"X-Collect-Token": "secret"},
            )
        self.assertEqual(response.status_code, 400)
        collect_mock.assert_not_called()

    def test_valid_job_request_applies_aggregate_cap(self):
        fake_db = FakeDb()
        companies = [
            {
                "company_name": "新規A",
                "industry": "不明",
                "prefecture": "東京都",
                "municipality": "千代田区",
                "employees": None,
                "phone": "",
                "department": "",
                "status": "未架電",
                "memo": "法人番号:111",
            },
            {
                "company_name": "新規B",
                "industry": "不明",
                "prefecture": "東京都",
                "municipality": "千代田区",
                "employees": None,
                "phone": "",
                "department": "",
                "status": "未架電",
                "memo": "法人番号:222",
            },
        ]
        with patch.dict(os.environ, {"COLLECT_API_TOKEN": "secret"}, clear=True), patch.object(
            app_module, "get_db", return_value=fake_db
        ), patch.object(app_module, "collect_companies", return_value=companies):
            response = self.client.post(
                "/collect",
                data=VALID_FORM,
                headers={
                    "X-Collect-Token": "secret",
                    "X-Collection-Mode": "prefecture-boost",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(fake_db.committed)
        self.assertEqual(len(fake_db.inserted), 1)

    def test_existing_companies_are_passed_to_collector(self):
        fake_db = FakeDb(
            scope_count=0,
            existing_rows=[{"company_name": "既存A", "memo": "法人番号:999"}],
        )
        with patch.dict(os.environ, {"COLLECT_API_TOKEN": "secret"}, clear=True), patch.object(
            app_module, "get_db", return_value=fake_db
        ), patch.object(app_module, "collect_companies", return_value=[]) as collect_mock:
            response = self.client.post(
                "/collect", data=VALID_FORM, headers={"X-Collect-Token": "secret"}
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(collect_mock.call_args.kwargs["exclude_names"], {"既存A"})
        self.assertEqual(collect_mock.call_args.kwargs["exclude_corporate_numbers"], {"999"})

    def test_upstream_failure_returns_502_without_lock_or_insert(self):
        fake_db = FakeDb()
        with patch.dict(os.environ, {"COLLECT_API_TOKEN": "secret"}, clear=True), patch.object(
            app_module, "get_db", return_value=fake_db
        ), patch.object(
            app_module, "collect_companies", side_effect=app_module.requests.Timeout("timeout")
        ):
            response = self.client.post(
                "/collect", data=VALID_FORM, headers={"X-Collect-Token": "secret"}
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(fake_db.inserted, [])


if __name__ == "__main__":
    unittest.main()
