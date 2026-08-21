"""A stage-2 STA gate graded on stage-3 artefacts (vibe-ic#758).

Steps 10 (pre-layout STA) and 23 (post-route sign-off STA) were wired to the SAME
program with the SAME arguments, differing only in where the summary JSON lands.
`eda_report_audit._check_sta` discovers evidence with a project-wide rglob, so the
pre-layout gate walked every STA report in the project.

MEASURED on edge_llm_accel x nangate45 (v1.9.74): step 10 FAILed with
STA_REAL_VIOLATION_FOUND citing `reports/phase3/aging_sta.rpt` — a post-route,
aging-derated report that cannot exist before layout — among 12 candidates, of
which exactly one is pre-layout.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


def _sta_directive(sid: int) -> str:
    """The `program_exit_zero` line that RUNS the gate — never a comment.

    Selecting the first line containing "sta_report_check" picks up the prose
    above it, because the step's own comments discuss the program by name. That
    is the same shape this tree already names elsewhere: a check matching its own
    remedy. Anchored to the directive that actually executes."""
    hits = [l for l in _step_block(sid).splitlines()
            if "program_exit_zero" in l and "sta_report_check" in l
            and not l.lstrip().startswith("#")]
    assert len(hits) == 1, f"step {sid}: expected 1 sta directive, got {len(hits)}"
    return hits[0]


def _step_block(sid: int) -> str:
    """The raw YAML text of one step, by id."""
    txt = FLOW.read_text(encoding="utf-8")
    m = re.search(rf"^  - id: {sid}$", txt, re.M)
    assert m, f"step {sid} not found in the flow"
    nxt = re.search(r"^  - id: \d+$", txt[m.end():], re.M)
    return txt[m.start(): m.end() + (nxt.start() if nxt else len(txt))]


def test_step_10_scopes_discovery_to_the_pre_layout_report():
    line = [_sta_directive(10)]
    assert "--under" in line[0], (
        "the pre-layout STA gate discovers project-wide, so it grades stage 2 on "
        "stage-3 artefacts that cannot exist yet")
    assert "pre_pnr_timing.rpt" in line[0], (
        f"scoped, but not to the pre-layout report: {line[0].strip()}")


def test_step_23_is_scoped_to_its_OWN_report_and_not_to_step_10s():
    """This assertion has been REVERSED against the shape it was written in,
    deliberately, and the reversal is the point of the comment.

    As written, it asserted that step 23 must NOT be scoped at all: narrowing
    what a SIGN-OFF gate may see is how a real violation gets hidden, so
    over-inclusion is the correct failure direction there. `3c85544ce` then
    landed the opposite — step 23 was scoped to `post_route_timing.rpt` —
    having MEASURED that the unscoped gate was also reading step 10's
    pre-layout report and step 32's POST-ECO report, which is what made the two
    steps publish byte-identical summaries. That commit states its own revert
    condition ("no root in the corpus moves step 23 from FAIL to PASS; if a
    future root ever does, the fix is wrong and must be reverted"), so the
    landed decision is reasoned and evidenced, not incidental.

    The property that survives both shapes, and that the original was really
    protecting, is this one: NO STA GATE MAY BE GRADED ON ANOTHER STAGE'S
    ARTEFACT. It is asserted here in the direction main actually took —
    step 23 is scoped, and scoped to the POST-ROUTE report, never to the
    pre-layout one. Asserted on substance rather than on the exact directive
    text, so the in-flight work on what `--under` means for the corner scan
    cannot make this go quiet.
    """
    line = _sta_directive(23)
    assert "--under" in line, (
        f"the post-route sign-off gate discovers project-wide again: "
        f"{line.strip()}. Unscoped, it also grades stage-2 and post-ECO "
        f"reports, which is what made steps 10 and 23 publish identical "
        f"summaries.")
    assert "post_route" in line, (
        f"step 23 is scoped, but not to the post-route report: {line.strip()}")
    assert "pre_pnr_timing.rpt" not in line, (
        f"the SIGN-OFF gate was scoped onto the PRE-LAYOUT report: "
        f"{line.strip()} — a sign-off verdict reached over stage-2 evidence.")


def test_the_two_steps_no_longer_run_an_identical_command():
    """The defect in one line: same program, same arguments, two different
    questions."""
    def cmd(sid):
        return _sta_directive(sid).strip()
    a, b = cmd(10), cmd(23)
    strip_json = lambda s: re.sub(r"--json \S+", "", s)
    assert strip_json(a) != strip_json(b), (
        "steps 10 and 23 differ only in where the summary is written, so they "
        "ask the same question of the same evidence and one of them is wrong")


@pytest.mark.parametrize("under,expect_fail", [
    ("phase3/stage3/sta/pre_pnr_timing.rpt", False),   # scoped: clean
    (None, True),                                      # unscoped: sees the aging report
])
def test_the_scope_is_what_decides_the_verdict(tmp_path, under, expect_fail):
    """END TO END on the reported shape: a clean pre-layout report beside a
    violating post-route one. The ONLY difference between the two runs is the
    scope, so the scope is proven to be what changes the verdict — not the
    fixture, and not the checker's opinion of either file."""
    proj = tmp_path / "p"
    (proj / "phase3" / "stage3" / "sta").mkdir(parents=True)
    (proj / "reports" / "phase3").mkdir(parents=True)
    clean = ("Startpoint: a\nEndpoint: b\n"
             "  data arrival time  1.00\n  data required time 2.00\n"
             "  slack (MET)        1.00\n" + "-" * 40 + "\n")
    dirty = ("Startpoint: a\nEndpoint: b\n"
             "  data arrival time  2.00\n  data required time 1.00\n"
             "  slack (VIOLATED)  -1.00\n" + "-" * 40 + "\n")
    (proj / "phase3" / "stage3" / "sta" / "pre_pnr_timing.rpt").write_text(clean * 40)
    (proj / "reports" / "phase3" / "aging_sta.rpt").write_text(dirty * 40)

    argv = [sys.executable, str(PROGRAMS / "sta_report_check.py"), str(proj),
            "--mode", "sta"]
    if under:
        argv += ["--under", under]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    failed = r.returncode != 0
    assert failed is expect_fail, (
        f"under={under!r}: expected {'FAIL' if expect_fail else 'PASS'}, got rc="
        f"{r.returncode}\n{(r.stdout + r.stderr)[-700:]}")
