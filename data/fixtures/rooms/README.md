# Room photo fixtures

Real room photographs, with the wall hand-labelled, used by the slow lane to check that wall
detection is actually right rather than merely running. Two of the acceptance criteria in ticket #6
are claims about accuracy — furniture, windows, doors, floor and ceiling are excluded, and shadowed
parts of a wall remain part of the wall — and code cannot prove either about itself. It needs an
input where the answer is already known.

## What to add

For each room, two files with the same stem:

| File | What it is |
|---|---|
| `<name>.jpg` | The photograph, straight off the phone. No cropping, no correction. |
| `<name>.wall.png` | The answer: **white where the wall is, black everywhere else.** |

The mask must be the same pixel dimensions as the photo. Anything mid-grey is treated as "don't
count this pixel" — use it along a boundary you are genuinely unsure about, rather than guessing,
because a wrong label is worse than an absent one.

Drawing one takes about fifteen minutes in any editor with a lasso and a paint bucket: fill the
wall white, invert, fill the rest black, save as PNG.

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
each one is in `origin.md` beside the files. A photograph of somebody's home is not test data first
and a home second.

## If this directory is empty

The tests that need these files **skip, and say why**. They do not quietly pass: a green lane that
checked nothing is worse than a red one, because it is believed. Everything else in the slow lane
still runs.
