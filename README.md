# BizonVR

## Docker (локально)

```bash
make dev      # или просто make — запуск на http://localhost:8000
make up       # продакшен-режим (порт из .env PORT, по умолчанию 8001)
make migrate  # миграции
make load-data-clear   # тестовые данные (с очисткой)
make superuser         # создать админа
make logs              # логи
```

Подробнее: [DEPLOY.md](DEPLOY.md)
