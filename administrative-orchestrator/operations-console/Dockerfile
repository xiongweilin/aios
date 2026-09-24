FROM node:24-alpine AS build

ARG VITE_OPERATIONS_API_BASE_URL=/api
ARG VITE_OIDC_AUTHORITY
ARG VITE_OIDC_CLIENT_ID
ARG VITE_OIDC_SCOPE="openid profile email"

ENV VITE_OPERATIONS_API_BASE_URL=${VITE_OPERATIONS_API_BASE_URL} \
    VITE_OIDC_AUTHORITY=${VITE_OIDC_AUTHORITY} \
    VITE_OIDC_CLIENT_ID=${VITE_OIDC_CLIENT_ID} \
    VITE_OIDC_SCOPE=${VITE_OIDC_SCOPE}

WORKDIR /app
COPY package.json tsconfig.json index.html ./
COPY src ./src
RUN npm install --ignore-scripts --no-audit --no-fund \
    && npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
