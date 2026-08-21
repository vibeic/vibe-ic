"""v0.2.43 blindness + lesson-digest regressions.

Pins the two ORGANIC-20260605 instruction/orchestration fixes:
  * blindness-rule-cross-problem-refs (#410): the shipped blind instructions
    (all shapes) + the methodology skill now forbid reading ANY dataset file
    other than the current problem's prompt — explicitly including SIBLING
    problems' reference/test files — and bind close-loop agents equally.
  * shapec-lesson-digest-injection (#412): `benchmark_dispatch.py --setup`
    renders the capture loop's general-pattern `### Skill:` sections into
    `<RUNDIR>/lessons.md`, and the Shape-C blind instructions make it a
    MUST-READ, so already-captured recoveries stop recurring single-shot.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import benchmark_dispatch as bd  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
SKILL = PLUGIN / "skills" / "open-benchmark-methodology" / "SKILL.md"


# ── #410: cross-problem prohibition present in every shipped instruction ──

def test_shape_c_carries_cross_problem_prohibition():
    txt = (HARNESS / "blind_instructions_shape_c.md").read_text()
    assert "CROSS-PROBLEM PROHIBITION" in txt
    assert "OTHER problems'" in txt
    assert "close-loop" in txt  # binds repair agents too


def test_shape_b_carries_cross_problem_prohibition():
    txt = (HARNESS / "blind_instructions_shape_b.md").read_text()
    assert "CROSS-PROBLEM PROHIBITION" in txt
    assert "OTHER designs'" in txt


def test_shape_d_carries_cross_problem_prohibition():
    txt = (HARNESS / "blind_instructions_shape_d.md").read_text()
    assert "CROSS-PROBLEM PROHIBITION" in txt
    assert "OTHER\nprojects'" in txt or "OTHER projects'" in txt


def test_methodology_skill_carries_cross_problem_item():
    txt = SKILL.read_text()
    assert "any dataset file other than the current problem's prompt" in txt
    assert "close-loop prompt" in txt  # spawn-time propagation instruction


# ── #412: lesson digest rendering ─────────────────────────────────────────

_FAKE_EXPERT = """# IC Expert Agent

## RTL Realization Principles

prose that is NOT a lesson

### Skill: alpha pattern
body line A1
body line A2

### Not a skill heading
ignored

### Skill: beta pattern
body line B1

### ~~Skill: retired pattern~~ → **NOW A PROGRAM RULE**
should be excluded

## Another section

### Skill: gamma pattern
body line C1
"""


def test_digest_extracts_active_skill_sections_only(tmp_path):
    md = tmp_path / "expert.md"
    md.write_text(_FAKE_EXPERT)
    run = tmp_path / "run"; run.mkdir()
    n = bd._render_lesson_digest(run, expert_md=md)
    assert n == 3
    digest = (run / "lessons.md").read_text()
    assert "READ BEFORE AUTHORING" in digest
    for frag in ("Skill: alpha pattern", "body line A2",
                 "Skill: beta pattern", "Skill: gamma pattern"):
        assert frag in digest
    assert "retired pattern" not in digest
    assert "Not a skill heading" not in digest


def test_digest_missing_expert_md_is_noop(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    assert bd._render_lesson_digest(run, expert_md=tmp_path / "absent.md") == 0
    assert not (run / "lessons.md").exists()


def test_digest_renders_real_expert_lessons(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    n = bd._render_lesson_digest(run)
    assert n >= 20, f"expected the real capture corpus, got {n}"
    digest = (run / "lessons.md").read_text()
    # a known captured general-pattern lesson must survive extraction
    assert "minimum SOP/POS with don't-cares" in digest


def test_setup_renders_lessons_md_end_to_end(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "ProbA_prompt.txt").write_text("Build a thing.\n")
    (ds / "ProbB_prompt.txt").write_text("Build another.\n")
    run = tmp_path / "run"
    r = subprocess.run(
        [sys.executable, str(PLUGIN / "programs" / "benchmark_dispatch.py"),
         "verilogeval-v2", "--setup", "--dataset", str(ds), "--run", str(run)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (run / "lessons.md").is_file()
    assert "lessons:" in r.stdout and "MUST read" in r.stdout


def test_shape_c_instructions_mandate_reading_digest():
    txt = (HARNESS / "blind_instructions_shape_c.md").read_text()
    assert "lessons.md" in txt
    assert "MUST read it BEFORE" in txt or "MUST-READ" in txt
