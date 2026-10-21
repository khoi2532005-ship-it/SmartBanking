# Budgets frontend microservice - static HTMX UI served by nginx.
# Build context: repository root (the shared theme and home page are needed)
#   docker build -f services/budgeting/frontend/Dockerfile -t budgets-frontend:1.0 .
FROM nginx:alpine

# Shared home page, CSS theme and vendored htmx go at the web root, so
# /css/styles.css and /js/htmx.min.js resolve exactly as they do in dev.
COPY shared/frontend/ /usr/share/nginx/html/

# This feature's tabs.
COPY services/budgeting/frontend/tabs/ /usr/share/nginx/html/tabs/

# /config.js and the /api/ proxy for cloud mode. These defaults keep local
# Compose as it was: the tabs call budgeting-service on port 5004 themselves.
COPY deploy/nginx/feature.conf.template /etc/nginx/templates/default.conf.template
ENV SMARTBANK_SAME_ORIGIN_API=false \
    API_UPSTREAM=http://budgeting-service:5004

EXPOSE 80
