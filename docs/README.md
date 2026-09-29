# SpectraPaint Documentation

Start here.

## Reading order

1. **[../CONTEXT.md](../CONTEXT.md)** — the domain glossary. Read first; everything else assumes this
   vocabulary.
2. **[design-decisions.md](./design-decisions.md)** — the hub. Every decision made so far, with the
   reasoning, plus what is still open.
3. **[adr/](./adr/)** — Architecture Decision Records for the choices that are expensive to reverse.
4. **[implementation-decisions.md](./implementation-decisions.md)** — the decisions the code forced,
   ticket by ticket: what, why, and who.
5. **[technical-difficulties.md](./technical-difficulties.md)** — what fought us on the way, solved
   or still open, so nobody meets it twice.
6. **[handoff/](./handoff/)** — work deliberately parked, written up so it can be resumed cold.

## Before writing code

| Document | Why |
|---|---|
| **[conventions.md](./conventions.md)** | Coding rules. Above all: **use the glossary vocabulary in the code** — synonyms are how a codebase becomes unreadable, and tickets worked in isolated contexts drift fast. |
| **[ui-guidelines.md](./ui-guidelines.md)** | Minimal UI rules. The one that is not about taste: **neutral grey chrome, nothing saturated near the render** — a colour looks different depending on what surrounds it, and this app exists for colour judgement. |
| **[specs/v1-spectrapaint.md](./specs/v1-spectrapaint.md)** | What V1 is, end to end, with the two test seams. |

`conventions.md` and `ui-guidelines.md` are linked from every ticket, since neither loads
automatically.

## While writing code

Keeping these two current is part of the ticket, not paperwork afterwards — see `conventions.md`
§7c. Tickets are worked in isolated fresh contexts, so anything not written down is lost to the next
contributor.

| Document | What goes in it |
|---|---|
| **[implementation-decisions.md](./implementation-decisions.md)** | Every major decision taken while implementing, **why**, and **who** took it. `design-decisions.md` holds the decisions made before the code existed; this holds the ones the code forced. |
| **[technical-difficulties.md](./technical-difficulties.md)** | The technical difficulties you hit — resolved, worked around, or still open. Dead ends are worth as much as fixes. |

## Architecture Decision Records

| # | Title | Status |
|---|---|---|
| [0001](./adr/0001-local-first-inference-over-localhost-rest.md) | Local-first inference over a localhost REST contract | Accepted |

An ADR is written only when a decision is hard to reverse, would puzzle a future reader without the
context, and came out of a real trade-off with genuine alternatives. If any of those three is
missing, it belongs in `design-decisions.md` instead.

## Parked and planned work

Written up so they can be picked up cold.

| Topic | Status | Document |
|---|---|---|
| Objective 2 — calibration-aware colour accuracy | **Parked.** Deferred during design; V1 excludes shade reading, but it remains the end goal | [handoff/objective-2-colour-accuracy.md](./handoff/objective-2-colour-accuracy.md) |
| Custom wall segmentation model | **Planned, not started.** Required before commercial deployment — the SegFormer weights used in development are non-commercial | [handoff/custom-wall-segmentation-model.md](./handoff/custom-wall-segmentation-model.md) |
| Dealer-testing bugs, September 2026 | **Diagnosed, decisions taken.** 9 reported bugs traced to 3 shared root causes; 6 proposed issues | [bugs/README.md](./bugs/README.md) |

## What this project is

SpectraPaint shows a paint dealer's customer what **their own room** looks like in a shade the
dealer actually sells — using the customer's photograph rather than a generic stock room, and
preserving the room's real lighting, shadows and texture so the result is believable.

Built with Arun Paint Industries as industry partner.
