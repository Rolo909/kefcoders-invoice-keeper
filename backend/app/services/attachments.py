"""Чек (файл) или ссылка, прикреплённые к конкретной оплате.

Файлы лежат в UPLOAD_DIR под случайными именями (uuid + расширение) — имя от пользователя
хранится только в БД и никогда не используется как путь. Тип проверяется по содержимому файла,
а не по расширению или заголовку браузера.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import anyio
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.domain.enums import AttachmentKind, Role
from app.errors import AppError, forbidden, not_found
from app.models import Attachment, PaymentOccurrence, RecurringPayment, User
from app.services import audit
from app.services.audit import AuditAction

CHUNK_BYTES: Final = 64 * 1024
NAME_MAX_LENGTH: Final = 255
URL_MAX_LENGTH: Final = 2000
LINK_TITLE_LENGTH: Final = 60
UNSUPPORTED = "Подходят PDF, PNG, JPG и WebP"


@dataclass(frozen=True)
class FileType:
    content_type: str
    extension: str

    def matches(self, head: bytes) -> bool:
        if self.extension == ".pdf":
            return head.startswith(b"%PDF-")
        if self.extension == ".png":
            return head.startswith(b"\x89PNG\r\n\x1a\n")
        if self.extension == ".jpg":
            return head.startswith(b"\xff\xd8\xff")
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


FILE_TYPES: Final = {
    ".pdf": FileType("application/pdf", ".pdf"),
    ".png": FileType("image/png", ".png"),
    ".jpg": FileType("image/jpeg", ".jpg"),
    ".jpeg": FileType("image/jpeg", ".jpg"),
    ".webp": FileType("image/webp", ".webp"),
}


@dataclass(frozen=True)
class AttachmentView:
    attachment: Attachment
    uploaded_by: User | None


def _invalid(detail: str, code: str = "validation_error") -> AppError:
    return AppError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, detail)


def safe_display_name(filename: str | None) -> str:
    """Имя для показа: без пути и управляющих символов, не длиннее 255 символов."""
    name = re.split(r"[\\/]", filename or "")[-1]
    name = "".join(ch for ch in unicodedata.normalize("NFC", name) if unicodedata.category(ch)[0] != "C").strip()
    return name[:NAME_MAX_LENGTH] or "файл"


async def _occurrence_with_payment(
    session: AsyncSession, occurrence_id: uuid.UUID
) -> tuple[PaymentOccurrence, RecurringPayment]:
    row = (
        await session.execute(
            select(PaymentOccurrence, RecurringPayment)
            .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
            .where(PaymentOccurrence.id == occurrence_id)
        )
    ).first()
    if row is None:
        raise not_found("Период не найден")
    occurrence, payment = row
    return occurrence, payment


def _details(occurrence: PaymentOccurrence, payment: RecurringPayment, name: str) -> dict[str, str]:
    return {"payment_name": payment.name, "due_date": occurrence.due_date.isoformat(), "name": name}


async def list_attachments(session: AsyncSession, occurrence_id: uuid.UUID) -> list[AttachmentView]:
    await _occurrence_with_payment(session, occurrence_id)
    rows = await session.execute(
        select(Attachment, User)
        .outerjoin(User, User.id == Attachment.uploaded_by)
        .where(Attachment.occurrence_id == occurrence_id)
        .order_by(Attachment.created_at, Attachment.id)
    )
    return [AttachmentView(a, u) for a, u in rows]


async def _store_upload(upload: UploadFile, target: Path, file_type: FileType, max_bytes: int) -> int:
    """Потоковая запись во временный файл с проверкой размера и сигнатуры; возвращает размер."""
    partial = target.with_suffix(target.suffix + ".part")
    size = 0
    try:
        async with await anyio.open_file(partial, "wb") as out:
            while chunk := await upload.read(CHUNK_BYTES):
                if size == 0 and not file_type.matches(chunk[:16]):
                    raise _invalid("Содержимое файла не похоже на PDF, PNG, JPG или WebP", "unsupported_type")
                size += len(chunk)
                if size > max_bytes:
                    raise _invalid(
                        f"Файл больше {max_bytes // (1024 * 1024)} МБ. Сожмите его или прикрепите ссылку", "too_large"
                    )
                await out.write(chunk)
        if size == 0:
            raise _invalid("Файл пустой")
        await anyio.Path(partial).rename(target)
    finally:
        await anyio.Path(partial).unlink(missing_ok=True)
    return size


async def add_file(
    session: AsyncSession,
    occurrence_id: uuid.UUID,
    upload: UploadFile,
    *,
    actor: User,
    upload_dir: Path,
    max_bytes: int,
    ip: str | None,
) -> AttachmentView:
    occurrence, payment = await _occurrence_with_payment(session, occurrence_id)
    name = safe_display_name(upload.filename)
    file_type = FILE_TYPES.get(Path(name).suffix.lower())
    if file_type is None:
        raise _invalid(UNSUPPORTED, "unsupported_type")

    await anyio.Path(upload_dir).mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4()}{file_type.extension}"
    target = upload_dir / stored_name
    size = await _store_upload(upload, target, file_type, max_bytes)
    try:
        attachment = Attachment(
            occurrence_id=occurrence.id,
            kind=AttachmentKind.FILE,
            file_path=stored_name,
            original_name=name,
            content_type=file_type.content_type,
            size=size,
            uploaded_by=actor.id,
        )
        session.add(attachment)
        audit.record(
            session,
            AuditAction.ATTACHMENT_ADD,
            actor=actor,
            entity=("occurrence", occurrence.id),
            details=_details(occurrence, payment, name),
            ip=ip,
        )
        await session.commit()
    except BaseException:
        await anyio.Path(target).unlink(missing_ok=True)  # запись в БД не удалась — файл не нужен
        raise
    await session.refresh(attachment)
    return AttachmentView(attachment, actor)


def _check_url(url: str) -> str:
    value = url.strip()
    parts = urlsplit(value)
    if len(value) > URL_MAX_LENGTH or parts.scheme not in {"http", "https"} or "." not in (parts.hostname or ""):
        raise _invalid("Вставьте ссылку целиком, начиная с https://")
    return value


async def add_link(
    session: AsyncSession, occurrence_id: uuid.UUID, url: str, *, actor: User, ip: str | None
) -> AttachmentView:
    occurrence, payment = await _occurrence_with_payment(session, occurrence_id)
    link = _check_url(url)
    title = re.sub(r"^https?://", "", link)[:LINK_TITLE_LENGTH]
    attachment = Attachment(
        occurrence_id=occurrence.id, kind=AttachmentKind.LINK, url=link, original_name=title, uploaded_by=actor.id
    )
    session.add(attachment)
    audit.record(
        session,
        AuditAction.ATTACHMENT_ADD,
        actor=actor,
        entity=("occurrence", occurrence.id),
        details=_details(occurrence, payment, title),
        ip=ip,
    )
    await session.commit()
    await session.refresh(attachment)
    return AttachmentView(attachment, actor)


async def get_file(session: AsyncSession, attachment_id: uuid.UUID, *, upload_dir: Path) -> tuple[Attachment, Path]:
    attachment = await session.get(Attachment, attachment_id)
    if attachment is None or attachment.kind is not AttachmentKind.FILE or attachment.file_path is None:
        raise not_found("Вложение не найдено")
    path = upload_dir / attachment.file_path
    if not await anyio.Path(path).is_file():
        raise not_found("Файл вложения не найден на сервере")
    return attachment, path


async def delete_attachment(
    session: AsyncSession, attachment_id: uuid.UUID, *, actor: User, upload_dir: Path, ip: str | None
) -> None:
    attachment = await session.get(Attachment, attachment_id)
    if attachment is None:
        raise not_found("Вложение не найдено")
    if attachment.uploaded_by != actor.id and actor.role is not Role.ADMIN:
        raise forbidden("Удалить вложение может только автор или администратор")
    occurrence, payment = await _occurrence_with_payment(session, attachment.occurrence_id)
    file_path = attachment.file_path
    audit.record(
        session,
        AuditAction.ATTACHMENT_DELETE,
        actor=actor,
        entity=("occurrence", occurrence.id),
        details=_details(occurrence, payment, attachment.original_name),
        ip=ip,
    )
    await session.delete(attachment)
    await session.commit()
    if file_path is not None:
        await anyio.Path(upload_dir / file_path).unlink(missing_ok=True)
