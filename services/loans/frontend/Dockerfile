# Build context: repository root (the shared theme and home page are needed)
#   docker build -f services/loans/frontend/Dockerfile -t smartbank-loans-web:0.1 .
FROM nginx:alpine

# Shared static assets, including the CSS theme and vendored htmx.
COPY shared/frontend/ /usr/share/nginx/html/

COPY services/loans/frontend/tabs/ /usr/share/nginx/html/tabs/
COPY services/loans/frontend/index.html /usr/share/nginx/html/index.html

EXPOSE 80
