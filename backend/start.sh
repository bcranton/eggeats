#!/bin/sh
set -e

echo "=== running alembic migrations ==="
alembic upgrade head

echo "=== testing python import ==="
python -c "from app.main import app; print('Import OK')"

echo "=== starting gunicorn ==="
# 2 uvicorn workers: CF edge cache handles public traffic, so Railway only
# sees cache misses and admin ops — 2 workers is plenty and halves RAM usage.
exec gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout 120 \
  --keep-alive 5 \
  --access-logfile -
