# api — the REST contract

    GET    /health                                -> { status }
    POST   /sessions              (photo upload) -> { session_id }
    GET    /sessions/{id}/events                  (progress stream)
    GET    /sessions/{id}/planes
    POST   /sessions/{id}/renders { assignments, mode }
    DELETE /sessions/{id}

Encode-once is enforced structurally, by omission: a photo enters only through `POST /sessions`,
and there is deliberately no endpoint accepting an image and a Shade together.

Note: the browser `EventSource` API cannot set custom headers, so the progress stream is consumed
with a fetch-based streaming reader. Do not pass the secret as a query parameter.

## Authentication

Every request carries the per-launch secret as `Authorization: Bearer <secret>`. The guard is
registered on the application, not on individual routes, so a new endpoint is authenticated by
default rather than by remembering to add a dependency. `/health` is authenticated too — Electron's
first successful call is what proves the handshake worked.

Rejections are `401` and are identical whether the header was absent, malformed or wrong.

## Errors

One shape, everywhere, defined in `errors.py`:

    { "code": "<machine-readable>", "message": "<plain language, safe to show the Dealer>" }

Add new codes to the vocabulary at the top of `errors.py`, never inline at a call site.
