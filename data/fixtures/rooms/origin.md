# Where these photographs came from

Consent, per this directory's README: a photograph of somebody's home is not test data first and a
home second. One row per photograph, and no photograph lands here without one.

| File | Whose room | Consent | Notes |
|---|---|---|---|
| `empty-corner.jpg` | Aniket Ghorpade's own home | Given by the owner, who supplied the photograph for this repository | Empty room, no people, no possessions in frame |
| `corner-with-clothesline.jpg` | Aniket Ghorpade's own home | Given by the owner, who supplied the photograph for this repository | Shows personal clothing and luggage |
| `windows-with-curtains.jpg` | Aniket Ghorpade's own home | Given by the owner, who supplied the photograph for this repository | Shows personal belongings on the sill and floor |

All three are straight off the phone: no cropping, no correction, no resizing. They are 25–120 KB
each, so none needed the "keep it to a sane resolution" trim the README asks for.

## What each one is for

| File | Failure mode it covers | Wall Planes |
|---|---|---|
| `empty-corner.jpg` | A crisp, wholly unoccluded corner, plus a door frame at the right edge. The control case: a detector that cannot split here cannot split anywhere. | 2 |
| `corner-with-clothesline.jpg` | A corner occluded by hanging clothes, a suitcase and bedding, with the two walls already different colours. Also a curtained window. | 2 |
| `windows-with-curtains.jpg` | Night, one tube light, a blown-out band along the top, two curtained windows and a switch plate. The bright-end mirror of the shadow criterion. | not labelled — see below |

`windows-with-curtains.jpg` has **no Wall Plane label**, deliberately. A return wall is visible at
the left edge, so "two planes" is a defensible reading of the photograph; it is also a sliver almost
entirely behind a curtain, so "one plane a Dealer could paint" is defensible too. The photograph does
not settle it. It was first labelled as one plane, and the split then found that region at 15% of the
wall's area — which is the label being arguable, not the detector being wrong, so the plane label was
withdrawn rather than defended. Its **wall** label stands; the plane tests skip it.

## Not included

A fourth photograph was considered and left out: a studio-style interior of unknown provenance. The
licence gate and this file both need to know where a photograph came from, and "found on the
internet" is not an answer either accepts.

## Exception: three stock photographs, added despite the rule above

| File | Whose room | Consent | Notes |
|---|---|---|---|
| `wood-doors-with-mirror.jpg` | Nobody's — stock photo, Unsplash | None obtainable; not a consenting owner's room | Two wood-veneer doors and a framed mirror on a plain wall |
| `dim-room-with-mirror.jpg` | Nobody's — stock photo, Wikimedia Commons ("Restaurant bathroom with two-way mirror, Edmond, Oklahoma", CC BY-SA 4.0) | None obtainable | Dim/warm lighting, mirror on tiled wall, resized from the original 6000x4000 to fit this directory's usual scale |
| `patterned-wallpaper-with-curtain.jpg` | Nobody's — stock photo, Unsplash | None obtainable | Patterned wallpaper filling most of the frame, plus a curtain |

These were added on 2026-09-14 at the repository owner's explicit instruction, overriding the "not
a shortcut past this" rule stated above for the first time. They were sourced and used to check
whether #31's over-claim bug (semantic pass calling a door/curtain/mirror `wall`) generalises beyond
the three consented fixtures — it did not reproduce on any of the three; see the commit/PR that
added them for the measurement. They carry no hand-drawn `.wall.png` or `.planes.png` labels, so the
accuracy tests in `tests/api/test_walls.py` skip them exactly as they would an unlabelled fixture;
they exist here as a reference set, not as graded fixtures. Given the rule above, treat this row as
the exception rather than the precedent: a future photograph of nobody's room still needs the same
explicit, on-the-record instruction to land here, not just "it looked useful."
