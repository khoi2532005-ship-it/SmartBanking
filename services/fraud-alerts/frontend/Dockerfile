# Fraud frontend microservice - the Normal and AI Mode tabs served by nginx.
# Build context: repository root (the shared theme and home page are needed)
#   docker build -f services/fraud-alerts/frontend/Dockerfile -t smartbank-fraud-web:0.1 .
FROM nginx:alpine

# Shared home page, CSS theme and vendored htmx go at the web root, so
# /css/styles.css and /js/htmx.min.js resolve exactly as they do in dev.
COPY shared/frontend/ /usr/share/nginx/html/

# This feature's tabs.
COPY services/fraud-alerts/frontend/templates/tabs/ /usr/share/nginx/html/tabs/

# /config.js and the /api/ proxy for cloud mode. These defaults keep local
# Compose as it was: the tabs call fraud-service on port 5003 themselves.
COPY deploy/nginx/feature.conf.template /etc/nginx/templates/default.conf.template
ENV SMARTBANK_SAME_ORIGIN_API=false \
    API_UPSTREAM=http://fraud-service:5003

EXPOSE 80
