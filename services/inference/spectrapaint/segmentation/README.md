# segmentation — finding Wall Planes

1. An ADE20K-trained semantic model labels the scene (wall, floor, ceiling, windowpane, door)
2. That wall region constrains SAM 2, which produces crisp boundaries
3. Output is a soft Alpha Matte, never a binary mask
4. The region is split into Wall Planes using vertical structure

Boundary precision is decoupled from network resolution: the mask is upsampled and its boundary
band refined at full resolution.

The SegFormer ADE20K checkpoints are non-commercial and are for development only.
Replacement: [custom-wall-segmentation-model.md](../../../../docs/handoff/custom-wall-segmentation-model.md).
Do not distil from them.
