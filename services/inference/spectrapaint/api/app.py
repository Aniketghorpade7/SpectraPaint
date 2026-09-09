"""The localhost REST contract.

    GET    /health
    POST   /sessions              (photo upload) -> { session_id }    <- issue #2
    GET    /sessions/{id}/events                  (progress stream)   <- issue #4
    GET    /sessions/{id}/planes                                        <- issue #6
    GET    /sessions/{id}/planes/{plane_id}/matte                       <- issue #6
    POST   /sessions/{id}/renders { assignments, mode }
    POST   /sessions/{id}/exports { assignments, mode }  -> JPEG      <- issue #12
    DELETE /sessions/{id}                                              <- issue #2
    GET    /catalogue                             (what is loaded)     <- issue #5
    GET    /catalogue/shades                      (browse or search)   <- issue #5
    GET    /catalogue/shades/{shade_code}                              <- issue #5
    GET|POST|PATCH|DELETE /bundles*          (the library)        <- issue #11
    GET|POST /consultations/{id}/*           (reopen, history)    <- issue #11

Every endpoint in the contract now exists.
"""

from collections.abc import Callable

from fastapi import Depends, FastAPI

from spectrapaint.api.auth import secret_required
from spectrapaint.api.bundles import router as bundles_router
from spectrapaint.api.catalogue import router as catalogue_router
from spectrapaint.api.errors import install_error_handlers
from spectrapaint.api.exports import router as exports_router
from spectrapaint.api.planes import router as planes_router
from spectrapaint.api.preparation import Stage, build_preparation_stages
from spectrapaint.api.renders import router as renders_router
from spectrapaint.api.sessions import SessionRegistry
from spectrapaint.api.sessions import router as sessions_router
from spectrapaint.api.storage import router as storage_router
from spectrapaint.catalogue import Catalogue, open_catalogue
from spectrapaint.storage import Store


def create_app(
    secret: str,
    catalogue: Catalogue | None = None,
    preparation_stages: Callable[[bytes], list[Stage]] = build_preparation_stages,
    store: Store | None = None,
) -> FastAPI:
    """Build the service, guarded by the per-launch secret.

    The secret is an argument rather than an environment read, so tests construct an app without
    touching process state and the runtime keeps its one place to decide where the secret came
    from (see spectrapaint.runtime).

    The Catalogue is an argument for the same reason, and defaults to whichever file the machine is
    configured with. It is loaded here, at construction, rather than on the first request: a service
    that starts happily and only discovers its Catalogue is unreadable when a Customer is at the
    counter has turned a setup problem into a Consultation problem.

    ``preparation_stages`` is an argument for the same reason too: tests inject deterministic stages
    so the progress stream is assertable without timing luck (ticket #4).

    ``store`` is where saved work lives. It is an argument so tests can point it at a throwaway
    directory; when it is not given there is no persistence — an in-memory service that forgets
    everything between restarts, which keeps existing behaviour exact for callers that have not
    opted in. Production passes one built at :func:`spectrapaint.storage.resolve_storage_dir`.
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
    app.state.session_registry = SessionRegistry(preparation_stages, store)
    app.state.catalogue = open_catalogue() if catalogue is None else catalogue
    app.state.store = store
    app.include_router(sessions_router)
    app.include_router(planes_router)
    app.include_router(renders_router)
    app.include_router(exports_router)
    app.include_router(catalogue_router)
    app.include_router(bundles_router)
    app.include_router(storage_router)

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
