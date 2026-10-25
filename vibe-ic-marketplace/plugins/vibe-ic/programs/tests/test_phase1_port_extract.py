"""phase1_port_extract — deterministic PORT/PARAM/RESET extraction for Phase-1 NL.

Field measurement (CVDP 12-prompt AI-vs-program audit): the phase1 NL ingester
captured only ~17% of an AI's ports because it (a) only recognised inline Verilog
declarations, (b) `_parse_md_table_ports` did not recognise the common `In/Out`
direction header or `Length` width header, and (c) returned only the single
largest interface table when a spec splits clock/reset, input and output into
SEPARATE tables. This validates the three structural fixes — and asserts the
gates' single-best contract is preserved (union is opt-in).
"""
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import _specrtl_common as S   # noqa: E402
import phase1_port_extract as PX  # noqa: E402

# A spec that splits its interface across THREE tables with `In/Out` + `Length`
# headers and `in`/`out` values — the dominant CVDP form.
_MULTI_TABLE = """\
### Clock / Reset
| Name | In/Out | Length | Description |
|------|--------|--------|-------------|
| Clk  | in     | 1      | clock |
| Rst  | in     | 1      | async reset |

### Input Data
| Name     | In/Out | Length      | Description |
|----------|--------|-------------|-------------|
| In_Data  | in     | `WIDTH`     | data in |
| In_Valid | in     | 1           | valid |

### Output Data
| Name      | In/Out | Length | Description |
|-----------|--------|--------|-------------|
| Out_Data  | out    | 8      | data out |
| Out_Valid | out    | 1      | valid |
"""


def test_in_out_header_recognised():
    assert S._DIR_HDR.match("In/Out")
    assert S._DIR_HDR.match("I/O")          # back-compat
    assert S._DIR_HDR.match("Direction")


def test_length_width_header_recognised():
    assert S._WIDTH_HDR.match("Length")
    assert S._WIDTH_HDR.match("Len")
    assert S._WIDTH_HDR.match("Width")      # back-compat


def test_union_collects_every_interface_table():
    names = {p.name for p in S._parse_md_table_ports(_MULTI_TABLE, union=True)[0]}
    assert names == {"Clk", "Rst", "In_Data", "In_Valid", "Out_Data", "Out_Valid"}


def test_default_is_single_best_table_gate_contract_preserved():
    # §4.05: the conformance gates rely on the single-best contract — default
    # (union=False) must still return ONLY the largest qualifying table.
    best, _ = S._parse_md_table_ports(_MULTI_TABLE)   # union defaults to False
    # the largest table here has 2 ports; best must be one 2-port table, not all 6
    assert len(best) == 2


def test_phase1_extractor_unions_all_ports():
    ports = {p["name"] for p in PX.extract_ports(_MULTI_TABLE)}
    assert ports == {"Clk", "Rst", "In_Data", "In_Valid", "Out_Data", "Out_Valid"}
    # direction + width carried
    by = {p["name"]: p for p in PX.extract_ports(_MULTI_TABLE)}
    assert by["Out_Data"]["dir"] == "output" and by["Out_Data"]["width"] == 8


def test_param_table_and_decl_extracted():
    txt = ("| Name | Default | Description |\n|---|---|---|\n"
           "| WIDTH | 32 | data width |\n| DEPTH | 8 | fifo depth |\n"
           "Also `parameter N = 4;` inline.\n")
    params = {p["name"]: p["default"] for p in PX.extract_params(txt)}
    assert params.get("WIDTH") == "32" and params.get("DEPTH") == "8"
    assert params.get("N") == "4"


def test_reset_polarity_inferred():
    r = PX.extract("input rst_n; // active-low asynchronous reset")
    assert r["reset"]["name"].lower() == "rst_n"
    assert r["reset"]["polarity"] == "active_low"


def test_prose_does_not_inject_phantom_ports():
    """PRECISION: parse_verilog_ports is run ONLY inside real Verilog code regions
    (fenced blocks / module…endmodule), so a prose sentence that merely contains
    `input`/`output` words never scrapes a phantom port (the #27/#28 prose-scrape
    class). A pure-prose spec with no table/code yields ZERO ports — not garbage."""
    prose = ("The module takes input data and produces an output result. The "
             "input is latched and the output drives the bus. Inputs include a "
             "clock and a reset signal.")
    assert PX.extract_ports(prose) == []


def test_code_block_ports_extracted_but_its_comments_are_not():
    code = ("```verilog\nmodule m (\n"
            "  input  wire clk,        // the system clock\n"
            "  output reg  done\n);\nendmodule\n```\n")
    names = {p["name"] for p in PX.extract_ports(code)}
    assert names == {"clk", "done"}, names  # 'the' (comment) must NOT appear


def test_regmap_table_extracted_with_offset_access_width():
    """A register-map table (distinguished by an Offset/Address column, headers
    possibly **bold**) is parsed into {name, offset, access, width}."""
    txt = ("| **Register** | **Offset** | **Access** | **Bit Width** |\n"
           "|---|---|---|---|\n"
           "| Beat  | 0x100 | Read/Write | 20 |\n"
           "| ID    | 0x500 | Read-Only  | 32 |\n")
    regs = {r["name"]: r for r in PX.extract_regmap(txt)}
    assert set(regs) == {"Beat", "ID"}
    assert regs["Beat"]["offset"] == "0x100" and regs["Beat"]["width"] == 20
    assert regs["ID"]["access"] == "Read-Only"


def test_port_table_not_mistaken_for_regmap():
    """§4.05: a port table (direction column, NO offset column) must NOT be
    harvested as a register map."""
    txt = ("| Name | In/Out | Length |\n|---|---|---|\n"
           "| clk | in | 1 |\n| dout | out | 8 |\n")
    assert PX.extract_regmap(txt) == []


# ── structured-prose signal-definition list (no table / no code) ──────────────

_PROSE_SIGLIST = """\
- **Inputs**:
  - `clk`: Clock signal, positive edge.
  - `rst`: Active high synchronous reset signal.
  - `go`: Start signal. Active high.
  - `A [WIDTH-1:0]`: input value A.
- **Outputs**:
  - `done`: Signal indicating completion.
  - `OUT [WIDTH-1:0]`: the GCD result.
"""


def test_prose_signal_definition_list_extracted_with_direction():
    by = {p["name"]: p for p in PX.extract_prose_ports(_PROSE_SIGLIST)}
    assert set(by) == {"clk", "rst", "go", "A", "done", "OUT"}
    assert by["clk"]["dir"] == "input" and by["done"]["dir"] == "output"


def test_prose_reference_bullet_not_a_port():
    """PRECISION: a bullet that REFERENCES signals in prose (name NOT immediately
    followed by `:`) must not be harvested — only definition bullets are."""
    txt = ("- `item_button` and `cancel` are treated as toggle signals.\n"
           "- This prevents continuous-signal registration.\n")
    assert PX.extract_prose_ports(txt) == []


def test_prose_section_descriptor_label_not_a_port():
    """PRECISION: a TitleCase descriptor bullet ('- **Clock:** the `clk` signal …')
    is a section label, not the port (the real port is the backtick token)."""
    txt = ("- **Clock:** The `clk` signal is the rising edge of the clock.\n"
           "- **Reset:** Active-low asynchronous reset.\n")
    names = {p["name"] for p in PX.extract_prose_ports(txt)}
    assert "Clock" not in names and "Reset" not in names


def test_prose_fallback_only_when_no_table_or_code():
    """The prose list is a FALLBACK — a design with a real port table uses the
    table (higher confidence), not the prose path."""
    txt = ("| Name | In/Out | Length |\n|---|---|---|\n"
           "| clk | in | 1 |\n| dout | out | 8 |\n"
           "- `something`: described in prose elsewhere\n")
    names = {p["name"] for p in PX.extract_ports(txt)}
    assert names == {"clk", "dout"}


def test_enums_verilog_multi_decl_and_table():
    code = ("```\nlocalparam IDLE = 2'b00, RUN = 2'b01, DONE = 2'b10;\n"
            "parameter MODE_ADD = 8'h01;\n```\n")
    by = {e["name"]: e["value"] for e in PX.extract_enums(code)}
    assert by == {"IDLE": "2'b00", "RUN": "2'b01", "DONE": "2'b10",
                  "MODE_ADD": "8'h01"}
    tbl = "| State | Encoding |\n|---|---|\n| S_IDLE | 2'b00 |\n| S_GO | 2'b01 |\n"
    names = {e["name"] for e in PX.extract_enums(tbl)}
    assert names == {"S_IDLE", "S_GO"}


def test_enums_prose_no_false_positive():
    assert PX.extract_enums("The state word appears in prose; clk = the clock.") == []


# ── Step-2.7 §4.05: region gate must validate Verilog CONTENT, not just "in a
# fence / module-span" — else a non-Verilog fence or a prose module…endmodule
# span scrapes phantom ports into an otherwise-empty L-doc. ───────────────────

def test_no_phantom_from_non_verilog_fence():
    """A bare/pseudo-code fence (logs, pseudo-code) must not be scraped: a line
    `input message byte stream` is prose, not a Verilog port decl."""
    crc = ("# CRC8 Generator\n```\n"
           "input message byte stream\noutput crc value after last byte\n```\n")
    assert PX.extract_ports(crc) == []


def test_no_phantom_from_prose_module_span():
    """The bare words module…endmodule in spec prose must not form a parseable
    Verilog region."""
    prose = ("Each module accepts an input signal stream and produces an output "
             "result. You must declare every endmodule explicitly.")
    assert PX.extract_ports(prose) == []


def test_no_phantom_from_fenced_python():
    """A python fence using input()/`output =` must yield no ports."""
    py = "```python\nx = input('go: ')\noutput = compute(x)\nfor input in items:\n    pass\n```"
    assert PX.extract_ports(py) == []


def test_genuine_verilog_regions_still_extracted():
    """Regression: real Verilog (module header, bare `,`-terminated port snippet,
    `;`-terminated decls) must STILL be extracted after the content gate."""
    mod = "```verilog\nmodule m(input clk, input [7:0] a, output reg q); endmodule\n```"
    assert {p["name"] for p in PX.extract_ports(mod)} == {"clk", "a", "q"}
    snip = "```\ninput clk,\noutput q\n```"
    assert {p["name"] for p in PX.extract_ports(snip)} >= {"clk", "q"}


_PROSE_FIELD_CASES = [
    ("Input ports:\n    Carry: Carry-in input.\n    Clk: Clock signal.\n"
     "    Rst: Reset signal.\nOutput port:\n"
     "    Q: 64-bit register representing the current count value.\n",
     {"Carry": ("input", 1), "Clk": ("input", 1),
      "Rst": ("input", 1), "Q": ("output", 64)}),
    ("Outputs:\n    clock[7:0]: An 8-bit output representing an internal count.\n"
     "    amber, cyan, magenta: Output status signals.\n",
     {"clock": ("output", 8), "amber": ("output", 1),
      "cyan": ("output", 1), "magenta": ("output", 1)}),
    ("Input ports:\n    wdata: Write data input. The width [WIDTH-1:0] is configurable.\n"
     "Output ports:\n    rdata: Read data output. The width [WIDTH-1:0] is configurable.\n"
     "Parameter:\n    WIDTH = 8\n    DEPTH = 16\n",
     {"wdata": ("input", 8), "rdata": ("output", 8)}),
]


@pytest.mark.parametrize("text,expected", _PROSE_FIELD_CASES)
def test_explicit_prose_port_fields(text, expected):
    actual = {row["name"]: (row["dir"], row["width"])
              for row in PX.extract_prose_ports(text)}
    assert actual == expected


@pytest.mark.parametrize("text,expected", _PROSE_FIELD_CASES)
def test_prose_port_field_shapes_reach_all_generated_aliases(tmp_path, text, expected):
    import json
    import subprocess
    import phase1_doc_one_shot_runner as producer

    source = tmp_path / "input/docs/interface.txt"
    source.parent.mkdir(parents=True)
    source.write_text(text)
    run = subprocess.run([sys.executable, producer.__file__, str(tmp_path)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    generated = tmp_path / "phase1/generated_docs"
    l1 = json.loads((generated / "L1_DATASHEET.json").read_text())
    l9 = json.loads((generated / "L9_INTEGRATION_SPEC.json").read_text())
    for rows in [l1["pin_table"], *(l9[key] for key in
                                   ("ports", "top_ports", "top_module_pins"))]:
        assert {row["name"]: ({"in": "input", "out": "output"}.get(
                    row["mode"], row["mode"]), row["width"])
                for row in rows} == expected


def test_unresolved_prose_dimension_is_not_a_scalar():
    rows = PX.extract_prose_ports(
        "Input ports:\n    payload[UNDECLARED-1:0]: Input data.\n")
    assert [(row["name"], row["dir"], row["width"]) for row in rows] == [
        ("payload", "input", S.WIDTH_UNKNOWN)]


def test_implementation_assignment_cannot_supply_an_undeclared_parameter():
    rows = PX.extract_prose_ports(
        "Input ports:\n    payload[SIZE-1:0]: Input data.\n"
        "Implementation:\n    SIZE = 8\n")
    assert [(row["name"], row["width"]) for row in rows] == [
        ("payload", S.WIDTH_UNKNOWN)]


def test_port_section_does_not_promote_later_internal_or_context_definitions():
    text = ("Input ports:\n    Clk: Clock signal.\n"
            "Internal registers:\n    shadow: 32-bit internal register.\n"
            "Output format:\n    trace: 64-bit output record.\n"
            "Implementation:\n    red, yellow, green: Internal signals.\n")
    assert {row["name"]: row["dir"]
            for row in PX.extract_prose_ports(text)} == {"Clk": "input"}


# Same issue3578 family: source-owned parametric interface, including refusal.
def _parametric_contract_fixture(name):
    from programs.tests._hostpaths import require_repo
    return require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                        "tests", "fixtures", "phase1_local",
                        "neutral_parametric_interface", name + ".md").read_text()


def _parametric_contract_generate(tmp_path, text, expected_rc=0):
    import json
    import subprocess
    import phase1_doc_one_shot_runner as producer
    source = tmp_path / "input/docs/current.md"
    source.parent.mkdir(parents=True)
    source.write_text(text)
    run = subprocess.run([sys.executable, producer.__file__, str(tmp_path)],
                         capture_output=True, text=True)
    assert run.returncode == expected_rc, run.stdout + run.stderr
    return {name: json.loads((tmp_path / "phase1/generated_docs" /
                             (name + ".json")).read_text()) for name in
            ("L1_DATASHEET", "L8_RTL_CONSTANTS", "L9_INTEGRATION_SPEC")}


def _parametric_contract_aliases(docs):
    l9 = docs["L9_INTEGRATION_SPEC"]
    return [docs["L1_DATASHEET"]["pin_table"],
            *(l9[key] for key in ("ports", "top_ports", "top_module_pins"))]


def test_parametric_contract_declaration_reader_keeps_absent_defaults():
    text = ('Input parameters:\n    FRACTION: Number of fractional bits.\n'
            '    TOTAL: Total number of bits.\nInput ports:\n'
            '    operand[TOTAL-1:0]: Input data.\n')
    assert [(p['name'], p.get('default')) for p in PX.extract_params(text)] == [
        ('FRACTION', None), ('TOTAL', None)]


@pytest.mark.parametrize('default_first', [False, True])
def test_parametric_contract_description_and_explicit_default_are_one_declaration(tmp_path, default_first):
    import json
    import phase1_doc_one_shot_runner as producer
    description = 'Input parameters:\n    SPAN: Number of data bits.\n'
    default = 'Parameter:\n    SPAN = 7\n'
    text = ('Module name:\n    neutral_core\n' +
            (default + description if default_first else description + default) +
            'Input ports:\n    payload[SPAN-1:0]: Input data.\n')
    assert [(p['name'], p.get('default')) for p in PX.extract_params(text)] == [('SPAN', '7')]
    assert [(p['name'], p['width']) for p in PX.extract_prose_ports(text)] == [('payload', 7)]
    result = producer.gen_l8_timing_waveform(tmp_path, {'current.md': text})
    doc = json.loads(result.path.read_text())
    assert [(p['name'], p.get('default')) for p in doc['parameters']] == [('SPAN', '7')]


def test_parametric_contract_public_bit_counts_reach_actual_consumer(tmp_path):
    import phase2_scaffold_gen as consumer
    docs = _parametric_contract_generate(
        tmp_path, _parametric_contract_fixture("arithmetic_width_prose"))
    for rows in _parametric_contract_aliases(docs):
        assert {r["name"]: r["width"] for r in rows} == {
            "clk": 1, "rst_n": 1, "mul_a": 4, "mul_b": 4, "mul_out": 8}
    assert [(r["name"], r.get("default")) for r in
            docs["L8_RTL_CONSTANTS"]["parameters"]] == [("size", "4")]
    signals = consumer.derive_signals({}, docs["L9_INTEGRATION_SPEC"])
    assert {r["name"]: r["width"] for r in signals if r["name"].startswith("mul_")} == {
        "mul_a": 4, "mul_b": 4, "mul_out": 8}
    rendered = consumer.emit_top_v("neutral_top", signals, [])
    assert "[3:0] mul_a" in rendered and "[3:0] mul_b" in rendered
    assert "[7:0] mul_out" in rendered


@pytest.mark.parametrize("fixture", ["declared_precision", "blank_separated_interface"])
def test_parametric_contract_no_default_declarations_survive(tmp_path, fixture):
    docs = _parametric_contract_generate(tmp_path, _parametric_contract_fixture(fixture))
    assert [(r["name"], r.get("default")) for r in
            docs["L8_RTL_CONSTANTS"]["parameters"]] == [("Q", None), ("N", None)]
    assert [(r["name"], r.get("default")) for r in
            docs["L9_INTEGRATION_SPEC"]["parameters"]] == [("Q", None), ("N", None)]
    for rows in _parametric_contract_aliases(docs):
        assert {r["name"] for r in rows} == {"a", "b", "c"}
        assert all(r.get("width_symbolic") in ("[N-1:0]", "N-1:0") for r in rows)
        assert all(r.get("width") in (None, 0) for r in rows)


@pytest.mark.parametrize('fixture', ['declared_precision', 'blank_separated_interface'])
def test_parametric_contract_declared_interface_emits_and_binds_in_native_tool(tmp_path, fixture):
    import shutil
    import subprocess
    import phase2_scaffold_gen as consumer
    import l1_pin_bus_width_actionable_check as gate
    docs = _parametric_contract_generate(
        tmp_path, _parametric_contract_fixture(fixture))
    assert [(p["name"], p.get("default")) for p in
            docs["L8_RTL_CONSTANTS"]["parameters"]] == [("Q", None), ("N", None)]
    report = gate.evaluate(tmp_path)
    assert report["verdict"] == "PASS", report
    assert report["qualification"] == "PARAMETRIC_INTERFACE"
    assert report["concrete_width_qualification"] == "NOT_MEASURED"
    signals = consumer.derive_signals({}, docs["L9_INTEGRATION_SPEC"])
    assert {r["name"]: r["width"] for r in signals if r["name"] in {"a", "b", "c"}} == {
        "a": None, "b": None, "c": None}
    with pytest.raises(consumer.UnresolvedPortWidth):
        consumer.emit_top_v("neutral_top", signals, [])
    top = docs["L9_INTEGRATION_SPEC"]["top_module"]
    rendered = consumer.emit_top_v(
        top, signals, docs['L1_DATASHEET']['ic_name'],
        parameters=docs["L9_INTEGRATION_SPEC"]["parameters"])
    assert "[N-1:0]" in rendered
    assert "parameter Q" in rendered and "parameter N" in rendered
    assert "parameter N =" not in rendered and "parameter Q =" not in rendered
    assert shutil.which("iverilog") and shutil.which("vvp"), "pinned native tools required"
    rtl = tmp_path / "declared_interface.sv"
    rtl.write_text(rendered)
    native_receipts = []
    for n, q in [(5, 2), (13, 7)]:
        probe = tmp_path / f"probe_{n}.sv"
        probe.write_text(
            f"module Probe; wire [{n-1}:0] a, b, c;\n"
            f"{top} #(.N({n}), .Q({q})) dut(.a(a), .b(b), .c(c));\n"
            "initial begin\n"
            f"if ($bits(dut.a)!={n} || $bits(dut.b)!={n} || $bits(dut.c)!={n}) $fatal;\n"
            '$display("BOUND_PARAMETER_INTERFACE_OK"); $finish; end\nendmodule\n')
        image = tmp_path / f"probe_{n}.vvp"
        compiled = subprocess.run(["iverilog", "-g2012", "-s", "Probe", "-o",
                                   str(image), str(rtl), str(probe)],
                                  capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stdout + compiled.stderr
        simulated = subprocess.run(["vvp", str(image)], capture_output=True, text=True)
        assert simulated.returncode == 0, simulated.stdout + simulated.stderr
        assert "BOUND_PARAMETER_INTERFACE_OK" in simulated.stdout
        native_receipts.extend([{'argv': compiled.args, 'rc': compiled.returncode,
                                 'stdout': compiled.stdout, 'stderr': compiled.stderr},
                                {'argv': simulated.args, 'rc': simulated.returncode,
                                 'stdout': simulated.stdout, 'stderr': simulated.stderr}])
    # Reverse the emitted interface itself. The same native probe must catch
    # a fabricated scalar even though Icarus merely warns at the connection.
    broken = tmp_path / 'scalarized_interface.sv'
    assert '[N-1:0] a' in rendered
    broken.write_text(rendered.replace('[N-1:0] a', '[0:0] a', 1))
    bad_image = tmp_path / 'scalarized.vvp'
    compiled = subprocess.run(['iverilog', '-g2012', '-s', 'Probe', '-o',
                              str(bad_image), str(broken), str(probe)],
                             capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    rejected = subprocess.run(['vvp', str(bad_image)], capture_output=True, text=True)
    assert rejected.returncode != 0, rejected.stdout + rejected.stderr
    native_receipts.extend([{'argv': compiled.args, 'rc': compiled.returncode,
                             'stdout': compiled.stdout, 'stderr': compiled.stderr},
                            {'argv': rejected.args, 'rc': rejected.returncode,
                             'stdout': rejected.stdout, 'stderr': rejected.stderr,
                             'expected_failure': 'the same bound probe rejects a scalarized input'}])
    import json
    (tmp_path / 'native-binding-receipts.json').write_text(json.dumps(native_receipts, indent=2))
    # Numeric-width emitters still cannot consume an unbound interface.
    with pytest.raises(consumer.UnresolvedPortWidth):
        consumer.emit_tb_v(top, signals)
    with pytest.raises(consumer.UnresolvedPortWidth):
        consumer.emit_scaffold(tmp_path)
    report = consumer.emit_scaffold(tmp_path, skip_tb=True, skip_cocotb=True,
                                    skip_soc=True, skip_regs=True)
    assert report["status"] == "ok"
    emitted = tmp_path / "phase2/stage1/scaffold" / (top + "_top.v")
    assert emitted.read_text() == rendered


def test_parametric_contract_conflicting_geometry_does_not_become_scalars(tmp_path):
    import phase2_scaffold_gen as consumer
    source = _parametric_contract_fixture("conflicting_memory_geometry")
    docs = _parametric_contract_generate(tmp_path, source, expected_rc=1)
    buses = {"write_addr", "read_addr", "write_data", "read_data"}
    for rows in _parametric_contract_aliases(docs):
        actual = {r["name"]: r for r in rows if r["name"] in buses}
        assert set(actual) == buses
        assert {n: r.get("width") for n, r in actual.items()} == dict.fromkeys(buses, 0)
        assert all(r.get("width_unresolved") for r in actual.values())
    assert docs["L9_INTEGRATION_SPEC"]["notes"] == source.strip()
    signals = consumer.derive_signals({}, docs["L9_INTEGRATION_SPEC"])
    assert {r["name"]: r["width"] for r in signals if r["name"] in buses} == dict.fromkeys(buses)
    with pytest.raises(consumer.UnresolvedPortWidth):
        consumer.emit_top_v("neutral_top", signals, [])


@pytest.mark.parametrize("expr,expected", [('"LANES"', 7), ('2*LANES', 14),
                                            ('(LANES + 2)', 9)])
def test_parametric_contract_bit_count_expression(expr, expected):
    text = ("Module name:\n    neutral_core\nInput ports:\n"
            f"    value: Input operand with a data width of {expr} bits.\n"
            "Parameter:\n    LANES = 7\n")
    assert [(r["name"], r["width"]) for r in PX.extract_prose_ports(text)] == [
        ("value", expected)]


def test_parametric_contract_unsupported_expression_is_preserved_and_refused():
    import phase2_scaffold_gen as consumer
    rows = PX.extract_prose_ports(
        "Input ports:\n    payload: Input data with a data width of mystery(W) bits.\n"
        "Parameter:\n    W = 5\n")
    assert [(r["name"], r["width"]) for r in rows] == [("payload", 0)]
    l9 = {"top_ports": [dict(r, direction=r["dir"]) for r in rows]}
    signals = consumer.derive_signals({}, l9)
    assert next(s for s in signals if s["name"] == "payload")["width"] is None
    with pytest.raises(consumer.UnresolvedPortWidth):
        consumer.emit_top_v("neutral_top", signals, [])


def test_parametric_contract_sibling_parameter_cannot_size_current_module():
    text = ("Module name:\n    selected_core\nInput ports:\n"
            "    payload[SPAN-1:0]: Input data.\n"
            "Module name:\n    sibling_core\nParameter:\n    SPAN = 23\n")
    assert [(r["name"], r["width"]) for r in PX.extract_prose_ports(text)] == [
        ("payload", 0)]


def test_parametric_contract_blank_line_only_preserves_port_definition_grammar():
    text = ("Output ports:\n\n    result[COUNT-1:0]: N-bit output.\n\n"
            "Namespace: Metadata for the output package.\n"
            "    internal[31:0]: Internal storage.\n")
    assert [(r["name"], r["dir"], r["width"]) for r in PX.extract_prose_ports(text)] == [
        ("result", "output", 0)]


def test_parametric_contract_blank_line_does_not_authorize_metadata_bullets():
    assert PX.extract_prose_ports(
        'Output ports:\n\n- Namespace: Metadata for the output package.\n'
        '    storage[31:0]: Internal storage.\n') == []


def test_parametric_contract_conflicting_owned_defaults_are_refused(tmp_path):
    import phase1_doc_one_shot_runner as producer
    text = ('Module name:\n    neutral_core\nParameter:\n'
            '    SPAN = 3\n    SPAN = 11\nInput ports:\n'
            '    payload[SPAN-1:0]: Input data.\n')
    assert [(r['name'], r['width']) for r in PX.extract_prose_ports(text)] == [('payload', 0)]
    with pytest.raises(ValueError, match='L8_PARAMETER_DEFAULT_CONFLICT'):
        producer.gen_l8_timing_waveform(tmp_path, {'current.md': text})


def test_parametric_contract_marker_refuses_even_if_a_numeric_alias_is_added():
    import phase2_scaffold_gen as consumer
    l9 = {"top_ports": [{"name": "entries", "direction": "output", "width": 1,
                         "width_unresolved": {"reason": "bus_width_not_stated",
                                              "source": "Data read from memory."}}]}
    signals = consumer.derive_signals({}, l9)
    assert next(s for s in signals if s["name"] == "entries")["width"] is None
    with pytest.raises(consumer.UnresolvedPortWidth):
        consumer.emit_top_v("neutral_top", signals, [])


@pytest.mark.parametrize('expression,owner', [('M-1:0', 'neutral_top'),
                                            ('N//2:0', 'neutral_top'),
                                            ('unknown(N):0', 'neutral_top'),
                                            ('N-1:0', 'sibling_top')])
def test_parametric_contract_module_emitter_rejects_undeclared_illegal_or_foreign(expression, owner):
    import phase2_scaffold_gen as consumer
    params = [{'name': 'N', 'default': None, 'module_owner': owner}]
    signals = consumer.derive_signals({}, {'top_ports': [
        {'name': 'bus_o', 'direction': 'output', 'width': 0,
         'width_symbolic': expression}]})
    assert next(s for s in signals if s['name'] == 'bus_o')['width'] is None
    with pytest.raises(consumer.UnresolvedPortWidth):
        consumer.emit_top_v('neutral_top', signals, 'neutral', parameters=params)


@pytest.mark.parametrize('declared', [True, False])
def test_parametric_contract_gate_does_not_borrow_a_sibling_hdl_default(tmp_path, declared):
    import json
    import l1_pin_bus_width_actionable_check as gate
    text = ('Module name:\n    selected_core\n' +
            ('Input parameters:\n    N: Data bus width.\n' if declared else '') +
            'Input ports:\n    payload[N-1:0]: Input data.\n')
    source = tmp_path / 'input/docs/current.md'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    foreign = tmp_path / 'input/rtl/sibling.sv'
    foreign.parent.mkdir(parents=True)
    foreign.write_text('module sibling #(parameter N = 23) (); endmodule\n')
    generated = tmp_path / 'phase1/generated_docs'
    generated.mkdir(parents=True)
    (generated / 'L1_DATASHEET.json').write_text(json.dumps({
        'ic_name': 'selected_core', 'pin_table': [
            {'name': 'payload', 'mode': 'in', 'width': 0, 'width_symbolic': '[N-1:0]'}]}))
    report = gate.evaluate(tmp_path)
    assert report['verdict'] == ('PASS' if declared else 'FAIL'), report
    if declared:
        assert report['qualification'] == 'PARAMETRIC_INTERFACE'
        assert report['concrete_width_qualification'] == 'NOT_MEASURED'
        assert report['symbolic_widths_resolved'] == []


@pytest.mark.parametrize('mutation', ['scalar', 'different_symbol'])
def test_parametric_contract_gate_rederives_source_instead_of_trusting_fields(tmp_path, mutation):
    import json
    import l1_pin_bus_width_actionable_check as gate
    source = tmp_path / 'input/docs/current.md'
    source.parent.mkdir(parents=True)
    source.write_text('Module name:\n    neutral_top\nInput parameters:\n'
                      '    N: Data width.\nInput ports:\n'
                      '    payload[N-1:0]: Input data.\n')
    generated = tmp_path / 'phase1/generated_docs'
    generated.mkdir(parents=True)
    row = {'name': 'payload', 'mode': 'in', 'width': 0, 'width_symbolic': '[N-1:0]'}
    if mutation == 'scalar': row['width'] = 1
    else: row['width_symbolic'] = '[M-1:0]'
    (generated / 'L1_DATASHEET.json').write_text(json.dumps({
        'ic_name': 'neutral_top', 'pin_table': [row]}))
    assert gate.evaluate(tmp_path)['verdict'] == 'FAIL'


def test_parametric_contract_existing_projection_cannot_turn_unknown_zero_into_scalar():
    import phase2_scaffold_gen as consumer
    rows = PX.extract_ports('Input ports:\n    payload[UNDECLARED-1:0]: Input data.\n')
    assert rows == [{'name': 'payload', 'dir': 'input', 'width': 0}]
    signals = consumer.derive_signals({}, {'top_ports': [
        dict(row, direction=row['dir']) for row in rows]})
    assert [(s['name'], s['width']) for s in signals if s['name'] == 'payload'] == [('payload', None)]
    with pytest.raises(consumer.UnresolvedPortWidth):
        consumer.emit_top_v('neutral_top', signals, 'neutral')


_PARAMETRIC_LITERAL_CASES = [
    ('range_hex', 'N+0x10-1:0', None, True),
    ('range_binary', 'N+0b10000-1:0', None, True),
    ('range_octal', 'N+0o20-1:0', None, True),
    ('default_hex', 'N-1:0', '0x10', True),
    ('decimal', 'N+16-1:0', '16', False),
]


@pytest.mark.parametrize('case,expression,default,unsupported', _PARAMETRIC_LITERAL_CASES)
def test_parametric_literal_admitted_module_compiles_natively(tmp_path, case, expression, default, unsupported):
    import json
    import subprocess
    import phase2_scaffold_gen as consumer
    params = [{'name': 'N', 'default': None, 'module_owner': 'neutral_top'}]
    if default is not None:
        params.append({'name': 'K', 'default': default, 'module_owner': 'neutral_top'})
    signals = consumer.derive_signals({}, {'top_ports': [
        {'name': 'payload', 'direction': 'input', 'width': 0,
         'width_symbolic': '[' + expression + ']'}]})
    receipts = []
    try:
        text = consumer.emit_top_v('neutral_top', signals, 'neutral', parameters=params)
    except consumer.UnresolvedPortWidth as exc:
        assert unsupported, str(exc)
        (tmp_path / 'native-literal-receipt.json').write_text(json.dumps({
            'case': case, 'status': 'REFUSED_BEFORE_EMIT', 'reason': str(exc)}))
        return
    source = tmp_path / 'emitted.sv'
    source.write_text(text)
    for n in (5, 13):
        width = n if case == 'default_hex' else n + 16
        probe = tmp_path / f'probe_{n}.sv'
        probe.write_text(
            f'module Probe; wire [{width-1}:0] payload;\n'
            f'neutral_top #(.N({n})) dut(.payload(payload));\n'
            f'initial begin if ($bits(dut.payload)!={width}) $fatal; '
            '$display("LITERAL_INTERFACE_BOUND_OK"); $finish; end\nendmodule\n')
        image = tmp_path / f'probe_{n}.vvp'
        run = subprocess.run(['iverilog', '-g2012', '-s', 'Probe', '-o',
                              str(image), str(source), str(probe)],
                             capture_output=True, text=True)
        receipts.append({'argv': run.args, 'rc': run.returncode,
                         'stdout': run.stdout, 'stderr': run.stderr})
        (tmp_path / 'native-literal-receipt.json').write_text(json.dumps({
            'case': case, 'status': 'EMITTED', 'receipts': receipts}, indent=2))
        assert run.returncode == 0, run.stdout + run.stderr
        sim = subprocess.run(['vvp', str(image)], capture_output=True, text=True)
        receipts.append({'argv': sim.args, 'rc': sim.returncode,
                         'stdout': sim.stdout, 'stderr': sim.stderr})
        (tmp_path / 'native-literal-receipt.json').write_text(json.dumps({
            'case': case, 'status': 'EMITTED', 'receipts': receipts}, indent=2))
        assert sim.returncode == 0, sim.stdout + sim.stderr
        assert 'LITERAL_INTERFACE_BOUND_OK' in sim.stdout


@pytest.mark.parametrize('case,expression,default,unsupported', _PARAMETRIC_LITERAL_CASES)
def test_parametric_literal_gate_rejects_unemittable_source(tmp_path, case, expression, default, unsupported):
    import json
    import l1_pin_bus_width_actionable_check as gate
    source = tmp_path / 'input/docs/current.md'
    source.parent.mkdir(parents=True)
    source.write_text('Module name:\n    neutral_top\nInput parameters:\n'
                      '    N: Payload width.\n' +
                      (f'Parameter:\n    K = {default}\n' if default is not None else '') +
                      'Input ports:\n    payload[' + expression + ']: Input data.\n')
    generated = tmp_path / 'phase1/generated_docs'
    generated.mkdir(parents=True)
    (generated / 'L1_DATASHEET.json').write_text(json.dumps({
        'ic_name': 'neutral_top', 'pin_table': [{'name': 'payload', 'mode': 'in',
            'width': 0, 'width_symbolic': '[' + expression + ']'}]}))
    report = gate.evaluate(tmp_path)
    assert report['verdict'] == ('FAIL' if unsupported else 'PASS'), report
    if unsupported:
        assert report['qualification'] != 'PARAMETRIC_INTERFACE'
    else:
        assert report['qualification'] == 'PARAMETRIC_INTERFACE'
        assert report['concrete_width_qualification'] == 'NOT_MEASURED'
