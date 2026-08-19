"""A Catalogue file to load, built in a test's own temporary directory.

Small on purpose: these tests are about what the loader accepts and refuses, and a fixture with two
Shades makes a failure readable. The committed 1,159-Shade file is loaded too, in one test, because
"it parses our own data" is a different claim from "it rejects the wrong data".
"""

import json

import pytest

VALID_HEADER = {
    "catalogue_id": "test-catalogue",
    "catalogue_name": "Test Catalogue",
    "version": "1",
    "colour_space": {"space": "CIELAB", "reference_white": "D65", "observer": "2"},
}

TWO_SHADES = [
    {
        "shade_code": "TC-1001",
        "name": "Morning Linen",
        "shade_family": "Whites",
        "lab": {"l": 94.0, "a": 0.5, "b": 2.0},
        "finishes": ["matte", "satin"],
    },
    {
        "shade_code": "TC-2001",
        "name": "Deep Indigo",
        "shade_family": "Blues",
        "lab": {"l": 34.0, "a": 6.0, "b": -28.0},
    },
]


@pytest.fixture
def write_catalogue_file(tmp_path):
    """Write a Catalogue file, defaulting to a valid one, and return its path."""

    def write(**overrides):
        document = {**VALID_HEADER, "shades": TWO_SHADES, **overrides}
        path = tmp_path / "test-catalogue-1.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    return write
