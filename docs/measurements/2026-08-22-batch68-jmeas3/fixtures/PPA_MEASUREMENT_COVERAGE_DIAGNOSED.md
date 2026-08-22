# `PPA measurement coverage` — the red is REAL, and here is why it arrived

This gate is the one measured instance of harm from the batch nobody measured.
The measurement report names it four times and diagnoses it zero times:

    ^^ FAILED: PPA measurement coverage
    54 record(s) in ppa-crosslayer/records/trials/b000/records_flat.json are REFUSED

It has been called "a content refusal over committed records — not host, not
load", which is correct, and "it arrived with v1.11.69", which is also correct.
Neither says WHY. This does.

## IT IS NOT A DATA REGRESSION. THE GATE'S SUBJECT WAS REPOINTED.

    81cd5321b  --coverage "$ROOT/benchmark-data/ppa/coverage.json"
    a4caccefe  --coverage "$ROOT/ppa-crosslayer/records/trials/b000/records_flat.json"

`benchmark-data/` is **not tracked in either tree**. At the landing tip the gate
opened nothing and said so:

    [CANNOT CHECK] INPUT_ABSENT: no such bundle: .../benchmark-data/ppa/coverage.json rc=2.
    ^^ NOT CHECKED (rc 2, non-fatal) — exempt until 2026-11-30

The records file is unchanged in v1.11.69 and was already present at 81cd5321b
(`git log 81cd5321b..a4caccefe -- <the file>` is empty). So no data got worse.
**A gate that had never opened a corpus was aimed at a real one, and the corpus
has real defects.** Confirmed by exit code, both subjects, on a clean tree:

    rc with the new subject  = 1
    rc with the old (absent) = 2

## THE REPOINT WAS DELIBERATE AND HONEST, AND CREDIT IS DUE

Whoever did it rewrote the exemption to say exactly what they had done:

> "...Nothing in this repository declares one; the record sets it would be
> measured against are committed and **this row now reads one**, so rc 2 is
> NO_EXPECTATION_SET and not INPUT_ABSENT. ... Writing one HERE would be
> composing the answer key after the exam"

That is the right call by this repo's rules, and they declined to fabricate the
missing denominator. **The defect is not the repoint.** It is that the exemption
mechanism, `uncheckable_until`, tolerates **rc 2 only** — and the repoint
activated a second, checkable half of the gate that returns **rc 1**. The gate
program is well built and separates the two questions itself:

> "54 record(s) ... are REFUSED; that is a finding about the record set and it
> does not depend on a denominator. Coverage over them is separately
> UNDETERMINED ... The rc is 1 for the records, not 0 for the coverage."

The repo's own convention, stated verbatim in two sibling exemptions, settles
whether that rc 1 is earned: **"a record that CAN be decided and fails is rc 1."**
It is earned. The gate is right to block.

## THE DECIDABLE DEFECTS, READ OUT OF THE COMMITTED DATA RATHER THAN OFF THE GATE

148 records, indexing to 91 identities, 54 refused. Verified directly:

**1. `worst_path_slack_ns` is UNDER-SCOPED — one artefact, three numbers.**
The parser emits the top-N worst paths from one STA report and files every one
of them under a **byte-identical scope**. Nothing distinguishes path 1 from path
3 — no rank, no endpoint, no path id:

    timing.setup.worst_path_slack_ns  sha256:4c1f7d31...  sta_spef_multicorner.rpt
      scope {check:setup, clock:clk, process:tt, rc_corner:max, temp:25.0, v:1.8}
      values 5.2 / 5.32 / 5.36        <- one identity, three facts

Four groups of this shape. This is precisely what the gate names a parser
defect, and the metric's own name concedes it: a *worst path* slack is per-path,
and the scope carries no path.

**2. CROSS-ARTEFACT DISAGREEMENT — two artefacts, one identity.**

    route.wirelength.um   openroad.log 16511.0  vs  openroad.metrics.json 16522
    route.via.count       openroad.log 4151     vs  openroad.metrics.json 4159
    timing.setup.worst_slack_ns
                          sta_mcorner_ocv.rpt 1.98  vs  sta_spef_based.rpt 3.58

The first two are the same run's log and its own metrics JSON disagreeing. As
the gate says, settling that is a declared authority decision (`_ppa/contract.py`),
never an index's.

**3. ONE ARTEFACT INDEXED UNDER TWO PATHS.** Records #60 and #88 differ in
exactly one field — and it is not the value:

    source.path   #60 = phase3/stage3/sta/sta_mcorner_ocv.rpt
                  #88 = reports/phase3/sta_mcorner_ocv.rpt

Same sha256, same value, two paths. Harmless to any number, but it files every
record from that report twice and is why each triple above appears six times
rather than three. It is also most of the gap between 148 records and 91
identities.

## THE 62 SCOPE_SENTINEL ROWS ARE A CAUSE THIS REPO HAS ALREADY DIAGNOSED

32 records carry `rc_corner: null` and 30 carry `clock: null` — explicit nulls,
not omitted keys, which is the distinction the gate refuses on. The producer-side
cause is already written down in this repo, on the sibling row `PPA head-to-head
records (end-to-end campaign)`:

> "the timing axis of both records is taken from `sta_spef_based.rpt`, and that
> report names no RC corner anywhere in this corpus — 490 of 490 metric rows
> sourced from it carry rc_corner null."

Same root cause, a different row. Those 62 are undecidable, which is rc 2
territory; the rc 1 is carried by the ~10 decidable ones above.

## WHAT I DID NOT DO, AND WHY

* **Did not touch `records_flat.json`.** Editing committed measurement data to
  turn a gate green is the same class of move as rewriting a baseline.
* **Did not widen the exemption to tolerate rc 1.** It would swallow every real
  finding above — which is the whole point of the rc split.
* **Did not write the missing `expected` list.** The v1.11.69 author already
  refused this for the correct reason and I am not going around them.
* **Did not repoint the gate back at the absent file.** That would restore a
  dormant gate and re-hide ten real defects.
* **Did not change the parser or the scope schema.** Adding a path discriminator
  changes what a record MEANS and what the committed set would have to be
  regenerated from. That is a producer/schema decision with an owner, and it is
  the same class of call this measurement line has correctly declined before.

## WHAT IS OWED, AND BY WHOM

1. `_ppa/backends/` — give `worst_path_slack_ns` a per-path discriminator in
   scope, or stop emitting more than one of them per scope. Until then, every
   record set that reads a multi-path STA report will refuse the same way.
2. `_ppa/contract.py` — declare which artefact wins when a run's log and its
   own metrics JSON disagree. Two of the refusals are waiting on exactly that.
3. The double-path indexing of one artefact is a producer or a collector bug and
   is the cheapest of the three to fix.

None of these is batch68's and none is mine. The point of this document is that
the red now has a mechanism instead of four sightings.
