FROM node:22-alpine AS ui
WORKDIR /src
COPY package*.json ./
RUN npm ci
COPY . ./
RUN npm run build

FROM nginx:1.28-alpine
ENV SEPEHR_API_UPSTREAM=http://192.168.10.251:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=ui /src/dist /usr/share/nginx/html
EXPOSE 80
