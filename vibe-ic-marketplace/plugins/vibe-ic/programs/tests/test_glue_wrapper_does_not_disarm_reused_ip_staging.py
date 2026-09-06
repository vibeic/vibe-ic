#!/usr/bin/env python3
"""Obeying the catalog-glue waive disarmed the staging the waive depends on.

MEASURED DEFECT
===============
`step_rtl_gen` WAIVES with ``fallback_skill=catalog-glue-author``, whose
documented job is to author a chip_top WRAPPER around reused IP. The IP it
wraps is staged by the NEXT step, `reused_ip_consume`, whose contract was
"fires ONLY when phase2/stage1/rtl/ is EMPTY".

So an author who obeys the waive literally writes one file into rtl/, and that
act makes the CONSUME step skip:

    SKIP reused_ip_consume "phase2/stage1/rtl/ already holds 1 RTL file(s) —
    a deterministic generator / author owns it; CONSUME skipped"

The whole vendor closure is then never staged and synthesis fails on a module
nobody can find — for a reason unrelated to the design. Measured both
directions on one IC: rtl/ empty staged 284 files; rtl/ holding the authored
wrapper staged 0.

The two halves of the flow already disagreed: `_autoemit_chip_top_wrapper`
defers at the WRAPPER level ("caller already provided one") while this deferred
at the DIRECTORY level. Only the directory-level one was load-bearing.

THE FIX'S OWN LINE
==================
The skip must still hold for a real generator/author tree — the thing it was
written to protect — and nothing already in rtl/ may ever be overwritten. Both
are pinned below, as is the control of a design that ships no reused IP at all.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reused_ip_rtl_consume as C  # noqa: E402

VENDOR_TOP = """module widget_top (input logic clk, output logic q);
  widget_core u_core (.clk(clk), .q(q));
endmodule
"""
VENDOR_CORE = """module widget_core (input logic clk, output logic q);
  assign q = clk;
endmodule
"""
GLUE_WRAPPER = """module chip_top (input logic clk, output logic q);
  widget_top u_dut (.clk(clk), .q(q));
endmodule
"""
CLOSED_DESIGN = """module chip_top (input logic clk, output logic q);
  assign q = clk;
endmodule
"""


def _project(rtl_seed=None, with_vendor=True):
    root = Path(tempfile.mkdtemp(prefix="glue_staging_"))
    rtl = root / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    vend = root / "input" / "vendor_rtl"
    vend.mkdir(parents=True)
    if with_vendor:
        (vend / "widget_top.sv").write_text(VENDOR_TOP)
        (vend / "widget_core.sv").write_text(VENDOR_CORE)
    for name, body in (rtl_seed or {}).items():
        (rtl / name).write_text(body)
    return root, rtl


def test_a_glue_wrapper_no_longer_suppresses_the_staging_it_needs():
    """DIRECTION 1 — the waive, obeyed literally. The IP the wrapper names
    arrives around it."""
    root, rtl = _project({"chip_top.sv": GLUE_WRAPPER})
    res = C.consume_reused_ip_rtl(root)
    assert res["reused_ip"] is True
    assert sorted(res["staged"]) == ["widget_core.sv", "widget_top.sv"]
    # It named what was missing rather than counting what was present.
    assert res["unresolved_module_refs"] == ["widget_top"]
    assert res["pre_existing_rtl"] == ["chip_top.sv"]
    # NOTHING already present was touched.
    assert (rtl / "chip_top.sv").read_text() == GLUE_WRAPPER
    shutil.rmtree(root, ignore_errors=True)


def test_control_a_closed_design_still_owns_its_own_rtl_directory():
    """CONTROL — the protection this skip was written for is intact: an rtl/
    whose instantiations all resolve inside it is a DESIGN, and staging over it
    would be clobbering someone's work."""
    root, rtl = _project({"chip_top.sv": CLOSED_DESIGN})
    res = C.consume_reused_ip_rtl(root)
    assert res["reused_ip"] is False
    assert res["staged"] == []
    assert "already holds 1 RTL file(s)" in res["reason"]
    assert "a deterministic generator / author owns it" in res["reason"]
    assert list(rtl.glob("*.sv")) == [rtl / "chip_top.sv"]
    shutil.rmtree(root, ignore_errors=True)


def test_control_a_design_with_no_reused_ip_is_byte_identical():
    """CONTROL — the brief's control: a design that ships nothing to consume
    behaves exactly as before, wrapper present or not."""
    root, _ = _project({"chip_top.sv": GLUE_WRAPPER}, with_vendor=False)
    res = C.consume_reused_ip_rtl(root)
    assert res["reused_ip"] is False
    assert res["staged"] == []
    assert "ships NO build RTL under input/" in res["reason"]
    shutil.rmtree(root, ignore_errors=True)


def test_an_empty_rtl_directory_is_unchanged():
    """CONTROL — the historical path is untouched."""
    root, _ = _project()
    res = C.consume_reused_ip_rtl(root)
    assert res["reused_ip"] is True
    assert sorted(res["staged"]) == ["widget_core.sv", "widget_top.sv"]
    assert "unresolved_module_refs" not in res
    shutil.rmtree(root, ignore_errors=True)


def test_mutation_a_blind_closure_analysis_restores_the_old_skip():
    """MUTATION — make the closure analysis see nothing. The directory-level
    skip comes straight back, which is what tells us the analysis (and not
    some other edit) is what moved the behaviour. It is also the FAIL-SAFE
    direction: a defect in the analysis can only ever refuse to stage, never
    stage over an author's tree."""
    root, rtl = _project({"chip_top.sv": GLUE_WRAPPER})
    orig = C._unresolved_module_refs
    C._unresolved_module_refs = lambda files: []
    try:
        res = C.consume_reused_ip_rtl(root)
    finally:
        C._unresolved_module_refs = orig
    assert res["reused_ip"] is False
    assert res["staged"] == []
    assert "CONSUME skipped" in res["reason"]
    assert (rtl / "chip_top.sv").read_text() == GLUE_WRAPPER
    shutil.rmtree(root, ignore_errors=True)
