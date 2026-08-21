# segmentation — finding Wall Planes

1. An ADE20K-trained semantic model labels the scene (wall, floor, ceiling, windowpane, door)
2. That wall region constrains SAM 2, which produces crisp boundaries
3. Output is a soft Alpha Matte, never a binary mask
4. The region is split into Wall Planes using vertical structure

Boundary precision is decoupled from network resolution: the mask is upsampled and its boundary
band refined at full resolution.

The modules, in pipeline order:

| Module | What it does |
|---|---|
| `semantic.py` | Labels the scene; returns the wall, the four named exclusions, and the wall confidence |
| `prompts.py` | Turns that region into the point prompts that constrain SAM 2 |
| `matte.py` | Runs the refiner and builds the soft matte — shadow restored, exclusions removed, boundary sharpened |
| `split.py` | Splits the wall matte into Wall Planes by vertical structure (edge + shading valley), hard partition — soft only wall↔non-wall, crisp wall↔wall |
| `walls.py` | Composes the above into Wall Planes, validates the partition, and decides when there is no wall to find |

Ticket #7: `walls.planes_from` now returns `wall_plane_1..N` (typically 1-3) via `split.split_alpha_into_planes`; every wall pixel belongs to exactly one plane and the sum of planes equals the original matte (no dark seam). See `split.py` module docstring and `docs/implementation-decisions.md:30`.

The SegFormer ADE20K checkpoints are non-commercial and are for development only.
Replacement: [custom-wall-segmentation-model.md](../../../../docs/handoff/custom-wall-segmentation-model.md).
Do not distil from them.
