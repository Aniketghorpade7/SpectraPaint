"""Per-launch secret, required on every request.

Localhost is not private. Any other process on the machine — and any web page open in the Dealer's
browser — can reach a service bound to loopback. With Customer room photographs stored on that
machine, an unprotected service is a real exposure, not a theoretical one. See
docs/design-decisions.md §13.

Electron generates a fresh secret each launch and passes it to both the service and the preload
script; the renderer never holds it.
"""

import hmac

from fastapi import Header

from spectrapaint.api.errors import UNAUTHORISED, ServiceError

_BEARER_PREFIX = "Bearer "

# Deliberately identical whether the header is absent, malformed or simply wrong: a caller learns
# only that it failed. Plain language, because docs/conventions.md §5 allows the UI to show any
# message as-is — even one it should never actually reach.
_REJECTION = "SpectraPaint could not verify this request."


def secret_required(secret: str):
    """Build the dependency that guards every route.

    Applied once at the application level rather than per-route, so a new endpoint is authenticated
    by default and cannot be added unguarded by omission.
    """

    if not secret:
        raise ValueError("The service refuses to start without a per-launch secret.")

    async def require_secret(authorization: str | None = Header(default=None)) -> None:
        if not _presented_secret_matches(authorization, secret):
            raise ServiceError(status_code=401, code=UNAUTHORISED, message=_REJECTION)

    return require_secret


def _presented_secret_matches(authorization: str | None, secret: str) -> bool:
    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        return False

    presented = authorization[len(_BEARER_PREFIX) :]
    # compare_digest, not ==, so the comparison does not leak the secret's prefix through timing.
    return hmac.compare_digest(presented, secret)
