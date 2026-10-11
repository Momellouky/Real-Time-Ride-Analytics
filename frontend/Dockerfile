FROM node:22-bookworm-slim AS dependencies
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM dependencies AS test
COPY . .
CMD ["npm", "test"]

FROM test AS build
ARG VITE_DASHBOARD_POLL_INTERVAL_MS=2000
ENV VITE_DASHBOARD_POLL_INTERVAL_MS=$VITE_DASHBOARD_POLL_INTERVAL_MS
RUN npm run build

FROM nginx:1.28-alpine AS web
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
