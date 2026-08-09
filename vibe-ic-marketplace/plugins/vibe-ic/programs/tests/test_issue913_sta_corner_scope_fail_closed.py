"""vibe-ic#913 — a sign-off PASS may not be narrower than the run's own record.

`post_route_signoff_corner_check` reads ONE axis: the RC/parasitic corners of
the multicorner SPEF report. v1.10.22 made the PASS line name that axis. This
is the fail-closed half: naming the scope does not stop the verdict being
quoted as sign-off.

MEASURED, on a real run: the gate returned PASS with
`setup_worst_slack_ns: 6.77` while the same run's own process-axis sign-off
record carried a VIOLATED setup corner at -2.850 ns. Reproduced 12 times across
the local corpus.

Every assertion below is on a RETURNED VALUE — a process exit code or a field
of the JSON the gate emits. Nothing asserts on the gate's source text.

MUTATION IN BOTH DIRECTIONS, which is the point of this file. The VERDICT tests
below assert only on exit code and `verdict`, so that restoring the unfixed
program (`git checkout origin/main -- post_route_signoff_corner_check.py`)
separates cleanly into:

  * FAILs on the unfixed program, on the EXIT CODE and nothing else —
    `test_out_of_scope_violated_axis_fails_the_signoff` (rc 0 -> must be 1) and
    `test_declared_axis_never_swept_fails`. That is the behavioural change.
  * PASSes on BOTH programs — `test_out_of_scope_met_axis_still_passes`,
    `test_single_axis_run_is_unaffected`,
    `test_availability_list_alone_never_manufactures_a_fail`,
    `test_slack_fail_is_still_a_slack_fail`,
    `test_absent_report_is_still_not_applicable`. These are the always-fail
    control: five trees, four of them PASSing, prove the gate did not become a
    program that can only say FAIL, and that no pre-existing verdict moved.

The `signoff_scope` triage field is asserted in SEPARATE tests at the bottom.
They necessarily fail on the unfixed program because the field is new, which
says nothing about behaviour — keeping them out of the verdict tests is what
makes the mutation above mean what it claims.

chip-AGNOSTIC: the fixtures name no design, PDK, vendor or part number, and the
out-of-scope axis is called `axis_b` — the gate keys on the run's declaration
STRUCTURE, never on a corner vocabulary, so a synthetic axis name exercises the
identical path a real one does.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
GATE = PROG_DIR / "post_route_signoff_corner_check.py"
sys.path.insert(0, str(PROG_DIR))
import post_route_signoff_corner_check as G  # noqa: E402

# An RC-axis sweep that is CLEAN on its own terms — every worst-slack positive.
_RC_AXIS_CLEAN = """# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# SETUP corner: max-RC   HOLD corner: min-RC
# corners_available: max,min,nom
=== SETUP (max-RC corner, SPEF=max) ===
worst slack max 6.77
tns max 0.00
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min 0.07
tns max 0.00
"""

# The stance the flow writes beside that report: this gate's OWN axis.
_OWN_AXIS_STANCE = {
    "signoff_dimension": "multi_corner_spef",
    "setup_corner": "max",
    "hold_corner": "min",
    "multicorner_sta_report": "phase3/stage3/sta/sta_spef_multicorner.rpt",
    "corner_library_resolution": {"axis": "rc_parasitic"},
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _make_run(root: Path, other_axis: dict | None) -> Path:
    """A synthetic run: a clean RC-axis report, its own stance, and optionally
    one out-of-scope sign-off axis with whatever outcome the caller wants."""
    _write(root / "phase3/stage3/sta/sta_spef_multicorner.rpt", _RC_AXIS_CLEAN)
    _write(root / "reports/phase3/multi_corner_spef_stance.json",
           json.dumps(_OWN_AXIS_STANCE))
    if other_axis is not None:
        _write(root / "reports/phase3/other_axis_stance.json",
               json.dumps(other_axis))
    return root


def _run_gate(root: Path, tmp_path: Path):
    """Invoke the gate exactly as the runner does; return (rc, verdict JSON)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "verdict.json"
    cp = subprocess.run(
        [sys.executable, str(GATE), str(root), "--json", str(out)],
        capture_output=True, text=True, check=False)
    doc = json.loads(out.read_text()) if out.is_file() else {}
    return cp.returncode, doc, cp.stdout


# ── direction 1: the fix must DO something ──────────────────────────────────

def test_out_of_scope_violated_axis_fails_the_signoff(tmp_path):
    """#913 itself. The RC axis is MET; the run's other declared sign-off axis
    records a violated corner. The gate must not publish that as PASS.

    Against the unfixed program this returns rc 0 / verdict PASS.
    """
    root = _make_run(tmp_path / "run", {
        "signoff_dimension": "multi_corner_axis_b",
        "corner_library_resolution": {"axis": "axis_b"},
        "setup_worst_slack_ns": -2.850,
        "hold_worst_slack_ns": 0.46,
        "violated_corners": ["setup"],
    })
    rc, doc, _ = _run_gate(root, tmp_path)

    assert rc == 1, f"a violated out-of-scope sign-off axis must exit 1, got {rc}"
    assert doc["verdict"] == "FAIL", doc
    # The in-scope numbers survive: the RC axis really was met, and the verdict
    # must not pretend otherwise or triage cannot tell the two defects apart.
    assert doc["setup_worst_slack_ns"] == 6.77, doc
    assert doc["governing_worst_slack_ns"] == 0.07, doc
    # The violated axis is named in the emitted reasons, with its own number.
    joined = " ".join(str(r) for r in doc["reasons"])
    assert "axis_b" in joined and "-2.85" in joined, joined


def test_declared_axis_never_swept_fails(tmp_path):
    """An out-of-scope axis DECLARED by the run but carrying no slack at all.

    An unswept corner is indistinguishable from a met one, so it may not be
    signed off. Against the unfixed program this also returned rc 0 / PASS.
    """
    root = _make_run(tmp_path / "run", {
        "signoff_dimension": "multi_corner_axis_b",
        "corner_library_resolution": {"axis": "axis_b"},
        "violated_corners": [],
    })
    rc, doc, _ = _run_gate(root, tmp_path)

    assert rc == 1, f"a declared-but-unswept sign-off axis must exit 1, got {rc}"
    assert doc["verdict"] == "FAIL", doc
    assert any("never swept" in str(r) for r in doc["reasons"]), doc


# ── direction 2: the OPPOSITE verdict must still be reachable ───────────────

def test_out_of_scope_met_axis_still_passes(tmp_path):
    """The always-fail control. Same tree, same code path — the ONLY difference
    is that the other axis is MET. A PASS must still be produced, or the two
    tests above would be proving nothing about the design."""
    root = _make_run(tmp_path / "run", {
        "signoff_dimension": "multi_corner_axis_b",
        "corner_library_resolution": {"axis": "axis_b"},
        "setup_worst_slack_ns": 4.56,
        "hold_worst_slack_ns": 0.38,
        "violated_corners": [],
    })
    rc, doc, _ = _run_gate(root, tmp_path)

    assert rc == 0, f"a met out-of-scope axis must still PASS, got rc {rc}: {doc}"
    assert doc["verdict"] == "PASS", doc


def test_single_axis_run_is_unaffected(tmp_path):
    """A run declaring NO second sign-off axis is judged exactly as before.

    This is the backward-compatibility edge: the gate invents no axis, so it
    invents no FAIL. `signoff_scope` reports the narrowness instead.
    """
    root = _make_run(tmp_path / "run", None)
    rc, doc, _ = _run_gate(root, tmp_path)

    assert rc == 0, doc
    assert doc["verdict"] == "PASS", doc


def test_availability_list_alone_never_manufactures_a_fail(tmp_path):
    """A pvt_matrix listing several corners is AVAILABILITY, not configuration.

    Letting it declare an axis would fire on every run in the corpus — the
    mirror-image defect. It is carried as context and drives nothing.
    """
    root = _make_run(tmp_path / "run", None)
    _write(root / "phase2/stage2/constraints/pvt_matrix.json", json.dumps({
        "corners": [{"name": "c1", "label": "A"}, {"name": "c2", "label": "B"},
                    {"name": "c3", "label": "C"}],
        "primary_corner": "B", "corner_count": 3, "multi_corner": True}))
    rc, doc, _ = _run_gate(root, tmp_path)

    assert rc == 0, doc
    assert doc["verdict"] == "PASS", doc


# ── the pre-existing single-axis behaviour is untouched ─────────────────────

def test_slack_fail_is_still_a_slack_fail(tmp_path):
    """A violated in-scope corner FAILs for its own reason, not the new one."""
    root = tmp_path / "run"
    _write(root / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _RC_AXIS_CLEAN.replace("worst slack max 6.77",
                                  "worst slack max -1.71"))
    rc, doc, _ = _run_gate(root, tmp_path)

    assert rc == 1, doc
    assert doc["verdict"] == "FAIL", doc
    assert any("VIOLATED" in str(r) for r in doc["reasons"]), doc


def test_absent_report_is_still_not_applicable(tmp_path):
    """No report, no judgement — the gate stays backward-compatible."""
    root = tmp_path / "empty"
    root.mkdir()
    rc, doc, _ = _run_gate(root, tmp_path)
    assert rc == 0 and doc["verdict"] == "NOT_APPLICABLE", doc


def test_pure_evaluator_without_scope_is_unchanged(tmp_path):
    """`evaluate(text)` with no scope is the pre-#913 single-axis evaluation.

    This is what keeps every existing report-only fixture and caller intact.
    """
    res = G.evaluate(_RC_AXIS_CLEAN)
    assert res["verdict"] == "PASS", res
    assert res["governing_worst_slack_ns"] == 0.07, res


# ── the triage field, asserted apart from the verdicts (see module docstring) ─
#
# `signoff_scope` is NEW, so these fail on the unfixed program for the trivial
# reason that the key does not exist. That is why they are not mixed into the
# verdict tests above: those must fail on the unfixed program for a
# BEHAVIOURAL reason (the exit code) or the mutation proves nothing.

def test_signoff_scope_field_distinguishes_the_four_outcomes(tmp_path):
    """One field a triage reader can key on, distinct per outcome."""
    violated = _make_run(tmp_path / "v", {
        "signoff_dimension": "multi_corner_axis_b",
        "corner_library_resolution": {"axis": "axis_b"},
        "setup_worst_slack_ns": -2.850, "hold_worst_slack_ns": 0.46,
        "violated_corners": ["setup"]})
    unswept = _make_run(tmp_path / "u", {
        "signoff_dimension": "multi_corner_axis_b",
        "corner_library_resolution": {"axis": "axis_b"},
        "violated_corners": []})
    met = _make_run(tmp_path / "m", {
        "signoff_dimension": "multi_corner_axis_b",
        "corner_library_resolution": {"axis": "axis_b"},
        "setup_worst_slack_ns": 4.56, "hold_worst_slack_ns": 0.38,
        "violated_corners": []})
    alone = _make_run(tmp_path / "s", None)

    assert _run_gate(violated, tmp_path / "jv")[1]["signoff_scope"] == \
        "OUT_OF_SCOPE_AXIS_VIOLATED"
    assert _run_gate(unswept, tmp_path / "ju")[1]["signoff_scope"] == \
        "DECLARED_AXIS_NOT_SWEPT"
    assert _run_gate(met, tmp_path / "jm")[1]["signoff_scope"] == \
        "MULTI_AXIS_CORROBORATED"
    assert _run_gate(alone, tmp_path / "js")[1]["signoff_scope"] == \
        "SINGLE_AXIS"


def test_a_corroborated_pass_states_how_wide_it_is(tmp_path):
    """The PASS line names both the axis swept and the one that corroborated."""
    met = _make_run(tmp_path / "m", {
        "signoff_dimension": "multi_corner_axis_b",
        "corner_library_resolution": {"axis": "axis_b"},
        "setup_worst_slack_ns": 4.56, "hold_worst_slack_ns": 0.38,
        "violated_corners": []})
    rc, doc, _ = _run_gate(met, tmp_path / "j")
    assert rc == 0 and doc["verdict"] == "PASS", doc
    joined = " ".join(str(r) for r in doc["reasons"])
    assert "max,min,nom" in joined and "axis_b" in joined, joined


def test_a_slack_fail_never_claims_corroboration_it_does_not_have(tmp_path):
    """The scope label states facts about the other axis on the FAIL path too.

    Deriving it only where the in-scope slack passed would let a slack-FAIL run
    publish `MULTI_AXIS_CORROBORATED` beside an axis that is itself violating —
    the same bug one level quieter.
    """
    root = tmp_path / "run"
    _write(root / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _RC_AXIS_CLEAN.replace("worst slack max 6.77",
                                  "worst slack max -1.71"))
    _write(root / "reports/phase3/multi_corner_spef_stance.json",
           json.dumps(_OWN_AXIS_STANCE))
    _write(root / "reports/phase3/other_axis_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_axis_b",
        "corner_library_resolution": {"axis": "axis_b"},
        "setup_worst_slack_ns": -2.850, "violated_corners": ["setup"]}))
    rc, doc, _ = _run_gate(root, tmp_path / "j")

    assert rc == 1 and doc["verdict"] == "FAIL", doc
    assert doc["signoff_scope"] == "OUT_OF_SCOPE_AXIS_VIOLATED", doc


def test_availability_list_is_context_only_in_the_json(tmp_path):
    """The pvt corner count is carried, but no axis is invented from it."""
    root = _make_run(tmp_path / "run", None)
    _write(root / "phase2/stage2/constraints/pvt_matrix.json", json.dumps({
        "corners": [{"name": "c1", "label": "A"}, {"name": "c2", "label": "B"},
                    {"name": "c3", "label": "C"}],
        "corner_count": 3, "multi_corner": True}))
    rc, doc, _ = _run_gate(root, tmp_path / "j")
    assert rc == 0 and doc["verdict"] == "PASS", doc
    assert doc["out_of_scope_axes"] == [], doc
