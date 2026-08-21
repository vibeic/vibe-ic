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
correct declaration. Neither is changed here. What is changed is the **sentence**
the blocking row prints, because on `main` it is not true.

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

## The declaration that IS dishonest, and what is changed

Not the blocking-ness. The **sentence**.

On `main` the row reads *"corpus … is EMPTY — nothing was checked over it"*. That
is a claim **about the corpus**. Nothing on `main` measured the corpus: there is
no `benchmark-data/` to read and no pointer to a clone. The producer's own stderr
says so — `NO_CORPUS … NOTHING WAS SCANNED` — and then that outcome is handed to
the dispatcher as `rc 0, 0 items`, which is the same pair of numbers a *measured*
zero produces.

Two different states, one sentence:

| state | what happened | what the row says today |
|---|---|---|
| **A** — no corpus anywhere, no pointer (`main`, now) | nothing was opened | "corpus is EMPTY" |
| **B** — pointer set at a real clone, index carries no routed DEF | the corpus was read and is empty | "corpus is EMPTY" |

Both were measured today and are byte-indistinguishable at the dispatcher.

`_corpus_location.py`'s own header names this class of collapse as the defect —
*"THE FOUR OUTCOMES, AND COLLAPSING ANY TWO OF THEM IS THE DEFECT"* — and
`routed_def_corpus.py`'s docstring promises *"A broken pointer, a loose
directory, or a failed git query is UNDETERMINED (rc 2), never an empty
population."* A corpus that is simply **absent** was the one row left out of that
promise, and it is the row `main` is in.

The change is therefore: state A is reported as an **unknown denominator**
(`rc 2` from the producer → *"corpus producer FAILED — denominator unknown"*),
state B as a **measured empty population** (`rc 0`, 0 items → *"corpus is EMPTY"*).
Both remain NOT CHECKED. Both remain BLOCKING. Both remain un-exemptable. Only
the true sentence differs, and only the true one is printed.

Today `main` is in state A, so `main` blocks on *"denominator unknown"* — which is
what actually happened — instead of on a claim about a corpus it never opened.
