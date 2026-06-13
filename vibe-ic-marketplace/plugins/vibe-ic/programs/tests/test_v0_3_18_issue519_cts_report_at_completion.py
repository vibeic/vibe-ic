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
import phase3_one_shot_runner as R  # noqa: E402

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


def _pnr(project: Path):
    pnr = R._pl.pnr_dir(project)
    pnr.mkdir(parents=True, exist_ok=True)
    return pnr


def test_report_emitted_when_cts_complete_even_without_routing(tmp_path):
    # CTS completed (post_cts.def + CTS log) but routing aborted → NO
    # routed.def. The report must still be written.
    pnr = _pnr(tmp_path)
    (pnr / "openroad.log").write_text(_CTS_LOG)
    (pnr / "post_cts.def").write_text("VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
    # explicitly NO routed.def — routing never finished.
    out = R._emit_cts_report_if_complete(tmp_path, "top")
    rpt = R._pl.cts_dir(tmp_path) / "clock_tree.rpt"
    assert out == str(rpt)
    assert rpt.is_file() and rpt.stat().st_size > 0
    txt = rpt.read_text()
    # extracted canonical CTS metrics are present.
    assert "inserted_buffers: 42" in txt
    assert "sinks: 89" in txt
    assert "clock_subnets: 41" in txt
    assert "max_path_depth: 7" in txt
    assert "sink_wire_length_um: 1234.5" in txt
    # raw CTS evidence lines carried through.
    assert "CTS-0004" in txt


def test_no_report_when_cts_did_not_complete(tmp_path):
    # log present but NO post_cts.def → CTS never finished → must NOT
    # fabricate a report (honest).
    pnr = _pnr(tmp_path)
    (pnr / "openroad.log").write_text(_CTS_LOG)
    out = R._emit_cts_report_if_complete(tmp_path, "top")
    assert out is None
    assert not (R._pl.cts_dir(tmp_path) / "clock_tree.rpt").is_file()


def test_idempotent_does_not_overwrite_existing(tmp_path):
    pnr = _pnr(tmp_path)
    (pnr / "openroad.log").write_text(_CTS_LOG)
    (pnr / "post_cts.def").write_text("DESIGN top ;\n")
    cts = R._pl.cts_dir(tmp_path)
    cts.mkdir(parents=True, exist_ok=True)
    (cts / "clock_tree.rpt").write_text("PRE-EXISTING REPORT\n")
    out = R._emit_cts_report_if_complete(tmp_path, "top")
    assert out is None                              # no re-write
    assert (cts / "clock_tree.rpt").read_text() == "PRE-EXISTING REPORT\n"


def test_nonfatal_noop_cts_recorded_honestly(tmp_path):
    # post_cts.def exists but the log carries no CTS signature. The two
    # indistinguishable causes (clkbuf-less PDK no-op OR a post-ECO
    # log-replacement that lost the original CTS section, ORGANIC #568) are
    # both recorded honestly as a VACUOUS report — never a fabricated tree —
    # so cts_quality_check FAILs on it explicitly rather than passing.
    pnr = _pnr(tmp_path)
    (pnr / "openroad.log").write_text("[INFO ODB-0227] LEF file: merged.lef\n")
    (pnr / "post_cts.def").write_text("DESIGN top ;\n")
    out = R._emit_cts_report_if_complete(tmp_path, "top")
    assert out
    txt = Path(out).read_text()
    # no fabricated tree: marker is one the cts_quality gate treats as vacuous
    assert "not invoked or zero output captured" in txt
    assert "EVIDENCE LOST" in txt


def test_parse_cts_metrics_omits_missing_fields():
    # a log with only some fields → only those keys appear (no fabrication).
    m = R._parse_cts_metrics(
        "[INFO CTS-0004] Total number of Buffers Inserted: 5.\n")
    assert m == {"inserted_buffers": "5"}


def test_step_pnr_emits_cts_before_routing_fail_return():
    # structural guard: the CTS-completion emit must be wired into step_pnr
    # BEFORE the routing-outcome FAIL return (so a routing abort cannot skip
    # it). Pin the ordering in the source.
    i_emit = _SRC.index("_emit_cts_report_if_complete(project, top)")
    # the FAIL return that fires when rc != 0 / routed.def missing
    i_fail = _SRC.index('if rc != 0 or not def_file.is_file():')
    assert i_emit < i_fail, "CTS emit must precede the routing-FAIL return"
