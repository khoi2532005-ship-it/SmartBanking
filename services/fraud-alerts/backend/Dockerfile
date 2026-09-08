# Fraud backend/API microservice - detection rules, alert management and
# AI-Mode explanations via the Gemini API (OpenAI-compatible endpoint).
# Build context: repository root (the shared prompts/ directory is needed)
#   docker build -f services/fraud-alerts/backend/Dockerfile -t smartbank-fraud-api:0.1 .
FROM python:3.12-slim

WORKDIR /app

# Requirements first: a code or prompt change then reuses this layer instead
# of reinstalling from PyPI on every build.
COPY services/fraud-alerts/backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/fraud-alerts/backend/ ./

# services/prompt_loader.py walks up from its own directory looking for a
# "prompts" folder, so /app/prompts is the first candidate it finds.
COPY prompts/ ./prompts/

# Overridden by docker-compose with service-name URLs.
ENV FRAUD_DB_URL=http://fraud-database-service:5013 \
    ACCOUNTS_SERVICE_URL=http://accounts:5001 \
    TRANSACTIONS_SERVICE_URL=http://transactions:5005 \
    TRANSACTIONS_SOURCE=seed \
    LLM_PROVIDER=gemini \
    GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/ \
    GEMINI_MODEL=gemini-flash-lite-latest

EXPOSE 5003

CMD ["python", "app.py"]
