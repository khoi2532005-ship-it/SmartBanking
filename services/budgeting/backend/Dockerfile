# Budgets backend/API microservice - business logic, cross-feature HTTP calls,
# and AI-Mode via the Gemini API (OpenAI-compatible endpoint).
# Build context: repository root (the shared prompts/ directory is needed)
#   docker build -f services/budgeting/backend/Dockerfile -t budgets-api:1.0 .
FROM python:3.12-slim

WORKDIR /app

COPY services/budgeting/backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/budgeting/backend/ ./
COPY prompts/ ./prompts/

# Overridden by docker-compose with service-name URLs. The MCP and RAG servers
# run on the host (Release 1), so containers reach them via host.docker.internal.
ENV BUDGET_DB_URL=http://budgets-db-api:5014 \
    TRANSACTIONS_SERVICE_URL=http://transactions-api:5005 \
    USE_MOCK_TRANSACTIONS=auto \
    LLM_PROVIDER=gemini \
    GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/ \
    GEMINI_MODEL=gemini-flash-lite-latest \
    MCP_ENABLED=true \
    MCP_SERVER_URL=http://host.docker.internal:8100/mcp \
    RAG_ENABLED=true \
    RAG_SERVER_URL=http://host.docker.internal:8200

EXPOSE 5004

CMD ["python", "app.py"]
