import json
import os

from openai import APIError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError


CONTEXT_EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "suspectedScamPattern",
        "impersonatedAuthority",
        "detectedContexts",
        "claim",
        "requestedAction",
        "summary",
    ],
    "properties": {
        "suspectedScamPattern": {
            "type": "string",
            "enum": ["AUTHORITY_IMPERSONATION", "NONE", "UNCLEAR"],
        },
        "impersonatedAuthority": {
            "type": "string",
            "description": (
                "상대방이 자신이라고 주장한 기관 또는 직책. 없으면 빈 문자열. "
                "실제 신원이 확인됐다는 의미가 아님."
            ),
        },
        "detectedContexts": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "AUTHORITY_IMPERSONATION",
                    "CRIME_INVOLVEMENT_CLAIM",
                    "SAFE_ACCOUNT_REQUEST",
                ],
            },
        },
        "claim": {
            "type": "string",
            "description": "상대방이 주장한 내용. 없으면 빈 문자열.",
        },
        "requestedAction": {
            "type": "string",
            "description": "상대방이 요구한 행동. 없으면 빈 문자열.",
        },
        "summary": {
            "type": "string",
            "description": "사용자 진술에서 확인된 정황만 바탕으로 쓴 짧은 요약.",
        },
    },
}

DEVELOPER_PROMPT = (
    "너는 DONWORRY 보이스피싱 예방 MVP의 AI POC다. "
    "사용자의 설명에서 기관사칭형 보이스피싱과 관련된 정황만 추출한다. "
    "보이스피싱이라고 확정하지 말고, 사용자가 말하지 않은 사실은 만들지 않는다. "
    "AUTHORITY_IMPERSONATION은 수법 분류 이름일 뿐 실제 사칭이 확인됐다는 뜻이 아니다. "
    "summary와 다른 문장에서는 '사칭했다'고 단정하지 말고, "
    "'기관 관계자라고 주장했다'처럼 사용자가 확인한 범위로 표현한다. "
    "정황이 없으면 빈 문자열 또는 빈 배열로 반환한다."
)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Please add it to DONWORRY-AI-POC/.env")
    return value


def create_client_from_env() -> OpenAI:
    return OpenAI(api_key=require_env("OPENAI_API_KEY"), timeout=20.0, max_retries=0)


def get_model_from_env() -> str:
    return require_env("OPENAI_MODEL")


def analyze_statement(client: OpenAI, model: str, user_statement: str) -> dict:
    if not isinstance(user_statement, str) or not user_statement.strip():
        return fallback_result("INVALID_INPUT")
    try:
        result = _extract_statement(client, model, user_statement)
    except APITimeoutError:
        return fallback_result("TIMEOUT")
    except AuthenticationError:
        return fallback_result("AUTHENTICATION_ERROR")
    except RateLimitError:
        return fallback_result("RATE_LIMIT_OR_QUOTA")
    except APIError:
        return fallback_result("API_ERROR")
    except (json.JSONDecodeError, ValueError):
        return fallback_result("INVALID_RESPONSE")
    return {**result, "analysisStatus": "SUCCESS", "errorCode": None}


def fallback_result(error_code: str) -> dict:
    return {
        "analysisStatus": "FAILED",
        "errorCode": error_code,
        "suspectedScamPattern": "UNCLEAR",
        "impersonatedAuthority": "",
        "detectedContexts": [],
        "claim": "",
        "requestedAction": "",
        "summary": (
            "상황을 분석하지 못했습니다. 이 결과는 안전하다는 뜻이 아닙니다. "
            "송금을 잠시 멈추고 은행 직원에게 확인해 주세요."
        ),
    }


def _validate_result(result: object) -> None:
    properties = CONTEXT_EXTRACTION_SCHEMA["properties"]
    if not isinstance(result, dict) or set(result) != set(properties):
        raise ValueError("Invalid response fields")
    for name, spec in properties.items():
        value = result[name]
        if spec["type"] == "string":
            if not isinstance(value, str):
                raise ValueError("Invalid response type")
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError("Invalid response value")
        elif not isinstance(value, list) or any(
            item not in spec["items"]["enum"] for item in value
        ):
            raise ValueError("Invalid contexts")


def _extract_statement(client: OpenAI, model: str, user_statement: str) -> dict:

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "developer",
                "content": DEVELOPER_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "아래 사용자 진술에서 발견되는 기관사칭형 보이스피싱 관련 정황을 "
                    "정해진 JSON Schema에 맞춰 추출해줘.\n\n"
                    f"사용자 진술: {user_statement}"
                ),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "donworry_context_extraction",
                "strict": True,
                "schema": CONTEXT_EXTRACTION_SCHEMA,
            }
        },
        max_output_tokens=300,
    )

    if response.status != "completed" or not response.output_text:
        raise ValueError("Response not completed or empty")
    result = json.loads(response.output_text)
    _validate_result(result)
    return result
