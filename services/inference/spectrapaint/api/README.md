# api — the REST contract

    GET    /health                                -> { status }
    POST   /sessions              (photo upload) -> { session_id }
    GET    /sessions/{id}/events                  (progress stream)
    GET    /sessions/{id}/planes
    POST   /sessions/{id}/renders { assignments, mode }
    DELETE /sessions/{id}
    GET    /catalogue                             -> { catalogue_id, version, shade_families, ... }
    GET    /catalogue/shades      ?q= &shade_family= &limit= &offset=
    GET    /catalogue/shades/{shade_code}         -> one Shade

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

## The Catalogue endpoints

Read-only, all three. The Catalogue is a data file the service was pointed at — swapping the file is
how it changes (`data/catalogue/README.md`), so there is no endpoint that adds, edits or deletes a
Shade.

`GET /catalogue/shades` both searches and browses, because to the Dealer they are one panel that
switches on every keystroke:

| | |
|---|---|
| `q` present | Ranked shortlist: exact Shade Code, then code prefix, then name prefix, then name substring. Response carries `searched: true`, and `total` is how many came back. |
| `q` absent | A page of the Catalogue in Fandeck order, optionally within one `shade_family`. `searched: false`, and `total` is the true count, so a virtualised list can size its scrollbar before it has the rows. |

`q` together with a non-zero `offset` is a `422`, not a silently ignored parameter — a caller paging
a search would get a ranking where it expected a page, with nothing in the response to reveal it.

Page sizes are bounded: 500 browsing, 200 searching.

The Catalogue is loaded **once, at application construction**, not on first request. A service that
starts happily and discovers its Catalogue is unreadable when a Customer is at the counter has turned
a setup problem into a Consultation problem — so a missing or invalid file exits the process at
launch (`spectrapaint/service.py`), and Electron shows it as a boot failure.
