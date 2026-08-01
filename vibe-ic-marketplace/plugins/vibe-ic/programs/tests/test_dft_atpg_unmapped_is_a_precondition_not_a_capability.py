"""An ATPG run that never got a mapped netlist was bookkept as a capability gap.

Third member of the family. `_dft_atpg_crash_reason` split a signal death out
("a crash must not be bookkept against a capability the engine HAS"); #581 and
its DT1 follow-up split a wall-clock expiry out ("a budget and a capability need
different remedies"). Both landed. The remaining blanket arm still absorbed a
FOURTH cause with a different remedy again: the engine was handed a netlist with
no library-mapped cells at all, so it never ran.

The emitted record was

    {"verdict": "SKIPPED-CONDITION",
     "reason": "OSS Fault ATPG could not measure sign-off stuck-at coverage on
                this netlist (... not turnkey on the generic_unmapped
                generic/UDP DFF forms) ... Sign-off ATPG coverage is a disclosed
                OSS capability gap; a mapped-netlist or commercial ATPG path
                closes it.",
     "capability_flag": "cap:atpg_signoff_coverage",
     "pdk_detected": "generic_unmapped",
     "atpg_exit": null, "faults_total": null, "coverage_measured": null}

`atpg_exit: null` and `faults_total: null` are the tell: the engine produced
nothing at all because it was never given a runnable input.

MEASURED inside ONE run (sha256 x sky130A, plugin v1.9.27, image 0.2.51). Same
`fault` binary, same design, same container; the only variable is whether the
mapped netlist existed yet:

  16:37:33  Phase-2 synth writes `phase2/stage2/synth/netlist.v`
            technology-GENERIC by construction (`dffunmap; abc -g cmos2`, no
            Liberty) — 28 397 cells, all `$_NAND_`/`$_NOR_`/`$_NOT_`/
            `$_DFF_P_`, ZERO library cells. A property of the FLOW, not of the
            design: every run of this shape gets it.
  16:37:33  Step 11 runs against exactly that. Retained
            `reports/phase2/dft/coverage.unmeasured.json`, verbatim:
            `"error": "unsupported pdk: unmapped. Supported: ['gf180',
            'sky130', 'ihp-sg13g2']"`, `"pdk_sniff": "no configured library's
            cells found in the resolved netlist"`. Recorded as a capability
            gap closed by "a commercial ATPG path".
  18:28:35  Phase 3 writes the tech-mapped sibling `<top>_synth.v`: 13 247
            library cells.
  18:28:48  THIRTEEN SECONDS LATER the same engine builds a real scan chain on
            it — `reports/phase2/dft/scan_chain.json`: `"chain_exit": 0`,
            `"pdk": "sky130"`, `"area_instances_before": 13247`,
            `"area_instances_after": 14225`, DFT ports added.
  18:28:55  `cut_netlist.v` appears — the precondition DT1 reported absent.

So the capability is present and demonstrated. What was absent was an input
this same flow produces one phase later. Recording that as an OSS capability
gap tells a reader to go find a commercial ATPG tool for an ordering problem.

DIRECTION OF THE CHANGE — declared. Dropping `capability_flag` can only leave a
step's status the SAME or make it STRICTER: the flag's sole gating role is
`flow_compliance_check._declared_sibling_self_skip_for_missing`, a capability-
AWARE promotion of MISSING -> SKIPPED-CONDITION. Refusing that promotion for a
precondition is the correct direction and can never turn a FAIL into a PASS.
Measured on the published sha256 x sky130A tree: removing both DFT capability
flags left `flow_compliance_check --strict` byte-identical (PASS=29 FAIL=4
MISSING=1 WAIVED-DEFERRED=5 SKIPPED=21 VACUOUS-PASS=3, rc 1 both arms), so on
that corpus member the flag was gating nothing and asserting something false.

SCOPE. This pins the CLASSIFICATION only. Making step 11 run after technology
mapping — so the coverage is actually measured rather than honestly skipped —
is the larger flow-ordering change and is deliberately NOT done here.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "design_one_shot_runner.py"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as fcc  # noqa: E402

# The flag the DT1 precondition record used to carry via `dict(_TDF_CAP, ...)`.
_TDF_CAP_FLAG = "cap:at_speed_timing_graded_atpg"


def _src() -> str:
    return PROG.read_text(encoding="utf-8")


def _strip_comments(block: str) -> str:
    """Code only. A scan that cannot tell documentation from code has to be
    weakened the first time someone documents something — every arm here must
    NAME the flag in prose to explain why it withholds it."""
    return "\n".join(ln for ln in block.splitlines()
                     if not ln.lstrip().startswith("#"))


def _stuck_at_dispatch() -> str:
    """The three-way `if _atpg_sig_death / elif / else` that chooses what the
    step-11 stuck-at not-run record claims."""
    src = _src()
    i = src.index("_atpg_sig_death = bool(")
    j = src.index("_dft_disclose_skip(", i)
    return src[i:j]


def _tdf_precondition_arm() -> str:
    """The DT1 arm taken when a required input is absent."""
    src = _src()
    i = src.index("    if _tdf_missing:")
    j = src.index("    else:", i)
    return src[i:j]


# ── the stuck-at arm ─────────────────────────────────────────────────────────
def test_the_unmapped_arm_exists_and_precedes_the_blanket_capability_arm():
    """Order is the fix. A trailing `else` would swallow it, exactly as the
    blanket `except Exception` swallowed the timeout before #581."""
    d = _stuck_at_dispatch()
    assert "elif not pdk:" in d, (
        "there is no arm for 'the sniff found no library-mapped cells', so the "
        "case still falls through to the capability-gap else")
    assert d.index("elif not pdk:") < d.index("else:"), (
        "the blanket capability arm precedes the precondition arm")


def test_the_unmapped_record_carries_no_capability_flag():
    """The defect, stated as a property of the emitted record."""
    d = _stuck_at_dispatch()
    arm = _strip_comments(d.split("elif not pdk:", 1)[1].split("else:", 1)[0])
    assert "capability_flag" not in arm, (
        "the unmapped arm still RECORDS a capability flag — it asserts the "
        "engine cannot do something this same engine has been measured doing")
    assert "capability_flag" in d.split("elif not pdk:", 1)[1], (
        "the arm no longer explains why it withholds the flag; without that "
        "the next reader adds it back as an obvious omission")


def test_the_unmapped_record_names_the_missing_input_and_the_stage():
    """A skip that does not say WHAT was missing is not actionable — the same
    bar `wall_budget_s` meets for the budget arm."""
    arm = _stuck_at_dispatch().split("elif not pdk:", 1)[1].split("else:", 1)[0]
    assert "not_run_stage" in arm and "precondition_unmet" in arm
    assert "missing_precondition" in arm


def test_a_real_mapped_pdk_still_records_the_capability_flag():
    """The accept case, and why this is a split and not a deletion.

    A netlist that IS library-mapped and still yields no measurement is a
    genuine engine limitation; dropping the flag there would trade one
    mislabel for another.
    """
    blanket = _stuck_at_dispatch().split("elif not pdk:", 1)[1].split("else:", 1)[1]
    assert "cap:atpg_signoff_coverage" in blanket, (
        "the genuine capability-gap path lost its flag")


def test_the_prose_stops_proposing_a_commercial_tool_for_a_missing_input():
    """`_dft_atpg_gap_reason` ends 'a mapped-netlist or commercial ATPG path
    closes it'. Pointing a reader at a commercial tool because our own flow has
    not written its netlist yet is the concrete harm of the mislabel."""
    src = _src()
    i = src.index("def _dft_atpg_precondition_reason(")
    j = src.index("def _derive_dft_clock_name(", i)
    reason = src[i:j]
    assert "commercial" not in reason.lower().split('"""')[-1], (
        "the precondition reason proposes a commercial ATPG path")
    assert "NEVER RAN" in reason and "precondition unmet" in reason


def test_the_step_summary_line_carries_the_same_distinction():
    """The console one-liner is what a human reads first; if it still says
    'engine-limited' the record's honesty never reaches them."""
    src = _src()
    i = src.index("stuck-at ATPG NEVER RAN")
    tail = src[i:i + 700]
    assert "precondition unmet" in tail and "NOT a capability gap" in tail
    # and the mapped-PDK branch of the SAME summary keeps its wording
    assert "engine-limited" in tail


# ── the DT1 arm ──────────────────────────────────────────────────────────────
def test_the_dt1_precondition_record_carries_no_capability_flag():
    """DT1 already SAID `precondition_unmet` while asserting a capability flag
    in the same dict — the two claims contradict each other."""
    arm = _strip_comments(_tdf_precondition_arm())
    assert "capability_flag" not in arm, (
        "the DT1 precondition arm still asserts a capability the engine was "
        "never asked to exercise")
    # FALSIFIABLE. The pre-fix arm spread the whole `_TDF_CAP` dict, which
    # CONTAINS capability_flag without naming it here — a literal-only scan
    # would have passed against the defect it is meant to catch.
    assert "dict(_TDF_CAP" not in arm, (
        "the arm still splats _TDF_CAP wholesale, so it carries "
        f"{_TDF_CAP_FLAG!r} into a record that says the engine never ran")
    assert "not_run_stage" in arm and "precondition_unmet" in arm


def test_the_dt1_precondition_record_keeps_its_ownership_claim():
    """`skips_required_output` says WHICH absent output this marker explains.
    That claim is true and is a different claim from the capability one;
    dropping it would make the record un-attributable."""
    arm = _strip_comments(_tdf_precondition_arm())
    assert "skips_required_output" in arm


def test_the_tdf_cap_constant_still_serves_the_arms_that_ran():
    """`_TDF_CAP` is still used where the engine actually ran and hit a real
    limit — this is a split of one arm, not the removal of the constant."""
    src = _src()
    assert "_TDF_CAP = {" in src
    assert src.count("_TDF_CAP") >= 3, (
        "_TDF_CAP no longer reaches the arms where the engine DID run")


# ── executed, not merely read ────────────────────────────────────────────────
@pytest.mark.parametrize("pdk,expected", [
    (None, "precondition"),
    ("", "precondition"),
    ("sky130", "capability"),
    ("gf180", "capability"),
    ("ihp-sg13g2", "capability"),
])
def test_python_dispatches_the_two_arms_as_written(pdk, expected):
    """Mirrors the discriminator and RUNS it. `_dft_atpg_sniff_pdk` returns ""
    for a generic/unmapped netlist and a library id otherwise, so `not pdk` is
    exactly 'the engine had no runnable input'."""
    def dispatch(p, sig_death=False):
        if sig_death:
            return "crash"
        if not p:
            return "precondition"
        return "capability"

    assert dispatch(pdk) == expected


def test_a_signal_death_still_wins_over_the_precondition_arm(tmp_path):
    """Order between the first two arms matters too: a crash on a mapped
    netlist must not be relabelled a missing input."""
    def dispatch(p, sig_death):
        if sig_death:
            return "crash"
        if not p:
            return "precondition"
        return "capability"

    assert dispatch("sky130", True) == "crash"
    assert dispatch(None, True) == "crash"


def test_the_emitted_record_is_not_a_declared_capability_gap(tmp_path):
    """End to end on the CONSUMER: build the record the fixed arm builds and
    ask `flow_compliance_check` whether it claims a declared capability gap.

    This is the property that matters — not that a key is absent from a dict,
    but that the gate can no longer read a capability claim off it.
    """
    record = {"verdict": "SKIPPED-CONDITION",
              "tool_attempted": True,
              "not_run_stage": "precondition_unmet",
              "missing_precondition": "phase2/stage2/synth/*_synth.v",
              "pdk_detected": "generic_unmapped"}
    p = tmp_path / "dft_atpg_not_run.json"
    p.write_text(json.dumps(record, indent=2))

    assert not fcc._is_declared_capability_gap(
        str(record.get("capability_flag", ""))), (
        "the precondition record is still readable as a declared capability gap")
    # and the arm that DID hit a real engine limit still is
    assert fcc._is_declared_capability_gap("cap:atpg_signoff_coverage"), (
        "the registry no longer declares the genuine gap — this test would "
        "then be passing for the wrong reason")
