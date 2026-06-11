# Pulse — single-container deployment: React frontend + API + always-on agent
# + the Satori visual render service. Stage 1 builds the frontend and the
# render service's node_modules; stage 2 runs FastAPI (which serves the built
# app, the JSON API, the visuals, and the scheduler) and spawns the local Node
# renderer on demand. SQLite DB, cards, visuals and backups live on /data.

FROM node:20-slim AS nodebuild
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build
WORKDIR /render
COPY render/package*.json ./
RUN npm install --no-audit --no-fund --omit=dev
COPY render/ .

FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# the node BINARY only (~50MB) for the Satori render service — no npm, no
# browser; this is what keeps visuals inside the single cheap container
COPY --from=nodebuild /usr/local/bin/node /usr/local/bin/node

COPY . .
COPY --from=nodebuild /fe/dist ./frontend/dist
COPY --from=nodebuild /render ./render

ENV DB_PATH=/data/agent.db \
    CARDS_DIR=/data/cards \
    VISUALS_DIR=/data/visuals \
    BACKUPS_DIR=/data/backups \
    SCHEDULER_IN_APP=1 \
    PYTHONUNBUFFERED=1

# Persistence: attach a volume mounted at /data (Railway: service -> Attach
# Volume; docker-compose maps one in compose.yml). Railway forbids the
# Dockerfile VOLUME directive, so it is deliberately not declared here.
EXPOSE 8080

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
