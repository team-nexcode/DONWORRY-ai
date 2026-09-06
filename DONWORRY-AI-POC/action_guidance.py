def clarification_description(result: dict) -> str:
    missing_authority = not result.get("impersonatedAuthority")
    missing_action = not result.get("requestedAction")
    if missing_authority and not missing_action:
        return "상대가 누구라고 했는지 알려주세요."
    if missing_action and not missing_authority:
        return "상대가 어떤 행동을 요구했는지 알려주세요."
    return "상대가 누구라고 했고 어떤 행동을 요구했는지 알려주세요."


def build_action_guidance(result: dict) -> dict:
    """Select advisory actions; never authorize or execute a transaction."""
    explanation = result.get("explanation", {})
    analysis_status = result.get("analysisStatus")
    explanation_status = explanation.get("status")
    if result.get("errorCode") == "INVALID_INPUT":
        reason = "INPUT_REQUIRED"
        codes = ["EDIT_STATEMENT"]
    elif analysis_status != "SUCCESS" or explanation_status == "FAILED":
        reason = "ANALYSIS_UNAVAILABLE"
        codes = ["STOP_TRANSFER", "CONTACT_BANK"]
    elif explanation_status == "NEEDS_CLARIFICATION":
        reason = "INFORMATION_REQUIRED"
        codes = ["EDIT_STATEMENT", "CONTACT_BANK"]
    elif explanation_status == "NO_MATCH" and not result.get("detectedContexts"):
        reason = "NO_SUPPORTED_CONTEXT"
        codes = []
    elif explanation_status == "GENERATED" and result.get("detectedContexts"):
        reason = "CONTEXT_REQUIRES_CHECK"
        codes = ["STOP_TRANSFER", "CONTACT_BANK"]
    else:
        reason = "ANALYSIS_UNAVAILABLE"
        codes = ["STOP_TRANSFER", "CONTACT_BANK"]

    actions = {
        "STOP_TRANSFER": {
            "code": "STOP_TRANSFER",
            "label": "송금 중단",
            "description": "아직 송금 전이라면 진행을 잠시 멈추고 상황을 확인해 주세요.",
        },
        "CONTACT_BANK": {
            "code": "CONTACT_BANK",
            "label": "은행 직원에게 확인",
            "description": "직접 확인한 은행 공식 연락처나 영업점을 통해 상황을 확인해 주세요.",
        },
        "EDIT_STATEMENT": {
            "code": "EDIT_STATEMENT",
            "label": "상황 다시 설명",
            "description": clarification_description(result),
        },
    }
    return {
        "reasonCode": reason,
        "recommendedActions": [actions[code] for code in codes],
    }
