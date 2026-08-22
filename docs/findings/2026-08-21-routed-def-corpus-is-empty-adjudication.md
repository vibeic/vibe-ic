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

That is not a promise — it is a POSITIVE CONTROL that already runs.
`test_real_distinct_root_receipts_authorize_only_the_exact_transition` plants one
tracked routed DEF in a bound external checkout and asserts the shipped producer
and the dispatcher between them reach:

    candidate_doc["corpora"][0]["items"]        == 1
    candidate_doc["declared"] == ["ran"]        == 4
    len(candidate_doc["process_attestations"])  == 4

— and that an untracked candidate-local DEF planted as a laundering control does
**not** enter the population. So the machinery is live, not merely declared, and
this gate is a check that currently has nothing to check rather than one that
could only ever say "nothing to look at". All four directions are pinned:

| input | outcome | pinned by |
|---|---|---|
| one published routed DEF | 4 gates run, 4 attestations | `…authorize_only_the_exact_transition` |
| a corpus read, holding none | `NOT CHECKED`, blocking, unexempted | `…shipped_producer_over_an_empty_corpus…` (new) |
| producer could not determine | `NOT CHECKED`, blocking, distinct label | `…failed_producer_is_a_distinct_blocking…` |
| someone buys it an exemption | WIRING ERROR, still rc 2 | `…cannot_buy_an_uncheckable_exemption` (new) |

---

## The block is real, and here is the whole chain

"It blocks" was the brief's premise and I had been repeating it. Traced link by
link, from the hook actually installed on this host and the shipped landing
script — **not** by running a landing, which would mean running the 11-minute
sweep this brief rules out:

1. **Push to `main`** — the pre-push hook, `PUSH_TO_MAIN=1` branch, requires
   `.git/gatekeeper-stamp` (via `--absolute-git-dir`, so per-worktree) and
   requires it to name the exact `HEAD` being pushed.
2. **Only one writer.** `gatekeeper-land.sh` writes that stamp, and only in the
   `[ "$FAILED" -eq 0 ]` arm. Every other arm does `rm -f` on it:
   *"FAILURES ABOVE — stamp removed; the pre-push hook will refuse"*.
3. **That script runs the sweep.** `lane_hygiene` → `run_capture "full:repo-hygiene"`
   → `tools/ci/repo_hygiene_gates.sh`.
4. **The sweep refuses.** The routed-DEF population refusal is an unexempted
   mode-2 `NOT_CHECKED`, so `nunexempted != 0` and `gate_dispatch_finish` does
   `exit 2` — *"UNEXEMPTED NOT_CHECKED gate(s) block this run; no complete
   verdict exists for: …"*.
5. **Which becomes `FAILED`.** `run_capture` records the rc; the lane resolves
   red; the stamp is removed; the hook refuses the push.

The landing script already records this exact outage class, in its own words,
one line below the stamp removal:

> This tier is ABSOLUTE: it refuses on any red, including one the base tree
> already carries. On 2026-08-17 that made main's own tip unpushable to main.

**So the consequence, said out loud: until one cell carrying a routed DEF is
published, `main` is unpushable to `main` through the sanctioned path.** That is
not a side effect of this finding — it is the finding's cost, and a reader
deserves it stated rather than left to discover.

It still does not change the verdict. The remedy is to publish a cell that meets
`INDEX.md`'s bar, or to decide deliberately to accept the block — not to weaken
the gate that noticed. An honest refusal that blocks is worth more than a
manufactured pass that does not, and the corpus is empty precisely because
someone applied that rule one repository upstream.

(The hook installed on this host is an OLDER revision than
`tools/git-hooks/pre-push` — it still runs `benchmark evidence structure` at
push, which the tracked version removed as a landing concern, and it reads the
whole stamp file rather than its first line. Both carry the main-only stamp gate,
so the chain above holds on either.)

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
turns the whole sweep rc 2 regardless.

That the other NOT CHECKED rows are a different KIND of thing is measured, not
assumed. Every `uncheckable_until` in `repo_hygiene_gates.sh` — all **25** of
them, dated `2026-11-30` or `2027-02-28` — attaches to a
`run_tolerating_uncheckable`. Not one attaches to a plain `run`, and not one
attaches to the population refusal:

    $ grep -c '^[[:space:]]*uncheckable_until ' tools/ci/repo_hygiene_gates.sh
    25
    # …and the wrapper each one precedes, following the declaration past any
    # comment lines (24 are adjacent; one is separated by a `gate_serial`):
    #   run_tolerating_uncheckable  x25      run  x0      gate_dispatch_over  x0

And none of the 25 has expired. Measured 2026-08-22, ISO-8601 so a string
compare is a date compare: **3** dated `2026-11-30`, **22** dated `2027-02-28`,
**0** past their review date. That matters because `gate_dispatch_finish` fails
the run on an expired exemption too — so the routed-DEF population refusal really
is the only unexempted blocking refusal in the file today, rather than one red
among several of its class.

> **CORRECTED 2026-08-22.** This passage previously read **20** / **9** / **11**
> with `run_tolerating_uncheckable x20`. Those are the values at `81cd5321b`,
> this record's first-draft base and 214 commits earlier. They were **already
> wrong at `fed57f213`, the commit this file landed in** — measured there and at
> `a4caccefe` nineteen commits later, both **25 / 3 / 22**, so the figure never
> described the tree it shipped in and had not merely aged. The paragraph's
> CONCLUSION is unchanged and was re-derived independently before this edit; only
> the arithmetic beside it moved. Recorded in place rather than silently
> rewritten, because a corrected number with no history is the next reader's
> unverifiable claim. Counting method, since a one-pass `grep` is how the wrong
> figure arose: the wrapper is not always the line after the declaration —
> pairing on adjacency alone yields a spurious 20.

*A count that matches is not an identity.* The brief observed nine exempted NOT
CHECKED rows; **three** exemptions carry the earlier date, so the numeric
coincidence that made the earlier version of this paragraph worth writing does
not exist — and the caution it argued for stands on its own without it. Four of
the 25 sit inside `_per_published_cell_gates` and cannot fire at all while the
population is 0, leaving at most 21 that could produce a row, and which of those
actually returned rc 2 in a given run is a fact about that run. Without its
record the nine cannot be mapped one to one, and asserting it because the numbers
agree would be the "the count was true and the impression was false" error this
file keeps repairing.

And none of the 20 has expired. Measured 2026-08-22, ISO-8601 so a string
compare is a date compare: **9** dated `2026-11-30`, **11** dated `2027-02-28`,
**0** past their review date. That matters because `gate_dispatch_finish` fails
the run on an expired exemption too — so the routed-DEF population refusal really
is the only unexempted blocking refusal in the file today, rather than one red
among several of its class.

*A count that matches is not an identity.* Nine exemptions carry the earlier date
and the brief observed nine exempted NOT CHECKED rows, which is a coincidence of
integers and nothing more: four of the 20 sit inside `_per_published_cell_gates`
and cannot fire at all while the population is 0, leaving at most 16 that could
produce a row, and which of those actually returned rc 2 in a given run is a fact
about that run. Without its record the nine cannot be mapped one to one, and
asserting it because the numbers agree would be the "the count was true and the
impression was false" error this file keeps repairing.

So every exemption in the file is bought by a GATE whose own process returned
rc 2 — "I could not look at my subject". This row is not a gate's verdict at all;
it is the dispatcher stating that the denominator was zero, and it is the only
NOT CHECKED row in the script with no exemption mechanism available to it.
Granting it one was considered and rejected upstream, in writing, for a stated
reason.

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

State A remains reachable, from exactly two places, and the scope is narrower
than an earlier draft of this document said. `gatekeeper-land.sh` never sets the
binding — its only two mentions of `VIBE_IC_BENCHMARK_DATA` are a comment and a
`[ -n … ]` read — but the PR-merge path does not run it bare:
`gatekeeper-verify-merge.sh` `launch_hermetic_land_arm()` runs it inside
`hermetic_candidate_runner.py`, which **injects the pointer itself**
(`CORPUS_PATH = "/corpus"`, `"VIBE_IC_BENCHMARK_DATA": CORPUS_PATH`). That arm is
state **B**. And with `GATEKEEPER_BENCHMARK_DATA_SHA` set but no pointer,
`_corpus_location.resolve()` returns `REFUSED`, which is rc 2 whatever
`may_be_absent` says — so "bound but unpointed" was never state A either.

What is left is: `tools/ci/repo_hygiene_gates.sh` run directly with no pointer
exported, and a human typing `tools/gatekeeper-land.sh` outside the hermetic
runner with no pointer exported — and this repository does land by direct push on
a maintainer's machine. There the sentence is not true. That is a real but **secondary** observation
about a producer contract (`routed_def_corpus.py`'s docstring already promises
*"A broken pointer, a loose directory, or a failed git query is UNDETERMINED
(rc 2), never an empty population"*; an ABSENT corpus is the one row left out of
it). **It is fixed here, after the reason for deferring it turned out to be false.**

An earlier draft deferred it, calling `may_be_absent=True` a considered call-site
opt-in that should be proposed rather than landed. Checked: it was never argued
for at this call site. It arrived inside `v1.10.69` (`7c376e348`), a **78-file,
21,872-insertion** feature commit whose message does not contain the words
`may_be_absent`, `NO_CORPUS`, `absent`, `empty population` or `rc 0` — and the
test that pinned it was written in that same commit, so it pinned what arrived,
not what was decided.

The flag is CORRECT where it was designed to be used: a **gate** whose rc 0 is a
green row, which without it refuses every landing — `gatekeeper-land.sh` argues
exactly that, at length, for the gates it passes `--corpus-may-be-absent` to.
Here rc 0 is not a green row. The dispatcher turns an empty population into a
blocking `NOT_CHECKED` either way, so the flag bought nothing at this call site
and cost the distinction. And the module's own docstring already promised the
opposite: *"A broken pointer, a loose directory, or a failed git query is
UNDETERMINED (rc 2), never an empty population."* An absent corpus is a
could-not-look like the rest; it was the one row left out of that promise.

So state A is now rc 2 — *"corpus producer FAILED — denominator unknown"* — and
state B stays rc 0 with 0 items — *"corpus is EMPTY"*. **The outcome does not
move**: both are unexempted `NOT_CHECKED`, both block (pinned by
`test_empty_population_has_one_shard_owner_attestation_and_progress` and
`test_failed_producer_is_a_distinct_blocking_attested_result`). Only the true
sentence differs, and only the true one is printed.

`test_an_unconfigured_moved_corpus_is_explicit_no_corpus` becomes
`…_is_an_unknown_denominator`. That is a **tightening** — rc 0 to rc 2 — not a
relaxed assertion, and it is RED without the change.

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

**Measured, 2026-08-21.** `grep` for that sentence outside `_gate_dispatch.sh`
returns nothing. With the four lines deleted and one `uncheckable_until` written
above the wiring site, a sweep of two gates — one ordinary gate that passes, plus
the empty corpus — reports:

    [NOT_CHECKED] EMPTY CORPUS "an observed corpus": producer rc 0 yielded 0 item(s)
       ^^ NOT CHECKED (rc 2, BLOCKING; no exemption): corpus … is EMPTY  [0s]
    repo_hygiene_gates: 1 of 2 gate(s) passed; 1 NOT CHECKED — this is NOT a pass
      over: corpus … is EMPTY … (exempt until 2099-01-01) (0s)
    $ echo $?
    0

Two contradictory sentences in one run — *"BLOCKING; no exemption"* beside
*"exempt until 2099-01-01"* — and **the exit code sides with the exemption**.
Before the deletion the same input exits 2 with a wiring error. And the deletion
was free: of the 15 tests in the file it turned exactly ONE red, the new one.

The row is stamped either way. `_dispatch` appends the pending exemption to
`GATE_EX_UNTIL` *before* it judges it, so the date lands on the record and
`not_checked_unexempted` comes back empty — measured, and asserted by the test so
it cannot quietly change shape. Nothing downstream can tell this row from one
that legitimately bought tolerance. The wiring error is the entire defence.

Two tests are added to `test_routed_def_corpus_dispatch.py`:

* `test_a_population_refusal_cannot_buy_an_uncheckable_exemption` — an exemption
  over an empty population is a WIRING ERROR and the run still exits 2.
* `test_the_shipped_producer_over_an_empty_corpus_blocks_and_never_passes` —
  state B end to end through the SHIPPED producer: a real checkout whose index
  holds no routed DEF expands to 0 items, records `NOT_CHECKED`, carries no
  exemption, leaves an rc-2 process attestation, and blocks.

### And the branch main is actually in said nothing at all

One change IS made to what the declaration *says* — not to its verdict, its
blocking, or its rc.

`refuse()`'s absent-corpus branch prints a full sentence with a cause and a
remedy. The branch where a corpus **was** opened and holds no routed DEF printed
**nothing**: measured against the real published clone, the producer's entire
stderr was one line, the resolution note.

    $ VIBE_IC_BENCHMARK_DATA=<clone> python3 tools/ci/routed_def_corpus.py --repo .
    [routed-def corpus] note: VIBE_IC_BENCHMARK_DATA overrides … -> …/ic
    # and that is all of it

So the LESS informative outcome was loud and the more informative one was silent,
and the loudest thing in the run — a blocking dispatcher refusal — was produced by
the quietest possible producer. A maintainer who hits this red has no path from
the row to the fact that the corpus was emptied on purpose on 2026-08-20.

It now states its measured zero: which tree it scanned and by which origin, that
the index holds 0 routed DEFs, what a member looks like, that this is an EMPTY
POPULATION and not a clean one, and what makes it non-empty again. **stderr only —
stdout is the machine population and prose there would become an item.** rc is
unchanged, the population is unchanged, the row is unchanged, and it still blocks.

Pinned by `test_a_corpus_that_was_read_and_holds_none_says_so`, which is RED
without it.

---

The gate's VERDICT does not change. It is `NOT CHECKED`, it is `BLOCKING`, it has
no exemption, and all three are correct. What changes is that the rule keeping it
that way can no longer be deleted in silence, and that the row can now tell a
reader why it is there.
