import os
import secrets
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_client import create_client_from_env, get_model_from_env
from explanation_client import analyze_and_explain


load_dotenv(Path(__file__).with_name(".env"))

RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]
RiskSignal = Literal["LARGE_AMOUNT", "NEW_RECIPIENT", "LIMIT_CHANGED"]
DetectedContext = Literal[
    "AUTHORITY_IMPERSONATION",
    "CRIME_INVOLVEMENT_CLAIM",
    "SAFE_ACCOUNT_REQUEST",
]
ActionCode = Literal["STOP_TRANSFER", "HANG_UP", "CONTACT_BANK", "EDIT_STATEMENT"]

app = FastAPI(
    title="DONWORRY AI API",
    version="1.0.0",
    description="기관사칭형 보이스피싱 정황 분석 API",
)


class TransactionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int | None = Field(default=None, ge=0)
    recipientName: str | None = Field(default=None, max_length=100)
    avgAmount: int | None = Field(default=None, ge=0)

    @field_validator("recipientName")
    @classmethod
    def normalize_recipient_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "transactionId": "TRX_20260906_001",
                "userId": "user_70s_01",
                "userStatement": (
                    "검찰청 검사님이 안전계좌로 피해보원금을 보관해야 한다고 했어요."
                ),
                "riskLevel": "HIGH",
                "riskSignals": [
                    "LARGE_AMOUNT",
                    "NEW_RECIPIENT",
                    "LIMIT_CHANGED",
                ],
                "transactionContext": {
                    "amount": 3_500_000,
                    "recipientName": "김철수",
                    "avgAmount": 650_000,
                },
            }
        },
    )

    transactionId: str = Field(min_length=1, max_length=100)
    userId: str = Field(min_length=1, max_length=100)
    userStatement: str = Field(min_length=1, max_length=2_000)
    riskLevel: RiskLevel
    riskSignals: list[RiskSignal]
    transactionContext: TransactionContext | None = None

    @field_validator("transactionId", "userId", "userStatement")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("riskSignals")
    @classmethod
    def risk_signals_must_be_unique(cls, value: list[RiskSignal]) -> list[RiskSignal]:
        if len(value) != len(set(value)):
            raise ValueError("riskSignals must not contain duplicates")
        return value

    def model_context(self) -> dict:
        context = {
            "riskLevel": self.riskLevel,
            "riskSignals": self.riskSignals,
        }
        if self.transactionContext is not None:
            transaction_context = self.transactionContext.model_dump(exclude_none=True)
            # Recipient names are not needed for pattern analysis and stay inside the AI service.
            transaction_context.pop("recipientName", None)
            context["transactionContext"] = transaction_context
        return context


class Source(BaseModel):
    publisher: str
    title: str
    url: str
    publishedAt: str


class ActionGuidance(BaseModel):
    code: ActionCode
    label: str
    description: str


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "transactionId": "TRX_20260906_001",
                "analysisStatus": "SUCCESS",
                "errorCode": None,
                "phishingType": "AUTHORITY_IMPERSONATION",
                "detectedContexts": [
                    "AUTHORITY_IMPERSONATION",
                    "SAFE_ACCOUNT_REQUEST",
                ],
                "explanation": (
                    "기관 관계자를 주장하며 안전계좌 송금을 요구한 정황은 "
                    "확인이 필요합니다."
                ),
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
                        "publisher": "금융위원회 (대한민국 정책브리핑 전재)",
                        "title": (
                            "금융·통신·수사 협업으로 보이스피싱 피해 신고 전에 막는다! "
                            "- 제2차 보이스피싱 근절 협의회 개최"
                        ),
                        "url": (
                            "https://m.korea.kr/briefing/pressReleaseView.do"
                            "?newsId=156774907"
                        ),
                        "publishedAt": "2026-08-20",
                    }
                ],
            }
        }
    )

    transactionId: str
    analysisStatus: Literal["SUCCESS", "FAILED"]
    errorCode: str | None
    phishingType: Literal["AUTHORITY_IMPERSONATION", "NONE", "UNCLEAR"]
    detectedContexts: list[DetectedContext]
    explanation: str
    actionGuidance: list[ActionGuidance]
    sources: list[Source]


class HealthResponse(BaseModel):
    status: Literal["ok"]


ERROR_CODES = {
    "INVALID_RESPONSE": "AI_PARSE_ERROR",
    "TIMEOUT": "AI_TIMEOUT",
    "AUTHENTICATION_ERROR": "AI_AUTHENTICATION_ERROR",
    "RATE_LIMIT_OR_QUOTA": "AI_RATE_LIMIT",
    "API_ERROR": "AI_API_ERROR",
    "KNOWLEDGE_ERROR": "KNOWLEDGE_ERROR",
    "INVALID_INPUT": "INVALID_INPUT",
}


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "location": list(item["loc"]),
            "message": item["msg"],
            "type": item["type"],
        }
        for item in error.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Invalid request", "errors": errors},
    )


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            if isinstance(operation, dict):
                operation.get("responses", {}).pop("422", None)
    schema["components"]["schemas"]["AnalyzeResponse"]["example"][
        "errorCode"
    ] = None
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


def verify_service_token(
    supplied_token: Annotated[str | None, Header(alias="X-AI-Service-Token")] = None,
) -> None:
    expected_token = os.getenv("AI_SERVICE_TOKEN")
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service authentication is not configured",
        )
    if supplied_token is None or not secrets.compare_digest(supplied_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid AI service token",
        )


def get_ai_runtime():
    try:
        model = get_model_from_env()
        client = create_client_from_env()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI runtime is not configured",
        ) from error
    try:
        yield client, model
    finally:
        client.close()


def build_api_response(transaction_id: str, result: dict) -> dict:
    explanation = result["explanation"]
    internal_error = result.get("errorCode") or explanation.get("errorCode")
    analysis_status = (
        "FAILED"
        if result.get("analysisStatus") != "SUCCESS" or explanation.get("status") == "FAILED"
        else "SUCCESS"
    )
    sources = [
        {
            "publisher": source["publisher"],
            "title": source["title"],
            "url": source["url"],
            "publishedAt": source["publishedAt"],
        }
        for source in explanation.get("sources", [])
    ]
    return {
        "transactionId": transaction_id,
        "analysisStatus": analysis_status,
        "errorCode": ERROR_CODES.get(internal_error, internal_error),
        "phishingType": result["suspectedScamPattern"],
        "detectedContexts": result["detectedContexts"],
        "explanation": explanation["text"],
        "actionGuidance": result["actionGuidance"]["recommendedActions"],
        "sources": sources,
    }


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/api/v1/ai/analyze",
    response_model=AnalyzeResponse,
    dependencies=[Depends(verify_service_token)],
    responses={
        400: {
            "description": "Required field missing or request value invalid",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid request",
                        "errors": [
                            {
                                "location": ["body", "transactionId"],
                                "message": "Field required",
                                "type": "missing",
                            }
                        ],
                    }
                }
            },
        },
        401: {
            "description": "Invalid or missing AI service token",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid AI service token"}
                }
            },
        },
        500: {"description": "Unhandled AI server error"},
        503: {
            "description": "AI service authentication or runtime not configured",
            "content": {
                "application/json": {
                    "example": {"detail": "AI runtime is not configured"}
                }
            },
        },
    },
)
def analyze(
    request: AnalyzeRequest,
    runtime=Depends(get_ai_runtime),
) -> dict:
    client, model = runtime
    result = analyze_and_explain(
        client,
        model,
        request.userStatement,
        backend_context=request.model_context(),
    )
    return build_api_response(request.transactionId, result)
