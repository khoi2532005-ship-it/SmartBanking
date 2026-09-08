# Fraud database microservice - exclusive owner of fraud.db.
# Build context: repository root
#   docker build -f services/fraud-alerts/database/Dockerfile -t smartbank-fraud-db:0.1 .
FROM python:3.12-slim

WORKDIR /app

COPY services/fraud-alerts/database/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/fraud-alerts/database/ ./

# Seed the database into the image so the container starts with populated
# tables (the assessment requires at least ten records per table). Baking it
# here means the image is self-contained: it no longer needs the named volume
# to hold seed data, which is what makes a cloud deployment possible.
RUN python init_db.py

EXPOSE 5013

CMD ["python", "app.py"]
