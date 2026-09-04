import json
import os

from openai import OpenAI


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
            "description": "사용자 진술에 나온 사칭 주체. 없으면 빈 문자열.",
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
    "정황이 없으면 빈 문자열 또는 빈 배열로 반환한다."
)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Please add it to DONWORRY-AI-POC/.env")
    return value


def create_client_from_env() -> OpenAI:
    return OpenAI(api_key=require_env("OPENAI_API_KEY"))


def get_model_from_env() -> str:
    return require_env("OPENAI_MODEL")


def analyze_statement(client: OpenAI, model: str, user_statement: str) -> dict:
    if not user_statement.strip():
        raise ValueError("user_statement must not be empty")

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

    return json.loads(response.output_text)
