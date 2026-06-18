# DEPLOY REPORT

Дата подготовки: 2026-06-16
Дата фактического deploy: 2026-06-18 17:29 UTC / 20:29 MSK

## Статус

Deploy выполнен на новый VPS в Латвии через терминал пользователя, потому что среда Codex не имеет исходящего SSH-доступа к серверу.

Итог: бот запущен в Docker Compose, работает в polling-режиме, контейнер `bot` находится в состоянии `healthy`.

## Git

- Branch: недоступно
- Commit hash: недоступно
- Причина: локальная рабочая папка не является Git-репозиторием, команды `git status` и `git pull origin main` возвращают `not a git repository`.

GitHub commit/push требуется выполнить отдельно после настройки репозитория и доступа.

## Сервер

- Host: `45.38.139.167`
- SSH port: `22`
- SSH user: `root`
- Путь установки: `/opt/digital_bot_tg`
- Режим работы: polling
- Webhook: отключен
- Docker network: `digital_goods_bot_net`
- PostgreSQL volume: `digital_goods_bot_postgres_data`
- Redis volume: `digital_goods_bot_redis_data`

## Архив

- Файл: `/root/digital_bot_tg_deploy_latvia_clean.tar.gz`
- SHA256: `f6d93a95ba4c04359c4bb90a9a311c3a170be11b2ddde03116230449b378bcdf`

Первый архив был заменен на clean-архив, потому что macOS добавила служебные AppleDouble-файлы `._*.py` с нулевыми байтами. Они вызывали падение Alembic с ошибкой `SyntaxError: source code string cannot contain null bytes`.

## Диагностика Перед Deploy

- Telegram API доступен напрямую: `curl -4 -I https://api.telegram.org` вернул HTTP 302.
- UFW не установлен: `ufw: command not found`.
- VPN services в выводе диагностики не обнаружены.
- Запрещенные операции с VPN, firewall, routing, reboot и shutdown не выполнялись.

## Состояние Контейнеров

Фактическое состояние после запуска:

```text
digital_bot_tg-bot-1        Up 20 seconds (healthy)
digital_bot_tg-postgres-1   Up 10 minutes (healthy)
digital_bot_tg-redis-1      Up 10 minutes (healthy)
```

Логи бота:

```text
Start polling
Run polling for bot @digitalxxx_bot id=8880342872 - 'Digital Boot'
```

Healthcheck:

```text
{"Status":"healthy","FailingStreak":0}
```

## Исправления Во Время Deploy

- Убран Telegram proxy из кода и `.env.example`.
- Создан clean-архив без `.DS_Store` и `._*`.
- В `.dockerignore` и `.gitignore` добавлены исключения для `.DS_Store` и `._*`.
- Исправлен `BOT_TOKEN` в production `.env`; проверка `getMe` вернула `ok:true`.

## Backup

Перед заменой директории создавались backup-каталоги в `/root`:

- `/root/digital_bot_tg_backup_<timestamp>`
- `/root/digital_bot_tg_backup_clean_<timestamp>`

В backup сохранялись `.env`, копия директории приложения и диагностические списки Docker/systemd, если соответствующие команды были доступны.

## Rollback

Rollback не должен затрагивать VPN, firewall и маршрутизацию.

Базовый безопасный сценарий:

```bash
cd /opt/digital_bot_tg
docker compose down
cp /root/digital_bot_tg_backup_clean_<timestamp>/.env /opt/digital_bot_tg/.env
cp -a /root/digital_bot_tg_backup_clean_<timestamp>/app_dir/. /opt/digital_bot_tg/
docker compose up -d --build
```

## Обновление

Для будущего обновления:

1. Собрать новый clean-архив без macOS-служебных файлов.
2. Загрузить архив на сервер.
3. Создать backup текущей `/opt/digital_bot_tg`.
4. Остановить только контейнер `bot`.
5. Заменить код, сохранить production `.env`.
6. Выполнить `docker compose build --no-cache bot`.
7. Выполнить `docker compose up -d --force-recreate bot`.
8. Проверить `docker compose ps` и `docker compose logs --tail=200 bot`.
