"""The Catalogue over HTTP.

    GET /catalogue                      -> what Catalogue is loaded, and its Shade Families
    GET /catalogue/shades               -> browse a page, or search
    GET /catalogue/shades/{shade_code}  -> one Shade

Read-only, all three: the Catalogue is a data file the service was pointed at, not something the
app edits. There is deliberately no endpoint that adds, changes or removes a Shade — swapping the
file is how the Catalogue changes (data/catalogue/README.md).

Browsing is paged rather than "here is everything", because the UI list is virtualised and asks
for the window it is about to draw. `total` comes back with every page so the list can size its
scrollbar before it has the rows.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from spectrapaint.api.errors import MALFORMED_REQUEST, SHADE_NOT_FOUND, ServiceError
from spectrapaint.catalogue import Catalogue, Shade

router = APIRouter(prefix="/catalogue")

# A page is a window of a virtualised list, not a screenful of swatches. The ceiling exists so one
# request cannot ask the service to serialise the whole Catalogue; the default is generous enough
# that scrolling fast does not outrun the fetch.
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500

# Search returns a ranked shortlist, not a page. Beyond a screenful or two the ranking is the answer
# — a Dealer scrolling to result 300 of a search has been failed by the search, not by the limit.
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 200

_MESSAGE_SHADE_NOT_FOUND = (
    "That Shade Code is not in this Catalogue. Please check the code on the chip, "
    "or search by name."
)


def _catalogue(request: Request) -> Catalogue:
    return request.app.state.catalogue


def _shade_payload(shade: Shade) -> dict:
    """One Shade, in the shape the swatch needs: the code to show, the colour to draw, and the
    Finishes to list beside it."""

    return {
        "shade_code": shade.shade_code,
        "name": shade.name,
        "shade_family": shade.shade_family,
        "lab": {"l": shade.lab.l, "a": shade.lab.a, "b": shade.lab.b},
        "finishes": list(shade.finishes),
    }


@router.get("")
async def read_catalogue(request: Request) -> dict:
    """Which Catalogue is loaded, and what it can be browsed by.

    The identity and version are here because the UI shows them and because every saved Render
    records them — a Consultation whose meaning quietly changes when the Catalogue is swapped is
    worse than one that is missing (docs/design-decisions.md §7).
    """

    catalogue = _catalogue(request)

    return {
        "catalogue_id": catalogue.catalogue_id,
        "catalogue_name": catalogue.catalogue_name,
        "version": catalogue.version,
        "shade_count": catalogue.shade_count,
        "shade_families": [
            {"shade_family": family, "shade_count": count}
            for family, count in catalogue.shade_families()
        ],
    }


@router.get("/shades")
async def read_shades(
    request: Request,
    q: Annotated[
        str | None,
        Query(description="What the Dealer typed: a Shade Code, part of one, or part of a name."),
    ] = None,
    shade_family: Annotated[
        str | None, Query(description="Browse within one Shade Family.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Search when ``q`` is given, browse otherwise.

    Two behaviours behind one path because they are one thing to the Dealer — the panel showing
    Shades — and because the alternative, a second path the UI switches to as soon as a character is
    typed, means every caller reimplements that switch.

    They differ in one respect worth stating: browsing is paged and reports the true ``total``;
    searching returns a ranked shortlist, so its ``total`` is what came back. Combining ``q`` with
    ``offset`` is refused rather than silently ignored, because a caller that paged a search would
    get a ranking, not a page, and would have no way to notice.
    """

    catalogue = _catalogue(request)

    if q is not None and q.strip():
        if offset:
            raise ServiceError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code=MALFORMED_REQUEST,
                message="SpectraPaint could not read that request. Please try again.",
            )

        shades = catalogue.search(q, limit=min(limit, MAX_SEARCH_LIMIT))
        return {
            "shades": [_shade_payload(shade) for shade in shades],
            "total": len(shades),
            "limit": limit,
            "offset": 0,
            "searched": True,
        }

    shades = catalogue.browse(shade_family=shade_family, limit=limit, offset=offset)
    return {
        "shades": [_shade_payload(shade) for shade in shades],
        "total": catalogue.count(shade_family=shade_family),
        "limit": limit,
        "offset": offset,
        "searched": False,
    }


@router.get("/shades/{shade_code}")
async def read_shade(request: Request, shade_code: str) -> dict:
    """One Shade by its code — the path a Dealer takes when the Customer reads out a chip.

    A code that is not in the Catalogue is a 404 with something to do next, not a dead end: check
    the chip, or search by name (conventions.md §5).
    """

    shade = _catalogue(request).find_by_code(shade_code)

    if shade is None:
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=SHADE_NOT_FOUND,
            message=_MESSAGE_SHADE_NOT_FOUND,
        )

    return _shade_payload(shade)
