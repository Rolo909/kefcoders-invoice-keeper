"""Напоминания: критерий приёмки «Минимум за 3 дня, без дублей; оплаченный период — без напоминания;
удалённый платёж не напоминает» (TASK_PLAN §4.5)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Currency, NotificationKind, NotificationStatus, OccurrenceStatus, Period
from app.models import Notification, PaymentOccurrence, RecurringPayment, Team, User
from app.services.notifiers.base import SendResult
from app.services.occurrences import ensure_occurrences, update_occurrence
from app.services.payments import stop_payment
from app.services.reminders import MAX_ATTEMPTS, ReminderDispatcher
from tests.conftest import RecordingNotifier

DUE = date(2026, 10, 25)


async def add_payment(
    session: AsyncSession, author: User, *, due: date = DUE, name: str = "Аренда офиса", today: date = DUE
) -> RecurringPayment:
    payment = RecurringPayment(
        name=name,
        amount=Decimal("50000.00"),
        currency=Currency.RUB,
        period=Period.MONTHLY,
        first_due_date=due,
        created_by=author.id,
    )
    session.add(payment)
    if await session.scalar(select(Team.id).limit(1)) is None:  # периоды создаются у команд
        session.add(Team(name="Kefcoders", created_at=datetime(2020, 1, 1, tzinfo=UTC)))
    await session.flush()
    await ensure_occurrences(session, [payment], today=today - timedelta(days=10), horizon_days=60)
    return payment


async def first_period(session: AsyncSession, payment: RecurringPayment) -> PaymentOccurrence:
    period = await session.scalar(
        select(PaymentOccurrence).where(
            PaymentOccurrence.recurring_payment_id == payment.id, PaymentOccurrence.seq == 0
        )
    )
    assert period is not None
    return period


async def notifications(session: AsyncSession) -> list[Notification]:
    return list(await session.scalars(select(Notification).execution_options(populate_existing=True)))


async def test_no_reminder_earlier_than_three_days(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    await add_payment(db_session, admin)

    assert await reminders.run(today=DUE - timedelta(days=4)) == 0
    assert notifier.sent == []


async def test_exactly_one_reminder_during_whole_three_day_window(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    await add_payment(db_session, admin)

    for days_before in (3, 2, 1, 0):
        await reminders.run(today=DUE - timedelta(days=days_before))
        await reminders.run(today=DUE - timedelta(days=days_before))  # повторная проверка в тот же день

    assert len(notifier.sent) == 1
    reminder = notifier.sent[0]
    assert (reminder.payment_name, reminder.amount, reminder.currency, reminder.due_date) == (
        "Аренда офиса",
        Decimal("50000.00"),
        Currency.RUB,
        DUE,
    )
    assert (reminder.kind, reminder.today) == (NotificationKind.BEFORE_DUE, DUE - timedelta(days=3))
    [stored] = await notifications(db_session)
    assert (stored.status, stored.attempts, stored.telegram_message_id) == (NotificationStatus.SENT, 1, 1)


async def test_paid_period_is_not_reminded(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    period = await first_period(db_session, await add_payment(db_session, admin))
    await update_occurrence(
        db_session,
        period.id,
        new_status=OccurrenceStatus.PAID,
        paid_date=None,
        actor=admin,
        today=DUE - timedelta(days=5),
        now=datetime.now(UTC),
        ip=None,
    )

    assert await reminders.run(today=DUE - timedelta(days=2)) == 0
    assert notifier.sent == []


async def test_stopped_payment_is_not_reminded(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    payment = await add_payment(db_session, admin)
    await stop_payment(
        db_session, payment.id, actor=admin, today=DUE - timedelta(days=5), now=datetime.now(UTC), ip=None
    )

    assert await reminders.run(today=DUE - timedelta(days=2)) == 0


async def test_failed_send_is_retried_and_delivered_once(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    await add_payment(db_session, admin)
    today = DUE - timedelta(days=2)
    notifier.failure = SendResult(ok=False, error="Telegram недоступен")

    assert await reminders.run(today=today) == 0
    [failed] = await notifications(db_session)
    assert (failed.status, failed.attempts, failed.last_error) == (NotificationStatus.FAILED, 1, "Telegram недоступен")

    notifier.failure = None
    assert await reminders.run(today=today) == 1
    assert await reminders.run(today=today) == 0
    [sent] = await notifications(db_session)
    assert (sent.status, sent.attempts, sent.last_error) == (NotificationStatus.SENT, 2, None)


async def test_retries_stop_after_max_attempts(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    await add_payment(db_session, admin)
    today = DUE - timedelta(days=2)
    notifier.failure = SendResult(ok=False, error="ошибка")
    for _ in range(MAX_ATTEMPTS + 2):
        await reminders.run(today=today)

    notifier.failure = None

    assert await reminders.run(today=today) == 0
    [stored] = await notifications(db_session)
    assert stored.attempts == MAX_ATTEMPTS


async def test_unconfigured_channel_does_not_burn_attempts(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    await add_payment(db_session, admin)
    today = DUE - timedelta(days=2)
    notifier.failure = SendResult(ok=False, error="Telegram не настроен", attempted=False)
    for _ in range(MAX_ATTEMPTS + 2):
        await reminders.run(today=today)

    notifier.failure = None  # токен задали — напоминание уходит

    assert await reminders.run(today=today) == 1


async def test_stale_claim_of_crashed_process_is_taken_over(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher
) -> None:
    period = await first_period(db_session, await add_payment(db_session, admin))
    db_session.add(
        Notification(
            occurrence_id=period.id,
            channel="telegram",
            kind=NotificationKind.BEFORE_DUE,
            status=NotificationStatus.PENDING,
            claimed_at=func.now() - timedelta(minutes=30),
        )
    )
    await db_session.flush()

    assert await reminders.run(today=DUE - timedelta(days=1)) == 1


async def test_fresh_claim_of_another_process_is_left_alone(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher
) -> None:
    period = await first_period(db_session, await add_payment(db_session, admin))
    db_session.add(
        Notification(
            occurrence_id=period.id,
            channel="telegram",
            kind=NotificationKind.BEFORE_DUE,
            status=NotificationStatus.PENDING,
            claimed_at=func.now(),
        )
    )
    await db_session.flush()

    assert await reminders.run(today=DUE - timedelta(days=1)) == 0


async def test_overdue_notice_is_sent_once_right_after_due_date(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    await add_payment(db_session, admin)

    for days_after in (1, 2, 3):
        await reminders.run(today=DUE + timedelta(days=days_after))

    assert [r.kind for r in notifier.sent] == [NotificationKind.OVERDUE]


async def test_long_overdue_periods_do_not_spam(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    await add_payment(db_session, admin, due=DUE - timedelta(days=20))

    await reminders.run(today=DUE)

    assert notifier.sent == []


async def test_reminders_can_be_limited_to_one_payment(
    db_session: AsyncSession, admin: User, reminders: ReminderDispatcher, notifier: RecordingNotifier
) -> None:
    await add_payment(db_session, admin, name="Аренда")
    server = await add_payment(db_session, admin, name="Сервер")

    await reminders.run(today=DUE - timedelta(days=1), payment_id=server.id)

    assert [r.payment_name for r in notifier.sent] == ["Сервер"]
    total = await db_session.scalar(select(func.count()).select_from(Notification))
    assert total == 1
