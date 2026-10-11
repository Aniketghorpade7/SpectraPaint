# tests

Two seams, deliberately kept few. See the spec Testing Decisions section.

- `api/` — Seam 1, the REST contract. Behaviour and lifecycle, models included.
- `render/` — Seam 2, the render engine as a pure function. Fast, deterministic, analytically checkable.

The model adapters are deliberately not a seam: they are covered through the contract, and
mocking them would assert only that the mocks work.

One narrow exception:

- `segmentation/` — rules about how the Alpha Matte is built that a synthetic array pins more
  exactly than any photograph can: the shape of its edges (#51), and the wall-confidence floor
  and the classes held to a lower one (#48). The one stand-in there replaces the ONNX session's
  output only, to check how `runtime.json` is read; it never asserts what a model predicts. Whether
  these rules suit real rooms is still the slow lane's question, answered by `api/test_walls.py`.
  Add a test here only for a rule that synthetic geometry can state exactly. Anything else belongs
  in one of the two seams.
