from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, utc_now
from app.db import SessionDep
from app.services.telegram import create_link_code

router = APIRouter(prefix="/telegram", tags=["telegram"])


class LinkCodeOut(BaseModel):
    code: str
    expires_at: datetime


@router.post(
    "/link-code",
    response_model=LinkCodeOut,
    summary="Код для привязки Telegram к своей учётной записи",
    description="Отправьте боту в личном чате команду `/link <код>`. Код действует 10 минут и одноразовый.",
)
async def link_code(user: CurrentUser, session: SessionDep) -> LinkCodeOut:
    link = await create_link_code(session, user, now=utc_now())
    return LinkCodeOut(code=link.code, expires_at=link.expires_at)
