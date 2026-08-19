"""What the Catalogue loader accepts, and what it refuses.

Every refusal here is a fault that would otherwise be invisible: the Catalogue would load, the app
would work, and a Dealer would tell a Customer the wrong colour. So the interesting assertions are
the rejections, and that each one says where the problem is.
"""

import pytest

from spectrapaint.catalogue.loader import CatalogueFileInvalid, read_catalogue_file
from spectrapaint.catalogue.location import resolve_catalogue_path
from tests.catalogue.conftest import TWO_SHADES


def test_reads_the_header_and_the_shades(write_catalogue_file):
    catalogue = read_catalogue_file(write_catalogue_file())

    assert catalogue.catalogue_id == "test-catalogue"
    assert catalogue.catalogue_name == "Test Catalogue"
    assert catalogue.version == "1"
    assert [shade.shade_code for shade in catalogue.shades] == ["TC-1001", "TC-2001"]
    assert catalogue.shades[0].lab.l == 94.0
    assert catalogue.shades[0].finishes == ("matte", "satin")


def test_finishes_are_optional(write_catalogue_file):
    """Finish does not reach the render in V1, so a Catalogue that omits it is still usable."""

    catalogue = read_catalogue_file(write_catalogue_file())

    assert catalogue.shades[1].finishes == ()


def test_families_keep_the_order_the_file_lists_them(write_catalogue_file):
    """The manufacturer arranged their range deliberately; browsing follows the Fandeck, not the
    alphabet — which is why Whites comes before Blues here."""

    catalogue = read_catalogue_file(write_catalogue_file())

    assert catalogue.shade_families == ("Whites", "Blues")


def test_the_committed_stand_in_catalogue_loads(write_catalogue_file):
    """Our own data is valid against our own validator — the check that would have caught the
    generator and the loader drifting apart."""

    catalogue = read_catalogue_file(resolve_catalogue_path({}))

    assert catalogue.catalogue_id
    assert catalogue.version
    assert len(catalogue.shades) > 1000, "the virtualisation criterion needs a realistic Catalogue"
    assert len(catalogue.shade_families) > 1


@pytest.mark.parametrize("missing", ["catalogue_id", "catalogue_name", "version"])
def test_a_missing_header_field_is_refused(write_catalogue_file, missing):
    """catalogue_id and version are stamped onto every Render, so a file without them would produce
    Consultations nobody can interpret later."""

    path = write_catalogue_file(**{missing: ""})

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert missing in failure.value.detail
    assert failure.value.message


def test_a_missing_colour_space_is_refused(write_catalogue_file):
    path = write_catalogue_file(colour_space=None)

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert "colour_space" in failure.value.detail


def test_a_different_reference_white_is_refused(write_catalogue_file):
    """D50 data would load cleanly and shift every conversion — the exact fault the field exists to
    make loud."""

    path = write_catalogue_file(
        colour_space={"space": "CIELAB", "reference_white": "D50", "observer": "2"}
    )

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert "D50" in failure.value.detail


def test_a_repeated_shade_code_is_refused(write_catalogue_file):
    """Two Shades sharing a code would make one of them permanently unreachable by lookup."""

    duplicate = {**TWO_SHADES[0], "name": "Something Else"}
    path = write_catalogue_file(shades=[*TWO_SHADES, duplicate])

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert "TC-1001" in failure.value.detail


def test_shade_codes_differing_only_in_case_are_refused(write_catalogue_file):
    """Lookup is case-insensitive, because the Dealer types what the Customer reads aloud — so these
    two are the same code as far as searching is concerned."""

    clash = {**TWO_SHADES[0], "shade_code": "tc-1001", "name": "Something Else"}
    path = write_catalogue_file(shades=[*TWO_SHADES, clash])

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert "tc-1001" in failure.value.detail


@pytest.mark.parametrize("field", ["shade_code", "name", "shade_family"])
def test_a_shade_missing_a_field_is_refused(write_catalogue_file, field):
    broken = {**TWO_SHADES[0]}
    del broken[field]
    path = write_catalogue_file(shades=[broken])

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert field in failure.value.detail
    assert "shades[0]" in failure.value.detail


@pytest.mark.parametrize(
    "lab",
    [
        {"l": 101.0, "a": 0.0, "b": 0.0},
        {"l": -1.0, "a": 0.0, "b": 0.0},
        {"l": 50.0, "a": 200.0, "b": 0.0},
        {"l": 50.0, "a": 0.0, "b": -200.0},
        {"l": 50.0, "a": 0.0},
        {"l": "94", "a": 0.0, "b": 0.0},
        {"l": True, "a": 0.0, "b": 0.0},
    ],
)
def test_a_lab_value_outside_the_space_is_refused(write_catalogue_file, lab):
    path = write_catalogue_file(shades=[{**TWO_SHADES[0], "lab": lab}])

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert "lab" in failure.value.detail


def test_a_shade_without_a_lab_is_refused(write_catalogue_file):
    broken = {**TWO_SHADES[0]}
    del broken["lab"]
    path = write_catalogue_file(shades=[broken])

    with pytest.raises(CatalogueFileInvalid):
        read_catalogue_file(path)


@pytest.mark.parametrize("finishes", ["matte", [""], [3], {"finish": "matte"}])
def test_an_unusable_finishes_value_is_refused(write_catalogue_file, finishes):
    """Absent is fine; present and meaningless is not."""

    path = write_catalogue_file(shades=[{**TWO_SHADES[0], "finishes": finishes}])

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert "finish" in failure.value.detail


def test_an_empty_catalogue_is_refused(write_catalogue_file):
    """A Catalogue with no Shades is not a Catalogue, and would leave the Dealer searching an empty
    panel with nothing to explain why."""

    path = write_catalogue_file(shades=[])

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert "no Shades" in failure.value.detail


def test_malformed_json_is_refused(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"catalogue_id": "x",', encoding="utf-8")

    with pytest.raises(CatalogueFileInvalid) as failure:
        read_catalogue_file(path)

    assert "JSON" in failure.value.detail
    assert failure.value.message


def test_a_json_array_at_the_top_level_is_refused(tmp_path):
    path = tmp_path / "array.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(CatalogueFileInvalid):
        read_catalogue_file(path)
