"""Render the hand-authored Wall Plane labels for data/fixtures/rooms (issue #30).

The labels themselves are traced by eye, but they are kept as polygons rather than as pixels the
only way that makes them reviewable: a diff of ``ROOMS`` below says what somebody decided about a
photograph, where a diff of a PNG says nothing at all. Re-run this script to regenerate the PNGs
after editing a polygon.

Two outputs per room, both the exact pixel size of the photograph:

``<name>.wall.png``
    White where the wall is, black where it is not, mid-grey where the boundary is genuinely
    uncertain -- data/fixtures/rooms/README.md treats mid-grey as "do not count this pixel".

``<name>.planes.png``
    One flat colour per Wall Plane, black everywhere else. Planes are ordered left to right by
    centroid, which is the order ``planes_from`` numbers ``wall_plane_N`` in, so plane 1 in the
    label is the plane the service calls ``wall_plane_1``.

Every traced boundary gets a grey band of ``UNCERTAIN_BAND`` pixels on both sides, because a line
drawn by eye over a curtain fold or a chair leg is not accurate to the pixel and a label that
claims otherwise is worse than no label at all. Occlusions too tangled to trace -- hanging clothes,
luggage, bedding -- are marked uncertain wholesale instead of being guessed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "rooms"

# How wide the "do not count this" band around every traced boundary is, in pixels.
UNCERTAIN_BAND = 7

# Label values, matching what tests/api/test_walls.py reads: >= 0.75 is wall, <= 0.25 is not wall,
# anything between is unsure.
WALL = 255
NOT_WALL = 0
UNCERTAIN = 128

# One colour per Wall Plane in <name>.planes.png. Distinct in hue so a human can see the split at a
# glance, and far from black so "no plane here" is never ambiguous.
PLANE_COLOURS = [(220, 50, 47), (38, 139, 210), (133, 153, 0), (211, 54, 130)]


@dataclass
class Plane:
    """One Wall Plane: the polygons that are confidently this plane's wall."""

    name: str
    polygons: list[list[tuple[int, int]]]


@dataclass
class Room:
    """One photograph's labels."""

    stem: str
    size: tuple[int, int]  # (width, height), must match the photo exactly
    planes: list[Plane]
    uncertain: list[list[tuple[int, int]]] = field(default_factory=list)
    note: str = ""
    # Whether this photograph's Wall Plane count is knowable from the photograph. Where it is not,
    # `<name>.planes.png` is not written at all and the plane tests skip the room, rather than a
    # guess being recorded as an answer. See `windows-with-curtains` below.
    label_planes: bool = True


def _fill(size: tuple[int, int], polygons: list[list[tuple[int, int]]]) -> np.ndarray:
    canvas = Image.new("L", size, 0)
    draw = ImageDraw.Draw(canvas)
    for polygon in polygons:
        draw.polygon(polygon, fill=255)
    return np.asarray(canvas) > 0


def _boundary_band(mask: np.ndarray, radius: int) -> np.ndarray:
    """Pixels within ``radius`` of the mask's edge, inside or out.

    Grown minus shrunk, both by ``radius``, using PIL's rank filters rather than scipy: the service
    does not depend on scipy and a labelling tool is no reason to add one.
    """

    image = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    size = 2 * radius + 1
    grown = np.asarray(image.filter(ImageFilter.MaxFilter(size))) > 0
    shrunk = np.asarray(image.filter(ImageFilter.MinFilter(size))) > 0
    return grown & ~shrunk


def render(room: Room) -> tuple[Image.Image, Image.Image]:
    """The two label images for one room."""

    width, height = room.size
    wall = np.full((height, width), NOT_WALL, dtype=np.uint8)
    planes_rgb = np.zeros((height, width, 3), dtype=np.uint8)

    plane_masks = [_fill(room.size, plane.polygons) for plane in room.planes]
    all_wall = np.zeros((height, width), dtype=bool)
    for mask in plane_masks:
        all_wall |= mask

    wall[all_wall] = WALL
    for index, mask in enumerate(plane_masks):
        planes_rgb[mask] = PLANE_COLOURS[index % len(PLANE_COLOURS)]

    # Uncertainty last, so it wins over both wall and non-wall: a pixel nobody can label must not
    # be counted for either side.
    band = _boundary_band(all_wall, UNCERTAIN_BAND)
    wall[band] = UNCERTAIN
    planes_rgb[band] = (0, 0, 0)

    explicit = _fill(room.size, room.uncertain)
    wall[explicit] = UNCERTAIN
    planes_rgb[explicit] = (0, 0, 0)

    return Image.fromarray(wall, mode="L"), Image.fromarray(planes_rgb, mode="RGB")


def main(rooms: list[Room]) -> int:
    for room in rooms:
        photo_path = FIXTURE_DIR / f"{room.stem}.jpg"
        if not photo_path.is_file():
            print(f"missing photograph: {photo_path}", file=sys.stderr)
            return 1
        with Image.open(photo_path) as photo:
            if photo.size != room.size:
                print(
                    f"{room.stem}: spec says {room.size}, photo is {photo.size}",
                    file=sys.stderr,
                )
                return 1
        wall, planes = render(room)
        wall.save(FIXTURE_DIR / f"{room.stem}.wall.png")
        planes_path = FIXTURE_DIR / f"{room.stem}.planes.png"
        if room.label_planes:
            planes.save(planes_path)
        elif planes_path.exists():
            planes_path.unlink()
        counts = {
            "wall": int((np.asarray(wall) == WALL).mean() * 100),
            "unsure": int((np.asarray(wall) == UNCERTAIN).mean() * 100),
        }
        print(
            f"{room.stem}: {len(room.planes)} plane(s), "
            f"{counts['wall']}% wall, {counts['unsure']}% unsure"
        )
    return 0


# ---------------------------------------------------------------------------
# The labels. Traced by eye from the photographs at 100-pixel grid overlays; the boundary bands and
# the explicit uncertain regions are where "traced by eye" is admitted rather than hidden.
# ---------------------------------------------------------------------------

ROOMS: list[Room] = [
    Room(
        # An empty room, two walls meeting in a crisp corner, a door frame at the right edge. The
        # cleanest split in the set: nothing occludes the corner, so a detector that cannot find it
        # here cannot find one anywhere.
        stem="empty-corner",
        size=(1280, 960),
        planes=[
            Plane(
                name="left wall",
                polygons=[
                    [
                        (0, 0),
                        (450, 0),
                        (505, 150),
                        (515, 300),
                        (528, 500),
                        (542, 700),
                        (556, 920),
                        (0, 920),
                    ],
                ],
            ),
            Plane(
                name="back wall",
                polygons=[
                    [
                        (505, 150),
                        (1280, 95),
                        (1280, 345),
                        (1195, 360),
                        (1195, 920),
                        (556, 920),
                        (542, 700),
                        (528, 500),
                        (515, 300),
                    ],
                ],
            ),
        ],
        uncertain=[
            # The floor junction runs along the bottom edge and is not clearly visible.
            [(0, 920), (1280, 920), (1280, 960), (0, 960)],
            # The coat rail screwed to the back wall.
            [(695, 485), (835, 485), (835, 520), (695, 520)],
        ],
        note="two planes, crisp unoccluded corner, door frame at the right edge",
    ),
    Room(
        # A corner with a clothes line across it: hanging garments, a suitcase and bedding cover
        # most of the join, and the two walls are different colours already. The occlusion case.
        stem="corner-with-clothesline",
        size=(1600, 1204),
        planes=[
            Plane(
                name="left wall",
                polygons=[
                    [
                        (5, 10),
                        (560, 10),
                        (600, 120),
                        (700, 230),
                        (755, 300),
                        (755, 990),
                        (700, 1080),
                        (5, 1120),
                    ],
                ],
            ),
            Plane(
                name="right wall",
                polygons=[
                    [(1385, 245), (1545, 220), (1548, 925), (1385, 935)],
                ],
            ),
        ],
        uncertain=[
            # Hanging clothes over the corner itself: the join is behind them, so its exact
            # position is not knowable from this photograph.
            [(760, 140), (1010, 140), (1010, 900), (760, 900)],
            # The strip of wall above the curtain, under the loft slab.
            [(1000, 140), (1390, 140), (1390, 260), (1000, 260)],
            # The corner behind the suitcase.
            [(690, 980), (800, 980), (800, 1160), (690, 1160)],
            # The window frame beside the right wall.
            [(1345, 190), (1395, 190), (1395, 960), (1345, 960)],
        ],
        note="two planes of different existing colours, corner occluded by clothes and luggage",
    ),
    Room(
        # Night, one tube light, two curtained windows. The bright band along the top is a blown-out
        # wall, which is the shadow criterion's mirror image, and the wall carries a switch plate.
        #
        # The **wall** is labelled; the **planes** are not, and that is deliberate. A return wall is
        # visible at the left edge, so "two planes" is a defensible reading; it is also a sliver
        # almost entirely behind a curtain, so "one plane a Dealer could paint" is defensible too.
        # The photograph does not settle it, and a fixture that asserts an answer the photograph
        # cannot give is a wrong label rather than a strict one. The plane tests skip this room.
        stem="windows-with-curtains",
        label_planes=False,
        size=(1599, 899),
        planes=[
            Plane(
                name="back wall",
                polygons=[
                    # Above the first window, under the curtain rod.
                    [(235, 15), (575, 15), (575, 140), (235, 95)],
                    # The lit band, either side of the light fitting.
                    [(700, 45), (790, 45), (790, 150), (700, 150)],
                    [(890, 45), (1240, 45), (1240, 150), (890, 150)],
                    # Between the second and third curtains, above and below the switch plate.
                    [(880, 230), (945, 230), (945, 440), (880, 440)],
                    [(880, 570), (945, 570), (950, 700), (880, 700)],
                    # Right of the third curtain.
                    [(1400, 190), (1550, 175), (1552, 600), (1400, 605)],
                ],
            ),
        ],
        uncertain=[
            # The left edge: a return wall may be there, but it is a sliver behind a curtain.
            [(0, 0), (120, 0), (120, 899), (0, 899)],
            # The wall/ceiling junction at the top right, lost in the light.
            [(1240, 0), (1599, 0), (1599, 165), (1240, 165)],
            # The light fitting itself and the glare around it.
            [(780, 0), (900, 0), (900, 60), (780, 60)],
            # The switch plate.
            [(860, 440), (950, 570), (950, 570), (860, 570)],
        ],
        note="one plane, night lighting with a blown-out band, windows and a switch plate",
    ),
]


if __name__ == "__main__":
    raise SystemExit(main(ROOMS))
