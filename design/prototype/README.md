# Прототип веб-панели Invoice Keeper

Кликабельный прототип всех страниц из `TASK_PLAN.md` §9.1. Статический HTML, сборка не нужна.

## Запуск

Нужны Git и Python 3.

```bash
git clone https://github.com/Rolo909/kefcoders-invoice-keeper.git
cd kefcoders-invoice-keeper
git switch design/ledger-prototype
python3 -m http.server 8765 --directory design/prototype
```

Сервер запускается из корня репозитория. На Windows вместо `python3` пишется `python`. Откройте `http://127.0.0.1:8765/login.html`, остановить сервер — `Ctrl+C`.

## Вход

| Логин | Пароль | Роль |
| --- | --- | --- |
| `admin` | `admin12345` | Администратор |
| `anna` | `anna12345` | Пользователь |

## Параметры адреса

| Параметр | Что делает |
| --- | --- |
| `?role=user` или `?role=admin` | Роль на время сессии |
| `?theme=dark` или `?theme=light` | Тема на время сессии |
| `?reset=1` | Сброс демо-изменений |
| `index.html?state=loading`, `empty`, `allpaid` | Загрузка, пустая книга, всё оплачено |
