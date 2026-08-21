"""ORGANIC #782 — the #683 phantom-synth-top fallback only fires for the
LITERAL auto-wrapper name 'chip_top'.

現象: a REUSED-IP / catalog-glue project is driven with an explicit
``--top-name <ic_name>`` (the campaign harness passes the IC name, e.g.
``--top-name ibex``). That name is PHANTOM — no staged file declares it. The
authored integration wrapper is staged under its own name (``chip_top``), and
Phase-1 doc-extraction lifted a prose top into ``L9.top_module`` ('ibex_top')
which is ALSO phantom, with ``L9.synth_top`` null.

The synth-top precedence (waiver -> L9.synth_top -> <top>_asic.sv -> caller
top_name) therefore resolves ``synth_top='ibex'``, and yosys is invoked
``read_slang ... --top ibex`` -> ``error: 'ibex' is not a valid top-level
module`` -> Phase-2 FAIL.

ORGANIC #683 added exactly the right repair for this — consult the structural
instantiation-graph resolver (`_v661_resolve_dut_module`, the same one the TB
path trusts) and adopt a real graph root. But its guard was written as
``if synth_top == top_name == "chip_top"``, keying on the literal runner
auto-wrapper name rather than on the condition that name was standing in for:
"the resolved top is not a module that exists in staged rtl/". So the identical
failure with any OTHER phantom name fell straight through.

Fix: guard on ``synth_top == top_name`` (precedence fell through, so no
waiver / L9.synth_top / <top>_asic.sv override is in play) AND
``synth_top not in staged_modules`` (yosys is GUARANTEED to reject it). That
can only ever convert a certain FAIL into a structurally-resolved top; it can
never redirect a top that would have worked.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as P2  # noqa: E402


def _stage(rtl: Path, files: dict) -> None:
    rtl.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (rtl / name).write_text(text)


# A catalog-glue shape: authored `chip_top` wrapper + vendor leaves. NOTHING
# declares the caller-supplied top name.
_GLUE = {
    "chip_top.sv": (
        "module chip_top (input clk, input rst_n, output q);\n"
        "  core_alu u_alu (.clk(clk), .rst_n(rst_n), .q(q));\n"
        "endmodule\n"),
    "core_alu.sv": (
        "module core_alu (input clk, input rst_n, output q);\n"
        "  leaf_reg u_r (.clk(clk), .d(rst_n), .q(q));\n"
        "endmodule\n"),
    "leaf_reg.sv": (
        "module leaf_reg (input clk, input d, output q);\n"
        "  assign q = d;\nendmodule\n"),
}


def _capture_synth_top(monkeypatch):
    """Run step_yosys_synth with yosys stubbed, returning the --top yosys got."""
    seen = {}

    def _sentinel_run(cmd, *a, **k):
        # CAPTURE THE YOSYS CALL, NOT THE LAST CALL, AND DO NOT FAIL THE STEPS
        # THAT MUST SUCCEED BEFORE IT. The first version returned rc 1 for every
        # `_run` and kept only the most recent command. When the path gained a
        # `docker cp` of the RTL into the container, that cp got rc 1, the step
        # aborted before yosys, and `seen["cmd"]` held the failed cp — so both
        # assertions read a docker-cp string and reported the missing `--top` as
        # a product defect. The probe was measuring its own stub.
        s = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "yosys" in s:
            seen["cmd"] = s
            return (1, "", "stub yosys ran")
        return (0, "", "")
    monkeypatch.setattr(P2, "_run", _sentinel_run)
    return seen


def test_phantom_caller_top_adopts_graph_root(tmp_path, monkeypatch):
    """REPRODUCE: a phantom caller top must be replaced by the real graph
    root, not handed to yosys verbatim."""
    proj = tmp_path / "proj"
    _stage(proj / "phase2" / "stage1" / "rtl", _GLUE)
    seen = _capture_synth_top(monkeypatch)

    P2.step_yosys_synth(proj, top_name="ibex")

    cmd = seen.get("cmd", "")
    assert "--top chip_top" in cmd or "-top chip_top" in cmd, cmd
    assert "--top ibex" not in cmd, "phantom top was handed to yosys: " + cmd


def test_resolver_finds_the_graph_root_directly(tmp_path):
    """The structural resolver itself returns the authored wrapper."""
    proj = tmp_path / "proj"
    _stage(proj / "phase2" / "stage1" / "rtl", _GLUE)

    mods = set(P2._v661_rtl_module_names(proj))
    assert "ibex" not in mods and "chip_top" in mods
    assert P2._v661_resolve_dut_module(proj, "ibex", None) == "chip_top"


def test_literal_chip_top_case_still_works(tmp_path, monkeypatch):
    """NO-REGRESSION: the original #683 case (phantom literal 'chip_top') must
    behave exactly as before."""
    proj = tmp_path / "proj"
    no_wrapper = {k: v for k, v in _GLUE.items() if k != "chip_top.sv"}
    _stage(proj / "phase2" / "stage1" / "rtl", no_wrapper)
    seen = _capture_synth_top(monkeypatch)

    P2.step_yosys_synth(proj, top_name="chip_top")

    cmd = seen.get("cmd", "")
    assert "core_alu" in cmd, cmd


def test_real_staged_top_is_never_redirected(tmp_path, monkeypatch):
    """NEGATIVE CONTROL: when the caller's top DOES exist in staged rtl/, it
    must be used verbatim — the fallback must not fire at all."""
    proj = tmp_path / "proj"
    _stage(proj / "phase2" / "stage1" / "rtl", _GLUE)
    seen = _capture_synth_top(monkeypatch)

    P2.step_yosys_synth(proj, top_name="core_alu")

    cmd = seen.get("cmd", "")
    assert "--top core_alu" in cmd or "-top core_alu" in cmd, cmd
    assert "--top chip_top" not in cmd, "a REAL staged top was redirected: " + cmd


def test_ambiguous_design_defers_honestly(tmp_path, monkeypatch):
    """NEGATIVE CONTROL: two independent graph roots ⇒ the resolver returns
    None ⇒ synth_top is left unchanged so the honest-FAIL path is preserved.
    The fix must not guess a top on a genuinely ambiguous design."""
    proj = tmp_path / "proj"
    _stage(proj / "phase2" / "stage1" / "rtl", {
        "root_a.sv": "module root_a (input a, output b); assign b = a; endmodule\n",
        "root_b.sv": "module root_b (input a, output b); assign b = ~a; endmodule\n",
    })
    seen = _capture_synth_top(monkeypatch)

    P2.step_yosys_synth(proj, top_name="phantom_top")

    cmd = seen.get("cmd", "")
    # Nothing was silently adopted — neither root was picked as the top.
    assert "--top root_a" not in cmd and "--top root_b" not in cmd, cmd
