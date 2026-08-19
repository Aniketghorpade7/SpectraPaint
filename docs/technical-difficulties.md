# SpectraPaint — Technical Difficulties

**Status:** Living document · Append-only, newest entry last

The technical difficulties hit while implementing, whether or not they were solved.

**Why this file exists.** Every ticket is worked in a fresh isolated context, so a difficulty that
cost one contributor a day costs the next one a day again — the second person has no way to know it
was ever met. Recording the dead ends is worth as much as recording the fix: knowing that an
approach was tried and does not work is what stops it being tried a third time.

Write it down **while you are stuck**, not after. The details that make an entry useful — the exact
error, the platform, the version — are the first thing you forget once it works.

---

## When to write an entry

- Something took materially longer than it should have, for a reason worth naming
- A platform difference bit (the target is Windows; contributors develop on Linux or Windows)
- A library, model or tool behaved differently from its documentation
- You tried an approach, it did not work, and you abandoned it
- You are **still blocked** — record it open, and say what you need. An unrecorded blocker looks
  identical to work nobody started
- You worked around something rather than fixing it, and the workaround will outlive your ticket

A difficulty that ends in a deliberate choice usually also earns an entry in
[implementation-decisions.md](./implementation-decisions.md). Link the two rather than repeating.

## Entry format

```markdown
## <n>. <The difficulty, in one line>

**Ticket:** #<number> · **Contributor:** <name> · **Date:** YYYY-MM-DD ·
**Status:** open | worked around | resolved

**What happened:** the symptom, concretely — the actual error, the platform, the versions.

**Why it was hard:** what made it non-obvious. This is the part that saves the next person.

**Where it stands:** the fix, the workaround and what it costs, or — if still open — what is needed
to move it.
```

Number entries sequentially and never renumber. Update an entry's **Status** when it changes, and
say what changed; do not delete a resolved difficulty, because the reason it happened is still true.

---

<!-- First entry goes here. -->
