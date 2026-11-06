"""v0.3.18 — #519: emit the CTS sign-off report (cts/clock_tree.rpt) AT CTS
COMPLETION, not deferred to a post-routing canonicalize pass.

The audited rot (field: sha256 round1 v0.3.16): the CTS report was only written
at the END of the phase3 segment (step_canonicalize_artefacts), AFTER routing.
When detailed_route aborted, step_pnr returned FAIL early and the canonicalize
pass never ran — so a CTS that had GEOMETRICALLY COMPLETED (post_cts.def
written, openroad.log carrying CTS-0101/0102/0207) had no clock_tree.rpt, and
Step-19 CTS gate FAILed on a missing artefact for a CTS that actually ran. CTS
sign-off (Step 19) is independent of routing (Step 21); its evidence must be
durable the moment CTS completes.

Fix: `_emit_cts_report_if_complete(project, top)` writes the report the moment
post_cts.def exists + the log has CTS evidence, and step_pnr calls it BEFORE the
routing-outcome FAIL return. Idempotent + honest: a no-op when the report is
already durable, and it REFUSES to fabricate a report when CTS did not actually
complete (no post_cts.def).

chip-AGNOSTIC: synthetic project + synthetic OpenROAD log, no chip literal.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

_SRC = (PROGRAMS / "phase3_one_shot_runner.py").read_text()

_CTS_LOG = """\
[INFO ODB-0227] LEF file: merged.lef
[INFO CTS-0001] Running TritonCTS.
[INFO CTS-0003] Total number of Clock Roots: 1.
[INFO CTS-0004] Total number of Buffers Inserted: 42.
[INFO CTS-0005] Total number of Clock Subnets: 41.
[INFO CTS-0006] Total number of Sinks: 89.
[INFO CTS-0207] Clock net "clk" has max path depth 7.
[INFO CTS-0099] sink wire length 1234.5 um.
[INFO DRT-0267] detailed_route ...
"""


















def test_step_pnr_emits_cts_before_routing_fail_return():
    # structural guard: the CTS-completion emit must be wired into step_pnr
    # BEFORE the routing-outcome FAIL return (so a routing abort cannot skip
    # it). Pin the ordering in the source.
    i_emit = _SRC.index("_emit_cts_report_if_complete(project, top)")
    # the FAIL return that fires when rc != 0 / routed.def missing
    i_fail = _SRC.index('if rc != 0 or not def_file.is_file():')
    assert i_emit < i_fail, "CTS emit must precede the routing-FAIL return"
