import unittest
from unittest.mock import patch

import requests

from scripts import collect_all_japan_resume, collect_prefecture_boost


def response(status):
    result = requests.Response()
    result.status_code = status
    result.url = "https://example.test/collect"
    return result


class RetryTests(unittest.TestCase):
    def assert_retry_behavior(self, module):
        with patch.object(module.requests, "request", side_effect=[response(429), response(200)]) as request_mock, patch.object(
            module.time, "sleep"
        ) as sleep_mock:
            result = module.request_with_retries("GET", "https://example.test")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once()

    def assert_permanent_failure_behavior(self, module):
        with patch.object(module.requests, "request", return_value=response(403)) as request_mock, patch.object(
            module.time, "sleep"
        ) as sleep_mock:
            with self.assertRaises(requests.HTTPError):
                module.request_with_retries("GET", "https://example.test")
        self.assertEqual(request_mock.call_count, 1)
        sleep_mock.assert_not_called()

    def test_boost_retries_transient_status(self):
        self.assert_retry_behavior(collect_prefecture_boost)

    def test_boost_fails_fast_on_403(self):
        self.assert_permanent_failure_behavior(collect_prefecture_boost)

    def test_resume_retries_transient_status(self):
        self.assert_retry_behavior(collect_all_japan_resume)

    def test_resume_fails_fast_on_403(self):
        self.assert_permanent_failure_behavior(collect_all_japan_resume)

    def test_redirect_is_successful(self):
        with patch.object(
            collect_prefecture_boost.requests, "request", return_value=response(302)
        ), patch.object(collect_prefecture_boost.time, "sleep") as sleep_mock:
            result = collect_prefecture_boost.request_with_retries(
                "POST", "https://example.test", allow_redirects=False
            )
        self.assertEqual(result.status_code, 302)
        sleep_mock.assert_not_called()

    def test_boost_main_propagates_exhausted_transient_failure(self):
        with patch.object(collect_prefecture_boost, "COLLECT_API_TOKEN", "secret"), patch.object(
            collect_prefecture_boost,
            "load_municipalities_by_prefecture",
            return_value=(["青森県"], {"青森県": ["青森市"]}),
        ), patch.object(collect_prefecture_boost, "get_worker_config", return_value=(1, 0)), patch.object(
            collect_prefecture_boost, "get_count", return_value=10_000
        ), patch.object(
            collect_prefecture_boost,
            "collect",
            side_effect=requests.ConnectionError("persistent failure"),
        ), patch.object(collect_prefecture_boost.time, "sleep"):
            with self.assertRaises(requests.ConnectionError):
                collect_prefecture_boost.main()

    def test_resume_main_propagates_exhausted_transient_failure(self):
        with patch.object(collect_all_japan_resume, "COLLECT_API_TOKEN", "secret"), patch.object(
            collect_all_japan_resume,
            "load_municipalities_by_prefecture",
            return_value=(["青森県"], {"青森県": ["青森市"]}),
        ), patch.object(collect_all_japan_resume, "get_count", return_value=0), patch.object(
            collect_all_japan_resume,
            "collect",
            side_effect=requests.ConnectionError("persistent failure"),
        ), patch.object(collect_all_japan_resume.time, "sleep"):
            with self.assertRaises(requests.ConnectionError):
                collect_all_japan_resume.main()


if __name__ == "__main__":
    unittest.main()
