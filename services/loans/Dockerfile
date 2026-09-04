# Build .NET service in a build stage and publish as self-contained linux-x64
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS dotnet-build
WORKDIR /src

# Copy the SmartBanking.Service project for restore and publish
COPY services/transactions/ ./services/transactions/
RUN dotnet restore services/transactions/SmartBanking.Service/SmartBanking.Service.csproj
RUN dotnet publish services/transactions/SmartBanking.Service/SmartBanking.Service.csproj -c Release -r linux-x64 --self-contained true -o /publish

# Final image: start from python base and include published .NET app
FROM python:3.12-slim

WORKDIR /app

# Install minimal dependencies for running .NET self-contained app (ca-certificates)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget unzip \
    && rm -rf /var/lib/apt/lists/*

# Copy published .NET app from build stage
COPY --from=dotnet-build /publish /opt/smartbanking

# Copy Python application files
COPY services/loans/database/requirements.txt database-requirements.txt
COPY services/loans/backend/ backend/
COPY services/loans/database/ database/
COPY services/loans/frontend/ frontend/
COPY prompts/ prompts/

# Install Python dependencies
RUN python -m pip install --no-cache-dir -r database-requirements.txt \
    && python -m pip install --no-cache-dir flask flask-cors requests openai

# Initialize database
RUN python database/init_db.py

# Small start script to run both services
RUN printf '%s\n' "#!/bin/sh" \
    "# Start the Python database service in background" \
    "python /app/database/app.py &" \
    "# Start the Python loans API service in background" \
    "python /app/backend/app.py &" \
    "# Give the DB a moment to start" \
    "sleep 1" \
    "# Start the .NET self-contained app (executable produced by publish)" \
    "/opt/smartbanking/SmartBanking.Service --urls=http://0.0.0.0:5260" \
    > /start.sh \
    && chmod +x /start.sh

EXPOSE 5002 5012 3002 5260

ENTRYPOINT ["/start.sh"]