"""Tests for flow_doc_emit — the runner-marker flow-doc generator (v0.2.3).

Unit tests pin the three parsers against synthetic source; the freshness test runs the
generator's `--check` so a future runner change that isn't regenerated fails CI (mirrors
test_programs_index_freshness).
"""
import subprocess
import sys
from pathlib import Path

import flow_doc_emit as fde


# ---------------------------------------------------------------- phase1_markers
def test_phase1_markers_extracts_and_dedups_in_order():
    src = '''
    print(f"[1/15] Extracting text ...")
    # a comment mentioning [9/15] must be ignored
    print(f"[2/15] L1_DATASHEET ...")
    print(f"[14e/15] serial synth ...")
    print(f"[14e2/15] bus_interconnect gate")   # first occurrence kept
    print(f"[14e2/15] bus_interconnect Tier-2 synth ...")  # dup ignored
    '''
    got = fde.phase1_markers(src)
    assert got[0] == ("[1/15]", "Extracting text")
    assert got[1] == ("[2/15]", "L1_DATASHEET")
    assert ("[9/15]", "") not in got            # comment-only excluded
    markers = [m for m, _ in got]
    assert markers.count("[14e2/15]") == 1       # de-duped
    assert markers == ["[1/15]", "[2/15]", "[14e/15]", "[14e2/15]"]  # order preserved


def test_phase1_markers_strips_trailing_dots():
    assert fde.phase1_markers('print(f"[3/15] L2_FRS ...")') == [("[3/15]", "L2_FRS")]


# --------------------------------------------------------------- step_functions
def test_step_functions_ordered_unique():
    src = (
        "def step_phase1(x):\n    pass\n"
        "def helper():\n    pass\n"
        "def step_rtl_gen(a, b):\n    pass\n"
        "def step_phase1(y):\n    pass\n"   # dup name (overload site) → kept once
    )
    assert fde.step_functions(src) == ["step_phase1", "step_rtl_gen"]


# ----------------------------------------------------------------- analog_steps
def test_analog_steps_parses_header():
    src = (
        "  A1 spec_extract           → analog/<block>/A1_spec.json\n"
        "  A2 topology_select        → analog/<block>/A2_topology.json\n"
        "  A1 dup_should_be_ignored  → nope\n"
    )
    got = fde.analog_steps(src)
    assert got[0] == ("A1", "spec_extract", "analog/<block>/A1_spec.json")
    assert got[1][0] == "A2"
    assert [a for a, _, _ in got] == ["A1", "A2"]   # de-duped


# --------------------------------------------------------------------- render
def test_render_contains_all_sections_and_marker():
    out = fde.render()
    for h in ("## Phase 1", "## Phase 2", "## Phase 3", "## Analog", "## Totals",
              "AUTO-GENERATED"):
        assert h in out
    assert "[14e/15]" in out                      # the 81-protocol dispatch marker
    assert "`step_synth`" in out                  # a real phase3 step


# --------------------------------------------------------------- freshness gate
def test_committed_flow_doc_is_fresh():
    """The committed FLOW_STEPS_GENERATED.md must match the generator (run --check)."""
    r = subprocess.run([sys.executable, str(Path(fde.__file__)), "--check"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (
        f"FLOW_STEPS_GENERATED.md is stale — run `python3 flow_doc_emit.py`.\n"
        f"{r.stdout}\n{r.stderr}")
