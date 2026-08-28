# DISTIL — re-deriving a published page, and the two things that came out of it

The capture step produced `recoveries.json` while re-deriving `vibeic.ai/ppa.html`
against the tree on 2026-08-28. Two records: one Bucket A, one Bucket B.

## Record 1 (Bucket A) — a page and its own receipt disagreed

MEASURED. The page's headline metric cards and its VERIFICATION RECEIPT state
the same closed-loop census:

    headline cards   DECLARED_ONLY 18 | EXECUTABLE 0 | REMEASURED 1 | ROLLBACK_PROVEN 2
    receipt          DECLARED_ONLY 18 | EXECUTABLE 0 | REMEASURED 3 | ROLLBACK_PROVEN 0

The cards had been updated when the tiers moved; the receipt had not. The
receipt is the half a reader trusts MOST — headed "what this review actually
ran", naming a pinned commit — so the stale half was the authoritative-looking
half. Nothing read both. Every existing guard on that page reads a sentence
against an EXTERNAL artefact (`ppa_page_claim_check` against a claims document,
`derived_corpus_figure_check` against what a program derives), and a page can
satisfy both while contradicting itself.

Shipped as `programs/page_states_one_figure_twice_check.py` with
`programs/tests/test_page_states_one_figure_twice.py`. Can-fail arm is the
published page byte-for-byte as it stood; can-pass arm is the repaired one.

### Three false positives, each now a can-pass test

The first version compared prose to prose. Swept over the 19 published pages, it
returned three findings on one page and **all three were the rule's own blind
spot**:

| what it flagged | what it actually was |
|---|---|
| `MAXEDGES=2` vs `MAXEDGES=15` | two settings of one knob in a NEG/POS experiment |
| `met1.PIN=1/2` -> `met1.PIN=68/16` | GDS layer/datatype pairs, stock vs fixed |
| `README:30-43` vs `README:48-51` | line ranges in two file citations |

The repair: a quantity is compared only if the page puts it on a metric card. A
card is the page's own declaration that a name is a published FIGURE, and that
is the shape the measured defect had — a card against a receipt sentence.

### And one true positive the repair then deleted

The guard added to reject `1/2` and `30-43` was `(?![0-9,]*\s*[/\-.])`. It also
rejected `ROLLBACK_PROVEN=0.` at the end of a sentence, reading the full stop as
a decimal point — silently dropping one of the two statements the rule exists to
catch, while passing every false-positive test that motivated it. Fixed by
requiring a DIGIT after the separator. Both directions are now pinned.

### Why it is not wired into the hygiene lane

It has no subject in this repository. MEASURED: `ppa-e2e/report/winner/report.md`
and `docs/PPA_CURRENT_STATE.md` both declare zero figures on a metric card, so
both return rc 2. Declaring it anyway would make it exit 2 on every run — a red
that only means "nothing was there". That is not a verdict about any page; it is
the gate reporting its own empty corpus, and a lane full of such reds teaches a
reader to stop reading them. Wiring it to LOOK wired would be the defect, not
the fix. Routed via `benchmark/CAPTURE_ROUTING.json` instead, under
`publish.figure_agreement`.

## Record 2 (Bucket B) — a hand-run grep nearly published a false accusation

`why_not_bucket_a`: the rule is "search every venue the audit itself searches
before contradicting it", and which venues an audit searches is written in its
own source in a different shape each time — a lambda here, a glob list there —
so deciding whether a hand-run search covered them requires reading the audit's
intent, not matching a pattern.

MEASURED. `checker_execution_wiring_audit` credits `ppa_area_threshold_check`
with a PROG runner. A grep over `programs/*.py` found only a docstring sentence,
and a paragraph was drafted for the published page saying the credit was "earned
on prose". Running the audit's OWN `_py_evidence` over the audit's OWN PROG
population found the real invocation one directory over:
`benchmark/cvdp_gate.py:97` imports `run_ppa_area_threshold` and blocks on its
verdict. The audit's source even says why that directory is in scope — a comment
records the identical miss being fixed once before, for
`harness_verdict_forgery_gate`.

The draft was withdrawn before publication. Appended to
`skills/open-benchmark-methodology/SKILL.md`.
