# The candidates carried a version stamp from a base that no longer exists

Found by asking a question I had not asked of my own deliverable: **are the
emitted candidates still regenerable, and do they still match?**

    $ enhancement_emit.py --records recoveries.json --out-dir /tmp/emit_land
    $ diff /tmp/emit_land/... candidates/...

    < # Auto-captured by benchmark-enhancement-capture at plugin v1.11.70
    > # Auto-captured by benchmark-enhancement-capture at plugin v1.11.69

`enhancement_emit.py` stamps each sketch with the plugin version AT EMIT TIME.
Mine were emitted on `a4caccefe` (v1.11.69) and carried forward, unchanged,
onto a tree whose `plugin.json` says **1.11.70**. So the shipped artefact
asserted a provenance that was true where it was written and false where it
sits.

## Why this is the same class one more time

A provenance field is a claim about WHICH VERSION produced a thing. Nobody
re-derives it; every consumer reads it. Carried across a rebase, it keeps
asserting the old answer with no visible sign — the same shape as a schema key
that survives its own refutation, and the same shape as a register that keeps
calling an implemented variable a gap. **A stamp is only true relative to the
tree it was taken on, and moving the tree does not move the stamp.**

It is also, precisely, the failure `enhancement_emit.py` itself warns about in
its own source, where it explains why an unreadable version is emitted as the
non-semver string `"unknown"`:

    a provenance field nobody measured must be visibly non-data, so that it
    fails the first time anyone sorts or compares by it. A plausible semver
    constant never fails, which is exactly how a stale one survives.

`v1.11.69` is a plausible semver constant. It did not fail. It survived.

## Fixed on this branch only

Regenerated here: all sketches now stamp **v1.11.70**, matching this branch's
base and its `plugin.json`.

**The record branch is deliberately NOT changed.** It is based on `a4caccefe`,
which IS v1.11.69, so its stamp is correct there. Rewriting it to say 1.11.70
would introduce the very defect this file is about, in the opposite direction.
The two branches now differ in exactly this one field, and each is right about
its own tree.

## What made it visible

Only re-running the emitter and diffing. The file looked fine, parsed fine, and
said something plausible and wrong. Nothing about reading it would have shown
it — the check is to REGENERATE and COMPARE, which is the same discipline as
re-polling the base rather than trusting the last answer.
