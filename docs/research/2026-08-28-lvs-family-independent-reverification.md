# The LVS family (8 IDs) — independent re-verification, second observer

Second, independent measurement of the same eight LVS-adjacent IDs that
`docs/research/2026-08-27-lvs-family-remeasured-at-v1-11-96.md` cleared. Taken by
a different session on a different fleet host, against the same live `main`,
without reusing any artefact of the first pass: a fresh `--no-local` clone (no
borrowed objects, no alternates), `git clean -xdfq`, its own control clone, and
its own constructed violations.

**Result: the first pass holds.** All eight are GREEN at `ae5cc4dbf` in both
lanes, on every observation. The ledger rows were stale, not wrong — and the
guard that produced the original red is still live and still bites, in two
independent directions.

```
subject   ae5cc4dbf  (v1.11.96)   TREE_SHA 954bc27704cb7d12cf7ba5c0fc4a348b6898ec3b
control   867de4289  (v1.11.18)   TREE_SHA 7840974874537d10d0952057f06857f4b699ec38
host      8HD-8 (192.168.1.114)
image     ghcr.io/vibeic/vibeic-eda:latest  (entrypoint bypassed; USER=designer)
env       PYTHONDONTWRITEBYTECODE=1 · TMPDIR outside the account home ·
          VIBEIC_TRUSTED_PYTEST_SITE=auto · PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ·
          VIBEIC_CORPUS_ROOT UNSET · one `python3 -m pytest` per lane, serial, no xdist
```

## 1. Head — the eight are green, repeatedly, in both lanes

Whole modules, never a `-k` selection, so a paired guard cannot hide behind a
narrow node set.

| lane | run | subject | result |
|---|---|---|---|
| host | 1 | `ae5cc4dbf` | 36 passed, 1 skipped (123.89s) |
| host | 2 | `ae5cc4dbf` | 36 passed, 1 skipped (123.75s) |
| host | 3 | `ae5cc4dbf` | 36 passed, 1 skipped (123.78s) |
| image | 1 | `ae5cc4dbf` | 36 passed, 1 skipped (124.83s) |
| image | 2 | `ae5cc4dbf` | 36 passed, 1 skipped (124.97s) |

All 37 collected nodes are accounted for in every run: 36 passed and one skip,
`test_v0_3_24::test_real_on_host_pin_fail_report_classifies_mismatch`, which is
corpus-bound (`VIBEIC_CORPUS_ROOT` unset) and is not one of the eight. Per
module at head: `test_v0_2_77` 5 passed, `test_v0_2_97` 9 passed, `test_v0_3_24`
22 passed / 1 skipped.

**Red ratio for each of the eight IDs: image 0/2, host 0/3.**

## 2. The control — the harness CAN produce this red

A harness that cannot go red proves nothing, so the same command was run against
the ratios table's own subject, `867de4289`, in a separate clone:

| lane | subject | result |
|---|---|---|
| host | `867de4289` | **8 failed**, 28 passed, 1 skipped |
| image | `867de4289` | **8 failed**, 28 passed, 1 skipped |

The failing set is **exactly the eight IDs of this slice** — not a superset, not
a subset — in both lanes. The ratios table's `BOTH 5/5 5/5` was a true
measurement of its own subject; the first pass's reading of it is confirmed
rather than taken on trust. Verbatim:

```
AssertionError: ('FAIL', 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT:
an extraction RAN for this project (evidence: chip_top_extracted.sp, …) but under
phase3/stage3/extracted none of extract_feedback.txt, fee
(see reports/phase3/magic_illegal_overlap.json)')
assert 'FAIL' == 'PASS'
```

## 3. Both directions, twice

### V1 — hide the extraction's error channel

At `ae5cc4dbf`, the only edit being removal of the `FEEDBACK_OUT` write that
`d3dce649b` added, in all three modules:

```python
-            _fb = _re.search(r"FEEDBACK_OUT=(\S+)", cmd)
-            if _fb:
-                Path(_fb.group(1)).parent.mkdir(parents=True, exist_ok=True)
-                Path(_fb.group(1)).write_text("")
```

| lane | result |
|---|---|
| host | **8 failed**, 28 passed, 1 skipped |
| image | **8 failed**, 28 passed, 1 skipped |

Same eight IDs, same `EXTRACTION_FEEDBACK_ABSENT` finding, same abort point
before netgen. The other 28 tests stay green, so the refusal is targeted and not
a blanket one.

### V2 — dump the channel, and put a real defect in it

V1 only shows the gate refuses an *unmeasured* channel. A gate that refuses
everything is not a check either, so the opposite input was constructed: an
extraction whose feedback file **is** written and carries two real
`Illegal overlap` records, with netgen then reporting `Circuits match uniquely`.
A `PASS` here would be the dangerous verdict — a layout defect signed off by a
clean compare.

| lane | `step_lvs` status | finding |
|---|---|---|
| host | `FAIL` | `LVS_EXTRACTION_ILLEGAL_OVERLAP` |
| image | `FAIL` | `LVS_EXTRACTION_ILLEGAL_OVERLAP` |

```
LVS aborted before netgen: MAGIC_ILLEGAL_OVERLAP: the extractor reported 2
illegal overlap(s), against a threshold of 0. Counted from: feedback dump
string=2 structural=0 (0 area(s)), transcript=0 — the verdict; …
```

So at head the gate distinguishes three states and refuses two of them: channel
absent → `EXTRACTION_FEEDBACK_ABSENT`, channel present and dirty →
`MAGIC_ILLEGAL_OVERLAP`, channel present and empty → the extraction is a measured
zero and LVS proceeds to netgen. That is the slice's shared invariant intact: an
LVS verdict that could not be computed never reads as a pass.

## 4. The repair is faithful to the tool, not to the test

The stub change is only legitimate if real Magic really does write that file.
Two independent confirmations, neither of them a docstring:

* **The command the runner actually emits.** `FEEDBACK_OUT=` is exported
  unconditionally in the `magic … ext2spice` invocation
  (`phase3_one_shot_runner.py:30082`), and the recipe ends
  `feedback save $env(FEEDBACK_OUT)` (`phase3_one_shot_runner.py:28871`,
  `lvs_power_aware_extract_tcl.py:333`). The repaired stub models the real
  command's contract; the old stub modelled a command that is never issued.
* **The tool itself.**
  `test_magic_illegal_overlap_check.py::test_real_magic_writes_a_dump_this_parser_reads`
  drives the actual binary and asserts `feedback save` with zero areas **creates**
  the file and that it is empty. Measured here:

| module | lane | result |
|---|---|---|
| `test_magic_illegal_overlap_check.py` | host | 26 passed, 1 skipped (`magic` not on PATH) |
| `test_magic_illegal_overlap_check.py` | image | **27 passed, 0 skipped** — the real-tool arm runs and passes |

Absent and empty are therefore genuinely different states of the world, measured
against Magic in the lane that has it, and the gate is right to treat them
differently.

## 5. What this does not claim

Only these eight IDs were driven to a verdict here. Not measured in this pass, by
name: every other row of the ratios table, the 35 `1.6x` matrix IDs, the two
FLAKY IDs, and the four `test_extraction_input_blocked_verdict.py` IDs that the
first pass measured green but deliberately left in `BOTH` for the slice that owns
them — this pass did not re-measure them either and does not speak for them.

The corpus-bound skip named in §1 was not resolved: `VIBEIC_CORPUS_ROOT` was left
unset deliberately, since the published benchmark cells were withdrawn on
2026-08-20. That ID is not one of the eight and its state is unchanged by this
work.
