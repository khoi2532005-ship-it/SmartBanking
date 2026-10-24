# Loans frontend microservice - the Normal and AI Mode tabs served by nginx.
# Build context: repository root (the shared theme and home page are needed)
#   docker build -f services/loans/frontend/Dockerfile -t smartbank-loans-web:0.1 .
FROM nginx:alpine

# Shared static assets, including the CSS theme and vendored htmx.
COPY shared/frontend/ /usr/share/nginx/html/

# This feature's tabs and JavaScript.
COPY services/loans/frontend/tabs/ /usr/share/nginx/html/tabs/
COPY services/loans/frontend/js/ /usr/share/nginx/html/loans-js/
COPY services/loans/frontend/index.html /usr/share/nginx/html/index.html

# /config.js and the /api/ proxy for cloud mode. These defaults keep local
# Compose as it was: the tabs call loans-service on port 5002 themselves.
COPY deploy/nginx/feature.conf.template /etc/nginx/templates/default.conf.template
ENV SMARTBANK_SAME_ORIGIN_API=false \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    API_UPSTREAM=http://loans-service:5002

EXPOSE 80
