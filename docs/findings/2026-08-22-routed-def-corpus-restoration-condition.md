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

This is not a hypothetical shape. It is the shape of a run tree that is
committed to the published corpus right now.

**And it is the same defect class the withdrawal was made for.** `u_hawaii_adc`
was withdrawn because its run wrote a second audit at `reports/`**`reports`**`/audit/…`
— one directory too deep — saying FAIL, 3.5 s before the PASS the public page
displayed. `INDEX.md` turns that into rule 3 and adds the instruction:

> Check for a nested `reports/reports/` before committing.

That instruction names one spelling of the bug. The corpus contains two others
(`phase2/phase2/`, `phase3/phase3/`) that nobody checked for, and **no program
in this repository detects any of them** — `grep -rn 'reports/reports'` over
`programs/` and `tools/` returns nothing, and there is no general nested-duplicate
detector either.

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

**Fixed (this commit):** `benchmark_evidence_structure_check.py` gains a
`NESTED_DUPLICATE` nonconformance. A cell whose run tree contains a directory
nested directly inside a same-named parent is refused at publish time. It is a
new refusal on an unprotected checker that `benchmark_evidence_publish.py`
already runs before staging and `gatekeeper-land.sh` already runs over the tree,
so it needs no new wiring, and it is strictly tightening — it can turn no red
green. It closes the gap between "a cell is published" and "the routed-DEF loop
can see it", which is what makes the restoration condition above true rather
than hopeful.

**Filed, not fixed:** `routed_def_corpus.py` hardcodes `may_be_absent=True`, so
"a corpus was read and holds no routed DEF" and "no corpus was supplied at all"
reach the dispatcher as the same rc 0 / 0 items. That file is line 71 of
`REQUIRED_AUTHORITY_PATHS` in `tools/ci/protected_landing_transition.py`;
`build_receipt` refuses a candidate whose protected bytes match neither BASE's
`current` nor BASE's `next` tuple (*"protected tuple attempts a rollback or
unprepared move"*), and PREPARE explicitly refuses to change live protected
bytes. So the fix is reachable only through a base-authorised PREPARE →
ACTIVATE pair, and not from one candidate commit. Recorded here so the next
transition has the reason to hand.

## What this deliberately does not do

It does not publish anything to make the corpus non-empty, and it does not widen
the producer's population rule so that the doubled shape would count. Widening
would make the row green over a run tree whose own layout is the defect that
withdrew a cell. The population rule is right; the publish path is what should
refuse to produce a shape it cannot see.
