FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cu128 && pip install -r /app/requirements.txt
RUN useradd --create-home --uid 10001 appuser && mkdir /models /data && chown appuser:appuser /models /data
COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY --from=ui /ui/dist/ /app/frontend/dist/
ENV PYTHONPATH=/app/backend MODEL_DIR=/models STATIC_DIR=/app/frontend/dist HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
USER appuser
EXPOSE 8080
CMD ["uvicorn","vietvoice.app:create_app","--factory","--host","0.0.0.0","--port","8080","--workers","1","--ws","websockets","--ws-max-queue","16","--ws-max-size","8192","--timeout-graceful-shutdown","45"]
