FROM node:22-alpine AS ui
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/app /app/backend/app
COPY --from=ui /src/frontend/dist /app/frontend/dist
RUN useradd --uid 10001 --create-home sepehr && mkdir -p /app/backend/data && chown sepehr:sepehr /app/backend/data
USER sepehr
EXPOSE 8000
CMD ["python","-m","uvicorn","app.main:app","--app-dir","/app/backend","--host","0.0.0.0","--port","8000","--workers","1"]
