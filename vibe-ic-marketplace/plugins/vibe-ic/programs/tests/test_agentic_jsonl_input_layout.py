"""Tests for v0.1.59 R9 capture: agentic_jsonl_to_shape_d.py must also stage
the runner's input/ layout (input/phase1_prompt.md + input/docs/design_description.md)
so vibe_ic_one_shot_runner.py's phase1 ingester can read the prompt without
a manual mkdir+cp dance.

Captured from v0.1.58 CVDP run: every Shape-D problem required hand-staging
these two files before invoking the runner.
"""
import importlib
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    if "agentic_jsonl_to_shape_d" in sys.modules:
        del sys.modules["agentic_jsonl_to_shape_d"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("agentic_jsonl_to_shape_d")


def test_input_phase1_prompt_emitted(tmp_path):
    """input/phase1_prompt.md must mirror work/PROMPT.txt verbatim."""
    mod = _load()
    rundir = tmp_path / "run"
    row = {"id": "p_001", "prompt": "Design a counter.", "harness": {"src/t.py": "code"}}
    proj = mod.extract_row(row, rundir)
    assert (proj / "input" / "phase1_prompt.md").read_text() == "Design a counter."


def test_input_docs_design_description_includes_prompt(tmp_path):
    """input/docs/design_description.md must start with the prompt."""
    mod = _load()
    rundir = tmp_path / "run"
    row = {"id": "p_001", "prompt": "Design a counter.", "harness": {"src/t.py": "c"}}
    proj = mod.extract_row(row, rundir)
    text = (proj / "input" / "docs" / "design_description.md").read_text()
    assert text.startswith("Design a counter.")


def test_input_docs_appends_context_md_docs(tmp_path):
    """When context contains docs/*.md files, their content must be appended
    to design_description.md so the runner's phase1 sees the full spec."""
    mod = _load()
    rundir = tmp_path / "run"
    row = {
        "id": "p_001",
        "prompt": "Top prompt.",
        "context": {
            "docs/specification.md": "## Spec body here.",
            "docs/architecture.md":  "## Architecture body here.",
            "verif/tb.sv":           "// TB — must NOT appear in design_description",
        },
        "harness": {"src/t.py": "c"},
    }
    proj = mod.extract_row(row, rundir)
    text = (proj / "input" / "docs" / "design_description.md").read_text()
    assert "Top prompt." in text
    assert "Spec body here." in text
    assert "Architecture body here." in text
    # verif/ content is NOT part of design_description (it's stimulus, not spec)
    assert "TB — must NOT" not in text


def test_input_dir_does_not_leak_score_harness(tmp_path):
    """Anti-blind-leak regression: nothing from row['harness'] (the hidden
    scorer) may end up under input/ — input is what the AI reads, score/ is
    blind to it."""
    mod = _load()
    rundir = tmp_path / "run"
    row = {
        "id": "p_001",
        "prompt": "p",
        "harness": {"src/test_secret.py": "GOLDEN_OUTPUT = 0xDEADBEEF"},
    }
    proj = mod.extract_row(row, rundir)
    for p in (proj / "input").rglob("*"):
        if p.is_file():
            assert "GOLDEN_OUTPUT" not in p.read_text(), (
                f"score/ content leaked into input/{p.relative_to(proj/'input')}")


def test_input_dir_created_even_when_no_context(tmp_path):
    """Minimal row (prompt + harness only, no context) still gets input/ layout."""
    mod = _load()
    rundir = tmp_path / "run"
    row = {"id": "p_001", "prompt": "p", "harness": {"src/t.py": "c"}}
    proj = mod.extract_row(row, rundir)
    assert (proj / "input" / "phase1_prompt.md").is_file()
    assert (proj / "input" / "docs" / "design_description.md").is_file()


def test_work_and_score_layout_preserved(tmp_path):
    """Adding input/ must NOT regress the existing work/ + score/ layout."""
    mod = _load()
    rundir = tmp_path / "run"
    row = {
        "id": "p_001",
        "prompt": "Top",
        "context": {"docs/spec.md": "S", "verif/tb.sv": "T"},
        "harness": {"src/test_foo.py": "X", "docker-compose.yml": "Y"},
    }
    proj = mod.extract_row(row, rundir)
    # Pre-R9 invariants still hold
    assert (proj / "work" / "PROMPT.txt").read_text() == "Top"
    assert (proj / "work" / "docs" / "spec.md").read_text() == "S"
    assert (proj / "work" / "verif" / "tb.sv").read_text() == "T"
    assert (proj / "score" / "src" / "test_foo.py").read_text() == "X"
    assert (proj / "score" / "docker-compose.yml").read_text() == "Y"
