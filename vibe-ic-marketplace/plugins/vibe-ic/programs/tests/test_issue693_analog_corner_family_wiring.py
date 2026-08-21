"""vibe-ic#693 — the analog-corner family: what is wired, and that it FIRES.

Three gates were referenced from no executable location at all. This file is
the executable half of that PR's claim, because for two of the three the
PUBLISHED CORPUS CANNOT SHOW THEM FIRING: no published root carries an
`A0_skip_decision.json`, and none carries a silent LEVEL=1 substitution. A
blast radius of zero is exactly the state in which "it is wired" and "it can
never run" look identical from the corpus, so the firing has to be proved
against a planted defect, through the flow's own gate evaluator.

What is asserted here:

  1. `analog_a0_skip_forbidden_check` is a BLOCKING clause of D1, and it sits
     AFTER `phase1_all_l_docs_present_check` — it reads L5, so it must not run
     before the gate that establishes the L docs exist.
  2. `analog_corner_lib_realism_lint` is an ADVISORY clause of A4, and it is
     LAST. Measured: `_evaluate_gate` short-circuits `all_of` at the first
     failing sub-gate and re-runs only the LATER advisory entries, and A4's
     gate block already fails on every in-scope published root — so a BLOCKING
     entry in this position executes on none of them.
  3. The advisory RUNS AND REPORTS ITS FINDING even when its blocking sibling
     has already failed. That is the whole reason for the slot; without it the
     wiring would be a gate wired somewhere that never executes.
  4. `analog_corner_margin_check` is wired NOWHERE, on purpose, and that fact
     is recorded in a register a machine reads.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest
import yaml

_PLUGIN = pathlib.Path(__file__).resolve().parents[2]
_PROGRAMS = _PLUGIN / "programs"
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_BASELINE = _PROGRAMS / "checker_execution_wiring_baseline.json"

sys.path.insert(0, str(_PROGRAMS))

_STEPS = {s["id"]: s for s in
          (yaml.safe_load(_FLOW.read_text(encoding="utf-8")).get("steps") or [])
          if isinstance(s, dict) and "id" in s}

_SILENT_LEVEL1_DECK = """* corner deck
.subckt amp vdd vss vin vout
mn1 vout vin vss vss nm w=8u l=1u
.ends
.model nm nmos (LEVEL=1 VTO=0.4 KP=70u)
.model pm pmos (LEVEL=1 VTO=-0.45 KP=28u)
"""


def _clauses(step_id, key):
    return [c[key] for c in _STEPS[step_id]["gate"]["all_of"]
            if isinstance(c, dict) and key in c]


# ── 1. D1: blocking, and after the gate that establishes its input ──────────


def test_a0_gate_is_a_blocking_clause_of_d1():
    cmds = _clauses("D1", "program_exit_zero")
    assert any(c.split()[0] == "analog_a0_skip_forbidden_check" for c in cmds), \
        cmds


def test_a0_gate_runs_after_the_gate_that_establishes_l5():
    """Its sanctioned-replacement branch (b) reads
    `L5.analog_blocks_detected`, so ordering it before the L-doc gate would
    have it judge a tree whose L5 may not exist."""
    cmds = _clauses("D1", "program_exit_zero")
    names = [c.split()[0] for c in cmds]
    assert names.index("analog_a0_skip_forbidden_check") > \
        names.index("phase1_all_l_docs_present_check"), names


def test_a0_gate_is_not_wired_at_an_a_step():
    """A1's condition is FALSE in 2 of the 3 shapes this gate can fail on — an
    agent deciding there are no analog blocks writes no block list, and L5 then
    declares none either. D1 has no `condition:` and runs on every project."""
    for sid, step in _STEPS.items():
        if not str(sid).startswith("A"):
            continue
        blob = json.dumps(step.get("gate") or {})
        assert "analog_a0_skip_forbidden_check" not in blob, sid


# ── 2/3. A4: advisory, last, and it fires ──────────────────────────────────


def test_lint_is_an_advisory_clause_of_a4_and_is_last():
    subs = _STEPS["A4"]["gate"]["all_of"]
    idx = [i for i, c in enumerate(subs)
           if isinstance(c, dict)
           and "analog_corner_lib_realism_lint" in json.dumps(c)]
    assert len(idx) == 1, subs
    i = idx[0]
    assert "advisory_program_exit_zero" in subs[i], subs[i]
    assert i == len(subs) - 1, (
        "the advisory must be LAST: `_evaluate_gate` re-runs only the advisory "
        "entries that come AFTER the sub-gate that failed")


def test_lint_is_not_a_blocking_clause_anywhere_in_the_flow():
    """Not caution — measurement. A4's gate block fails on every in-scope
    published root today, so a blocking entry there executes on none of them."""
    for sid, step in _STEPS.items():
        for c in (step.get("gate") or {}).get("all_of") or []:
            if isinstance(c, dict) and "program_exit_zero" in c:
                assert "analog_corner_lib_realism_lint" not in \
                    c["program_exit_zero"], sid


_REAL_CORNERS = [
    {"name": f"{p}_{t}", "process": p, "temp_c": tc, "simulator_run": True,
     "vout_v": 1.2, "_provenance": "real_ngspice",
     "ngspice_log": "phase3/analog/amp0/pvt.log"}
    for p in ("ss", "tt", "ff")
    for t, tc in (("m40c", -40), ("27c", 27), ("125c", 125))
]


def _a4_tree(root, deck):
    """A block whose corner sweep really ran and which DOES NOT SAY what
    circuit it measured — the shape the incumbent A4 gate fails on across the
    published corpus (`A4_DESIGN_CONTENT_UNDECLARED`)."""
    d = root / "phase3" / "analog" / "amp0"
    d.mkdir(parents=True)
    (d / "amp0.sp").write_text(deck)
    (d / "corner_results.json").write_text(json.dumps(
        {"block": "amp0", "block_type": "ldo", "total_corners": 9,
         "corners": _REAL_CORNERS, "_provenance": "real_ngspice",
         "simulator": "ngspice", "corners_executed": 9,
         "full_pvt_sweep_executed": True, "results_found": True,
         "analysis_status": "ok"}))
    (root / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["amp0"]}))
    return root


@pytest.mark.parametrize("disclosed,expect_finding", [(False, True),
                                                      (True, False)])
def test_the_a4_advisory_actually_runs_and_reports(tmp_path, disclosed,
                                                   expect_finding):
    """END-TO-END through the flow's own gate evaluator, on the REAL A4 gate
    block, with the incumbent blocking sibling ALREADY FAILING.

    `design_content` is deliberately absent, which is what the incumbent A4
    gate fails on today across the published corpus. So this is the exact
    situation the advisory slot exists for: the step is already red, and the
    advisory still has something to say.
    """
    import flow_compliance_check as fcc

    deck = _SILENT_LEVEL1_DECK
    if disclosed:
        deck = deck.replace(
            "* corner deck",
            "* corner deck\n* DOCUMENTED LEVEL=1 STANDIN — no public ngspice\n"
            "* corner library for this process; MODELED, not silicon sign-off.")
    project = _a4_tree(tmp_path, deck)

    passed, reasons = fcc._evaluate_gate(project, _STEPS["A4"]["gate"])
    advisory = [r for r in reasons
                if "analog_corner_lib_realism_lint" in r]
    assert advisory, (
        "the advisory did not run at all — a gate wired somewhere that never "
        "executes is the same defect moved: " + "; ".join(reasons))
    found = any("FINDING" in r for r in advisory)
    assert found is expect_finding, advisory
    assert passed is False, (
        "precondition of this test: the incumbent blocking sibling is expected "
        "to fail here, which is what makes the advisory's survival the point")


def test_the_lint_reads_both_analog_roots():
    """A4's own `required_outputs` accepts `phase2/analog/*/corner_results.json`
    as an alternative, so a lint that read only `phase3/analog/` credited a
    plain PASS to a project whose decks it never opened."""
    required = json.dumps(_STEPS["A4"].get("required_outputs") or [])
    assert "phase2/analog" in required, required
    import analog_corner_lib_realism_lint as lint
    assert "phase2/analog" in lint._ANALOG_ROOTS, lint._ANALOG_ROOTS


# ── 4. the one that stays unwired, recorded where a machine reads it ────────


def test_the_margin_gate_is_wired_nowhere():
    flow = _FLOW.read_text(encoding="utf-8")
    assert "analog_corner_margin_check" not in flow


def test_the_margin_gate_is_recorded_as_unwired_with_a_reason():
    """Being listed is a DISCLOSURE, not permission — but a gate that is
    neither wired NOR listed is invisible, which is the state #693 measured
    130 programs into."""
    d = json.loads(_BASELINE.read_text(encoding="utf-8"))
    assert "analog_corner_margin_check.py" in d["known"], d["known"]
    note = d["triage"]["analog_corner_margin_check.py"]
    # The reason must name BOTH unreachable rules, not just say "unwired".
    assert "voltage axis" in note, note
    assert "TOLERANCE" in note.upper(), note
    assert "analog_a4_corner_sweep_check" in note, note


def test_the_margin_gates_own_header_records_the_same_reason():
    head = (_PROGRAMS / "analog_corner_margin_check.py").read_text(
        encoding="utf-8")[:6000]
    assert "NOT WIRED" in head
    assert "build_pvt_grid" in head


def test_the_skill_no_longer_names_it_as_a4s_gate_of_record():
    """The A4 row named it, and a sentence beside the row promised that the
    A1-A9 gates run inside the analog runner. The runner's A4 entry is
    `analog_a4_corner_sweep_check`; this program appears nowhere in it."""
    skill = (_PLUGIN / "skills" / "analog-output-verify" /
             "SKILL.md").read_text(encoding="utf-8")
    assert "analog_corner_margin_check" not in skill
    assert "analog_a4_corner_sweep_check" in skill
    runner = (_PROGRAMS / "analog_one_shot_runner.py").read_text(
        encoding="utf-8")
    assert "analog_corner_margin_check" not in runner


def test_the_margin_gate_still_runs_standalone():
    """Unwired is not the same as deleted: it keeps its tests and its CLI, so
    the producer fix that makes it wireable can be measured against it."""
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "analog_corner_margin_check.py"),
         str(_PROGRAMS)], capture_output=True, text=True)
    assert r.returncode in (0, 1, 2), r.stderr
