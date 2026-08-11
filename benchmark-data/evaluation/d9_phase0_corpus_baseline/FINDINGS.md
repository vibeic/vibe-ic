# D9 Phase 0 / Deliverable 0.2 — what the corpus baseline says

The table is `corpus_baseline.md` (+ `corpus_baseline.json`, one row per
`(run, checker)` cell). It is emitted by `tools/d9_corpus_baseline.py`, so it is
regenerable rather than pasted:

```
python3 tools/d9_corpus_baseline.py --out benchmark-data/evaluation/d9_phase0_corpus_baseline
```

This is a MEASUREMENT. No checker was repaired, nothing was wired into
`flow/phase1_phase2_phase3.yaml`, and no verdict was changed. After the
authoritative sweep, `git status` over `benchmark-data/` is **empty** — the
corpus is byte-identical to `origin/main`.

---

## 1. The corpus: 107 published run directories, not ~89

**Discovered, not typed.** PUBLISHED == git-tracked, because `.gitignore`
excludes some working run trees, so "on disk" and "published" differ:

```
git ls-files benchmark-data | dirs containing phase1/generated_docs/
```

That yields **107**: `evaluation/phase1_parity/*` 87, `evaluation/cvdp/**` 4,
`ic/**` 16.

### CONTRADICTION WITH THE BRIEF — stated, not smoothed over

The brief says "~89". The measurement says **107**. The alternatives were
measured rather than argued:

| definition | count |
|---|--:|
| tracked dirs with `phase1/generated_docs/` (**used**) | **107** |
| dirs with `phase1/` and (`phase2/` or `phase3/`), minus `reports/` noise | 78 |
| dirs with both `input/` and `phase1/` | 69 |
| dirs containing a `RESULT.md` | 52 |

No definition tried yields 89; 87 (`phase1_parity` alone) and 91 (`evaluation/`
alone) bracket it, so "~89" is most likely a sub-family rather than the corpus.
The 107 list is enumerated in `corpus_baseline.json` under `corpus.run_dirs`, so
the denominator is auditable rather than asserted.

Two `ic/` entries are NESTED inside another run (`caravel_user_project/` and its
`v1.9.43_sky130A/`; `sha256/` and its `clean_run_*`). Counted separately,
because each has its own Phase-1 output and each would go red on its own.

---

## 2. The checkers: 78, of which the brief's 13 are a subset

Candidate = a program under `programs/` that has an `ArgumentParser`, reads file
CONTENT, is **verdict-shaped** (can name a failure AND exit non-zero because of
one), and appears nowhere in the flow YAML.

| stage | count |
|---|--:|
| non-underscore programs | 1073 |
| named in the flow YAML | 207 |
| unreferenced | 866 |
| … dir-positional + content-reading | 191 |
| … **and verdict-shaped** | 69 |
| + bespoke arg shapes the AST filter cannot see | 9 |
| **total measured** | **78** (77 measurable per-cell + 1 not) |

### CONTRADICTION WITH THE BRIEF — two of the 13 are already in the flow

The brief defines the set as having **ZERO** flow-YAML references. Measured
against `origin/main` @ `38c8e687`:

| candidate | lines | refs in flow YAML |
|---|--:|--:|
| `l8_sta_clock_period_design_owned_check` | 591 | **2** |
| `dfm_screen_check` | 576 | **3** |

The other 11 are at 0 refs and their line counts match the brief exactly. The
brief's own "7,321 lines" is `1822+204+808+614+608+364+219+190+851+591+913+137`
— it **includes** `l8_sta_…` (591, 2 refs) and **excludes** `dfm_screen_check`.
Both were measured anyway and are flagged in the table.

`dual_track_select` is **not measurable per (run, checker)** and is reported as
such rather than dropped: it is a SELECTOR over caller-supplied
`--candidate name=path` pairs. It reads no artefact of a published run, so there
is no cell to fill. Denominator: 77 × 107 = **8239 cells**.

---

## 3. The four buckets

**8239 cells · 263.7 s.**

| bucket | cells | share |
|---|--:|--:|
| CLEAN — read content, found nothing wrong | 2164 | 26.3% |
| FINDING — read content, found something | 827 | 10.0% |
| NO-INPUT — the artefact it needs is not in this run | 4817 | 58.5% |
| ERROR — crashed / could not run | 431 | 5.2% |

ERROR = **428 "could not measure"** (argparse refused the run-dir shape:
`analog_mc_yield_run` needs `--block`, `lec_run` and `regmap_transaction_tb_gen`
need `--top`, `benchmark_run_manifest` takes a subcommand — 4 × 107) plus
**3 genuine crashes** (`l21_to_upf_emit`, `ValueError: cannot resolve the supply
net for power domain(s)`). These stay in the denominator: "could not measure" is
a result.

### 3.1 HEADLINE 1 — the exit code is not enough; 2051 cells prove it

A first pass trusting `rc` alone reported **CLEAN=4332 / NO-INPUT=2395**. That
was wrong. Gates exit `rc 0` while their own stdout says they read nothing:

```
crc_residue_settle_state_required_check → "[SKIP] …  files scanned: 0"      rc 0
phy_counter_audit                       → {"verdict":"SKIP","pass":true}     rc 0
send_test_active_drive_check            → "PASS_SKIP — no SEND_TEST opcode"  rc 0
em_current_density_check                → {"severity":"SKIPPED", …}          rc 3
```

Letting each gate's **self-disclosure outrank its exit code** moved **2051 cells
from CLEAN to NO-INPUT**. Nearly half of what looked like "clean across the
corpus" was "examined nothing" — the exact conflation this deliverable exists to
prevent, one level up.

The rule is the repo's own: `programs/_vacuous_exit.py`
(`RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2`, `VACUOUS_PASS:`) and the
`denominator{examined, unit, not_applicable_reason}` block of
`programs/_gate_denominator.py`. The disclosure predicate is **imported** from
`gate_discloses_denominator_check`, not re-implemented, so this table and that
gate cannot drift into two dialects.

### 3.2 HEADLINE 2 — the instrument was corrupting its own measurement

**10 of 77 candidates WRITE INTO THE RUN THEY JUDGE.** `phase1_one_shot_runner`
rewrites `phase1/generated_docs/*`; `qsf_gen` emits FPGA project files;
`ip_catalog_pull` drops vendor RTL into `phase2/stage1/rtl/`. The first sweep
left **2336 tracked files modified** under `benchmark-data/`.

That is two problems, and the second is worse. It edits published data — and it
**contaminates the numbers**, because a cell's verdict then depends on which
cells the scheduler happened to run first.

Measured cost: `step_internal_fail_bubble_up_check` read **91** red on the
contaminated sweep and **17** on the isolated one. 74 of those 91 were files
*my own sweep had written*. **An adjudication built on that was retracted** —
see §4.4.

Fix: every cell now runs against a pristine throwaway copy, **unconditionally**.
An intermediate version isolated only the writers a probe had caught, and still
left 40 files modified: a probe on one run cannot reveal a writer that only
fires when a richer artefact is present. Probing 1 run found 3 writers, 2 runs
found 8, 3 runs found 10 — the set is *still* not proven complete, which is
exactly why safety must not depend on it. The writer census is published as a
finding (`writers_isolated` in the JSON); correctness depends on nothing.

**A checker that writes into the run it judges is not promotable to a blocking
gate as-is**, independently of whether its ruler is right.

### 3.3 161 CLEAN cells are a PASS that never says how much it looked at

By the house `discloses()` predicate, 2003 of 2164 CLEAN cells state their
denominator; **161 do not** — those PASSes are not yet distinguishable from a
PASS over nothing. Reported, not fixed.

---

## 4. Adjudication — REAL DEFECT vs WRONG RULER

**15 checkers adjudicated; 24 individual red cells opened and read by hand**
(including *every one* of `metal_layer_density_check`'s 14). All adjudications
below were re-verified against the **pristine** corpus after §3.2. The other
red cells are not adjudicated and nothing is claimed about them.

### 4.1 SAFE TO PROMOTE — ruler verified correct on the cells inspected

| checker | would redden | evidence (pristine corpus) |
|---|--:|---|
| `l9_submodule_conformance_check` | 8 | `sgmii`: L9 declares `k28p5_special_char` / `k27p7_special_char`; no `module` of either name exists under `rtl/`. Discloses "2 of 2 declared submodule(s) examined". |
| `l6_fsm_scaffold_actionable_check` | 41 | `a2b`: L6 describes 1 state machine, 10 states, **0** transitions; `emit_fsm_v()`'s body is literally `// TODO — transition logic per L6.fsm_transitions`. |
| `l20_dft_scan_topology_actionable_check` | 55 | `afdx`: `dft_present='partial'` asserted while `scan_chains[]` is EMPTY — an assertion nothing downstream can falsify. |
| `step_internal_fail_bubble_up_check` | 17 | `espi`: three **git-tracked** reports (`reports/phase2/gates/spare_cell_preservation.json`, `…/spare_preservation_postfill.json`, `reports/spare_preservation.json`) each carry `verdict: FAIL`, unacknowledged at top level. Tracked-status checked explicitly *because* of §3.2. |
| `declared_pdk_is_the_pdk_used_check` | 10 | `edge_llm_accel`: declares `pdk_target: nangate45`, stages `0 file(s) under input/pdk/`, and no cell-library load appears in the logs. The gate states plainly that this is absence-of-evidence, not evidence of a wrong PDK. |

Caveat carried openly: `l20` (55) and `l6` (41) are correct rulers that redden
half the corpus. Promoting them is honest but is a *policy* call about published
history, not a measurement call.

### 4.2 RULER MUST BE SETTLED FIRST — do not promote

| checker | would redden | why the ruler is wrong |
|---|--:|---|
| `agent_report_presence_check` | **107 / 107** | Demands `AGENT_REPORT.md` at project root. `git ls-files benchmark-data \| grep -ci AGENT_REPORT.md` = **0**. A 107/107 red is a ruler, not a defect. |
| `metal_layer_density_check` | 14 | §5 — **14 of 14** reds are a zero-denominator FAIL, not a density fact. |
| `behavioral_evidence_per_spec_item_check` | **107** | `cvdp_copilot_cont_adder_0042`: prints `no requirements found in …L9_INTEGRATION_SPEC.json`, then `FAIL: L9 has no extractable behavioral requirements`, at **rc 1**. A zero denominator must REFUSE (rc 2) — `gate_zero_denominator_refuses_check` is the house rule. This is "I had nothing to judge" dressed as a defect. |
| `spec_conformance_check` | 2 | **Split verdict.** `caravel_user_project` is REAL: 9 concrete port-contract violations (`io_in`/`io_oeb`/`io_out` width RTL=16 vs spec=38; `analog_io`, `user_clock2`, `user_irq` missing). `sent` is the checker's own prose-semantic inference, which it labels `semantic candidate — NOT LLM-confirmed (no backend); AI must double-confirm`. **Safe in its port-contract dimension; not in its prose-semantic one.** |

### 4.3 RULER POSTDATES THE CORPUS — true, but not a design defect

Both redden 107/107 because they enforce a convention introduced *after* these
runs were published. Promoting either reddens every project for being old.

| checker | evidence |
|---|---|
| `l_doc_generator_stamp` | `ace_chi`: `UNSTAMPED=24` — "no `_generator` key — produced before the emitter recorded its release; vintage unknown". |
| `gate_evidence_completeness_check` | `sha256`: "31 PASS gates, 0 with evidence, 31 without evidence". |

### 4.4 RETRACTED — an adjudication that did not survive isolation

An earlier draft cited `ace_chi`'s `reports/phase1_one_shot.json` (`verdict:
FAIL`) as proof for `step_internal_fail_bubble_up_check`. **That file does not
exist in the published corpus** — my own contaminated sweep created it (§3.2).
The adjudication was redone on `espi` against git-tracked files, and the
checker's real red count is 17, not 91. Recorded rather than quietly corrected,
because the failure mode — an instrument manufacturing its own evidence — is the
most dangerous one in this deliverable.

### 4.5 NOT GATES AT ALL — a limit of my own discovery filter

"Emits a FAIL string + has an `rc != 0` path" admits **generators and runners**
that fail when they cannot generate. In the table for completeness, **not
promotable candidates**: `qsf_gen` (95), `phase1_one_shot_runner` (50),
`l21_to_upf_emit` (10, incl. the 3 crashes), `spec_declaration_emit` (5), plus
the 4 that ERROR on every run for want of a required option. Naming the filter's
own false-positive class is cheaper than letting a reviewer find it.

---

## 5. The known landmine — flagged, NOT resolved

`metal_layer_density_check` is owned by another agent and is not resolved here.

The brief's known issue: it FAILs 5 of 6 layers on the flagship published run
against that PDK's own deck.

**This sweep measured a SECOND, INDEPENDENT wrong-ruler defect in the same
program.** Driven at run-dir granularity it reddens 14 projects, and **all 14
emit the identical verdict**:

```json
{"verdict": "FAIL",
 "detail": "no per-layer metal density found in the report
            (present but carries no per-layer metal-density data)"}
```

rc 1 — on `espi`, `lpc`, `mdio`, `sgmii` (Phase-1-only runs with **no layout at
all**) as well as on `caravel_user_project`, `sha256`, `subservient`,
`edge_llm_accel` and every `spm` variant. Not one of the 14 is a density
measurement. It is a zero-denominator FAIL where the house rule requires a
REFUSE, and it is **distinct** from the 5-of-6-layers window question, which is
reached by a different invocation carrying a real density report. Recorded so
whoever settles the window knows there is a second thing to settle.
**Nothing was changed here.**

---

## 6. Limits I am leaving in place — stated so nobody has to catch them

1. **107 ≠ the brief's ~89** (§1). Alternatives measured; the run list is in the
   JSON.
2. **The extension is heuristic.** "Verdict-shaped" = a `FAIL`/`VIOLATION`
   literal AND a `return 1` / `exit(1)` path. It admits generators (§4.5) and
   would miss a gate failing via a helper the regex cannot see. The brief's 13
   are covered explicitly and do not depend on the heuristic.
3. **One invocation per checker per run.** Several candidates have richer CLIs
   (`--pdk`, `--jmax`, `--tech-lef`, `--golden`, `--strict`). This measures the
   run-dir-shaped invocation only. `metal_layer_density_check` with a real
   `--pdk` and a real density report will say something different from row 14 —
   §5.
4. **`xor_layout_check` = NO-INPUT on all 107, which is an environment limit,
   not a clean bill.** No published run ships a `.gds`/`.gds.gz` this harness
   locates, and its real mode needs a golden reference plus a layout tool. Never
   exercised.
5. **`analog_oracle_compare` = NO-INPUT on all 107** — no published run carries
   an `analog/` block dir with `oracle_specs.json`. Never exercised.
6. **`em_current_density_check` = NO-INPUT on all 107**, because it correctly
   refuses without `--jmax`/`--tech-lef` (`§4.05: cannot fabricate PASS`). Its
   real behaviour against a tech LEF is **unmeasured**.
7. **No container, no PDK, no EDA tools were available.** Anything needing a
   tech LEF, a sign-off deck or a layout engine is NO-INPUT or ERROR here and
   its true rate is unknown. Items 4–6 are the concrete instances.
8. **The writer census is not proven complete** (§3.2): 1 probe run → 3 writers,
   2 → 8, 3 → 10. Isolation is unconditional so the numbers do not depend on it,
   but the published census may under-count.
9. **My own locators are part of the ruler.** `locate_rtl_dir` and
   `locate_spec` decide what `spec_conformance_check` and
   `spec_rtl_port_fidelity_check` are pointed at. An earlier version pointed
   caravel's checker at `input/design_src/verilog/rtl` (vendor RTL) instead of
   `phase2/stage1/rtl` — a wrong ruler introduced by the *instrument*, invisible
   in the checker's own output. Fixed and regression-tested
   (`TestGeneratedRtlIsNeverTheInputRtl`). The other bespoke locators have had
   no equivalent audit.
10. **827 FINDING cells; 24 adjudicated across 15 checkers.** The
    REAL-vs-WRONG-RULER split is asserted only for §4. Everything else is a
    measurement with no verdict attached.
11. **Nested runs are counted separately** (§1), so a defect a child inherits
    from its parent tree is counted twice in "would redden N projects".
12. **`ERROR` for the 4 required-option programs is a statement about the
    run-dir invocation, not about the program.** Given `--block` / `--top` they
    may work fine; that was not measured.
