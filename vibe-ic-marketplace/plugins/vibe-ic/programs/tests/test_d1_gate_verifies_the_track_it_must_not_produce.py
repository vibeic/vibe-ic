#!/usr/bin/env python3
"""test_d1_gate_verifies_the_track_it_must_not_produce.py

D1's gate clause WAS the producer of D1's own declared output.

`flow_compliance_check` is the acceptance auditor: it runs each step's gate and
then reports whether that step's `required_outputs` are present. Step D1
declares `reports/audit/phase1/expert_parse_track.json`, and its gate carried

    - program_exit_zero: "phase1_expert_parse_track ."

which is the program that WRITES that report. So on any tree that did not
already have it, the audit created the artefact and then certified it, and the
clause could never fail for the one thing the yaml says it is there to catch —
"a second track that can quietly not run is the same as no second track".

MEASURED on origin/main 74ac9fa78, one whole `flow_compliance_check` per root,
on a FRESH `copytree` per arm — a shared tree is not an A/B when the probe is
also a producer:

    root                              report present before   audit created it
    ic/u_hawaii_adc                          no                     YES
    ic/caravel_user_project                  no                     YES
    ic/sha256                                no                     YES
    ic/subservient                           no                     YES
    ic/spm/v1.5.58_ihp-sg13g2                no                     YES
    ic/spm/v1.9.96_gf180mcuD                 yes                    no
    ic/u_hawaii_adc/v1.9.86_sky130A          yes                    no

FIVE of seven, not the one `test_d3_the_compliance_audit_does_not_create_
declared_outputs` names — that pin drives three roots and only one of them
lacked the report, so it saw the narrowest possible slice of a defect that was
already general.

THE REMEDY IS THE ONE THAT PIN'S OWN ASSERTION STATES: "Move the producer to
the runner that owns the step; the audit must measure a tree it did not touch."
`phase1_one_shot_runner` already runs the track, so only the gate had to stop
doing it. Same shape as A8's withdrawn `analog_hardmacro_gds_emit` clause and
as `metal_fill_emit --verify-only`.

WHAT IS PINNED HERE
  * `--verify-only` NEVER writes — not the report, not anything;
  * it still FAILS loudly for absent / unparseable / another producer's file at
    the declared path, which is the whole of what the clause was for;
  * the two modes agree on what a verdict COSTS, through one table, so
    VACUOUS_PASS and REFUSED cannot come to mean different things in the gate
    than in the runner;
  * D1's clause in the flow yaml carries `--verify-only`, so re-instating the
    producer reddens HERE by name rather than only in a 500-second aggregate.

chip-AGNOSTIC: no design, PDK, vendor or SKU literal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parents[1]
PROGRAMS = PLUGIN
PROGRAM_PATH = PLUGIN / "phase1_expert_parse_track.py"
FLOW_YAML = PLUGIN.parent / "flow" / "phase1_phase2_phase3.yaml"
REPORT_REL = "reports/audit/phase1/expert_parse_track.json"

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase1_expert_parse_track as EPT  # noqa: E402


def _run(project: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(PROGRAM_PATH), str(project), *extra],
        capture_output=True, text=True, timeout=120)


def _snapshot(root: Path):
    return {p.relative_to(root): p.stat().st_mtime_ns
            for p in root.rglob("*") if p.is_file()}


def _plant(project: Path, verdict: str = "PASS", program: str = EPT.PROGRAM):
    """A report shaped like the one the RUNNER leaves behind."""
    target = project / REPORT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "program": program,
        "version": getattr(EPT, "VERSION", "test"),
        "verdict": verdict,
        "findings": [],
        "denominator": {"total": 4, "deterministic": 3, "ai": 1},
        "ai_subtrack": {"status": "CONSUMED"},
    }, indent=2) + "\n")
    return target


# ──────────────────────────────────────────────────────────────────────
# The producing half must stay OUT of the gate
# ──────────────────────────────────────────────────────────────────────
def test_verify_only_writes_nothing_at_all(tmp_path):
    """The defect, stated as a property of the program rather than of a run."""
    project = tmp_path / "proj"
    project.mkdir()
    _plant(project)
    before = _snapshot(project)

    res = _run(project, "--verify-only")

    after = _snapshot(project)
    assert set(after) == set(before), (
        f"--verify-only created {sorted(set(after) - set(before))}. A gate that "
        f"writes the artefact the same audit then reports as present has "
        f"certified its own output.\n{res.stdout}\n{res.stderr}")
    assert after == before, (
        f"--verify-only MODIFIED {sorted(k for k in after if after[k] != before.get(k))}")
    assert res.returncode == EPT.RC_BY_VERDICT["PASS"], res


def test_the_producer_really_does_write_it_so_the_control_is_not_vacuous(
        tmp_path):
    """THE NEGATIVE CONTROL. Without it the test above proves nothing.

    If the program could not write this report on this input at all, "verify-
    only wrote nothing" would be true of every mode and would measure nothing.
    """
    project = tmp_path / "proj"
    project.mkdir()
    before = _snapshot(project)

    _run(project)                       # the PRODUCING form, as the gate was

    after = _snapshot(project)
    created = sorted(str(p) for p in (set(after) - set(before)))
    assert any(c.endswith("expert_parse_track.json") for c in created), (
        f"the producing form wrote no report on this input ({created}), so "
        f"`test_verify_only_writes_nothing_at_all` is vacuous and proves "
        f"nothing about the mode it names")


# ──────────────────────────────────────────────────────────────────────
# ...and the clause must still catch what it was there to catch
# ──────────────────────────────────────────────────────────────────────
def test_verify_only_fails_when_the_track_never_ran(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    before = _snapshot(project)

    res = _run(project, "--verify-only")

    assert res.returncode == 1, res
    assert "no report" in (res.stderr + res.stdout), res.stderr
    assert _snapshot(project) == before, (
        "the failing path wrote something; a gate must not leave the tree it "
        "refused in a state where the next run passes")


def test_verify_only_fails_on_an_unparseable_report(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    target = project / REPORT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not json")

    res = _run(project, "--verify-only")
    assert res.returncode == 1, res
    assert "does not parse" in res.stderr, res.stderr


def test_verify_only_fails_on_another_producers_file_at_the_path(tmp_path):
    """The `foreign payload` case, which absence alone would not catch.

    A file IS at the declared path and it parses, so a presence check passes.
    It is not this track's report, so the track still never ran.
    """
    project = tmp_path / "proj"
    project.mkdir()
    _plant(project, program="some_other_producer")

    res = _run(project, "--verify-only")
    assert res.returncode == 1, res
    assert "not this program's report" in res.stderr, res.stderr


@pytest.mark.parametrize("verdict", sorted(EPT.RC_BY_VERDICT))
def test_the_gate_and_the_runner_agree_on_what_a_verdict_costs(
        tmp_path, verdict):
    """One table, both modes. Two copies is how they would come to disagree."""
    project = tmp_path / "proj"
    project.mkdir()
    _plant(project, verdict=verdict)
    res = _run(project, "--verify-only")
    assert res.returncode == EPT.RC_BY_VERDICT[verdict], (
        f"{verdict}: --verify-only exited {res.returncode}, the shared table "
        f"says {EPT.RC_BY_VERDICT[verdict]}\n{res.stdout}\n{res.stderr}")


def test_verify_only_refuses_a_verdict_this_program_cannot_have_written(
        tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _plant(project, verdict="TOTALLY_FINE")
    res = _run(project, "--verify-only")
    assert res.returncode == 1, res
    assert "cannot have written" in res.stderr, res.stderr


# ──────────────────────────────────────────────────────────────────────
# ...and the flow must actually USE it
# ──────────────────────────────────────────────────────────────────────
def _d1_clauses():
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))

    def walk(o):
        if isinstance(o, dict):
            if str(o.get("id")) == "D1":
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)

    steps = list(walk(doc))
    assert len(steps) == 1, f"expected exactly one step D1, found {len(steps)}"
    gate = steps[0].get("gate") or {}
    out = []
    for clause in gate.get("all_of") or []:
        if isinstance(clause, dict):
            out.extend(str(v) for v in clause.values())
    assert out, "step D1 has no gate clauses at all"
    return out


def test_the_flow_invokes_the_verifying_form_not_the_producing_one():
    """The wiring, checked in the yaml, because that is where it can rot.

    The program can grow a perfect `--verify-only` and the flow can go on
    calling the producer; nothing else in the suite would say so until a
    500-second census went NORECORD.
    """
    producing = [c for c in _d1_clauses()
                 if c.split()[0] == EPT.PROGRAM and "--verify-only" not in c]
    assert not producing, (
        f"step D1's gate invokes the PRODUCING form of {EPT.PROGRAM}: "
        f"{producing}. D1 declares {REPORT_REL}, which that form writes, so "
        f"the audit would create the artefact it then reports as present. Use "
        f"`{EPT.PROGRAM} . --verify-only`; production belongs to "
        f"phase1_one_shot_runner.")

    assert any(c.split()[0] == EPT.PROGRAM and "--verify-only" in c
               for c in _d1_clauses()), (
        f"step D1 no longer verifies the second track at all. A second track "
        f"that can quietly not run is the same as no second track — the "
        f"clause must stay, in its verifying form.")
