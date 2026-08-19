"""Which Catalogue file gets loaded.

Path resolution is the whole of the "swap the file, no code change" criterion, and every one of its
failure paths ends in the Dealer being told something. It is a pure function over an environment and
a directory, so it is tested directly rather than through the contract — nothing here needs a
running service, and asserting it at seam 1 would prove the same thing far more slowly.
"""

import pytest

from spectrapaint.catalogue.location import (
    CATALOGUE_PATH_ENV_VAR,
    CatalogueFileMissing,
    resolve_catalogue_path,
)


def write_catalogue(directory, name="public-stand-in-2026-08-19.json"):
    path = directory / name
    path.write_text("{}", encoding="utf-8")
    return path


def test_uses_the_file_named_in_the_environment(tmp_path):
    named = write_catalogue(tmp_path, "arun-2027-01.json")
    ignored = tmp_path / "development"
    ignored.mkdir()
    write_catalogue(ignored)

    resolved = resolve_catalogue_path({CATALOGUE_PATH_ENV_VAR: str(named)}, development_dir=ignored)

    assert resolved == named


def test_swapping_the_named_file_swaps_the_catalogue(tmp_path):
    """The acceptance criterion, stated as a test: a different file, the same code."""

    first = write_catalogue(tmp_path, "public-stand-in-2026-08-19.json")
    second = write_catalogue(tmp_path, "arun-2027-01.json")

    assert resolve_catalogue_path({CATALOGUE_PATH_ENV_VAR: str(first)}) == first
    assert resolve_catalogue_path({CATALOGUE_PATH_ENV_VAR: str(second)}) == second


def test_falls_back_to_the_single_development_file(tmp_path):
    only = write_catalogue(tmp_path)

    assert resolve_catalogue_path({}, development_dir=tmp_path) == only


def test_a_blank_environment_variable_is_not_a_path(tmp_path):
    """An empty value is how a shell hands over "unset", and must not resolve to the directory."""

    only = write_catalogue(tmp_path)

    assert resolve_catalogue_path({CATALOGUE_PATH_ENV_VAR: "   "}, development_dir=tmp_path) == only


def test_a_named_file_that_does_not_exist_fails_loudly(tmp_path):
    missing = tmp_path / "not-here.json"

    with pytest.raises(CatalogueFileMissing) as failure:
        resolve_catalogue_path({CATALOGUE_PATH_ENV_VAR: str(missing)}, development_dir=tmp_path)

    assert "not-here.json" in failure.value.detail
    assert failure.value.message


def test_two_candidate_files_fail_rather_than_one_being_chosen(tmp_path):
    """A stale file beside a new one must not silently decide which Shades the Dealer sells."""

    write_catalogue(tmp_path, "public-stand-in-2026-08-19.json")
    write_catalogue(tmp_path, "public-stand-in-2027-02-01.json")

    with pytest.raises(CatalogueFileMissing) as failure:
        resolve_catalogue_path({}, development_dir=tmp_path)

    assert "more than one" in failure.value.detail
    assert CATALOGUE_PATH_ENV_VAR in failure.value.detail


def test_an_empty_directory_fails_rather_than_serving_no_shades(tmp_path):
    with pytest.raises(CatalogueFileMissing) as failure:
        resolve_catalogue_path({}, development_dir=tmp_path)

    assert "no Catalogue file" in failure.value.detail


def test_a_missing_directory_fails(tmp_path):
    with pytest.raises(CatalogueFileMissing):
        resolve_catalogue_path({}, development_dir=tmp_path / "absent")


def test_the_repository_checkout_resolves_to_the_committed_stand_in():
    """No arguments at all: a fresh clone with nothing configured finds the stand-in Catalogue."""

    resolved = resolve_catalogue_path({})

    assert resolved.is_file()
    assert resolved.suffix == ".json"
