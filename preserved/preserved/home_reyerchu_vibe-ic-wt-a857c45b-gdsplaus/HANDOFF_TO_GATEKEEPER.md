# HANDOFF — GDS deliverable plausibility gate + canonical-GDS staleness fix

| | |
|---|---|
| Worktree | `/home/reyerchu/vibe-ic-wt-a857c45b-gdsplaus` |
| Branch | `fix/a857c45b-gds-plausibility` |
| Base | `origin/main` @ `0d2c63d34` (plugin 1.5.78) |
| Commits | `b03a2e795` (gate) · `763f06ff2` (root cause) |
| Pushed | **No.** Local worktree only, per instruction. |
| Version bump | **None applied.** The gatekeeper assigns the monotonic version at THEIR land time. `plugin.json` / `marketplace.json` are untouched. |

The two commits are independently landable. `b03a2e795` is the requested
deliverable and stands alone. `763f06ff2` fixes the root cause the gate's
corpus sweep exposed; drop it without affecting the gate if you prefer to
decide that separately.

---

## 1. What actually happened in the reported run

Run: `192.168.1.120:~/campaign_v1574/spm/converge_1.5.74_ihp-sg13g2`,
plugin cache 1.5.74 (verified present on the host; its `gds_size_check.py`
is v1.1.0 with `severity="WARNING"` and `min_size_kb: float = 100.0`, and
`gds_deliverable_plausibility_check.py` is absent — the pre-fix code is
what ran).

**The 86-byte GDS was a symlink, not an empty artefact.**

```
$ ls -l  steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds
lrwxrwxrwx 1 reyerchu reyerchu 86 ... -> …/phase3/stage4/gds/spm.gds
$ ls -lL steps/37_gdsii_output_only_if_step_31_pv_fully_clean/spm.gds
-rw-rw-r-- 1 reyerchu reyerchu 822084 ...
```

`ls -l` on a symlink prints the length of the target path string. That
path is 86 characters. Every artefact under `steps/<N>_*/` is such a link
(`netlist.v` 90, `routed.def` 89, `spm.v` 84, …), so the whole class reads
as tiny under `ls -l`. `find -printf '%y'` reports `l` for all of them.

The resolved file is a genuine layout: parses clean as a GDSII record
stream, ENDLIB present, 28 structures, 11,583 elements, 1,826 SREF
placements against a `routed.def` that declares `COMPONENTS 1826`, 19
layers.

**169 s (the orchestrator's own number; the 198 s was wall clock) is not
too fast for this design.** Measured step time:

```
phase3.pnr                     85.6s      phase2 TOTAL   13.0s / 26 steps
phase3.gds                      7.6s      phase3 TOTAL  110.9s
phase3.drc                     15.2s      orchestrator  169.2s
phase3.lvs                      1.9s
phase3.synth                    0.0s  (self-disclosed reuse)
```

The design places 352 logic instances (1,826 DEF components including
fill / tap / spare). 85.6 s of OpenROAD PnR on that is ordinary. The
balance of the 169 s is orchestration and the gate subprocesses.

Two reuses occurred, both self-disclosed in the run's own output: phase1
`SKIPPED`, and phase3 `synth PASS — netlist already present:
spm_synth.v (skipped re-run to preserve provenance)`. Neither is silent.

**The DFT evidence is genuine and belongs to this run.** The run window is
12:29:06 → 12:31:55. `phase2/stage2/dft/tdf/_tdf_cal.ys` is 12:29:17 and
`reports/phase2/dft/transition_coverage_gate.json` (scan_flops 65,
tdf_fault_coverage_pct 40.5) is 12:31:54 — both inside it.

**But one thing in the report was right for a reason nobody had found
yet.** 246 files were written inside the run window; 217 predate it, left
by an earlier attempt in the same directory. The shipped deliverable is
one of the 217:

```
phase3/stage4/gds/spm.gds    822,084 B  12:25:18   <- SHIPPED (earlier attempt)
phase3/stage3/pnr/spm.gds    822,084 B  12:31:31   <- this run's stream-out
```

The deliverable is not the artefact this run produced and verified. Here
it was harmless — the re-run reproduced an identical layout and the two
streams differ in 116 bytes, all embedded GDSII header timestamps
(`cmp -l` shows only minute/second fields). The mechanism is not harmless;
see §4.

---

## 2. The gate defect (the deliverable)

`gds_size_check` v1.1.0, the gate wired at flow Step 37, had **one** fatal
criterion: a hardcoded 100 KB byte floor. Its GDSII-format check was a
`WARNING`, which cannot fail a gate. Measured against `origin/main`:

| fixture | v1.1.0 exit | findings |
|---|---|---|
| 150 KB of `0x00` | **0** | 1 warning |
| a tool error log renamed `.gds` | **0** | 1 warning |
| 4 valid header bytes + 150 KB garbage | **0** | **0** |
| 86-byte real file | 1 | TOO_SMALL |

So any blob at or above the floor passed sign-off as a GDS. And one byte
count cannot be right for two designs of different size: too high for a
small design (false FAIL), far too low for a large one — a 120 KB stub
clears 100 KB whether the design places 20 instances or 200,000.

---

## 3. The guard

`plugins/vibe-ic/programs/gds_deliverable_plausibility_check.py` — chip-
AGNOSTIC, pure Python, no external tool, no vendor/SKU/PDK/IC literal in
any decision. `source_chip_agnostic_check` PASS.

**Structural** (every canonical GDS; hard FAIL): walks the record stream —
`NOT_A_GDS`, `GDS_MALFORMED`, `GDS_TRUNCATED`, `GDS_NO_ENDLIB`,
`GDS_NO_STRUCTURE`, `GDS_NO_GEOMETRY`, `GDS_NO_LAYER`.

**Design-derived** (chip deliverable; hard FAIL) — the size expectation
comes from the design's own `COMPONENTS` count in its own DEF, never from
a per-design constant:

* `GDS_PLACEMENT_SHORTFALL` — SREF + every AREF's `cols × rows` (or
  BOUNDARY count for a flattened stream) must reach ≥ 50% of the DEF's
  instances. Observed on real layouts: **1.00 / 1.00 / 4.98**, and 1.00 on
  a 141,863-instance SoC. 0.5 is a 2× margin.
* `GDS_BELOW_DESIGN_FLOOR` — `instances × 16` bytes. **16 is a property of
  the GDSII record format, not of a design**: the cheapest legal
  per-instance encoding is SREF(4) + SNAME(≥6) + XY(12) + ENDEL(4) ≈ 28
  bytes. Observed ratios on real layouts: **450 / 588 / 798 / 1309** bytes
  per instance — a 28×–82× margin. Skipped, with a stated reason, for an
  array-dominated stream (an AREF can place many instances cheaply);
  placement coverage governs there.
* `DEF_ZERO_COMPONENTS` — a placement of 0 instances cannot back a PASS.

**Symlink transparency.** The report carries both `apparent_size_bytes`
(lstat) and `size_bytes` (stat) plus an explicit `DELIVERABLE_IS_SYMLINK`
note, so the misreading that produced this investigation cannot be
re-derived from the gate's own output. Whether a symlink is *allowed* at a
canonical path stays `chip_gds_canonical_real_file_check`'s call.

**Fail-closed details.** A broken symlink is a candidate (not `is_file()`,
so a naive glob would have dropped it into VACUOUS_PASS — the worst
outcome for a substance gate). DEF selection prefers the DEF whose
`DESIGN` name matches the chip GDS stem, so a macro's DEF cannot supply
the instance count for a different design. VACUOUS_PASS (rc 2) only when
no canonical GDS exists at all.

**Also fixed:** `gds_size_check` v1.2.0 — `INVALID_GDS_FORMAT` is now an
`ERROR`. It keeps its role as the absolute backstop.

**Wiring:** flow Step 37 `all_of` (hard gate, alongside the existing size
check), universal gate list in `flow_compliance_check.py`,
`_path_layout.py`, `INDEX.md`. `plugin_full_audit` PASS (D1 + D2).

---

## 4. Root cause (second commit — separately landable)

`phase3_one_shot_runner.step_canonicalize_artefacts` staged the canonical
deliverable behind an existence-only guard:

```python
if not canon_gds.is_file():
```

On any resume / re-run / warm-started tree the copy was skipped, so the
deliverable kept its old contents while the verified layout went only to
`phase3/stage3/pnr/`. Found by the new gate's corpus sweep —
subservient × sky130A, plugin 1.5.50:

```
phase3/stage4/gds/<top>.gds          3,067,904 B  03:25:56   <- SHIPPED
phase3/stage3/pnr/<top>.gds         21,511,808 B  04:02:01   <- verified
phase3/stage4/foundry_handoff/….gds 31,185,462 B  04:01:57
```

The shipped file is a page-aligned truncation (exactly 749 × 4096), with
**zero ENDLIB records anywhere in it**, 13 of the layout's 18 layers and
40,502 of its 479,814 elements (~8%). Its last bytes stop inside a cell
name. `gds_size_check` v1.1.0 recorded `"pass": true,
"findings_count": 0` on it. The same run's `gds` step reported PASS
quoting `size=21511808` — a number matching no file at the canonical path.

The fix refreshes when this run's stream-out is newer. This runner is the
**only writer** of `phase3/stage4/gds/<top>.gds` (every other reference in
the plugin is a reader), so a refresh cannot clobber another producer's
artefact. A newer-or-equal staged copy is left alone; first write is
unchanged. The decision lives in `_canonical_gds_is_stale` so the test
calls the real helper rather than mirroring it (the drift class of
ORGANIC #592).

---

## 5. Gate results

| check | result |
|---|---|
| `source_chip_agnostic_check` (plugin root) | **PASS** |
| `plugin_full_audit` D1 + D2 | **PASS** (940 programs) |
| flow YAML parses; Step 37 gate resolves | **PASS** |
| universal gate wiring resolves | **PASS** |
| `agent_checkin_scope_guard --role core-agent --base origin/main` | **PASS** — all 10 paths in scope |
| full plugin suite, CI way (`pytest -q --maxfail=20 --timeout=300`) | **SEE §5.1** |

Note: this environment needs `-p no:pytest_ethereum`; a broken `web3`
entry-point plugin in the user site-packages aborts collection otherwise.
Unrelated to this change.

### 5.1 Negative control — fails against unfixed code

`TestInvalidFormatIsFatal` run against `origin/main`'s `gds_size_check.py`
v1.1.0 (extracted with `git show`, tests unchanged):

```
4 failed, 11 passed
  test_zero_blob_above_floor_is_error
  test_renamed_text_log_is_error
  test_cli_exit_1_for_non_gds[zero_blob]
  test_cli_exit_1_for_non_gds[renamed_error_log]
```

Post-fix: all pass. Additionally every fixture in `TestNegativeControl`
asserts the **pre-fix gate's exit code explicitly** (`run_prefix_size_gate
(...) == 0`), so a fixture that stops reproducing the false PASS fails the
test rather than silently degrading into a restatement of current
behaviour.

### 5.2 Corpus sweep — 23 trees, zero false positives

| set | trees | result |
|---|---|---|
| `benchmark-data/ic/spm` — `v1.5.58_ihp-sg13g2`, `v1.5.65_sky130A`, `v1.5.66_gf180mcuD` | 3 | **3 PASS** |
| local host, campaign run dirs | 2 | 2 PASS |
| 8HD-4, campaign run dirs | 7 | 7 PASS |
| 8HD-d, campaign run dirs (mixed designs / PDKs, incl. a 113 MB / 141,863-instance SoC) | 11 | 10 PASS, **1 FAIL** |

The single FAIL is the genuine truncated deliverable in §4, not a
misfire. Runtime 7 s on the 113 MB case — inside the 60 s universal-gate
budget and far inside the 900 s flow-gate budget.

The three named reference cells report:

```
v1.5.58_ihp-sg13g2  822,084 B  1,826 inst  450.2 B/inst  cov 1.00  28 struct  11,583 elem  19 layers
v1.5.65_sky130A     730,458 B    558 inst 1309.1 B/inst  cov 1.00  36 struct   8,848 elem  17 layers
v1.5.66_gf180mcuD 1,180,456 B  2,007 inst  588.2 B/inst  cov 4.98  42 struct  13,337 elem  19 layers
```

---

## 6. For the reviewer to weigh

1. **Deliberate contract change.** `gds_size_check`'s passing fixtures used
   `b'\x00' * N`, i.e. the suite asserted *as expected behaviour* that
   200 KB of zeros is an acceptable sign-off GDS. They now open with a real
   HEADER record. The size logic under test is unchanged; what is gone is
   the certification of a non-GDS blob. Flagging it explicitly because it
   is a test-expectation change, not just an addition.

2. **The array-dominated escape hatch** in the byte floor is a deliberate
   soundness choice (an AREF legitimately places many instances in few
   bytes). Placement coverage still applies there, and it counts AREFs by
   their full `cols × rows` expansion.

3. **Residual, not fixed:** `gds_size_check`'s 100 KB floor can still
   false-FAIL a legitimately tiny design. Lowering it would weaken a gate,
   and the new gate now carries the design-derived floor, so I left the
   backstop fail-closed rather than tune it in a bounded task.

4. **Not fixed, reported:** `phase3/stage4/foundry_handoff/<top>.gds` is a
   different byte stream from the shipped GDS in every run I inspected —
   in the spm run, 964,702 B / 14,711 elements / GDS version 3 with epoch
   timestamps, versus the shipped 822,084 B / 11,583 elements / version 6,
   i.e. the pre-grid-snap stream-out. Same placement count, so the guard
   correctly does not fire, but the foundry package and the DRC-verified
   file are not the same bytes. Worth its own investigation.

5. **Incidental:** `plugins/vibe-ic/programs/tests/test_gds_geometry_signoff_wiring.py`
   writes `vibe-ic-marketplace/scratch_geom_signoff_tests/` into the repo
   tree on every run. Pre-existing, untouched here, not committed.
