FROM python:3.12-slim

WORKDIR /app

COPY loans-and-credit/database/requirements.txt database-requirements.txt
COPY loans-and-credit/backend/ backend/
COPY loans-and-credit/database/ database/
COPY loans-and-credit/frontend/ frontend/
COPY loans-and-credit/run.py run.py
COPY prompts/ prompts/

RUN pip install --no-cache-dir -r database-requirements.txt \
    && pip install --no-cache-dir flask flask-cors requests openai

RUN python database/init_db.py

EXPOSE 5001 5012 8080

CMD ["python", "run.py"]
