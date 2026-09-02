"""A DECLARATION was booked as a CASCADE. `_BLOCKED_RE`'s `\\bno l\\d+\\b` read
"and no L19 die-area contract" — a sentence about what the design states — as
"L19 never arrived", so step D1 lost its tier to an upstream that does not
exist. Bidirectional: the declaration must stop classifying BLOCKED_BY_UPSTREAM
and a genuinely absent layer document must keep classifying it."""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

# The exact sentence `l9_floorplan_contract_check` emits when both layers were
# read and neither mandates a floorplan.
DECLARED = ("the design mandates no floorplan (no DIE_AREA / DIE_WIDTH+"
            "DIE_HEIGHT / PL_TARGET_DENSITY / FP_CORE_UTIL, and L19 declares "
            "no die-area contract) — phase3 auto-sizes and there is no "
            "verbatim-consumed value to protect")
# The wording that actually fooled the recogniser, kept verbatim: the fix must
# hold for the sentence as it was, not only for the clearer one that replaces it.
LEGACY = ("the design mandates no floorplan (no DIE_AREA / DIE_WIDTH+"
          "DIE_HEIGHT / PL_TARGET_DENSITY / FP_CORE_UTIL and no L19 "
          "die-area contract) — phase3 auto-sizes and there is no "
          "verbatim-consumed value to protect")
# The other branch of the same gate: the documents really are not there.
ABSENT = ("no L9 / constraint / floorplan source file and no L19 die-area "
          "contract in the project")


def test_declaration_is_not_a_cascade():
    import _flow_reason_taxonomy as tax
    for msg in (DECLARED, LEGACY):
        assert tax.infer_nonverdict_reason(
            verdict="VACUOUS_PASS",
            message=msg) != tax.BLOCKED_BY_UPSTREAM, msg


def test_absent_layer_document_still_is_a_cascade():
    """Over-reach control. Narrowing the recogniser must not launder a real
    missing upstream into a design N/A."""
    import _flow_reason_taxonomy as tax
    for msg in (ABSENT,
                "no L19 json under phase1/generated_docs",
                "no L5 emitted by the upstream step"):
        assert tax.infer_nonverdict_reason(
            verdict="VACUOUS_PASS",
            message=msg) == tax.BLOCKED_BY_UPSTREAM, msg


def _project(tmp_path, *, with_layers):
    p = tmp_path / "proj"
    d = p / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    if with_layers:
        (d / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
            {"doc_class": "L9_INTEGRATION_SPEC", "ports": []}))
        (d / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
            {"doc_class": "L19_CONSTRAINTS_PDK", "pdk": "gf180mcuD"}))
    return p


def test_end_to_end_the_gate_no_longer_reports_a_cascade(tmp_path):
    """Behavioural, through the real gate and the real classifier."""
    import _flow_reason_taxonomy as tax
    proj = _project(tmp_path, with_layers=True)
    out = tmp_path / "l9.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "l9_floorplan_contract_check.py"),
         str(proj), "--json", str(out)], capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    reason = json.loads(out.read_text())["summary"]["skipped_reason"]
    assert "mandates no floorplan" in reason
    assert tax.infer_nonverdict_reason(
        verdict="VACUOUS_PASS", message=reason) != tax.BLOCKED_BY_UPSTREAM

    proj2 = _project(tmp_path / "b", with_layers=False)
    out2 = tmp_path / "l9b.json"
    subprocess.run(
        [sys.executable, str(PROGRAMS / "l9_floorplan_contract_check.py"),
         str(proj2), "--json", str(out2)], capture_output=True, text=True)
    reason2 = json.loads(out2.read_text())["summary"]["skipped_reason"]
    assert tax.infer_nonverdict_reason(
        verdict="VACUOUS_PASS", message=reason2) == tax.BLOCKED_BY_UPSTREAM
