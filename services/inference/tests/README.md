# tests

Two seams, deliberately kept few. See the spec Testing Decisions section.

- `api/` — Seam 1, the REST contract. Behaviour and lifecycle, models included.
- `render/` — Seam 2, the render engine as a pure function. Fast, deterministic, analytically checkable.

The model adapters are deliberately not a seam: they are covered through the contract, and
mocking them would assert only that the mocks work.

One narrow exception:

- `segmentation/` — the matte's wall-confidence floor and its exempt classes (#48), checked on
  synthetic boolean maps. The rule is arithmetic, and a 1x4 array pins it more exactly than any
  photograph can. The one stand-in there replaces the ONNX session's output only, to check how
  `runtime.json` is read; it never asserts what a model predicts. Whether the rule suits real rooms
  is still the slow lane's question, answered by `api/test_walls.py`. Add a test here only for a
  rule that is arithmetic in the same way. Anything else belongs in one of the two seams.
