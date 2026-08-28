"""ORGANIC #689 [HIGH/P1, chip-AGNOSTIC] — reset/clock variant-alias canonicaliser
over-fired and LOSSY-renamed a spec-correct STANDARD reset/clock spelling away
from the design's OWN contract, breaking the hidden TB (compile_error).

TWO FACETS:
  FACET 1 (over-fire): the canonicaliser unconditionally renamed any recognised
    non-canonical STANDARD reset/clock spelling (`reset`->`rst`, `clock`->`clk`,
    …) and took over the top name. When the design's OWN contract (prompt /
    external-interface doc) already declares that standard spelling AND the
    hidden TB instantiates it by that SAME spelling, the renamed wrapper exposes
    a DIFFERENT port than the TB binds → `port 'reset' is not a port of dut`.
    The #618 SDC guard missed it (RTLLM ships no SDC → empty pinned set) and the
    #518 L9 guard missed it (top_ports==[] + top_module case differs).
  FACET 2 (lossy in-place rename): `plan_aliases(['clk','reset','up_down',
    'count'])` -> `{'reset':'rst'}`; the wrapper then exposes ONLY `rst`,
    REMOVING `reset` from the TB-facing surface — the active-HIGH/clock common
    case (the active-LOW path masks it: `rst_n` already canonical -> {}).

FIX (Bucket A, additive + contract-aware): treat the design's OWN stated port
spelling as a FIRST-CLASS suppression source on par with #618 SDC + #518 L9.
`design_contract_ports(project)` parses the staged prompt / external-interface
doc / parsed L3 port list; `plan_aliases(..., contract_ports=<that>)` DROPS the
rename of any port whose spelling is contract-declared (preserving it verbatim
on the TB-facing surface). The runner wires this BEFORE the #618/#518 guards.

§4.05 NO-LEAK (load-bearing — this RELAXES a guard): the legitimate variant-alias
case must STILL fire — when the design declares a NON-canonical spelling its
hidden TB needs as the canonical name (the #518/#678 motivating case) AND ships
NO staged contract (exactly like it ships no SDC), the alias STILL fires.

The real RTLLM repro (multi_booth_8bit `reset`, up_down_counter `reset`, plus the
`clock` shape) is embedded verbatim.

chip-AGNOSTIC: port-declaration grammar + the closed standard reset/clock
spelling set; no chip/vendor/SKU literal.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import reset_clock_variant_alias as V  # noqa: E402
import design_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ════════════════════════════════════════════════════════════════════════
# FACET 2 — plan_aliases is non-lossy + contract-aware (unit level)
# ════════════════════════════════════════════════════════════════════════

def test_facet2_decisive_repro_no_contract_still_overfires_without_arg():
    # The decisive bug repro (the issue's words): WITHOUT contract evidence the
    # active-HIGH `reset` is still canonicalised (the field-verified #518
    # convergence doctrine — preserved when NO contract is staged).
    assert V.plan_aliases(["clk", "reset", "up_down", "count"]) == {"reset": "rst"}


def test_facet2_contract_declares_reset_suppresses_rename():
    # FACET 2 FIX: the design's own contract declares `reset` -> the rename is
    # DROPPED; the original `reset` spelling is preserved (additive, not lossy).
    assert V.plan_aliases(
        ["clk", "reset", "up_down", "count"], contract_ports={"reset"}) == {}


def test_facet1_clock_shape_contract_suppresses_both():
    # the `clock`/`reset` shape: contract declares both -> neither renamed.
    assert V.plan_aliases(
        ["clock", "reset", "a", "b"]) == {"clock": "clk", "reset": "rst"}
    assert V.plan_aliases(
        ["clock", "reset", "a", "b"],
        contract_ports={"clock", "reset"}) == {}


def test_contract_partial_suppression_is_not_a_blanket_skip():
    # contract pins ONLY `reset`; an unpinned non-canonical `clock` STILL aliases.
    assert V.plan_aliases(
        ["clock", "reset", "d"], contract_ports={"reset"}) == {"clock": "clk"}


def test_noleak_no_contract_legit_alias_still_fires():
    # §4.05 (b): a design that ships NO contract STILL gets the alias — the
    # legitimate #518 hidden-TB-needs-canonical case.
    assert V.plan_aliases(["clk", "reset_n", "d", "q"]) == {"reset_n": "rst_n"}
    assert V.plan_aliases(["clk", "reset_n", "d", "q"],
                          contract_ports=set()) == {"reset_n": "rst_n"}


def test_noleak_active_low_already_canonical_is_noop():
    # active-LOW `rst_n` is already canonical -> {} regardless of contract.
    assert V.plan_aliases(["clk", "rst_n", "d"]) == {}
    assert V.plan_aliases(["clk", "rst_n", "d"],
                          contract_ports={"rst_n"}) == {}


def test_noleak_contract_naming_canonical_does_not_block_unrelated():
    # a contract that names the CANONICAL spelling (`rst`) does NOT suppress an
    # unrelated non-canonical `reset_n` (different polarity, different spelling).
    assert V.plan_aliases(
        ["clk", "reset_n", "d"], contract_ports={"rst"}) == {"reset_n": "rst_n"}


# ════════════════════════════════════════════════════════════════════════
# design_contract_ports — the contract reader (only port-decl contexts count)
# ════════════════════════════════════════════════════════════════════════

def test_contract_reader_markdown_table_real_rtllm_shape(tmp_path):
    # REAL RTLLM multi_booth_8bit external-interface shape (markdown table).
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "design_description.md").write_text(
        "# multi_booth_8bit — 8-bit Booth multiplier\n\n"
        "| Signal | Width | Dir | Description |\n"
        "|---|---|---|---|\n"
        "| clk | 1 | input | system clock |\n"
        "| reset | 1 | input | active-high reset |\n"
        "| a | 8 | input | multiplicand |\n"
        "| b | 8 | input | multiplier |\n")
    pinned = V.design_contract_ports(tmp_path)
    assert "reset" in pinned and "clk" in pinned


def test_contract_reader_verilog_decl_in_prompt(tmp_path):
    # REAL up_down_counter shape: a Verilog header in the staged prompt.
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "phase1_prompt.md").write_text(
        "Design `up_down_counter`:\n"
        "module up_down_counter(input clk, input reset, input up_down,"
        " output reg [15:0] count);")
    pinned = V.design_contract_ports(tmp_path)
    assert "reset" in pinned and "clk" in pinned


def test_contract_reader_backtick_names(tmp_path):
    docs = tmp_path / "phase1" / "input_doc"
    docs.mkdir(parents=True)
    (docs / "L3_external_interface.txt").write_text(
        "The `reset` port is active-high; `clk` samples on the rising edge.")
    pinned = V.design_contract_ports(tmp_path)
    assert "reset" in pinned and "clk" in pinned


def test_contract_reader_parsed_l3_json(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L3_external_interface.json").write_text(json.dumps({
        "top_module": "multi_booth_8bit",
        "top_ports": [{"name": "clk"}, {"name": "reset"},
                      {"name": "a"}, {"name": "p"}]}))
    pinned = V.design_contract_ports(tmp_path)
    assert pinned == {"clk", "reset"}


def test_contract_reader_prose_only_does_not_overcollect(tmp_path):
    # NO over-suppression: loose prose mentioning "reset"/"clock" with NO
    # port-declaration context must NOT register as a declared port.
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L1_overview.md").write_text(
        "When the reset is asserted, the clock is gated. The block resets "
        "all internal state within one clock cycle of reset assertion.")
    assert V.design_contract_ports(tmp_path) == set()


def test_contract_reader_empty_project_is_empty(tmp_path):
    # NO contract staged -> empty set -> callers fall through (no-leak).
    assert V.design_contract_ports(tmp_path) == set()


def test_free_prompt_explicit_port_sections_are_authoritative(tmp_path):
    """A complete Input/Output ports list is an exact interface, not prose."""
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "phase1_prompt.md").write_text(
        "Module name:\n  generic_counter\n\n"
        "Input ports:\n"
        "  clk: clock\n"
        "  reset: active-high reset\n"
        "  direction: count direction\n\n"
        "Output ports:\n"
        "  value [15:0]: current value\n\n"
        "Reset is synchronous.\n")
    assert V.authoritative_contract_ports(tmp_path) == {
        "clk", "reset", "direction", "value"}


def test_free_prompt_fullwidth_colon_sections_are_authoritative(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "phase1_prompt.md").write_text(
        "Input ports：\n  clk：clock\n  arstn：reset A\n\n"
        "Output ports：\n  q：registered output\n")
    assert V.authoritative_contract_ports(tmp_path) == {"clk", "arstn", "q"}


# ════════════════════════════════════════════════════════════════════════
# Runner step end-to-end — FACET 1 over-fire: the repro now elaborates
# ════════════════════════════════════════════════════════════════════════

MULTI_BOOTH_RTL = (
    "module multi_booth_8bit (\n"
    "    input  wire        clk,\n"
    "    input  wire        reset,\n"
    "    input  wire [7:0]  a,\n"
    "    input  wire [7:0]  b,\n"
    "    output reg  [15:0] p,\n"
    "    output reg         rdy\n"
    ");\n"
    "    always @(posedge clk or posedge reset)\n"
    "        if (reset) begin p <= 16'd0; rdy <= 1'b0; end\n"
    "        else begin p <= p + 1; rdy <= 1'b1; end\n"
    "endmodule\n")

UP_DOWN_RTL = (
    "module up_down_counter (\n"
    "    input             clk,\n"
    "    input             reset,\n"
    "    input             up_down,\n"
    "    output reg [15:0] count\n"
    ");\n"
    "    always @(posedge clk)\n"
    "        if (reset) count <= 16'd0;\n"
    "        else if (up_down) count <= count + 16'd1;\n"
    "        else count <= count - 16'd1;\n"
    "endmodule\n")


def _stage_rtl(proj, text, name):
    rtl = R._pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    f = rtl / name
    f.write_text(text)
    return f


def _stage_contract_md(proj, body):
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "design_description.md").write_text(body)


def test_step_facet1_contract_declares_reset_skips_and_elaborates(tmp_path):
    # FACET 1 (#689 over-fire) → #792 ADDITIVE doctrine. The contract declares
    # `reset` and ITS hidden TB binds `.reset(...)`, but a DIFFERENT hidden TB may
    # bind the canonical `.rst(...)` (indistinguishable from the contract alone).
    # The step now emits an ADDITIVE dual-spelling reset wrapper (PASS): `reset`
    # STAYS bindable (no regression) AND `rst` is ALSO exposed, polarity-safe
    # (active-high → tri0 pull, OR-combine), so BOTH bindings elaborate.
    f = _stage_rtl(tmp_path, MULTI_BOOTH_RTL, "multi_booth_8bit.v")
    _stage_contract_md(
        tmp_path,
        "# multi_booth_8bit\n\n"
        "| Signal | Width | Dir | Description |\n"
        "|---|---|---|---|\n"
        "| clk | 1 | input | clock |\n"
        "| reset | 1 | input | active-high reset |\n"
        "| a | 8 | input | multiplicand |\n")
    res = R.step_reset_clock_variant_aliases(tmp_path, "multi_booth_8bit")
    assert res.status == "PASS", (res.status, res.detail)
    assert "#792" in res.detail and "additive" in res.detail.lower()
    body = f.read_text()
    assert "reset" in body and "__rcvar_inner" in body
    assert "rst" in body, "additive canonical spelling must be exposed"

    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host — structural checks only")

    def _elab(bind):
        tb = tmp_path / f"tb_{bind}.v"
        tb.write_text(
            f"module tb;\n reg clk=0, {bind}=0; reg [7:0] a=0,b=0;"
            f" wire [15:0] p; wire rdy;\n"
            f" multi_booth_8bit dut(.clk(clk), .{bind}({bind}), .a(a), .b(b),"
            f" .p(p), .rdy(rdy));\nendmodule\n")
        return _pr.run(
            [iv, "-g2012", "-s", "tb", "-o", str(tmp_path / f"{bind}.out"),
             str(f), str(tb)], capture_output=True, text=True)
    # NO-REGRESSION: the contract `.reset` binding still elaborates.
    assert _elab("reset").returncode == 0
    # #792 RESCUE: the canonical `.rst` binding now ALSO elaborates.
    assert _elab("rst").returncode == 0


def test_step_facet2_up_down_counter_contract_preserves_reset(tmp_path):
    # FACET 2 → #792: up_down_counter declares `reset`; the step now exposes BOTH
    # `reset` (contract) and `rst` (canonical) additively. TBs binding either
    # `.reset(...)` (no regression) or `.rst(...)` (rescue) elaborate.
    f = _stage_rtl(tmp_path, UP_DOWN_RTL, "up_down_counter.v")
    _stage_contract_md(
        tmp_path,
        "module up_down_counter(input clk, input reset, input up_down,"
        " output reg [15:0] count);")
    res = R.step_reset_clock_variant_aliases(tmp_path, "up_down_counter")
    assert res.status == "PASS", (res.status, res.detail)
    assert "#792" in res.detail and "additive" in res.detail.lower()
    body = f.read_text()
    assert "reset" in body and "__rcvar_inner" in body

    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")

    def _elab(bind):
        tb = tmp_path / f"tb_{bind}.v"
        tb.write_text(
            f"module tb; reg clk=0,{bind}=0,up_down=0; wire [15:0] count;"
            f" up_down_counter dut(.clk(clk),.{bind}({bind}),.up_down(up_down),"
            f".count(count)); endmodule\n")
        return _pr.run(
            [iv, "-g2012", "-o", str(tmp_path / f"{bind}.out"), str(tb), str(f)],
            capture_output=True, text=True)
    assert _elab("reset").returncode == 0    # no regression
    assert _elab("rst").returncode == 0      # #792 rescue


def test_step_facet1_clock_shape_contract_preserves_clock(tmp_path):
    # the `clock` shape: contract declares `clock` (+ `reset`). A CLOCK has no
    # inactive level → it is NEVER additive (stays suppressed: `clock` survives,
    # not renamed). The active-high `reset` becomes ADDITIVE (PASS): `reset`
    # stays bindable AND `rst` is exposed. The `.clock`+`.reset` binding (and the
    # `.clock`+`.rst` rescue) elaborate; the clock is not rescued (no `.clk`).
    rtl = (
        "module dut_clk (\n  input clock, input reset, input d,"
        " output reg q\n);\n"
        "  always @(posedge clock) if (reset) q<=0; else q<=d;\nendmodule\n")
    f = _stage_rtl(tmp_path, rtl, "dut_clk.v")
    _stage_contract_md(
        tmp_path,
        "Ports: `clock` (input, system clock), `reset` (input, active-high), "
        "`d`, `q`.")
    res = R.step_reset_clock_variant_aliases(tmp_path, "dut_clk")
    assert res.status == "PASS", (res.status, res.detail)
    assert "#792" in res.detail and "additive" in res.detail.lower()
    body = f.read_text()
    # clock stays its contract spelling (no `clk` rename); reset is additive.
    assert "clock" in body and "reset" in body and "__rcvar_inner" in body
    assert "rst" in body

    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")

    def _elab(rbind):
        tb = tmp_path / f"tb_{rbind}.v"
        tb.write_text(
            f"module tb; reg clock=0,{rbind}=0,d=0; wire q;"
            f" dut_clk dut(.clock(clock),.{rbind}({rbind}),.d(d),.q(q));"
            f" endmodule\n")
        return _pr.run(
            [iv, "-g2012", "-o", str(tmp_path / f"{rbind}.out"), str(tb), str(f)],
            capture_output=True, text=True)
    assert _elab("reset").returncode == 0    # no regression (clock + spec reset)
    assert _elab("rst").returncode == 0      # #792 rescue (clock + canon reset)


# ════════════════════════════════════════════════════════════════════════
# §4.05 NO-LEAK — the legitimate alias STILL fires; existing guards intact
# ════════════════════════════════════════════════════════════════════════

def _seq_core(reset_name):
    return (f"module sequence_detector(\n"
            f"    input wire clk,\n"
            f"    input wire {reset_name},\n"
            f"    input wire data_in,\n"
            f"    output reg detected\n"
            f");\n"
            f"    always @(posedge clk or negedge {reset_name})\n"
            f"        if (!{reset_name}) detected <= 1'b0; "
            f"else detected <= data_in;\n"
            f"endmodule\n")


def test_noleak_step_no_contract_legit_alias_still_fires(tmp_path):
    # §4.05 (b) END-TO-END: the #518 motivating case — a design declaring
    # active-low `reset_n` whose hidden TB needs the canonical `rst_n`, with NO
    # staged contract. The alias MUST still fire (wrapper takes the top name,
    # exposes rst_n) so the TB binding `.rst_n` elaborates.
    f = _stage_rtl(tmp_path, _seq_core("reset_n"), "sequence_detector.v")
    res = R.step_reset_clock_variant_aliases(tmp_path, "sequence_detector")
    assert res.status == "PASS", (res.status, res.detail)
    body = f.read_text()
    assert "module sequence_detector (" in body and "input rst_n" in body
    assert "module sequence_detector__rcvar_inner(" in body

    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb; reg clk=0,rst_n=0,data_in=0; wire detected;"
        " sequence_detector dut(.clk(clk),.rst_n(rst_n),"
        ".data_in(data_in),.detected(detected)); endmodule\n")
    r = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "sd"), str(tb), str(f)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_noleak_prose_contract_does_not_block_legit_alias(tmp_path):
    # a design with a contract doc that mentions reset/clock ONLY in prose (no
    # port-decl context) must NOT suppress the legitimate reset_n->rst_n alias.
    f = _stage_rtl(tmp_path, _seq_core("reset_n"), "sequence_detector.v")
    _stage_contract_md(
        tmp_path,
        "A sequence detector. On reset the detector clears. It samples on the "
        "clock edge. The reset is asynchronous.")
    res = R.step_reset_clock_variant_aliases(tmp_path, "sequence_detector")
    assert res.status == "PASS", (res.status, res.detail)
    assert "input rst_n" in f.read_text()


def test_noleak_sdc_guard_618_still_works(tmp_path):
    # the #618 staged-SDC guard must still fire (independent of #689 contract).
    c = tmp_path / "input" / "constraints"
    c.mkdir(parents=True)
    (c / "constraint.sdc").write_text(
        "set clk_port_name clk_i\n"
        "create_clock -name core -period 10 [get_ports $clk_port_name]\n")
    f = _stage_rtl(
        tmp_path,
        "module chip_top (\n  input  clk_i,\n  input  rst_ni,\n"
        "  output [7:0] o\n);\n  assign o = 8'd0;\nendmodule\n",
        "chip_top.sv")
    res = R.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert res.status == "SKIP"
    assert "#618" in res.detail and "clk_i" in res.detail
    assert "clk_i" in f.read_text() and "__rcvar_inner" not in f.read_text()


def test_noleak_l9_guard_518_still_works(tmp_path):
    # the #518 L9 native-port guard must still fire.
    f = _stage_rtl(tmp_path, _seq_core("reset_n"), "sequence_detector.v")
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "sequence_detector",
        "top_ports": [{"name": "clk"}, {"name": "reset_n"},
                      {"name": "data_in"}, {"name": "detected"}]}))
    before = f.read_text()
    res = R.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert res.status == "SKIP", (res.status, res.detail)
    assert "L9 declares native port spelling" in res.detail
    assert f.read_text() == before


def test_explicit_prompt_interface_does_not_gain_reset_synonym(tmp_path):
    """AI-confirmed public contracts stay exact after Program generation."""
    rtl = (
        "module generic_counter(input clk, input reset, input direction, "
        "output reg [15:0] value);\n"
        "always @(posedge clk) if (reset) value<=0; "
        "else if(direction) value<=value+1; else value<=value-1;\n"
        "endmodule\n")
    f = _stage_rtl(tmp_path, rtl, "generic_counter.v")
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "input" / "phase1_prompt.md").write_text(
        "Input ports:\n"
        "  clk: system clock\n"
        "  reset: synchronous reset\n"
        "  direction: count direction\n\n"
        "Output ports:\n"
        "  value [15:0]: counter value\n")
    before = f.read_text()
    res = R.step_reset_clock_variant_aliases(tmp_path, "generic_counter")
    assert res.status == "SKIP", (res.status, res.detail)
    assert f.read_text() == before
    assert " rst" not in f.read_text()
    assert "__rcvar_inner" not in f.read_text()
