# FastAPI server and deployment

## Local setup

Run these commands from the repository root.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\DONWORRY-AI-POC\requirements.txt
```

Add these values to `DONWORRY-AI-POC/.env`. Never commit the real values.

```dotenv
OPENAI_API_KEY=...
OPENAI_MODEL=...
OPENAI_TIMEOUT_SECONDS=4.0
AI_SERVICE_TOKEN=...
```

Start the development server:

```powershell
python -m uvicorn api:app --app-dir .\DONWORRY-AI-POC --reload
```

Open `http://127.0.0.1:8000/docs` to inspect the API. The health check is
available at `http://127.0.0.1:8000/health`.

## Request example

```powershell
$headers = @{ "X-AI-Service-Token" = $env:AI_SERVICE_TOKEN }
$body = @{
    transactionId = "TRX_20260906_001"
    userId = "user_70s_01"
    userStatement = "검찰에서 제 계좌가 범죄에 연루됐다며 안전계좌로 송금하라고 했어요."
    riskLevel = "HIGH"
    riskSignals = @("LARGE_AMOUNT", "NEW_RECIPIENT", "LIMIT_CHANGED")
    transactionContext = @{
        amount = 3500000
        recipientName = "김철수"
        avgAmount = 650000
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/api/v1/ai/analyze" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body
```

`transactionId`, `userId`, `userStatement`, `riskLevel`, and `riskSignals` are
required. `transactionContext` is optional. The AI service returns `transactionId`
unchanged for backend request tracing. User and transaction identifiers and the
recipient name are not sent to the external model.

## Docker

Build and run from the AI project directory:

```powershell
cd .\DONWORRY-AI-POC
docker build -t donworry-ai .
docker run --rm -p 8000:8000 --env-file .env donworry-ai
```

For a cloud deployment, use `DONWORRY-AI-POC` as the service root and the included
`Dockerfile`. Configure `OPENAI_API_KEY`, `OPENAI_MODEL`,
`OPENAI_TIMEOUT_SECONDS`, and `AI_SERVICE_TOKEN` in the hosting provider's secret
or environment settings. Do not put production values in the Docker image or
GitHub repository.

The public health check path is `/health`. The backend must send the shared secret
in the `X-AI-Service-Token` header when calling `/api/v1/ai/analyze`. During E2E
testing, the backend request timeout is 10 seconds. The AI client timeout defaults
to 4 seconds per model call and automatic retries are disabled.
