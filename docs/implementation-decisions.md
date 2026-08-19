# SpectraPaint — Implementation Decisions

**Status:** Living document · Append-only, newest entry last

Every major decision taken **while implementing** a ticket, why it was taken, and who took it.

This is not [design-decisions.md](./design-decisions.md). That document records the decisions made
*before* code existed, during the design grilling session. This one records the decisions the code
forced — the ones nobody could have made from the spec alone, because they only became visible once
a real file, a real library or a real failure was in front of somebody.

**Why this file exists.** V1 is worked ticket by ticket in isolated fresh contexts. Nobody working
ticket #9 was present for the argument that settled ticket #5, and the code alone records *what* was
chosen while losing *why* — which is exactly the half a later contributor needs in order to change
it safely. Without this file, every such decision gets silently re-argued, or worse, quietly
reversed by somebody who assumed it was arbitrary.

**Who** is recorded for the same reason a commit records an author: a decision has somebody who can
be asked about it. Name the person who owns the change — the human on the pull request — and note
where an agent wrote the code, since the reasoning was still a human's to accept.

---

## When to write an entry

Write one when any of these is true:

- You chose between genuine alternatives and the spec did not settle it
- You deviated from what a document said, for a reason
- You made a choice a later contributor could reasonably assume was arbitrary — and undo
- You bounded something: a limit, a timeout, a threshold, a page size
- Somebody reviewing the pull request asked "why is it done this way?"

Do **not** write one for: routine choices with an obvious default, anything already recorded in
`design-decisions.md`, or anything the code says plainly by itself.

If the decision is **hard to reverse**, it is an [ADR](./adr/) instead — see the test in
[README.md](./README.md). If it blocked you rather than being decided,
[technical-difficulties.md](./technical-difficulties.md) is the right file.

## Entry format

Copy this. Keep it short — a decision nobody reads is not recorded.

```markdown
## <n>. <What was decided, as a statement>

**Ticket:** #<number> · **Contributor:** <name> · **Date:** YYYY-MM-DD

**Decided:** what is now true in the code.

**Why:** the reasoning, including the alternatives rejected and what they would have cost.

**Consequence:** what this makes harder, and what would have to change to reverse it. Omit if
genuinely nothing.
```

Number entries sequentially and never renumber — a reference to entry 12 must stay pointing at
entry 12. Append; do not edit a past entry to say something different. If a decision is later
reversed, write a new entry that says so and links back to the one it replaces.

---

<!-- First entry goes here. -->
