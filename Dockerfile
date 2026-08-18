FROM python:3.12-slim AS base

RUN useradd --create-home --shell /usr/sbin/nologin appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

RUN chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
# scripts/seed.py and scripts/backup.py are invoked as plain script paths
# (`python scripts/backup.py`), not via `-m` — without this, only the
# script's own directory lands on sys.path, not /app, so `import app...`
# fails even though CMD's `python -m app.main` works fine either way.
ENV PYTHONPATH=/app

CMD ["python", "-m", "app.main"]
