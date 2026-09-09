# Loans backend/API microservice - loan applications, repayments and
# AI-Mode explanations via the Gemini API (OpenAI-compatible endpoint).
# Build context: repository root (the shared prompts/ directory is needed)
#   docker build -f services/loans/backend/Dockerfile -t smartbank-loans-api:0.1 .
FROM python:3.12-slim

WORKDIR /app

COPY services/loans/backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/loans/backend/ ./

# services/prompt_loader.py walks up from its own directory looking for a
# "prompts" folder, so /app/prompts is the first candidate it finds.
COPY prompts/ ./prompts/

# Overridden by docker-compose with service-name URLs.
ENV DATABASE_SERVICE_URL=http://loans-database-service:5012 \
    ACCOUNTS_SERVICE_URL=http://accounts:5001 \
    LLM_PROVIDER=gemini \
    GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/ \
    GEMINI_MODEL=gemini-flash-lite-latest

EXPOSE 5002

CMD ["python", "app.py"]
