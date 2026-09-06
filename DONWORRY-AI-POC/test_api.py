import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from api import app, get_ai_runtime


SERVICE_TOKEN = "test-service-token"
HEADERS = {"X-AI-Service-Token": SERVICE_TOKEN}
ENDPOINT = "/api/v1/ai/analyze"


def valid_request() -> dict:
    return {
        "transactionId": "TRX_20260906_001",
        "userId": "user_70s_01",
        "userStatement": "검찰에서 안전계좌로 송금하라고 했어요.",
        "riskLevel": "HIGH",
        "riskSignals": ["LARGE_AMOUNT", "NEW_RECIPIENT", "LIMIT_CHANGED"],
        "transactionContext": {
            "amount": 3_500_000,
            "recipientName": "김철수",
            "avgAmount": 650_000,
        },
    }


def successful_result() -> dict:
    return {
        "suspectedScamPattern": "AUTHORITY_IMPERSONATION",
        "impersonatedAuthority": "검찰",
        "detectedContexts": [
            "AUTHORITY_IMPERSONATION",
            "SAFE_ACCOUNT_REQUEST",
        ],
        "claim": "",
        "requestedAction": "안전계좌 송금 요구",
        "summary": "검찰 관계자라고 주장하며 안전계좌 송금을 요구함",
        "analysisStatus": "SUCCESS",
        "errorCode": None,
        "explanation": {
            "status": "GENERATED",
            "text": "기관 관계자를 주장하며 송금을 요구한 정황은 확인이 필요합니다.",
            "errorCode": None,
            "sources": [
                {
                    "id": "SOURCE_ID",
                    "publisher": "금융위원회",
                    "title": "보이스피싱 피해예방 사례",
                    "url": "https://example.com/source",
                    "publishedAt": "2026-08-20",
                    "section": "피해예방 사례",
                    "note": "원문 요약",
                }
            ],
        },
        "actionGuidance": {
            "reasonCode": "CONTEXT_REQUIRES_CHECK",
            "recommendedActions": [
                {
                    "code": "STOP_TRANSFER",
                    "label": "송금 즉시 중단",
                    "description": "해당 계좌로의 송금을 즉시 중지하세요.",
                },
                {
                    "code": "HANG_UP",
                    "label": "통화 종료",
                    "description": "의심스러운 전화나 문자를 즉시 끊으세요.",
                },
            ],
        },
    }


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.runtime_client = Mock()
        app.dependency_overrides[get_ai_runtime] = lambda: (
            self.runtime_client,
            "test-model",
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    def post(self, payload=None, headers=HEADERS):
        with patch.dict("os.environ", {"AI_SERVICE_TOKEN": SERVICE_TOKEN}):
            return self.client.post(
                ENDPOINT,
                headers=headers,
                json=valid_request() if payload is None else payload,
            )

    def test_health_does_not_require_authentication_or_openai(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.runtime_client.responses.create.assert_not_called()

    def test_openapi_documents_actual_status_codes_and_examples(self):
        schema = app.openapi()
        responses = schema["paths"][ENDPOINT]["post"]["responses"]
        self.assertEqual(set(responses), {"200", "400", "401", "500", "503"})
        example = schema["components"]["schemas"]["AnalyzeResponse"]["example"]
        self.assertEqual(example["phishingType"], "AUTHORITY_IMPERSONATION")
        self.assertIsNone(example["errorCode"])

    def test_analyze_returns_agreed_output_contract(self):
        with patch("api.analyze_and_explain", return_value=successful_result()) as analyze:
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "transactionId": "TRX_20260906_001",
            "analysisStatus": "SUCCESS",
            "errorCode": None,
            "phishingType": "AUTHORITY_IMPERSONATION",
            "detectedContexts": [
                "AUTHORITY_IMPERSONATION",
                "SAFE_ACCOUNT_REQUEST",
            ],
            "explanation": "기관 관계자를 주장하며 송금을 요구한 정황은 확인이 필요합니다.",
            "actionGuidance": [
                {
                    "code": "STOP_TRANSFER",
                    "label": "송금 즉시 중단",
                    "description": "해당 계좌로의 송금을 즉시 중지하세요.",
                },
                {
                    "code": "HANG_UP",
                    "label": "통화 종료",
                    "description": "의심스러운 전화나 문자를 즉시 끊으세요.",
                },
            ],
            "sources": [
                {
                    "publisher": "금융위원회",
                    "title": "보이스피싱 피해예방 사례",
                    "url": "https://example.com/source",
                    "publishedAt": "2026-08-20",
                }
            ],
        })
        analyze.assert_called_once_with(
            self.runtime_client,
            "test-model",
            "검찰에서 안전계좌로 송금하라고 했어요.",
            backend_context={
                "riskLevel": "HIGH",
                "riskSignals": [
                    "LARGE_AMOUNT",
                    "NEW_RECIPIENT",
                    "LIMIT_CHANGED",
                ],
                "transactionContext": {
                    "amount": 3_500_000,
                    "avgAmount": 650_000,
                },
            },
        )

    def test_identifiers_and_recipient_name_are_not_sent_to_model(self):
        with patch("api.analyze_and_explain", return_value=successful_result()) as analyze:
            self.post()
        _, kwargs = analyze.call_args
        serialized = str(kwargs["backend_context"])
        self.assertNotIn("TRX_20260906_001", serialized)
        self.assertNotIn("user_70s_01", serialized)
        self.assertNotIn("김철수", serialized)

    def test_missing_required_fields_return_400(self):
        required = [
            "transactionId",
            "userId",
            "userStatement",
            "riskLevel",
            "riskSignals",
        ]
        for field in required:
            with self.subTest(field=field):
                payload = valid_request()
                payload.pop(field)
                response = self.post(payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"], "Invalid request")

    def test_invalid_or_duplicate_risk_values_return_400(self):
        candidates = [
            {"riskLevel": "CRITICAL"},
            {"riskSignals": ["UNKNOWN_SIGNAL"]},
            {"riskSignals": ["LARGE_AMOUNT", "LARGE_AMOUNT"]},
        ]
        for change in candidates:
            with self.subTest(change=change):
                response = self.post({**valid_request(), **change})
                self.assertEqual(response.status_code, 400)

    def test_blank_statement_and_unknown_fields_return_400(self):
        for payload in (
            {**valid_request(), "userStatement": "   "},
            {**valid_request(), "unexpected": True},
        ):
            with self.subTest(payload=payload):
                response = self.post(payload)
                self.assertEqual(response.status_code, 400)
        self.runtime_client.responses.create.assert_not_called()

    def test_internal_parse_error_uses_agreed_error_code(self):
        result = successful_result()
        result["explanation"] = {
            "status": "FAILED",
            "text": "상황을 분석하지 못했습니다.",
            "errorCode": "INVALID_RESPONSE",
            "sources": [],
        }
        result["actionGuidance"] = {
            "reasonCode": "ANALYSIS_UNAVAILABLE",
            "recommendedActions": [],
        }
        with patch("api.analyze_and_explain", return_value=result):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["analysisStatus"], "FAILED")
        self.assertEqual(response.json()["errorCode"], "AI_PARSE_ERROR")

    def test_analyze_requires_service_token(self):
        response = self.post(headers={})
        self.assertEqual(response.status_code, 401)

    def test_analyze_fails_closed_when_token_is_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            response = self.client.post(ENDPOINT, headers=HEADERS, json=valid_request())
        self.assertEqual(response.status_code, 503)

    def test_analyze_returns_service_unavailable_when_ai_is_not_configured(self):
        app.dependency_overrides.pop(get_ai_runtime)
        with patch.dict("os.environ", {"AI_SERVICE_TOKEN": SERVICE_TOKEN}, clear=True):
            response = self.client.post(ENDPOINT, headers=HEADERS, json=valid_request())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "AI runtime is not configured")


if __name__ == "__main__":
    unittest.main()
