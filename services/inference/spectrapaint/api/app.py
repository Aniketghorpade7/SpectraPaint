"""The localhost REST contract.

    GET    /health                                (this ticket)
    POST   /sessions              (photo upload) -> { session_id }    <- issue #2
    GET    /sessions/{id}/events                  (progress stream)
    GET    /sessions/{id}/planes
    POST   /sessions/{id}/renders { assignments, mode }
    DELETE /sessions/{id}                                              <- issue #2

The session endpoints exist (issue #2). The rest arrive with the tickets that need them.
"""

from fastapi import Depends, FastAPI

from spectrapaint.api.auth import secret_required
from spectrapaint.api.errors import install_error_handlers
from spectrapaint.api.renders import router as renders_router
from spectrapaint.api.sessions import SessionRegistry
from spectrapaint.api.sessions import router as sessions_router


def create_app(secret: str) -> FastAPI:
    """Build the service, guarded by the per-launch secret.

    The secret is an argument rather than an environment read, so tests construct an app without
    touching process state and the runtime keeps its one place to decide where the secret came
    from (see spectrapaint.runtime).
    """

    app = FastAPI(
        title="SpectraPaint inference service",
        version="0.1.0",
        # No interactive docs: this is a hardened localhost service, not a public API. The contract
        # lives in docs/specs/v1-spectrapaint.md, which is where it belongs anyway.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        # Applied to every route, so authentication cannot be forgotten on a new endpoint.
        dependencies=[Depends(secret_required(secret))],
    )

    install_error_handlers(app)
    app.state.session_registry = SessionRegistry()
    app.include_router(sessions_router)
    app.include_router(renders_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Readiness probe. Authenticated like everything else — Electron's first successful call
        is what proves the secret handshake worked, so an unauthenticated probe would prove less.
        """
        return {"status": "ready"}

    return app


# Note: no CORS middleware, deliberately. Without CORS headers a browser refuses to read a
# cross-origin response, which closes the "web page open in the Dealer's browser" half of the risk;
# the secret closes the "any local process" half.
