"""Чек или ссылка к оплате; журнал действий и журнал напоминаний (дополнительные возможности кейса)."""

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from tests.conftest import ADMIN_LOGIN, ADMIN_PASSWORD, USER_LOGIN, USER_PASSWORD, bearer, login

UPLOAD_DIR = Path(os.environ["UPLOAD_DIR"])
PDF = b"%PDF-1.4\n% test receipt\n" + b"0" * 1000
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


def uploaded_files() -> set[Path]:
    return set(UPLOAD_DIR.iterdir())


@pytest.fixture
async def admin_token(api: AsyncClient, admin: User) -> str:
    return await login(api, ADMIN_LOGIN, ADMIN_PASSWORD)


@pytest.fixture
async def user_token(api: AsyncClient, regular_user: User) -> str:
    return await login(api, USER_LOGIN, USER_PASSWORD)


@pytest.fixture
async def period_id(api: AsyncClient, admin_token: str) -> str:
    due = (date.today() + timedelta(days=10)).isoformat()
    response = await api.post(
        "/api/v1/recurring-payments",
        json={"name": "МТС Бизнес", "amount": "3900", "currency": "RUB", "next_due_date": due},
        headers=bearer(admin_token),
    )
    assert response.status_code == 201, response.text
    result: str = response.json()["next_occurrence"]["id"]
    return result


async def upload(
    api: AsyncClient, token: str, period: str, name: str, content: bytes, mime: str = "application/pdf"
) -> Any:
    return await api.post(
        f"/api/v1/payment-occurrences/{period}/attachments",
        files={"file": (name, content, mime)},
        headers=bearer(token),
    )


# ---------- файлы ----------


async def test_user_attaches_receipt_and_downloads_it(
    api: AsyncClient, user_token: str, period_id: str, db_session: AsyncSession
) -> None:
    created = await upload(api, user_token, period_id, "чек-октябрь.pdf", PDF)

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["kind"], body["original_name"], body["content_type"], body["size"]) == (
        "file",
        "чек-октябрь.pdf",
        "application/pdf",
        len(PDF),
    )
    assert body["uploaded_by"]["login"] == USER_LOGIN
    downloaded = await api.get(f"/api/v1/attachments/{body['id']}/download", headers=bearer(user_token))
    assert downloaded.status_code == 200
    assert downloaded.content == PDF
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert "inline" in downloaded.headers["content-disposition"]


async def test_attachment_is_listed_and_counted_on_period(api: AsyncClient, user_token: str, period_id: str) -> None:
    await upload(api, user_token, period_id, "receipt.png", PNG, "image/png")

    listed = await api.get(f"/api/v1/payment-occurrences/{period_id}/attachments", headers=bearer(user_token))
    period = await api.get(f"/api/v1/payment-occurrences/{period_id}", headers=bearer(user_token))

    assert [a["original_name"] for a in listed.json()] == ["receipt.png"]
    assert period.json()["attachments_count"] == 1
    assert [h["action"] for h in period.json()["history"]] == ["attachment.add"]
    assert period.json()["history"][0]["details"]["name"] == "receipt.png"


@pytest.mark.parametrize(
    ("name", "content", "code"),
    [
        ("virus.exe", b"MZ\x90\x00", "unsupported_type"),
        ("fake.pdf", b"MZ\x90\x00 not a pdf", "unsupported_type"),
        ("photo.jpg", PNG, "unsupported_type"),
        ("empty.pdf", b"", "validation_error"),
    ],
)
async def test_unsafe_or_wrong_files_are_rejected(
    api: AsyncClient, user_token: str, period_id: str, name: str, content: bytes, code: str
) -> None:
    files_before = uploaded_files()

    response = await upload(api, user_token, period_id, name, content)

    assert response.status_code == 422
    assert response.json()["code"] == code
    assert uploaded_files() == files_before  # ничего не осталось на диске


async def test_file_over_size_limit_is_rejected(api: AsyncClient, user_token: str, period_id: str) -> None:
    response = await upload(api, user_token, period_id, "big.pdf", PDF + b"0" * (10 * 1024 * 1024))

    assert response.status_code == 422
    assert response.json()["code"] == "too_large"


async def test_file_name_cannot_escape_upload_folder(api: AsyncClient, user_token: str, period_id: str) -> None:
    response = await upload(api, user_token, period_id, "../../../etc/passwd.pdf", PDF)

    assert response.json()["original_name"] == "passwd.pdf"
    assert not (UPLOAD_DIR.parent / "passwd.pdf").exists()


async def test_download_requires_login(api: AsyncClient, user_token: str, period_id: str) -> None:
    attachment = (await upload(api, user_token, period_id, "receipt.pdf", PDF)).json()
    api.cookies.clear()

    response = await api.get(f"/api/v1/attachments/{attachment['id']}/download")

    assert response.status_code == 401


async def test_unknown_period_is_not_found(api: AsyncClient, user_token: str) -> None:
    response = await upload(api, user_token, "00000000-0000-0000-0000-000000000000", "receipt.pdf", PDF)

    assert response.status_code == 404


# ---------- ссылки ----------


async def test_link_is_attached(api: AsyncClient, user_token: str, period_id: str) -> None:
    url = "https://github.com/organizations/kefcoders/settings/billing"

    response = await api.post(
        f"/api/v1/payment-occurrences/{period_id}/attachments", json={"url": url}, headers=bearer(user_token)
    )

    body = response.json()
    assert response.status_code == 201
    assert (body["kind"], body["url"], body["size"]) == ("link", url, None)
    assert body["original_name"] == url.removeprefix("https://")[:60]
    download = await api.get(f"/api/v1/attachments/{body['id']}/download", headers=bearer(user_token))
    assert download.status_code == 404


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://files.ru/a.pdf", "просто текст", "https://localhost"])
async def test_bad_link_is_rejected(api: AsyncClient, user_token: str, period_id: str, url: str) -> None:
    response = await api.post(
        f"/api/v1/payment-occurrences/{period_id}/attachments", json={"url": url}, headers=bearer(user_token)
    )

    assert response.status_code == 422


# ---------- удаление ----------


async def test_only_author_or_admin_can_delete(
    api: AsyncClient, admin_token: str, user_token: str, period_id: str
) -> None:
    by_admin = (await upload(api, admin_token, period_id, "admin.pdf", PDF)).json()
    by_user = (await upload(api, user_token, period_id, "anna.pdf", PDF)).json()

    foreign = await api.delete(f"/api/v1/attachments/{by_admin['id']}", headers=bearer(user_token))
    own = await api.delete(f"/api/v1/attachments/{by_user['id']}", headers=bearer(user_token))
    admin = await api.delete(f"/api/v1/attachments/{by_admin['id']}", headers=bearer(admin_token))

    assert (foreign.status_code, own.status_code, admin.status_code) == (403, 204, 204)
    listed = await api.get(f"/api/v1/payment-occurrences/{period_id}/attachments", headers=bearer(admin_token))
    assert listed.json() == []


async def test_deleted_attachment_file_is_removed_from_disk(api: AsyncClient, user_token: str, period_id: str) -> None:
    files_before = uploaded_files()
    attachment = (await upload(api, user_token, period_id, "receipt.pdf", PDF)).json()
    assert len(uploaded_files() - files_before) == 1

    await api.delete(f"/api/v1/attachments/{attachment['id']}", headers=bearer(user_token))

    assert uploaded_files() == files_before


async def test_attachment_of_deleted_user_keeps_readable_author(
    api: AsyncClient, admin_token: str, user_token: str, period_id: str, regular_user: User
) -> None:
    await upload(api, user_token, period_id, "receipt.pdf", PDF)
    await api.delete(f"/api/v1/users/{regular_user.id}", headers=bearer(admin_token))

    listed = await api.get(f"/api/v1/payment-occurrences/{period_id}/attachments", headers=bearer(admin_token))

    assert listed.json()[0]["uploaded_by"]["full_name"] == "Удалённый пользователь"


# ---------- журналы ----------


async def test_audit_log_is_for_admin_only(api: AsyncClient, user_token: str) -> None:
    assert (await api.get("/api/v1/audit-logs", headers=bearer(user_token))).status_code == 403
    assert (await api.get("/api/v1/notifications", headers=bearer(user_token))).status_code == 403


async def test_audit_log_lists_newest_first_and_filters(
    api: AsyncClient, admin_token: str, user_token: str, regular_user: User, period_id: str
) -> None:
    await upload(api, user_token, period_id, "receipt.pdf", PDF)

    everything = (await api.get("/api/v1/audit-logs", headers=bearer(admin_token))).json()
    auth_only = (await api.get("/api/v1/audit-logs", params={"action": "auth"}, headers=bearer(admin_token))).json()
    by_anna = (
        await api.get("/api/v1/audit-logs", params={"actor_id": str(regular_user.id)}, headers=bearer(admin_token))
    ).json()

    assert everything["items"][0]["action"] == "attachment.add"
    assert {i["action"] for i in auth_only["items"]} == {"auth.login"}
    assert {i["actor_login"] for i in by_anna["items"]} == {USER_LOGIN}
    assert everything["total"] >= auth_only["total"] + 2


async def test_audit_log_date_filter(api: AsyncClient, admin_token: str) -> None:
    today = date.today()

    tomorrow = await api.get(
        "/api/v1/audit-logs", params={"date_from": (today + timedelta(days=2)).isoformat()}, headers=bearer(admin_token)
    )
    recent = await api.get(
        "/api/v1/audit-logs", params={"date_from": (today - timedelta(days=1)).isoformat()}, headers=bearer(admin_token)
    )

    assert tomorrow.json()["total"] == 0
    assert recent.json()["total"] >= 1


async def test_notification_log_shows_reminders(api: AsyncClient, admin_token: str) -> None:
    due = (date.today() + timedelta(days=1)).isoformat()
    await api.post(
        "/api/v1/recurring-payments",
        json={"name": "Бухгалтерия", "amount": "25000", "currency": "RUB", "next_due_date": due},
        headers=bearer(admin_token),
    )

    sent = await api.get(
        "/api/v1/notifications", params={"channel": "telegram", "status": "sent"}, headers=bearer(admin_token)
    )
    failed = await api.get("/api/v1/notifications", params={"status": "failed"}, headers=bearer(admin_token))

    assert [(n["payment_name"], n["due_date"], n["kind"]) for n in sent.json()["items"]] == [
        ("Бухгалтерия", due, "before_due")
    ]
    assert failed.json()["total"] == 0
