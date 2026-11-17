FROM python:3.12-slim
WORKDIR /app
ARG INSTALL_VERTEX=false
ARG INSTALL_LOCAL=false
COPY backend/requirements*.txt ./
RUN if [ "$INSTALL_LOCAL" = "true" ]; then pip install --no-cache-dir -r requirements-local.txt; elif [ "$INSTALL_VERTEX" = "true" ]; then pip install --no-cache-dir -r requirements-vertex.txt; else pip install --no-cache-dir -r requirements.txt; fi
COPY backend/ .
COPY docs/knowledge /app/knowledge
RUN useradd --create-home bridge && chown -R bridge /app
USER bridge
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
