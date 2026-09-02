"""Per-CLAUSE non-vacuity for step 37.5ic's gate.

`test_path_step_matrix_ic_and_ip` asserts the step's gate does not pass an
empty tree, one assertion loop per matrix row. It is the right guard and it is
not enough on its own: it names the FIRST clause that exits 0 and stops, so a
second vacuous clause hides behind the first, and a fix is reported per ROW
rather than per GATE.

This module asks the two questions per clause.

  1. DOES IT REFUSE A TREE IT CANNOT HAVE LOOKED AT?  A tree carrying only
     `input/submission_template/SELF_TAPEOUT.txt` has no floorplan, no routed
     DEF, no GDS and no metrics. rc 1 (a finding) and rc 2 (`[CANNOT CHECK]`)
     are both answers; rc 0 is not.

  2. DOES IT LOOK AT THE PROJECT AT ALL?  A clause whose behaviour is
     BYTE-IDENTICAL on a bare tree and on a tree carrying phase-3 artefacts
     never opened either. That is the failure mode this module was written for:
     MEASURED 2026-09-02, `closed_loop_executed_reentry_census` exited 0 on
     every project because `_plugin_root` falls back to the SHIPPED tree when
     the root carries no `programs/` -- the same rc for every design and for a
     directory holding one file. Question 1 alone catches that only while the
     answer happens to be 0; question 2 catches it whatever the answer is.

A vacuous guard has one direction, so both are asserted: refusing everything is
not a pass either, and question 2 is what says so.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

HERE = Path(__file__).resolve()
PROGRAMS = HERE.parents[1]
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
STEP = "37.5ic"


def _clauses(step_id: str):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for value in doc.values():
        if not isinstance(value, list):
            continue
        for step in value:
            if isinstance(step, dict) and str(step.get("id")) == step_id:
                out = []
                for group in (step.get("gate") or {}).values():
                    if not isinstance(group, list):
                        continue
                    for clause in group:
                        for kind, spec in clause.items():
                            cmd = spec if isinstance(spec, str) else (
                                spec or {}).get("command")
                            if cmd:
                                out.append((kind, cmd))
                return out
    raise AssertionError(f"step {step_id} is not in {FLOW}")


CLAUSES = _clauses(STEP)
#: A clause whose exit code can DENY the step its tier.
BLOCKING = [c for k, c in CLAUSES if not k.startswith("advisory_")]
ADVISORY = [c for k, c in CLAUSES if k.startswith("advisory_")]
ALL = [c for _k, c in CLAUSES]


def _bare(root: Path) -> Path:
    """A tree carrying the router file and nothing else."""
    marker = root / "input" / "submission_template" / "SELF_TAPEOUT.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("# tapeout_declaration: self tape-out, no operator\n")
    return root


def _with_phase3(root: Path) -> Path:
    """The bare tree plus phase-3 artefacts, so a clause has something to read.

    Deliberately THIN -- a DEF, a log and a metrics file. It is not a signed-off
    run and no clause is expected to PASS on it; what is asserted is only that
    a clause behaves DIFFERENTLY here than on a tree with nothing.
    """
    _bare(root)
    pnr = root / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
    (pnr / "tool.log").write_text("read_lef /pdks/x/libs.ref/y/lef/y.lef\n")
    final = root / "phase3" / "final"
    final.mkdir(parents=True, exist_ok=True)
    (final / "metrics.json").write_text(json.dumps({"design": "top"}))
    gds = root / "phase3" / "stage4" / "gds"
    gds.mkdir(parents=True, exist_ok=True)
    (gds / "top.gds").write_bytes(b"\x00\x06\x00\x02\x00\x07")
    return root


def _run(project: Path, command: str):
    import shlex
    toks = shlex.split(command)
    prog = PROGRAMS / (toks[0] + ".py")
    assert prog.is_file(), f"gate names {toks[0]!r}, which is not a program"
    p = subprocess.run([sys.executable, str(prog)] + toks[1:],
                       cwd=str(project), capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def test_the_step_declares_the_clause_population_this_module_measures():
    """Without this, a clause added to the gate is silently unmeasured."""
    assert len(ALL) >= 6, ALL
    assert len(set(ALL)) == len(ALL), "a clause is declared twice"
    assert BLOCKING and ADVISORY, (
        "this module measures the two kinds differently; a step with only one "
        "of them needs the split re-examined, not silently skipped")


@pytest.mark.parametrize("command", ALL, ids=[c.split()[0] for c in ALL])
def test_the_clause_refuses_a_tree_it_cannot_have_looked_at(command, tmp_path):
    rc, out = _run(_bare(tmp_path / "bare"), command)
    assert rc != 0, (
        f"`{command}` exited 0 on a tree carrying only a router file. A gate "
        f"clause that passes what it cannot have looked at is a vacuous pass.\n"
        f"{out[:800]}")


@pytest.mark.parametrize("command", BLOCKING,
                         ids=[c.split()[0] for c in BLOCKING])
def test_a_blocking_clause_actually_reads_the_project(command, tmp_path):
    """The other direction, and it applies to the clauses that can DENY a tier.

    A clause that answers identically whatever the project contains never
    opened it, so its verdict is a property of the checkout rather than of the
    design — and a BLOCKING clause of that shape decides a design's step on
    evidence about something else.

    MEASURED: `closed_loop_executed_reentry_census` was exactly this. Its
    `_plugin_root` falls back to the SHIPPED tree when the root carries no
    `programs/`, which is right for what it censuses and is what made its exit
    code project-blind — rc 0 for every design and for a one-file directory.
    """
    rc_bare, out_bare = _run(_bare(tmp_path / "bare"), command)
    rc_full, out_full = _run(_with_phase3(tmp_path / "full"), command)
    assert (rc_bare, out_bare) != (rc_full, out_full), (
        f"BLOCKING clause `{command}` produced a BYTE-IDENTICAL answer "
        f"(rc {rc_bare}) on a tree with nothing and on a tree carrying a DEF, "
        f"a tool log, a metrics file and a GDS. A clause that can deny this "
        f"step its tier is not reading the design it grades.\n{out_bare[:800]}")


@pytest.mark.parametrize("command", ADVISORY,
                         ids=[c.split()[0] for c in ADVISORY])
def test_a_project_blind_clause_is_declared_advisory(command, tmp_path):
    """THE INVARIANT, stated the way round that is enforceable.

    Two of this step's clauses ask a question about the FLOW, not about a
    design: whether every required metric key has a producer, and whether a
    declared closed-loop edge could reach one. MEASURED, both answer
    byte-identically on a bare tree and on a tree carrying phase-3 artefacts —
    they are project-blind, and legitimately so.

    That is acceptable ONLY because they are `advisory_program_exit_zero`:
    their rc cannot deny the step its tier. Promote either to blocking without
    teaching it to read the project and this test says so, naming the clause.
    It holds in BOTH directions — it passed before the census fix and after —
    so it can only break by a promotion, which is the change it exists to
    catch.
    """
    rc_bare, out_bare = _run(_bare(tmp_path / "bare"), command)
    rc_full, out_full = _run(_with_phase3(tmp_path / "full"), command)
    if (rc_bare, out_bare) == (rc_full, out_full):
        assert command in ADVISORY, (
            f"`{command}` is project-blind and is NOT declared advisory")
