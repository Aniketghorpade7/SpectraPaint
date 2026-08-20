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
| `walls.py` | Composes the above into Wall Planes, and decides when there is no wall to find |

One region for now: ticket #6 finds the wall, ticket #7 splits it into planes. `walls.py` already
returns a list of Wall Planes with ids, so #7 lengthens a list rather than changing a shape.

The SegFormer ADE20K checkpoints are non-commercial and are for development only.
Replacement: [custom-wall-segmentation-model.md](../../../../docs/handoff/custom-wall-segmentation-model.md).
Do not distil from them.
