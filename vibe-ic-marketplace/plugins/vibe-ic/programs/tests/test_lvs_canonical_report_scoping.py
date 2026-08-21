"""eda_report_audit._check_lvs — CANONICAL-REPORT SCOPING.

The GAP-E2E-9 power-aware LVS upgrade path (`phase3_one_shot_runner.
_try_power_aware_lvs`) is strictly monotonic: it tries a stricter
power-aware netgen compare and writes its OWN transcript to
`reports/phase3/lvs_power_aware.rpt`, but when that attempt does not
reach a clean match it returns None and the runner falls through to the
plain-netlist path, which writes the REAL sign-off report to the
canonical `reports/phase3/lvs.rpt`. The abandoned attempt's file is
never deleted and still matches `_check_lvs`'s broad `*lvs*.rpt`
discovery glob.

Pre-fix, `_check_lvs` concatenated EVERY discovered file into one blob
before classifying it, so the abandoned attempt's own terminal MISMATCH
token ("Final result: Top level cell failed pin matching.") silently
overrode a genuinely clean canonical verdict — a real PASS reported as
a false FAIL.

MEASURED: caravel_user_project x sky130A, v1.5.60 — `reports/phase3/
lvs.rpt` ends "Final result: Circuits match uniquely." (confirmed by
the runner's own `reports/phase3/lvs_verdict.json`: status=PASS,
finding=LVS_MATCH), while a stale `reports/phase3/lvs_power_aware.rpt`
(an abandoned 4-rail power-aware retry) ends "Final result: Top level
cell failed pin matching.". Concatenating both flipped Step-31 LVS
sign-off from PASS to FAIL.

Fix: when `reports/phase3/lvs.rpt` (the flow-defined canonical sign-off
path, `flow/phase1_phase2_phase3.yaml` Step 31) exists, classify SOLELY
on its own text. This is still an INDEPENDENT re-derivation from the
report's own netgen text (never a trust of the runner's self-reported
verdict) — it only stops an unrelated `*lvs*`-glob-matching file from
name-colliding with it. Any project shape without that canonical path
falls back to the prior aggregate-blob behaviour, unchanged.

chip-AGNOSTIC: `reports/phase3/lvs.rpt` is a fixed project-structure
path used for every IC/PDK, never a chip literal.
"""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "eda_report_audit.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import eda_report_audit as era  # noqa: E402

_PAD = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB — clears MIN_REPORT_BYTES["lvs"]

_CANONICAL_MATCH = (
    "Netgen LVS comparison\n"
    "Subcircuit instance summary: 567 instances compared\n"
    "NET count: 1234\ndevice count: 567\n"
    "Number of topologically valid matches: 567\n"
    "Final result: Circuits match uniquely.\n" + _PAD
)

_ABANDONED_POWER_AWARE_MISMATCH = (
    "Netgen LVS comparison (power-aware attempt)\n"
    "Subcircuit instance summary: 567 instances compared\n"
    "NET count: 1234\ndevice count: 567\n"
    "Cell sky130_fd_sc_hd__buf_16 (0) disconnected node: VGND\n"
    "Netlists do not match.\n"
    "Final result: Top level cell failed pin matching.\n" + _PAD
)


def _write_canonical(tmp_path, text):
    p = tmp_path / "reports" / "phase3" / "lvs.rpt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _write_abandoned_power_aware(tmp_path, text):
    p = tmp_path / "reports" / "phase3" / "lvs_power_aware.rpt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# --------------------------------------------------------------- POSITIVE ---

def test_clean_canonical_survives_a_stale_abandoned_attempt(tmp_path):
    """The measured bug: a clean canonical lvs.rpt must PASS even with a
    stale, mismatched lvs_power_aware.rpt sitting next to it."""
    _write_canonical(tmp_path, _CANONICAL_MATCH)
    _write_abandoned_power_aware(tmp_path, _ABANDONED_POWER_AWARE_MISMATCH)

    result = era._check_lvs(tmp_path)

    assert result.passed is True
    assert result.summary["terminal_verdict"] == "MATCH"
    assert result.summary["canonical_report_used"] is True
    assert not any(f.rule == "LVS_NETLISTS_DO_NOT_MATCH"
                   for f in result.findings)


def test_canonical_scoping_also_avoids_stale_no_signature_pollution(tmp_path):
    """A stale attempt file that ALSO lacks a recognizable tool signature
    (e.g. an interrupted/partial transcript) must not poison authenticity
    either, once the canonical report is what's actually classified."""
    _write_canonical(tmp_path, _CANONICAL_MATCH)
    stale = tmp_path / "reports" / "phase3" / "lvs_power_aware.rpt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("not a real tool transcript\n")

    result = era._check_lvs(tmp_path)

    assert result.passed is True
    assert result.summary["tool_authentic"] is True
    assert not any(f.rule == "LVS_NO_TOOL_SIGNATURE" for f in result.findings)


# ------------------------------------------------------------- NO-LEAK -----

def test_mismatched_canonical_still_fails_even_with_a_clean_aux_file(tmp_path):
    """§4.05 no-leak: an unrelated file's CLEAN verdict must never upgrade a
    genuinely mismatched canonical report into a PASS."""
    _write_canonical(tmp_path, _ABANDONED_POWER_AWARE_MISMATCH)
    _write_abandoned_power_aware(tmp_path, _CANONICAL_MATCH)  # aux is clean

    result = era._check_lvs(tmp_path)

    assert result.passed is False
    assert result.summary["terminal_verdict"] == "MISMATCH"
    assert any(f.rule == "LVS_NETLISTS_DO_NOT_MATCH" for f in result.findings)


def test_no_canonical_path_falls_back_to_prior_aggregate_behaviour(tmp_path):
    """A project shape with no `reports/phase3/lvs.rpt` at all (legacy /
    non-standard layout) must behave exactly as before the fix: classify
    from whatever `*lvs*` files are discovered."""
    rpt = tmp_path / "chip_lvs.rpt"
    rpt.write_text(_CANONICAL_MATCH)

    result = era._check_lvs(tmp_path)

    assert result.passed is True
    assert result.summary["canonical_report_used"] is False


def test_no_canonical_path_still_catches_a_real_mismatch(tmp_path):
    rpt = tmp_path / "chip_lvs.rpt"
    rpt.write_text(_ABANDONED_POWER_AWARE_MISMATCH)

    result = era._check_lvs(tmp_path)

    assert result.passed is False
    assert result.summary["terminal_verdict"] == "MISMATCH"


# ---------------------------------------------- harvest(#341 via #349) -----
# NAME-SPECIFIC no-leak. The scoping above is keyed on the canonical PATH, so
# the advisory report's NAME is irrelevant to it — and that is precisely why
# this control is needed. The obvious alternative implementation, proposed
# while this defect was being triaged, filters by name instead:
#
#     files = [f for f in files if "power_aware" not in f.name.lower()]
#
# On the shape below that filter empties the list, and a `_check_lvs` that
# then reports "nothing to judge" as clean would turn a run whose ONLY LVS
# evidence is a MISMATCH into a PASS — a false sign-off certificate built out
# of an empty result set, the same family as every other defect in this
# campaign. Behaviour on main is already correct (verified before writing
# this: rc=1); this pins it against that specific future rewrite.

def test_advisory_report_alone_is_still_judged_not_silently_passed(tmp_path):
    """A run that produced ONLY the advisory power-aware report — at its real
    path and under its real name — must be JUDGED on it. With no
    authoritative sign-off report there is nothing to prefer it over, so its
    mismatch stands and the gate FAILs."""
    p3 = tmp_path / "reports" / "phase3"
    p3.mkdir(parents=True)
    (p3 / "lvs_power_aware.rpt").write_text(_ABANDONED_POWER_AWARE_MISMATCH)

    result = era._check_lvs(tmp_path)

    assert result.passed is False
    assert result.summary["terminal_verdict"] == "MISMATCH"
    assert result.summary["files_found"] >= 1, (
        "the advisory report must not be filtered out of existence — an "
        "empty result set is indistinguishable from a clean one")


def test_advisory_alone_that_matches_is_not_forced_to_fail(tmp_path):
    """Symmetric control, so the test above cannot be satisfied by simply
    failing on the advisory file's name: the same lone advisory report
    carrying a genuine MATCH must PASS. The verdict comes from the report's
    own text, never from which file it is."""
    p3 = tmp_path / "reports" / "phase3"
    p3.mkdir(parents=True)
    (p3 / "lvs_power_aware.rpt").write_text(_CANONICAL_MATCH)

    result = era._check_lvs(tmp_path)

    assert result.passed is True
    assert result.summary["terminal_verdict"] == "MATCH"
