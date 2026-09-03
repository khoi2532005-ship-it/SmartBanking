# Budgets backend/API microservice - business logic, cross-feature HTTP calls,
# and AI-Mode via Ollama.
# Build context: repository root (the shared prompts/ directory is needed)
#   docker build -f budgeting-and-insights/backend/Dockerfile -t budgets-api:1.0 .
FROM python:3.12-slim

WORKDIR /app

COPY budgeting-and-insights/backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY budgeting-and-insights/backend/ ./
COPY prompts/ ./prompts/

# Overridden by docker-compose with service-name URLs.
ENV BUDGET_DB_URL=http://budgets-db-api:5014 \
    TRANSACTIONS_SERVICE_URL=http://transactions-api:5005 \
    USE_MOCK_TRANSACTIONS=auto \
    OLLAMA_URL=http://ollama:11434 \
    OLLAMA_MODEL=qwen2.5:0.5b

EXPOSE 5004

CMD ["python", "app.py"]
