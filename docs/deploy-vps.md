# Развёртывание на VPS (Ubuntu 22.04 / 24.04)

Сайт и бот работают на одном сервере в Docker. Наружу открыты только порты 80 и 443: nginx с бесплатным
сертификатом Let's Encrypt **на IP-адрес сервера** (домен не нужен). API, база данных и worker — внутри.

Команды выполняются на сервере от `root`. Вместо `203.0.113.10` подставьте IP вашего сервера.

## Что понадобится

- IP-адрес сервера и вход по SSH: `ssh root@203.0.113.10`
- доступ к репозиторию на GitHub (он приватный — подключим ключ только для чтения)
- токен Telegram-бота и `chat_id` чата ([как получить](../README.md#telegram-бот-и-чат))
- почтовый ящик для отправки писем (адрес и пароль приложения) и e-mail для Let's Encrypt

## 1. Обновление системы и файрвол

```bash
apt update && apt upgrade -y
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

## 2. Docker

```bash
curl -fsSL https://get.docker.com | sh
docker compose version
```

Должна быть версия Compose 2.24 или новее.

## 3. Код из GitHub

Ключ только для чтения этого репозитория (deploy key):

```bash
ssh-keygen -t ed25519 -N "" -C "invoice-keeper-vps" -f ~/.ssh/invoice_keeper
cat ~/.ssh/invoice_keeper.pub
```

Скопируйте выведенную строку: GitHub → репозиторий → **Settings → Deploy keys → Add deploy key**,
галочку «Allow write access» **не** ставьте. Затем:

```bash
printf 'Host github.com\n  IdentityFile ~/.ssh/invoice_keeper\n  IdentitiesOnly yes\n' >> ~/.ssh/config
git clone git@github.com:Rolo909/kefcoders-invoice-keeper.git /opt/invoice-keeper
cd /opt/invoice-keeper
```

## 4. Настройки (`.env`)

```bash
cp .env.example .env
chmod 600 .env
openssl rand -base64 18   # пароль администратора
openssl rand -base64 18   # пароль базы данных
nano .env
```

Что поменять в `.env`:

| Переменная | Значение |
|---|---|
| `COMPOSE_FILE` | добавьте строку `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` — тогда `docker compose` сам берёт серверную конфигурацию |
| `ADMIN_PASSWORD` | первый сгенерированный пароль |
| `POSTGRES_PASSWORD` | второй сгенерированный пароль (строку `DATABASE_URL` трогать не нужно) |
| `PUBLIC_WEB_URL` | `https://203.0.113.10` — в напоминаниях появится кнопка «Открыть в панели» |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | токен бота и `chat_id` чата |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS` | например, Яндекс: `smtp.yandex.ru`, `587`, `true`; Gmail: `smtp.gmail.com`, `587`, `true` |
| `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | адрес ящика, **пароль приложения** (не обычный пароль), тот же адрес в `SMTP_FROM` |
| `EMAIL_ENABLED` | `true` |

Поддерживается порт 587 (STARTTLS). Некоторые хостинги блокируют исходящую почту — проверьте:
`nc -vz smtp.yandex.ru 587` должен ответить `succeeded`. Если заблокировано — напишите в поддержку хостинга
или временно поставьте `EMAIL_ENABLED=false`.

## 5. Сертификат Let's Encrypt на IP-адрес

Let's Encrypt выдаёт сертификаты на IP-адрес только «короткоживущими» (около 6 дней) — certbot будет
продлевать их сам.

```bash
snap install --classic certbot
ln -sf /snap/bin/certbot /usr/bin/certbot
certbot --version
mkdir -p /var/www/certbot
```

Первый выпуск — до запуска сайта, пока порт 80 свободен:

```bash
certbot certonly --standalone --cert-name invoice-keeper \
  --preferred-profile shortlived --ip-address 203.0.113.10 \
  -m you@example.com --agree-tos --no-eff-email
```

Должно появиться `Successfully received certificate` и файлы в `/etc/letsencrypt/live/invoice-keeper/`.
Если certbot ответит, что не знает `--ip-address` или `--preferred-profile`, пришлите вывод
`certbot --version` и текст ошибки.

## 6. Запуск

```bash
docker compose up -d --build
docker compose ps
```

Первая сборка — 3–5 минут. У `db` и `backend` статус `healthy`, у `worker`, `frontend`, `edge` — `running`.
Сайт: **https://203.0.113.10**, вход `admin` и пароль из `ADMIN_PASSWORD`.

## 7. Автопродление сертификата

Сайт уже работает, поэтому продлевать будем через него (webroot), а после продления перезагружать nginx:

```bash
certbot reconfigure --cert-name invoice-keeper --webroot -w /var/www/certbot \
  --deploy-hook "docker exec invoice-keeper-edge-1 nginx -s reload"
grep -q '^renew_before_expiry' /etc/letsencrypt/renewal/invoice-keeper.conf \
  || sed -i '1i renew_before_expiry = 3 days' /etc/letsencrypt/renewal/invoice-keeper.conf
certbot renew --dry-run
systemctl list-timers | grep certbot
```

`--dry-run` должен закончиться `Congratulations, all simulated renewals succeeded`. Таймер certbot
проверяет сертификат дважды в день и продлевает его за 3 дня до окончания.

## 8. Проверка

1. https://203.0.113.10 открывается без предупреждения браузера, вход `admin` работает.
2. «Журнал» → «Уведомления» → «Отправить тестовое уведомление»: Telegram и почта — «доставлено».
3. Боту в личке `/start` — он отвечает. В панели «Профиль» → «Получить код» → боту `/link <код>`.
4. Тестовые «Аренда офиса» и «Бухгалтерское сопровождение» уже прислали напоминание в чат —
   нажмите «✅ Оплачено», в панели период станет оплаченным.
5. Остальное — по [сценарию защиты](demo-scenario.md).

Логи: `docker compose logs -f worker` (напоминания и бот), `docker compose logs -f backend`.

Сквозные тесты можно прогнать со своего компьютера против сервера (они создают на сервере платежи
с пометкой «E2E»; их потом можно прекратить в панели):

```bash
E2E_BASE_URL=https://203.0.113.10 E2E_ADMIN_PASSWORD='пароль-администратора' sh e2e/run.sh
```

## Обновление

```bash
cd /opt/invoice-keeper
git pull
docker compose up -d --build
```

Данные (база и чеки) хранятся в Docker-томах и при обновлении не теряются. Чистая установка с нуля —
`docker compose down -v` (удалит **все** данные).

## Если что-то не так

| Симптом | Что сделать |
|---|---|
| certbot: `Could not bind TCP port 80` | порт занят — выпускайте сертификат до `docker compose up` или остановите стек: `docker compose down` |
| `edge` перезапускается | нет сертификата в `/etc/letsencrypt/live/invoice-keeper/` — выполните шаг 5 |
| сайт не открывается | `ufw status` — открыты ли 80 и 443; файрвол в панели хостинга тоже должен их пропускать |
| бот молчит | `docker compose logs worker | grep -i telegram`; токен и `chat_id` в `.env`, бот — участник чата; после правки `.env` — `docker compose up -d` |
| письма не уходят | «Отправить тестовое уведомление» покажет причину; проверьте пароль приложения и доступность порта 587 |
