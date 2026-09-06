import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

from ai_client import analyze_statement


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.valid = {
            "suspectedScamPattern": "NONE",
            "impersonatedAuthority": "",
            "detectedContexts": [],
            "claim": "",
            "requestedAction": "",
            "summary": "No relevant context.",
        }

    def analyze(self):
        return analyze_statement(self.client, "test-model", "Test statement")

    def assert_failed(self, result, code):
        self.assertEqual(result["analysisStatus"], "FAILED")
        self.assertEqual(result["errorCode"], code)
        self.assertEqual(result["suspectedScamPattern"], "UNCLEAR")
        self.assertNotIn("secret-marker", json.dumps(result))

    def test_success_preserves_fields(self):
        self.client.responses.create.return_value = SimpleNamespace(
            status="completed", output_text=json.dumps(self.valid)
        )
        result = self.analyze()
        self.assertEqual(result["analysisStatus"], "SUCCESS")
        self.assertIsNone(result["errorCode"])
        for key, value in self.valid.items():
            self.assertEqual(result[key], value)

    def test_empty_input_skips_api(self):
        for value in ("", "  ", None):
            self.assert_failed(
                analyze_statement(self.client, "test-model", value), "INVALID_INPUT"
            )
        self.client.responses.create.assert_not_called()

    def test_api_errors(self):
        request = httpx.Request("POST", "https://example.com")
        errors = [
            (APITimeoutError(request=request), "TIMEOUT"),
            (APIConnectionError(request=request), "API_ERROR"),
            (AuthenticationError("secret-marker", response=httpx.Response(401, request=request), body=None), "AUTHENTICATION_ERROR"),
            (RateLimitError("secret-marker", response=httpx.Response(429, request=request), body={"code": "insufficient_quota"}), "RATE_LIMIT_OR_QUOTA"),
        ]
        for error, code in errors:
            with self.subTest(code=code):
                self.client.responses.create.side_effect = error
                self.assert_failed(self.analyze(), code)

    def test_invalid_responses(self):
        invalid = ["", "not json", "null", "[]", "{}"]
        invalid.extend(json.dumps({**self.valid, **change}) for change in [
            {"detectedContexts": ["UNKNOWN"]},
            {"detectedContexts": "wrong type"},
            {"claim": None},
            {"suspectedScamPattern": "SAFE"},
            {"extra": "unexpected"},
        ])
        for value in invalid:
            with self.subTest(value=value):
                self.client.responses.create.return_value = SimpleNamespace(
                    status="completed", output_text=value
                )
                self.assert_failed(self.analyze(), "INVALID_RESPONSE")

    def test_incomplete_response_rejects_valid_json(self):
        self.client.responses.create.return_value = SimpleNamespace(
            status="incomplete", output_text=json.dumps(self.valid)
        )
        self.assert_failed(self.analyze(), "INVALID_RESPONSE")


if __name__ == "__main__":
    unittest.main()
