#!/bin/sh
set -e

echo "=== running alembic migrations ==="
alembic upgrade head

echo "=== testing python import ==="
python -c "from app.main import app; print('Import OK')"

echo "=== starting gunicorn ==="
# 4 uvicorn workers: enough to saturate Railway's cores without
# exhausting the Postgres connection pool (4 workers × 10 pool = 40 conns).
exec gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout 120 \
  --keep-alive 5 \
  --access-logfile -
