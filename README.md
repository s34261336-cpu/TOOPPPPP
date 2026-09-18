# GiftFastel — Telegram Mini App

Готовый Telegram-бот и Mini App на Flask + SQLite. Основа перенесена из
переданного проекта: авторизация одноразовым кодом из бота, профиль, звёзды,
магазин подарков, инвентарь, улучшения, маркетплейс, аукционы и админ-панель.

## Запуск на BotHost

1. Загрузите этот репозиторий на GitHub или GitLab.
2. В BotHost создайте Telegram-бота и выберите Python.
3. Укажите главный файл: `app.py`.
4. Установите зависимости из `requirements.txt`.
5. Добавьте переменные окружения:

| Переменная | Обязательно | Назначение |
| --- | --- | --- |
| `BOT_TOKEN` | да | Токен из BotFather |
| `MINI_APP_URL` | да для кнопки Mini App | Публичный HTTPS-адрес этого приложения |
| `BOT_USERNAME` | нет | Username бота без символа `@`, для ссылки в интерфейсе |
| `ADMIN_CODE` | для админ-панели | Код входа администратора |
| `SESSION_SECRET` | рекомендуется | Секрет Flask-сессии |
| `DB_PATH` | нет | Путь к SQLite, по умолчанию `database.db` |

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_TOKEN` и `APP_URL` также поддерживаются как
совместимые имена переменных.

Приложение слушает порт из BotHost (или `5000`, если переменная `PORT` не
передана). Для Mini App Telegram требует публичный HTTPS-адрес. Если BotHost
не выдаёт веб-адрес для Python-процесса, оставьте бот на BotHost, а папку с
Mini App разместите на любом HTTPS-хостинге и укажите его адрес в
`MINI_APP_URL`.

## Локальный запуск

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="токен_бота"
export MINI_APP_URL="https://ваш-домен.example"
export ADMIN_CODE="ваш-код"
python app.py
```

Без `BOT_TOKEN` веб-часть запускается для локальной проверки, но Telegram
polling не включается.

## Данные и файлы

- `database.db` — SQLite-база с каталогом подарков без пользовательских данных.
- `static/uploads/` — изображения подарков и улучшений.
- `templates/index.html` — интерфейс Mini App.
- `app.py` — бот, Flask API, фоновые процессы и запуск приложения.

Не добавляйте токен BotFather, `SESSION_SECRET` или рабочую базу пользователей
в Git.