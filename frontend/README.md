# Invoice Keeper — веб-панель

React 18, Vite, TypeScript, Mantine 7, TanStack Query, React Router, react-hook-form и zod — стек из `TASK_PLAN.md` §1.

## Запуск без бэкенда

Нужен Node.js 20 или новее.

```bash
cd frontend
npm install
npm run dev
```

Откройте `http://localhost:5173`. Запросы к `/api/v1` обрабатывает имитация сервера в браузере (`src/mocks`): те же эндпоинты и правила, что в `TASK_PLAN.md` §4–5. Данные хранятся в браузере и переживают перезагрузку. Сбросить их к исходным — открыть любой адрес с `?reset-demo`.

| Логин | Пароль | Роль |
| --- | --- | --- |
| `admin` | `admin12345` | Администратор |
| `anna` | `anna12345` | Пользователь |
| `maria` | `maria12345` | Пользователь |
| `user` | `user12345` | Пользователь |

## Запуск с настоящим бэкендом

Создайте `frontend/.env.local`:

```bash
VITE_API_MOCK=false
API_PROXY_TARGET=http://localhost:8000
```

Перезапустите `npm run dev`. Vite будет проксировать `/api` на бэкенд, cookie сессии работает как на одном домене.

В Docker имитация выключена: образ собирает статику и отдаёт её через nginx на порту 8080, а `/api/` проксирует на `backend:8000` (`Dockerfile`, `nginx.conf`).

## Проверки

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

## Что фронтенд ждёт от бэкенда

Всё по `TASK_PLAN.md` §5, плюс уточнения ниже. Точные типы — в `src/api/types.ts`.

- `GET /auth/me` → `{ user, server_today, timezone }`. «Сегодня» фронтенд берёт только отсюда.
- `PATCH /auth/me` `{ email, notify_email }` — пользователь меняет свою почту в профиле. Для администратора из `.env` — 403.
- Пользователь: `telegram_linked: boolean` вместо `telegram_user_id`.
- Период (`Occurrence`) содержит `recurring_payment: { id, name, period, is_deleted }`, `paid_by: { id, login, full_name }`, вычисляемые `state`, `is_overdue`, `days_overdue`, а также `attachments_count` и `last_reminder_at` (время последнего отправленного напоминания в Telegram).
- `GET /payment-occurrences/{id}` дополнительно отдаёт `history` (записи журнала по периоду) и `reminders` (уведомления по периоду): журнал целиком доступен только администратору.
- `GET /payment-occurrences`: несколько валют — повтором параметра `currency=RUB&currency=USD`; `sort` — `due_date`, `amount`, `days_overdue`, с минусом для убывания.
- `GET /payments/summary`: в каждой валюте, кроме полей из §4.7, есть `paid_late` — сумма оплат позже срока. `overdue` — только неоплаченное с прошедшим сроком.
- `GET /payments/calendar?month=YYYY-MM` → `{ month, days: [{ date, occurrences, planned }] }`, где `planned` — будущие сроки без созданных периодов.
- `GET /budgets?year&month` и `PUT /budgets` — список `{ currency, period_type, year, month, amount }`.
- `GET /inbox` → `{ items, unread_count }`; у элемента есть `payment_name`, `amount`, `currency`, `due_date`, `occurrence_state`, `paid_date`, `payment_deleted`.
- `POST /notifications/test` → `{ channels: [{ channel, ok, error }] }`.
- В записях журнала поле `details` содержит `payment_name`, `due_date`, `paid_date`, `old_paid_date`, `new_paid_date`, `name`, `login` — по ним строится текст события (`src/lib/audit.ts`).
- Ошибки — `{ detail, code }`. Фронтенд различает коды `login_taken`, `not_paid`, `rate_limited` (429 на вход).
