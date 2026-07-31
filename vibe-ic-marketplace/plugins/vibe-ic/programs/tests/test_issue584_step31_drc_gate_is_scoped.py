"""#584 — two sign-off gates reported different DRC counts for the same GDS.

Step 31 (`drc_report_check`) said 3; step 36 (`tapeout_signoff_check`) said 1.
The physical truth was 1. Step 31's number was inflated because discovery in
`eda_report_audit` is a project-wide `rglob` and `real_violation_total` is
SUMMED across every hit — and a completed run tree holds several copies of the
same report once snapshot directories exist.

MEASURED on `benchmark-data/ic/caravel_user_project`, which carries three
`drc_signoff.rpt` (one declared, two under `clean_run_*` snapshots):

    drc_report_check . --mode drc                      files_found 12  total 102
    drc_report_check . --mode drc --under reports/phase3  files_found  2  total  51

The `--under` mechanism already existed for exactly this — `eda_report_audit`
documents the same failure at step 21 and step 21's gate already passes it.
Step 31 is the sibling that never got it.

WHY THE EXISTING DE-DUPLICATION DOES NOT HELP: discovery keeps a `seen` set
keyed on `Path.resolve()`. Three copies at three paths are three distinct paths,
so path de-duplication cannot collapse them. Content de-duplication would be a
different mechanism, and on this corpus it would not fire either — the three
caravel copies are NOT byte-identical (three distinct sha256), so they are
genuinely different reports from different runs, which is exactly why summing
them is wrong rather than merely redundant.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

_PLUGIN = pathlib.Path(__file__).resolve().parents[2]
FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"


def _step(doc, step_id):
    found = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("id") == step_id:
                found.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    assert found, f"step {step_id} not in the flow"
    return found[0]


def _gate_commands(gate):
    out = []
    if isinstance(gate, dict):
        for key, val in gate.items():
            if key in ("program_exit_zero", "optional_program_exit_zero"):
                out.append(val["command"] if isinstance(val, dict) else val)
            else:
                out.extend(_gate_commands(val))
    elif isinstance(gate, list):
        for item in gate:
            out.extend(_gate_commands(item))
    return out


@pytest.fixture(scope="module")
def flow():
    return yaml.safe_load(FLOW.read_text(encoding="utf-8"))


def _drc_command(flow, step_id):
    cmds = [c for c in _gate_commands(_step(flow, step_id).get("gate"))
            if "drc_report_check" in c]
    assert cmds, f"step {step_id} has no drc_report_check gate"
    return cmds[0]


# ── the fix ──────────────────────────────────────────────────────────────────
def test_step31_drc_gate_is_scoped(flow):
    """The defect: an unscoped gate sums every copy in the run tree."""
    cmd = _drc_command(flow, 31)
    assert "--under" in cmd, (
        "step 31's DRC gate is project-wide again; a run tree with snapshot "
        "directories will sum their violations into this step's verdict")


def test_step31_is_scoped_to_what_it_declares(flow):
    """Scoping to the WRONG subtree is a different wrong answer.

    Step 31 declares `reports/phase3/drc_signoff.rpt`, so `reports/phase3` is
    the subtree that contains its own evidence and nothing else's.
    """
    step = _step(flow, 31)
    # `required_outputs`, not `artifacts` — read from the flow's real schema
    # rather than assumed. An assumed key name yields an empty list, and an
    # empty list makes every `any(...)` below vacuously false, so this test
    # would have failed for the wrong reason.
    declared = [a for a in (step.get("required_outputs") or [])
                if isinstance(a, str) and "drc" in a]
    assert any("reports/phase3" in a for a in declared), (
        f"step 31 no longer declares a drc artefact under reports/phase3: "
        f"{declared}")
    unders = re.findall(r"--under\s+(\S+)", _drc_command(flow, 31))
    assert unders, "no --under argument to check"
    for u in unders:
        assert any(u in a or a.startswith(u) for a in declared), (
            f"--under {u} does not correspond to anything step 31 declares "
            f"({declared}) — the gate would read someone else's evidence")


# ── the accept case, so this is not a one-step patch ─────────────────────────
def test_step21_stays_scoped(flow):
    """Step 21 had this fix already. A change that scoped 31 by unscoping 21
    would satisfy the tests above and move the defect rather than remove it."""
    assert "--under" in _drc_command(flow, 21)


def test_no_drc_gate_in_the_flow_is_unscoped(flow):
    """The general form. Two steps are known; a third added later without
    `--under` inherits the same summing defect silently."""
    doc = flow
    unscoped = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and o.get("gate") is not None:
                for c in _gate_commands(o["gate"]):
                    if "drc_report_check" in c and "--under" not in c:
                        unscoped.append((o["id"], c[:70]))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    assert not unscoped, (
        f"drc_report_check invoked project-wide at step(s): {unscoped} — "
        f"discovery is an rglob and real_violation_total is summed across hits")
