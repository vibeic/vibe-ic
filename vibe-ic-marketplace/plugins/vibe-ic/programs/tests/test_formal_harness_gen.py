"""Unit tests for formal_harness_gen.py (Step 5 DETERMINISTIC property author).

The parse/emit controls pin the interface /
reset-value parse, the construction-safety guards (non-literal reset values are
NEVER asserted), the thin-wrapper descent to the leaf logic module, and the
emitted-harness shape the Step-5 runner + abc-pdr proof depend on.

The parse fixtures are shaped like the REAL spm serial-parallel multiplier (a
sync active-high reset, a registered serial-product output aliased through a
reg) so a regression in the parser is caught deterministically.
The diagnostic-string regression also exercises the real native runner and
consumer on self-authored neutral RTL in the EDA image.
"""
import sys
from pathlib import Path
import pytest
import json
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import formal_harness_gen as G  # noqa: E402


# A shaped-like-real synchronous, active-high reset multiplier: output `p` is a
# wire aliased to `p_reg` which resets to 1'b0.  (chip-AGNOSTIC fixture.)
_SPM_LIKE = """
module spm #( parameter size = 32 ) (
    input  wire              clk,
    input  wire              rst,   // synchronous, active-high
    input  wire [size-1:0]   x,
    input  wire              y,
    output wire              p
);
    reg  [size:0] acc;
    wire [size:0] addend = y ? {x, 1'b0} : {(size+1){1'b0}};
    wire [size:0] sum    = acc + addend;
    always @(posedge clk) begin
        if (rst) acc <= {(size+1){1'b0}};
        else     acc <= {1'b0, sum[size:1]};
    end
    reg p_reg;
    always @(posedge clk) begin
        if (rst) p_reg <= 1'b0;
        else     p_reg <= sum[0];
    end
    assign p = p_reg;
endmodule
"""

_WRAPPER = """
module chip_top #( parameter size = 32 ) (
    input wire clk, input wire rst, input wire [size-1:0] x, input wire y,
    output wire p);
  spm #(.size(size)) u_dut (.clk(clk), .rst(rst), .x(x), .y(y), .p(p));
endmodule
"""


def _gen(tmp_path, text, name="dut.v", **kw):
    f = tmp_path / name
    f.write_text(text)
    out = tmp_path / "harness.sv"
    return G.generate(rtl=[f], out=out, **kw), out


# ── comment hygiene ─────────────────────────────────────────────────────────
def test_strip_comments():
    assert "secret" not in G.strip_comments("a // secret\n/* b\n c */d")
    # newlines preserved so line structure survives
    assert G.strip_comments("a // x\nb").count("\n") == 1


# ── module header parse ─────────────────────────────────────────────────────
def test_parse_module_params_and_ports():
    m = G.parse_module(_SPM_LIKE, "spm")
    assert m is not None
    assert ("size", "32") in m.params
    dirs = {p.name: p.direction for p in m.ports}
    assert dirs == {"clk": "input", "rst": "input", "x": "input",
                    "y": "input", "p": "output"}
    widths = {p.name: p.width for p in m.ports}
    assert widths["x"] == "[size-1:0]" and widths["p"] == ""


def test_classify_clock_and_reset_active_high():
    m = G.parse_module(_SPM_LIKE, "spm")
    assert G.classify_clock(m.ports) == "clk"
    name, active_low = G.classify_reset(m.ports, m.body)
    assert name == "rst" and active_low is False


def test_classify_reset_active_low_by_name_and_usage():
    body = "always @(posedge clk) if (!rst_n) q <= 1'b0; else q <= d;"
    ports = [G.Port("input", "", "clk"), G.Port("input", "", "rst_n"),
             G.Port("input", "", "d"), G.Port("output", "", "q")]
    name, active_low = G.classify_reset(ports, body)
    assert name == "rst_n" and active_low is True


# ── reset-constant normalization (construction-safety core) ─────────────────
def test_normalize_reset_const_zero_forms():
    for z in ("0", "1'b0", "8'h00", "'0", "{(size+1){1'b0}}", "{9{1'b0}}"):
        assert G._normalize_reset_const(z) == "'0"


def test_normalize_reset_const_literal_and_reject():
    assert G._normalize_reset_const("1'b1") == "1'b1"
    assert G._normalize_reset_const("8'hFF") == "8'hFF"
    # NON-literal reset values must be REJECTED (never assert a guessed value)
    assert G._normalize_reset_const("d") is None
    assert G._normalize_reset_const("q + 1") is None
    assert G._normalize_reset_const("some_signal") is None


# ── reset FF discovery: sync + async ────────────────────────────────────────
def test_find_reset_ffs_sync():
    m = G.parse_module(_SPM_LIKE, "spm")
    ffs = {f.signal: f for f in G.find_reset_ffs(m.body, "rst", False)}
    assert ffs["p_reg"].value == "'0" and ffs["p_reg"].is_async is False
    assert ffs["acc"].value == "'0"


def test_find_reset_ffs_async():
    body = ("always @(posedge clk or negedge rst_n) "
            "if (!rst_n) q <= 1'b0; else q <= ~q;")
    ffs = G.find_reset_ffs(body, "rst_n", True)
    assert len(ffs) == 1 and ffs[0].signal == "q" and ffs[0].is_async is True


def test_find_reset_ffs_combinational_block_ignored():
    body = "always @(*) o = a & b;"
    assert G.find_reset_ffs(body, "rst", False) == []


# ── alias resolution ────────────────────────────────────────────────────────
def test_alias_map_only_plain_identifier():
    amap = G._alias_map("assign p = p_reg; assign s = a + b; assign z = w;")
    assert amap == {"p": "p_reg", "z": "w"}   # expression RHS not aliased


# ── derive_reset_props (the property set) ───────────────────────────────────
def test_derive_reset_props_via_alias():
    m = G.parse_module(_SPM_LIKE, "spm")
    props = G.derive_reset_props(m, "rst", False)
    assert len(props) == 1
    p = props[0]
    assert p.output == "p" and p.target == "p_reg" and p.value == "'0"


_DIAGNOSTIC_DIRECT = ('module neutral_register(input clk,rst,data,output reg held); '
    'always @(posedge clk) begin if(rst) held<=0; else held<=data; '
    '$display("assign held = data;"); end endmodule\n')
_NEUTRAL_GATED = ('module neutral_register(input clk,rst,data,output wire held); '
    'reg stored; always @(posedge clk) if(rst) stored<=0; else stored<=data; '
    'assign held=!rst && stored; endmodule\n')


def _diagnostic_project(project, text):
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    for name, value in (
        ("L3_CMD_PROTOCOL.json", {"no_opcodes_in_input": True}),
        ("L6_FSM.json", {"no_fsm_in_input": True}),
        ("L8_TIMING_WAVEFORM.json", {"formal_applicability": {
            "status": "NOT_APPLICABLE", "reason": "Neutral INPUT declares no additional waveform obligations beyond the synchronous RTL reset contract."}})):
        (docs / name).write_text(json.dumps(value))
    rtl = project / "phase2/stage1/rtl/neutral_register.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(text)
    return rtl


def _native_diagnostic_proof(project, rtl, floor):
    from not_verified_tier import skip_not_verified
    if any(shutil.which(tool) is None for tool in ("yosys", "sby")):
        skip_not_verified("native diagnostic reset control needs yosys/sby",
                          "Run this module in the pinned EDA image")
    import formal_property_run as runner
    import formal_proof_evidence_check as consumer
    proof = runner.run(project, harness=Path(floor["harness_path"]), rtl=[rtl],
        top=floor["harness_module"], container=None, timeout=60,
        mem_limit_kb=4 * 1024 * 1024, prove_engines="direct")
    checked = consumer.audit(project)
    (project / "native-diagnostic-receipt.json").write_text(json.dumps({
        "floor": floor, "proof": proof, "consumer": checked}, indent=2))
    return proof, checked


def test_current_native_floor_keeps_direct_reset_output_with_hdl_diagnostic_string(tmp_path):
    rtl = _diagnostic_project(tmp_path, _DIAGNOSTIC_DIRECT)
    floor = G.generate(project=tmp_path, top="neutral_register", assertion_form="immediate")
    assert floor["rc"] == 0, floor
    assert floor["verdict"] == "EMITTED"
    assert floor["properties"] == [{"output": "held", "target": "held",
        "reset_value": "'0", "reset_style": "sync"}]
    assert floor["property_denominator"] == floor["authored_property_count"] == 1
    assert rtl.read_text() == _DIAGNOSTIC_DIRECT
    proof, checked = _native_diagnostic_proof(tmp_path, rtl, floor)
    assert proof["verdict"] == checked["verdict"] == "PASS"
    assert proof["all_proved"] is True
    assert {p["status"] for p in proof["properties"]} == {"PASS"}


@pytest.mark.parametrize("style,message", [
    ("plain", "always_ff held <= data;"),
    ("gated", "assign held = data;"),
    ("gated", "assign stored = data;"),
    ("gated", "always_ff stored <= data;"),
    ("gated", "always_comb held = data;"),
])
def test_plain_and_gated_driver_analysis_ignores_diagnostic_strings(tmp_path, style, message):
    expression = "stored" if style == "plain" else "!rst && stored"
    text = ('module neutral_register(input clk,rst,data,output wire held); reg stored; '
        'always @(posedge clk) begin if(rst) stored<=0; else stored<=data; '
        f'$display("{message}"); end assign held={expression}; endmodule\n')
    result, _ = _gen(tmp_path, text)
    assert result["verdict"] == "EMITTED", result
    assert result["properties"] == [{"output": "held", "target": "stored",
        "reset_value": "'0", "reset_style": "sync"}]


def test_gated_driver_analysis_ignores_comments(tmp_path):
    text = _NEUTRAL_GATED.replace("endmodule", "// always_ff stored <= data;\n/* assign held = data; */\nendmodule")
    result, _ = _gen(tmp_path, text)
    assert result["verdict"] == "EMITTED"
    assert result["properties"][0]["target"] == "stored"


@pytest.mark.parametrize("expression,extra", [
    ("!rst && stored", "assign held = data;"),
    ("!rst && stored", "always @(posedge clk) stored <= data;"),
    ("rst && stored", ""),
    ("!rst && data", ""),
])
def test_diagnostic_strings_do_not_hide_real_invalid_gated_drivers(tmp_path, expression, extra):
    text = ('module neutral_register(input clk,rst,data,output wire held); reg stored; '
        'always @(posedge clk) begin if(rst) stored<=0; else stored<=data; '
        '$display("assign held = !rst && stored; always_ff stored <= data;"); end '
        f'assign held={expression}; {extra} endmodule\n')
    result, _ = _gen(tmp_path, text)
    assert result["rc"] == 2 and result["verdict"] == "NOT_APPLICABLE", result


@pytest.mark.parametrize("mutation", [None, "missing_gate", "wrong_polarity", "input_driver"])
def test_same_native_gated_property_keeps_current_reset_first_edge_semantics(tmp_path, mutation):
    rtl = _diagnostic_project(tmp_path, _NEUTRAL_GATED)
    floor = G.generate(project=tmp_path, top="neutral_register", assertion_form="immediate")
    assert floor["rc"] == 0 and floor["property_denominator"] == 1
    harness = Path(floor["harness_path"]).read_bytes()
    assert b"rst_active || (f_past_valid && rst_active_q)" in harness
    if mutation == "missing_gate":
        rtl.write_text(_NEUTRAL_GATED.replace("!rst && stored", "stored"))
    elif mutation == "wrong_polarity":
        rtl.write_text(_NEUTRAL_GATED.replace("!rst && stored", "rst && stored"))
    elif mutation == "input_driver":
        rtl.write_text(_NEUTRAL_GATED.replace("!rst && stored", "!rst && data"))
    proof, checked = _native_diagnostic_proof(tmp_path, rtl, floor)
    assert Path(floor["harness_path"]).read_bytes() == harness
    expected = "PASS" if mutation is None else "FAIL"
    assert proof["verdict"] == checked["verdict"] == expected
    assert {p["status"] for p in proof["properties"]} == {expected}
    assert proof["all_proved"] is (mutation is None)


def _gated_output(expression, reset="rst", reset_condition="rst",
                  reset_value="1'b0", extra="", output_width=""):
    return f"""module gated_output(input clk, {reset}, d,
        output wire {output_width} admitted);
        reg launch;
        always @(posedge clk)
            if ({reset_condition}) launch <= {reset_value};
            else launch <= d;
        assign admitted = {expression};
        {extra}
    endmodule"""


@pytest.mark.parametrize("expression", [
    "!rst && launch", "launch && !rst", "~rst & launch",
    "((! (rst)) && (launch))",
])
def test_generate_reset_gated_registered_output(tmp_path, expression):
    result, out = _gen(tmp_path, _gated_output(expression))
    assert result["verdict"] == "EMITTED"
    assert result["properties"] == [{
        "output": "admitted", "target": "launch", "reset_value": "'0",
        "reset_style": "sync"}]
    assert "|-> (admitted == '0)" in out.read_text()
    assert "(rst_active || (f_past_valid && rst_active_q)) |->" in out.read_text()


@pytest.mark.parametrize("expression", ["rst_n && launch", "launch & (rst_n)"])
def test_generate_reset_gated_active_low(tmp_path, expression):
    result, _ = _gen(tmp_path, _gated_output(
        expression, reset="rst_n", reset_condition="!rst_n"))
    assert result["verdict"] == "EMITTED"
    assert result["properties"][0]["output"] == "admitted"
    assert result["properties"][0]["target"] == "launch"
    iface = G.parse_module(_gated_output(
        expression, reset="rst_n", reset_condition="!rst_n"), "gated_output")
    immediate = G.emit_harness(iface, "clk", "rst_n", True,
        G.derive_reset_props(iface, "rst_n", True), assertion_form="immediate")
    assert "if (rst_active || (f_past_valid && rst_active_q))" in immediate


@pytest.mark.parametrize("expression,kwargs", [
    ("rst && launch", {}),                         # wrong polarity
    ("!rst && d", {}),                             # input, not register
    ("!rst && missing", {}),                       # undriven register atom
    ("!rst && launch", {"reset_value": "1'b1"}),    # released gate is nonzero
    ("!(rst && launch)", {}),                      # whole-expression NOT
    ("(!rst && launch) || d", {}),                  # unsupported expression
    ("!rst && launch && d", {}),                   # additional qualifier
    ("!rst && launch", {"output_width": "[3:0]"}),  # outside scalar grammar
    ("!rst && launch", {"extra": "assign admitted = d;"}),
    ("!rst && launch", {"extra": "always @(posedge clk) launch <= d;"}),
    ("!rst && launch", {"extra": "always_ff @(posedge clk) launch <= d;"}),
    ("!rst && launch", {"extra": "always_comb launch = d;"}),
    ("!rst && launch", {"extra": "always @(posedge clk) if (rst) admitted <= 0; else admitted <= d;"}),
    ("!rst && launch", {"extra": "always_ff @(posedge clk) if (rst) admitted <= 0; else admitted <= d;"}),
    ("!rst && launch", {"extra": "always_comb admitted = d;"}),
    ("!rst && launch", {"extra": "assign launch = d;"}),
])
def test_generate_reset_gated_unsupported_refused(tmp_path, expression, kwargs):
    result, _ = _gen(tmp_path, _gated_output(expression, **kwargs))
    assert result["verdict"] == "NOT_APPLICABLE"
    assert result["rc"] == 2
    assert "construction-safe" in result["reason"]


def test_derive_reset_props_omits_nonliteral_output():
    text = """
    module multi(input clk, input reset, input [7:0] din,
                 output reg [7:0] a, output reg valid, output reg [7:0] b);
      always @(posedge clk) begin
        if (reset) begin a <= 8'h00; valid <= 1'b0; b <= din; end
        else begin a <= din; valid <= 1'b1; b <= b; end
      end
    endmodule"""
    m = G.parse_module(text, "multi")
    props = {p.output: p.value for p in G.derive_reset_props(m, "reset", False)}
    # a and valid have literal resets; b resets from an INPUT → must be omitted
    assert props == {"a": "'0", "valid": "'0"}
    assert "b" not in props


# ── generate: EMITTED + NOT_APPLICABLE fail-safe contract ───────────────────
def test_generate_emitted_spm_like(tmp_path):
    res, out = _gen(tmp_path, _SPM_LIKE)
    assert res["verdict"] == "EMITTED" and res["rc"] == 0
    assert res["top"] == "spm" and res["clock"] == "clk"
    assert res["reset"] == "rst" and res["reset_active_low"] is False
    assert res["properties"] == [
        {"output": "p", "target": "p_reg", "reset_value": "'0",
         "reset_style": "sync"}]
    h = out.read_text()
    # CONCURRENT form: the gate at step 5 requires a named property and an
    # `assert property`, and until the EDA image carried a frontend that could
    # PARSE one there was no honest way to emit it.  Pinned as three separate
    # facts rather than one literal, so a regression says which half broke:
    # the property must be declared, it must carry the guarded implication, and
    # something must actually assert it.  A harness with the property and no
    # assert parses, satisfies half the gate, and proves nothing.
    assert "property p_reset_safety_1;" in h
    assert "endproperty" in h
    assert "|-> (p == '0)" in h, (
        "the implication must be OVERLAPPING — `|=>` would move the consequent "
        "one cycle later and prove something the design does not claim")
    assert "assert property (p_reset_safety_1)" in h
    assert "(* anyseq *) wire rst;" in h
    assert "f_past_valid && rst_active_q" in h   # sync guard


def test_generate_not_applicable_combinational(tmp_path):
    res, _ = _gen(tmp_path,
                  "module a(input [3:0] x, output [3:0] y); assign y=~x; endmodule")
    assert res["verdict"] == "NOT_APPLICABLE" and res["rc"] == 2


def test_generate_not_applicable_no_literal_reset(tmp_path):
    res, _ = _gen(tmp_path,
                  "module m(input clk, input rst, input [7:0] d, "
                  "output reg [7:0] o); always @(posedge clk) "
                  "if (rst) o <= d; else o <= o; endmodule")
    assert res["verdict"] == "NOT_APPLICABLE" and res["rc"] == 2


def test_generate_not_applicable_inout(tmp_path):
    res, _ = _gen(tmp_path,
                  "module io(input clk, input rst, inout sda, output reg q); "
                  "always @(posedge clk) if (rst) q <= 1'b0; endmodule")
    assert res["verdict"] == "NOT_APPLICABLE"
    assert "inout" in res["reason"]


def test_generate_active_low_nonzero_literal(tmp_path):
    res, out = _gen(tmp_path,
                    "module c #(parameter W=8)(input clk, input rst_n, "
                    "input en, output reg [W-1:0] q); always @(posedge clk) "
                    "if (!rst_n) q <= 8'hFF; else if (en) q <= q + 1; endmodule")
    assert res["verdict"] == "EMITTED"
    assert res["reset"] == "rst_n" and res["reset_active_low"] is True
    h = out.read_text()
    assert "wire rst_active = !rst_n;" in h
    # CONCURRENT form: the gate at step 5 requires a named property and an
    # `assert property`, and until the EDA image carried a frontend that could
    # PARSE one there was no honest way to emit it.  Pinned as three separate
    # facts rather than one literal, so a regression says which half broke:
    # the property must be declared, it must carry the guarded implication, and
    # something must actually assert it.  A harness with the property and no
    # assert parses, satisfies half the gate, and proves nothing.
    assert "property p_reset_safety_1;" in h
    assert "endproperty" in h
    assert "|-> (q == 8'hFF)" in h, (
        "the implication must be OVERLAPPING — `|=>` would move the consequent "
        "one cycle later and prove something the design does not claim")
    assert "assert property (p_reset_safety_1)" in h


# ── thin-wrapper descent to the leaf logic module ──────────────────────────
def test_generate_descends_thin_wrapper(tmp_path):
    (tmp_path / "chip_top.v").write_text(_WRAPPER)
    (tmp_path / "spm.v").write_text(_SPM_LIKE)
    out = tmp_path / "h.sv"
    res = G.generate(rtl=[tmp_path / "chip_top.v", tmp_path / "spm.v"],
                     top="chip_top", out=out)
    assert res["verdict"] == "EMITTED"
    assert res["top"] == "spm"                 # descended to the leaf
    assert res["declared_top"] == "chip_top"
    assert res["descended_to_leaf"] is True
    assert "spm #(.size(size)) dut" in out.read_text()


# ── chip-AGNOSTIC / anti-fabrication guards ─────────────────────────────────
def test_emitted_harness_only_uses_design_own_names(tmp_path):
    """The harness must contain ONLY the design's own port/signal names + the
    generic formal scaffold — no vendor/PDK/SKU literal is ever synthesised."""
    _, out = _gen(tmp_path, _SPM_LIKE)
    h = out.read_text()
    # every asserted comparison value came from the RTL's own reset branch
    assert "== '0" in h
    # generic scaffold only
    assert "`default_nettype none" in h and "endmodule" in h


def test_generate_never_asserts_a_guessed_value(tmp_path):
    """Regression guard: for a registered output whose reset value is NOT a
    literal, the generator must emit NO assertion for it (a wrong asserted value
    would produce a FALSE counterexample and regress a passing cell to FAIL)."""
    text = ("module g(input clk, input rst, input [3:0] seed, "
            "output reg [3:0] o); always @(posedge clk) "
            "if (rst) o <= seed; else o <= o + 1; endmodule")
    res, _ = _gen(tmp_path, text)
    assert res["verdict"] == "NOT_APPLICABLE"   # nothing construction-safe


# ── issue #1974: declaration denominator + honest fallback ────────────────
def _write_doc(project, name, data):
    import json
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data))


def _write_project_rtl(project, text):
    d = project / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    (d / "dut.v").write_text(text)


def test_explicit_global_formal_inapplicable_is_the_only_not_applicable(tmp_path):
    _write_doc(tmp_path, "L22_VERIFICATION_PLAN.json", {
        "fields": {"formal_applicability": {
            "status": "NOT_APPLICABLE",
            "reason": "This declaration defines a pure analog block with no RTL state."}}})
    res = G.generate(project=tmp_path, top="none")
    assert res["verdict"] == "NOT_APPLICABLE"
    assert res.get("reason") == (
        "This declaration defines a pure analog block with no RTL state.")
    assert res.get("property_denominator", -1) == 0
    contract = (tmp_path / "phase2/stage1/formal/property_contract.json").read_text()
    assert "pure analog block" in contract
    assert not (tmp_path / "phase2/stage1/formal/formal_authoring_request.json").exists()


def test_program_floor_counts_l3_l6_l8_and_routes_unresolved_to_expert(tmp_path):
    import json
    _write_doc(tmp_path, "L3_CMD_PROTOCOL.json", {
        "no_opcodes_in_input": False,
        "opcodes": [{"name": "START", "hex": "0x01", "purpose": "begin"}]})
    _write_doc(tmp_path, "L6_CONTROL_LOGIC.json", {
        "no_fsm_in_input": False,
        "fsm_states": [{"name": "IDLE", "transitions": ["IDLE -> RUN on start"]}]})
    _write_doc(tmp_path, "L8_TIMING_WAVEFORM.json", {
        "timing_constants": {"reset_release_cycles": 2}})
    _write_project_rtl(tmp_path, _SPM_LIKE.replace("module spm", "module dut"))

    res = G.generate(project=tmp_path, top="dut")
    assert res["verdict"] == "EMITTED"
    assert res.get("authored_property_count", -1) == 1
    assert res.get("property_denominator", -1) == 4
    ids = {row["id"] for row in res.get("unresolved_obligations", [])}
    assert ids == {"L3.opcode.START", "L6.fsm_state.IDLE",
                   "L8.timing_constants.reset_release_cycles"}
    req = json.loads((tmp_path /
        "phase2/stage1/formal/formal_authoring_request.json").read_text())
    assert req["verdict"] == "INCOMPLETE"
    assert req["fallback_skill"] == "formal-verify"
    assert req["invocation_status"] == "REQUIRED_NOT_INVOKED"


def test_applicable_but_unanswerable_authoring_is_incomplete_not_skip(tmp_path):
    import json
    _write_doc(tmp_path, "L3_CMD_PROTOCOL.json", {"no_opcodes_in_input": True})
    _write_doc(tmp_path, "L6_CONTROL_LOGIC.json", {"no_fsm_in_input": True})
    _write_doc(tmp_path, "L8_TIMING_WAVEFORM.json", {
        "formal_applicability": {"status": "NOT_APPLICABLE",
                                  "reason": "No cycle timing was declared."}})
    _write_project_rtl(
        tmp_path,
        "module dut(input [3:0] x, output [3:0] y); assign y = ~x; endmodule")

    res = G.generate(project=tmp_path, top="dut")
    assert res["verdict"] == "INCOMPLETE"
    assert res["fallback_skill"] == "formal-verify"
    assert [row["id"] for row in res["unresolved_obligations"]] == [
        "RTL.sound_property_missing"]
    req = json.loads((tmp_path /
        "phase2/stage1/formal/formal_authoring_request.json").read_text())
    assert req["verdict"] == "INCOMPLETE"
    assert "construction-safe property" in req["unresolved_obligations"][0]["description"]
