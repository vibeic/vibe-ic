# The LVS family (8 IDs) re-measured — one cause, already fixed, and the guard still bites

Slice: the eight LVS-adjacent IDs listed BOTH (red in the pinned CI image AND on
the host, 5/5 in each lane) in
`docs/research/2026-08-21-main-92-red-triage-ratios.md`.

**Result: all eight are GREEN at `ae5cc4dbf` (v1.11.96), in BOTH lanes.** They
were real when the ratios table was taken — the ratios table was taken against
`867de4289` (v1.11.18) — and they were closed by `d3dce649b` (v1.11.43) later
the same day. The rows in the ratios table are stale, not wrong.

---

## 1. The one root cause behind all eight

The three modules share a `_fake_docker` stub. Its `magic ... ext2spice` branch
wrote the extracted netlist and nothing else:

```python
if "magic" in cmd and "SPICE_OUT=" in cmd:
    Path(m.group(1)).write_text(spice_body)     # netlist only
    return (0, "MAGIC_EXT2SPICE_DONE", "")
```

Real Magic does more than that. The extraction recipe ends
`feedback save $env(FEEDBACK_OUT)`, and Magic writes that file — 0 bytes when
`feedback count` is 0. So the stub modelled an extraction that cannot happen:
one whose error channel was never dumped at all.

`step_lvs` grew a pre-netgen gate, `magic_illegal_overlap_check`, whose whole
point is that **an absent feedback file is not a measured zero, it is an
unmeasured nothing**. Against the old stub that gate correctly refused, and
every one of the eight IDs died at the same place, before netgen was ever
reached. Verbatim, from the re-run at `867de4289`:

```
AssertionError: ('FAIL', 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT:
an extraction RAN for this project (evidence: chip_top_extracted.sp,
ext2spice_chip_top.tcl) but under phase3/stage3/extracted none of
extract_feedback.txt, fee (see reports/phase3/magic_illegal_overlap.json)')
```

The eight assertions that fell out of that single abort:

| ID | what it asked | what it got |
|---|---|---|
| `test_v0_2_77::test_lvs_runs_and_passes_on_match` | `PASS` | `FAIL` |
| `test_v0_2_77::test_lvs_fails_on_real_mismatch` | `"real compare ran"` in detail | `LVS aborted before netgen` |
| `test_v0_2_97::test_clean_complete_lvs_still_passes` | `PASS` | `FAIL` |
| `test_v0_2_97::test_real_mismatch_still_fails_as_conclusive` | `LVS_MISMATCH` | `LVS_EXTRACTION_ILLEGAL_OVERLAP` |
| `test_v0_2_97::test_truncated_verdict_less_report_is_incomplete_fail` | `LVS_NO_TERMINAL_VERDICT` | `LVS_EXTRACTION_ILLEGAL_OVERLAP` |
| `test_v0_2_97::test_small_ext2spice_error_count_is_warning_not_fail` | warning, not fail | `FAIL` |
| `test_v0_3_24::test_runner_pin_fail_is_conclusive_mismatch_not_incomplete` | `LVS_MISMATCH` | `LVS_EXTRACTION_ILLEGAL_OVERLAP` |
| `test_v0_3_24::test_runner_truncated_still_incomplete` | `LVS_NO_TERMINAL_VERDICT` | `LVS_EXTRACTION_ILLEGAL_OVERLAP` |

This is exactly the shared invariant the slice was expected to have: **an LVS
verdict that could not be computed must never read as a pass.** The gate was
right. The stub was the thing that had stopped modelling reality.

`d3dce649b` fixed the stub — in all three modules — by having the fake `magic`
also write `FEEDBACK_OUT`, as real Magic does. No assertion was weakened, no
case deleted, no `skipif` added, no tolerance widened.

## 2. Measured

Independent clone, `git clean -xdfq`, `PYTHONDONTWRITEBYTECODE=1`,
`TMPDIR` outside the account home, `VIBEIC_TRUSTED_PYTEST_SITE=auto`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, one `python3 -m pytest` per module, serially,
no xdist — the ratios table's own methodology.

```
subject   ae5cc4dbf  (v1.11.96)   TREE_SHA 954bc27704cb7d12cf7ba5c0fc4a348b6898ec3b
control   867de4289  (v1.11.18)   TREE_SHA 7840974874537d10d0952057f06857f4b699ec38
image     ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…d01ff  (--skip first)
```

| run | lane | subject | result |
|---|---|---|---|
| the 8 IDs | host | `ae5cc4dbf` | **8 passed** |
| the 8 IDs | image | `ae5cc4dbf` | **8 passed** |
| the 8 IDs | host | `867de4289` | **8 failed** (control) |
| `test_v0_2_77_lvs_reachable.py` (whole) | host | `ae5cc4dbf` | 5 passed |
| `test_v0_2_97_issue477_lvs_incomplete.py` (whole) | host | `ae5cc4dbf` | 9 passed |
| `test_v0_3_24_issue524_lvs_pin_matching_verdict.py` (whole) | host | `ae5cc4dbf` | 22 passed, 1 skipped |
| `test_magic_illegal_overlap_check.py` (whole) | host | `ae5cc4dbf` | 26 passed, 1 skipped |
| `test_v0_2_77_lvs_reachable.py` (whole) | image | `ae5cc4dbf` | 5 passed |
| `test_v0_2_97_issue477_lvs_incomplete.py` (whole) | image | `ae5cc4dbf` | 9 passed |
| `test_v0_3_24_issue524_lvs_pin_matching_verdict.py` (whole) | image | `ae5cc4dbf` | 22 passed, 1 skipped |
| `test_magic_illegal_overlap_check.py` (whole) | image | `ae5cc4dbf` | **27 passed, 0 skipped** |

The two host skips are the real-tool arms
(`test_real_on_host_pin_fail_report_classifies_mismatch`,
`test_real_magic_writes_a_dump_this_parser_reads`); neither is one of the eight.
In the image `test_real_magic_writes_a_dump_this_parser_reads` is not skipped and
passes — real Magic is there, and it does write the dump this parser reads. So the
premise the stub repair rests on is not asserted from the docstring; it is measured
against the tool, in the lane that has it.

## 3. Both directions

A green obtained by removing the thing that used to say no is not a green. So
the direction that must still go RED was constructed at `ae5cc4dbf` — the only
edit being the removal of the `FEEDBACK_OUT` write that `d3dce649b` added:

```
programs/tests/test_v0_2_77_lvs_reachable.py
-            _fb = _re.search(r"FEEDBACK_OUT=(\S+)", cmd)
-            if _fb:
-                Path(_fb.group(1)).parent.mkdir(parents=True, exist_ok=True)
-                Path(_fb.group(1)).write_text("")
```

```
2 failed, 3 passed in 0.87s
FAILED test_v0_2_77_lvs_reachable.py::test_lvs_runs_and_passes_on_match
FAILED test_v0_2_77_lvs_reachable.py::test_lvs_fails_on_real_mismatch
E  AssertionError: assert 'real compare ran' in 'LVS aborted before netgen:
   EXTRACTION_FEEDBACK_ABSENT: …'
```

The gate is live at head: hide the feedback channel and LVS still refuses to
produce a verdict, at the same place, with the same finding. The three tests in
that module that never reach extraction stayed green, so the refusal is
targeted rather than blanket.

The product-side invariant has its own owner, and it is green and not vacuous:
`test_magic_illegal_overlap_check.py::test_absent_feedback_is_not_a_measured_zero`
(feedback absent → `passed False`, `skipped False`, rule
`EXTRACTION_FEEDBACK_ABSENT`, `RC_FAIL`) and
`test_a_project_with_neither_an_extraction_nor_an_lvs_verdict_is_vacuous`
(the genuine no-run case is still rc 2, so "evidence" has not crept until every
empty directory FAILs).

## 4. What this does not claim

Only these eight IDs were driven to a verdict. The other rows of the ratios
table were not re-measured here and are not spoken for — with one exception,
recorded because it shares this exact cause and cost nothing to measure.

`test_extraction_input_blocked_verdict.py` carries the same `FEEDBACK_OUT` stub
repair from the same commit. Its four BOTH-listed IDs
(`test_complete_generic_tech_still_passes_end_to_end`,
`test_complete_tech_passes_with_real_tech_lef_layer_crosscheck`,
`test_complete_tech_with_matching_design_still_passes`,
`test_unreadable_tech_does_not_block`) measured GREEN at `ae5cc4dbf` in both
lanes — whole module 51 passed / 2 skipped on host and 51 passed / 2 skipped in
the image, and the four named IDs 4 passed in each. Their rows are left in BOTH
for the slice that owns them; the measurement is stated here so that slice does
not have to rediscover it.

Not measured here, by name: every other row of the ratios table, the 35 `1.6x`
matrix IDs, and the two FLAKY IDs.
