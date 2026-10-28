# Multi-stage production build for Frontend Dashboard
# Stage 1: Build static assets
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . ./
RUN npm run build

# Stage 2: Minimal runtime Nginx container
FROM nginx:1.25-alpine

COPY --from=builder /app/dist /usr/share/nginx/html

RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chmod -R 755 /usr/share/nginx/html && \
    touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx

USER nginx

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
