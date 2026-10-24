from zoneinfo import ZoneInfo

from app.config import Settings
from app.services.reminders import ReminderDispatcher
from app.worker import build_scheduler


def test_worker_checks_reminders_at_start_and_periodically() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+asyncpg://u:p@db/x", admin_password="long-enough")
    dispatcher = ReminderDispatcher(None, [], remind_days_before=3, timezone=ZoneInfo("Europe/Moscow"))  # type: ignore[arg-type]

    scheduler = build_scheduler(settings, dispatcher)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"reminders", "cleanup"}
    assert jobs["reminders"].trigger.interval.total_seconds() == settings.reminder_check_interval_minutes * 60
    assert jobs["reminders"].max_instances == 1
