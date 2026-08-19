"""The Catalogue in SQLite.

Built from the file at launch, held **in memory**, and never written to again. The file is the
source of truth; this is an index over it, thrown away when the process ends and rebuilt from
scratch next launch — a thousand-odd rows load in milliseconds, so there is nothing to gain by
persisting it and
something real to lose: a cached copy on disk can disagree with the file beside it, and the whole
reason the Catalogue identity and version are stamped onto every Render is that this class of
mismatch is expensive.

The on-disk database in ``spectrapaint/storage/`` is a different thing entirely — that one holds
Bundles, Consultations and Renders, which must survive a restart. This one must not.

Rows keep the file's order, so browsing a Shade Family matches how the manufacturer arranged the
Fandeck rather than how Python happened to sort it.
"""

import json
import sqlite3

from spectrapaint.catalogue.loader import CatalogueFile

# One row, because one Catalogue is loaded at a time (docs/design-decisions.md §7). A table rather
# than a Python attribute so a query can join against it and return a Shade already stamped with the
# Catalogue it came from.
_CREATE_CATALOGUE = """
CREATE TABLE catalogue (
    catalogue_id   TEXT NOT NULL,
    catalogue_name TEXT NOT NULL,
    version        TEXT NOT NULL
)
"""

# `*_folded` columns hold case-folded text for searching, alongside the original for display.
#
# Why not SQLite's own NOCASE collation: it case-folds ASCII only. A Shade named "Café Crème" would
# then be findable by "café" but not "CAFÉ", and manufacturer data is exactly where accented names
# turn up. Python's str.casefold handles the whole of Unicode, so the folding is done once here, at
# load, rather than trusted to the database at query time.
_CREATE_SHADES = """
CREATE TABLE shades (
    position          INTEGER PRIMARY KEY,
    shade_code        TEXT NOT NULL,
    shade_code_folded TEXT NOT NULL,
    name              TEXT NOT NULL,
    name_folded       TEXT NOT NULL,
    shade_family      TEXT NOT NULL,
    lab_l             REAL NOT NULL,
    lab_a             REAL NOT NULL,
    lab_b             REAL NOT NULL,
    finishes          TEXT NOT NULL
)
"""

# One index per access pattern, and no more. Measured on the 1,159-Shade stand-in Catalogue, median
# of 200 runs (docs/implementation-decisions.md entry 4):
#
#   exact Shade Code     0.058 ms scanned  ->  0.004 ms indexed
#   Shade Family browse  0.206 ms scanned  ->  0.158 ms indexed
#
# The unique index on the folded code does a second job: the loader refuses a repeated Shade Code,
# and this makes that rule true in the database too, so a future writer cannot quietly break it.
#
# Nothing indexes the substring name search, because nothing can — an index is ordered by the start
# of a value, so `LIKE '%lin%'` has to look at every row whatever exists. It costs 0.11 ms here, and
# 5.7 ms at 50,000 rows, which is why there is no FTS5 table (entry 4).
_CREATE_INDEXES = (
    "CREATE UNIQUE INDEX shades_by_code ON shades (shade_code_folded)",
    "CREATE INDEX shades_by_family ON shades (shade_family, position)",
    # Serves the name-prefix half of search: a Dealer typing "lin" wants Linen ranked above
    # Bougainvillea. Reached by a range seek (0.0048 ms), not by LIKE — SQLite will not use an index
    # for LIKE unless case_sensitive_like is on, and it falls back to scanning at 0.0708 ms. The
    # folded column is already lowercase, so a plain `>= prefix AND < prefix+1` comparison is both
    # correct and seekable. It is a covering index too, so even the substring scan reads it rather
    # than the wider table.
    "CREATE INDEX shades_by_name ON shades (name_folded)",
)

_INSERT_SHADE = """
INSERT INTO shades (
    position, shade_code, shade_code_folded, name, name_folded, shade_family,
    lab_l, lab_a, lab_b, finishes
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def build_catalogue_database(catalogue: CatalogueFile) -> sqlite3.Connection:
    """Load a validated Catalogue into a fresh in-memory database and return the connection.

    ``check_same_thread`` is off because FastAPI runs synchronous endpoints in a worker thread pool,
    so the thread that answers a search is not the thread that built this. Safe here specifically
    because nothing writes after this function returns — the connection is read-only for the rest of
    the process's life.
    """

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row

    with connection:
        connection.execute(_CREATE_CATALOGUE)
        connection.execute(_CREATE_SHADES)
        connection.execute(
            "INSERT INTO catalogue (catalogue_id, catalogue_name, version) VALUES (?, ?, ?)",
            (catalogue.catalogue_id, catalogue.catalogue_name, catalogue.version),
        )
        connection.executemany(
            _INSERT_SHADE,
            (
                (
                    position,
                    shade.shade_code,
                    shade.shade_code.casefold(),
                    shade.name,
                    shade.name.casefold(),
                    shade.shade_family,
                    shade.lab.l,
                    shade.lab.a,
                    shade.lab.b,
                    # Finish is metadata only in V1 and is never searched or filtered on, so it
                    # travels as JSON in one column. A finishes table would buy a join on every read
                    # to support a query nothing makes.
                    json.dumps(list(shade.finishes)),
                    # Position from 1, matching the file's order: SQLite's implicit rowid would do
                    # the same, but relying on that would make the Fandeck's order an accident.
                )
                for position, shade in enumerate(catalogue.shades, 1)
            ),
        )

        # Indexes after the rows, not before: building one index over a finished table is cheaper
        # than maintaining three across 1,159 inserts.
        for statement in _CREATE_INDEXES:
            connection.execute(statement)

        # SQLite's planner uses these statistics to choose an index over a scan. Gathered once,
        # here, because the table never changes again.
        connection.execute("ANALYZE")

    return connection
