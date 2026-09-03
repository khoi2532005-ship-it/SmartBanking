# Build .NET service in a build stage and publish as self-contained linux-x64
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS dotnet-build
WORKDIR /src

# Copy the SmartBanking.Service project for restore and publish
COPY src/SmartBanking.Service/SmartBanking.Service/ ./src/SmartBanking.Service/SmartBanking.Service/
RUN dotnet restore src/SmartBanking.Service/SmartBanking.Service/SmartBanking.Service.csproj
RUN dotnet publish src/SmartBanking.Service/SmartBanking.Service/SmartBanking.Service.csproj -c Release -r linux-x64 --self-contained true -o /publish

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
COPY loans-and-credit/database/requirements.txt database-requirements.txt
COPY loans-and-credit/backend/ backend/
COPY loans-and-credit/database/ database/
COPY loans-and-credit/frontend/ frontend/
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
    "# Give the DB a moment to start" \
    "sleep 1" \
    "# Start the .NET self-contained app (executable produced by publish)" \
    "/opt/smartbanking/SmartBanking.Service --urls=http://0.0.0.0:5260" \
    > /start.sh \
    && chmod +x /start.sh

EXPOSE 5001 5012 3002 5260

ENTRYPOINT ["/start.sh"]