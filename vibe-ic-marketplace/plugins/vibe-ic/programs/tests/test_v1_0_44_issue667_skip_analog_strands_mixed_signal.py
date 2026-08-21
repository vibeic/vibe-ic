"""ORGANIC #667 [MEDIUM] — `--skip-analog` downgrades A* steps to
SKIPPED-CONDITION (check_step) + suppresses the P0 analog sub-gates (#632), but
the downstream mixed-signal M*-track sign-off steps (M1 blocks_on [A8,15];
M2->M1; M3->M2; M4->M3) are NOT suppressed. Their files_exist condition is
auto-satisfied by `_has_canonical_analog_blocks()` (canonical
phase3/analog/analog_block_list.json or L5 analog_blocks>0), so they cannot
self-skip; their mixed-signal required_outputs are never produced under
--skip-analog → status MISSING. The #502 cascade only converts
MISSING->DEFERRED-BY-UPSTREAM when the blocking ancestor is WAIVED, never
SKIPPED-CONDITION, so the M-steps stay hard MISSING and become the SOLE
Overall: FAIL. Net: a legitimate --skip-analog digital-scope run on ANY
mixed-signal-class IC could never reach Overall: PASS/PASS_WITH_WAIVERS.

Fix: extend the #502/#503 cascade — when skip_analog is set, a MISSING
M-track step whose transitive blocks_on ancestry reaches a SKIPPED-CONDITION
A-track step inherits the skip (downgraded to SKIPPED-CONDITION), exactly as
A* steps and the #632 P0 analog sub-gates already are. Chip-AGNOSTIC: gated on
the structural _track_of classification (M-track step, A-track skipped
ancestor) over declared blocks_on edges — no step-id / chip literal.

POSITIVE (#667): M-steps reachable from a skipped A-step → SKIPPED-CONDITION.
KEEP #632 positive: A-steps still SKIPPED-CONDITION; P0 still PASS.

NEGATIVE no-leak:
  - WITHOUT --skip-analog, M-steps are NOT auto-skipped (stay MISSING).
  - a GENUINE M-step FAIL (real counter-evidence) is NOT converted to SKIP.
  - an M-step whose ancestry does NOT reach a skipped analog step is untouched.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import flow_compliance_check as F  # noqa: E402

R = F.StepResult


def _mk(sid, status):
    return R(id=sid, name=str(sid), stage="", status=status)


# Minimal blocks_on graph mirroring the real flow: M1->[A8,15]; M2->M1;
# M3->M2; M4->M3. Built as `steps` dicts so _attribute_cascade_verdicts
# reads the edges exactly as it does from the YAML.
def _steps():
    return [
        {"id": 15, "blocks_on": [9]},
        {"id": "A8", "blocks_on": ["A7"]},
        {"id": "M1", "blocks_on": ["A8", 15]},
        {"id": "M2", "blocks_on": ["M1"]},
        {"id": "M3", "blocks_on": ["M2"]},
        {"id": "M4", "blocks_on": ["M3"]},
    ]


# ── POSITIVE: skipped A-ancestry propagates to MISSING M-steps ────────────
def test_skip_analog_downgrades_stranded_mixed_signal_steps():
    results = [
        _mk(15, "PASS"),
        _mk("A8", "SKIPPED-CONDITION"),  # skipped via --skip-analog
        _mk("M1", "MISSING"),
        _mk("M2", "MISSING"),
        _mk("M3", "MISSING"),
        _mk("M4", "MISSING"),
    ]
    F._attribute_cascade_verdicts(results, _steps(), {}, skip_analog=True)
    by = {r.id: r.status for r in results}
    assert by["M1"] == "SKIPPED-CONDITION"
    assert by["M2"] == "SKIPPED-CONDITION"
    assert by["M3"] == "SKIPPED-CONDITION"
    assert by["M4"] == "SKIPPED-CONDITION"
    # A-step and digital step untouched.
    assert by["A8"] == "SKIPPED-CONDITION"
    assert by[15] == "PASS"
    # cascade note records the skipped analog ancestor.
    m1 = next(r for r in results if r.id == "M1")
    assert "skipped-by-upstream-analog" in m1.cascade_note


# ── NEGATIVE no-leak: without --skip-analog, M-steps stay MISSING ─────────
def test_without_skip_analog_mixed_signal_steps_stay_missing():
    results = [
        _mk(15, "PASS"),
        _mk("A8", "MISSING"),  # analog NOT skipped — genuinely absent
        _mk("M1", "MISSING"),
        _mk("M2", "MISSING"),
    ]
    F._attribute_cascade_verdicts(results, _steps(), {}, skip_analog=False)
    by = {r.id: r.status for r in results}
    assert by["M1"] == "MISSING"
    assert by["M2"] == "MISSING"


# ── NEGATIVE no-leak: a genuine M-step FAIL is NOT converted ──────────────
def test_genuine_mixed_signal_fail_not_skipped():
    results = [
        _mk("A8", "SKIPPED-CONDITION"),
        _mk("M1", "FAIL"),       # real counter-evidence
        _mk("M2", "MISSING"),    # downstream of the real FAIL
    ]
    F._attribute_cascade_verdicts(results, _steps(), {}, skip_analog=True)
    by = {r.id: r.status for r in results}
    assert by["M1"] == "FAIL"  # survives — the fix never masks a real FAIL


# ── NEGATIVE no-leak: M-step whose ancestry has no skipped analog step ────
def test_mixed_signal_without_skipped_analog_ancestor_untouched():
    # A8 is PASS (analog ran), so the M-step MISSING is a real gap, not a skip.
    results = [
        _mk(15, "PASS"),
        _mk("A8", "PASS"),
        _mk("M1", "MISSING"),
    ]
    F._attribute_cascade_verdicts(results, _steps(), {}, skip_analog=True)
    by = {r.id: r.status for r in results}
    assert by["M1"] == "MISSING"


# ── END-TO-END through main() against the real flow YAML ──────────────────
def _adc_like_project(tmp_path):
    """A mixed-signal-class project: canonical analog blocks present (so the
    M-step files_exist condition auto-satisfies and the steps don't self-skip),
    but NO analog/mixed-signal outputs on disk (so M-steps go MISSING)."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "no_analog": False,
        "analog_blocks": [{"name": "blk_a"}, {"name": "blk_b"}],
    }))
    an = tmp_path / "phase3" / "analog"
    an.mkdir(parents=True)
    (an / "analog_block_list.json").write_text(json.dumps({
        "blocks": [{"name": "blk_a"}, {"name": "blk_b"}]}))
    return tmp_path


def _run(project, extra):
    jp = project / "_report.json"
    argv = [str(project), "--strict", "--phase", "2",
            "--json", str(jp)] + extra
    rc = F.main(argv)
    data = json.loads(jp.read_text())
    by = {str(s["id"]): s["status"] for s in data["steps"]}
    return rc, by, data


def test_e2e_skip_analog_no_longer_strands_mixed_signal(tmp_path):
    project = _adc_like_project(tmp_path)
    _, by, _ = _run(project, ["--skip-analog", "--skip-hardware"])
    # The four M-steps must NOT be hard MISSING any more.
    for m in ("M1", "M2", "M3", "M4"):
        assert by.get(m) in ("SKIPPED-CONDITION", "DEFERRED-BY-UPSTREAM"), (
            f"{m} status={by.get(m)} (expected skip-inherited, not MISSING)")
    # The A-steps are skipped (#632 path intact).
    assert all(by.get(a) == "SKIPPED-CONDITION"
               for a in by if a.startswith("A"))


def test_e2e_without_skip_analog_mixed_signal_still_missing(tmp_path):
    # NO-LEAK end-to-end: without --skip-analog the M-steps are genuinely
    # MISSING (the fix only fires under the disclosed --skip-analog mode).
    project = _adc_like_project(tmp_path)
    _, by, _ = _run(project, ["--skip-hardware"])
    assert by.get("M1") == "MISSING"
