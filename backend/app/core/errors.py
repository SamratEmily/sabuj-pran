import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


class AppError(Exception):
    """Raise from services for any expected failure. Rendered as {detail, code}."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def _error(status_code: int, code: str, detail: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, "code": code, **extra})


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return _error(exc.status_code, exc.code, exc.detail)


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = HTTP_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail), "code": code},
        headers=exc.headers,
    )


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # `errors` lets forms show messages next to the right field.
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    first = errors[0] if errors else None
    detail = f"{'.'.join(map(str, first['loc'][1:]))}: {first['msg']}" if first else "Invalid input"
    return _error(422, "VALIDATION_ERROR", detail, errors=errors)


async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    # A unique key won a race that the service's own pre-check could not see (e.g. two
    # users saving the same record at once). The request's transaction is rolled back.
    logger.warning("Integrity error: %s", exc.orig)
    return _error(
        409, "CONFLICT", "This conflicts with a record saved at the same time. Reload and retry."
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return _error(500, "INTERNAL_ERROR", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
