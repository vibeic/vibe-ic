# The routed-DEF corpus is empty, and that is the true answer

**Subject:** `repo_hygiene_gates.sh` corpus `published cells carrying a routed
DEF` — the one NOT CHECKED row on `main` that carries no exemption and blocks.

    NOT CHECKED (rc 2, BLOCKING; no exemption):
    corpus "published cells carrying a routed DEF" is EMPTY —
    nothing was checked over it
    [population: producer rc 0, 0 items]

**Adjudicated 2026-08-21 against `main` at `a00f53f20` and against the published
corpus at its own `origin/main`, fetched the same day.**

---

## The verdict

The corpus is **legitimately empty**. The producer is not wrong and it is not
asking the wrong question. Every routed DEF this repository ever published was
**withdrawn on 2026-08-20**, by owner instruction, because not one of the four
published cells was a pass.

That makes `NOT CHECKED` the correct verdict, and it makes `BLOCKING` the
correct declaration. **Neither is changed here, and no exemption is bought** —
the dispatcher refuses one by design, and buying it would be the weakening this
brief forbids.

What ships instead is a test for the rule itself. The property "an empty corpus
never becomes a pass" rests on exactly one four-line branch in
`_gate_dispatch.sh`, and **nothing asserted it**: deleting it left the suite
green. That is now pinned.

---

## What was measured

### 1. The population is zero, and the refusal reproduces

On a clean checkout of `main`, with no corpus pointer set:

    $ python3 tools/ci/routed_def_corpus.py --repo "$PWD"
    [routed-def corpus] NO_CORPUS: nothing at <repo>/benchmark-data/ic and
    VIBE_IC_BENCHMARK_DATA is unset. ... NOTHING WAS SCANNED, 0 routed DEF(s)
    were examined ...
    rc=0, stdout: 0 lines

### 2. The corpus is not in this repository at all

`benchmark-data/` has no tracked file on `main` — not one, not `input/`, not
`PUBLISHING.md`. It left in `v1.10.56` (`e23d0be5e`, 2026-08-17), which moved
`benchmark-data`, `benchmark_external` and `IP` to their own repositories. The
routed DEF the corpus once selected — `benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/
phase3/stage3/pnr/routed.def` — left with it.

    $ git ls-tree -r --name-only origin/main | grep -c '\.def$'
    0

### 3. The published corpus itself publishes zero routed DEFs

`https://github.com/vibeic/benchmark-data`, `origin/main` = `bcf2f94`, fetched
2026-08-21:

    $ git ls-files | grep -c 'routed\.def'      0
    $ git ls-files | grep -icE '\.def$'         0
    $ find . -name routed.def -not -path './.git/*' | wc -l    0

Zero tracked, zero untracked, zero under any other spelling. `ic/` retains only
`ic/<ic>/input/` — design input, which is not a result.

### 4. Why it is zero — the withdrawal

`bcf2f94`, 2026-08-20, *"withdraw all four published cells, and write down what
may be published here"*. Measured before removal:

| cell | verdict | registered gates | gates that actually RAN |
|---|---|---|---|
| spm × sky130A | PASS_WITH_WAIVERS | 246 | 154 |
| spm × gf180mcuD | PASS_WITH_WAIVERS | 246 | 154 |
| u_hawaii_adc × sky130A | **PASS** | 246 | **0** |
| spm × ihp-sg13g2 | PASS_WITH_WAIVERS | *unset* | **0** |

Two carried a passing verdict over an audit in which not one of 246 registered
gates ever ran. A third wrote two completion audits — the deeper one saying
`FAIL`, 3.5 s before the `PASS`, invisible to the page generator. And the two
that did run 154 gates are refused by the shuttle operator's own precheck.

**The corpus is empty because publishing a non-pass as a pass was stopped.** The
gate reporting NOT CHECKED is that decision arriving, correctly, one repository
downstream.

---

## The three candidate answers, adjudicated

**(1) "The producer is wrong."** Refuted by measurement. Pointed at the real
published corpus it announces the override and still returns zero:

    $ VIBE_IC_BENCHMARK_DATA=<clone> python3 tools/ci/routed_def_corpus.py --repo .
    [routed-def corpus] note: VIBE_IC_BENCHMARK_DATA overrides
      <repo>/benchmark-data/ic -> <clone>/ic
    rc=0, stdout: 0 lines

Same zero, obtained by looking. The producer finds nothing because there is
nothing.

**(3) "The population query asks the wrong question."** Refuted by measurement.
There is no DEF under any other name or path: zero files match `\.def$` anywhere
in the published repository's index, and zero `routed.def` exist on its disk.
The nearest thing — `protocol_parity/*/phase3/stage3/pnr/` — carries
`chip_top_pnr.v`, `routed.drc.rpt` and a GDS, and **no DEF at all**.

**(2) "The corpus is legitimately empty."** True. With one correction to the way
the brief framed it: the gate is **not structurally unsatisfiable**. It is
satisfiable, and the condition is written down.

---

## What would have to exist for this gate to check anything

One published cell, in `https://github.com/vibeic/benchmark-data`, at

    ic/<ic>/v<major>.<minor>.<patch>_<pdk>/phase3/stage3/pnr/routed.def

meeting the bar that repository's own `INDEX.md` sets, written in the same commit
that withdrew the four:

1. the run actually happened, on the PDK named in the directory;
2. `passed_gate_count > 0` — *a verdict is not evidence; `passed_gate_count` is*;
3. exactly one `reports/audit/phase23_completion_audit.json`, with no nested
   `reports/reports/`;
4. the directory version is the plugin version the run used;
5. the artefacts are committed, not a summary of them.

Plus, for CI to see it: `VIBE_IC_BENCHMARK_DATA` pointed at a clone of that
repository (or `GATEKEEPER_BENCHMARK_DATA_SHA` binding one).

On the day one such cell lands, the population becomes 1, four per-cell gates go
live, and this row stops blocking **with nothing in this repository changed**.

---

## Why there is no dated exemption, and why BLOCKING stays

**A dated exemption is not available at this wiring site, by design.** The
dispatcher refuses one:

    tools/ci/_gate_dispatch.sh
      elif [ "$tolerate" -eq 2 ] && [ -n "$ex_until" ]; then
        _gate_wiring_error "\"$label\" is a dispatcher-owned population refusal
    and cannot consume an uncheckable exemption — an unknown denominator must
    remain blocking"

`uncheckable_until` before this row is a **wiring error**, and a wiring error
turns the whole sweep rc 2 regardless. The nine other NOT CHECKED rows carry
dated exemptions because each is a `run_tolerating_uncheckable` gate whose own
process returned rc 2; this row is not a gate's verdict at all — it is the
dispatcher stating that the denominator was zero. Granting it a tolerance was
considered and rejected upstream, in writing, for a stated reason.

**And BLOCKING is right.** The subject of these four gates is post-route geometry
on published silicon. Today nothing published carries post-route geometry. A
sweep that prints ~70 green rows while zero post-route checks ran is precisely
the "the count was true and the impression was false" failure the surrounding
comments in `repo_hygiene_gates.sh` were written to remove. Making the row
non-blocking — by dropping `GATE_DISPATCH_ATTEST_POPULATION=1` and falling back
to the legacy synthetic row — restores that impression exactly. That is
weakening what the gate asks, and it is refused.

**An empty corpus stays rc 2 NOT CHECKED. It does not become a pass.**

---

## Is the row's SENTENCE true? Yes — on the path that produces it

`main`'s row reads *"corpus … is EMPTY — nothing was checked over it"*. That is a
claim **about the corpus**, so it is true only if a corpus was actually opened.
Two states reach the dispatcher as the identical `rc 0, 0 items`:

| state | what happened |
|---|---|
| **A** — nothing at `benchmark-data/`, no pointer | nothing was opened |
| **B** — a corpus was resolved and its index carries no routed DEF | it was read, and it is empty |

Both were measured today and are byte-indistinguishable at the dispatcher, and
that collapse is the shape `_corpus_location.py`'s own header calls the defect
(*"COLLAPSING ANY TWO OF THEM IS THE DEFECT"*).

**But the review and landing path is in state B, not state A.**
`gatekeeper_review._published_corpus_binding()` resolves the corpus BEFORE the
hygiene set runs — `$VIBE_IC_BENCHMARK_DATA`, then
`$VIBEIC_BENCHMARK_DATA_CHECKOUT`, then a default `~/_matrix_benchmark_data`
clone — refuses with rc 2 and a named remedy if it cannot, and exports
`GATEKEEPER_BENCHMARK_DATA_SHA` so the binding cannot be shadowed. Its own
measurement, 2026-08-20:

    pointer UNSET -> ... the routed-DEF corpus EMPTY and BLOCKING, 239s wasted.
    pointer SET   -> ... and `published-evidence index honest` FAILS — a real
                     defect the empty corpus hid outright.

So on the path that produced the row in question, the corpus **was** opened, the
zero **was** measured, and the sentence is true. **There is no dishonest
declaration here to repair.** An earlier draft of this document claimed there
was; that claim was wrong and is withdrawn.

State A remains reachable — `tools/ci/repo_hygiene_gates.sh` run by hand, or
`gatekeeper-land.sh`'s `lane_hygiene` on a host that never exported the pointer —
and there the sentence is not true. That is a real but **secondary** observation
about a producer contract (`routed_def_corpus.py`'s docstring already promises
*"A broken pointer, a loose directory, or a failed git query is UNDETERMINED
(rc 2), never an empty population"*; an ABSENT corpus is the one row left out of
it). It is recorded here and deliberately **not** changed tonight: reversing
`may_be_absent=True`, which `_corpus_location` documents as a considered
call-site opt-in and which `test_an_unconfigured_moved_corpus_is_explicit_no_corpus`
pins, is a decision to propose, not to land unilaterally on a secondary finding.
It also has **zero** effect on the outcome: both states already block (measured —
`test_empty_population_has_one_shard_owner_attestation_and_progress` and
`test_failed_producer_is_a_distinct_blocking_attested_result` both pin rc 2).

---

## What IS shipped: the absolute rule was itself unpinned

The rule the brief calls absolute — *an empty corpus stays rc 2 NOT CHECKED and
must never become a pass* — rests on exactly one mechanism, and **nothing tested
it**.

There is one way this row could stop blocking: buy it the dated tolerance a human
may buy for an ordinary gate. `gate_dispatch_finish` counts a `NOT_CHECKED` row
as unexempted only when `GATE_EX_UNTIL[i]` is empty — and `_dispatch` **records**
the pending exemption unconditionally, before it judges it. So an
`uncheckable_until` written above this wiring site is consumed, stamped onto the
row, and removes it from `not_checked_unexempted`. The only thing left refusing
the run is the mode-2 arm:

    tools/ci/_gate_dispatch.sh:667-670
      elif [ "$tolerate" -eq 2 ] && [ -n "$ex_until" ]; then
        _gate_wiring_error "\"$label\" is a dispatcher-owned population refusal
    and cannot consume an uncheckable exemption — an unknown denominator must
    remain blocking"

**Measured:** `grep` for that sentence outside `_gate_dispatch.sh` returns
nothing, and removing the branch leaves the suite green. Four lines stood between
this corpus and a silently exempted row, and they were a free edit.

Two tests are added to `test_routed_def_corpus_dispatch.py`:

* `test_a_population_refusal_cannot_buy_an_uncheckable_exemption` — an exemption
  over an empty population is a WIRING ERROR and the run still exits 2.
* `test_the_shipped_producer_over_an_empty_corpus_blocks_and_never_passes` —
  state B end to end through the SHIPPED producer: a real checkout whose index
  holds no routed DEF expands to 0 items, records `NOT_CHECKED`, carries no
  exemption, leaves an rc-2 process attestation, and blocks.

Nothing about the gate's declaration changes. It is `NOT CHECKED`, it is
`BLOCKING`, it has no exemption, and all three are correct. What changes is that
the rule keeping it that way can no longer be deleted in silence.
