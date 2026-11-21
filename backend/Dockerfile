# Build from the repository root:
#   docker build -f backend/Dockerfile -t agentflow-backend .
#   docker build -f backend/Dockerfile --target test -t agentflow-backend-test .

FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
# Unprivileged user: RLIMIT_NPROC (no new processes in the sandbox) is ignored for root.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin agentflow \
    && mkdir -p /app/uploads /app/data \
    && chown agentflow:agentflow /app/uploads /app/data
COPY backend backend

# Test image: runs the whole suite as the unprivileged user, on Linux.
FROM base AS test
COPY backend/requirements-dev.txt backend/requirements-dev.txt
RUN pip install -r backend/requirements-dev.txt
COPY pytest.ini pytest.ini
USER agentflow
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
USER agentflow
ENV DATABASE_URL=sqlite:////app/data/agentflow.db \
    UPLOAD_DIR=uploads
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=3)"
# Hosts such as Render inject PORT; 8000 locally.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
