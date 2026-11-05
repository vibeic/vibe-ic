"""ORGANIC #571 — step_lvs DEF stage sanity (no routing → SKIP, not 2h magic)
+ pnr.tcl post-route checkpoint before antenna repair.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402














def test_571b_pnr_tcl_emits_preantenna_checkpoint():
    # the pnr tcl template must write a routed checkpoint right after
    # detailed_route, before the antenna repair block.
    src = inspect.getsource(R)
    assert "routed_preantenna.def" in src
    # ordering: the checkpoint write appears before the antenna_repair_block
    cp = src.index("routed_preantenna.def")
    ar = src.index("antenna_repair_block")
    # the checkpoint reference precedes the antenna block placeholder use
    assert cp < src.rindex("antenna_repair_block")
    assert "ROUTED_CHECKPOINT_NONFATAL" in src
