# BizonVR / portal-shop — Django app (production-ready)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 \
    libffi-dev libjpeg62-turbo libopenjp2-7 libharfbuzz0b libfribidi0 \
    shared-mime-info fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Node для сборки Tailwind CSS на этапе сборки образа
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/entrypoint.sh

# Сборка Tailwind CSS в образе должна падать при ошибке, иначе легко уехать в прод без CSS.
RUN npm ci --no-audit --no-fund && npm run build:css

# Директории для статики и медиа (заполняются в entrypoint при старте)
RUN mkdir -p /app/staticfiles /app/media

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
