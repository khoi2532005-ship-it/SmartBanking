# Shared home page - the single entry point that routes to all five feature
# frontends. Build context: repository root.
#   docker build -f shared/frontend/Dockerfile -t smartbank-home .
FROM nginx:alpine

COPY shared/frontend/ /usr/share/nginx/html/

# Serve the htmx fragments with no caching so a redeploy is picked up on the
# next click, and let a directory hit fall through to index.html.
RUN printf 'server {\n\
    listen 80;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    location /features/ { add_header Cache-Control "no-store"; }\n\
    location / { try_files $uri $uri/ /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80
