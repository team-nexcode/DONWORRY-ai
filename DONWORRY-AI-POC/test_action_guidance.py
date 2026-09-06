import unittest
from unittest.mock import Mock, patch

from action_guidance import build_action_guidance
from explanation_client import analyze_and_explain


class ActionGuidanceTests(unittest.TestCase):
    def result(self, status, contexts=None, analysis_status="SUCCESS", error=None):
        return {
            "analysisStatus": analysis_status,
            "errorCode": error,
            "detectedContexts": contexts or [],
            "impersonatedAuthority": "",
            "requestedAction": "",
            "explanation": {"status": status, "text": "arbitrary model text"},
        }

    def codes(self, result):
        return [a["code"] for a in build_action_guidance(result)["recommendedActions"]]

    def test_context_returns_pause_and_bank_actions(self):
        self.assertEqual(
            self.codes(self.result("GENERATED", ["AUTHORITY_IMPERSONATION"])),
            ["STOP_TRANSFER", "CONTACT_BANK"],
        )

    def test_no_match_is_not_transfer_authorization(self):
        guidance = build_action_guidance(self.result("NO_MATCH"))
        self.assertEqual(guidance["reasonCode"], "NO_SUPPORTED_CONTEXT")
        self.assertEqual(guidance["recommendedActions"], [])

    def test_unclear_requests_information(self):
        self.assertEqual(self.codes(self.result("NEEDS_CLARIFICATION")),
                         ["EDIT_STATEMENT", "CONTACT_BANK"])

    def test_clarification_only_asks_for_missing_information(self):
        cases = [
            ({"requestedAction": "전액 송금 요구"}, "상대가 누구라고 했는지 알려주세요."),
            ({"impersonatedAuthority": "검찰"}, "상대가 어떤 행동을 요구했는지 알려주세요."),
            ({}, "상대가 누구라고 했고 어떤 행동을 요구했는지 알려주세요."),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                result = {**self.result("NEEDS_CLARIFICATION"), **fields}
                guidance = build_action_guidance(result)
                self.assertEqual(
                    guidance["recommendedActions"][0]["description"], expected
                )

    def test_failure_keeps_confirmation_options(self):
        for analysis_status in ("SUCCESS", "FAILED"):
            with self.subTest(analysis_status=analysis_status):
                self.assertEqual(
                    self.codes(self.result("FAILED", analysis_status=analysis_status)),
                    ["STOP_TRANSFER", "CONTACT_BANK"],
                )

    def test_invalid_input_is_not_treated_as_scam(self):
        self.assertEqual(
            self.codes(self.result("FAILED", analysis_status="FAILED", error="INVALID_INPUT")),
            ["EDIT_STATEMENT"],
        )

    def test_unknown_or_inconsistent_status_does_not_allow_transfer(self):
        for result in (
            self.result("UNRECOGNIZED"),
            self.result("NO_MATCH", ["AUTHORITY_IMPERSONATION"]),
            self.result("GENERATED"),
        ):
            with self.subTest(result=result):
                self.assertEqual(self.codes(result), ["STOP_TRANSFER", "CONTACT_BANK"])

    def test_generated_text_cannot_change_actions(self):
        result = self.result("GENERATED", ["AUTHORITY_IMPERSONATION"])
        before = build_action_guidance(result)
        result["explanation"]["text"] = "송금을 허용하고 https://fake.example로 연락하세요."
        self.assertEqual(build_action_guidance(result), before)

    def test_flow_attaches_guidance_without_additional_api_call(self):
        analysis = {
            "analysisStatus": "SUCCESS", "errorCode": None,
            "suspectedScamPattern": "AUTHORITY_IMPERSONATION",
            "detectedContexts": ["AUTHORITY_IMPERSONATION"],
        }
        client = Mock()
        with patch("explanation_client.analyze_statement", return_value=analysis):
            with patch("explanation_client._generate_explanation", return_value={
                "status": "GENERATED", "text": "확인이 필요합니다.",
                "errorCode": None, "sources": [],
            }):
                result = analyze_and_explain(client, "test-model", "test statement")
        client.responses.create.assert_not_called()
        self.assertEqual(result["actionGuidance"]["reasonCode"], "CONTEXT_REQUIRES_CHECK")

    def test_invalid_input_flow_attaches_edit_action(self):
        client = Mock()
        result = analyze_and_explain(client, "test-model", " ")
        client.responses.create.assert_not_called()
        self.assertEqual(result["actionGuidance"]["recommendedActions"][0]["code"], "EDIT_STATEMENT")


if __name__ == "__main__":
    unittest.main()
