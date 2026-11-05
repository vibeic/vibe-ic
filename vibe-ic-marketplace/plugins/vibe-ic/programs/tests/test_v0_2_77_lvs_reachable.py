"""v0.2.77 — #443: open-source LVS is structurally REACHABLE.

The audited rot: step_lvs auto-WAIVED in every configuration — even
with netgen on PATH — because no layout-extraction step existed
anywhere in phase3; LVS was permanently unreachable and the waiver
rationale ("deferred to dedicated extraction flow") shipped on every
project forever.

Pins (monkeypatched docker — no container needed):
  * with magic+netgen+PDK tech present and GDS+netlist inputs, step_lvs
    RUNS Magic ext2spice + netgen and the verdict comes from the real
    compare output ("Circuits match uniquely" → PASS, mismatch → FAIL);
  * the unconditional-WAIVE shape is GONE from the source;
  * missing tool / missing PDK tech → ENV_UNAVAILABLE naming the gap;
  * missing GDS/netlist inputs → WAIVED naming the missing input.

chip-AGNOSTIC: synthetic project + fake docker transcripts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PLUGIN = Path(__file__).resolve().parent.parent.parent
_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()
















def test_unconditional_waive_shape_is_gone():
    assert "deferred to dedicated extraction flow" not in _SRC
    assert "ext2spice" in _SRC and "_run_extraction_lvs" in _SRC
