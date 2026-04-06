#!/bin/sh
set -e

echo "=== running alembic migrations ==="
alembic upgrade head

echo "=== testing python import ==="
python -c "from app.main import app; print('Import OK')"

echo "=== starting gunicorn ==="
# 1 uvicorn worker: traffic is low enough that a single worker handles it fine,
# halving RAM usage vs 2 workers.
exec gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  --workers 1 \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout 120 \
  --keep-alive 5 \
  --access-logfile -
