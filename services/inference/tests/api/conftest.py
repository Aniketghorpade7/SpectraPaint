"""Preparation the contract tests can rely on, without a model in sight.

Seam 1 asks whether the REST contract behaves: statuses, error shapes, mode semantics, what a
render actually looks like. None of that is a question about SegFormer or SAM 2. So the tests here
supply their own preparation through ``create_app(preparation_stages=...)`` — the injection point
:mod:`spectrapaint.api.preparation` documents and ticket #4's stream tests already used — and get a
photo with a Wall Plane whose matte they know exactly.

This is not mocking the model adapters, which conventions.md §6 rules out. Nothing here stands in
for the pipeline's *interface* so that the pipeline's absence goes unnoticed: the real pipeline is
exercised over the same contract by the tests marked ``models``, which run in the slow lane against
the real graphs. What this file replaces is the *input* — "assume a photo was prepared and this is
its matte" — which is what lets the fast lane assert render behaviour on both operating systems in
seconds, without a gigabyte of weights.

The matte is the centred rectangle that used to live in production code as the stub. It has a
fully-interior region, which is what lets a test assert that the repaint actually shows up, and a
soft edge band, which is what lets it assert that the composite stays clean at a fractional alpha.
"""

import numpy as np

from spectrapaint.api.preparation import PreparedPhoto, Stage, decode_photo
from spectrapaint.segmentation.walls import FIRST_WALL_PLANE_ID, WallPlane

# The test matte's geometry, as production's stub had it (docs/implementation-decisions.md §18).
STUB_WIDTH_FRACTION = 0.60
STUB_HEIGHT_FRACTION = 0.55
STUB_SOFT_BAND_FRACTION = 0.03


def rectangular_matte(shape: tuple[int, int]) -> np.ndarray:
    """A centred, soft-edged rectangle in [0, 1], shaped HxWx1 like any Wall Plane matte.

    The edge band is a linear ramp, so the alpha composite it feeds stays clean in linear space.
    """

    height, width = shape
    rect_w = max(1, round(width * STUB_WIDTH_FRACTION))
    rect_h = max(1, round(height * STUB_HEIGHT_FRACTION))
    band = max(1, round(min(width, height) * STUB_SOFT_BAND_FRACTION))

    left = (width - rect_w) // 2
    right = left + rect_w
    top = (height - rect_h) // 2
    bottom = top + rect_h

    x = np.arange(width, dtype=np.float32)
    y = np.arange(height, dtype=np.float32)

    from_left = np.minimum(np.minimum(x[None, :] - left, right - x[None, :]), band) / band
    from_top = np.minimum(np.minimum(y[:, None] - top, bottom - y[:, None]), band) / band
    return np.clip(np.minimum(from_left, from_top), 0.0, 1.0)[..., None].astype(np.float32)


def prepared_photo_of(contents: bytes) -> PreparedPhoto:
    """Decode the uploaded bytes for real, then attach a matte the test chose."""

    decoded = decode_photo(contents)
    plane = WallPlane(
        plane_id=FIRST_WALL_PLANE_ID,
        alpha=rectangular_matte(decoded.srgb.shape[:2]),
    )
    return PreparedPhoto(linear=decoded.linear, srgb=decoded.srgb, planes=(plane,))


def two_plane_mattes(shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """The stub rectangle cut down the middle into two Wall Planes.

    A partition of the same matte, exactly as the splitter produces one (ticket #7): the outer edge
    stays soft where the wall meets a non-wall, the cut between the two is hard so a wall-to-wall
    corner stays crisp, and no pixel is claimed twice — so an Accent Wall composited from these
    cannot show a dark seam for a reason the test itself introduced.
    """

    matte = rectangular_matte(shape)
    width = shape[1]
    seam = width // 2

    left = matte.copy()
    left[:, seam:] = 0.0
    right = matte.copy()
    right[:, :seam] = 0.0
    return left, right


def two_plane_photo_of(contents: bytes) -> PreparedPhoto:
    """The same decode as :func:`prepared_photo_of`, with the matte split into two planes."""

    decoded = decode_photo(contents)
    left, right = two_plane_mattes(decoded.srgb.shape[:2])
    return PreparedPhoto(
        linear=decoded.linear,
        srgb=decoded.srgb,
        planes=(
            WallPlane(plane_id="wall_plane_1", alpha=left),
            WallPlane(plane_id="wall_plane_2", alpha=right),
        ),
    )


def two_plane_preparation_stages(contents: bytes) -> list[Stage]:
    """Preparation that hands back two Wall Planes, for the Accent Wall tests (ticket #7)."""

    return [Stage(message="Reading your photo…", run=lambda: two_plane_photo_of(contents))]


def stub_preparation_stages(contents: bytes) -> list[Stage]:
    """Preparation that decodes the photo and hands back a known Wall Plane.

    The decode is genuine, so a file that only *looks* like a photo still fails preparation here
    exactly as it would in production — that behaviour is contract, and faking it would quietly
    delete a test.
    """

    return [Stage(message="Reading your photo…", run=lambda: prepared_photo_of(contents))]
