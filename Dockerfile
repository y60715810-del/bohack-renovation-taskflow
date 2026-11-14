FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TASKFLOW_HOST=0.0.0.0 \
    TASKFLOW_PORT=8774 \
    TASKFLOW_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt ./
# Optional build-only CA bundle for managed HTTPS proxies; never retained.
RUN --mount=type=secret,id=pip_ca \
    set -eu; \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check \
    && groupadd --system taskflow \
    && useradd --system --gid taskflow taskflow \
    && mkdir -p /data \
    && chown taskflow:taskflow /data
COPY --chown=taskflow:taskflow . .
USER taskflow
EXPOSE 8774
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8774/api/health', timeout=4)"
CMD ["python", "server.py"]
