#!/bin/sh
set -e
echo "[entrypoint] Running migrations..."
python manage.py migrate --noinput
# Сборка Tailwind только если нет файла (dev с volume; в prod уже собран в образе)
if [ ! -f /app/static/css/tailwind.css ]; then
  echo "[entrypoint] Building Tailwind CSS (first run)..."
  (cd /app && npm install 2>/dev/null && npm run build:css 2>/dev/null) || true
fi
echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput
WORKERS="${GUNICORN_WORKERS:-2}"
echo "[entrypoint] Starting Gunicorn at http://0.0.0.0:8000 (workers=$WORKERS)"
exec gunicorn --bind 0.0.0.0:8000 --workers "$WORKERS" config.wsgi:application
