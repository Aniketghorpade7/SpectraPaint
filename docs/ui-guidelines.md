# UI Guidelines

**V1's UI exists to demonstrate the use case. Keep it minimal. Do not build a design system.**

This is short on purpose. It covers only the decisions that are expensive to get wrong or that
thirteen separately-worked tickets would otherwise each answer differently.

---

## The one rule that is not about taste

**The chrome must be neutral grey, and nothing saturated may sit near the render.**

This is correctness, not aesthetics. **A colour looks different depending on what surrounds it** —
simultaneous contrast. Put a saturated blue button beside the rendered wall and it genuinely shifts
how the Customer perceives that paint. They then choose a Shade they saw wrong, and the complaint
lands on the Dealer.

It is why every serious photo editor has grey chrome. SpectraPaint's whole purpose is colour
judgement, so it matters here more than most.

Concretely:

- **Greys only** for backgrounds, panels, borders and text
- **No accent colour anywhere near the preview.** If a control must stand out, use weight, size or a
  border — not hue
- **A generous neutral margin around the render**, so the wall is judged against grey rather than
  against whatever is next to it
- **Pick one appearance and stay there.** No light/dark toggle in V1 — a changing surround changes
  perceived colour, which defeats the point
- **Selection is shown by an outline or a chip, never by a wash on the wall being judged.** The
  wash is for *all* the walls equally, as a faint "here is what was found". The moment one of them
  gets a stronger mark of its own, that wall is the one the Customer is judging and the mark
  corrupts its colour — a white selection mark made the chosen wall paler than its neighbours, so
  the Dealer picked a Shade against a colour that was never on the wall. Use a neutral grey line
  along the surface's own edge, with a contrasting halo so it reads on light and dark alike.

The only saturated colour on screen should be **the paint**, and the Shade swatches.

## Tokens

The whole set. Anything beyond this is out of scope for V1.

**Greys** — one scale, roughly: near-black text, three mid greys for borders and secondary text,
two panel surfaces, one page background. Around 7 steps. Pick them once, name them, reuse them.

**Spacing** — multiples of 4px: `4, 8, 12, 16, 24, 32`. Nothing else.

**Text** — three sizes only: **body**, **small** (captions, Shade Codes), **heading**. One weight
step for emphasis. No display sizes, no custom fonts — the system font stack is fine.

**Tap targets — minimum 44px.** The Dealer works fast at a counter, possibly on a touchscreen (still
unconfirmed — see `design-decisions.md` §12). Small targets cost taps, and the budget is three.

## Components

Only what the tickets need. Build them once, reuse them:

`Button` · `Panel` · `ShadeSwatch` (must show its **Shade Code**) · `ProgressMessage` ·
`EmptyState` · `ErrorState` · `Toast`

**Every surface needs its loading, empty and error state.** For a tool whose design goal is that
the Dealer never looks incompetent, these are not edge cases — they are the states that decide
whether it works.

## Interaction

- **Tap only.** No brush tools, no drag-to-draw. The correction surface is taps: add, merge, split
- **Never a mandatory confirmation step.** A confirmation is a tap we cannot afford. Act, and let it
  be undone
- **Never a dead end.** Every error state offers an action

### What Undo covers, and what it does not (issue #50)

**Act, and let it be undone** needs an actual Undo. In V1 it is the application menu's Edit →
Undo/Redo, and it covers exactly two things: **Shade changes and wall-choice changes**, within one
open Consultation. Undoing restores the previous wall choice and Shades together and re-renders;
undoing everything painted returns to the original photo. Undo/Redo are disabled when there is
nothing to undo or redo.

**What it does not cover:**

- **Wall corrections (Add/Split/Merge).** They are not undoable in V1 — undoing one honestly would
  need a plane-history stack on the service and a REST contract change, because a correction can
  retire the plane id a snapshot names. The Dealer simply re-runs a correction. Any correction also
  clears the paint history, so no snapshot is replayed onto a wall that no longer exists.
- **Across saves.** A reopened Consultation starts with no history: what the Customer saw last time
  is what reopening shows, not an editable past.

If the shop PC turns out to be a touchscreen (still open — see `design-decisions.md` §12), the menu
is not reachable by touch and **an on-screen Undo affordance will be needed** alongside it; the
Toast pattern from `useLibrary.ts` is the candidate.

## Semantics

Use real elements — `<button>` for actions, `<h1>`–`<h3>` for headings in order, `<label>` bound to
inputs, `<ul>` for lists. A `<div>` with a click handler is not a button: it breaks keyboard use and
screen readers for free reasons.

Images of the room need meaningful `alt` text (the room and Shade, not "image").

## Explicitly out of scope for V1

Animations and transitions · theming · a component library or design-system package · responsive
breakpoints beyond the shop screen · custom fonts · icon sets beyond the handful genuinely needed ·
onboarding or tours.

If a ticket seems to need something here, it probably does not. Ask before building it.
