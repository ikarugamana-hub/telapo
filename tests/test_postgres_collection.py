import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

os.environ["SKIP_DB_INIT"] = "1"

import app as app_module


FORM = {
    "industry": "その他",
    "prefecture": "東京都",
    "municipality": "千代田区",
    "count": "2",
}
HEADERS = {
    "X-Collect-Token": "integration-secret",
    "X-Collection-Mode": "prefecture-boost",
}


def company(name, corporate_number):
    return {
        "company_name": name,
        "industry": "不明",
        "prefecture": "東京都",
        "municipality": "千代田区",
        "employees": None,
        "phone": "",
        "department": "",
        "status": "未架電",
        "memo": f"法人番号:{corporate_number}",
    }


@unittest.skipUnless(os.environ.get("TELAPO_TEST_POSTGRES") == "1", "PostgreSQL integration disabled")
class PostgreSQLCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["COLLECT_API_TOKEN"] = "integration-secret"
        app_module.app.config.update(TESTING=False)
        app_module.init_db()

    def setUp(self):
        connection = app_module.get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM companies")
        connection.commit()
        connection.close()

    def count_rows(self):
        connection = app_module.get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM companies")
            count = cursor.fetchone()[0]
        connection.close()
        return count

    def post(self):
        with app_module.app.test_client() as client:
            return client.post("/collect", data=FORM, headers=HEADERS).status_code

    def test_concurrent_retry_inserts_each_company_once(self):
        barrier = threading.Barrier(2)

        def collect_same_companies(*args, **kwargs):
            barrier.wait(timeout=5)
            return [company("同時A", "1001"), company("同時B", "1002")]

        with patch.object(app_module, "collect_companies", side_effect=collect_same_companies), ThreadPoolExecutor(
            max_workers=2
        ) as executor:
            statuses = list(executor.map(lambda _: self.post(), range(2)))

        self.assertEqual(statuses, [302, 302])
        self.assertEqual(self.count_rows(), 2)

    def test_concurrent_requests_do_not_exceed_scope_target(self):
        barrier = threading.Barrier(2)
        call_lock = threading.Lock()
        call_number = 0

        def collect_distinct_company(*args, **kwargs):
            nonlocal call_number
            with call_lock:
                call_number += 1
                number = call_number
            barrier.wait(timeout=5)
            return [company(f"上限{number}", f"200{number}")]

        target_scope = {
            "key": "test-scope",
            "name": "test-scope",
            "prefectures": ("東京都",),
            "target": 1,
            "target_type": "test",
        }
        with patch.object(app_module, "collect_companies", side_effect=collect_distinct_company), patch.object(
            app_module, "get_collection_scope", return_value=target_scope
        ), ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _: self.post(), range(2)))

        self.assertEqual(statuses, [302, 302])
        self.assertEqual(self.count_rows(), 1)

    def test_insert_failure_rolls_back_and_releases_lock(self):
        original_executemany = app_module.Db.executemany

        def fail_after_insert(db, sql, rows):
            original_executemany(db, sql, rows)
            raise RuntimeError("injected insert failure")

        with patch.object(app_module, "collect_companies", return_value=[company("失敗A", "3001")]), patch.object(
            app_module.Db, "executemany", fail_after_insert
        ):
            failed_status = self.post()

        self.assertEqual(failed_status, 500)
        self.assertEqual(self.count_rows(), 0)

        with patch.object(app_module, "collect_companies", return_value=[company("再試行A", "3001")]):
            retry_status = self.post()
        self.assertEqual(retry_status, 302)
        self.assertEqual(self.count_rows(), 1)


if __name__ == "__main__":
    unittest.main()
