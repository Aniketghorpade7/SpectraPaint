# Room photo fixtures

Real room photographs, with the wall hand-labelled, used by the slow lane to check that wall
detection is actually right rather than merely running. Two of the acceptance criteria in ticket #6
are claims about accuracy — furniture, windows, doors, floor and ceiling are excluded, and shadowed
parts of a wall remain part of the wall — and code cannot prove either about itself. It needs an
input where the answer is already known.

## What to add

For each room, three files with the same stem:

| File | What it is |
|---|---|
| `<name>.jpg` | The photograph, straight off the phone. No cropping, no correction. |
| `<name>.wall.png` | Where the wall is: **white wall, black everything else.** |
| `<name>.planes.png` | Where one Wall Plane ends and the next begins: **one flat colour per plane, black for non-wall.** |

Both masks must be the same pixel dimensions as the photo. In `<name>.wall.png` anything mid-grey is
treated as "don't count this pixel" — use it along a boundary you are genuinely unsure about, rather
than guessing, because a wrong label is worse than an absent one.

`<name>.planes.png` answers the question `<name>.wall.png` cannot: ticket #7 splits the wall into
Wall Planes, and "how many, and where is the join" is not derivable from a single wall mask. Two
conventions make it checkable rather than merely suggestive:

* **Colour a plane only where `<name>.wall.png` is white.** A pixel nobody could label as wall
  cannot be assigned to a plane either, so uncertain pixels are black here.
* **Planes are ordered left to right by centroid**, which is the order the service numbers
  `wall_plane_N` in. Plane 1 in the label is the plane the service calls `wall_plane_1`.

Label a plane only where the photograph supports it, and where the photograph does not settle the
question, **do not write the file at all**. `windows-with-curtains.jpg` has no `.planes.png`: a
return wall is visible at its left edge, so "two planes" is defensible, and that wall is a sliver
almost entirely behind a curtain, so "one plane a Dealer could paint" is defensible too. The plane
tests skip a room with no plane label, which is the honest outcome — a fixture that asserts an answer
the photograph cannot give is a wrong label, not a strict one. Say why in `origin.md`.

Drawing one takes about fifteen minutes in any editor with a lasso and a paint bucket: fill the
wall white, invert, fill the rest black, save as PNG.

The labels currently here were traced as polygons instead, and the polygons are kept in
[`tools/fixtures/label_rooms.py`](../../../tools/fixtures/label_rooms.py) — run it to regenerate the
PNGs after an edit. Either way is fine; polygons were chosen because a diff of them says what
somebody decided about a photograph, where a diff of a PNG says nothing at all. That tool also grows
a "don't count this" band along every traced boundary automatically, on the grounds that a line
drawn by eye over a curtain fold is not accurate to the pixel.

## What makes a set worth having

Aim for three photos, chosen for the failure modes that matter rather than for looking nice:

1. **A wall with a strong shadow on it** — a dark strip near the ceiling, or a hard shadow from a
   window. This is the single most damaging failure: a shadowed wall wrongly excluded leaves a
   ghost of the old paint after recolouring. Label the shadowed part **as wall**, because it is.
2. **A wall partly occluded by furniture** — a wardrobe, a sofa, a hanging. Label only the wall you
   can actually see.
3. **A wall with a window or a door in it.** Label the frame and the glass as not-wall.

Shot on the phones the customers actually use, and of Indian rooms, since that is the domain gap
`docs/handoff/custom-wall-segmentation-model.md` identifies as the real one. These photos are also
the beginning of the ground-truth set `docs/design-decisions.md` §10 requires for evaluation — one
collection effort, two deliverables.

## Consent

Only rooms whose owner is happy for the photograph to live in this repository. Record whose room
each one is in [`origin.md`](./origin.md) beside the files. A photograph of somebody's home is not
test data first and a home second.

A photograph whose provenance is unknown — found on the internet, of nobody's room in particular —
is not a shortcut past this. The licence gate and `origin.md` both need an answer.

## What the tests currently expect

`measured.toml` beside these files records what wall detection actually scores on each photograph,
for the metrics where it falls short of the targets in `tests/api/test_walls.py`. It exists because
the first real photographs showed the pipeline does not clear two of those targets, for a reason no
threshold edit fixes (#31). Adding a photograph does not require adding an entry: a fixture with no
entry is held to the target, which is the right default — entries are for known, tracked shortfalls,
and the lane fails if one is still present after the pipeline catches up.

## If this directory is empty

The tests that need these files **skip, and say why**. They do not quietly pass: a green lane that
checked nothing is worse than a red one, because it is believed. Everything else in the slow lane
still runs.
