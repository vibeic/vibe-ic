"""Native CDC input frontend: packaged SV, generate, selected top and legacy Verilog."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

import pytest

PROG = Path(__file__).resolve().parents[1]
FIXTURE = PROG / "tests/fixtures/cdc_netlist"
sys.path.insert(0, str(PROG))
import _cdc_netlist as cdc

pytestmark = pytest.mark.skipif(not shutil.which("yosys"), reason="native Yosys/slang required")


def project(root, unsafe=False):
    rtl = root / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    for source in (FIXTURE / "sv_source_import").glob("*.sv"):
        shutil.copyfile(source, rtl / source.name)
    if unsafe:
        bridge = rtl / "a_bridge.sv"
        bridge.write_text("`define SHORT_PIPE\n" + bridge.read_text())
    l9 = root / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({"top_module": "neutral_bridge"}))
    return sorted(rtl.glob("*.sv"))


@pytest.mark.parametrize("unsafe,flops,rc,rules", [
    (False, 3, 0, []), (True, 2, 1, ["CDC_REG_NO_SYNC"]),
])
def test_packaged_generated_native_netlist_and_real_crossing(tmp_path, unsafe, flops, rc, rules):
    files = project(tmp_path, unsafe)
    before = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    try:
        native = cdc.build(tmp_path, files, "neutral_bridge")
        observed = {"status": "PASS", "reason": ""}
    except cdc.Refusal as error:
        observed = {"status": "FAIL", "reason": str(error)}
    assert observed["status"] == "PASS", observed
    netlist = cdc.load(native)
    assert netlist.top == "neutral_bridge"
    assert len(netlist.flops) == flops
    assert cdc.clock_domains(netlist) == ["clk_aux_i", "clk_fast_i"]
    assert before == {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def test_missing_package_provider_leaves_no_prior_admission(tmp_path):
    files = project(tmp_path)
    (files[0].parent / "z_types.sv").unlink()
    with pytest.raises(cdc.Refusal, match="CDC_NETLIST_BUILD_FAILED"):
        cdc.build(tmp_path, [f for f in files if f.exists()], "neutral_bridge")
    assert not (tmp_path / cdc.NETLIST_REL).exists()


def test_existing_plain_verilog_fixture_keeps_real_native_reader(tmp_path):
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    source = rtl / "multi_clock_sync.v"
    shutil.copyfile(FIXTURE / "multi_clock_sync.v", source)
    native = cdc.build(tmp_path, [source], "multi_clock_sync")
    netlist = cdc.load(native)
    assert cdc.clock_domains(netlist) == ["clk_a", "clk_b"]
    assert "read_verilog -sv -defer" in (tmp_path / cdc.NETLIST_LOG_REL).read_text()
    assert "read_slang" not in (tmp_path / cdc.NETLIST_LOG_REL).read_text()


def test_bad_syntax_cannot_leave_prior_native_admission(tmp_path):
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    source = rtl / "sample.sv"
    source.write_text("module sample(input clk, input d, output reg q); always @(posedge clk) q <= d; endmodule\n")
    native = cdc.build(tmp_path, [source], "sample")
    source.write_text("module sample(input clk, input d, output reg q); always @(posedge clk) q <= ; endmodule\n")
    with pytest.raises(cdc.Refusal, match="CDC_NETLIST_BUILD_FAILED"):
        cdc.build(tmp_path, [source], "sample")
    assert not (tmp_path / cdc.NETLIST_REL).exists()


def _reset_control_source(case):
    """Public #3335 inputs; extensions share exactly the same source bytes."""
    if case in {"ring4", "dag4", "external4", "selfloop", "low4"}:
        size = 1 if case == "selfloop" else 4
        lines = [f"module neutral_reset_top(input wire clk, ext_rst, input wire [{size-1}:0] data_i, output reg [{size-1}:0] q);"]
        for i in range(size):
            dependency = (case not in {"dag4", "external4"} or
                          (case == "dag4" and i != size-1))
            expr = f"ext_rst | q[{(i+1)%size}]" if dependency else "ext_rst"
            if case == "low4":
                expr = f"ext_rst & ~q[{(i+1)%size}]"
            lines.append(f"wire rst_{i} = {expr};")
            edge, condition = ("negedge", "!") if case == "low4" else ("posedge", "")
            lines.append(f"always @(posedge clk or {edge} rst_{i}) if ({condition}rst_{i}) q[{i}] <= 1'b0; else q[{i}] <= data_i[{i}];")
        text = "\n".join(lines + ["endmodule"]) + "\n"
        if case == "external4":
            text = text.replace("ext_rst", "guard_raw")
            text = text.replace("<= data_i[", "<= guard_raw ^ data_i[")
        return text
    if case == "vector_constant":
        return ("module neutral_reset_top(input wire clk, ext_rst, input wire [2:0] data_i, output reg [2:0] q);\n"
                "always @(posedge clk or negedge ext_rst) if (!ext_rst) q <= 3'b110; else q <= data_i;\nendmodule\n")
    if case == "dynamic_ad":
        return ("module neutral_reset_top(input wire clk, ext_rst, async_i, data_i, output reg q);\n"
                "always @(posedge clk or posedge ext_rst) if (ext_rst) q <= async_i; else q <= data_i;\nendmodule\n")
    if case == "set_clr":
        return ("module neutral_reset_top(input wire clk, set_i, clr_i, data_i, output reg q);\n"
                "always @(posedge clk or posedge set_i or posedge clr_i) if (clr_i) q <= 1'b0; else if (set_i) q <= 1'b1; else q <= data_i;\nendmodule\n")
    raise ValueError(case)


def _reset_control_native(root, case, extension):
    source = root / "phase2/stage1/rtl" / ("neutral_reset_top." + extension)
    source.parent.mkdir(parents=True)
    source.write_text(_reset_control_source(case))
    l9 = root / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({"top_module": "neutral_reset_top"}))
    refusal = None
    try:
        native = cdc.build(root, [source], "neutral_reset_top")
    except cdc.Refusal as error:
        refusal = error.code
        native = (root / cdc.NETLIST_REL).with_suffix(".json.tmp")
    raw = json.loads(native.read_text())["modules"]["neutral_reset_top"]
    (root / "raw_control_cells.json").write_text(json.dumps(raw["cells"], indent=2))
    return source, native, raw, refusal


def _reset_control_consumers(root, native, unsupported=False, label=""):
    results = {}
    for program in ("cdc_async_input_check",):
        report = root / (program + label + ".json")
        argv = [sys.executable, "-B", str(PROG / (program + ".py")), str(root),
                "--front-end", "netlist", "--json", str(report)]
        if unsupported:
            argv += ["--netlist", str(native)]
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        doc = json.loads(report.read_text())
        rules = sorted({row["rule"] for row in doc["findings"] if row["severity"] == "ERROR"})
        receipt = {"argv": argv, "pid": process.pid, "rc": process.returncode,
                   "stdout": stdout, "stderr": stderr, "report": doc}
        (root / (program + label + ".receipt.json")).write_text(json.dumps(receipt, indent=2))
        results[program] = (process.returncode, rules)
    return results


@pytest.mark.parametrize("extension", ["v", "sv"])
@pytest.mark.parametrize("case", ["ring4", "dag4", "external4", "selfloop", "low4", "vector_constant"])
def test_native_async_reset_controls_reach_all_ordinary_consumers(tmp_path, case, extension):
    source, native, raw, refusal = _reset_control_native(tmp_path, case, extension)
    observed = _reset_control_consumers(tmp_path, native)
    expected = {"cdc_async_input_check": (0, [])}
    assert observed == expected, observed
    assert refusal is None
    model = cdc.load(native, "neutral_reset_top")
    assert len(model.flops) == (1 if case in {"selfloop", "vector_constant"} else 4)
    assert all(flop.arst is not None for flop in model.flops)
    for flop in model.flops:
        cell = raw["cells"][flop.name]
        pin = "ALOAD" if extension == "sv" else "ARST"
        assert flop.arst == cell["connections"][pin][0]
        assert flop.arst_pin == pin
        assert flop.arst_pol == (0 if case in {"low4", "vector_constant"} else 1)
        assert flop.arst_value == (["0", "1", "1"] if case == "vector_constant" else ["0"])
        assert flop.arst_source == cell["attributes"]["src"]
        assert flop.srst is None


@pytest.mark.parametrize("case,extension", [("dynamic_ad", "v"), ("dynamic_ad", "sv"), ("set_clr", "v")],
                         ids=["dynamic_ad-v", "dynamic_ad-sv", "set_clr-v"])
def test_native_unsupported_async_controls_refuse_in_all_ordinary_consumers(tmp_path, case, extension):
    _source, native, raw, refusal = _reset_control_native(tmp_path, case, extension)
    expected_code = "CDC_NETLIST_UNSUPPORTED_ASYNC_CONTROL"
    observed = _reset_control_consumers(tmp_path, native, unsupported=True)
    assert observed == {name: (1, [expected_code]) for name in observed}, observed
    assert refusal == expected_code
    with pytest.raises(cdc.Refusal, match=expected_code):
        cdc.load(native, "neutral_reset_top")
    assert any(cell["type"] in {"$aldff", "$aldffe", "$dffsr", "$dffsre"}
               for cell in raw["cells"].values())


@pytest.mark.parametrize("case,constant,expression,value", [
    ("literal0", "1'b1", "1'b0", "0"),
    ("literal1", "1'b1", "1'b1", "1"),
    ("not_constant1", "1'b1", "!bit_true", "0"),
    ("not_constant0", "1'b0", "!bit_true", "1"),
    ("dynamic", "1'b1", "reset_data", None),
    ("unknown", "1'b1", "1'bx", None),
    ("dynamic_not", "1'b1", "!reset_data", None),
    ("mixed_dynamic", "1'b1", "{reset_data, !bit_true}", None),
    ("unknown_not", "1'bx", "!bit_true", None),
    ("unsupported_logic", "1'b1", "bit_true ^ 1'b1", "0"),
    ("constant_cycle", "!bit_true", "bit_true", None),
], ids=lambda value: str(value))
def test_native_aload_reset_expression(tmp_path, case, constant, expression, value):
    """#3344 public input, canonical native producer and ordinary CDC/RDC."""
    source = tmp_path / "phase2/stage1/rtl/neutral.sv"
    source.parent.mkdir(parents=True)
    width = "[1:0] " if case == "mixed_dynamic" else ""
    source.write_text(
        (f"module neutral(input clk,rst_n,input {width}d,input reset_data,output reg {width}q);\n"
         if width else "module neutral(input clk,rst_n,d,reset_data,output reg q);\n") +
        f"wire bit_true={constant};\n"
        "always @(posedge clk or negedge rst_n)\n"
        f"  if(!rst_n) q<={expression}; else q<=d;\n"
        "endmodule\n")
    before = source.read_bytes()
    (tmp_path / "neutral.input.txt").write_bytes(before)
    l9 = tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({"top_module": "neutral"}))
    refusal = None
    try:
        native = cdc.build(tmp_path, [source], "neutral")
    except cdc.Refusal as error:
        refusal = error.code
        native = (tmp_path / cdc.NETLIST_REL).with_suffix(".json.tmp")
    raw_bytes = native.read_bytes()
    raw = json.loads(raw_bytes)["modules"]["neutral"]
    observed = _reset_control_consumers(tmp_path, native, unsupported=refusal is not None)
    expected_code = "CDC_NETLIST_UNSUPPORTED_ASYNC_CONTROL"
    expected = (1, [expected_code]) if value is None else (0, [])
    assert observed == {name: expected for name in observed}, observed
    assert source.read_bytes() == before
    if value is None:
        assert refusal == expected_code
        with pytest.raises(cdc.Refusal, match=expected_code):
            cdc.load(native)
    else:
        assert refusal is None
        model = cdc.load(native)
        assert len(model.flops) == 1
        flop = model.flops[0]
        assert (flop.arst_pin, flop.arst_pol, flop.arst_value) == ("ALOAD", 0, [value])
        assert flop.arst == raw["ports"]["rst_n"]["bits"][0]
        assert flop.d == raw["ports"]["d"]["bits"]
        assert flop.q == raw["ports"]["q"]["bits"]
        assert flop.srst is None
        raw_native = tmp_path / cdc.NETLIST_RAW_REL
        if case == "unsupported_logic":
            # Native normalization supports this constant XOR; the narrow raw
            # loader must still refuse it rather than grow a constant evaluator.
            with pytest.raises(cdc.Refusal, match=expected_code):
                cdc.load(raw_native)
        if case.startswith("not_constant"):
            raw_model = cdc.load(raw_native)
            assert raw_model.flops[0].arst_value == [value]
            raw_graph = json.loads(raw_native.read_text())["modules"]["neutral"]
            ad = raw_graph["cells"][flop.name]["connections"]["AD"][0]
            assert isinstance(ad, int), "exercise the retained native expression"
            driver = raw_graph["cells"][raw_model.drivers[ad][0]]
            assert driver["type"] == "$logic_not"
            assert driver["connections"]["A"] == ["1" if value == "0" else "0"]
        assert native.read_bytes() == raw_bytes


@pytest.mark.parametrize("case", ["ring4", "low4"])
def test_native_constant_expression_keeps_reset_cycle(tmp_path, case):
    source = tmp_path / "phase2/stage1/rtl/neutral_reset_top.sv"
    source.parent.mkdir(parents=True)
    source.write_text(_reset_control_source(case).replace(
        ";\n", ";\nwire bit_true = 1'b1;\n", 1).replace("<= 1'b0", "<= !bit_true"))
    l9 = tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({"top_module": "neutral_reset_top"}))
    refusal = None
    try:
        native = cdc.build(tmp_path, [source], "neutral_reset_top")
    except cdc.Refusal as error:
        refusal = error.code
        native = (tmp_path / cdc.NETLIST_REL).with_suffix(".json.tmp")
    observed = _reset_control_consumers(tmp_path, native, unsupported=refusal is not None)
    assert observed == {"cdc_async_input_check": (0, [])}, observed
    assert refusal is None
    model = cdc.load(native)
    assert len(model.flops) == 4
    assert all((f.arst_pin, f.arst_pol, f.arst_value) ==
               ("ALOAD", 0 if case == "low4" else 1, ["0"]) for f in model.flops)
    findings = cdc.reset_dependency_findings(model)
    assert any(f["rule"] == "CIRCULAR_RESET_DEPENDENCY" for f in findings)
def _constant_ad_project(root, declaration, expression, width=1):
    source = root / 'phase2/stage1/rtl/neutral_reset_top.sv'
    source.parent.mkdir(parents=True)
    vector = f'[{width-1}:0] ' if width != 1 else ''
    source.write_text(
        f'module neutral_reset_top(input clk,rst_n,reset_data,input {vector}data_i,'
        f'output reg {vector}q);{declaration}'
        'always @(posedge clk or negedge rst_n) '
        f'if(!rst_n)q<={expression};else q<=data_i;endmodule\n')
    l9 = root / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({'top_module': 'neutral_reset_top'}))
    return source


@pytest.mark.parametrize('declaration,expression,width,value', [
    ("wire fixed_bit=1'b1;", '!fixed_bit', 1, ['0']),
    ("wire fixed_bit=1'b0;", '!fixed_bit', 1, ['1']),
    ("wire [2:0] fixed_word=3'b110;", '~fixed_word', 3, ['1', '0', '0']),
    ("wire [2:0] fixed_word=3'b101;", "!((fixed_word ^ 3'b101) | 3'b000)", 1, ['1']),
], ids=['not-one', 'not-zero', 'vector', 'nested'])
def test_3344_native_constant_ad_expression_reaches_ordinary_consumers(
        tmp_path, declaration, expression, width, value):
    source = _constant_ad_project(tmp_path, declaration, expression, width)
    original = source.read_bytes()
    try:
        native = cdc.build(tmp_path, [source], 'neutral_reset_top')
        observed = {'status': 'ACCEPTED'}
    except cdc.Refusal as error:
        observed = {'status': 'REFUSED', 'reason': str(error)}
    assert observed == {'status': 'ACCEPTED'}, observed
    model = cdc.load(native)
    assert len(model.flops) == 1
    flop = model.flops[0]
    assert (flop.type, flop.arst_pin, flop.arst_pol, flop.arst_value) == (
        '$aldff', 'ALOAD', 0, value)
    raw = json.loads((tmp_path / cdc.NETLIST_RAW_REL).read_text())['modules'][model.top]
    normalized = json.loads(native.read_text())['modules'][model.top]
    raw_flop = raw['cells'][flop.name]
    final_flop = normalized['cells'][flop.name]
    assert raw_flop['type'] == final_flop['type']
    assert raw_flop['parameters'] == final_flop['parameters']
    assert {p: v for p, v in raw_flop['connections'].items() if p != 'AD'} == {
        p: v for p, v in final_flop['connections'].items() if p != 'AD'}
    observed = _reset_control_consumers(tmp_path, native)
    assert observed == {name: (0, []) for name in observed}, observed
    assert source.read_bytes() == original


@pytest.mark.parametrize('declaration,expression', [
    ('', 'reset_data'), ('', "1'bx"), ("wire fixed_bit=1'bx;", '!fixed_bit'),
], ids=['dynamic', 'unknown', 'not-unknown'])
def test_3344_nonconstant_ad_still_refuses(tmp_path, declaration, expression):
    source = _constant_ad_project(tmp_path, declaration, expression)
    with pytest.raises(cdc.Refusal, match='CDC_NETLIST_UNSUPPORTED_ASYNC_CONTROL'):
        cdc.build(tmp_path, [source], 'neutral_reset_top')
    assert not (tmp_path / cdc.NETLIST_REL).exists()
    output = (tmp_path / cdc.NETLIST_REL).with_suffix('.json.tmp')
    observed = _reset_control_consumers(tmp_path, output, unsupported=True)
    assert observed == {name: (1, ['CDC_NETLIST_UNSUPPORTED_ASYNC_CONTROL'])
                        for name in observed}, observed


def test_3344_failed_normalization_cannot_reuse_admission(tmp_path, monkeypatch):
    source = _constant_ad_project(tmp_path, "wire fixed_bit=1'b1;", '!fixed_bit')
    cdc.build(tmp_path, [source], 'neutral_reset_top')
    original_run = cdc.subprocess.run
    calls = []

    def native_then_refuse(argv, **kwargs):
        if "-p" in argv and argv[argv.index("-p") + 1].startswith("read_json "):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 17, '', 'neutral normalization failure')
        return original_run(argv, **kwargs)

    monkeypatch.setattr(cdc.subprocess, 'run', native_then_refuse)
    with pytest.raises(cdc.Refusal, match='CDC_NETLIST_BUILD_FAILED'):
        cdc.build(tmp_path, [source], 'neutral_reset_top')
    assert len(calls) == 1
    assert not (tmp_path / cdc.NETLIST_REL).exists()
    assert 'neutral normalization failure' in (tmp_path / cdc.NETLIST_NORMALIZE_LOG_REL).read_text()


def test_published46_checkpoint_keeps_its_original_native_binding(tmp_path):
    """Read the actual retained old producer output; do not rerun its producer."""
    root = tmp_path / 'checkpoint'
    shutil.copytree(FIXTURE / 'published46_checkpoint', root)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    native = root / cdc.NETLIST_REL
    model = cdc.load(native)
    assert model.flops[0].arst_value == ['0']
    observed = _reset_control_consumers(root, native)
    assert observed == {name: (0, []) for name in observed}, observed
    assert {p: (root / p).read_bytes() for p in before} == before
