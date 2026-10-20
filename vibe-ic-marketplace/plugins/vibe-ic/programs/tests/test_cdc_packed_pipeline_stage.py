"""Native two-sample CDC recognition must not depend on word packing."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import pytest

PROG = Path(os.environ.get("CDC_STAGE_PROBE_PROGRAMS", str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROG))
import _cdc_netlist as cdc
pytestmark = pytest.mark.skipif(not shutil.which("yosys"), reason="native Yosys required")
CASES = [('separate2', 'module neutral_cdc(input logic clk_a,clk_b,rst_n,en_i,data_i,output logic[1:0]out_o); logic launch; always_ff @(posedge clk_a)launch<=data_i; logic first,second; always_ff @(posedge clk_b) first<=launch; always_ff @(posedge clk_b) second<=first; assign out_o={second,first}; endmodule\n', 0), ('packed2', 'module neutral_cdc(input logic clk_a,clk_b,rst_n,en_i,data_i,output logic[1:0]out_o); logic launch; always_ff @(posedge clk_a)launch<=data_i; logic [1:0] chain; always_ff @(posedge clk_b) chain <= {chain[0], launch}; assign out_o=chain; endmodule\n', 0), ('packed-parallel1', 'module neutral_cdc(input logic clk_a,clk_b,rst_n,en_i,data_i,output logic[1:0]out_o); logic launch; always_ff @(posedge clk_a)launch<=data_i; logic [1:0] chain; always_ff @(posedge clk_b) chain <= {chain[1], launch}; assign out_o=chain; endmodule\n', 1)]

@pytest.mark.parametrize("label,source,expected", CASES, ids=[x[0] for x in CASES])
def test_native_two_sample_pipeline(tmp_path, label, source, expected):
    rtl = tmp_path / "phase2/stage1/rtl/neutral.sv"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(source)
    native = cdc.build(tmp_path, [rtl], "neutral_cdc")
    cdc.require_binding(tmp_path, native, cdc.load(native))
    report = tmp_path / "ordinary.json"
    command = [sys.executable, str(PROG / "clock_domain_reg_crossing_check.py"),
               str(tmp_path), "--front-end", "netlist", "--json", str(report)]
    result = subprocess.run(command, capture_output=True, text=True)
    document = json.loads(report.read_text())
    assert document["summary"]["netlist_read"] is True
    actual_rc = result.returncode
    assert actual_rc == expected, document["findings"]


def _stage_results(model, word, index):
    # The public reader delegates to a fresh per-analysis snapshot. Exercise
    # that implementation directly so the packed-lane rule cannot be lost by
    # changing only the wrapper.
    domain = model.domain(word)
    return (cdc._sync_stage2(model, word, index, domain),
            cdc._LookupSnapshot(model).sync_stage2(word, index, domain))


# The stage predicate is shared by register and async-input consumers. These
# native reader controls isolate bit lanes without changing cone/mux semantics.
LANES = [
    ("forward2", 2, "chain <= {chain[0], launch};", "", "", 0, True),
    ("reverse2", 2, "chain <= {launch, chain[1]};", "", "", 1, True),
    ("forward3", 3, "chain <= {chain[1:0], launch};", "", "", 0, True),
    ("reverse3", 3, "chain <= {launch, chain[2:1]};", "", "", 2, True),
    ("async-reset", 2, "if (!rst_n) chain <= 0; else chain <= {chain[0], launch};", " or negedge rst_n", "", 0, True),
    ("initial-value", 2, "chain <= {chain[0], launch};", "", "initial chain = 0;", 0, True),
    ("sync-reset", 2, "if (!rst_n) chain <= 0; else chain <= {chain[0], launch};", "", "", 0, True),
    ("hold-enable", 2, "if (en_i) chain <= {chain[0], launch};", "", "", 0, True),
    ("reset-and-hold", 2, "if (!rst_n) chain <= 0; else if (en_i) chain <= {chain[0], launch};", " or negedge rst_n", "", 0, True),
    ("self-hold-is-not-stage2", 2, "chain <= {chain[1], launch};", "", "", 0, False),
    ("parallel-samples-is-not-stage2", 2, "chain <= {launch, launch};", "", "", 0, False),
    ("constant-is-not-stage2", 2, "chain <= {1'b0, launch};", "", "", 0, False),
]


def lane_model(tmp_path, width, statement, edge="", initial=""):
    rtl = tmp_path / "phase2/stage1/rtl/neutral.sv"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(f"""module neutral_cdc(input logic clk_a, clk_b, rst_n, en_i, data_i,
        output logic [{width-1}:0] out_o);
      logic launch; always_ff @(posedge clk_a) launch <= data_i;
      logic [{width-1}:0] chain; {initial}
      always_ff @(posedge clk_b{edge}) {statement}
      assign out_o = chain;
    endmodule
    """)
    native = cdc.build(tmp_path, [rtl], "neutral_cdc")
    model = cdc.load(native)
    cdc.require_binding(tmp_path, native, model)
    word, = [f for f in model.flops if model.domain(f) == "clk_b"]
    assert len(word.d) == len(word.q) == width
    return model, word


@pytest.mark.parametrize("label,width,statement,edge,initial,index,expected", LANES, ids=[x[0] for x in LANES])
def test_native_bit_lane_witness(tmp_path, label, width, statement, edge, initial, index, expected):
    model, word = lane_model(tmp_path, width, statement, edge, initial)
    # Assert the actual D-lane source independently of the stage recognizer.
    successors = [i for i in range(width) if i != index and word.q[i] != word.q[index]
                  and model.direct_source(word, i) == word.q[index]]
    assert bool(successors) is expected
    for actual in _stage_results(model, word, index):
        assert actual is expected
    # Sync-reset/enable cell-wide cone precision is outside this repair. The
    # stage witness alone does not assert full register/async/reset signoff.


def test_reanalysis_sees_removed_stage_lane(tmp_path):
    model, word = lane_model(tmp_path, 2, "chain <= {chain[0], launch};")
    original = list(word.d)
    assert cdc.judge(model, "reg_crossing") == []
    word.d[1] = word.q[1]
    model.cells[word.name]["connections"]["D"][1] = word.q[1]
    findings = cdc.judge(model, "reg_crossing")
    assert [f["rule"] for f in findings] == ["CDC_REG_NO_SYNC"]
    word.d[:] = original
    model.cells[word.name]["connections"]["D"][:] = original
    assert cdc.judge(model, "reg_crossing") == []


def test_duplicate_q_alias_does_not_create_distinct_sample(tmp_path):
    model, word = lane_model(tmp_path, 2, "chain <= {chain[0], launch};")
    # Deliberately malformed in-memory reader data is a refusal control,
    # never a source-bound native qualification result.
    word.q[1] = word.q[0]
    for actual in _stage_results(model, word, 0):
        assert actual is False


@pytest.mark.parametrize("second,expected", [("chain[0]", 0), ("chain[1]", 1)], ids=["two-samples", "self-hold"])
def test_native_async_input_uses_distinct_packed_lane(tmp_path, second, expected):
    rtl = tmp_path / "phase2/stage1/rtl/neutral.sv"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(f"""module neutral_async(input logic clk_b, signal_raw,
        output logic [1:0] out_o);
      logic [1:0] chain;
      always_ff @(posedge clk_b) chain <= {{{second}, signal_raw}};
      assign out_o = chain;
    endmodule
    """)
    native = cdc.build(tmp_path, [rtl], "neutral_async")
    cdc.require_binding(tmp_path, native, cdc.load(native))
    report = tmp_path / "async.json"
    result = subprocess.run([sys.executable, str(PROG / "cdc_async_input_check.py"),
        str(tmp_path), "--front-end", "netlist", "--json", str(report)],
        capture_output=True, text=True)
    document = json.loads(report.read_text())
    assert document["summary"]["netlist_read"] is True
    assert result.returncode == expected, document["findings"]
    assert [f["rule"] for f in document["findings"]] == ([] if expected == 0 else ["ASYNC_INPUT_NO_SYNC"])
