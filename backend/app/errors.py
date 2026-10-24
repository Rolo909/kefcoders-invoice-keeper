"""Ошибки приложения в едином формате ответа {"detail": "...", "code": "..."} (TASK_PLAN §5.4)."""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.validation_messages import validation_detail

_CODE_BY_STATUS = {
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
}


class AppError(Exception):
    """Ожидаемая ошибка бизнес-логики: текст `detail` показывается пользователю как есть."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def unauthorized() -> AppError:
    return AppError(status.HTTP_401_UNAUTHORIZED, "unauthorized", "Войдите в систему")


def forbidden(detail: str = "Недостаточно прав: действие доступно только администратору") -> AppError:
    return AppError(status.HTTP_403_FORBIDDEN, "forbidden", detail)


def not_found(detail: str) -> AppError:
    return AppError(status.HTTP_404_NOT_FOUND, "not_found", detail)


def _body(detail: str, code: str) -> dict[str, str]:
    return {"detail": detail, "code": code}


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise exc
    return JSONResponse(_body(exc.detail, exc.code), status_code=exc.status_code)


async def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    code = _CODE_BY_STATUS.get(exc.status_code, "error")
    return JSONResponse(_body(str(exc.detail), code), status_code=exc.status_code, headers=exc.headers)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    return JSONResponse(
        _body(validation_detail(exc.errors()), "validation_error"), status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
