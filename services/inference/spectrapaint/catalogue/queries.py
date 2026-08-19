"""Searching and browsing the Catalogue.

The three things a Dealer does — read a code off a chip, half-remember a name, browse a family — and
nothing else. SQL lives here and nowhere above: the HTTP layer asks for Shades, not for rows.

Search is **tiered**, not scored. The Dealer's most common act is typing a Shade Code the Customer
has just read aloud, so an exact code match is answered first and separately; then codes beginning
with what was typed, then names beginning with it, then names containing it anywhere. Within a
tier, Fandeck order. A single relevance score mixing codes and names would sometimes put a name
match above the exact code that was typed, and that is the one result the Dealer is certain of.
"""

import json
import sqlite3

from spectrapaint.catalogue.loader import CatalogueFile, Lab, Shade

# Highest code point there is: appending it makes "everything that starts with this prefix" an
# ordinary range comparison, which SQLite can seek on an index. LIKE cannot be used for this —
# see docs/implementation-decisions.md entry 4.
_ABOVE_EVERY_PREFIX = "\U0010ffff"

# The Dealer types into a search box, so `%` and `_` arrive as text and must not act as wildcards.
_LIKE_ESCAPE = "\\"

_SHADE_COLUMNS = "shade_code, name, shade_family, lab_l, lab_a, lab_b, finishes, position"


class Catalogue:
    """The loaded Catalogue, and the only way to ask it anything.

    Read-only: it is built once at launch and answers queries for the life of the process.
    """

    def __init__(self, catalogue_file: CatalogueFile, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.catalogue_id = catalogue_file.catalogue_id
        self.catalogue_name = catalogue_file.catalogue_name
        self.version = catalogue_file.version
        self.shade_count = len(catalogue_file.shades)

    # -- browsing ---------------------------------------------------------------------------

    def shade_families(self) -> tuple[tuple[str, int], ...]:
        """Every Shade Family with how many Shades it holds, in the order the file lists them.

        The count is what lets the UI show "Blues (99)" without fetching ninety-nine Shades to find
        out, which matters when the list is virtualised.
        """

        rows = self._connection.execute(
            "SELECT shade_family, count(*) AS shade_count, min(position) AS first_position"
            " FROM shades GROUP BY shade_family ORDER BY first_position"
        )
        return tuple((row["shade_family"], row["shade_count"]) for row in rows)

    def browse(
        self, *, shade_family: str | None = None, limit: int, offset: int = 0
    ) -> tuple[Shade, ...]:
        """A page of Shades in Fandeck order, optionally within one Shade Family."""

        if shade_family is None:
            rows = self._connection.execute(
                f"SELECT {_SHADE_COLUMNS} FROM shades ORDER BY position LIMIT ? OFFSET ?",
                (limit, offset),
            )
        else:
            rows = self._connection.execute(
                f"SELECT {_SHADE_COLUMNS} FROM shades WHERE shade_family = ?"
                " ORDER BY position LIMIT ? OFFSET ?",
                (shade_family, limit, offset),
            )
        return tuple(_to_shade(row) for row in rows)

    def count(self, *, shade_family: str | None = None) -> int:
        """How many Shades a browse would page through — the virtualised list needs the total to
        size its scrollbar before it has fetched anything."""

        if shade_family is None:
            return int(self._connection.execute("SELECT count(*) FROM shades").fetchone()[0])

        row = self._connection.execute(
            "SELECT count(*) FROM shades WHERE shade_family = ?", (shade_family,)
        ).fetchone()
        return int(row[0])

    # -- searching --------------------------------------------------------------------------

    def find_by_code(self, shade_code: str) -> Shade | None:
        """The primary path: the Customer points at a chip and reads out the code.

        Case-insensitive and whitespace-tolerant, because the Dealer is typing at a counter while
        talking. Returns ``None`` rather than raising — an unknown code is a normal thing for a
        Dealer to type, and the HTTP layer decides what that means.
        """

        folded = shade_code.strip().casefold()
        if not folded:
            return None

        row = self._connection.execute(
            f"SELECT {_SHADE_COLUMNS} FROM shades WHERE shade_code_folded = ?", (folded,)
        ).fetchone()
        return None if row is None else _to_shade(row)

    def search(self, query: str, *, limit: int) -> tuple[Shade, ...]:
        """Shades matching what the Dealer typed, best first.

        Tiers, in order: the exact Shade Code, then Shade Codes starting with it, then names
        starting with it, then names containing it. Each Shade appears once, in its best tier.
        """

        folded = query.strip().casefold()
        if not folded:
            return ()

        found: dict[str, Shade] = {}

        for shade in self._tiers(folded, limit):
            found.setdefault(shade.shade_code, shade)
            if len(found) == limit:
                break

        return tuple(found.values())

    def _tiers(self, folded: str, limit: int):
        exact = self.find_by_code(folded)
        if exact is not None:
            yield exact

        yield from self._by_prefix("shade_code_folded", folded, limit)
        yield from self._by_prefix("name_folded", folded, limit)
        yield from self._containing("name_folded", folded, limit)

    def _by_prefix(self, column: str, folded: str, limit: int) -> tuple[Shade, ...]:
        """Rows whose column starts with the text — an index seek, not a scan."""

        rows = self._connection.execute(
            f"SELECT {_SHADE_COLUMNS} FROM shades WHERE {column} >= ? AND {column} < ?"
            " ORDER BY position LIMIT ?",
            (folded, folded + _ABOVE_EVERY_PREFIX, limit),
        )
        return tuple(_to_shade(row) for row in rows)

    def _containing(self, column: str, folded: str, limit: int) -> tuple[Shade, ...]:
        """Rows whose column contains the text anywhere. A scan by nature, and cheap at Fandeck
        size — 0.1 ms across 1,159 Shades (docs/implementation-decisions.md entry 4)."""

        rows = self._connection.execute(
            f"SELECT {_SHADE_COLUMNS} FROM shades WHERE {column} LIKE ? ESCAPE ?"
            " ORDER BY position LIMIT ?",
            (f"%{_escape_like(folded)}%", _LIKE_ESCAPE, limit),
        )
        return tuple(_to_shade(row) for row in rows)


def _escape_like(text: str) -> str:
    """Neutralise the wildcards, so a Dealer searching for "50%" finds a Shade called "50%"."""

    for character in (_LIKE_ESCAPE, "%", "_"):
        text = text.replace(character, _LIKE_ESCAPE + character)
    return text


def _to_shade(row: sqlite3.Row) -> Shade:
    return Shade(
        shade_code=row["shade_code"],
        name=row["name"],
        shade_family=row["shade_family"],
        lab=Lab(l=row["lab_l"], a=row["lab_a"], b=row["lab_b"]),
        finishes=tuple(json.loads(row["finishes"])),
    )
