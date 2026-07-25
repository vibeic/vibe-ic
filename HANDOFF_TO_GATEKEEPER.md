# HANDOFF TO GATEKEEPER — gds_substance_check

**Worktree:** `/home/reyerchu/vibe-ic-wt-gdssubstance/`
**Branch:** `fix/gds-substance-gate-gdssubstance` (branched from `origin/main` @ `0d2c63d3`)
**Commit:** _(see §6 — filled in at commit time)_
**NOT pushed.** Nothing was pushed to any remote. Landing is the gatekeeper's call.

> **VERSION: deliberately NOT bumped.** `plugin.json` still reads `1.5.78`.
> Assign the version at land time, in the landing commit. A version bump
> committed here would be silently eaten by the rebase — that collision
> already happened once today.

---

## 1. Headline: the reported run is NOT a false certificate

The premise of the investigation ("a run reported convergence but the GDS is
only 86 bytes") **does not hold**. The `converge_1.5.74_ihp-sg13g2` run is
legitimate. Reporting this honestly, because the opposite conclusion would
have triggered a much larger rollback.

**The 86 bytes is a symlink's target-path length, not a file size.**

```
$ cd ~/campaign_v1574/spm/converge_1.5.74_ihp-sg13g2
$ stat -c "%n lsize=%s" steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds
steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds lsize=86
$ stat -L -c "%n size=%s" steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds
steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds size=822084
$ readlink steps/37_.../spm.gds | wc -c
86
```

`ls -l` on a symlink reports the length of the target path string. The target
path is exactly 86 characters. The `steps/` tree is an index of pointers into
the phase trees, materialised at 12:31:55; every entry there is a symlink.

**The actual GDS is real, 822,084 bytes** — the same size as the committed
golden `benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/`. The SHA differs
(`94be29af…` vs `acbb3ae1…`) because GDSII embeds BGNLIB/BGNSTR
timestamps; that is expected run-to-run and not evidence of anything.

Structural proof from the raw bytes (not from any summary JSON):

```
00000000: 0006 0002 0258   HEADER, version 600
          001c 0102 07ea…  BGNLIB, 2026-07-25
          0008 0206 7370 6d00        LIBNAME "spm"
          0014 0305 …                UNITS
          001c 0502 …                BGNSTR
          0012 0606 7367 3133 6732…  STRNAME "sg13g2_buf_16"
…
000c8b34: … 0004 1100  0004 0700  0004 0400   ENDEL / ENDSTR / ENDLIB
```

Parsed with the new gate: **28 structures, 11,583 layout elements, 19 layers,
1,826 SREF placements against 1,826 DEF `COMPONENTS`** — an exact match. A
fabricated artefact cannot reproduce that correspondence.

### The 198 seconds

Also explainable, and also not evidence of fakery. Two facts:

1. **It was never a full phase1→3.** `reports/phase1_one_shot.json` shows
   `mode: docs`, delegated to `phase1_doc_one_shot_runner`, `duration_s:
   1.515`. `vibe_ic_one_shot.json` records `phases[0] phase1 = SKIPPED` and
   `phases[2] analog = SKIPPED`. Only phase2 + phase3 executed.
   The orchestrator's own `duration_s` is **169.22 s**, which is the number
   behind the "198 s" recollection.

2. **The run kept working after that summary was written.** The same summary
   says `deliverable_self_check.state = RUN_STILL_IN_PROGRESS`, `pid 3531403
   alive`. File mtimes span **12:22:22 → 12:31:55 = 573 s wall**, in two
   bursts (12:22–12:25, then 12:29–12:31 for the DFT TDF SAT run and the
   canonical KLayout streamout).

Per-step durations from `phase3_one_shot.json` account for the 169 s honestly:

| step | duration | detail |
|---|---|---|
| synth | 0.0 s | `netlist already present: spm_synth.v (skipped re-run to preserve provenance)` |
| pnr | 85.6 s | real OpenROAD: 352 instances → 1,826 placed, DRT 23.8 s, 6,897 µm² |
| gds | 7.6 s | `streamout=magic`, runner recorded `size=822084` |
| drc | 15.2 s | violations=0 |
| lvs | 1.9 s | netgen, power-aware, circuits match uniquely |

**On the netlist-reuse concern specifically:** synth was *not* stale-reused.
`phase2/stage2/synth/spm_synth.v` and `synth.log` (27 KB) are both stamped
`07-25 12:22:32` — 10 s into this run. Phase3 at 12:24 skipped *re-running*
a netlist that this same run had produced two minutes earlier. The RTL
(`phase2/stage1/rtl/spm.v`) is unchanged since 07-21, so netlist and RTL are
consistent. This run does not exercise the known main-branch hole.

Net: **no rollback needed for v1574.**

---

## 2. But there IS a real gate defect, and it is fixed here

While the 86-byte scare was a misread, chasing it surfaced a genuine hole in
the sign-off path. **The chip-level GDS had no substance gate at all.**

Step 37's only content check was `gds_size_check` (v1.1.0), which:

- compares against a **flow-wide hardcoded constant** (`--min-size-kb`,
  default `100.0`) that has nothing to do with the design's size; and
- demotes an invalid GDSII header to a **WARNING**, so it never fails.

Analog blocks have had `analog_artefact_substance_check` since v1.6.28
(catches 64-byte HEADER+ENDLIB stubs). **The top-level chip GDS had no
equivalent.**

### Measured, before the fix

Three fabricated artefacts, each sized to clear the 100 KB constant, all
placed at the canonical path `phase3/stage4/gds/spm.gds` of an otherwise
real converged project:

| fake | `gds_size_check` | **Step 37 verdict** |
|---|---|---|
| 150 KB of `os.urandom()` behind a 4-byte HEADER | `pass:true, errors:0, warnings:0` | **✓ PASS** |
| 150 KB zero-padded library, **zero structures** | `pass:true, errors:0, warnings:0` | **✓ PASS** |
| 150 KB even-length junk, never reaches ENDLIB | `pass:true, errors:0, warnings:0` | **✓ PASS** |
| 86-byte HEADER+ENDLIB stub | `TOO_SMALL` | ✗ FAIL |

The last row matters for honest scoping: **an 86-byte GDS was already caught**
by the size floor. The hole is the opposite shape — anything *above* 100 KB
signed off no matter what it contained. A 200k-instance SoC shipping a 120 KB
stub cleared step 37 exactly as easily as a 350-instance test chip.

---

## 3. The fix

**New:** `programs/gds_substance_check.py` (v1.0.0, 0 deps, pure Python)

Three layers, all **hard FAIL** — the gate has no advisory tier:

**A. Structure** — full GDSII record-stream walk: first record is HEADER,
last is ENDLIB, every record length ≥4 / even / inside the file, no trailing
bytes after ENDLIB, BGNLIB+LIBNAME+UNITS present, BGNSTR/ENDSTR balanced.
A file that does not parse is not a GDS, whatever its byte count.

**B. Substance** — ≥1 structure, ≥1 layout element
(BOUNDARY/PATH/SREF/AREF/TEXT/BOX), ≥1 drawn layer.

**C. Design-derived floor** — **no per-design constants anywhere.** The
placed-instance count is read from the design's *own* `phase3/stage3/pnr/
routed.def` (`COMPONENTS <n> ;`); the GDS must carry ≥ `n × 1.0` layout
elements. No DEF → floor skipped and reported as skipped; structure and
substance still apply. `VACUOUS_PASS` before stream-out.

Calibration is measured, not guessed — elements per placed instance on the
three committed converged cells:

| cell | elements / instances | ratio |
|---|---|---|
| v1.5.58_ihp-sg13g2 | 11583 / 1826 | 6.34 |
| v1.5.65_sky130A | 8848 / 558 | 15.86 |
| v1.5.66_gf180mcuD | 13337 / 2007 | 6.65 |

Default `1.0` sits **6.3× below the tightest real point**. Placement records
alone already track the DEF almost exactly (SREF 1826/1826, 558/558; gf180
2145 SREF + 170 AREF for 2007 instances) — the headroom is BOUNDARY geometry,
which is why the ratio tolerates hierarchy-vs-flattening differences between
PDKs instead of policing them.

**Wired in two places** (mirroring how the existing GDS gates are wired):

1. `flow/phase1_phase2_phase3.yaml` step 37 `gate.all_of` — blocks the step
   that produces the GDS.
2. `programs/flow_compliance_check.py` gate registry, next to
   `chip_gds_canonical_real_file_check` — project-level audit. It is
   `VACUOUS_PASS`-friendly, which is that list's stated admission criterion.

`programs/INDEX.md` regenerated via `tools/gen_programs_index.py` (the
freshness CI test diffs it, so this is required, not cosmetic).

---

## 4. Negative control

`programs/tests/test_gds_substance_check.py` — **19 tests, all passing.**

The negative controls assert **both halves**, so they cannot silently become
tautologies:

- `test_negative_control_new_gate_fails` — each of the 4 fakes must produce
  findings, with the expected category, and **every finding must be severity
  ERROR** (a warning would not block).
- `test_negative_control_old_gate_passed_these` — pins the defect by calling
  `gds_size_check.audit_gds()` directly and asserting the 3 oversized fakes
  **pass** the pre-fix code. If this test ever goes red, `gds_size_check`
  gained real structural checking and this gate's justification should be
  re-examined.
- `test_86_byte_stub_was_already_caught_by_size_gate` — records the honest
  scoping from §1: the 86-byte case was never the hole.
- `test_floor_is_derived_not_hardcoded` — same GDS passes at 300 instances,
  fails at 5000. The floor tracks the design, not a constant.

**End-to-end through the real acceptance gate** (`flow_compliance_check.py`,
i.e. the report the gate actually reads — not the fix's own numbers):

| fixture | Step 37 before | Step 37 after |
|---|---|---|
| real 822,084 B GDS | ✓ PASS | ✓ PASS |
| 150 KB random bytes | ✓ PASS | **✗ FAIL** `MALFORMED_RECORD` |
| 150 KB empty library | ✓ PASS | **✗ FAIL** `TRAILING_GARBAGE` + `NO_STRUCTURES` + `NO_GEOMETRY` + `SUBSTANCE_BELOW_DESIGN_FLOOR` |
| 150 KB even-length junk | ✓ PASS | **✗ FAIL** `NO_ENDLIB` |
| 86-byte stub | ✗ FAIL | ✗ FAIL |

---

## 5. Corpus sweep — no false positives

**Required 3 committed converged spm cells — all PASS:**

```
rc=0 v1.5.58_ihp-sg13g2 :: PASS — 28 structures, 11583 elements, 19 layers, floor 1826 (from 1826 placed instances)
rc=0 v1.5.65_sky130A    :: PASS — 36 structures,  8848 elements, 17 layers, floor  558 (from  558 placed instances)
rc=0 v1.5.66_gf180mcuD  :: PASS — 42 structures, 13337 elements, 19 layers, floor 2007 (from 2007 placed instances)
```

**Widened to every run on 192.168.1.120 with a canonical chip GDS — 35
projects, zero false positives:**

- 4 designs: `spm`, `caravel_user_project`, `sha256`, `opentitan_aes`
- 4 PDKs: `sky130A`, `ihp-sg13g2`, `gf180mcuD`, `nangate45`
- scale 558 → 134,748 placed instances; 8,648 → 1,555,181 elements
- every pre-stream-out project correctly returned `VACUOUS_PASS`
- **`campaign_v1574/spm/converge_1.5.74_ihp-sg13g2` itself PASSES** — the run
  under investigation clears the new gate, consistent with §1

---

## 6. Reproduce

```bash
cd /home/reyerchu/vibe-ic-wt-gdssubstance/vibe-ic-marketplace/plugins/vibe-ic

# unit + negative control
python3 -m pytest programs/tests/test_gds_substance_check.py -q     # 19 passed

# corpus (non-mutating: no --json, writes nothing)
cd /home/reyerchu/vibe-ic-wt-gdssubstance
for c in v1.5.58_ihp-sg13g2 v1.5.65_sky130A v1.5.66_gf180mcuD; do
  python3 vibe-ic-marketplace/plugins/vibe-ic/programs/gds_substance_check.py \
    benchmark-data/ic/spm/$c
done
```

> Note for whoever reruns this: `flow_compliance_check.py <project>` **writes
> report JSONs into the project tree**. Running it against
> `benchmark-data/ic/spm/*` dirties 39 committed golden files. It happened
> during this investigation and was reverted with `git checkout --
> benchmark-data/`; `git diff origin/main -- benchmark-data/` is 0 lines in
> the delivered commit. Use a `/tmp` copy for gate experiments.

---

## 7. Gate results

- New suite: **19 passed**
  (`pytest programs/tests/test_gds_substance_check.py`).
- Related subset (`-k "gds or flow_compliance or index or substance or
  symlink"`): **444 passed, 6 skipped, 2 failed**.

Both failures are in `test_gds_geometry_signoff_wiring.py` and **neither is
caused by this change**:

| test | status |
|---|---|
| `test_density_fill_raises_a_sparse_layer_to_target` | **pre-existing red on main.** Fails identically on the pristine `1.5.79` plugin cache (density fill target not reached on every layer; foundry CMP floor not met). |
| `test_geometry_deck_catches_what_the_router_report_path_misses` | **order-dependent, not mine.** Passes in isolation in this worktree — `pytest programs/tests/test_gds_geometry_signoff_wiring.py` gives `1 failed, 22 passed` in BOTH this worktree and the pristine cache, byte-identical. These tests share a `vibe-ic-marketplace/scratch_geom_signoff_tests/` scratch dir, so they interfere when run in a larger selection. |

Worth a separate ticket for the gatekeeper — both are latent reds on main and
neither is in this change's blast radius (this change touches no geometry,
density, or router code).

## 8. Files changed

```
 M vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml   (+10)
 M vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py (+14)
 M vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md                (regenerated)
 A vibe-ic-marketplace/plugins/vibe-ic/programs/gds_substance_check.py
 A vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_gds_substance_check.py
```

`benchmark-data/` untouched. No RTL changed, so no synth/netlist re-run
question arises. No synthesis knob touched, so no pre-PnR-vs-shipped-SPEF
judgement is involved. Design INPUT only was read; no oracle/golden consulted
(§4.05).
