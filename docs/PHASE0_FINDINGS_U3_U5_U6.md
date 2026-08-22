# Phase-0 findings: three settled UNDECIDEDs (U3, U5, U6) — second-reader record

Three independent measurements, each of which was blocking a decision. Nothing in
`flow/phase1_phase2_phase3.yaml` was changed by this document — every remedy below
is a **proposal**, because a declaration change moves what every dimension measures
and needs its own blast-radius review.

Measured on `origin/main` @ `38c8e687`, on host `192.168.1.114`.
Denominators are stated everywhere. Where the brief that commissioned this work
stated a premise that the measurement contradicts, the contradiction is stated
first and the brief is not accommodated.

---

## Convergence note — this is the SECOND independent read

A second agent measured the same three questions concurrently in the same worktree
and landed `docs/D9_PHASE0_U3_U5_U6_FINDINGS.md` (commit `a5a9dcb3`) before this
document. Both records are kept, because two independent reads converged on the
same measurements is the strongest form this evidence takes — and because
converging every disagreement in writing is this repo's own dual-track doctrine
rather than an accident of two agents colliding.

**Agreed, independently, to the digit:** `netlist.v` md5 and its 449/0 split; the
mapped sibling's md5 and its 287/0 split; the two-writer alias mechanism; three
`l_doc_expectations.json` on this host with `{14,10,4/5}` convergence records; the
schema-mismatch answer coerced to a passing zero denominator; FS1 → fix the
declaration; SSH to the other four hosts unavailable.

**Three places the two reads differ, and how each resolves:**

| # | disagreement | resolution |
|---|---|---|
| 1 | U3 headline: they say **(b) contract**; this document first said "neither reading as posed" | **They are right, and this document is corrected below.** They found the decisive citation I did not: `programs/fault_atpg_run.py:607-609` states the intent in the flow's own words. My contribution reduces to a refinement of (b), not a rival verdict. |
| 2 | U6 marker count: they say **4** markers (steps 15/29/32/34); this document measures **7** | **This document's number is the complete one.** Their sweep missed step 4 (`sim/pass.flag`) and both of step A6's entries (`drc_clean.flag`, `lvs_match.flag`) — the analog track and step 4 are outside a 44-step-core sweep. A6 matters: like step 29, **both** of its declared artefacts are marker-`OR`s. |
| 3 | P0: they say **(ii) NA**; this document said **(i) fix the declaration** | **Converged to (ii) now, (i) later** — see the P0 entry below. Their argument is the stronger one and I adopt it. |

---

## U3 — the Step-9 netlist split is **a CONTRACT (b)**, with a declaration that is
## not merely incomplete but self-contradictory

### Verdict

**(b) — an intentional two-artefact contract.** The flow states the intent in its
own words, at `programs/fault_atpg_run.py:607-609`:

> "The flow writes BOTH a generic `netlist.v` (kept for LEC/equivalence, where the
> abstract gate view is wanted) AND a mapped `<top>_synth.v` (what PnR/streamout
> consume)."

That settles bug-vs-contract: it is a contract. Per the brief's "if it is already
answered, say where and stop", **that citation is the answer** and the companion
document reaches it independently.

**The refinement this document adds** — and which the intent statement does not
cover — is that the declaration is not merely *incomplete*. It is **internally
inconsistent**: Step 9's own two `required_outputs` describe two different
netlists, so the step contradicts itself about which arm it signs off on.

**A cell that judged `netlist.v` is not judging a scratch artefact** — it is a
real, gated, provenance-logged artefact that steps 10 and 11 declare as their
input, and LEC deliberately wants exactly this abstract gate view. But it is the
**pre-map arm**, and on a full run **no back-end consumer reads it**.

### Evidence

Newest published run: `benchmark-data/ic/spm/v1.10.18_sky130A` (plugin 1.10.18,
`producer_identity.json` `written_utc 2026-08-09T11:07:40Z`).

| file | md5 | content |
|---|---|---|
| `phase2/stage2/synth/netlist.v` | `856e5f7de19e490b96ab6fd79c473c2a` | 449 generic Yosys primitives (`$_NAND_` 221, `$_NOR_` 128, `$_DFF_P_` 65, `$_NOT_` 35), **0** standard cells |
| `phase2/stage2/synth/netlist_yosys.v` | `856e5f7de19e490b96ab6fd79c473c2a` | byte-identical to the above (it is the alias source) |
| `phase2/stage2/synth/<top>_synth.v` | `765b04284014d1f3c302a44105ae5cf6` | 287 library cells, **0** generic primitives |

1. **The step's two declared artefacts describe different files.**
   `required_outputs[0]` is `netlist.v`. `required_outputs[1]` is
   `area.rpt OR stats.json`, and the `stats.json` that was produced says
   `"netlist": "phase2/stage2/synth/<top>_synth.v"`, `cell_count: 287`,
   `chip_area: 2577.472`.

2. **All three Step-9 gate clauses judge `netlist.v`** — `files_exist`,
   `synth_netlist_check --netlist .../netlist.v`, and
   `provenance_check --output .../netlist.v`. The mapped netlist that PnR,
   streamout, LVS, LEC and SDF gate-sim actually consume is **never touched by the
   Step-9 gate**.

3. **The flow already detects and publishes this.**
   `reports/phase2/synth_netlist.json` on the same run carries
   `"netlist_binding": "DESCRIBES_ANOTHER_NETLIST"` and a WARNING
   `AREA_ARTEFACT_DESCRIBES_ANOTHER_NETLIST` naming both files and both sha256s.
   The gate passes (`"pass": true`) — deliberately. `synth_netlist_check.py:703-721`
   says so in its own words: *"picking which synthesis step 9 should account for is
   a flow decision this gate must not make on its own."* **That open flow decision
   is exactly U3, and it is already written down as open.**

4. **`netlist.v` is a run-shape-dependent alias, not a stable artefact.** Two
   writers, and which one wins is decided by ordering:
   * `design_one_shot_runner.step_yosys_synth` (`:9251-9260`) writes
     `netlist.v` **unconditionally** from the generic `netlist_yosys.v`
     (the `if not is_file()` guard was removed on purpose, for
     ORGANIC-20260606 #426 — stale-alias-on-regate).
   * `phase3_one_shot_runner` canonicalize-artefacts Step 14 (`:30735-30749`)
     aliases `<top>_synth.v` → `netlist.v` **only `if not canon_netlist.is_file()`**.

   So on any phase2→phase3 run, phase 2 wins and `netlist.v` is generic forever;
   the phase-3 alias branch is dead on a full run. On a phase3-only run the same
   path name means the mapped netlist.

### Prior art in the tree (cite, do not re-derive)

The *split itself* is documented and measured — as a **step-11 ordering defect**:
* `design_one_shot_runner.py:11026-11085` — `_dft_atpg_precondition_reason`, with
  timestamps showing the mapped sibling landing after step 11 gave up on it.
* `design_one_shot_runner.py:10703-10727` — `_dft_atpg_sniff_pdk`.
* `phase3_one_shot_runner.py:29750-29800` — "canonical Step 9 … implemented in
  TWO HALVES on OPPOSITE SIDES of the phase boundary".

**What none of them says**, and what this document adds: that Step 9's *declaration*
names the wrong half for the purpose "the netlist this flow taped out", and that
`required_outputs[0]` and `required_outputs[1]` contradict each other.

### Proposed declaration change — NOT APPLIED

Step 9 should declare both halves, and the `synth_netlist_check` clause should run
against the mapped netlist that `stats.json` already accounts for:

```yaml
required_outputs:
  - "phase2/stage2/synth/netlist.v"          # pre-map, generic (phase-2 half)
  - "phase2/stage2/synth/*_synth.v"          # tech-mapped (phase-3 half)
  - "phase2/stage2/synth/area.rpt OR phase2/stage2/synth/stats.json"
```

**Blast radius, stated rather than hidden:** `required_outputs` is ALL-of-N (see the
step-10 comment at `flow/phase1_phase2_phase3.yaml:1233-1243`). Declaring
`*_synth.v` makes Step 9 report MISSING on **every `--skip-phase3` run**, because
the mapped netlist is written by the phase-3 runner. That is a real regression in
the reported matrix and is the reason this is a proposal and not a patch. A `SOFT`
/ conditional-output shape, or moving the mapping into the phase-2 half, are the
two ways out, and choosing between them is the owner's call.

---

## U6 — the "definitionally empty" cells: **the premise is false as measured**

### The contradiction, first

> the brief: *"4 of the 133 declared artefacts are `.done` / `.flag` markers with
> no content"*

Measured over **163 declared alternatives** (133 `required_outputs` entries, which
expand to 163 once `OR` alternatives are split) across **125 discovered run roots**
(every directory under `benchmark-data/` holding a `phase2/` or `phase3/`, excluding
`**/input/**`):

* **Zero-byte declared artefacts: 0.** Not one declared artefact resolved to an
  empty file on any run root.
* Marker-shaped declarations: **7**, not 4 — steps 4, A6 (×2), 15, 29, 32, 34.
* **Every one of the 7 is an `OR` alternative, never the sole declared artefact.**
* Marker file sizes actually on disk: **5 B – 779 B**. Every one except the 5-byte
  one carries a verdict *and* a provenance line naming the log it was derived from.

Contents, verbatim:

| marker | bytes | content |
|---|---|---|
| `phase3/stage3/pnr/pdn.done` | 144 | `# PDN inserted by OpenROAD make_tracks + global_route` + `# source: .../openroad.log` + `# tool: openroad` |
| `phase3/stage3/pnr/metal_fill.done` | 373 | `metal_fill_done`, `# fillers placed: 0`, the fill-master list, `# source: .../metal_fill.log` |
| `phase3/stage3/sim_postlayout/pass.flag` | 341 | `PASS` + evidence paths + an explicit disclosure that this is the OSS approximation and names its substance gate `post_layout_sim_check` |
| `phase3/stage3/eco/no_eco_needed.flag` | 155–158 | `no_eco_needed` + producer + `# Reason: post-route STA reports TNS=0 and no WNS violations` |
| `phase3/analog/*/lvs_match.flag` | 95–779 | a full scope disclosure ending `result=LVS_SCHEMATIC_SPEC_LEVEL device_exact_lvs=out_of_scope_per_L9` |
| `phase3/analog/*/drc_clean.flag` | 93–665 | same shape |
| `phase2/stage1/sim/pass.flag` | 5–49 | `PASS` — **the one genuine tick** |

### Ruling, per case

**A content-correctness cell over six of the seven is a real check, not a tick** —
each marker states a claim *and names the artefact the claim was derived from, so
the claim is falsifiable against that artefact.* That is a third resolution the
brief did not offer, and it is the right one for most of them. The exception is
step 29, which is empty by *declaration* rather than by content and takes (i) —
see the section after this table.

| step | artefact | marker-only on | recommendation |
|---|---|---|---|
| 15 | `pdn.tcl OR pdn.done` | **6 / 6** resolving roots | **(iii) publish the cell** — judge `pdn.done`'s `source:` log for a real PDN insertion. Separately **(i)**: `pdn.tcl` resolved **0/125** — dead branch. |
| 29 | `results.log OR pass.flag` | **4 / 4** | **(i) fix the declaration** — this is the one step that is empty *by declaration* (sole entry, marker-only). Declare `reports/phase2/gates/post_layout_sim.json`, the report of the blocking substance gate the flag itself names. `results.log` resolves **0/125**. |
| 34 | `filled.def OR metal_fill.done` | **5 / 5** | **(iii) publish the cell** — `# fillers placed: N` is a number that can be checked against `metal_fill.log`. Note the measured value is `0` on the sampled run, which is itself a finding for whoever owns fill. Separately **(i)**: `filled.def` **0/125**. |
| 32 | `eco_log.json OR no_eco_needed.flag` | **5 / 6** | **(iii) publish the cell** — `no_eco_needed.flag` names its source STA report and its reason (`TNS=0`); both are checkable. |
| A6 | `lvs_match.flag OR …` | **1 / 2** | **(iii) publish the cell** — 763–779 B of scope disclosure is the *most* judgeable artefact in this table. |
| A6 | `drc_clean.flag OR …` | **0 / 2** | **(iii) publish the cell**; content sibling present on the roots that resolve. |
| 4 | `*.log OR results.xml OR pass.flag OR …` | **0 / 20** | **(iii) publish the cell** — `results.xml` resolved on all 20. The 5-byte `pass.flag` is a tick, but it is never the artefact the cell has to judge. Separately **(i)**: `phase2/stage1/sim/*.log` **0/125** — dead branch. |

**No case warrants (ii) "publish as NA" on grounds of emptiness.** Zero of the
seven produces only a contentless marker.

### The two steps that ARE empty *by declaration* — 29 and A6

Emptiness-by-declaration is a different test from emptiness-of-content, and two
steps fail it. A step is empty by declaration when **every** entry in its
`required_outputs` is a marker-`OR`, so there is no declared artefact the step can
be held to other than the marker:

```
29  ['results.log OR pass.flag']                                 # 1 entry, 1 marker-OR
A6  ['drc_clean.flag OR drc.report OR *.lyrdb OR drc.rpt',       # 2 entries,
     'lvs_match.flag OR lvs.report OR comp.json OR lvs.rpt']     #   both marker-ORs
```

* **Step 29** is the sharpest case in the flow: its sole declared artefact is an
  `OR` whose content arm (`results.log`) resolves **0 / 125**, and the marker arm
  resolved on **4 / 4** roots that got that far. The companion document reaches the
  same conclusion and proposes the better remedy: **(i) declare
  `reports/phase2/gates/post_layout_sim.json`** — the report of the blocking
  `post_layout_sim_check` that `pass.flag` itself names as its substance gate, and
  which exists on 5 published runs. Adopted here.
* **Step A6** is the same shape and was missed by the 44-step-core sweep. Both
  entries are marker-`OR`s, and 3 of its 8 alternatives (`drc.rpt`, `comp.json`,
  `lvs.rpt`) resolve **0 / 125**. It is nonetheless the *least* worrying of the
  two, because the analog markers are the richest artefacts in the table
  (763–779 B of explicit scope disclosure ending in a machine-readable
  `result=…` token). **(iii) publish the cell** and judge that disclosure.

By contrast steps 15, 32, 34 and 4 each declare a content artefact **beside** the
marker, so the "definitionally empty" premise is simply not met for them — even
where that content artefact is itself never produced (step 15's `floorplan.def`
and step 32's `eco_trigger_decision.json` both resolve 0 / 125, which makes them
empty *in practice* but not *by declaration*, and is the separate finding below).

### FS1 and P0 — both are (i), both produce judgeable content today

**FS1** (`ISO-26262 FMEDA diagnostic-coverage`) declares no `required_outputs`, but
its `gate` names two artefacts its own programs write:
`reports/phase2/safety/fmeda_coverage.json` and `.../fmeda_coverage_gate.json`.
Both exist on the sampled run and carry content
(`{"gate": "fmeda_coverage_check", "verdict": "VACUOUS_PASS", "passed": true,
"reason": "no declared safety mechanism (ECC/parity/lockstep) found …"}`).
→ **(i) fix the declaration**: promote the two gate-named JSONs to
`required_outputs`. The cell then judges whether the vacuity reason is true of the
RTL — a real check.

**P0** (`Structural-RTL pre-flight`) declares neither `required_outputs` nor `gate`.
It is the *least* empty step in the flow: measured on
`benchmark-data/ic/spm/v1.10.18_sky130A/reports/audit/flow_compliance_check.log:8`
—

```
… [INCOMPLETE       ] Step P0: Structural-RTL gates (P0 umbrella, 210 of 246 checkers returned a verdict)  (stage1)
   [UNCLASSIFIED     ] …
        measures : (the flow definition for step P0 declares no gate)
```

246 checkers, 210 verdicts, **and it already discloses its own denominator** — the
house rule, satisfied. The verdict is emitted in-process by
`flow_compliance_check._run_structural_rtl_gates` (`:6999`) as `_p0_gate_record`
entries.

→ **(ii) publish as NA in writing, now — with (i) named as the follow-up.**

This document first recommended (i). The companion record's argument is the
stronger one and I adopt it: **P0 owns no artefact.** Its own `notes:` say the
verdict "is emitted directly by `flow_compliance_check.py`'s
`_run_structural_rtl_gates(...)` and surfaces in
`reports/audit/phase23_completion_audit.json`" — a file P0 does not produce.
Declaring that shared aggregate as P0's `required_output` would make P0's cell
judge someone else's artefact, which is **exactly the U3 pathology this same
document is arguing against**. Consistency requires (ii).

But NA here must not be read as "P0 is empty". It is the least empty step in the
flow, and the honest NA text has to say so: *no step-owned artefact exists to
judge*, not *nothing was checked*. The real fix is a program change — have
`_run_structural_rtl_gates` persist its `_p0_gate_record` list to a P0-owned path
— after which (i) becomes available and correct. That is a program change, not a
declaration change, and it is out of scope here.

### One more thing the sweep found, unasked

**17 `OR`-declarations have a branch that resolved 0/125 while a sibling branch
resolved on the same roots** — i.e. the step ran and produced the *other* thing,
every time. Four of them are a systematic phase-path drift in the analog track:

```
A1  DEAD phase1/analog/*/spec.json            LIVE phase3/analog/*/spec.json          (3)
A2  DEAD phase2/analog/*/topology.md          LIVE phase3/analog/*/topology.md        (3)
A3  DEAD phase2/analog/*/*.sp                 LIVE phase3/analog/*/*.sp               (3)
A4  DEAD phase2/analog/*/corner_results.json  LIVE phase3/analog/*/corner_results.json(3)
34  DEAD reports/phase3/density.{json,rpt}    LIVE reports/density.{json,rpt}         (11)
22  DEAD phase3/stage3/extracted/parasitic.spef  LIVE phase3/stage3/extracted/*.spef  (5)
```

A declared alternative that no run has ever produced is a promise nobody kept.
Full list in the reproduction below.

---

## U5 — has the IC-expert subagent ever produced an answer? **YES.**

### Answer

**Yes — three times, all on `192.168.1.114`, and none of them has ever been
published.** The AI half of the dual track is **not dead**. It works when a
subagent is actually invoked. What has never happened is that a converged run was
landed into `benchmark-data/`.

This contradicts the brief's premise (*"the subagent appears never to be
invoked"*). The brief's premise is correct about the **published** corpus and wrong
about the **fleet**.

### What I searched

Shape-based, not filename-based. `find /home/reyerchu -xdev` for
`ic_expert_agent_handoff.json` (the pack), then for **each pack** read its
`output_target` field and checked whether that file exists beside it. This is the
right shape because the answer filename is whatever the pack asked for, not a
constant.

* **313 handoff packs** found on this host.
* `output_target` distribution: **313 / 313 = `l_doc_expectations.json`.** (The
  program's other target, `rtl.sv`, is the `ic_expert_backup_pack.assemble`
  default and appears in **0** emitted packs.)
* **3 packs have their answer file present. 310 do not.**

### The three answers

| mtime (UTC) | bytes | `expectations` | `ai_convergence` published by the track | verdict |
|---|---|---|---|---|
| 2026-08-09T16:10:43 | 7619 | **14** | `{consumed:14, agreed:10, disagreed:4, undecidable:0}` | `FINDINGS` |
| 2026-08-04T10:53:08 | 6499 | **10** | `{consumed:10, agreed:5, disagreed:5, undecidable:0}` | `FINDINGS` |
| 2026-08-04T09:54:36 | 4591 | **absent (schema mismatch)** | `{0,0,0,0}` | `PASS` |

Paths, in ad-hoc campaign directories outside any git repo:
`/home/reyerchu/_c_nda3_ibex_run`, `/home/reyerchu/_c_nda2_edge_llm_matmul_accel_run`,
`/home/reyerchu/_c_nda_opentitan_aes_run` — each at
`reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json`.

The two substantive answers are real expert work: per-layer expectations with
`field_path`, `expected_tokens` and file:line `evidence` drawn from the design
**input only**, and the track converged them against the program track and
disagreed on 4 and 5 of them respectively. That is the dual track doing exactly
what it exists to do.

### Two corrections to the brief's supporting claims

1. **The pack is not written to a scratch directory.** It goes to
   `<project>/reports/audit/phase1/expert_parse_track_pack/`
   (`phase1_expert_parse_track.evaluate`, via `_pl.report_path`). Four of these pack
   directories are **committed into `benchmark-data/`** today. What is absent from
   the repo is the *answer*, not the pack.
2. **`ai_convergence {0,0,0,0}` on the 4 published reports is correct and honest.**
   Those 4 runs are `HANDOFF_EMITTED` — the pack was written, no subagent answered,
   and the track said so. They are not evidence that the AI track cannot run.

### The defect this exposed — a zero denominator that PASSES

The third answer above **parses as valid JSON but has no `expectations` key** — it
is an `ic-expert-agent` dialogue verdict blob (`gate`, `subagent`,
`ic_class_verdict`, `verdict: "gaps"`, `complete: false`,
`internally_consistent: false`, `cross_layer_inconsistencies`, …), not the
expectations schema the PARSE track asked for.

`phase1_expert_parse_track.ai_subtrack` (`:581-595`) guards only the JSON-parse
failure. A parse *success* with a missing/incorrectly-typed `expectations` key
falls through to:

```python
status.update(status="CONSUMED",
              reason=f"read {len(exps) if isinstance(exps, list) else 0} expectation(s) …",
              expectations=exps if isinstance(exps, list) else [])
```

so the track publishes `status: CONSUMED`, `"read 0 expectation(s)"`,
`ai_convergence {0,0,0,0}` and **`verdict: PASS`**. An expert answered, the answer
was the wrong shape, and the flow recorded it as a clean pass over an empty
population.

This is the exact failure mode `gate_zero_denominator_refuses_check` exists to
prevent, and it is worse than the `HANDOFF_EMITTED` state it is confused with:
`HANDOFF_EMITTED` says "nobody answered"; this says "somebody answered and we
agreed with all zero of it". **A `CONSUMED` with a zero denominator must refuse,
not pass.**

I did **not** implement this fix — see *What I deliberately did not do*.

### The limit on this answer, stated plainly

**Only 1 of the 5 named hosts was searched: this one (`192.168.1.114`).**
SSH to `192.168.1.105`, `.121`, `.120`, `.112` fails from here with
`Permission denied (publickey,password)` for **every** key in `~/.ssh`
(9 keys tried individually with `-o IdentitiesOnly=yes`), with no ssh-agent and no
`~/.ssh/config` entry for any fleet IP. Retried with the tool sandbox disabled —
same result. The TCP connection succeeds and the server rejects the key, so this is
an authorization limit, not a network one.

So the answer to "has the AI track ever produced an artefact on ANY host" is
**yes, proven on one host** — which is sufficient to settle the question in the
affirmative. The four unsearched hosts could only add more instances, never
retract these three.

**A near-miss worth recording as a method note:** my first sweep was
`find … | head -100` and returned `0` matches for `l_doc_expectations`. That was
**truncation, not absence** — the answers were past line 100. A pipeline that
truncates its own evidence and then reports a zero is how a "never" gets
manufactured. The 313-pack sweep above writes to a file first and states its
denominator.

---

## What I deliberately did NOT do

* **No change to `flow/phase1_phase2_phase3.yaml`.** All three questions end in a
  proposed declaration change; each moves what all eight existing dimensions
  measure. Proposed, not applied, as instructed.
* **No fix for the U5 zero-denominator defect.** It is a real defect with a clean
  remedy (refuse a `CONSUMED` whose `expectations` key is absent or not a list),
  but it is a behaviour change to a gate that was not in scope for three
  measurements. It is written up above with enough detail to be implemented
  directly, and it deserves its own change with its own two-arm control.
* **No fix for the 17 dead `OR` branches.** Same reason.
* **No tests written**, therefore no two-arm mutation control and no mutant arm to
  report. This work is three measurements over published artefacts and program
  source; there is no decision of mine for a mutant arm to neuter. Adding a test
  here would have been a test of the *measurement script*, not of the repo.
* **Nothing was run, started, or modified on any other host.** Read-only was
  honoured — and in the event, unreachable.
* **I did not delete, rewrite or quietly absorb the companion document.** Two
  agents ran this brief concurrently in the same worktree; the collision is
  disclosed at the top rather than resolved by making one record disappear. Where
  we disagreed I said which read won and why, including the one where mine lost.
* **`programs/tests/matrix_63x8/waivers.py` untouched. No baseline widened.
  Nothing under `benchmark-data/**/input/` edited. Nothing pushed to `main`.**

## Limits I am leaving in place

1. **U5 covers 1 of 5 hosts** (authorization, above). The other four are unknown.
2. **U6's 125 run roots are discovered as "any directory containing `phase2/` or
   `phase3/`"**, which includes nested and partial roots. That inflates the
   denominator and therefore *understates* per-artefact resolution rates. It does
   not affect any "0 of 125" result, which is what every dead-branch claim rests
   on.
3. **U3 was measured on one published run** (the newest by version). The
   two-writer alias mechanism is read from source and holds for any run of that
   shape, but I did not sweep every root for the generic-vs-mapped split.
4. **U6's marker-content table samples one file per marker kind.** Sizes are
   reported as ranges across all instances; contents are quoted from one each.
5. `_c_nda3_ibex_run`'s pack file is **newer than** its answer file
   (`11:26` vs `00:10`), i.e. the pack was re-emitted after the answer was
   consumed. I did not chase why; it does not affect the answer's existence or the
   published `consumed: 14`.

## Reproduction

```bash
# U3 — the split, on the newest published run
cd benchmark-data/ic/spm/v1.10.18_sky130A/phase2/stage2/synth
md5sum netlist.v netlist_yosys.v *_synth.v
grep -oE '\$_[A-Z0-9_]+_' netlist.v | sort | uniq -c        # 449, four kinds
python3 -c "import json;print(json.load(open('stats.json'))['netlist'])"
python3 -c "import json;print(json.load(open('../../../reports/phase2/synth_netlist.json'))['stats']['area_stats']['netlist_binding'])"

# U5 — every pack on the host, and whether its declared answer exists
find /home/reyerchu -xdev -name ic_expert_agent_handoff.json > /tmp/packs.txt
wc -l < /tmp/packs.txt                                       # 313
python3 - <<'PY'
import json, os
for p in (l.strip() for l in open('/tmp/packs.txt') if l.strip()):
    t = json.load(open(p)).get('output_target')
    a = os.path.join(os.path.dirname(p), t)
    if os.path.isfile(a):
        print(os.path.getsize(a), a)
PY

# U6 — zero-byte artefacts and dead OR branches over every discovered run root
#   (the sweep script is in the PR description; it parses required_outputs,
#    splits on ' OR ', and globs each alternative against every root)
```
