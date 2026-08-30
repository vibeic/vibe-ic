"""The census is falsified by MUTATION, not asserted.

The trap this file exists to avoid: a census that finds loops because somebody
told it where to look. Every positive result below is paired with a mutation
that BREAKS a running loop, and the census has to notice — while a CONTROL loop,
untouched, keeps its verdict in every arm.

THE SUBJECT is the area re-synthesis loop in `phase3_one_shot_runner.step_synth`:
on a cell area over the declared die it calls `step_synth` again at
`AREA_RETRY_PERIOD_RELAX` and re-measures `chip_area`. It carries BOTH signals,
which is what makes it the only site in the tree where each can be broken alone.

THE CONTROLS are the routing/die feedback loop (`step_pnr -> _docker_exec`) and
the RTL repair retry (`main -> step_rtl_gen`). Neither mutation touches them and
neither may move.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import closed_loop_executed_reentry_census as C  # noqa: E402

PHASE3 = PROGRAMS / "phase3_one_shot_runner.py"
DESIGN = PROGRAMS / "design_one_shot_runner.py"

#: The re-entry the flow's area edge actually executes, quoted from the runner.
AREA_REENTRY = ("                    _area_retry = step_synth(\n"
                "                        project, top, pdk, container,\n"
                "                        period_relax=AREA_RETRY_PERIOD_RELAX)")
#: Its measurement — the line that reads back what the re-entry produced.
AREA_MEASURE = "                    _after = _synth_chip_area(project)"


def _sites(path: Path):
    return {(r["fn"], r["callee"], r["line"]): r for r in C.scan_module(path)}


def _one(path: Path, fn: str, callee: str):
    rows = [r for r in C.scan_module(path)
            if r["fn"] == fn and r["callee"] == callee]
    assert rows, f"no re-entry site {fn} -> {callee} in {path.name}"
    return rows


def _mutate(tmp_path: Path, src: Path, old: str, new: str) -> Path:
    text = src.read_text()
    assert text.count(old) == 1, (
        f"the mutation anchor is not unique in {src.name} "
        f"({text.count(old)} occurrences) — the arm would not be measuring "
        f"what it claims to")
    out = tmp_path / src.name
    out.write_text(text.replace(old, new))
    return out


# ── the population is DERIVED, and it finds the loops nothing declares ───────

def test_the_four_running_loops_are_all_found():
    """Each is named in the program's docstring and in none of the three
    declaration censuses."""
    area = _one(PHASE3, "step_synth", "step_synth")
    assert len(area) == 1 and area[0]["kind"] == "SELF_CALL"
    assert _one(PHASE3, "step_pnr", "_docker_exec")          # loosen + upsize
    assert len(_one(DESIGN, "main", "step_rtl_gen")) >= 2    # RTL repair retry


def test_the_area_loop_carries_both_signals():
    row = _one(PHASE3, "step_synth", "step_synth")[0]
    assert row["verdict"] == C.ACTUATING
    assert row["varying_args"], "the re-entry must pass something its parent did not"
    assert row["measured_name"], "the recursion must be read back after it returns"


def test_the_rtl_repair_retry_is_self_checked_not_actuating():
    """THE SHARPEST CASE. It re-enters `step_rtl_gen` with byte-identical
    arguments — that is WHY it can come back byte-identical — and it carries its
    own anti-cheat for exactly that. A census that only looked for changed
    arguments would call this loop absent."""
    for row in _one(DESIGN, "main", "step_rtl_gen"):
        assert row["verdict"] == C.SELF_CHECKED_ONLY
        assert row["varying_args"] == []
        assert row["measured_name"]


def test_the_declared_edges_and_the_executed_loops_are_disjoint():
    """`REACHABLE=0` is a true statement about the declarations and a false
    impression of the flow."""
    root = PROGRAMS.parents[3]
    edges = C.declared_edges(root)
    assert edges, "the flow declares closed_loop edges"
    reg = C.registered_steps(PROGRAMS)
    assert len(reg) < len(edges), (
        "the hand-maintained actuator register is smaller than the declaration "
        "set it is supposed to cover — that gap IS the root cause")
    sites = C.scan_module(PHASE3) + C.scan_module(DESIGN)
    assert len(sites) > len(reg), (
        "the derived population must exceed the hand register, or this program "
        "has learnt nothing the register did not already say")


# ── FALSIFICATION: break a running loop, the census must notice ─────────────

def test_arm_A_breaking_the_variance_is_noticed(tmp_path):
    """Pass the parameter straight back through. The recursion now re-runs the
    same work; nothing else changes, and the measurement is untouched."""
    mutant = _mutate(tmp_path, PHASE3, AREA_REENTRY,
                     AREA_REENTRY.replace("period_relax=AREA_RETRY_PERIOD_RELAX",
                                          "period_relax=period_relax"))
    row = [r for r in C.scan_module(mutant)
           if r["fn"] == "step_synth" and r["callee"] == "step_synth"][0]
    assert row["verdict"] == C.SELF_CHECKED_ONLY, (
        "an inert re-entry that still measures must fall a tier")
    assert row["varying_args"] == []


def test_arm_B_breaking_both_reads_INERT(tmp_path):
    """Break the variance AND delete the read-back. This loop can now neither
    change what it feeds in nor see what came out."""
    step1 = _mutate(tmp_path, PHASE3, AREA_REENTRY,
                    AREA_REENTRY.replace("period_relax=AREA_RETRY_PERIOD_RELAX",
                                         "period_relax=period_relax"))
    text = step1.read_text()
    assert text.count(AREA_MEASURE) == 1
    mutant = tmp_path / "both.py"
    mutant.write_text(text.replace(AREA_MEASURE,
                                   "                    _after = _before"))
    row = [r for r in C.scan_module(mutant)
           if r["fn"] == "step_synth" and r["callee"] == "step_synth"][0]
    assert row["verdict"] == C.INERT, (
        "a re-entry with no varying argument and no read-back is INERT; if the "
        "census cannot say so it is a list, not a census")


@pytest.mark.parametrize("arm", ["variance", "both"])
def test_the_control_loops_do_not_move_under_either_mutation(tmp_path, arm):
    """A census that reddens everything when one thing breaks has told you
    nothing about the one thing."""
    (tmp_path / arm).mkdir()
    mutant = _mutate(tmp_path / arm, PHASE3, AREA_REENTRY,
                     AREA_REENTRY.replace("period_relax=AREA_RETRY_PERIOD_RELAX",
                                          "period_relax=period_relax"))
    if arm == "both":
        t = mutant.read_text()
        mutant.write_text(t.replace(AREA_MEASURE,
                                    "                    _after = _before"))
    before = {k: v["verdict"] for k, v in _sites(PHASE3).items()
              if k[0] != "step_synth"}
    after = {k: v["verdict"] for k, v in _sites(mutant).items()
             if k[0] != "step_synth"}
    assert before == after, "an unrelated re-entry site changed verdict"
    ctl = [r for r in C.scan_module(mutant) if r["fn"] == "step_pnr"]
    assert ctl and all(r["verdict"] == C.SELF_CHECKED_ONLY for r in ctl)


def test_a_broken_loop_makes_the_regression_check_refuse():
    """The mutation has to reach the EXIT CODE, not only the verdict field."""
    base = C.summarise([{"file": "r.py", "fn": "step_synth",
                         "callee": "step_synth", "verdict": C.ACTUATING}])
    now = C.summarise([{"file": "r.py", "fn": "step_synth",
                        "callee": "step_synth",
                        "verdict": C.SELF_CHECKED_ONLY}])
    regs = C.regressions(now, base)
    assert regs and "ACTUATING 1 -> 0" in regs[0]


def test_a_deleted_re_entry_is_a_regression_not_a_pass():
    base = C.summarise([{"file": "r.py", "fn": "step_synth",
                         "callee": "step_synth", "verdict": C.ACTUATING}])
    regs = C.regressions({}, base)
    assert regs and "no longer present" in regs[0]


# ── the rc contract ─────────────────────────────────────────────────────────

def _tree(root: Path, runner_src: str) -> Path:
    p = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    p.mkdir(parents=True)
    (p / "x_one_shot_runner.py").write_text(runner_src)
    (p / "_atomic_artefact.py").write_text(
        (PROGRAMS / "_atomic_artefact.py").read_text())
    return root


def _run(root: Path, *extra):
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "closed_loop_executed_reentry_census.py"),
         str(root), *extra],
        capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_rc_2_when_no_runner_re_enters_anything(tmp_path):
    """A zero denominator REFUSES. 'Nothing to examine' is not 'examined and
    clean' — the same rule the sibling census keeps."""
    root = _tree(tmp_path, "def step_a(p):\n    return 1\n")
    rc, out = _run(root)
    assert rc == 2, out
    assert "CANNOT CHECK" in out


def test_rc_1_on_an_inert_re_entry(tmp_path):
    root = _tree(tmp_path,
                 "def step_a(p, q):\n"
                 "    for _i in range(3):\n"
                 "        step_b(p, q)\n"
                 "def step_b(p, q):\n"
                 "    return 1\n")
    rc, out = _run(root, "--baseline", str(tmp_path / "none.json"))
    assert rc == 1, out
    assert "[INERT]" in out and "step_a -> step_b" in out


def test_rc_0_when_every_re_entry_can_change_or_check_itself(tmp_path):
    root = _tree(tmp_path,
                 "def step_a(p, q):\n"
                 "    for i in range(3):\n"
                 "        step_b(p, i)\n"
                 "def step_b(p, q):\n"
                 "    return 1\n")
    rc, out = _run(root, "--baseline", str(tmp_path / "none.json"))
    assert rc == 0, out
    assert "INERT=0" in out


def test_the_shipped_baseline_matches_the_shipped_tree():
    """A baseline that has drifted from the tree cannot detect a regression in
    it, and would fail open."""
    root = PROGRAMS.parents[3]
    rc, out = _run(root)
    assert rc == 0, out
    assert "REGRESSION" not in out
