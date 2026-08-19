"""Error shape for the REST contract.

Every failure the service returns carries a machine-readable ``code`` and a ``message`` written in
plain language that the UI may show to the Dealer as-is. Messages name no model and no technique —
"Finding the walls in your photo…", never "SAM 2 inference failed". See docs/conventions.md §5.

Keeping one shape here, rather than letting each router invent its own, is what stops fifteen
tickets worked in isolated contexts from producing fifteen error formats.
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# The error vocabulary. Add to it here, never inline at a call site.
UNAUTHORISED = "unauthorised"
MALFORMED_REQUEST = "malformed_request"
SESSION_NOT_FOUND = "session_not_found"
UNSUPPORTED_IMAGE = "unsupported_image"
PHOTO_TOO_LARGE = "photo_too_large"


class ServiceError(Exception):
    """A failure with a code the UI can branch on and a message it can display."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_body(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def install_error_handlers(app: FastAPI) -> None:
    """Route every failure through the one response shape."""

    @app.exception_handler(ServiceError)
    async def _handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        # FastAPI's default validation body is a different shape and leaks internal field paths.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error_body(
                MALFORMED_REQUEST,
                "SpectraPaint could not read that request. Please try again.",
            ),
        )
