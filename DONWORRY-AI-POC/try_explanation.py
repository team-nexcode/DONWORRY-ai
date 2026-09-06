import json
from pathlib import Path

from dotenv import load_dotenv

from ai_client import create_client_from_env, get_model_from_env
from explanation_client import analyze_and_explain


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    statement = input("상대가 한 말과 요구한 행동을 입력하세요: ")
    with create_client_from_env() as client:
        result = analyze_and_explain(client, get_model_from_env(), statement)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n설명:", result["explanation"]["text"])
    print("\n권장 행동:")
    actions = result["actionGuidance"]["recommendedActions"]
    if not actions:
        print("AI가 추가로 제안할 행동은 없습니다. 이는 송금 허용이나 안전 보장이 아닙니다.")
    for action in actions:
        print(f"- {action['label']}: {action['description']}")
    if result["explanation"]["status"] == "FAILED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
