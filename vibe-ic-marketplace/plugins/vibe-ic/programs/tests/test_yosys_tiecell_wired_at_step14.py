"""The tie-cell recipe-ordering gate is WIRED at flow Step 14, it RUNS, and it
is ADVISORY (records a FINDING without failing the step).

Why each half is pinned:

  * WIRED — `yosys_tiecell_recipe_order_check` was referenced from no
    executable location at all: not the flow YAML, not another program, not
    `tools/`, not a hook. Its own unit tests were the only thing that ever ran
    it, so the two ordering rules it encodes had never been applied to a real
    synthesis recipe.

  * IT RUNS, AND IN THE RIGHT ARG SHAPE — the gate used to accept ONLY
    `--ys-file`, while every Step-14 gate is invoked as
    `<project_dir> --json <out>`. Measured on the pristine tree that shape
    answered `error: the following arguments are required: --ys-file` with
    rc 2, and `flow_compliance_check._check_program_exit_zero` maps rc 2 to a
    VACUOUS_PASS — so the naive wiring would have been permanently, silently
    green. A gate wired somewhere it never executes is the same defect moved,
    which is why this test drives the REAL executor rather than asserting the
    YAML text.

  * ADVISORY — `phase3_one_shot_runner` never emits `setundef -zero`, so a
    BLOCKING wiring would redden every real-PDK run the canonical runner
    produces. `advisory_program_exit_zero` is the slot that runs a gate and
    records its verdict without failing the step.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

GATE = "yosys_tiecell_recipe_order_check"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

_INLINE = "-- Running command `{cmd}' --\n"
_DIRTY = ("read_verilog -sv a.v; synth -top t -flatten; "
          "dfflibmap -liberty /p/lib.lib; abc -liberty /p/lib.lib; "
          "hilomap -hicell HI Y -locell LO Y; clean; write_verilog out.v")
_CLEAN = ("read_verilog -sv a.v; synth -top t -flatten; "
          "dfflibmap -liberty /p/lib.lib; abc -liberty /p/lib.lib; "
          "setundef -zero; hilomap -hicell HI Y -locell LO Y; splitnets; "
          "clean; write_verilog out.v")


def _step14() -> dict:
    doc = yaml.safe_load(FLOW.read_text())
    steps = [s for s in doc["steps"] if s.get("id") == 14]
    assert steps, "flow Step 14 disappeared"
    return steps[0]


def _advisory_entry(step: dict) -> dict:
    subs = step["gate"]["all_of"]
    hits = [s["advisory_program_exit_zero"] for s in subs
            if isinstance(s, dict) and "advisory_program_exit_zero" in s
            and GATE in s["advisory_program_exit_zero"].get("command", "")]
    assert len(hits) == 1, f"expected exactly one advisory entry for {GATE}"
    return hits[0]


def _project(tmp_path: Path, cmd: str) -> Path:
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "synth.log").write_text(_INLINE.format(cmd=cmd))
    (synth / "netlist.v").write_text(
        "module top (input a, output y);\n  BUF _0_ (.A(a), .Y(y));\nendmodule\n")
    return tmp_path


def test_step14_declares_the_gate() -> None:
    step = _step14()
    assert GATE in step["programs"]
    entry = _advisory_entry(step)
    cmd = entry["command"]
    # the project-dir shape, NOT the flag-only one that argparse rejects
    assert cmd.split()[1] == ".", cmd
    assert "--ys-file" not in cmd, cmd
    assert entry["condition_files_exist"] == ["phase2/stage2/synth"]


def test_the_declared_shape_reaches_a_verdict_not_a_usage_error(
        tmp_path: Path) -> None:
    """The exact regression: the flag-only CLI answered rc 2 (-> VACUOUS_PASS)
    to `<project_dir> --json <out>`, so wiring it would have been permanently
    green. The declared shape must now reach a real verdict."""
    import yosys_tiecell_recipe_order_check as T
    project = _project(tmp_path, _DIRTY)
    rc = T.main([str(project), "--json", str(tmp_path / "rep.json")])
    assert rc == 1, "the declared shape must produce a VERDICT, not rc 2"
    # a usage error is still a usage error
    with pytest.raises(SystemExit) as excinfo:
        T.main(["--json", str(tmp_path / "x.json")])
    assert excinfo.value.code == 2


def test_the_wiring_fires_on_a_violating_recipe(tmp_path: Path) -> None:
    import flow_compliance_check as F
    project = _project(tmp_path, _DIRTY)
    passed, reasons = F._evaluate_gate(
        project, {"all_of": [{"advisory_program_exit_zero":
                              _advisory_entry(_step14())}]})
    assert passed is False
    records = [r for r in reasons
               if r.startswith(F._ADVISORY_RECORD_HINT_PREFIX)]
    assert records, reasons
    assert any('"enforcement": "BLOCKING"' in r for r in records)
    assert any(GATE in r for r in records)


def test_the_wiring_reports_ok_on_a_conformant_recipe(tmp_path: Path) -> None:
    import flow_compliance_check as F
    project = _project(tmp_path, _CLEAN)
    passed, reasons = F._evaluate_gate(
        project, {"all_of": [{"advisory_program_exit_zero":
                              _advisory_entry(_step14())}]})
    assert passed is True
    records = [r for r in reasons
               if r.startswith(F._ADVISORY_RECORD_HINT_PREFIX)]
    assert records, reasons
    assert any('"enforcement": "PASSED"' in r for r in records)


def test_a_project_with_no_recipe_is_recorded_as_not_applicable(
        tmp_path: Path) -> None:
    """NOT CHECKED (rc 2) must reach the advisory record as `n/a`, never as
    `ok`. 15 of the 16 published projects with a mapped netlist land here."""
    import flow_compliance_check as F
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text(
        "module top (input a, output y);\n  BUF _0_ (.A(a), .Y(y));\nendmodule\n")
    passed, reasons = F._evaluate_gate(
        tmp_path, {"all_of": [{"advisory_program_exit_zero":
                               _advisory_entry(_step14())}]})
    assert passed is True
    records = [r for r in reasons
               if r.startswith(F._ADVISORY_RECORD_HINT_PREFIX)]
    assert records, reasons
    assert any('"enforcement": "DISCLOSED_INCOMPLETE"' in r
               for r in records)
    assert not any("ok:" in r for r in reasons)
