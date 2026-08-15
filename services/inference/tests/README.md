# tests

Two seams, deliberately kept few. See the spec Testing Decisions section.

- `api/` — Seam 1, the REST contract. Behaviour and lifecycle, models included.
- `render/` — Seam 2, the render engine as a pure function. Fast, deterministic, analytically checkable.

The model adapters are deliberately not a seam: they are covered through the contract, and
mocking them would assert only that the mocks work.
