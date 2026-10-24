import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import AdminUser, client_ip
from app.db import SessionDep
from app.schemas.common import DEFAULT_PAGE_SIZE, LimitQuery, OffsetQuery, Page
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])

_SYSTEM_USER_RESPONSES: dict[int | str, dict[str, str]] = {
    status.HTTP_403_FORBIDDEN: {"description": "Администратора из .env нельзя менять или удалять"},
    status.HTTP_404_NOT_FOUND: {"description": "Пользователь не найден"},
}


@router.get("", response_model=Page[UserOut], summary="Список пользователей")
async def list_users(
    _: AdminUser, session: SessionDep, limit: LimitQuery = DEFAULT_PAGE_SIZE, offset: OffsetQuery = 0
) -> Page[UserOut]:
    users, total = await users_service.list_users(session, limit=limit, offset=offset)
    return Page(items=[UserOut.model_validate(u) for u in users], total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создание обычного пользователя",
    responses={status.HTTP_409_CONFLICT: {"description": "Логин уже занят"}},
)
async def create_user(body: UserCreate, admin: AdminUser, request: Request, session: SessionDep) -> UserOut:
    user = await users_service.create_user(session, body, actor=admin, ip=client_ip(request))
    return UserOut.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    summary="Изменение пользователя",
    responses={**_SYSTEM_USER_RESPONSES, status.HTTP_409_CONFLICT: {"description": "Логин уже занят"}},
)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, admin: AdminUser, request: Request, session: SessionDep
) -> UserOut:
    user = await users_service.update_user(session, user_id, body, actor=admin, ip=client_ip(request))
    return UserOut.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление пользователя",
    responses=_SYSTEM_USER_RESPONSES,
)
async def delete_user(user_id: uuid.UUID, admin: AdminUser, request: Request, session: SessionDep) -> None:
    await users_service.delete_user(session, user_id, actor=admin, ip=client_ip(request))
