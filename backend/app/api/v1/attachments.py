import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError
from starlette.datastructures import UploadFile

from app.api.deps import CurrentUser, SettingsDep, client_ip
from app.config import Settings
from app.db import SessionDep
from app.domain.enums import AttachmentKind
from app.errors import AppError
from app.schemas.user import UserBrief
from app.services import attachments as attachments_service
from app.services.attachments import AttachmentView

router = APIRouter(tags=["attachments"])

# Автора вложения удалили: панель показывает имя автора, поэтому null не отдаём.
DELETED_USER = UserBrief(id=uuid.UUID(int=0), login="deleted", full_name="Удалённый пользователь")


class AttachmentOut(BaseModel):
    id: uuid.UUID
    occurrence_id: uuid.UUID
    kind: AttachmentKind
    url: str | None
    original_name: str
    content_type: str | None
    size: int | None
    uploaded_by: UserBrief
    created_at: datetime


class LinkIn(BaseModel):
    url: str


def _out(view: AttachmentView) -> AttachmentOut:
    a = view.attachment
    return AttachmentOut(
        id=a.id,
        occurrence_id=a.occurrence_id,
        kind=a.kind,
        url=a.url,
        original_name=a.original_name,
        content_type=a.content_type,
        size=a.size,
        uploaded_by=UserBrief.model_validate(view.uploaded_by) if view.uploaded_by else DELETED_USER,
        created_at=a.created_at,
    )


def _upload_dir(settings: Settings) -> Path:
    return Path(settings.upload_dir)


def _invalid(detail: str) -> AppError:
    return AppError(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", detail)


_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary", "description": "PDF, PNG, JPG, WebP"}
                    },
                }
            },
            "application/json": {
                "schema": {"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}}
            },
        },
    }
}


@router.get(
    "/payment-occurrences/{occurrence_id}/attachments",
    response_model=list[AttachmentOut],
    summary="Чеки и ссылки, прикреплённые к оплате",
)
async def list_attachments(occurrence_id: uuid.UUID, session: SessionDep) -> list[AttachmentOut]:
    return [_out(v) for v in await attachments_service.list_attachments(session, occurrence_id)]


@router.post(
    "/payment-occurrences/{occurrence_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Прикрепить к оплате чек (файл до UPLOAD_MAX_MB) или ссылку",
    openapi_extra=_UPLOAD_BODY,
)
async def add_attachment(
    occurrence_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> AttachmentOut:
    ip = client_ip(request)
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form(max_files=1, max_fields=1)
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise _invalid("Выберите файл чека")
        view = await attachments_service.add_file(
            session,
            occurrence_id,
            upload,
            actor=user,
            upload_dir=_upload_dir(settings),
            max_bytes=settings.upload_max_mb * 1024 * 1024,
            ip=ip,
        )
    else:
        try:
            link = LinkIn.model_validate_json(await request.body())
        except ValidationError as exc:
            raise _invalid('Передайте файл (multipart, поле file) или JSON {"url": "https://…"}') from exc
        view = await attachments_service.add_link(session, occurrence_id, link.url, actor=user, ip=ip)
    return _out(view)


@router.get(
    "/attachments/{attachment_id}/download",
    response_class=FileResponse,
    summary="Скачать файл чека",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Вложение не найдено или это ссылка"}},
)
async def download(attachment_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> FileResponse:
    attachment, path = await attachments_service.get_file(session, attachment_id, upload_dir=_upload_dir(settings))
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.original_name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить вложение (автор или администратор)",
)
async def delete_attachment(
    attachment_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> None:
    await attachments_service.delete_attachment(
        session, attachment_id, actor=user, upload_dir=_upload_dir(settings), ip=client_ip(request)
    )
