"""Finding a Shade: by code, by half a name, or by browsing.

These are the three things the Dealer actually does at the counter, so they are asserted as
behaviour — what comes back and in what order — never as the SQL that produced it.
"""

import pytest

from spectrapaint.catalogue import open_catalogue
from spectrapaint.catalogue.database import build_catalogue_database
from spectrapaint.catalogue.loader import read_catalogue_file
from spectrapaint.catalogue.queries import Catalogue


@pytest.fixture
def catalogue(write_catalogue_file):
    """A small Catalogue whose Shades are chosen to make each search tier visible."""

    shades = [
        {
            "shade_code": "TC-1001",
            "name": "Morning Linen",
            "shade_family": "Whites",
            "lab": {"l": 94.0, "a": 0.5, "b": 2.0},
            "finishes": ["matte", "satin"],
        },
        {
            "shade_code": "TC-1002",
            "name": "Linen Fold",
            "shade_family": "Whites",
            "lab": {"l": 92.0, "a": 0.4, "b": 2.4},
        },
        {
            "shade_code": "TC-2001",
            "name": "Deep Indigo",
            "shade_family": "Blues",
            "lab": {"l": 34.0, "a": 6.0, "b": -28.0},
        },
        {
            "shade_code": "TC-2002",
            "name": "50% Harbour",
            "shade_family": "Blues",
            "lab": {"l": 56.0, "a": -2.0, "b": -14.0},
        },
    ]
    catalogue_file = read_catalogue_file(write_catalogue_file(shades=shades))
    return Catalogue(catalogue_file, build_catalogue_database(catalogue_file))


# -- the Catalogue's own identity -----------------------------------------------------------


def test_carries_the_identity_a_render_has_to_record(catalogue):
    assert catalogue.catalogue_id == "test-catalogue"
    assert catalogue.catalogue_name == "Test Catalogue"
    assert catalogue.version == "1"
    assert catalogue.shade_count == 4


# -- by Shade Code --------------------------------------------------------------------------


def test_finds_a_shade_by_its_code(catalogue):
    assert catalogue.find_by_code("TC-2001").name == "Deep Indigo"


@pytest.mark.parametrize("typed", ["tc-2001", "TC-2001", "  TC-2001  ", "Tc-2001"])
def test_the_code_is_found_however_the_dealer_types_it(catalogue, typed):
    """The Dealer is typing at a counter while talking to a Customer reading a chip aloud."""

    assert catalogue.find_by_code(typed).shade_code == "TC-2001"


def test_an_unknown_code_is_not_found_rather_than_an_error(catalogue):
    """A Dealer mistyping a code is ordinary. What it means is the HTTP layer's decision."""

    assert catalogue.find_by_code("TC-9999") is None
    assert catalogue.find_by_code("   ") is None


# -- search ---------------------------------------------------------------------------------


def test_the_exact_code_comes_first(catalogue):
    """The one result the Dealer is certain about outranks everything else."""

    results = catalogue.search("TC-2001", limit=10)

    assert results[0].shade_code == "TC-2001"


def test_a_partial_code_finds_the_shades_it_begins(catalogue):
    codes = [shade.shade_code for shade in catalogue.search("tc-10", limit=10)]

    assert codes == ["TC-1001", "TC-1002"]


def test_a_name_beginning_with_the_text_outranks_one_merely_containing_it(catalogue):
    """Typing "linen" should reach *Linen Fold* before *Morning Linen*."""

    names = [shade.name for shade in catalogue.search("linen", limit=10)]

    assert names == ["Linen Fold", "Morning Linen"]


def test_search_is_case_insensitive(catalogue):
    assert [shade.name for shade in catalogue.search("LINEN", limit=10)] == [
        "Linen Fold",
        "Morning Linen",
    ]


def test_a_shade_appears_once_however_many_tiers_it_matches(catalogue):
    """TC-1002 is both an exact code and a code prefix; it is one Shade either way."""

    results = catalogue.search("TC-1002", limit=10)

    assert [shade.shade_code for shade in results].count("TC-1002") == 1


def test_wildcards_the_dealer_types_are_treated_as_text(catalogue):
    """A Shade called "50% Harbour" is findable by "50%", and "_" matches an underscore only."""

    assert [shade.name for shade in catalogue.search("50%", limit=10)] == ["50% Harbour"]
    assert [shade.name for shade in catalogue.search("_arbour", limit=10)] == []


def test_search_respects_its_limit(catalogue):
    assert len(catalogue.search("tc", limit=2)) == 2


def test_an_empty_search_returns_nothing(catalogue):
    """Not everything: an empty box is the Dealer having typed nothing, not asking for the lot."""

    assert catalogue.search("", limit=10) == ()
    assert catalogue.search("   ", limit=10) == ()


def test_a_search_matching_nothing_returns_nothing(catalogue):
    assert catalogue.search("zzzz", limit=10) == ()


# -- browsing ---------------------------------------------------------------------------------


def test_families_come_back_in_fandeck_order_with_their_counts(catalogue):
    """Whites before Blues because the file says so, and the counts let the UI label a family
    without fetching it."""

    assert catalogue.shade_families() == (("Whites", 2), ("Blues", 2))


def test_browsing_a_family_returns_only_that_family_in_file_order(catalogue):
    codes = [shade.shade_code for shade in catalogue.browse(shade_family="Blues", limit=10)]

    assert codes == ["TC-2001", "TC-2002"]


def test_browsing_without_a_family_walks_the_whole_catalogue(catalogue):
    codes = [shade.shade_code for shade in catalogue.browse(limit=10)]

    assert codes == ["TC-1001", "TC-1002", "TC-2001", "TC-2002"]


def test_browsing_pages(catalogue):
    """The virtualised list asks for a window at a time, not the whole Catalogue."""

    page = catalogue.browse(limit=2, offset=2)

    assert [shade.shade_code for shade in page] == ["TC-2001", "TC-2002"]


def test_counts_are_available_before_anything_is_fetched(catalogue):
    """A virtualised list has to size its scrollbar before it has the rows."""

    assert catalogue.count() == 4
    assert catalogue.count(shade_family="Blues") == 2
    assert catalogue.count(shade_family="Nothing") == 0


def test_a_shade_carries_everything_a_swatch_needs(catalogue):
    shade = catalogue.find_by_code("TC-1001")

    assert shade.shade_code == "TC-1001"
    assert shade.name == "Morning Linen"
    assert shade.shade_family == "Whites"
    assert (shade.lab.l, shade.lab.a, shade.lab.b) == (94.0, 0.5, 2.0)
    assert shade.finishes == ("matte", "satin")


# -- the real Catalogue -------------------------------------------------------------------------


def test_the_stand_in_catalogue_answers_all_three_questions():
    """One test against the committed 1,159-Shade file: the small fixture proves the rules, this
    proves they hold on real data."""

    catalogue = open_catalogue({})

    known = catalogue.browse(limit=1)[0]
    assert catalogue.find_by_code(known.shade_code.lower()) == known
    assert catalogue.search(known.name[:4], limit=5)
    assert catalogue.count(shade_family=known.shade_family) > 1
    assert sum(count for _, count in catalogue.shade_families()) == catalogue.shade_count
