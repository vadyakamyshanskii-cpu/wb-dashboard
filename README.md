# WB Дашборд

Дашборд Wildberries на Streamlit: заказы, продажи, остатки + история в PostgreSQL.

## Деплой на Railway

1. Залейте этот код в репозиторий GitHub.
2. В проекте Railway: **New → GitHub Repo** → выберите репозиторий.
3. Добавьте в проект **PostgreSQL** (New → Database → PostgreSQL). Переменная `DATABASE_URL` подключится к сервису автоматически (или добавьте ссылку на неё в Variables).
4. В сервисе дашборда → **Variables** → добавьте `WB_TOKEN` = ваш токен Wildberries (категория «Статистика»).
5. В **Settings → Networking** включите **Generate Domain**, чтобы получить публичный URL.

Старт-команда (Railway берёт из `Procfile`):

```
streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
```

## Переменные окружения

| Переменная     | Обязательна | Назначение                               |
|----------------|-------------|------------------------------------------|
| `WB_TOKEN`     | да          | Токен WB Statistics API                  |
| `DATABASE_URL` | нет         | PostgreSQL для истории (Railway даёт сам) |

## Локальный запуск

```
pip install -r requirements.txt
export WB_TOKEN=...        # Windows: set WB_TOKEN=...
streamlit run app.py
```
