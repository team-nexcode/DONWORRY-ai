import json
from pathlib import Path

from dotenv import load_dotenv

from ai_client import analyze_statement, create_client_from_env, get_model_from_env


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


def contexts_match(actual: list[str], expected: list[str]) -> bool:
    return sorted(actual) == sorted(expected)


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))

    client = create_client_from_env()
    model = get_model_from_env()

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
