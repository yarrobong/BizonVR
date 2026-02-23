#!/bin/sh
set -e

# Ждём готовности БД (до 60 сек)
echo "[entrypoint] Waiting for database..."
i=1
while [ $i -le 30 ]; do
  if python manage.py check --database default 2>/dev/null; then
    echo "[entrypoint] Database ready."
    break
  fi
  if [ $i -eq 30 ]; then
    echo "[entrypoint] ERROR: Could not connect to database after 30 attempts"
    exit 1
  fi
  echo "  Attempt $i/30: waiting 2s..."
  sleep 2
  i=$((i + 1))
done

echo "[entrypoint] Running migrations..."
python manage.py migrate --noinput
# Сборка Tailwind только если нет файла (dev с volume; в prod уже собран в образе)
if [ ! -f /app/static/css/tailwind.css ]; then
  echo "[entrypoint] Building Tailwind CSS (first run)..."
  (cd /app && npm ci --no-audit --no-fund && npm run build:css)
fi
echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput
WORKERS="${GUNICORN_WORKERS:-2}"
echo "[entrypoint] Starting Gunicorn at http://0.0.0.0:8000 (workers=$WORKERS)"
exec gunicorn --bind 0.0.0.0:8000 --workers "$WORKERS" config.wsgi:application
