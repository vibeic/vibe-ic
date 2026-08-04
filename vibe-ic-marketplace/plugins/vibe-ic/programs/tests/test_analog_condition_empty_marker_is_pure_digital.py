#!/usr/bin/env python3
"""An EMPTY analog block-list marker must read as PURE-DIGITAL, not analog.

The defect
----------
`stage_analog` (A1..A9) and `stage_mixed_signal` (M1..M4) fire only when the
step `condition` `files_exist:["phase1/analog/analog_block_list.json"]` is met,
evaluated by `flow_compliance_check._check_condition`. A pure-digital design is
supposed to leave that stage SKIPPED-CONDITION — the flow-def itself says
"SKIP if no analog_block_list.json (pure digital)".

`_check_condition` used to satisfy the analog condition on the mere EXISTENCE of
a block-list file:

    for pat in files:
        if _glob_first(project, pat):     # <-- existence short-circuit
            continue
        if "analog_block_list" in pat:
            ... content-aware helpers only reached when the glob MISSES ...

`_glob_first` carries a canonical-analog-dir tolerance (v0.2.55): when a
`phase1/analog/<x>` pattern misses, it re-probes `<_pl.analog_dir>/<x>`
(i.e. `phase3/analog/<x>`). So an EMPTY `phase3/analog/analog_block_list.json`
— `{"blocks": []}`, which explicitly declares NO analog blocks — is matched by
existence, the loop `continue`s, and the analog track is marked APPLICABLE off
a marker that says the opposite. Every A-step then reports MISSING and voids
every downstream physical step declaring `blocks_on:[A*]` (15..31): a converged
pure-digital backend renders as a wall of PASS-VOIDED. This is the
measured-something-ADJACENT-to-the-question failure class: the condition
measured "does a file named analog_block_list.json exist" instead of "does this
design have analog blocks".

`_has_canonical_analog_blocks` was ALREADY the content-aware source of truth for
"does this project have analog blocks" (it requires a non-empty `blocks[]` and
honours `L5.no_analog`, and is what `_project_is_pure_analog` /
`_digital_backend_is_na` consult). The fix makes `_check_condition` consult
CONTENT the same way for the `analog_block_list` pattern, so an empty marker no
longer differs from an absent one, while the L9 `analog_modules` auto-trigger
(v0.113) is preserved.

Bidirectional control: `test_empty_marker_reads_pure_digital` FAILs against the
byte-identical pre-fix file (existence short-circuit -> True) and PASSes after;
`test_nonempty_marker_is_still_analog` and `test_l9_analog_modules_still_trigger`
STILL PASS both ways, proving the fix did not tighten the trigger into a filter
that swallows genuine analog designs. chip-AGNOSTIC — no chip/PDK literal.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import flow_compliance_check as fcc            # noqa: E402

# The condition every A-step and M-step carries in the flow-def.
_ANALOG_COND = {"files_exist": ["phase1/analog/analog_block_list.json"]}


def _digital_project(tmp_path: Path) -> Path:
    """A pure-digital project: real RTL, L5.no_analog, no L9 analog modules."""
    proj = tmp_path / "proj"
    (proj / "phase2/stage1/rtl").mkdir(parents=True)
    (proj / "phase2/stage1/rtl/top.v").write_text(
        "module top(input clk, input rst, input a, output y);\n"
        "  reg y; always @(posedge clk) y <= a; endmodule\n")
    (proj / "phase1/generated_docs").mkdir(parents=True)
    (proj / "phase1/generated_docs/L5_ADI_SPEC.json").write_text(
        json.dumps({"no_analog": True, "analog_blocks": []}))
    return proj


def _write_block_list(proj: Path, blocks) -> None:
    d = fcc._pl.analog_dir(proj)          # canonical: phase3/analog/
    d.mkdir(parents=True, exist_ok=True)
    (d / "analog_block_list.json").write_text(json.dumps({"blocks": blocks}))


# --------------------------------------------------------------------------
# NEGATIVE CONTROL — the defect. FAILs pre-fix (True), PASSes post-fix (False).
# --------------------------------------------------------------------------
def test_empty_marker_reads_pure_digital(tmp_path):
    proj = _digital_project(tmp_path)
    _write_block_list(proj, [])           # explicit "no analog blocks"
    # The empty marker IS still matched by _glob_first's canonical tolerance —
    # that is exactly why existence was the wrong question. Assert the bug's
    # mechanism is present so this test cannot silently stop exercising it.
    assert fcc._glob_first(
        proj, "phase1/analog/analog_block_list.json"), \
        "canonical-dir tolerance must still existence-match the empty marker"
    # ...yet the CONDITION must read pure-digital (analog stage NOT applicable).
    assert fcc._check_condition(proj, _ANALOG_COND) is False


def test_empty_marker_matches_absent_marker(tmp_path):
    """Empty `{"blocks": []}` must be indistinguishable from no file at all."""
    proj = _digital_project(tmp_path)
    absent = fcc._check_condition(proj, _ANALOG_COND)      # no analog dir yet
    _write_block_list(proj, [])
    empty = fcc._check_condition(proj, _ANALOG_COND)
    assert absent is False and empty is False and absent == empty


# --------------------------------------------------------------------------
# REVERSE CASES — must STILL PASS both pre- and post-fix (no over-tightening).
# --------------------------------------------------------------------------
def test_nonempty_marker_is_still_analog(tmp_path):
    proj = _digital_project(tmp_path)
    _write_block_list(proj, [{"name": "ldo", "type": "regulator"}])
    assert fcc._check_condition(proj, _ANALOG_COND) is True


def test_l9_analog_modules_still_trigger(tmp_path):
    """A design that declares analog via L9 (no block-list file) stays analog."""
    proj = _digital_project(tmp_path)
    (proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"analog_modules": [{"name": "bandgap"}]}))
    assert fcc._check_condition(proj, _ANALOG_COND) is True


def test_l5_analog_blocks_still_trigger(tmp_path):
    """L5_ADI_SPEC with a non-empty analog_blocks[] (no file) stays analog."""
    proj = _digital_project(tmp_path)
    (proj / "phase1/generated_docs/L5_ADI_SPEC.json").write_text(
        json.dumps({"no_analog": False,
                    "analog_blocks": [{"name": "comparator"}]}))
    assert fcc._check_condition(proj, _ANALOG_COND) is True


# --------------------------------------------------------------------------
# Non-analog conditions must be untouched (bare existence still governs them).
# --------------------------------------------------------------------------
def test_non_analog_condition_still_existence_based(tmp_path):
    proj = _digital_project(tmp_path)
    cond = {"files_exist": ["phase2/stage1/rtl/top.v"]}
    assert fcc._check_condition(proj, cond) is True
    cond_absent = {"files_exist": ["phase2/stage1/rtl/does_not_exist.v"]}
    assert fcc._check_condition(proj, cond_absent) is False
