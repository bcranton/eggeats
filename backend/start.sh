#!/bin/sh
set -e

echo "=== running alembic migrations ==="
alembic upgrade head

echo "=== testing python import ==="
python -c "from app.main import app; print('Import OK')"

echo "=== starting uvicorn ==="
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
