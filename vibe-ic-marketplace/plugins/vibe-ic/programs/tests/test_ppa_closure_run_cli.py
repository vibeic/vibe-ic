#!/usr/bin/env python3
"""The CLI's exit code is the only part of this lane a flow gate can read.

Every case below is a real `subprocess.run` of the shipped program, because the
thing under test is the PROCESS EXIT CODE and calling `main()` in-process proves
something adjacent to it. Each exit code is asserted against a case that has
actually shipped wrong somewhere in this repository:

    0   green, and only for a loop that really converged or a trigger that
        really did not fire
    1   a finding about the DESIGN, and only after a real measurement
    2   NOT CHECKED, with a printed marker so it can never read as a silent skip
    3   BAD INVOCATION, never a design FAIL

THE VACUOUS FIXTURE IS THE ONE THAT MATTERS. A gate whose declared invocation
exits 2 on absent input can never fail, and this repository has shipped that
twice — so `test_the_declared_invocation_can_actually_fail` runs the SAME argv
over a good tree and a bad one and asserts the two answers differ.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PLUGIN = pathlib.Path(__file__).resolve().parents[2]
CLI = PLUGIN / "programs" / "ppa_closure_run.py"
REGISTRY = PLUGIN / "config" / "ppa_actuator_registry.yaml"
CONTROLLER = "pnr.deck.hold_block_emission"

RC_OK, RC_FINDING, RC_NOT_CHECKED, RC_BAD_INVOCATION = 0, 1, 2, 3

DECK_VIOLATION = ("# P&R deck\nset_wire_rc -layer met3\nrepair_design\n"
                  "repair_timing -setup\ndetailed_route\n")
DECK_CLEAN = ("set_wire_rc -layer met3\nestimate_parasitics -placement\n"
              "repair_design\nrepair_timing -setup\nrepair_timing -hold\n")


def run(*args, **kw):
    return _pr.run([sys.executable, str(CLI), *[str(a) for a in args]],
                          capture_output=True, text=True, **kw)


def _impl(tmp_path, deck: str, name="impl") -> pathlib.Path:
    root = tmp_path / name
    root.mkdir()
    (root / "pnr.tcl").write_text(deck, encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# POSITIVE
# --------------------------------------------------------------------------

def test_positive_a_deck_with_nothing_wrong_exits_zero(tmp_path):
    p = run(_impl(tmp_path, DECK_CLEAN), "--controller", CONTROLLER)
    assert p.returncode == RC_OK, p.stderr
    assert "NOT_TRIGGERED" in p.stdout
    assert "closed_loop_success=True" in p.stdout


def test_positive_verify_registry_exits_zero_when_every_claim_resolves():
    p = run("--verify-registry")
    assert p.returncode == RC_OK, p.stderr
    assert "every EXECUTABLE claim resolves" in p.stdout


# --------------------------------------------------------------------------
# NEGATIVE — RED when it should be red.
# --------------------------------------------------------------------------

def test_negative_a_real_residual_violation_exits_one(tmp_path):
    p = run(_impl(tmp_path, DECK_VIOLATION), "--controller", CONTROLLER)
    assert p.returncode == RC_FINDING, p.stdout + p.stderr
    assert "closed_loop_success=False" in p.stdout
    assert "RESIDUAL" in p.stderr, "the residual is printed, not summarised away"
    assert "NOT repaired, still open" in p.stderr


def test_negative_a_collateral_regression_is_printed_by_name(tmp_path):
    p = run(_impl(tmp_path, DECK_VIOLATION), "--controller", CONTROLLER)
    assert "missing_required_commands: 0.0 -> 3.0" in p.stdout + p.stderr


def test_the_declared_invocation_can_actually_fail(tmp_path):
    """A gate that passes is not a gate that discriminates. SAME argv shape,
    two trees, two different answers."""
    good = run(_impl(tmp_path, DECK_CLEAN, "good"), "--controller", CONTROLLER)
    bad = run(_impl(tmp_path, DECK_VIOLATION, "bad"), "--controller", CONTROLLER)
    assert good.returncode == RC_OK
    assert bad.returncode == RC_FINDING
    assert good.returncode != bad.returncode


# --------------------------------------------------------------------------
# VACUOUS — missing input is 2 or 3, never 0 and never 1.
# --------------------------------------------------------------------------

def test_vacuous_an_implementation_root_with_no_deck_is_not_checked(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    p = run(empty, "--controller", CONTROLLER)
    assert p.returncode == RC_NOT_CHECKED, p.stdout + p.stderr
    assert "[CANNOT CHECK]" in p.stderr
    assert "NOT_MEASURED" in p.stdout


def test_vacuous_a_missing_implementation_root_is_a_bad_invocation(tmp_path):
    p = run(tmp_path / "nope", "--controller", CONTROLLER)
    assert p.returncode == RC_BAD_INVOCATION, p.stdout + p.stderr
    assert "is not a directory" in p.stderr


def test_vacuous_a_missing_registry_is_not_checked(tmp_path):
    p = run(_impl(tmp_path, DECK_CLEAN), "--edge", "20",
            "--registry", tmp_path / "absent.yaml")
    assert p.returncode == RC_NOT_CHECKED, p.stdout + p.stderr
    assert "[CANNOT CHECK]" in p.stderr
    assert "not found" in p.stderr


def test_vacuous_an_unreadable_registry_is_not_checked(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("{{{{ not yaml at all", encoding="utf-8")
    p = run(_impl(tmp_path, DECK_CLEAN), "--edge", "20", "--registry", bad)
    assert p.returncode == RC_NOT_CHECKED, p.stdout + p.stderr
    assert "[CANNOT CHECK]" in p.stderr


def test_vacuous_a_registry_declaring_no_edges_is_a_refusal(tmp_path):
    """A ZERO DENOMINATOR IS A REFUSAL. Without this, "21 declared, 0 bound"
    and "nothing declared at all" would print the same reassuring number."""
    import yaml
    doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    doc["edges"] = {}
    empty = tmp_path / "noedges.yaml"
    empty.write_text(yaml.safe_dump(doc), encoding="utf-8")
    p = run("--list-edges", "--registry", empty)
    assert p.returncode == RC_NOT_CHECKED, p.stdout + p.stderr
    assert "declares no edges" in p.stderr


# --------------------------------------------------------------------------
# DECLARED_ONLY — the honesty requirement, at the process boundary.
# --------------------------------------------------------------------------

def test_a_declared_only_edge_is_not_checked_and_never_green(tmp_path):
    p = run(_impl(tmp_path, DECK_VIOLATION), "--edge", "20")
    assert p.returncode == RC_NOT_CHECKED, p.stdout + p.stderr
    assert "[CANNOT CHECK]" in p.stderr
    assert "must not be displayed as one" in p.stderr
    assert "closed_loop_success=False" in p.stdout


def test_list_edges_refuses_while_no_edge_has_an_executable_controller():
    """rc=2, not 0. An inventory that always exits 0 is a listing today and a
    false green the moment somebody wires it into a gate."""
    p = run("--list-edges")
    assert p.returncode == RC_NOT_CHECKED, p.stdout + p.stderr
    assert "[CANNOT CHECK]" in p.stderr
    assert "21 declared edges, 0 BOUND, 21 DECLARED_ONLY" in p.stdout
    assert "DECLARED_ONLY" in p.stdout


def test_every_declared_flow_edge_is_listed():
    """The listing is the whole denominator, not the interesting subset."""
    import yaml
    flow = yaml.safe_load(
        (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text(encoding="utf-8"))
    declared = [str(s["id"]) for s in flow["steps"] if s.get("closed_loop")]
    p = run("--list-edges")
    for edge_id in declared:
        assert f"edge {edge_id:>5}" in p.stdout, edge_id


# --------------------------------------------------------------------------
# BAD INVOCATION — never a design FAIL.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("args", [
    ("--edge", "999"),
    ("--controller", "no.such.controller"),
])
def test_an_undeclared_name_is_a_bad_invocation(tmp_path, args):
    p = run(_impl(tmp_path, DECK_CLEAN), *args)
    assert p.returncode == RC_BAD_INVOCATION, p.stdout + p.stderr
    assert "is not declared" in p.stderr


def test_giving_both_or_neither_of_edge_and_controller_is_a_bad_invocation(tmp_path):
    impl = _impl(tmp_path, DECK_CLEAN)
    both = run(impl, "--edge", "20", "--controller", CONTROLLER)
    neither = run(impl)
    assert both.returncode == RC_BAD_INVOCATION
    assert neither.returncode == RC_BAD_INVOCATION


def test_no_refusal_path_exits_one():
    """rc=1 IS A CLAIM ABOUT SILICON. Two shipped gates refused with a bare
    `SystemExit("...")`, which exits 1, and a run that never opened an image
    reported a hard finding. Asserted on the parsed source so it survives a
    refactor: no `SystemExit` carrying a string, anywhere in this lane."""
    import ast
    for rel in ("programs/ppa_closure_run.py", "programs/_ppa/closure.py"):
        tree = ast.parse((PLUGIN / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                name = ast.unparse(node.exc.func)
                assert name != "SystemExit", (
                    f"{rel}:{node.lineno} raises SystemExit, which exits 1 — "
                    f"and 1 means a finding about the design")


# --------------------------------------------------------------------------
# The --json record.
# --------------------------------------------------------------------------

def test_the_json_record_is_written_and_is_complete(tmp_path):
    out = tmp_path / "run.json"
    p = run(_impl(tmp_path, DECK_VIOLATION), "--controller", CONTROLLER,
            "--json", out)
    assert p.returncode == RC_FINDING
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "vibeic.ppa.closure_run.v1"
    assert doc["closed_loop_success"] is False
    assert doc["digest"].startswith("sha256:")
    assert doc["registry_digest"].startswith("sha256:")
    assert doc["residual"]["visible"] is True
    assert doc["iterations"][0]["digest_restored"] == \
        doc["iterations"][0]["digest_before"]
    assert doc["flow_steps_not_rerun_in_process"], (
        "the record states which flow steps a full re-run would additionally "
        "have to execute")


def test_the_json_record_is_canonical_bytes(tmp_path):
    """It is hashed, so it is written through the one serializer."""
    out = tmp_path / "run.json"
    run(_impl(tmp_path, DECK_VIOLATION), "--controller", CONTROLLER, "--json", out)
    raw = out.read_text(encoding="utf-8")
    assert not raw.endswith("\n")
    assert '", "' not in raw, "canonical_json uses no spaces after separators"


def test_a_not_measured_row_is_printed_rather_than_omitted(tmp_path):
    """A report prints the literal NOT_MEASURED row; it does not drop it —
    otherwise "nobody looked" becomes "nothing to see"."""
    empty = tmp_path / "empty"
    empty.mkdir()
    p = run(empty, "--controller", CONTROLLER)
    assert "NOT_MEASURED" in p.stdout
