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

## BotHost + Render одновременно

Если бот работает на BotHost, а Mini App открывается на Render, локальная
SQLite-база у них разная. Для входа нужно включить синхронизацию кодов:

1. На Render добавьте `CODE_SYNC_SECRET`.
2. На BotHost добавьте такой же `CODE_SYNC_SECRET`, а `WEBAPP_URL` укажите
   точным адресом Render без завершающего `/`.
3. На BotHost запускайте этот `app.py` с `BOT_TOKEN` и `ADMIN_CODE`.
4. На Render оставьте `BOT_TOKEN` пустым, чтобы два сервера не конкурировали
   за Telegram polling.

`CODE_SYNC_SECRET` — это общий длинный случайный секрет. Его значение должно
совпадать на BotHost и Render, но не должно попадать в Git или сообщения.

## Тестирование в Replit

В текущей конфигурации Replit polling включён для тестирования. Перед запуском
остановите бота на BotHost: Telegram разрешает получать обновления только
одному процессу с одним `BOT_TOKEN`. В Replit кнопка Mini App использует
текущий Replit-домен, а синхронизация в Render отключена, поэтому код можно
проверять прямо в предпросмотре Replit.

## Render Free

В репозитории есть готовый `render.yaml`.

1. Создайте на Render новый **Blueprint** из этого репозитория.
2. Выберите бесплатный план Web Service.
3. Заполните `BOT_TOKEN`, `ADMIN_CODE` и `BOT_USERNAME`.
4. `SESSION_SECRET` Render создаст автоматически.
5. После первого запуска Render выдаст адрес вида
   `https://имя-сервиса.onrender.com`. Если `MINI_APP_URL` не задан, приложение
   само использует `RENDER_EXTERNAL_URL` и отправит этот адрес кнопкой Mini App.
6. В BotFather укажите домен Render в настройках Telegram Mini App, если
   Telegram попросит подтвердить домен.

Бесплатный Render Web Service использует эфемерный диск: SQLite-файл может
сброситься после redeploy или перезапуска. Для тестового запуска это нормально;
для постоянных пользователей позже вынесите базу в PostgreSQL или другое
постоянное хранилище.

## Данные и файлы

- `database.db` — SQLite-база с каталогом подарков без пользовательских данных.
- `static/uploads/` — изображения подарков и улучшений.
- `templates/index.html` — интерфейс Mini App.
- `app.py` — бот, Flask API, фоновые процессы и запуск приложения.

Не добавляйте токен BotFather, `SESSION_SECRET` или рабочую базу пользователей
в Git.