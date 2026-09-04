import json
import os

from dotenv import load_dotenv
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


TEST_CASES = [
    {
        "name": "CASE 1 - 검찰 안전계좌",
        "statement": "검찰에서 제 계좌가 범죄에 연루됐다고 안전계좌로 돈을 보내라고 했어요.",
        "expectedContexts": [
            "AUTHORITY_IMPERSONATION",
            "CRIME_INVOLVEMENT_CLAIM",
            "SAFE_ACCOUNT_REQUEST",
        ],
    },
    {
        "name": "CASE 2 - 경찰 사건 사용",
        "statement": "경찰이라고 전화가 왔는데 제 통장이 사건에 사용됐다고 했어요.",
        "expectedContexts": [
            "AUTHORITY_IMPERSONATION",
            "CRIME_INVOLVEMENT_CLAIM",
        ],
    },
    {
        "name": "CASE 3 - 검사 안전한 계좌",
        "statement": "검사라고 하는 사람이 돈을 안전한 계좌로 잠시 옮겨놓으라고 했어요.",
        "expectedContexts": [
            "AUTHORITY_IMPERSONATION",
            "SAFE_ACCOUNT_REQUEST",
        ],
    },
    {
        "name": "CASE 4 - 친구에게 빌린 돈",
        "statement": "친구에게 빌린 돈을 갚으려고 보내는 거예요.",
        "expectedContexts": [],
    },
    {
        "name": "CASE 5 - 부모님 병원비",
        "statement": "부모님 병원비 때문에 보내는 돈이에요.",
        "expectedContexts": [],
    },
    {
        "name": "CASE 6 - 서울중앙지검 대포통장",
        "statement": "서울중앙지검이라는데 제 통장이 대포통장 사건에 연루됐대요.",
        "expectedContexts": [
            "AUTHORITY_IMPERSONATION",
            "CRIME_INVOLVEMENT_CLAIM",
        ],
    },
]


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Please add it to DONWORRY-AI-POC/.env")
    return value


def analyze_statement(client: OpenAI, model: str, user_statement: str) -> dict:
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "developer",
                "content": (
                    "너는 DONWORRY 보이스피싱 예방 MVP의 AI POC다. "
                    "사용자의 설명에서 기관사칭형 보이스피싱과 관련된 정황만 추출한다. "
                    "보이스피싱이라고 확정하지 말고, 사용자가 말하지 않은 사실은 만들지 않는다. "
                    "정황이 없으면 빈 문자열 또는 빈 배열로 반환한다."
                ),
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


def contexts_match(actual: list[str], expected: list[str]) -> bool:
    return sorted(actual) == sorted(expected)


def main() -> None:
    load_dotenv()

    api_key = require_env("OPENAI_API_KEY")
    model = require_env("OPENAI_MODEL")

    client = OpenAI(api_key=api_key)

    for test_case in TEST_CASES:
        result = analyze_statement(client, model, test_case["statement"])
        actual_contexts = result["detectedContexts"]
        expected_contexts = test_case["expectedContexts"]
        status = "PASS" if contexts_match(actual_contexts, expected_contexts) else "FAIL"

        print("=" * 60)
        print(test_case["name"])
        print(f"입력: {test_case['statement']}")
        print(f"기대 Context: {expected_contexts}")
        print(f"실제 Context: {actual_contexts}")
        print(f"결과: {status}")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
