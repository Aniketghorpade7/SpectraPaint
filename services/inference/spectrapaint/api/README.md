# api — the REST contract

    GET    /health                                -> { status }
    POST   /sessions              (photo upload) -> { session_id }
    GET    /sessions/{id}/events                  (progress stream)
    GET    /sessions/{id}/planes                  -> { planes, note, quality_note }
    POST   /sessions/{id}/planes  { x, y }         (Add a missed wall)
    POST   /sessions/{id}/planes/split { x, y }    (Split a merged corner)
    POST   /sessions/{id}/planes/merge { x, y }    (Merge a wrongly-split corner)
    GET    /sessions/{id}/planes/{plane_id}/matte
    POST   /sessions/{id}/renders { assignments, mode }
    DELETE /sessions/{id}
    GET    /catalogue                             -> { catalogue_id, version, shade_families, ... }
    GET    /catalogue/shades      ?q= &shade_family= &limit= &offset=
    GET    /catalogue/shades/{shade_code}         -> one Shade
    GET    /bundles                               -> { bundles }                        (issue #11)
    POST   /bundles               { name }        -> one Bundle
    PATCH  /bundles/{id}          { name }        (rename)
    DELETE /bundles/{id}                          (consultations move to the default Bundle)
    GET    /bundles/{id}/consultations            -> { consultations }
    POST   /bundles/{id}/consultations { consultation_id }   (file one into a Bundle)
    GET    /consultations/{id}/renders            -> { renders } — every shade already tried
    GET    /consultations/{id}/photo/png          (the photo as preparation left it)
    GET    /consultations/{id}/renders/{rid}/png  (the stored render, byte-for-byte)
    POST   /consultations/{id}/reopen             -> { session_id } — no preparation runs

Encode-once is enforced structurally, by omission: a photo enters only through `POST /sessions`,
and there is deliberately no endpoint accepting an image and a Shade together.

The library endpoints (issue #11) replay stored work and never regenerate it: the two `png` routes
serve exactly the bytes written when the work happened, and `reopen` rebuilds a live session from the
photo and Alpha Mattes preparation already produced, so trying another Shade skips preparation.
Nothing here deletes a Consultation or a Render.

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

## The render endpoint

`POST /sessions/{id}/renders` takes `assignments` — a Shade Code per Wall Plane — and returns the
repainted photo as `image/png`. The photo is never in the request: it entered at upload and the
render reads what preparation produced, so encode-once holds structurally rather than by convention.

There is one Wall Plane today (a stub rectangle), so `assignments` carries one entry. The map is the
contract anyway, because an Accent Wall is two planes with two Shades in one request — see
`docs/implementation-decisions.md` §18.

| Refused | |
|---|---|
| Unknown session | `404 session_not_found` |
| That photo failed preparation | `422 unsupported_image` |
| Shade Code not in the Catalogue | `404 shade_not_found` — the same status the Catalogue's own lookup gives |
| A plane the photo does not have, or no assignment at all | `422 malformed_request` |
| An unrecognised `mode` | `422 malformed_request` |

An assignment naming an unknown plane is refused rather than ignored: nothing in a returned PNG
would reveal that the render answered a different question than the one asked.

## The correction endpoints (ticket #10)

Three POSTs under `planes.py`, one per tool the Dealer can arm on the Consultation surface — Add,
Split, Merge — each taking nothing but `{ "x": int, "y": int }`, the tapped point in the prepared
photo's own pixel space (the same space `photo_width`/`photo_height` on `GET .../planes` already
describe). All three answer with the same shape `GET .../planes` does —
`{ planes, note, quality_note }` — so a correction's result is handled exactly like a fresh load.
None of them touch the photo or re-run
preparation; the segmentation work lives in `segmentation/corrections.py`, this module is only the
HTTP translation.

| | |
|---|---|
| `POST /sessions/{id}/planes` | Add. `201`. The point must not already be covered by a plane. |
| `POST /sessions/{id}/planes/split` | Split. `201`. The point must be inside an existing plane. |
| `POST /sessions/{id}/planes/merge` | Merge. `200`. The point must be near where two planes meet. |

A tap that does not satisfy its tool's precondition is `422 malformed_request`, with a message
naming the right tool instead — see `segmentation.corrections.CorrectionRefused` and its
subclasses, and `docs/implementation-decisions.md` §39–41.

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
