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
added them for the measurement. Given the rule above, treat this row as the exception rather than
the precedent: a future photograph of nobody's room still needs the same explicit, on-the-record
instruction to land here, not just "it looked useful."

On 2026-09-16 (issue #33), two of the three gained hand-drawn labels — polygons kept in
`tools/fixtures/label_rooms.py`, which regenerates the PNGs — so they now run in the accuracy tests
as graded fixtures:

| File | Failure mode it covers | Wall Planes |
|---|---|---|
| `patterned-wallpaper-with-curtain.jpg` | A wall with a strong pattern: every column carries texture, so the flat-wall case at its hardest for the energy cue. | 1 |
| `dim-room-with-mirror.jpg` | Three walls at two slanted corners (a rolled camera), tiled wainscot in deep shadow, a mirror bridging one corner — the three-wall and shadow modes in one frame. | not labelled — see below |

`dim-room-with-mirror.jpg` has **no Wall Plane label**, deliberately, and it is the measured answer
issue #33's raise-the-cap question needed. Three planes are plainly visible to a person, but the
boundaries are not photometrically findable: the left corner is faint (paint against paint in
shadow) and the right corner is cream wall against cream wall with both sides lit — no edge exists
at all. The corner columns (x≈996 and x≈1747, measured from the tile lines) sit far from where any
cue peaks, so labelling planes would assert a split the pipeline cannot produce and the seam/purity
tests would rightly fail it. Its **wall** label stands; the plane tests skip it, exactly as
`windows-with-curtains.jpg`'s do, and decision 50 records the measurement.

On 2026-10-04 (issue #48) the third, `wood-doors-with-mirror.jpg`, gained a wall label too, so what
exempting `mirror` from the wall-confidence floor costs on a real mirror is measured rather than
assumed. Its mirror and frame are not wall, so the matte painting them counts as non-wall leakage.

| File | Failure mode it covers | Wall Planes |
|---|---|---|
| `wood-doors-with-mirror.jpg` | One flat wall with two doors and a framed mirror: what a mirror exempt from the confidence floor costs. | not labelled — #48 asked for the wall only |

## Dealer-testing photographs, added for #48

| File | Whose room | Consent | Notes |
|---|---|---|---|
| `blue-wall-sunlit.jpg` | A private home; the owner asked not to be named | Given by the owner for this repository, received by the repository owner | Shows a loft of personal papers, a laptop and clothing |
| `green-room-sunlit.jpg` | A private home; the owner asked not to be named | Given by the owner for this repository, received by the repository owner | Shows a bed, clothing, bags and personal belongings on shelves |
| `yellow-wall-sunlight-band.jpg` | A private home; the owner asked not to be named | Given by the owner for this repository, received by the repository owner | Empty wall, a chair, and a glimpse of a washroom through the doorway |
| `kitchen-tiles.jpg` | A private home; the owner asked not to be named | Given by the owner for this repository, received by the repository owner | Kitchen wall, half tiled and half bare plaster |

All four came by WhatsApp, so they are **not** straight off the phone. WhatsApp recompressed them to
720x1280 and removed their EXIF metadata. That is the same resolution as the copies in the bug
report (`docs/bugs/SpectrapaintBugs.pdf`), so these photographs are what the Dealer's photos looked
like when they reached the app. They were copied in byte for byte, with no further change.

`blue-wall-sunlit.jpg` is the page-6 photograph itself, identical to the one embedded in the report.
`green-room-sunlit.jpg` is **not** page 4's photograph. It shows the same room, photographed again on
2026-10-03 from a slightly different angle, because the original was not available.
`yellow-wall-sunlight-band.jpg` shows the wall in page 7's screenshot, whose original was not in the
report either.

| File | Failure mode it covers | Wall Planes |
|---|---|---|
| `blue-wall-sunlit.jpg` | A sunlit recessed wall that the semantic checkpoint labels `mirror`, which the #31 floor deleted (bug 9). | not labelled — see `tools/fixtures/label_rooms.py` |
| `green-room-sunlit.jpg` | Daylight on a back wall and a pillar, behind shelves, clothes and a bed (bug 7). | not labelled — see `tools/fixtures/label_rooms.py` |
| `yellow-wall-sunlight-band.jpg` | A hard vertical band of sunlight down one flat wall: the bright-end counterpart of a cast shadow (bug 9). | 1, but the label is withheld until #60 — see `tools/fixtures/label_rooms.py` |
| `kitchen-tiles.jpg` | Wall tiles the checkpoint does not call wall (bug 8). Unlabelled for now; the ticket for that bug labels it. | not labelled |
