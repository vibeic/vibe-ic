# D9 Phase 0 — three UNDECIDEDs, settled by measurement

Scope: three questions (U3, U5, U6) that each block a downstream decision.
This document is a **measurement record**, not a change. No flow YAML, no
program, and no gate was modified. Every recommendation below is a
*proposal* for an owner ruling.

Measured against `origin/main` @ `38c8e687`, worktree `/home/reyerchu/_d9_d9d`,
on host `8HD-8` (`192.168.1.114`).

---

## U3 — the Step-9 netlist split is a CONTRACT, not a declaration bug

**Verdict: (b), an intentional two-artefact contract — with an incomplete
declaration that the repo already documents as having caused measured defects.**

This question was **already answered in the tree**. Per the brief's
"if it is already answered, say where and stop", the two load-bearing citations
are:

- `programs/fault_atpg_run.py:607-609` —
  > "The flow writes BOTH a generic `netlist.v` (kept for LEC/equivalence, where
  > the abstract gate view is wanted) AND a mapped `<top>_synth.v` (what
  > PnR/streamout consume)."
- `programs/phase3_one_shot_runner.py:29755-29764` — canonical Step 9 is
  implemented in **two halves on opposite sides of the phase boundary**:
  - phase 2 `design_one_shot_runner.step_yosys_synth` → `netlist.v`,
    "technology-GENERIC **on purpose**"
  - phase 3 `phase3_one_shot_runner.step_synth` → `<top>_synth.v`, the
    technology mapping, written into the *same* directory

### Corroborating measurement (newest published run of the single-module design)

`benchmark-data/ic/spm/v1.10.18_sky130A/phase2/stage2/synth/`

| file | md5 | cell content |
|---|---|---|
| `netlist.v` | `856e5f7de19e490b96ab6fd79c473c2a` | **449 generic Yosys primitives, 0 standard cells** |
| `netlist_yosys.v` | `856e5f7de19e490b96ab6fd79c473c2a` | byte-identical to `netlist.v` |
| `spm_synth.v` | `765b04284014d1f3c302a44105ae5cf6` | **287 standard cells, 0 generic primitives** |

Generic-primitive histogram of `netlist.v` — 221 `$_NAND_`, 128 `$_NOR_`,
65 `$_DFF_P_`, 35 `$_NOT_` = **449**, and `grep -c sky130 netlist.v` = **0**.
This reproduces the brief's figure exactly.

**Why it is generic by construction, not by accident.** The phase-2 recipe
(`design_one_shot_runner.py:9108-9114`) is
`techmap; opt; dffunmap; abc -g cmos2` with **no Liberty loaded**. `dffunmap`
produces `$_DFF_*_` and `abc -g cmos2` produces the `$_NAND_`/`$_NOR_`/`$_NOT_`
AIG-CMOS vocabulary. The observed 449 is precisely that vocabulary. There is no
path by which this recipe could emit a standard cell.

**Why `netlist.v` stays generic on a full run.** Phase 2 writes
`netlist.v` as an **unconditional** copy of `netlist_yosys.v`
(`design_one_shot_runner.py:9245-9262`, made unconditional by ORGANIC #426 so a
close-loop re-gate cannot judge a stale ghost). Phase 3 would alias the *mapped*
netlist to `netlist.v`, but only `if not canon_netlist.is_file()`
(`phase3_one_shot_runner.py:30734`). On a phase2-then-phase3 run the file is
never absent, so the generic copy survives. The two behaviours are individually
correct and jointly produce the split.

### What each consumer actually reads

| consumer | reads | behaviour |
|---|---|---|
| Step 9 gate (`files_exist`, `synth_netlist_check`, `provenance_check`) | `netlist.v` | the declared artefact |
| Step 14 pre-PnR handoff gate | `netlist.v` | `yosys_script_template_check.py:201` |
| LEC / equivalence | `netlist.v` | the abstract gate view is *wanted* here |
| stats / area | **`<top>_synth.v`** | `stats.json` records `"netlist": "phase2/stage2/synth/spm_synth.v"` |
| scan / ATPG | **`<top>_synth.v`** | `fault_atpg_run.resolve_mapped_netlist` detects `is_generic_unmapped` and switches; `iverilog` cannot elaborate `$_NAND_`, so the generic file yields **zero fault sites** |
| PnR / streamout | **`<top>_synth.v`** first | resolver order at `phase3_one_shot_runner.py:1482` |

So the consumers are not confused — each deliberately binds the arm it needs.
Both artefacts are legitimate. **A D9 cell that judged `netlist.v` would be
judging a real artefact, not scratch** — but it would be judging the *pre-map*
one, and must not be read as a statement about the mapped netlist that PnR,
area and ATPG actually consume.

### The residual defect, which is real and already documented

The declaration is **incomplete**, and the repo names the cost itself:

- `synth_netlist_check.py:704-720` already emits
  `AREA_ARTEFACT_DESCRIBES_ANOTHER_NETLIST` as a **WARNING**, with the explicit
  note that "picking which synthesis step 9 should account for is a flow
  decision this gate must not make on its own."
- `phase3_one_shot_runner.py:29766-29788` records a measured blast radius from
  the same split: canonical Step 11 asked for the mapped netlist 9.391 s before
  it existed, disclosed a **false capability gap**, and dragged Step 11 /
  DT1 / DT2 / DT3 plus ~20 dependent steps into MISSING/SKIPPED.

**Proposed declaration change (NOT applied — flow YAML untouched in this
branch).** Step 9 should declare **both** arms and name which is which, e.g.
a pre-map arm (`phase2/stage2/synth/netlist.v`) and a mapped arm
(`phase2/stage2/synth/<top>_synth.v`), so that a dimension can state which one
it measured. This moves what all eight existing dimensions measure and needs
its own blast-radius review — it is proposed here, not made.

---

## U5 — YES. The AI track has produced an artefact, and has been consumed, more than once

**Answer: YES — but on 3 of 313 reports (0.96%), never on any *published* run,
and one of the three was silently discarded.**

This **contradicts the brief's premise** in three separate ways. All three
corrections are stated with the measurement.

### Correction 1 — the pack is NOT written to a scratch directory

`phase1_expert_parse_track.evaluate()` sets
`out_dir = report_path(project,"phase1/expert_parse_track").parent / "expert_parse_track_pack"`
— inside the project's own reports tree. It is published: every one of the four
`benchmark-data` runs carries
`reports/audit/phase1/expert_parse_track_pack/ic_expert_agent_handoff.json`
(+ `ic_expert_db.md`, `lessons.md`). The pack is emitted and shipped correctly.
The absolute path recorded in `pack_dir` is simply the run dir of the machine
that ran it.

### Correction 2 — the subagent HAS answered

Census of **every** `expert_parse_track.json` on this host, excluding pytest
temp dirs — **313 reports**:

| verdict / AI status | count |
|---|---|
| `VACUOUS_PASS` / `HANDOFF_EMITTED` | 310 |
| `FINDINGS` / `CONSUMED` | 2 |
| `PASS` / `CONSUMED` | 1 |

Three real (non-pytest) `l_doc_expectations.json` exist on disk:

| run dir | date | expectations | `ai_convergence` | verdict |
|---|---|---|---|---|
| `_c_nda3_ibex_run` | 2026-08-10 | 14 | `{consumed:14, agreed:10, disagreed:4, undecidable:0}` | `FINDINGS` |
| `_c_nda2_edge_llm_matmul_accel_run` | 2026-08-04 | 10 | `{consumed:10, agreed:5, disagreed:5, undecidable:0}` | `FINDINGS` |
| `_c_nda_opentitan_aes_run` | 2026-08-04 | 0 (see below) | `{consumed:0, ...}` | `PASS` |

The first answer is authored
`"vibe-ic:ic-expert-agent (human-directed IC expert agent, run c_nda3_ibex)"`,
carries `input_only: true` and a `read_scope` limited to design input, and
produced four real disagreements the program track missed
(`EXP_TOP_MODULE`, `EXP_PIPELINE_2_STAGE`, `EXP_ISA_RV32IMC`, `EXP_MULT_3CYCLE`).

**So the dual track works end-to-end when a subagent is actually invoked.**
It is not invoked automatically because a program cannot spawn a subagent —
the track emits a handoff and consumes an answer only if a *later* invocation
finds one on disk. Nothing in the flow performs that second invocation, so the
default outcome is `HANDOFF_EMITTED` forever. That is the true shape of the gap:
**not "the AI track cannot run" but "nothing ever calls it".**

### Correction 3 — the worst case is not a missing answer, it is a discarded one

`_c_nda_opentitan_aes_run` is the important one. The subagent **did** answer,
substantively: `verdict: "gaps"`, `complete: false`,
`internally_consistent: false`, and two real cross-layer defects
(`L1-PIN-POLLUTION-791` — register/enum names collected as chip pins;
`RST-NI-ABSENT` — a required active-low reset port absent from L1 and L9).

But it wrote a **different schema**. Top-level keys:

```
['gate','subagent','ic_class_verdict','verdict','complete',
 'internally_consistent','canonical_port_set_from_input',
 'cross_layer_inconsistencies','what_is_correctly_captured',
 'auto_decided_defaults_applied']
```

There is no `expectations` key. The consumer
(`phase1_expert_parse_track.py:581-594`) does
`exps = data.get("expectations")` then
`expectations = exps if isinstance(exps, list) else []`, and reports
`status="CONSUMED", reason="read 0 expectation(s)"`.

Net result: **a real expert review that found two real design defects was
coerced to the empty list and published as `verdict=PASS`, `blocking=False`,
`0 findings`.** A zero denominator passed instead of refusing — the exact
failure mode this repo enforces against elsewhere
(`gate_zero_denominator_refuses_check`). This is filed as its own issue; it is
**not fixed in this branch**, because changing a gate verdict changes what a
dimension measures and carries the same blast radius as the U3 declaration
change.

### Search performed, and the limit on it

On this host (`192.168.1.114`), read-only:

- exact name `l_doc_expectations*` over `/home/reyerchu` and `/tmp` → 23 hits
  (3 real, 20 pytest fixtures)
- by shape: every `expert_parse_track.json` (313), every `*expectations*.json`,
  every recorded `pack_dir` from the published reports
- the four published `benchmark-data` expert-track reports

**LIMIT — 4 of the 5 named hosts were NOT searched.** From this host,
`192.168.1.105`, `.121`, `.120` and `.112` all have **port 22 OPEN** but reject
every available key: `Permission denied (publickey,password)` for
`~/.ssh/id_ed25519`, `id_ed25519_lts`, `id_ed25519_run`, with no ssh-agent
available. I did not attempt password auth and started nothing on any remote
host. So the honest scope of the "YES" is: **yes on 192.168.1.114**, which is
where all four published runs and the plugin checkout live. The other four
hosts remain unmeasured, and a "no" from them could not change the answer —
one positive is enough to settle the question.

---

## U6 — it is THREE definitionally-empty cells, not six

Measured from the flow YAML directly (`yaml.safe_load`, not grep):
**71 `id`-bearing nodes = 8 stage containers + 63 real steps**, carrying
**133 declared `required_outputs`**. Both figures reproduce the brief.

Of the 10 nodes with no `required_outputs`, **8 are stage containers**
(`stage1`, `stage2`, `stage3`, …) which are not cells at all. The real steps
with none are exactly **FS1 and P0**, as the brief says.

### The 4 marker artefacts — and why only one of them makes a cell empty

All four are the **second arm of an `X OR Y`**, and none is zero-byte
(144–373 bytes; each carries a verdict token and a provenance comment naming
its source artefact). The brief's "markers with no content" is not what is on
disk.

| step | required_outputs | marker present | content arm present |
|---|---|---|---|
| 15 Floorplan+PDN | `floorplan.def`; `pdn.tcl OR pdn.done` | `pdn.done` ×6 | `floorplan.def` **×0**; `pdn.tcl` ×0 |
| 29 Post-layout gate sim | `results.log OR pass.flag` **(only entry)** | `pass.flag` ×5 | `results.log` **×0** |
| 32 Post-route timing repair | `eco_log.json OR no_eco_needed.flag`; `eco_trigger_decision.json` | `no_eco_needed.flag` ×5 | `eco_log.json` ×1; `eco_trigger_decision.json` **×0** |
| 34 Metal fill | `filled.def OR metal_fill.done`; `density.json`; `density.rpt` | `metal_fill.done` ×5 | `density.json` **×11** |

Only **Step 29** is empty *by declaration* — its sole `required_outputs` entry
is the `OR` whose content arm is never produced. Steps 15, 32 and 34 each
declare a content artefact alongside the marker, so the premise "definitionally
empty" is **false for those three**.

(Separate observation, flagged not claimed: `floorplan.def` and
`eco_trigger_decision.json` appear **0 times** across the 8 published runs that
have a `phase3/stage3/pnr` directory. Those are declared required_outputs that
no published run satisfies. That is a different question from U6 and deserves
its own measurement.)

### Recommendation, one line per case

| # | case | recommendation | evidence |
|---|---|---|---|
| 1 | **FS1** — no `required_outputs` | **(i) fix the declaration.** Declare `reports/phase2/safety/fmeda_coverage.json` and `reports/phase2/safety/fmeda_coverage_gate.json`. | Its own `gate:` already names both; **15 such files exist across 8 published designs**, carrying judgeable content (`{applicable, verdict, reason, asil}`). The step produces judgeable output and the flow does not say so. |
| 2 | **P0** — no `required_outputs` | **(ii) publish as NA in writing.** | Its own `notes:` state it is a *synthetic* preflight whose verdict "is emitted directly by `flow_compliance_check._run_structural_rtl_gates(...)` and surfaces in `reports/audit/phase23_completion_audit.json` under the `gates:` array". It owns no artefact. Declaring the audit's file would make P0's cell judge a file P0 does not produce — the exact U3 pathology. The matrix should say NA. |
| 3 | **Step 29** — marker-only | **(i) fix the declaration.** Declare `reports/phase2/gates/post_layout_sim.json`. | The step already runs `post_layout_sim_check` as a **blocking** gate and that report exists in **5** published runs. `pass.flag` itself even names it as "Substance gate". The judgeable artefact exists; it is simply undeclared. |
| 4 | **Steps 15, 32, 34** | **no change — premise not met.** | Each declares a content artefact beside the marker. Not definitionally empty. |

Net: **2 declaration fixes proposed (FS1, Step 29), 1 NA ruling proposed (P0),
3 non-findings.** None applied — the flow YAML is untouched in this branch.

---

## What I deliberately did NOT do, and every limit left in place

- **No flow YAML change.** Every U3/U6 recommendation ends in a declaration
  change; each moves what all eight existing dimensions measure. Proposed only.
- **No fix to the U5 schema-coercion defect**, though it is the most serious
  thing found. Changing `phase1_expert_parse_track`'s verdict from PASS to a
  refusal is a gate-verdict change with the same blast radius; it belongs in
  its own PR with its own negative control. Filed as an issue instead.
- **No two-arm mutation control, and no mutant arm — because I wrote no test
  and changed no code.** The rules of evidence bind "every test you write"; I
  wrote none, so there is nothing whose bite could be demonstrated by
  neutering it. This document asserts no passing test. Every claim here is a
  file read, a parse, or a count, each with the path and figure shown so it can
  be re-run directly.
- **4 of 5 fleet hosts unmeasured** for U5 (SSH auth unavailable from here; see
  the U5 limit section). Read-only throughout; nothing was started or modified
  on any remote host.
- **U5's census counts reports, not runs.** 313 `expert_parse_track.json` files
  include re-runs and stale report trees; it is a denominator over report
  files on one host, not over distinct designs.
- **U3's netlist measurement is one published run** of a single-module design.
  The mechanism (recipe + unconditional copy + `if not is_file()` alias) is
  general and was read from source, but the 449/287 figures are that one run.
- **No waiver touched, no baseline widened, nothing under
  `benchmark-data/**/input/` edited, nothing pushed to main.**
