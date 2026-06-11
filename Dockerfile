# Pulse — single-container deployment: React frontend + API + always-on agent.
# Stage 1 builds the frontend; stage 2 runs FastAPI, which serves the built
# app, the JSON API, the image cards, and the scheduler. The SQLite DB and
# cards live on a mounted volume (/data) so they survive redeploys.

FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /fe/dist ./frontend/dist

ENV DB_PATH=/data/agent.db \
    CARDS_DIR=/data/cards \
    BACKUPS_DIR=/data/backups \
    SCHEDULER_IN_APP=1 \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8080

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
