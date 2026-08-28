#!/usr/bin/env python3
"""Step 6's `fpga_test_harness_gen` entry describes what the program does.

THE DEFECT
==========
Step 6 registered `fpga_test_harness_gen` with this comment:

    Wave 82 — emit the FPGA test-harness wrapper before Quartus
    picks it up. `fpga_test_harness_gen` reads chip_top + L9 ports
    and writes fpga/*.sv (top wrapper + pin map glue).

Every clause was false, and the sibling entry one line below
(`debug_first_pass`) carries an explicit "called interactively by the agent …
kept registered here for discoverability" disclosure, so the asymmetry read as
"this one IS wired":

  * nothing invokes it — not a runner, not a gate, not an MCP tool. Being
    named in a step's `programs:` list executes nothing: the only two readers
    of that list (`flow_dashboard_data`, `flow_step_executor_coverage_check`)
    inspect tokens for dashboard/audit purposes.
  * it reads neither chip_top nor L9 — it takes a project path and writes a
    FIXED DE10-Lite template.
  * it writes ONE file under the RTL dir, not `fpga/*.sv`, and no pin map glue.

A declaration nobody can act on is the paper-wiring this repo keeps finding;
the correction is to say what the program is (an agent-invoked bring-up
helper), because auto-wiring it as-is would emit a wrapper that does not
elaborate for any design whose top is not a `chip_top` with four specific
ports — measured on the reference spm x ihp-sg13g2 run, whose RTL dir contains
only `spm.v`.

METHOD NOTE — DISTINGUISHING "NOT THERE" FROM "I CANNOT SEE IT"
==============================================================
The reachability half is measured, not assumed: the runner scan below matches
the program stem on WORD BOUNDARIES (the flow writes program names bare, so a
quoted-only matcher reports false orphans) and the dynamic-dispatch sites in
`programs/` were enumerated separately — every `__import__` / `importlib` call
in the tree takes an explicit literal or a module-name tuple, and none of them
names this program.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parent.parent
_FLOW_YAML = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_PROGRAMS))

PROGRAM = "fpga_test_harness_gen"

#: The closed set of modules that actually DRIVE a step (mirrors
#: flow_step_executor_coverage_check._RUNNER_FILES).
_RUNNERS = [
    "vibe_ic_one_shot_runner.py", "phase1_one_shot_runner.py",
    "phase2_one_shot_runner.py", "design_one_shot_runner.py",
    "phase3_one_shot_runner.py", "phase3_backend_step.py",
    "analog_one_shot_runner.py",
]


def _emitted_wrapper(project: Path) -> Path:
    import _path_layout as _pl  # noqa: E402  (needs the sys.path insert above)
    return _pl.rtl_dir(project) / "fpga_test_harness.sv"


def _runner_text() -> str:
    parts = []
    for name in _RUNNERS:
        p = _PROGRAMS / name
        if p.is_file():
            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def _strip_comments(src: str) -> str:
    """Drop `#` comment tails so a MENTION in a comment is not a call site."""
    out = []
    for line in src.splitlines():
        i = line.find("#")
        out.append(line if i < 0 else line[:i])
    return "\n".join(out)


def _step6_programs_block() -> str:
    """The raw YAML text of Step 6's `programs:` list, comments included.

    Read from the shipped file because the declaration under test IS a
    comment; `yaml.safe_load` discards it.
    """
    text = _FLOW_YAML.read_text(encoding="utf-8")
    start = text.index("\n  - id: 6\n")
    end = text.index("\n  - id: 7\n", start)
    block = text[start:end]
    p = block.index("\n    programs:")
    return block[p:block.index("\n    required_outputs:", p)]


# ── measured premises — what the program actually is ────────────────────────

def test_premise_program_writes_one_wrapper_under_the_rtl_dir(tmp_path):
    """Run it: the artefact is <rtl_dir>/fpga_test_harness.sv, nothing else."""
    project = tmp_path / "proj"
    project.mkdir()
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / f"{PROGRAM}.py"), str(project)],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    wrapper = _emitted_wrapper(project)
    assert wrapper.is_file(), f"no wrapper at {wrapper}; stdout={cp.stdout}"
    produced = sorted(p.relative_to(project).as_posix()
                      for p in project.rglob("*") if p.is_file())
    assert produced == [wrapper.relative_to(project).as_posix()], produced


def test_premise_template_is_fixed_and_reads_nothing_from_the_project(tmp_path):
    """Two unrelated projects get byte-identical output.

    This is the claim "reads chip_top + L9 ports" fails on, stated as a
    property rather than by reading the source.
    """
    outs = []
    for i, ports in enumerate(("input clk, output q", "inout sda, inout scl")):
        project = tmp_path / f"p{i}"
        (project / "phase2" / "stage1" / "rtl").mkdir(parents=True)
        (project / "phase2" / "stage1" / "rtl" / "chip_top.v").write_text(
            f"module chip_top({ports}); endmodule\n")
        _pr.run(
            [sys.executable, str(_PROGRAMS / f"{PROGRAM}.py"), str(project)],
            capture_output=True, text=True, check=True)
        outs.append(_emitted_wrapper(project).read_text())
    assert outs[0] == outs[1], "the template is not fixed after all"


def test_premise_no_runner_invokes_the_program():
    """Reachability, measured on word boundaries and outside comments."""
    src = _strip_comments(_runner_text())
    assert src, "no runner sources found — the scan would be vacuous"
    assert not re.search(r"\b" + re.escape(PROGRAM) + r"\b", src), (
        f"{PROGRAM} IS invoked by a runner now — update Step 6's declaration, "
        f"which says it is not wired")


# ── DEFECT direction — fails on origin/main ─────────────────────────────────

def test_DEFECT_step6_declaration_names_the_real_artefact():
    """The comment must name the file the program actually writes.

    origin/main promises `fpga/*.sv` (top wrapper + pin map glue), which no
    run has ever produced.
    """
    block = _step6_programs_block()
    head = block[:block.index(f"      - {PROGRAM}")]
    assert "fpga_test_harness.sv" in head, (
        "Step 6's fpga_test_harness_gen entry does not name the artefact the "
        "program writes (<rtl_dir>/fpga_test_harness.sv)")


def test_DEFECT_step6_declaration_discloses_that_nothing_wires_it():
    """The unwired entry must disclose it, like its `debug_first_pass` sibling.

    Anchored to the sibling rather than to a phrase of my choosing: the two
    entries are in the same state, so they must carry the same kind of note.
    """
    block = _step6_programs_block()
    head = block[:block.index(f"      - {PROGRAM}")]
    sibling = block[block.index(f"      - {PROGRAM}"):
                    block.index("      - debug_first_pass")]
    for name, seg in (("fpga_test_harness_gen", head),
                      ("debug_first_pass", sibling)):
        low = seg.lower()
        assert ("agent" in low or "interactiv" in low) \
            and "discoverability" in low, (
            f"{name}'s entry does not disclose that it is agent-invoked and "
            f"registered for discoverability only")


# ── GUARD direction — must hold on BOTH trees ───────────────────────────────

def test_GUARD_step6_still_registers_the_program():
    """The correction is to the DESCRIPTION; the entry itself stays.

    Deleting it would hide the program from the catalogue instead of telling
    the truth about it.
    """
    doc = yaml.safe_load(_FLOW_YAML.read_text(encoding="utf-8"))

    def steps(o):
        if isinstance(o, dict):
            if "id" in o and ("name" in o or "required_outputs" in o):
                yield o
            for v in o.values():
                yield from steps(v)
        elif isinstance(o, list):
            for v in o:
                yield from steps(v)

    s6 = next(s for s in steps(doc) if str(s.get("id")) == "6")
    assert PROGRAM in (s6.get("programs") or [])


def test_GUARD_step6_gate_and_outputs_are_untouched():
    """Direction-1: correcting a comment must not move a gate or an output.

    UPDATED 2026-08-03 (vibe-ic#693). This used to assert
    ``len(all_of) == 4``. A bare count answers "did anything change?" but not
    "did anything I already relied on change?", so adding a deliberate leg and
    silently deleting an existing one look identical to it — and the only way
    past it is to bump a number, which is exactly the ratchet edit nobody can
    review.

    It now pins the four ORIGINAL legs by content and position, which is the
    invariant this guard was written for, and asserts that anything beyond them
    is `advisory_program_exit_zero` — the one slot that cannot change a step
    verdict. A future PR that wants to add a BLOCKING leg here must edit this
    test and say why; one that adds an advisory leg does not, and one that
    quietly rewrites leg 1..4 still fails.
    """
    doc = yaml.safe_load(_FLOW_YAML.read_text(encoding="utf-8"))

    def steps(o):
        if isinstance(o, dict):
            if "id" in o and ("name" in o or "required_outputs" in o):
                yield o
            for v in o.values():
                yield from steps(v)
        elif isinstance(o, list):
            for v in o:
                yield from steps(v)

    s6 = next(s for s in steps(doc) if str(s.get("id")) == "6")
    assert s6["required_outputs"] == [
        "phase2/stage1/fpga/output_files/*.sof",
        "phase2/stage1/fpga/output_files/*.map.rpt",
        "reports/phase2/fpga/quartus_map_audit.json",
    ]
    legs = s6["gate"]["all_of"]
    assert len(legs) >= 4
    assert legs[0] == {"files_exist": ["phase2/stage1/fpga/output_files/*.sof"]}
    assert legs[1] == {
        "files_exist": ["reports/phase2/fpga/quartus_map_audit.json"]}
    assert list(legs[2]) == ["program_exit_zero"]
    assert legs[2]["program_exit_zero"].split()[0] == "quartus_map_audit"
    assert list(legs[3]) == ["optional_program_exit_zero"]
    assert (legs[3]["optional_program_exit_zero"]["command"].split()[0]
            == "fpga_verification_audit")
    for extra in legs[4:]:
        assert list(extra) == ["advisory_program_exit_zero"], (
            f"step 6 gained a leg that is not advisory: {extra}. A blocking "
            f"leg here changes the step verdict on every run that reaches it; "
            f"say why in this test before adding one.")
