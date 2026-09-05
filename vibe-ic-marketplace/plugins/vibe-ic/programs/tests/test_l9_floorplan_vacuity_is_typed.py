"""The floorplan gate's "nothing to examine" must say WHICH nothing it is.

WHAT WAS MEASURED
=================
`l9_floorplan_contract_check` returns rc 2 for two different facts and gives
the flow no way to tell them apart:

  A. the design's L9 / constraint / floorplan docs WERE read, and none of them
     mandates a floorplan — `_effective_die_um` then auto-sizes, so there is no
     verbatim-consumed value for this gate to protect;
  B. no L9 / constraint / floorplan source file and no L19 die-area contract
     exist at all — the layer this gate audits never arrived.

Both were emitted untyped, and the flow clause
(`flow/phase1_phase2_phase3.yaml`) invoked the gate with no `--json`, so
`flow_compliance_check` had nothing but the gate's prose to classify. Measured
on this host over 2,514 L-doc project roots: case A occurs on 2,283 of them and
`_flow_reason_taxonomy.infer_nonverdict_reason` classifies it EXECUTION_ERROR —
the fail-closed default, which states that the program errored. It did not: it
read the design and answered.

WHAT THE FIX IS, AND WHAT IT DELIBERATELY IS NOT
================================================
The gate publishes its OWN reason class, and the flow clause is wired with
`--json` so the class can be read instead of guessed. Case A is
`DESIGN_DECLARED_NA` — the same class this repo's shipped taxonomy already
gives to "no analog blocks", "no inout", "no otp", "no fpga target": an
applicability question answered by scanning the design's own inputs.

Case B stays OUT of the skip-eligible tier. An absent layer is not a design
declaration, and the whole hazard here is emptiness being laundered into
credit.

No N/A CREDIT PATH IS AUTHORED. Case A lands in VACUOUS_PASS — "the gate
examined NOTHING" — which is exactly what happened, and is the tier the gate's
own `_vacuous_exit` rc-2 return was already asking for. It does not reach
`NOT_APPLICABLE`, which `_report_proves_executed_design_na` guards behind a
design-owned typed zero-population declaration this condition does not have.

chip-AGNOSTIC: no design name, PDK name or geometry literal from any real
project appears here.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _flow_reason_taxonomy as rt  # noqa: E402

PROG = PROGRAMS / "l9_floorplan_contract_check.py"
PLUGIN_ROOT = PROGRAMS.parent
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project), *args],
                          capture_output=True, text=True)


def _project(tmp_path: Path, docs: dict[str, str] | None) -> Path:
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    for name, body in (docs or {}).items():
        (gd / name).write_text(body)
    return proj


_SILENT_L9 = (
    "# L9 constraints\n"
    "| knob | value |\n"
    "| --- | --- |\n"
    "| CLOCK_PERIOD | 10 |\n"
)
_AMBIGUOUS_L9 = (
    "# L9 constraints\n"
    "DIE_AREA 0 0 100 100\n"
    "DIE_AREA 0 0 200 200\n"
)


def _report(tmp_path: Path, project: Path) -> dict:
    out = tmp_path / "report.json"
    _run(project, "--json", str(out))
    return json.loads(out.read_text())


def test_a_design_that_mandates_no_floorplan_is_typed_as_declared_na(tmp_path):
    """THE DEFECT, case A: the gate read the layer and had an answer."""
    proj = _project(tmp_path, {"L9_constraints.md": _SILENT_L9})
    assert _run(proj).returncode == 2
    cls = rt.report_reason_class(_report(tmp_path, proj))
    assert cls == rt.DESIGN_DECLARED_NA, f"reason_class={cls!r}"
    assert cls in rt.SKIP_ELIGIBLE


def test_the_flow_reads_the_type_instead_of_guessing_from_prose(tmp_path):
    """End to end through the classifier the flow actually calls."""
    proj = _project(tmp_path, {"L9_constraints.md": _SILENT_L9})
    report = _report(tmp_path, proj)
    p = _run(proj)
    inferred = rt.infer_nonverdict_reason(
        verdict="VACUOUS_PASS",
        message=(p.stdout or "") + (p.stderr or ""),
        explicit=rt.report_reason_class(report))
    assert inferred == rt.DESIGN_DECLARED_NA
    assert inferred in rt.SKIP_ELIGIBLE


def test_the_flow_clause_passes_json_so_the_type_can_be_read():
    """A type nothing opens is not a disclosure."""
    lines = [ln for ln in FLOW_YAML.read_text().splitlines()
             if "command:" in ln and "l9_floorplan_contract_check" in ln]
    assert lines, "the flow no longer invokes l9_floorplan_contract_check"
    for ln in lines:
        assert "--json" in ln, f"wired without --json: {ln.strip()}"


def test_an_absent_layer_is_not_laundered_into_a_design_declaration(tmp_path):
    """NEGATIVE CONTROL, case B. This is the direction that must NOT move."""
    proj = _project(tmp_path, docs=None)
    assert _run(proj).returncode == 2
    cls = rt.report_reason_class(_report(tmp_path, proj))
    assert cls is not None, "case B must be typed too, not left to prose"
    assert cls != rt.DESIGN_DECLARED_NA
    assert cls not in rt.SKIP_ELIGIBLE, (
        f"an absent L9 layer became skip-eligible as {cls!r}")


def test_the_gate_can_still_refuse_a_design_it_does_examine(tmp_path):
    """A gate that cannot fail is not a gate."""
    proj = _project(tmp_path, {"L9_constraints.md": _AMBIGUOUS_L9})
    p = _run(proj)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "L9_DIE_AREA_AMBIGUOUS" in p.stdout


def test_an_unambiguous_floorplan_still_passes(tmp_path):
    """PAIRED GUARD — typing the vacuity must not disturb a real verdict."""
    proj = _project(tmp_path,
                    {"L9_constraints.md": "DIE_AREA 0 0 100 100\n"})
    p = _run(proj)
    assert p.returncode == 0, p.stdout + p.stderr
    assert rt.report_reason_class(_report(tmp_path, proj)) is None


def test_the_report_still_carries_no_bare_verdict_field(tmp_path):
    """PAIRED GUARD against a known cascade.

    `step_internal_fail_bubble_up_check` scans `reports/**/*.json` for a
    top-level string `verdict` and treats FAIL/MISSING as an unbubbled step
    failure. Wiring `--json` here is safe precisely because this gate publishes
    `passed`, not `verdict`; adding one later would manufacture that red.
    """
    proj = _project(tmp_path, {"L9_constraints.md": _AMBIGUOUS_L9})
    assert "verdict" not in _report(tmp_path, proj)
