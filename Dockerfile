# PrepPilot — CPU image (text mode + prosody analytics; bring your own GPU image for Whisper/CUDA)
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY config.yaml ./
COPY --from=frontend /app/frontend/out ./frontend/out
EXPOSE 8000
ENV PREPPILOT_SERVER__HOST=0.0.0.0
# Shell form so hosts that inject their own $PORT (Render, Koyeb, Cloud Run) work;
# defaults to 8000 locally.
CMD python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
