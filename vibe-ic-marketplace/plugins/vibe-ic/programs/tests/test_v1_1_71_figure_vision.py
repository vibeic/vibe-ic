"""v1.1.71 — figure_extractor: the vision tier's deterministic program side. Finds
every figure reference + caption, classifies it to a vision element_type, and routes
lead=vision for the runtime image model (which interprets the picture into structured
data, exactly as the AI text pass does for prose). Completes the dual-pass: program
covers table/parametric/prose-routing/figure-routing; AI + vision passes fill the rest.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import figure_extractor as F             # noqa: E402
import spec_artifact_dual_pass as DP       # noqa: E402


def _types(text):
    return [e["element_type"] for e in F.extract_figures(text)]


def test_numbered_captions_classified():
    t = ("Figure 1: State diagram of the FSM.\n"
         "Figure 2 - Timing waveform of the bus.\n"
         "Fig. 3. Block diagram of the architecture.\n")
    assert _types(t) == ["state_diagram", "timing_diagram", "block_diagram"]


def test_markdown_image_and_schematic_and_floorplan():
    t = "![gate-level schematic](sch.png)\nFigure 5: Floorplan / die plot."
    ts = _types(t)
    assert "circuit_schematic" in ts and "floorplan_spec" in ts


def test_untyped_figure_is_generic_but_routed():
    t = "Figure 9: Overview of the system context."
    els = F.extract_figures(t)
    assert els[0]["element_type"] == "figure"          # cannot type from caption
    assert els[0]["data"]["lead"] == "vision"          # still routed to the vision pass


def test_dedup_and_empty():
    assert F.extract_figures("prose with no figures at all") == []
    t = "Figure 1: State diagram.\nFigure 1: State diagram.\n"   # same caption+type
    assert len(F.extract_figures(t)) == 1


def test_figure_carries_reference():
    els = F.extract_figures("![state diagram](images/fsm.svg)")
    assert els[0]["element_type"] == "state_diagram"
    assert els[0]["data"]["ref"] == "images/fsm.svg" and els[0]["data"]["lead"] == "vision"


def test_vision_in_dual_pass_baseline():
    doc = (" - input clk\n - output q\n\nThe FSM is shown in Figure 2: state diagram.\n")
    base = DP.program_baseline(doc)
    types = {e["element_type"] for e in base}
    assert "pinout_table" in types and "state_diagram" in types   # text + vision tiers both fire
    sd = next(e for e in base if e["element_type"] == "state_diagram")
    assert sd["data"]["lead"] == "vision"
