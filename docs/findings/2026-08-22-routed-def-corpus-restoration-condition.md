# The routed-DEF corpus is empty, the publisher says so, and one publication is
# not enough to restore the gate

Second, independent adjudication of the one NOT CHECKED row on `origin/main`
that carries no exemption:

```
NOT CHECKED (rc 2, BLOCKING; no exemption):
corpus "published cells carrying a routed DEF" is EMPTY — nothing was checked over it
[population: producer rc 0, 0 items]
```

Measured 2026-08-22 on a clean worktree of `origin/main` @ `81cd5321b`
(`PYTHONDONTWRITEBYTECODE=1`). It reaches the same verdict as
`2026-08-22-routed-def-corpus-adjudication.md` by a different route — that
record read this repository's publishing programs; this one reads the
**publishing repository's own committed statement** — and it then contradicts
one load-bearing sentence in it.

## Verdict: (2), the corpus is legitimately empty

Not "the producer is wrong" (1) and not "the artefacts are under a name the
producer does not look at" (3). The artefacts were looked for where they are
supposed to be, and they are not anywhere.

## What was measured, at the publisher rather than at the producer

`routed_def_corpus._ORIGIN` names `https://github.com/vibeic/benchmark-data`.
That repository's tip on 2026-08-22 is `3b58ccd42`. Its complete recursive tree
(`GET /repos/vibeic/benchmark-data/git/trees/3b58ccd42?recursive=1`,
`truncated: false`):

| query over the published tip | result |
|---|---|
| blobs in the whole repository | 6929 |
| blobs whose name is `routed.def` | **0** |
| blobs whose name ends `.def`, anywhere, any depth | **0** |
| `v<version>_<PDK>` cell directories under `ic/` | **0** |
| designs under `ic/` | 9 |
| what remains under every one of those 9 `ic/<design>/` | `input/` only |

There is no routed DEF in the published corpus, at any path, under any name.
The population is zero at the source, not merely zero in this checkout.

## The publisher says so itself, in two committed files

This is the part the earlier adjudication infers and this one reads. The corpus
repository states its own state and its own contract:

`CELL_MATRIX.md`:

> **No cells are published.** The four that were here were withdrawn on
> 2026-08-20: two carried a passing verdict over an audit in which zero of 246
> registered gates had run, and one of those also carried a second,
> contradictory `FAIL` audit at a nested path the generator could not see.

`INDEX.md` carries the measurement the withdrawal was made on:

| cell | verdict | registered gates | actually passed |
|---|---|---|---|
| spm × sky130A | PASS_WITH_WAIVERS | 246 | 154 |
| spm × gf180mcuD | PASS_WITH_WAIVERS | 246 | 154 |
| u_hawaii_adc × sky130A | **PASS** | 246 | **0** |
| spm × ihp-sg13g2 | PASS_WITH_WAIVERS | *unset* | **0** |

So the answer to "why is the population zero" is not an inference about this
repository's programs. It is a dated decision, published in the repository that
would have to carry the artefact, for a reason that is better than the artefact
it removed: *a verdict is not evidence, `passed_gate_count` is*.

`ic/spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def` — the single member
this loop ever had — belonged to the fourth row of that table.

## What would have to exist for this gate to check anything

Taken from the publisher's own numbered contract (`INDEX.md`, "Publishing a
result"), not from a reading of this repository's intent:

1. The run **actually happened**, in a real flow run, on the PDK named in the
   directory.
2. `passed_gate_count > 0`. A FAIL that ran is worth more there than a PASS
   that did not.
3. **Exactly one** `reports/audit/phase23_completion_audit.json`.
4. The directory is `v<plugin-version>_<PDK>`, matched by a regex whose
   mismatch is fatal.
5. The artefacts are committed, not a summary of them.

and — this repository's own requirement, which the contract above does not
state — the routed DEF at exactly

```
ic/<design>/v<version>_<PDK>/phase3/stage3/pnr/routed.def
```

because that is the only shape `routed_def_corpus._index_paths` counts: it
requires the path relative to `ic/` to have **exactly six components**, with
`parts[2:] == ("phase3", "stage3", "pnr", "routed.def")`.

## The sentence this record contradicts

The earlier adjudication closes with:

> The moment one such cell lands in the corpus repository and the pointer is
> bound, this loop expands to a real population.

That premise is not safe, and the published corpus is where it fails. Every
directory in the published tree that holds a `stage3/pnr` stage, today:

| files | directory |
|---|---|
| 11 | `protocol_parity/espi/phase3/stage3/pnr` |
| 10 | `protocol_parity/interlaken/phase3/.phase3_held/stage3/pnr` |
| 11 | `protocol_parity/lpc/phase3/`**`phase3`**`/stage3/pnr` |
| 11 | `protocol_parity/mdio/phase3/stage3/pnr` |
| 12 | `protocol_parity/sgmii/phase3/stage3/pnr` |

Three of the five are canonical. One is a deliberate hold. **One is a doubled
directory**, and it is not a one-off inside that cell — the same cell doubles
its phase-2 stage too:

| stage entries under `protocol_parity/lpc/` | vs `protocol_parity/espi/` |
|---|---|
| `phase2/`**`phase2`**`/` — 12 files | `phase2/stage1/` 6, `phase2/stage2/` 6 |
| `phase3/`**`phase3`**`/` — 28 files | `phase3/stage3/` 98, `phase3/reports/` 2 |

`<design>/<version>/phase3/phase3/stage3/pnr/routed.def` is **seven** components
relative to `ic/`, not six. The producer does not count it, exits 0, and prints
nothing on stdout — which is byte-for-byte the population an empty corpus
produces. A cell published in that shape leaves the row saying
`is EMPTY — nothing was checked over it` while a routed DEF is published, and
nothing anywhere would say otherwise.

This is not a hypothetical shape, and it is not an inference about the producer
either. Run against two synthetic corpus checkouts that differ only in that one
directory:

| corpus contains | producer rc | items on stdout |
|---|---|---|
| `ic/demo/v9.9.9_openpdkx/phase3/stage3/pnr/routed.def` | 0 | **1** |
| `ic/demo/v9.9.9_openpdkx/phase3/`**`phase3`**`/stage3/pnr/routed.def` | 0 | **0** |
| no routed DEF at all | 0 | **0** |

Rows two and three are the same bytes. Nothing downstream can tell the blocking
row's *stated* reason (`is EMPTY`) from the unstated one (*a routed DEF is
published where I cannot count it*).

`test_routed_def_population_is_depth_exact.py` pins all three. The pin is not
vacuous: mutating a **copy** of the producer from `len(parts) == 6` /
`parts[2:]` to `len(parts) >= 6` / `parts[-4:]` gives 2 failed / 1 passed, while
the identical harness over a byte-identical copy gives 3 passed — so the colour
is the mutation and not the scaffold. The tracked producer was not touched
(`git status --porcelain` empty; sha256 `d04b8215…` before and after).

**And it is the same defect class the withdrawal was made for.** `u_hawaii_adc`
was withdrawn because its run wrote a second audit at `reports/`**`reports`**`/audit/…`
— one directory too deep — saying FAIL, 3.5 s before the PASS the public page
displayed. `INDEX.md` turns that into rule 3 and adds the instruction:

> Check for a nested `reports/reports/` before committing.

That instruction names one spelling of the bug. The corpus contains three
directories with that shape and **not one of them is the spelling the
instruction names**:

| same-name nesting, published corpus @ `3b58ccd42` | files |
|---|---|
| `protocol_parity/lpc/phase2/phase2` | 12 |
| `protocol_parity/lpc/phase3/phase3` | 28 |
| `protocol_parity/usb_pd/reports/phase3/phase3` | 24 |

Measured before this change, **no program in this repository detected any of
them**: `grep -rn 'reports/reports'` over `programs/` and `tools/` returned
nothing, and there was no general nested-duplicate detector either.

### The third one is the withdrawal, reproduced

`protocol_parity/usb_pd` is not merely misshapen. Four report names exist at
BOTH `reports/phase3/` and `reports/phase3/phase3/`, and **three of the four
differ in content**:

| report | outer (what consumers read) | inner (one directory deeper) |
|---|---|---|
| `foundry_handoff_audit.json` | `"verdict": "SKIP"`, `found: []`, both required files **missing** | `"verdict": "PASS"`, both **found** |
| `si_crosstalk.json` | no SPEF, structural screen, `max_crosstalk_noise: 0.0` | real SPEF, `max_crosstalk_noise: 1791.87` of 1800 mV, 500 coupling-dominated nets |
| `si_crosstalk.rpt` | differs | differs |
| `gds_size.json` | identical | identical |

The two copies are not two writes of one run: their own `chip_gds` /`spef`
fields name **different source trees** (`vibe-ic/benchmark_phase1/usb_pd/…`
against `AI_IC_design/_usb_pd_phase3_stage/…`, the second in a repository that
has since been retired). One published cell therefore carries two runs' answers
to the same question, at two depths, and every consumer reads exactly one of
them.

That is the `u_hawaii_adc` shape — a second, contradictory verdict one directory
too deep — still committed, in a different design, two days after the cell that
carried it was withdrawn for exactly that and the instruction to check for it
was written down. It is why the rule below is a program and not another line in
a contract.

## Decision: BLOCKING stays, and it buys no exemption

Unchanged from the earlier adjudication, and for the same two reasons, both of
which this record's measurements strengthen rather than alter:

**Not an exemption.** `_gate_dispatch.sh` mode 2 refuses one by construction —
*"a dispatcher-owned population refusal … cannot consume an uncheckable
exemption — an unknown denominator must remain blocking"*. It is also the wrong
instrument on the facts: the population is zero because a publisher deliberately
removed four cells that were not evidence. A dated tolerance would restore
exactly the silence that removal ended.

**Not a declaration change.** This row is the only statement on `main` that
post-route geometry is checked over nothing at all. An advisory row would still
be advisory on the day the corpus refills — it would stop blocking precisely
when it regains the ability to find something.

**So: neither instrument. The declaration is already the honest one.** What was
missing is not a change to the gate but a written restoration condition, and the
condition the earlier record wrote is incomplete: it names what must be
published and omits the shape it must be published in.

## What is fixed here, and what is only filed

**Fixed (this branch):** `benchmark_evidence_structure_check.py` gains a
`NESTED_DUPLICATE` nonconformance. A cell whose run tree contains a directory
nested directly inside a same-named parent is refused at publish time. It is a
new refusal on an unprotected checker that `benchmark_evidence_publish.py`
already runs before staging and `gatekeeper-land.sh` already runs over the tree,
so it needs no new wiring, and it is strictly tightening — it can turn no red
green. It closes the gap between "a cell is published" and "the routed-DEF loop
can see it", which is what makes the restoration condition above true rather
than hopeful.

The red, with the same test file on both arms:

| arm | result |
|---|---|
| final tests vs `origin/main`'s checker (byte-identical copy) | **6 failed**, 1 passed |
| final tests vs the fixed checker | **7 passed** |

The 1 that passes on the red arm is the negative control — the canonical cell,
which carries `phase3/` and `reports/phase3/` in one tree, must not be refused.
It is written first so that a rule matching the NAME rather than the ADJACENCY
is caught by a test instead of by a reviewer.

And the rule is measured rather than argued. Over the full historical
published-cell corpus at the last commit that carried it — 5 cells, **388**
distinct directories — it fires exactly **once**, on
`u_hawaii_adc/v1.9.86_sky130A/reports/reports`. One true positive, 387 clean
directories, zero false positives.

Targeted regression (load 61–72 on 32 cores): the checker's own suite plus every
test file that names its rules — 125 passed, 12 skipped — and
`size_policy_drift_check.py`, which probes `check_folder` as its decision entry
point, still exits 0.

### And it does NOT reach the three instances above. Measured, not assumed.

`--tree` over one synthetic root carrying both shapes at once:

| unit in the tree | what the checker did |
|---|---|
| `ic/demo/v9.9.9_openpdkx/` with `reports/reports/` | **FAIL — NESTED_DUPLICATE**, named |
| `protocol_parity/demo2/` with `phase3/phase3/` **and** `reports/phase3/phase3/` | **not enumerated at all** |

`1/2 conformant, 1 nonconformant`, rc 1 — and the two units are the IC root and
the cell. Nothing under `protocol_parity/` was discovered, because
`_discover_evidence_folders` keeps a child only under `ic/<IC>/`.

So this rule covers the population the routed-DEF loop actually draws from —
`ic/<design>/v<version>_<PDK>/` — and covers nothing else. The three
`protocol_parity/` instances that made the shape credible remain uncaught, in
the corpus repository, today. Catching them needs `_discover_evidence_folders`
to enumerate a second tree, which changes what the structure gate reports over
the whole corpus and would land three live FAILs on a tree `gatekeeper-land.sh`
walks. That is a decision about the structure gate's scope, not a side effect of
adjudicating one blocking row, so it is **named here and not taken**.

The honest summary of the fix is therefore narrower than "the nested-duplicate
bug is fixed": a cell can no longer be PUBLISHED into the routed-DEF corpus in a
shape that corpus cannot see. The instances already published elsewhere are
untouched.

**Filed, not fixed:** `routed_def_corpus.py` hardcodes `may_be_absent=True`, so
"a corpus was read and holds no routed DEF" and "no corpus was supplied at all"
reach the dispatcher as the same rc 0 / 0 items. That file is line 71 of
`REQUIRED_AUTHORITY_PATHS` in `tools/ci/protected_landing_transition.py`;
`build_receipt` refuses a candidate whose protected bytes match neither BASE's
`current` nor BASE's `next` tuple — `_match_state` raises *"protected tuple
matches neither authorised atomic state"* — and the PREPARE arm explicitly
refuses a candidate that changed live protected bytes. So the fix is reachable
only through a base-authorised PREPARE → ACTIVATE pair, and not from one
candidate commit. Recorded here so the next transition has the reason to hand.

**A note for whoever lands this.** A sibling branch,
`fix/routed-def-corpus-empty-adjudication`, reaches the same verdict about the
corpus and then edits `tools/ci/routed_def_corpus.py` directly (70 lines) with
no manifest change. On the reading above that candidate cannot land as it
stands: same manifest bytes as BASE, protected tuple equal to neither
authorised state, so `_match_state` raises before any test runs. The two
branches do not conflict — this one touches no protected path — but landing them
as a pair would not produce the fix that branch intends.

## What this deliberately does not do

It does not publish anything to make the corpus non-empty, and it does not widen
the producer's population rule so that the doubled shape would count. Widening
would make the row green over a run tree whose own layout is the defect that
withdrew a cell. The population rule is right; the publish path is what should
refuse to produce a shape it cannot see.
