# Loans frontend microservice - the Normal and AI Mode tabs served by nginx.
# Build context: repository root (the shared theme and home page are needed)
#   docker build -f services/loans/frontend/Dockerfile -t smartbank-loans-web:0.1 .
FROM nginx:alpine

# Shared home page, CSS theme and vendored htmx go at the web root, so
# /css/styles.css and /js/htmx.min.js resolve exactly as they do in dev.
COPY shared/frontend/ /usr/share/nginx/html/

# This feature's tabs and JavaScript.
COPY services/loans/frontend/tabs/ /usr/share/nginx/html/tabs/
COPY services/loans/frontend/js/ /usr/share/nginx/html/loans-js/

EXPOSE 80
