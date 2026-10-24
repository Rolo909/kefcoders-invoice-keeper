"""Команды и изоляция: пользователь видит только свою команду, администратор — все.

Случаи — те же, что в frontend/src/mocks/handlers.test.ts (имитация API панели), плюс перебор всех
маршрутов: новый маршрут без изоляции сломает тест.
"""

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import AttachmentKind, NotificationChannel, NotificationKind, NotificationStatus, Role
from app.models import Attachment, AuditLog, Notification, PaymentOccurrence, RecurringPayment, Team, User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, RecordingNotifier, bearer, login

MSK = ZoneInfo("Europe/Moscow")
TODAY = "2026-10-15"
OLEG = "oleg"


@pytest.fixture(autouse=True)
def frozen_today() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 10, 15, 12, 0, tzinfo=MSK), tick=False):
        yield


@dataclass
class World:
    kef: Team
    studio: Team
    admin: str
    anna: str
    oleg: str
    rent: dict[str, Any]  # платёж Kefcoders
    adobe: dict[str, Any]  # платёж Студии
    shared: dict[str, Any]  # общий платёж


async def _payment(api: AsyncClient, token: str, name: str, team: Team | None, **extra: Any) -> dict[str, Any]:
    body = {"name": name, "amount": "1000", "currency": "RUB", "next_due_date": "2026-10-20", **extra}
    if team is not None:
        body["team_id"] = str(team.id)
    response = await api.post("/api/v1/recurring-payments", json=body, headers=bearer(token))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


@pytest.fixture
async def world(
    api: AsyncClient,
    db_session: AsyncSession,
    admin: User,
    regular_user: User,
    team: Team,
    password_hashes: dict[str, str],
) -> World:
    """Kefcoders (anna) и Студия дизайна (oleg); платёж каждой команды и общий."""
    studio = Team(name="Студия дизайна", created_at=team.created_at)
    db_session.add(studio)
    await db_session.flush()
    db_session.add(
        User(
            login=OLEG,
            password_hash=password_hashes[USER_PASSWORD],
            role=Role.USER,
            full_name="Олег",
            team_id=studio.id,
        )
    )
    await db_session.flush()
    admin_token = await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)
    return World(
        kef=team,
        studio=studio,
        admin=admin_token,
        anna=await login(api, USER_LOGIN, USER_PASSWORD),
        oleg=await login(api, OLEG, USER_PASSWORD),
        rent=await _payment(api, admin_token, "Аренда офиса", team),
        adobe=await _payment(api, admin_token, "Adobe Creative Cloud", studio, currency="EUR"),
        shared=await _payment(api, admin_token, "Бухгалтерское сопровождение", None),
    )


async def get(api: AsyncClient, token: str, path: str, **params: Any) -> Response:
    return await api.get(f"/api/v1{path}", params=params, headers=bearer(token))


async def items(api: AsyncClient, token: str, path: str, **params: Any) -> list[dict[str, Any]]:
    response = await get(api, token, path, limit=500, **params)
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()["items"]
    return found


async def period_of(api: AsyncClient, token: str, payment: dict[str, Any], team: Team) -> dict[str, Any]:
    [first, *_] = await items(
        api, token, "/payment-occurrences", recurring_payment_id=payment["id"], team_id=str(team.id)
    )
    return first


# ---------- пользователь видит только свою команду ----------


async def test_user_sees_own_and_shared_payments_and_only_own_periods(api: AsyncClient, world: World) -> None:
    payments = await items(api, world.anna, "/recurring-payments", include_deleted=True)
    periods = await items(api, world.anna, "/payment-occurrences")

    assert {p["name"] for p in payments} == {"Аренда офиса", "Бухгалтерское сопровождение"}
    assert all(p["team"] is None or p["team"]["name"] == "Kefcoders" for p in payments)
    assert periods
    assert {o["team"]["name"] for o in periods} == {"Kefcoders"}


async def test_foreign_period_is_not_found_for_reading_paying_and_attachments(api: AsyncClient, world: World) -> None:
    foreign = await period_of(api, world.admin, world.adobe, world.studio)
    path = f"/api/v1/payment-occurrences/{foreign['id']}"
    headers = bearer(world.anna)

    responses = [
        await api.get(path, headers=headers),
        await api.patch(path, json={"status": "paid"}, headers=headers),
        await api.get(f"{path}/attachments", headers=headers),
        await api.post(f"{path}/attachments", json={"url": "https://bank.ru/r/1"}, headers=headers),
        await api.get(f"/api/v1/recurring-payments/{world.adobe['id']}", headers=headers),
    ]

    assert [r.status_code for r in responses] == [404] * 5
    assert {r.json()["code"] for r in responses} == {"not_found"}
    assert (await period_of(api, world.admin, world.adobe, world.studio))["status"] == "unpaid"


@pytest.mark.parametrize(
    "path", ["/payment-occurrences", "/recurring-payments", "/payments/summary", "/payments/calendar", "/budgets"]
)
async def test_foreign_team_in_filter_is_forbidden(api: AsyncClient, world: World, path: str) -> None:
    response = await get(api, world.anna, path, team_id=str(world.studio.id))

    assert response.status_code == 403
    assert response.json() == {"detail": "Данные другой команды недоступны", "code": "forbidden"}


async def test_own_team_in_filter_is_allowed(api: AsyncClient, world: World) -> None:
    assert (await get(api, world.anna, "/payment-occurrences", team_id=str(world.kef.id))).status_code == 200


async def test_inbox_and_budgets_show_only_own_team(api: AsyncClient, world: World, db_session: AsyncSession) -> None:
    for payment, team in ((world.rent, world.kef), (world.adobe, world.studio)):
        period = await period_of(api, world.admin, payment, team)
        db_session.add(
            Notification(
                occurrence_id=uuid.UUID(period["id"]),
                channel=NotificationChannel.INAPP,
                kind=NotificationKind.BEFORE_DUE,
                status=NotificationStatus.SENT,
            )
        )
    budget = {"currency": "RUB", "period_type": "month", "year": 2026, "month": 10, "amount": "100.00"}
    await api.put(
        "/api/v1/budgets",
        json=[{**budget, "team_id": str(world.kef.id)}, {**budget, "team_id": str(world.studio.id)}],
        headers=bearer(world.admin),
    )

    inbox = (await get(api, world.anna, "/inbox")).json()
    budgets = (await get(api, world.anna, "/budgets", year=2026, month=10)).json()

    assert [i["team"]["name"] for i in inbox["items"]] == ["Kefcoders"]
    assert inbox["unread_count"] == 1
    assert [b["team_id"] for b in budgets] == [str(world.kef.id)]
    assert len((await get(api, world.admin, "/inbox")).json()["items"]) == 2  # администратор видит все команды


async def test_only_admin_manages_teams(api: AsyncClient, world: World) -> None:
    headers = bearer(world.anna)

    responses = [
        await api.get("/api/v1/teams", headers=headers),
        await api.post("/api/v1/teams", json={"name": "Своя команда"}, headers=headers),
        await api.patch(f"/api/v1/teams/{world.kef.id}", json={"name": "Моя"}, headers=headers),
        await api.delete(f"/api/v1/teams/{world.studio.id}", headers=headers),
    ]

    assert [r.status_code for r in responses] == [403] * 4


# ---------- общий платёж ----------


async def test_shared_payment_has_own_period_per_team(api: AsyncClient, world: World) -> None:
    query = {"recurring_payment_id": world.shared["id"], "date_from": "2026-10-20", "date_to": "2026-10-20"}
    everyone = await items(api, world.admin, "/payment-occurrences", **query)
    assert sorted(o["team"]["name"] for o in everyone) == ["Kefcoders", "Студия дизайна"]

    [mine] = await items(api, world.anna, "/payment-occurrences", **query)
    paid = await api.patch(
        f"/api/v1/payment-occurrences/{mine['id']}", json={"status": "paid"}, headers=bearer(world.anna)
    )

    [theirs] = await items(api, world.oleg, "/payment-occurrences", **query)
    assert paid.status_code == 200
    assert (theirs["team"]["name"], theirs["status"]) == ("Студия дизайна", "unpaid")


async def test_payment_without_team_is_shared(api: AsyncClient, world: World) -> None:
    assert world.shared["team"] is None


async def test_team_payment_is_seen_only_by_its_team(api: AsyncClient, world: World) -> None:
    path = f"/recurring-payments/{world.adobe['id']}"

    assert world.adobe["team"] == {"id": str(world.studio.id), "name": "Студия дизайна"}
    assert (await get(api, world.anna, path)).status_code == 404
    assert (await get(api, world.oleg, path)).status_code == 200


async def test_admin_opens_team_payment_whatever_team_is_selected(api: AsyncClient, world: World) -> None:
    detail = await get(api, world.admin, f"/recurring-payments/{world.adobe['id']}", team_id=str(world.kef.id))

    assert detail.status_code == 200
    occurrences = detail.json()["occurrences"]
    assert occurrences
    assert {o["team"]["name"] for o in occurrences} == {"Студия дизайна"}


async def test_shared_payment_detail_follows_selected_team(api: AsyncClient, world: World) -> None:
    path = f"/recurring-payments/{world.shared['id']}"

    everyone = (await get(api, world.admin, path)).json()["occurrences"]
    studio = (await get(api, world.admin, path, team_id=str(world.studio.id))).json()["occurrences"]

    assert {o["team"]["name"] for o in everyone} == {"Kefcoders", "Студия дизайна"}
    assert {o["team"]["name"] for o in studio} == {"Студия дизайна"}
    # в один день — по названию команды
    first_day = [o["team"]["name"] for o in everyone if o["due_date"] == everyone[0]["due_date"]]
    assert first_day == sorted(first_day, key=str.lower)


async def test_unknown_team_of_payment_is_rejected(api: AsyncClient, world: World) -> None:
    body = {"name": "X", "amount": "10", "currency": "EUR", "next_due_date": TODAY, "team_id": str(uuid.uuid4())}

    response = await api.post("/api/v1/recurring-payments", json=body, headers=bearer(world.admin))

    assert response.status_code == 422


async def test_unknown_team_in_admin_filter_is_not_found(api: AsyncClient, world: World) -> None:
    response = await get(api, world.admin, "/payment-occurrences", team_id=str(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json() == {"detail": "Команда не найдена", "code": "not_found"}


# ---------- команды ----------


async def test_new_team_gets_shared_payments_from_nearest_due_without_debts(
    api: AsyncClient, world: World, db_session: AsyncSession
) -> None:
    # Общий платёж заведён давно: у старых команд есть прошлые сроки, у новой их быть не должно.
    await db_session.execute(
        update(RecurringPayment)
        .where(RecurringPayment.id == uuid.UUID(world.shared["id"]))
        .values(first_due_date=datetime(2026, 6, 20).date(), created_at=datetime(2026, 6, 1, tzinfo=MSK))
    )

    created = await api.post(
        "/api/v1/teams",
        json={"name": "Отдел продаж", "telegram_chat_id": "-1001234567890"},
        headers=bearer(world.admin),
    )

    assert created.status_code == 201
    team = created.json()
    assert {k: team[k] for k in ("name", "telegram_chat_id", "members_count")} == {
        "name": "Отдел продаж",
        "telegram_chat_id": "-1001234567890",
        "members_count": 0,
    }
    periods = await items(api, world.admin, "/payment-occurrences", team_id=team["id"])
    joined = datetime.fromisoformat(team["created_at"]).astimezone(MSK).date().isoformat()
    assert {o["recurring_payment"]["name"] for o in periods} == {"Бухгалтерское сопровождение"}
    assert all(o["due_date"] >= joined and o["state"] != "overdue" for o in periods)


async def test_team_name_is_unique_regardless_of_case(api: AsyncClient, world: World) -> None:
    response = await api.post("/api/v1/teams", json={"name": "  kefcoders "}, headers=bearer(world.admin))

    assert response.status_code == 409
    assert response.json() == {"detail": "Команда «kefcoders» уже есть", "code": "team_name_taken"}


@pytest.mark.parametrize(
    "body",
    [{"name": ""}, {"name": "x" * 101}, {"name": "Отдел", "telegram_chat_id": "чат продаж"}, {"name": "A", "x": 1}],
)
async def test_invalid_team_is_rejected(api: AsyncClient, world: World, body: dict[str, Any]) -> None:
    response = await api.post("/api/v1/teams", json=body, headers=bearer(world.admin))

    assert response.status_code == 422


async def test_only_empty_team_can_be_deleted(api: AsyncClient, world: World, db_session: AsyncSession) -> None:
    busy = await api.delete(f"/api/v1/teams/{world.studio.id}", headers=bearer(world.admin))
    empty = (await api.post("/api/v1/teams", json={"name": "По ошибке"}, headers=bearer(world.admin))).json()
    assert await items(api, world.admin, "/payment-occurrences", team_id=empty["id"])  # периоды общего платежа

    deleted = await api.delete(f"/api/v1/teams/{empty['id']}", headers=bearer(world.admin))

    assert busy.status_code == 409
    assert busy.json()["code"] == "team_not_empty"
    assert deleted.status_code == 204
    assert (await get(api, world.admin, "/payment-occurrences", team_id=empty["id"])).status_code == 404
    actions = list(await db_session.scalars(select(AuditLog.action).where(AuditLog.action.like("team.%"))))
    assert actions == ["team.create", "team.delete"]


async def test_team_with_paid_period_cannot_be_deleted(api: AsyncClient, world: World) -> None:
    empty = (await api.post("/api/v1/teams", json={"name": "Отдел"}, headers=bearer(world.admin))).json()
    period = (await items(api, world.admin, "/payment-occurrences", team_id=empty["id"]))[0]
    await api.patch(f"/api/v1/payment-occurrences/{period['id']}", json={"status": "paid"}, headers=bearer(world.admin))

    response = await api.delete(f"/api/v1/teams/{empty['id']}", headers=bearer(world.admin))

    assert response.status_code == 409


async def test_teams_are_listed_by_name_with_members(api: AsyncClient, world: World) -> None:
    page = (await get(api, world.admin, "/teams")).json()

    assert [(t["name"], t["members_count"]) for t in page["items"]] == [("Kefcoders", 1), ("Студия дизайна", 1)]
    assert (page["total"], page["limit"]) == (2, 200)


async def test_team_is_renamed_and_its_chat_changed(api: AsyncClient, world: World) -> None:
    response = await api.patch(
        f"/api/v1/teams/{world.studio.id}",
        json={"name": "Дизайн", "telegram_chat_id": "@design_team"},
        headers=bearer(world.admin),
    )
    cleared = await api.patch(
        f"/api/v1/teams/{world.studio.id}", json={"telegram_chat_id": ""}, headers=bearer(world.admin)
    )

    assert (response.json()["name"], response.json()["telegram_chat_id"]) == ("Дизайн", "@design_team")
    assert (cleared.json()["name"], cleared.json()["telegram_chat_id"]) == ("Дизайн", None)


async def test_user_is_created_only_in_a_team(api: AsyncClient, world: World) -> None:
    without = await api.post(
        "/api/v1/users", json={"login": "no.team", "password": "long-enough"}, headers=bearer(world.admin)
    )
    within = await api.post(
        "/api/v1/users",
        json={"login": "vera", "password": "long-enough", "team_id": str(world.studio.id)},
        headers=bearer(world.admin),
    )

    assert without.status_code == 422
    assert within.status_code == 201
    assert within.json()["team"]["name"] == "Студия дизайна"


async def test_users_can_be_filtered_by_team(api: AsyncClient, world: World) -> None:
    studio = await items(api, world.admin, "/users", team_id=str(world.studio.id))

    assert [u["login"] for u in studio] == [OLEG]


async def test_totals_of_all_teams_are_sum_of_each_team(api: AsyncClient, world: World) -> None:
    def by_currency(team_id: str | None) -> dict[str, tuple[float, float]]:
        return {t["currency"]: (float(t["planned"]), float(t["paid"])) for t in summaries[team_id]["totals"]}

    period = await period_of(api, world.anna, world.rent, world.kef)
    await api.patch(f"/api/v1/payment-occurrences/{period['id']}", json={"status": "paid"}, headers=bearer(world.anna))
    summaries: dict[str | None, Any] = {}
    for team_id in (None, str(world.kef.id), str(world.studio.id)):
        params = {"date_from": "2026-10-01", "date_to": "2026-12-31"} | ({"team_id": team_id} if team_id else {})
        summaries[team_id] = (await get(api, world.admin, "/payments/summary", **params)).json()

    everyone, kef, studio = by_currency(None), by_currency(str(world.kef.id)), by_currency(str(world.studio.id))
    for currency, (planned, paid) in everyone.items():
        assert planned == pytest.approx(kef[currency][0] + studio[currency][0])
        assert paid == pytest.approx(kef[currency][1] + studio[currency][1])
    assert everyone["RUB"][1] > 0


async def test_budget_is_saved_only_for_a_team(api: AsyncClient, world: World) -> None:
    item = {"currency": "RUB", "period_type": "month", "year": 2026, "month": 10, "amount": "100.00"}

    response = await api.put("/api/v1/budgets", json=[item], headers=bearer(world.admin))

    assert response.status_code == 422


# ---------- перебор маршрутов: изоляция не забыта нигде ----------


async def _foreign_ids(api: AsyncClient, world: World, db_session: AsyncSession) -> dict[str, str]:
    """Объекты Kefcoders, которые участник Студии видеть не должен."""
    period = await period_of(api, world.admin, world.rent, world.kef)
    occurrence_id = uuid.UUID(period["id"])
    attachment = Attachment(
        occurrence_id=occurrence_id, kind=AttachmentKind.LINK, url="https://bank.ru/r/1", original_name="bank.ru"
    )
    notification = Notification(
        occurrence_id=occurrence_id,
        channel=NotificationChannel.INAPP,
        kind=NotificationKind.BEFORE_DUE,
        status=NotificationStatus.SENT,
    )
    anna = await db_session.scalar(select(User).where(User.login == USER_LOGIN))
    assert anna is not None
    attachment.uploaded_by = anna.id
    db_session.add_all([attachment, notification])
    await db_session.flush()
    return {
        "payment_id": world.rent["id"],
        "occurrence_id": period["id"],
        "attachment_id": str(attachment.id),
        "notification_id": str(notification.id),
        "user_id": str(anna.id),
        "team_id": str(world.kef.id),
    }


BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("patch", "/api/v1/payment-occurrences/{occurrence_id}"): {"status": "paid"},
    ("post", "/api/v1/payment-occurrences/{occurrence_id}/attachments"): {"url": "https://bank.ru/r/2"},
    ("patch", "/api/v1/users/{user_id}"): {"full_name": "Чужая"},
    ("patch", "/api/v1/teams/{team_id}"): {"name": "Чужая"},
}


async def test_every_object_of_another_team_is_hidden(
    app: FastAPI, api: AsyncClient, world: World, db_session: AsyncSession
) -> None:
    ids = await _foreign_ids(api, world, db_session)
    paths = {path: ops for path, ops in app.openapi()["paths"].items() if "{" in path}
    assert paths

    for path, operations in paths.items():
        url = re.sub(r"\{([^}]+)\}", lambda m: ids[m.group(1)], path)  # KeyError — новый вид объекта: добавьте его
        for method in operations:
            response = await api.request(
                method.upper(), url, json=BODIES.get((method, path)), headers=bearer(world.oleg)
            )
            assert response.status_code in (403, 404), f"{method.upper()} {path}: {response.status_code}"
    # ничего не изменилось
    assert (await period_of(api, world.admin, world.rent, world.kef))["status"] == "unpaid"
    assert await db_session.get(Attachment, uuid.UUID(ids["attachment_id"])) is not None


async def test_every_list_with_team_filter_refuses_another_team(app: FastAPI, api: AsyncClient, world: World) -> None:
    filtered = [
        path
        for path, operations in app.openapi()["paths"].items()
        if any(p["name"] == "team_id" and p["in"] == "query" for p in operations.get("get", {}).get("parameters", []))
    ]
    assert len(filtered) >= 6

    for path in filtered:
        response = await api.get(path, params={"team_id": str(world.kef.id)}, headers=bearer(world.oleg))
        assert response.status_code == 403, path


async def test_period_list_of_user_without_team_is_empty(
    api: AsyncClient, world: World, db_session: AsyncSession
) -> None:
    # Прежний админ, снятый сменой ADMIN_LOGIN, остаётся пользователем без команды: ему не видно ничего.
    oleg = await db_session.scalar(select(User).where(User.login == OLEG))
    assert oleg is not None
    oleg.team_id = None
    await db_session.flush()

    assert await items(api, world.oleg, "/payment-occurrences") == []
    payments = await items(api, world.oleg, "/recurring-payments")
    assert [(p["name"], p["team"], p["next_occurrence"]) for p in payments] == [
        ("Бухгалтерское сопровождение", None, None)  # общий виден, но периодов у него нет
    ]
    assert (await get(api, world.oleg, "/budgets")).json() == []


async def test_occurrence_team_moves_nothing_when_user_changes_team(
    api: AsyncClient, world: World, db_session: AsyncSession
) -> None:
    period = await period_of(api, world.anna, world.rent, world.kef)
    await api.patch(f"/api/v1/payment-occurrences/{period['id']}", json={"status": "paid"}, headers=bearer(world.anna))
    anna = await db_session.scalar(select(User).where(User.login == USER_LOGIN))
    assert anna is not None

    await api.patch(f"/api/v1/users/{anna.id}", json={"team_id": str(world.studio.id)}, headers=bearer(world.admin))

    stored = await db_session.get(PaymentOccurrence, uuid.UUID(period["id"]), populate_existing=True)
    assert stored is not None
    assert (stored.team_id, stored.paid_by) == (world.kef.id, anna.id)  # прошлая отметка осталась за Kefcoders
    assert (await get(api, world.anna, f"/payment-occurrences/{period['id']}")).status_code == 404


# ---------- общий платёж: прекращение, календарь, напоминания новой команды ----------


async def test_stopping_shared_payment_stops_it_for_every_team(api: AsyncClient, world: World) -> None:
    stopped = await api.delete(f"/api/v1/recurring-payments/{world.shared['id']}", headers=bearer(world.admin))

    periods = await items(api, world.admin, "/payment-occurrences", recurring_payment_id=world.shared["id"])
    assert stopped.status_code == 204
    assert periods == []  # будущие неоплаченные периоды убраны у всех команд


async def test_calendar_plans_shared_payment_for_each_team(api: AsyncClient, world: World) -> None:
    far = (await get(api, world.admin, "/payments/calendar", month="2027-03")).json()
    mine = (await get(api, world.anna, "/payments/calendar", month="2027-03")).json()

    def planned(body: dict[str, Any]) -> list[tuple[str, str]]:
        return sorted((p["name"], p["team"]["name"]) for day in body["days"] for p in day["planned"])

    assert planned(far) == [
        ("Adobe Creative Cloud", "Студия дизайна"),
        ("Аренда офиса", "Kefcoders"),
        ("Бухгалтерское сопровождение", "Kefcoders"),
        ("Бухгалтерское сопровождение", "Студия дизайна"),
    ]
    assert planned(mine) == [("Аренда офиса", "Kefcoders"), ("Бухгалтерское сопровождение", "Kefcoders")]


async def test_new_team_is_reminded_at_once_about_near_shared_due(
    api: AsyncClient, world: World, notifier: RecordingNotifier
) -> None:
    await _payment(api, world.admin, "Яндекс 360", None, next_due_date="2026-10-17")
    notifier.sent.clear()

    await api.post("/api/v1/teams", json={"name": "Отдел продаж"}, headers=bearer(world.admin))

    assert [(r.payment_name, r.team.name) for r in notifier.sent] == [("Яндекс 360", "Отдел продаж")]


async def test_channel_check_for_a_team_uses_its_chat(
    api: AsyncClient, world: World, notifier: RecordingNotifier, db_session: AsyncSession
) -> None:
    world.studio.telegram_chat_id = "-1001234567890"
    await db_session.flush()

    checked = await api.post(
        "/api/v1/notifications/test", params={"team_id": str(world.studio.id)}, headers=bearer(world.admin)
    )
    unknown = await api.post(
        "/api/v1/notifications/test", params={"team_id": str(uuid.uuid4())}, headers=bearer(world.admin)
    )

    assert checked.status_code == 200
    assert [(t.name, t.telegram_chat_id) if t else None for t in notifier.checked] == [
        ("Студия дизайна", "-1001234567890")
    ]
    assert unknown.status_code == 404
