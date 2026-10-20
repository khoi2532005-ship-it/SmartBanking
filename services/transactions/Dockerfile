FROM python:3.12-slim

WORKDIR /app

ENV ACCOUNTS_SERVICE_URL=http://accounts:5001 \
    LLM_PROVIDER=gemini \
    GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/ \
    GEMINI_MODEL=gemini-flash-lite-latest \
    MCP_ENABLED=true \
    MCP_SERVER_URL=http://host.docker.internal:8100/mcp \
    RAG_ENABLED=true \
    RAG_SERVER_URL=http://host.docker.internal:8200 \
    MULTI_AGENT_ENABLED=true \
    MULTI_AGENT_SERVER_URL=http://host.docker.internal:8300

COPY services/transactions/database/requirements.txt database-requirements.txt
COPY services/transactions/backend/ backend/
COPY services/transactions/database/ database/
COPY services/transactions/frontend/ frontend/
COPY shared/frontend/ shared-frontend/
COPY services/transactions/run.py run.py
COPY prompts/ prompts/

RUN pip install --no-cache-dir -r database-requirements.txt \
    && pip install --no-cache-dir -r backend/requirements.txt

RUN python database/init_db.py

EXPOSE 5005 5015 3005

CMD ["python", "run.py"]
