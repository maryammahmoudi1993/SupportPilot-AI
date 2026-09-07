# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system app \
    && adduser --system --ingroup app --home /home/app --shell /usr/sbin/nologin app \
    && mkdir -p /home/app \
    && chown app:app /home/app
ENV HOME=/home/app

WORKDIR /app

COPY . .
RUN pip install --upgrade pip && pip install -e .

RUN chmod +x /app/entrypoint.sh && chown -R app:app /app

USER app

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
# Worker count/timeouts are configurable via environment (WEB_CONCURRENCY,
# WEB_TIMEOUT_SECONDS, ...) inside config/gunicorn_conf.py itself — never
# passed as a CLI flag here, since a Gunicorn CLI flag overrides its config
# file's value and would silently ignore those settings.
CMD ["gunicorn", "config.wsgi:application", "--config", "config/gunicorn_conf.py", "--bind", "0.0.0.0:8000"]
