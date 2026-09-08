FROM python:3.12-slim

WORKDIR /app

COPY services/transactions/database/requirements.txt database-requirements.txt
COPY services/transactions/backend/ backend/
COPY services/transactions/database/ database/
COPY services/transactions/frontend/ frontend/
COPY services/transactions/run.py run.py
COPY prompts/ prompts/

RUN pip install --no-cache-dir -r database-requirements.txt \
    && pip install --no-cache-dir -r backend/requirements.txt

RUN python database/init_db.py

EXPOSE 5005 5015 3005

CMD ["python", "run.py"]
