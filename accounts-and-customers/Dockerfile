FROM python:3.12-slim

WORKDIR /app

COPY accounts-and-customers/database/requirements.txt database-requirements.txt
COPY accounts-and-customers/backend/ backend/
COPY accounts-and-customers/database/ database/
COPY accounts-and-customers/frontend/ frontend/
COPY accounts-and-customers/run.py run.py
COPY prompts/ prompts/

RUN pip install --no-cache-dir -r database-requirements.txt \
    && pip install --no-cache-dir flask flask-cors requests openai

RUN python database/init_db.py

EXPOSE 5001 5011 3001

CMD ["python", "run.py"]
