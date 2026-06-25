# Production-ready Telegram-бот для продажи цифровых товаров

Бот продает уникальные цифровые строки: ключи, промокоды, токены, аккаунты, доступы. После успешной оплаты через Telegram Payments или Platega он атомарно выдает свободные коды выбранного товара.

## Стек

- Python 3.11+
- aiogram 3.x
- PostgreSQL
- SQLAlchemy 2.x async
- Alembic
- Redis
- Docker / Docker Compose
- Telegram Payments / Platega

## Ключевая защита продажи

- Каждый заказ получает HMAC-подписанный `payment_payload`.
- Перед оплатой проверяются пользователь, товар, категория, подкатегория, сумма, валюта и остатки.
- После `successful_payment` заказ блокируется транзакцией.
- Код выбирается через `SELECT ... FOR UPDATE SKIP LOCKED`.
- На платежи стоят уникальные ограничения по `telegram_payment_charge_id` и `provider_payment_charge_id`.
- Повторный `successful_payment` не выдает новый код, а возвращает уже выданный.

## Платежи

По умолчанию используется Telegram Payments:

```env
PAYMENT_PROVIDER=telegram
TELEGRAM_PAYMENT_PROVIDER_TOKEN=replace_with_provider_token_from_botfather
```

Для Platega:

```env
PAYMENT_PROVIDER=platega
PLATEGA_MERCHANT_ID=4ca85495-99c7-4c04-bb40-aa8e753ab166
PLATEGA_API_KEY=replace_with_platega_api_key
PLATEGA_CALLBACK_ENABLED=true
```

Если `PLATEGA_PAYMENT_METHOD` пустой, бот создает универсальную платежную форму через `v2/transaction/process`. При необходимости можно указать метод из инструкции Platega: `2` СБП QR, `3` ЕРИП, `11` карты, `12` международные карты, `13` криптовалюта.

Callback URL для кабинета Platega:

```text
https://your-domain.example/payments/platega/callback
```

Endpoint принимает POST-уведомления Platega, проверяет заголовки `X-MerchantId` и `X-Secret`, завершает заказ только при статусе `CONFIRMED` и игнорирует повторную выдачу кодов.

## BotFather

1. Создайте бота через `/newbot`.
2. Скопируйте `BOT_TOKEN`.
3. Включите Payments у нужного бота.
4. Получите `TELEGRAM_PAYMENT_PROVIDER_TOKEN` у выбранного платежного провайдера в BotFather.
5. Для тестов можно использовать тестовый provider token.

## Настройка `.env`

```bash
cp .env.example .env
```

Обязательно замените:

- `BOT_TOKEN`
- `TELEGRAM_PAYMENT_PROVIDER_TOKEN` или параметры `PLATEGA_*`
- `ADMIN_IDS`
- `CALLBACK_SECRET`
- `POSTGRES_PASSWORD`

`CALLBACK_SECRET` должен быть длинной случайной строкой, минимум 24 символа.

## Запуск Docker

```bash
docker compose up -d --build
```

Контейнер `bot` при старте выполняет:

```bash
alembic upgrade head
python -m app.main
```

Режим по умолчанию: polling. Для Platega callback контейнер `bot` слушает `WEBHOOK_PORT` и должен быть доступен снаружи через публичный HTTPS-адрес или reverse proxy.

## Миграции

Внутри контейнера:

```bash
docker compose exec bot alembic upgrade head
docker compose exec bot alembic revision --autogenerate -m "change"
```

## Добавление администратора

Есть два способа:

1. Указать Telegram ID в `ADMIN_IDS`.
2. Добавить запись в таблицу `admins`.

Пример SQL:

```sql
insert into admins (telegram_id, role, is_active)
values (123456789, 'admin', true)
on conflict (telegram_id) do update set is_active = true;
```

## Пользовательские функции

- `/start`: регистрация и главное меню.
- Каталог: категории → подкатегории → товары → карточка товара.
- Покупка: счет Telegram Payments или ссылка на оплату Platega.
- Мои покупки: дата, товар, цена, статус, выданный код.
- Поддержка, FAQ, Правила: тексты из таблицы `settings`.

## Админ-панель

Откройте:

```text
/admin
```

Доступ проверяется через `ADMIN_IDS` и таблицу `admins`.

### Кнопочное управление товарами

В `/admin` откройте раздел `Товары`.

Доступно без ручного ввода команд:

- создать товар;
- выбрать категорию и подкатегорию кнопками;
- заполнить название, описание, цену, валюту и сортировку пошаговым диалогом;
- открыть карточку товара;
- изменить название, описание, цену, валюту и сортировку;
- включить или отключить товар;
- безопасно удалить товар через soft delete с записью в audit log.

### Быстрые команды администратора

Команды ниже оставлены как технический запасной путь.

Создать категорию:

```text
/admin_create_category Название категории
```

Создать подкатегорию:

```text
/admin_create_subcategory category_id Название подкатегории
```

Создать товар:

```text
/admin_create_product category_id subcategory_id | Название | 100.00 | RUB | Описание
```

Включить или отключить сущность:

```text
/admin_set_active category 1 true
/admin_set_active subcategory 1 false
/admin_set_active product 1 true
```

Переименовать сущность:

```text
/admin_rename category 1 Новое название
```

Изменить сортировку:

```text
/admin_sort product 1 10
```

Удалить сущность безопасно:

```text
/admin_delete_entity category 1
```

Команда выполняет soft delete через отключение и пишет audit log.

Изменить цену товара:

```text
/admin_update_price product_id 150.00
```

Загрузить цифровые товары:

```text
/admin_upload_items product_id
CODE-1
CODE-2
CODE-3
```

Можно отправить `.txt` или `.csv` документ с caption:

```text
/admin_upload_items product_id
```

Экспортировать цифровые товары:

```text
/admin_export_items product_id
```

Найти код:

```text
/admin_search_items часть_кода
```

Изменить код:

```text
/admin_update_item item_id новое_значение
```

Удалить код:

```text
/admin_delete_item item_id
```

Изменить статус заказа:

```text
/admin_set_order_status order_id pending|paid|cancelled|error|refunded
```

Добавить комментарий к заказу:

```text
/admin_comment_order order_id комментарий
```

Обновить тексты:

```text
/admin_set_text support_text
Текст поддержки
```

Доступные ключи:

- `support_text`
- `faq_text`
- `rules_text`

Блокировка пользователя:

```text
/admin_block_user user_db_id причина
/admin_unblock_user user_db_id
```

Рассылка:

```text
/admin_broadcast all
Текст сообщения
```

```text
/admin_broadcast buyers
Текст сообщения
```

```text
/admin_broadcast product:1
Текст сообщения
```

## Тестирование покупки

1. Создайте категорию.
2. Создайте подкатегорию.
3. Создайте товар с валютой, поддерживаемой provider token.
4. Загрузите минимум один код.
5. В пользовательском меню выберите товар и нажмите “Купить”.
6. Оплатите тестовой картой провайдера.
7. Проверьте, что код появился в “Мои покупки”.

## Тесты

Быстрые статические security-тесты:

```bash
python -m unittest app.tests.test_security_static
```

Полный прогон в Docker:

```bash
docker compose --profile test run --rm tests
```

PostgreSQL-тесты используют `TEST_DATABASE_URL` и проверяют:

- double sale
- repeated successful payment
- запрет просмотра чужого заказа

## Логи

```bash
docker compose logs -f bot
docker compose logs -f postgres
docker compose logs -f redis
```

## Безопасный деплой на сервер

Перед SSH-деплоем нужно получить от владельца сервера:

- SSH host
- SSH port
- SSH user
- путь установки
- способ авторизации
- production `.env`
- polling или webhook

Приватный SSH-ключ нельзя отправлять в чат. Используйте локальный SSH-agent или заранее установленный ключ.

На сервере с VPN запрещено без отдельного подтверждения:

- перезапускать VPN
- менять firewall
- менять маршрутизацию
- выполнять reboot/shutdown
- выполнять `iptables -F` или `nft flush ruleset`

Деплой должен использовать отдельную директорию, отдельный `.env`, отдельную Docker network и отдельные volumes.

## Откат

Откат не затрагивает VPN, firewall и маршрутизацию:

```bash
docker compose down
cp backups/<timestamp>/docker-compose.yml ./docker-compose.yml
cp backups/<timestamp>/.env ./.env
docker compose up -d --build
```

Перед откатом сохраните текущие логи:

```bash
docker compose logs --no-color > rollback-logs.txt
```
