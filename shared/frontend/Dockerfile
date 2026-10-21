# Shared home page - the single entry point that routes to all five feature
# frontends. Build context: repository root.
#   docker build -f shared/frontend/Dockerfile -t smartbank-home .
FROM nginx:alpine

COPY shared/frontend/ /usr/share/nginx/html/

# Serves the htmx fragments with no caching (a redeploy is picked up on the
# next click), lets a directory hit fall through to index.html, and serves
# /config.js with the map of deployed feature frontends (empty locally).
COPY deploy/nginx/home.conf.template /etc/nginx/templates/default.conf.template
ENV SMARTBANK_FRONTENDS={}

EXPOSE 80
