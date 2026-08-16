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
