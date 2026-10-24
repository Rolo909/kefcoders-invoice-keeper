from app.domain.enums import NotificationChannel
from app.services.notifiers.base import Reminder, SendResult, TeamTarget


class InAppNotifier:
    """Уведомление в колокольчике панели: «доставка» — это сама запись в журнале уведомлений.

    Работает без внешних сервисов и настроек, поэтому видно в любом окружении — даже без Telegram.
    """

    channel = NotificationChannel.INAPP

    async def send(self, reminder: Reminder) -> SendResult:
        return SendResult(ok=True)

    async def check(self, team: TeamTarget | None = None) -> SendResult:
        return SendResult(ok=True)
