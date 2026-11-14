# Build from the REPO ROOT so both backend/ and frontend/ are in the context:
#   docker build -f backend/Dockerfile -t trinetra-voiceops-ai .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/tmp/trinetra_enterprise.db \
    FRONTEND_DIR=/app/frontend

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/
COPY frontend/ /app/frontend/

RUN useradd --create-home appuser
USER appuser

# Cloud Run injects $PORT (default 8080)
EXPOSE 8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
