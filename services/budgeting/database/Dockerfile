# Budgets database microservice - exclusive owner of budgeting_and_insights.db
# Build context: repository root
#   docker build -f services/budgeting/database/Dockerfile -t budgets-db-api:1.0 .
FROM python:3.12-slim

WORKDIR /app

COPY services/budgeting/database/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/budgeting/database/ ./

# Seed the database into the image so the container starts with populated
# tables (the assessment requires at least ten records per table).
RUN python init_db.py

EXPOSE 5014

CMD ["python", "app.py"]
