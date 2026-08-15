# api — the REST contract

    POST   /sessions              (photo upload) -> { session_id }
    GET    /sessions/{id}/events                  (progress stream)
    GET    /sessions/{id}/planes
    POST   /sessions/{id}/renders { assignments, mode }
    DELETE /sessions/{id}

Encode-once is enforced structurally, by omission: a photo enters only through `POST /sessions`,
and there is deliberately no endpoint accepting an image and a Shade together.

Note: the browser `EventSource` API cannot set custom headers, so the progress stream is consumed
with a fetch-based streaming reader. Do not pass the secret as a query parameter.
