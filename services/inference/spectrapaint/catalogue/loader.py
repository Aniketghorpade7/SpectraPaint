"""Read a Catalogue file, and refuse a bad one.

The file is the source of truth, so everything downstream trusts what comes out of here — which
makes this the one place that must not be generous. A Catalogue that loads with a missing Shade
Family, a Lab value outside the space, or two Shades sharing a code does not fail; it works,
wrongly, and the failure surfaces as a Dealer telling a Customer the wrong colour.

So validation is strict and total: the whole file is checked before anything is served, and the
first problem stops the load with a message naming where it is. Partial loading is not offered.
"Proceed imperfectly rather than refuse" (conventions.md §5) is the right rule for a poor
*photograph*, whose flaws are visible; it is the wrong rule for reference data, whose flaws are not.

The format itself is specified in data/catalogue/README.md.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Pinned, not defaulted: the spec fixes Lab reference white at D65, 2° observer, and a file measured
# against D50 would shift every conversion by an amount too small to notice and too large to accept.
REQUIRED_COLOUR_SPACE = {"space": "CIELAB", "reference_white": "D65", "observer": "2"}

# The Lab space, as a validation bound rather than as a suggestion.
LIGHTNESS_RANGE = (0.0, 100.0)
CHROMATIC_RANGE = (-128.0, 127.0)

_MESSAGE_INVALID = (
    "SpectraPaint could not read its Shade Catalogue. Please reinstall the app, or contact whoever "
    "set it up for you."
)


class CatalogueFileInvalid(Exception):
    """The Catalogue file exists but cannot be trusted.

    ``message`` is plain language for the Dealer, who cannot act on a JSON path; ``detail`` names
    the offending field for whoever can (conventions.md §5).
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.message = _MESSAGE_INVALID
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Lab:
    """A Shade's colour, in CIELAB under D65 and the 2° observer."""

    l: float  # noqa: E741 — the axis is named L in every colour reference; renaming it here would
    a: float  #                cost more in readability than the ambiguous-name lint saves.
    b: float


@dataclass(frozen=True, slots=True)
class Shade:
    """One Shade a Dealer can sell. Finish is metadata in V1 and does not reach the render."""

    shade_code: str
    name: str
    shade_family: str
    lab: Lab
    finishes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogueFile:
    """A whole Catalogue, as read from one file.

    ``catalogue_id`` and ``version`` travel with every Render (docs/design-decisions.md §7), which
    is why they are part of this value rather than something the caller has to remember to carry.
    """

    catalogue_id: str
    catalogue_name: str
    version: str
    shades: tuple[Shade, ...]

    @property
    def shade_families(self) -> tuple[str, ...]:
        """The families in the order the file lists them — a Fandeck's order, not alphabetical.

        The manufacturer arranged their range deliberately, and a Dealer who knows the book expects
        browsing to match it.
        """

        seen: dict[str, None] = {}
        for shade in self.shades:
            seen.setdefault(shade.shade_family, None)
        return tuple(seen)


def read_catalogue_file(path: Path) -> CatalogueFile:
    """Parse and validate the file at ``path``, or raise ``CatalogueFileInvalid``."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as error:
        raise CatalogueFileInvalid(f"{path} is not valid UTF-8: {error}") from error
    except json.JSONDecodeError as error:
        raise CatalogueFileInvalid(f"{path} is not valid JSON: {error}") from error
    except OSError as error:
        raise CatalogueFileInvalid(f"{path} could not be read: {error}") from error

    if not isinstance(raw, dict):
        raise CatalogueFileInvalid(f"{path} must hold a JSON object, not {type(raw).__name__}.")

    _check_colour_space(raw.get("colour_space"))

    return CatalogueFile(
        catalogue_id=_required_text(raw, "catalogue_id", "the file"),
        catalogue_name=_required_text(raw, "catalogue_name", "the file"),
        version=_required_text(raw, "version", "the file"),
        shades=_read_shades(raw.get("shades")),
    )


def _check_colour_space(value: Any) -> None:
    if not isinstance(value, dict):
        raise CatalogueFileInvalid(
            "the file has no 'colour_space'. It is required, so that a Catalogue measured "
            "against a different reference white is rejected rather than silently rendered wrong."
        )

    given = {key: value.get(key) for key in REQUIRED_COLOUR_SPACE}
    if given != REQUIRED_COLOUR_SPACE:
        raise CatalogueFileInvalid(
            f"the file declares colour_space {given!r}, and V1 supports only "
            f"{REQUIRED_COLOUR_SPACE!r}."
        )


def _read_shades(value: Any) -> tuple[Shade, ...]:
    if not isinstance(value, list):
        raise CatalogueFileInvalid("the file has no 'shades' array.")

    if not value:
        raise CatalogueFileInvalid("the file lists no Shades.")

    shades: list[Shade] = []
    # Case-insensitive, because lookup is: two Shades whose codes differ only in case would make one
    # of them permanently unreachable, which is worse than being told the file is wrong.
    codes_seen: dict[str, str] = {}

    for index, entry in enumerate(value):
        where = f"shades[{index}]"

        if not isinstance(entry, dict):
            raise CatalogueFileInvalid(f"{where} is not an object.")

        shade_code = _required_text(entry, "shade_code", where)
        folded = shade_code.casefold()
        if folded in codes_seen:
            raise CatalogueFileInvalid(
                f"{where} repeats Shade Code {shade_code!r}, already used by "
                f"{codes_seen[folded]!r}. Shade Codes must be unique."
            )
        codes_seen[folded] = shade_code

        shades.append(
            Shade(
                shade_code=shade_code,
                name=_required_text(entry, "name", where),
                shade_family=_required_text(entry, "shade_family", where),
                lab=_read_lab(entry.get("lab"), where),
                finishes=_read_finishes(entry.get("finishes"), where),
            )
        )

    return tuple(shades)


def _read_lab(value: Any, where: str) -> Lab:
    if not isinstance(value, dict):
        raise CatalogueFileInvalid(f"{where} has no 'lab' object.")

    return Lab(
        l=_axis(value, "l", where, LIGHTNESS_RANGE),
        a=_axis(value, "a", where, CHROMATIC_RANGE),
        b=_axis(value, "b", where, CHROMATIC_RANGE),
    )


def _axis(value: dict[str, Any], axis: str, where: str, bounds: tuple[float, float]) -> float:
    given = value.get(axis)

    # bool is an int in Python, and `true` in a colour value means the file is wrong, not that the
    # axis is 1.
    if isinstance(given, bool) or not isinstance(given, int | float):
        raise CatalogueFileInvalid(f"{where} has a non-numeric lab.{axis}: {given!r}.")

    low, high = bounds
    if not low <= given <= high:
        raise CatalogueFileInvalid(
            f"{where} has lab.{axis} of {given}, outside the Lab range {low} to {high}."
        )

    return float(given)


def _read_finishes(value: Any, where: str) -> tuple[str, ...]:
    # Optional: a Catalogue that does not say which finishes a Shade is sold in is usable, because
    # Finish does not affect the render in V1. An unusable *value*, though, is still an error.
    if value is None:
        return ()

    if not isinstance(value, list) or not all(isinstance(finish, str) for finish in value):
        raise CatalogueFileInvalid(f"{where} has a 'finishes' that is not a list of names.")

    finishes = tuple(finish.strip() for finish in value)
    if any(not finish for finish in finishes):
        raise CatalogueFileInvalid(f"{where} lists a blank finish.")

    return finishes


def _required_text(source: dict[str, Any], field: str, where: str) -> str:
    value = source.get(field)

    if not isinstance(value, str) or not value.strip():
        raise CatalogueFileInvalid(f"{where} has a missing or blank {field!r}.")

    return value.strip()
