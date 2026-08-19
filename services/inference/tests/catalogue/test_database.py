"""The Catalogue as SQLite: everything in the file is in the index, and nothing is added.

Table shapes are implementation and are not asserted here beyond what a query needs. What matters is
that no Shade is lost on the way in, that the file's order survives, and that the Catalogue identity
is available to stamp onto a Render.
"""

import sqlite3

import pytest

from spectrapaint.catalogue.database import build_catalogue_database
from spectrapaint.catalogue.loader import read_catalogue_file
from spectrapaint.catalogue.location import resolve_catalogue_path


def test_every_shade_in_the_file_reaches_the_database(write_catalogue_file):
    catalogue = read_catalogue_file(write_catalogue_file())

    connection = build_catalogue_database(catalogue)

    assert connection.execute("SELECT count(*) FROM shades").fetchone()[0] == len(catalogue.shades)


def test_the_catalogue_identity_is_available_to_stamp_onto_a_render(write_catalogue_file):
    catalogue = read_catalogue_file(write_catalogue_file())

    row = build_catalogue_database(catalogue).execute("SELECT * FROM catalogue").fetchone()

    assert row["catalogue_id"] == catalogue.catalogue_id
    assert row["version"] == catalogue.version


def test_rows_keep_the_order_the_file_listed_them(write_catalogue_file):
    """Browsing follows the Fandeck, so the file's order has to survive the load."""

    catalogue = read_catalogue_file(write_catalogue_file())

    codes = [
        row["shade_code"]
        for row in build_catalogue_database(catalogue).execute(
            "SELECT shade_code FROM shades ORDER BY position"
        )
    ]

    assert codes == [shade.shade_code for shade in catalogue.shades]


def test_a_shade_is_findable_by_a_case_folded_code(write_catalogue_file):
    """The Dealer types what the Customer reads off the chip, in whatever case they type it."""

    catalogue = read_catalogue_file(write_catalogue_file())

    row = (
        build_catalogue_database(catalogue)
        .execute("SELECT shade_code FROM shades WHERE shade_code_folded = ?", ["tc-1001"])
        .fetchone()
    )

    assert row["shade_code"] == "TC-1001"


def test_the_whole_stand_in_catalogue_loads_into_the_database():
    """The realistic case: a thousand-plus Shades, the size the virtualised list must survive."""

    catalogue = read_catalogue_file(resolve_catalogue_path({}))

    connection = build_catalogue_database(catalogue)

    assert connection.execute("SELECT count(*) FROM shades").fetchone()[0] == len(catalogue.shades)
    families = connection.execute("SELECT count(DISTINCT shade_family) FROM shades").fetchone()[0]
    assert families == len(catalogue.shade_families)


def test_the_database_refuses_a_repeated_shade_code(write_catalogue_file):
    """The loader already rejects a duplicate. Enforcing it here as well means a future writer
    cannot quietly reintroduce one and make a Shade unreachable."""

    catalogue = read_catalogue_file(write_catalogue_file())
    connection = build_catalogue_database(catalogue)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO shades (position, shade_code, shade_code_folded, name, name_folded,"
            " shade_family, lab_l, lab_a, lab_b, finishes)"
            " VALUES (999, 'TC-1001', 'tc-1001', 'Clash', 'clash', 'Whites', 50, 0, 0, '[]')"
        )
