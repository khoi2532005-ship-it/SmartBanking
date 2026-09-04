FROM python:3.12-slim

WORKDIR /app

COPY services/accounts/database/requirements.txt database-requirements.txt
COPY services/accounts/backend/ backend/
COPY services/accounts/database/ database/
COPY services/accounts/frontend/ frontend/
COPY services/accounts/run.py run.py
COPY prompts/ prompts/

RUN pip install --no-cache-dir -r database-requirements.txt \
    && pip install --no-cache-dir flask flask-cors requests openai

RUN python database/init_db.py

EXPOSE 5001 5011 3001

CMD ["python", "run.py"]
