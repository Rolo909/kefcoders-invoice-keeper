# Развёртывание на VPS (Ubuntu 22.04 / 24.04)

Сайт и бот работают на одном сервере в Docker. Наружу открыты только порты 80 и 443: nginx с бесплатным
сертификатом Let's Encrypt **на IP-адрес сервера** (домен не нужен). API, база данных и worker — внутри.

Вместо `203.0.113.10` везде подставьте IP вашего сервера.

## Что понадобится

- IP-адрес сервера и пароль `root` от хостинга (нужен один раз — потом вход только по ключу)
- доступ к репозиторию на GitHub (он приватный — подключим ключ только для чтения)
- токен Telegram-бота и `chat_id` чата ([как получить](../README.md#telegram-бот-и-чат))
- почтовый ящик для отправки писем (адрес и пароль приложения) и e-mail для Let's Encrypt

## 0. SSH-ключ на своём компьютере

В PowerShell на Windows (на macOS/Linux — в терминале, вместо `type $env:USERPROFILE\.ssh\...` — `cat ~/.ssh/...`).
Ключ создаётся один раз; на вопрос о passphrase лучше задать пароль к ключу.

```powershell
ssh-keygen -t ed25519 -C "invoice-keeper"
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@203.0.113.10 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
ssh root@203.0.113.10
```

Вторая команда последний раз спросит пароль `root`, третья должна войти уже без него.

## 1. Обновление системы и пользователь для входа

```bash
apt update && apt upgrade -y
apt install -y ufw fail2ban python3-systemd unattended-upgrades
adduser deploy
usermod -aG sudo deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
install -m 600 -o deploy -g deploy ~/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
```

`adduser` спросит пароль для `deploy` — он нужен для `sudo`; войти по SSH с паролем будет нельзя.

## 2. Защита SSH: только ключи, без root

```bash
cat > /etc/ssh/sshd_config.d/00-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowUsers deploy
EOF
mkdir -p /run/sshd && sshd -t && systemctl restart ssh
```

**Не закрывайте текущее окно.** В новом окне проверьте вход: `ssh deploy@203.0.113.10`, затем `sudo -i`
(станете `root`). Только если это получилось, старое окно можно закрыть. Дальше все команды — после `sudo -i`.

## 3. Файрвол, защита от подбора паролей, автообновления

```bash
ufw default deny incoming
ufw default allow outgoing
ufw limit OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose
```

`ufw limit` отбрасывает IP, который открывает больше 6 SSH-соединений за 30 секунд. fail2ban банит на час
после 5 неудачных входов по SSH:

```bash
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
backend = systemd
EOF
systemctl enable fail2ban && systemctl restart fail2ban
fail2ban-client status sshd
```

Обновления безопасности ставятся сами каждый день; ядро — с защитой от SYN-флуда:

```bash
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' > /etc/apt/apt.conf.d/20auto-upgrades
cat > /etc/sysctl.d/99-hardening.conf <<'EOF'
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.icmp_echo_ignore_broadcasts = 1
EOF
sysctl --system >/dev/null
```

Если `free -h` показывает 2 ГБ памяти или меньше, добавьте swap — иначе сборка может упасть:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 4. Docker

```bash
curl -fsSL https://get.docker.com | sh
cat > /etc/docker/daemon.json <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
EOF
systemctl restart docker
docker compose version
```

Должна быть версия Compose 2.24 или новее. Ограничение логов не даст забить диск, если сайт заваливают запросами.
Docker открывает порты в обход ufw, поэтому в `docker-compose.prod.yml` наружу опубликованы только 80 и 443.

## 5. Код из GitHub

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

## 6. Настройки (`.env`)

```bash
cp .env.example .env
chmod 600 .env
openssl rand -hex 16   # пароль администратора
openssl rand -hex 16   # пароль базы данных (только буквы и цифры — он входит в адрес подключения)
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

## 7. Сертификат Let's Encrypt на IP-адрес

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

## 8. Запуск

```bash
docker compose up -d --build
docker compose ps
```

Первая сборка — 3–5 минут. У `db` и `backend` статус `healthy`, у `worker`, `frontend`, `edge` — `running`.
Сайт: **https://203.0.113.10**, вход `admin` и пароль из `ADMIN_PASSWORD`.

## 9. Автопродление сертификата

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

## 10. Проверка

1. https://203.0.113.10 открывается без предупреждения браузера, вход `admin` работает.
2. «Журнал» → «Уведомления» → «Отправить тестовое уведомление»: Telegram и почта — «доставлено».
3. Боту в личке `/start` — он отвечает. В панели «Профиль» → «Получить код» → боту `/link <код>`.
4. Тестовые «Аренда офиса, Санкт-Петербург» и «Бухгалтерское и налоговое сопровождение» уже прислали напоминание в чат —
   нажмите «✅ Оплачено», в панели период станет оплаченным.
5. Остальное — по [сценарию защиты](demo-scenario.md).

Защита: снаружи должны быть видны только SSH, 80 и 443 — `ss -tlnp` покажет порты 22, 80, 443
(и `127.0.0.53:53` — это локальный DNS). `fail2ban-client status sshd` — кого забанили.

Логи: `docker compose logs -f worker` (напоминания и бот), `docker compose logs -f backend`.

Сквозные тесты можно прогнать со своего компьютера против сервера (они создают на сервере платежи
с пометкой «E2E»; их потом можно прекратить в панели):

```bash
E2E_BASE_URL=https://203.0.113.10 E2E_ADMIN_PASSWORD='пароль-администратора' sh e2e/run.sh
```

## Защита от флуда и DDoS

- **Сайт.** nginx (`deploy/nginx/edge.conf`) ограничивает один IP: 20 запросов в секунду (с запасом 100),
  50 одновременных соединений, 60 попыток входа в минуту; лишнее получает `429` и до приложения не доходит.
  Медленные соединения (slowloris) обрываются через 10–30 секунд. Бэкенд дополнительно блокирует логин после
  5 неверных паролей за минуту.
- **Бот.** Работает через long polling: сам ходит в Telegram за обновлениями, входящих портов у него нет —
  атаковать его запросами из интернета нельзя. От флуда сообщениями и нажатиями — не больше 10 событий от
  одного человека за 10 секунд, остальные отбрасываются.
- **Большой DDoS** (гигабиты трафика с тысяч адресов) один сервер не выдержит никакими настройками — его
  отсекает сеть хостинга. Проверьте в панели хостинга, что защита от DDoS включена для IP сервера; Cloudflare
  с IP-адресом без домена не работает.

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
| `edge` перезапускается | нет сертификата в `/etc/letsencrypt/live/invoice-keeper/` — выполните шаг 7 |
| сайт не открывается | `ufw status` — открыты ли 80 и 443; файрвол в панели хостинга тоже должен их пропускать |
| бот молчит | `docker compose logs worker | grep -i telegram`; токен и `chat_id` в `.env`, бот — участник чата; после правки `.env` — `docker compose up -d` |
| письма не уходят | «Отправить тестовое уведомление» покажет причину; проверьте пароль приложения и доступность порта 587 |
