# Output layout — from the flow YAML to a published `benchmark-data/` cell

**Status:** current as of plugin **v1.10.4** (repo `main` @ `f0d10e383`).
**Scope:** where EDA-tool output actually lands during a run, what decides that,
how the `steps/<phase>/<stage>/<id>_<slug>/` mirror is built, and exactly what
changes when a run is published into `benchmark-data/ic/<IC>/v<version>_<PDK>/`.

Every number in this document was **re-measured** against the tree at the commit
above. Each section states the command that reproduces it. Nothing here is
copied forward from an earlier write-up.

There are **four** artefact layers, and they are commonly conflated:

| Layer | Lives at | Made of | Authority |
|---|---|---|---|
| 1. Canonical run tree | `<run>/phase{1,2,3}/`, `<run>/reports/` | real files written by the tools | **authoritative** — the inter-step contract |
| 2. `steps/` mirror | `<run>/steps/<phase>/<stage>/<id>_<slug>/` | **symlinks** + `outputs.json` | a derived **VIEW**; never read as evidence |
| 3. Write ledger | `<run>/reports/write_ledger.json` + per-step `written.json` | observation of what was written | independent **observation** |
| 4. Published cell | `benchmark-data/ic/<IC>/v<ver>_<PDK>/` | copied subtrees + **records** | the deliverable; contains **no symlinks** |

---

## 1. The flow YAML — what is declared

`flow/phase1_phase2_phase3.yaml` (4431 lines) is the single source of truth for
the step list. Top-level keys: `version`, `flow_name`, `total_steps`,
`analog_steps`, `stages`, `steps`, `final_gate`.

### 1.1 The 44-vs-63 question, settled

Both numbers are correct and they count different things:

```
$ python3 -c "import yaml;d=yaml.safe_load(open('flow/phase1_phase2_phase3.yaml'));\
print(d['total_steps'], d['analog_steps'], len(d['steps']))"
44 9 63
```

* **`total_steps: 44`** = the **numeric main-track** ids `1..44`. It is defined
  as *the max integer id*, and `programs/tests/test_all_steps_covers_flow.py::
  test_headline_step_count_matches_flow` pins `max(int_ids) == total_steps` and
  pins the `ALL_STEPS_*.md` headline to the same figure. Verified passing
  (`5 passed`).
* **63** = the number of **nodes** in `steps:` — every node the runner, the
  dashboard and the mirror iterate. It is `44` numeric **+ 19 non-numeric**:
  `D1` (Phase-1 doc extraction), `P0` (structural pre-flight), `FS1` (ISO-26262
  FMEDA), `DT1`/`DT2`/`DT3` (DFT sub-steps), `A1..A9` (analog), `M1..M4`
  (mixed-signal).
* **No YAML field declares 63.** It is only ever obtained by `len(steps)`. That
  is why the two figures circulate side by side.

### 1.2 Actual stage membership (measured, not from `stages[]`)

```
stage_phase1          1 step   D1
stage1                7 steps  1,2,3,4,5,6,P0
stage2               12 steps  7,8,9,10,11,FS1,DT1,12,13,14,DT2,DT3
stage_analog          9 steps  A1..A9
stage3               18 steps  15..32
stage_mixed_signal    4 steps  M1..M4
stage4                7 steps  33,34,35,36,37,38,39
stage5_manufacturing  5 steps  40,41,42,43,44
                     ---
                     63
```

### 1.3 `required_outputs` — the grammar that decides directories

Each step carries a `required_outputs:` list. Each entry is a **run-relative
glob**, optionally a set of alternatives joined by a literal ` OR `:

```yaml
- id: 34
  required_outputs:
    - phase3/stage3/pnr/filled.def OR phase3/stage3/pnr/metal_fill.done
    - reports/density.json OR reports/phase3/density.json
```

`flow_dashboard_data._resolve_spec()` splits on `\s+OR\s+`, globs each
alternative against the run root in order, and returns the **first** that
resolves. `present=True` if **any** alternative resolves. When none resolve the
entry is returned with `exists=False` and the **first literal alternative** as
the expected location.

Counts: **133** `required_outputs` entries across 63 steps (**163** once OR
alternatives are expanded). Two steps declare none — `P0` and `FS1`, both
umbrella/pre-flight nodes with no artefact of their own.

### 1.4 Declared output directories, by stage

| Stage | Dominant output directories (entry count) |
|---|---|
| `stage_phase1` | `phase1/generated_docs` (14) |
| `stage1` | `phase2/stage1/{sim,rtl,formal,fpga/output_files,sim_full_stack,sim_professional}`, `reports/phase{1,2}/…` |
| `stage2` | `phase2/stage2/{synth,dft,constraints}`, `reports/phase2/dft`, `reports/` root (2) |
| `stage_analog` | `phase3/analog` (16), `phase3/analog/hardmacro` (4), `phase2/analog` (3, legacy OR), `phase1/analog` (1, legacy OR) |
| `stage3` | `reports/phase3` (20), `phase3/stage3/{pnr,spice,eco,cts,extracted,sta,sim_postlayout}`, `sim_spice` (1) |
| `stage4` | `reports/phase3` (6), `phase3/stage4/foundry_handoff` (5), `phase3/stage4/gds` (1), `phase2/stage1/fpga/final` (1) |
| `stage_mixed_signal` | `reports/analog/mixed_signal` (6), `phase3/mixed_signal{,/cosim}` |
| `stage5_manufacturing` | `phase3/stage5_manufacturing` (8) |

Note `stage4` step 39 (FPGA final sign-off) writes under **`phase2/`** — see
`_path_layout.fpga_final_dir()`, which was deliberately unified onto
`phase2/stage1/fpga/final` because three paths previously competed and the
declared artefact was unproducible.

---

## 2. Where the tools actually write — `programs/_path_layout.py`

`_path_layout.py` (956 lines) is the **single source of truth for the project
directory tree**. Producers MUST call its helpers rather than hardcode strings.
The canonical tree:

```
<project>/
├── input/                     raw vendor docs / PDK / prompt
├── provenance.jsonl           tool invocation log
├── rig_topology.json
├── waivers.json
├── phase1/
│   ├── input_doc/             Path A — vendor docs verbatim
│   ├── input_prompt/          Path B — dialogue + fact graph
│   ├── generated_docs/        L1..L27 JSON — the universal handoff
│   ├── human_docs/            L*.md
│   └── *.json                 extraction_patterns / completeness / patches
├── phase2/
│   ├── stage1/ rtl/ sim/ sim_full_stack/ formal/ tb/ fpga/{output_files,final}/
│   └── stage2/ constraints/ synth/ dft/
├── phase3/
│   ├── stage3/ pnr/ cts/ extracted/ eco/ spice/ sta/ sim_postlayout/
│   ├── stage4/ gds/ foundry_handoff/
│   ├── stage5_manufacturing/
│   ├── analog/<block>/ , analog/hardmacro/<block>/
│   └── mixed_signal/{,cosim}/
├── reports/
│   ├── phase1/ phase2/ phase3/ audit/ orchestrator/
│   └── final_summary.md, chip_specific_summary.md    ← only 2 root files allowed
└── steps/                     the per-step VIEW (see §3)
```

### 2.1 What decides a path — three mechanisms, in this order

1. **A named accessor.** `rtl_dir()`, `pnr_dir()`, `cts_dir()`, `gds_dir()`,
   `analog_block_dir()`, … Each returns a fixed constant path. Example:
   `pnr_dir(p) -> p/"phase3/stage3/pnr"`. There is no per-step override
   mechanism and no per-PDK or per-IC branching anywhere in the module — the
   layout is **chip-AGNOSTIC by construction**.
2. **A content-addressed resolver**, where one concept legitimately has several
   homes. `resolve_tb_dir()` returns the first of seven candidate directories
   that actually *holds* a testbench, and returns `None` (≠ "default path
   missing") when none do. Introduced because two gates answered the same
   question from two independently incomplete candidate lists (#599).
3. **The reports auto-router.** `report_path(project, filename)` maps a bare
   report filename into its phase subfolder using `_REPORT_CATEGORY` (exact
   filename → phase), `_REPORT_SUBDIR_CATEGORY` (leading subdir → phase), a
   two-file root whitelist, and `reports/audit/` as the fallback for unknown
   names. E.g. `report_path(p,"drc_signoff.rpt") -> reports/phase3/drc_signoff.rpt`.

### 2.2 The two layout whitelists

```python
TOP_LEVEL_VALID_DIRS  = ("input","phase1","phase2","phase3","reports","steps")
TOP_LEVEL_VALID_FILES = ("provenance.jsonl","rig_topology.json","waivers.json")
REPORTS_VALID_SUBDIRS = ("phase1","phase2","phase3","audit","orchestrator")
REPORTS_VALID_ROOT_FILES = ("final_summary.md","chip_specific_summary.md")
```

Enforced by `top_level_outputs_in_canonical_check.py` and
`reports_subfolder_taxonomy_check.py`. **Both gates are recorded as UNWIRED** —
see `programs/gate_is_wired_baseline.json`, which lists each in both `unwired`
("no automatic verdict consults it") and `skill_only`. This matters for §6.

---

## 3. The `steps/` mirror — how it is built and what it contains

### 3.1 Who builds it

`_path_layout.emit_steps_view(project, programs_dir, runner=…)` is the shared
entry point, called once at finalize by **all six** orchestrators:

```
programs/vibe_ic_one_shot_runner.py:978      programs/phase3_one_shot_runner.py:38449
programs/design_one_shot_runner.py:13171     programs/phase23_one_shot_runner.py:207
programs/phase1_one_shot_runner.py:653,699   programs/analog_one_shot_runner.py:1306
```

It shells out to `step_output_collector.py` with a 300 s cap, then **verifies
the result itself** — it re-reads `steps/index.json` and counts folders rather
than trusting the child's exit code — and writes a status record to
`reports/audit/steps_view.json` with `status ∈ {OK, BUILD_FAILED, TIMEOUT,
COLLECTOR_MISSING}`. It never raises and never gates a run. The record exists so
that "no steps tree" is a written statement with a reason, not an unexplained
absence.

### 3.2 What the collector produces — **symlinks, still, today**

`step_output_collector.materialize()`:

* iterates `flow_dashboard_data.collect(project)` — the same data source the
  dashboard uses, so no step classification is invented here;
* folder = `"<phase>/<stage>/<safe_id>_<slug>"`, e.g.
  `phase3/stage3/21_routing_global_detailed`;
* for each declared output that **exists**, creates an **absolute symlink**
  (`link.symlink_to(src)`) named after the source basename, with a
  `<parentdir>__<name>` fallback on basename collision;
* writes `outputs.json` per step (`id/name/status/phase/stage/folder/outputs[]`,
  each output carrying `rel`, `abs`, `size`) and `steps/index.json` (the ordered
  list with `n_outputs`);
* is idempotent: stale symlinks and manifests are cleared, folders from a prior
  `index.json` that the current run no longer produces are pruned (with a
  path-traversal guard on the deletion loop, added after a hand-edited
  `index.json` carrying `../../x` deleted files outside the project).

**Symlinks are still current practice inside a run.** Measured on a live
converged run:

```
$ find /home/reyerchu/_car15_evidence/steps -type l | wc -l
83
```

What changed is only what gets **published** (§4).

### 3.3 The `<phase>` segment is a display lane, not the YAML stage's phase

`flow_dashboard_data._phase_key_for()` maps each step to one of six lanes
(`phase1/phase2/phase3/analog/mixed/manufacturing`) by first-match rules, which
produces two structures worth knowing about:

* one `stage` can split across two lanes — step 39 (stage4) is claimed by the
  phase2 rule for FPGA bring-up, so the tree holds **both**
  `steps/phase2/stage4/39_…` and `steps/phase3/stage4/33_…`;
* one lane can hold two stages — `P0` (stage1) is forced to phase1, so
  `steps/phase1/stage1/P0_…` sits beside `steps/phase1/stage_phase1/D1_…`.

Confirmed on a published cell: the 10 `<phase>/<stage>` pairs present are
`phase1/{stage1,stage_phase1}`, `phase2/{stage1,stage2,stage4}`,
`phase3/{stage3,stage4}`, `analog/stage_analog`, `mixed/stage_mixed_signal`,
`manufacturing/stage5_manufacturing`.

### 3.4 The write ledger — the *other* half

The mirror is built **entirely from `required_outputs`**. It is a restatement of
the declaration and cannot witness anything the declaration does not already
claim. `step_write_ledger.py` (1032 lines) records the complementary fact — what
the run **actually wrote** — via one post-hoc `os.walk` + **`lstat`** over the
run tree, and residuals observation against declaration:

* *written, never declared* → D7 candidate (`required_outputs` incomplete)
* *declared, never written* → D3 finding, attributed to the step
* *written with no witnessed tool* → D5 candidate

It deliberately **skips `steps/`** when walking (`_SKIP_DIRS`), so the
declaration cannot re-enter the observation. It never hashes file content, it
withholds every time-derived conclusion on a tree whose mtimes have been
flattened by a copy or `git checkout` (which is exactly what a published cell
is), and `emit()` never raises.

`emit()` writes **two** artefacts:

* **`reports/write_ledger.json`** — the primary, whole-run ledger. Placed under
  `reports/` **specifically so it survives publishing**, since the publisher does
  not copy `steps/`.
* **`steps/<folder>/written.json`** — a per-step **slice** of the same ledger
  (one row of `led["steps"]`), dropped next to the collector's `outputs.json`
  when that tree exists. Additive; the collector's own files are untouched.

---

## 4. Publishing — what changes between a run tree and a `benchmark-data/` cell

Driven by `programs/benchmark_evidence_publish.py` (1520 lines), validated by
`benchmark_evidence_structure_check.py`. The publisher **stages only** — it
never runs `git add/commit/push`.

### 4.1 Copied verbatim

```python
_COPY_SUBTREES = ("phase1", "phase2", Path("phase3")/"reports",
                  Path("phase3")/"analog", "reports")
_COPY_FILES    = ("provenance.jsonl",)
```

Everything else in the run is **not copied**. In particular
**`phase3/stage3/` (raw PnR + extraction working files) is not published**, nor
is `sim/`, nor `steps/` itself.

### 4.2 Layout artefacts routed by **size**, not by extension

`.gds/.def/.spef/.oas` under the 50,000,000-byte ceiling (`_SIZE_CEILING`, kept
in lockstep with `tracked_blob_size_guard` and `.gitignore` by
`size_policy_drift_check.py`) are **staged**; above it they are recorded but not
copied. `.gitignore` ignores `*.gds`/`*.def` repo-wide and negates them back for
`benchmark-data/ic/**`. Every layout artefact gets a line in
`LAYOUT_ROUTING.txt` (`STAGED | ROUTED_AWAY | NOT_PUBLISHED`) with its sha256,
emitted even when nothing was routed away.

### 4.3 Per-step evidence — published as a **RECORD**, never as the view

`publish_steps()` walks the run's `steps/` tree read-only
(`os.walk(followlinks=False)`, because a recursive glob over a symlink tree does
not terminate) and, per step folder, resolves each declared output **against the
run, by its run-relative path** — never via the collector's host-absolute `abs`
field. It emits:

| Artefact | Where | Content |
|---|---|---|
| `STEP_RECORD.json` | `steps/<phase>/<stage>/<id>_<slug>/` | id, name, status, phase, stage, folder, `declared_outputs[]` (rel, symlink, bytes, sha256, in_cell, decision), `records[]` |
| `STEP_INDEX.json` | `steps/` | ordered step list + `n_declared` / `n_in_cell` |
| `STEP_ROUTING.txt` | **cell root** | flat, greppable, one line per declared output; always emitted |

`decision ∈ IN_CELL | OUT_OF_PUBLISHED_SCOPE | ZERO_BYTE | DANGLING_IN_RUN |
ABSENT_IN_RUN`.

**No symlink is created in a cell and none is copied.** Measured on
`benchmark-data/ic/spm/v1.9.94_sky130A` and `v1.9.96_gf180mcuD`:

```
$ git ls-files -s benchmark-data/ic/spm/v1.9.94_sky130A \
      benchmark-data/ic/spm/v1.9.96_gf180mcuD | awk '$1=="120000"' | wc -l
0
```

### 4.4 `written.json` **is** published — as a verbatim record

This is the point most often gotten backwards. The publisher **replaces** the
two collector manifests and **copies everything else**:

```python
_COLLECTOR_MANIFESTS = frozenset({"outputs.json", "index.json"})   # replaced
_STEP_RECORD_EXTS    = (".json", ".txt", ".md", ".jsonl")          # copied verbatim
```

`outputs.json` and `index.json` are replaced because both describe the symlink
view (`abs` names a path on the authoring host, which does not survive leaving
it). Any *other* record file in a step folder that is not a symlink and is under
the commit ceiling is copied through. `written.json` matches that rule, so it
ships. Confirmed:

```
$ find benchmark-data/ic -name written.json | wc -l
126
$ cat .../steps/phase3/stage3/21_routing_global_detailed/STEP_RECORD.json
  ... "records": [ "written.json" ]
$ ls .../steps/phase3/stage3/21_routing_global_detailed/
STEP_RECORD.json  written.json
```

`reports/write_ledger.json` ships too, via the ordinary `reports/` subtree copy.

### 4.5 The four names, disambiguated

| Name | Written by | Lives in | Published? | What it answers |
|---|---|---|---|---|
| `outputs.json` | `step_output_collector` | run `steps/<folder>/` | **No** — replaced | which declared outputs existed at collect time, incl. host-absolute `abs` |
| `index.json` | `step_output_collector` | run `steps/` | **No** — replaced by `STEP_INDEX.json` | the ordered step list + output counts |
| `written.json` | `step_write_ledger.emit()` | run `steps/<folder>/` | **Yes** — copied verbatim | this step's slice of the OBSERVED-writes ledger |
| `write_ledger.json` | `step_write_ledger.emit()` | run `reports/` | **Yes** — via `reports/` copy | the whole-run observed-writes ledger + D3/D5/D7 residual |
| `STEP_RECORD.json` | `benchmark_evidence_publish` | cell `steps/<folder>/` | **created at publish** | each declared output as run-relative path + bytes + sha256 + where a reader of THIS cell finds it |
| `STEP_ROUTING.txt` | `benchmark_evidence_publish` | cell **root** | **created at publish** | the same data, flat and greppable |

`written.json` and `write_ledger.json` are **not** two halves of one thing:
`write_ledger.json` is the whole ledger, `written.json` is one row of it.
`STEP_RECORD.json` is a different question entirely — it is the *declaration*
resolved against the run, not an observation of writes.

### 4.6 Measured shape of a current cell

`benchmark-data/ic/spm/v1.9.94_sky130A`:

```
root:      CITATION_ROUTING.txt  LAYOUT_ROUTING.txt  STEP_ROUTING.txt
           RESULT.md  provenance.jsonl
           phase1/  phase2/  phase3/  reports/  steps/
phase3/:   reports/  stage4/gds/        ← no stage3/, by design
STEP_INDEX: 63 steps, 91 declared outputs, 70 in cell
STEP_ROUTING histogram: IN_CELL 70, OUT_OF_PUBLISHED_SCOPE 21,
                        ZERO_BYTE 0, DANGLING_IN_RUN 0, ABSENT_IN_RUN 0
```

The 21 `OUT_OF_PUBLISHED_SCOPE` rows are almost entirely `phase3/stage3/*` —
each carrying a sha256, so the artefact stays verifiable without being stored.

---

## 5. History — symlinks → record, with the measured reason

The change was **not** stylistic. Three measurements drove it, and all three
reproduce today.

**(a) A run's own view goes 100% dangling the moment the directory moves.**
`_car15_evidence` is a converged run whose directory was later renamed:

```
$ python3 -c "...steps/index.json..."   → 63 steps, 90 declared outputs
$ find steps -type l | wc -l            → 83
$ for l in $(find steps -type l); do [ -e "$l" ] || echo dangling; done | wc -l
83
```

**83 of 83 dangling.** Copying that tree would have published 83 broken links.
The run-relative paths, by contrast, still resolve: 83 of the 90 declared
entries are present on disk.

**(b) The "step says PASS but its declared output no longer exists" residual is
real, and it is 7.** On the same run, resolving every declared output
run-relative:

```
step 15 pass  phase3/stage3/pnr/floorplan.def       ABSENT
step 17 pass  phase3/stage3/pnr/placed.def          ABSENT
step 19 pass  phase3/stage3/pnr/post_cts.def        ABSENT
step 20 pass  phase3/stage3/pnr/post_hold.def       ABSENT
step 21 pass  phase3/stage3/pnr/routed.def          ABSENT
step 22 pass  phase3/stage3/extracted/…​.spef        ABSENT
step 34 pass  phase3/stage3/pnr/filled.def          ABSENT
```

**7 outputs, declared by 7 steps whose own status is `pass`, that no longer
exist.** Mirroring the view would have shown 83 identical broken links and named
none of them. The prior figure of "7 caught cases" is **correct**; the six `.def`
+ one `.spef` breakdown is correct.

**(c) Legacy cells that DID commit their steps tree ship broken links.**

```
$ git ls-files -s benchmark-data | awk '$1=="120000"' | wc -l      → 143
$   … of which under a steps/ path                                 → 142
$   … whose symlink target the git index does not carry            → 31
```

**142 tracked symlinks, 31 dangling on a clean clone.** Exact match to the
figures in the code comments (`_published_tree` #404). They live in four legacy
cells:

```
53  sha256/clean_run_v1427_20260715
47  edge_llm_accel/steps          ← a FLAT steps tree at the IC level, pre-nesting
25  sha256/clean_run_v1422_20260715
17  u_hawaii_adc/clean_run_v1422_20260715
```

The alternative — dereferencing on copy — duplicates bytes the cell already
carries at their canonical path (measured 2,787,213 B for one spm run vs 59,581 B
for the record that replaced it).

**Three generations are therefore visible in `benchmark-data/` today:**
flat committed symlink trees (`edge_llm_accel/steps/`) → nested committed symlink
trees (`clean_run_*/steps/`) → nested **record** trees (`v1.9.9x_*/steps/` with
`STEP_RECORD.json`). Only the third is produced by the current program.

---

## 6. Gaps and inconsistencies

Ordered by how much they can mislead a reader. Each is reproducible from the
command shown.

### G1 — the per-step record silently truncates at 6 outputs (**highest value**)

`flow_dashboard_data._OUTPUTS_CAP = 6` is a **display** cap. `_resolve_outputs`
returns full `n_present`/`n_total` (so the *status* is correct) but attaches only
`entries[:6]`. The collector consumes only those entries, so the cap propagates
into `outputs.json` → `STEP_RECORD.json` → `STEP_ROUTING.txt` — the **evidence**
path — with **no marker that truncation occurred**.

Exactly one step is affected today, and it is the Phase-1 root: **`D1` declares
14 `required_outputs`; the published record carries 6.**

```
$ python3 -c "...D1 required_outputs..."       → 14 (L1..L13 + L8_RTL_CONSTANTS)
$ jq '.declared_outputs|length' .../D1_…/STEP_RECORD.json  → 6  (L1..L6, all IN_CELL)
$ ls benchmark-data/ic/spm/v1.9.94_sky130A/phase1/generated_docs/ | wc -l → 28
```

A reader of `D1/STEP_RECORD.json` sees `status: pass, 6 declared, 6 in cell` and
has no way to learn that 8 further outputs were declared — even though the cell
physically carries L7..L27. **The record understates the flow's own declaration
and gives no signal that it is doing so.** Fix shape: either raise/remove the cap
on the collector path (the cap exists for a dashboard UI, not for evidence), or
record `n_declared_total` alongside the truncated list.

### G2 — the record can only ever report `ABSENT_IN_RUN` for an output that once existed

The collector filters `if not o.get("exists"): continue`, so a declared output
that was **never produced** never enters `outputs.json`, therefore never enters
`STEP_RECORD.json`, therefore can never be assigned `ABSENT_IN_RUN`. That
decision fires only for an output present at collect time and gone by publish
time (which is precisely the `_car15_evidence` case that motivated it).

Measured on `v1.9.94_sky130A`: 22 of 63 steps carry fewer recorded outputs than
the YAML declares. 21 of those are honestly explained by the step's own
`status` (`na` ×13 analog/mixed, `external` ×5 manufacturing, `skipped` ×3) —
the 22nd is D1 (G1). So the current corpus is not *lying*, but the mechanism that
would catch a lie is structurally unable to: `STEP_ROUTING.txt` shows **0
`ABSENT_IN_RUN`** on both reference cells and would show 0 even if a step had
declared an output and produced nothing. The whole-run answer to that question
lives in `reports/write_ledger.json`'s D3 direction — but nothing joins the two.

### G3 — the flow declares three families of paths its own layout gates forbid

Reproduced against a synthetic project holding exactly the declared paths:

```
$ python3 programs/reports_subfolder_taxonomy_check.py <proj>
[FAIL] 1 stray subdir(s): analog        rc=1
$ python3 programs/top_level_outputs_in_canonical_check.py <proj>
[FAIL] 1 stray dir(s): sim_spice        rc=1
```

| Declared in flow | Refs | Forbidden by |
|---|---|---|
| `reports/analog/**` | 18 (6 `required_outputs` for M1–M4, 12 gate `--json` targets incl. A1/A2/A3/A5) | `REPORTS_VALID_SUBDIRS` has no `analog` |
| `reports/manufacturing/**` | 5 (gate `--json` for steps 40–44) | same |
| `reports/{lec.json,lec.rpt,spare_cell_coverage.json,lec_equivalence_check.json,density.json,density.rpt}` | 6 | `REPORTS_VALID_ROOT_FILES` allows only 2 files |
| `sim_spice/*.sp` (step 30, 3rd OR alternative) | 2 | `TOP_LEVEL_VALID_DIRS` has no `sim_spice` |

These are **not** hypothetical: `lec_run.py` / `lec_equivalence_check.py`
hardcode `reports/lec.json` + `reports/lec.rpt`, and
`spare_cell_coverage_check.py` hardcodes `reports/spare_cell_coverage.json`
(bypassing `report_path()`, which would route both to `reports/audit/`).
Measured on real trees:

```
$ reports_subfolder_taxonomy_check.py benchmark-data/ic/spm/v1.9.94_sky130A
[FAIL] 16 stray file(s)   rc=1
$ … benchmark-data/ic/spm/v1.9.96_gf180mcuD   → 17 stray file(s)  rc=1
$ … /home/reyerchu/_car15_evidence            → 15 stray file(s)  rc=1
```

**Both reference cells — the repo's own gold standard — fail the repo's own
`reports/` taxonomy gate.** Note `reports_subfolder_taxonomy_check.py`'s **own
docstring** (line 8) lists `analog/` as a valid subdir while the code reads
`_pl.REPORTS_VALID_SUBDIRS`, which does not contain it: doc and code disagree
inside a single 170-line file.

By contrast, `phase{1,2}/analog/**` (A1–A4) is **not** a gap: those are declared
strictly as `OR` fallbacks after `phase3/analog/…`, matching `_path_layout`'s
explicit "legacy read-side tolerance, zero callers" comment.

### G4 — the publisher emits three root files the canonical-top-level gate rejects

```
$ top_level_outputs_in_canonical_check.py benchmark-data/ic/spm/v1.9.94_sky130A
[FAIL] 3 stray file(s): CITATION_ROUTING.txt, LAYOUT_ROUTING.txt, STEP_ROUTING.txt
```

All three are written **by the plugin's own publisher** at the cell root, and
none is in `TOP_LEVEL_VALID_FILES`. This is the same class of defect that was
already fixed once for directories — `steps/` was added to
`TOP_LEVEL_VALID_DIRS` with a long comment explaining that "recording the
directory the flow legitimately owns is not widening the gate" — and the three
`*_ROUTING.txt` files were simply not carried through the same reasoning.

### G5 — G3 and G4 are latent, not blocking, because both gates are unwired

`programs/gate_is_wired_baseline.json` (`"Gates no automatic verdict consults"`)
lists **both** `reports_subfolder_taxonomy_check` and
`top_level_outputs_in_canonical_check` in `unwired` **and** in `skill_only`.
So the contradictions above fail nothing today. That is worth stating plainly in
both directions: no run is being wrongly failed, **and** the gate that would have
caught the flow/layout drift has never been in a position to catch it. Wiring
either gate as-is would immediately red both reference cells.

### G6 — `stages[].steps` membership lists are stale from step 14 onward

```
stage3  declares 14..31   actual 15..32
stage4  declares 32..37   actual 33..39
stage5  declares 38..41   actual 40..44
stage1  declares 1..6      actual 1..6 + P0
stage2  declares 7..13     actual 7..14 + FS1,DT1,DT2,DT3
```

Off by one from the Design-for-ECO renumber, and never updated for the DFT /
FMEDA / P0 insertions. **No program in the tree reads `stages[].steps`** — the
only consumer of the `stages:` block, `phase1_planned_consumer_starved_check.py`,
indexes by `id` and reads `condition` only. So this is documentation that is
wrong and unguarded. The same drift appears in two other places:

* the YAML header comment: *"the main flow integer track is now 1..41 …
  Foundry Handoff is 36, FPGA final sign-off is 37, manufacturing 38-41"* —
  actual: track is 1..44, Foundry Handoff is **38**, FPGA final sign-off is
  **39**, manufacturing is **40–44**;
* `_path_layout.py`'s module docstring: *stage3 "Steps 14-30", stage4 "Steps
  31-36", stage5 "Steps 37-40"* — actual: 15–32, 33–39, 40–44.

The `total_steps: 44` figure itself is **correctly** maintained and guarded
(`test_all_steps_covers_flow.py`, 5 passed, incl. the `ALL_STEPS_*.md` headline).

### G7 — `PUBLISHING.md` contradicts itself on raw geometry

`benchmark-data/PUBLISHING.md` §"Excluded by construction" states the four
layout extensions are *"gitignored / too large and never committed"*, while the
`NO_RAW_GEOMETRY` bullet 70 lines later correctly states they ship **under the
50 MB ceiling** (#419), as does the publisher's own code. The first paragraph is
a leftover from the pre-#419 extension rule and reads as authoritative.

### G8 — published-tree re-audit false negative (already disclosed, advisory only)

Re-running `flow_compliance_check.py --strict` against **any** published cell
produces spurious `FAIL`/`MISSING` on `phase3/stage3/*` targets, because
publishing excludes that subtree by design — so `files_exist` can never resolve.
This surfaced on `caravel_user_project/v1.9.43_sky130A` and reproduces
identically on both spm reference cells, whose own committed audits record
`PASS_WITH_WAIVERS`. Landed as `_published_tree_advisory()` in
`flow_compliance_check.py` (v1.10.3, commit `e6257c6b3`): **purely additive**,
detects the shape structurally (`GDS_MANIFEST.txt` present + `phase3/stage3/`
absent) and changes no verdict, count or exit code. The operative rule it
records: *a published tree's authoritative verdict is the audit captured at
original run time, never a re-run against the published copy.*

Related residual: the advisory's docstring (and the commit message) attribute
the `phase3/stage3/*` + `*.log` exclusion to `PUBLISHING.md`, but `PUBLISHING.md`
only *implies* it in a scope note. The exclusion actually lives in
`benchmark_evidence_publish._COPY_SUBTREES`. Worth stating explicitly in
`PUBLISHING.md`.

### G9 — 31 dangling symlinks remain committed in four legacy cells

Not produced by any current code path, but a clean clone of `main` still
receives them (§5c). They are the reason `_published_tree` distinguishes
"tracked path" from "tracked content"; they have not been retired.

---

## 7. Reproduction index

```bash
R=/home/reyerchu/vibe-ic
P=$R/vibe-ic-marketplace/plugins/vibe-ic

# §1 step counts / stage membership / declared directories
python3 - <<'PY'
import yaml, collections
d = yaml.safe_load(open("flow/phase1_phase2_phase3.yaml"))
print(d["total_steps"], d["analog_steps"], len(d["steps"]))
print(collections.Counter(s["stage"] for s in d["steps"]))
PY

# §3.2 the mirror is still symlinks in a live run
find /home/reyerchu/_car15_evidence/steps -type l | wc -l

# §4.4 written.json ships; index.json / outputs.json do not
find $R/benchmark-data/ic -name written.json | wc -l
find $R/benchmark-data/ic/spm/v1.9.94_sky130A/steps -name outputs.json | wc -l   # 0

# §5c legacy committed symlinks
git -C $R ls-files -s benchmark-data | awk '$1=="120000"' | wc -l

# §6 G3/G4 the layout gates against the reference cells
python3 $P/programs/reports_subfolder_taxonomy_check.py    $R/benchmark-data/ic/spm/v1.9.94_sky130A
python3 $P/programs/top_level_outputs_in_canonical_check.py $R/benchmark-data/ic/spm/v1.9.94_sky130A

# §6 G6 the 44-count guard (passes)
cd $P && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest programs/tests/test_all_steps_covers_flow.py -q
```

---

## 8. Related documents

* `benchmark-data/PUBLISHING.md` — the publish contract as a how-to.
* `programs/_path_layout.py` — the layout itself (read the module docstring).
* `programs/step_output_collector.py`, `programs/step_write_ledger.py`,
  `programs/benchmark_evidence_publish.py` — the three producers.
* `programs/gate_is_wired_baseline.json` — which gates no verdict consults.
