# Loans database microservice - exclusive owner of loans_and_credit.db.
# Build context: repository root
#   docker build -f services/loans/database/Dockerfile -t smartbank-loans-db:0.1 .
FROM python:3.12-slim

WORKDIR /app

COPY services/loans/database/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/loans/database/ ./

# Seed the database into the image so the container starts with populated
# tables. Baking it here means the image is self-contained.
RUN python init_db.py

EXPOSE 5012

CMD ["python", "app.py"]
