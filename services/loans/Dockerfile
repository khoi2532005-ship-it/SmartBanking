FROM python:3.12-slim

WORKDIR /app

COPY services/loans/database/requirements.txt database-requirements.txt
COPY services/loans/backend/ backend/
COPY services/loans/database/ database/
COPY services/loans/frontend/ frontend/
COPY prompts/ prompts/

RUN python -m pip install --no-cache-dir -r database-requirements.txt \
    && python -m pip install --no-cache-dir flask flask-cors requests openai

RUN python database/init_db.py

# Small start script to run both Python services
RUN printf '%s\n' "#!/bin/sh" \
    "# Start the Python database service in background" \
    "python /app/database/app.py &" \
    "# Give the DB a moment to start" \
    "sleep 1" \
    "# Start the Python loans API service in the foreground" \
    "exec python /app/backend/app.py" \
    > /start.sh \
    && chmod +x /start.sh

EXPOSE 5002 5012 3002

ENTRYPOINT ["/start.sh"]
