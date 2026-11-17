FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-vertex.txt
COPY backend/ ./
COPY docs/knowledge ./knowledge
COPY --from=web /web/dist ./static
RUN useradd --create-home bridge && chown -R bridge /app
USER bridge
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
