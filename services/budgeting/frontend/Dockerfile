# Budgets frontend microservice - static HTMX UI served by nginx.
# Build context: repository root (the shared theme and home page are needed)
#   docker build -f services/budgeting/frontend/Dockerfile -t budgets-frontend:1.0 .
FROM nginx:alpine

# Shared home page, CSS theme and vendored htmx go at the web root, so
# /css/styles.css and /js/htmx.min.js resolve exactly as they do in dev.
COPY shared/frontend/ /usr/share/nginx/html/

# This feature's tabs.
COPY services/budgeting/frontend/tabs/ /usr/share/nginx/html/tabs/

EXPOSE 80
