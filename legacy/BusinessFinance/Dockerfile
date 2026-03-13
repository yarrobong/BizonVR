# Дешёвый деплой: Render, Railway, Fly.io
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Порт для облака (Render/Railway ожидают PORT из env)
ENV STREAMLIT_SERVER_PORT=8080
EXPOSE 8080

# PORT задаёт Render/Railway при запуске контейнера
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
