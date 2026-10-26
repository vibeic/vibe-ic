"""#3368 — source-bound non-encoding/value interface semantics.

These are actual producer and receipt-consumer tests.  Native execution is
cadence-controlled because the source-repair host is not an EDA qualification
runner; the landing owner runs them in the pinned current image.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parents[1]
SCRIPT = PROGRAMS / "interface_encoding_audit.py"
sys.path.insert(0, str(PROGRAMS))
import interface_encoding_audit as audit


def _run(tmp_path, source):
    rtl = tmp_path / "rtl"
    out = tmp_path / "out"
    rtl.mkdir(parents=True)
    out.mkdir()
    (rtl / "neutral.sv").write_text(source)
    result = subprocess.run([
        sys.executable, str(SCRIPT), "--rtl-dir", str(rtl),
        "--top-module", "neutral", "--out-dir", str(out),
        "-D", "ISSUE3368_NATIVE",
    ], capture_output=True, text=True)
    report = json.loads((out / "encoding_audit_report.json").read_text())
    return result, report


def _run_retained(tmp_path):
    rtl = Path(os.environ["ISSUE3368_RETAINED_RTL"])
    expected = Path(os.environ["ISSUE3368_RETAINED_REPORT"])
    out = Path(os.environ.get(
        "ISSUE3368_RETAINED_OUT", str(tmp_path / "retained-out")))
    out.mkdir()
    result = subprocess.run([
        sys.executable, str(SCRIPT), "--rtl-dir", str(rtl),
        "--top-module", "subservient", "--out-dir", str(out),
    ], capture_output=True, text=True)
    return (result,
            json.loads((out / "encoding_audit_report.json").read_text()),
            json.loads(expected.read_text()))


def _consume(tmp_path):
    shared = PROGRAMS.parent / "_shared"
    sys.path.insert(0, str(shared))
    import skill_compliance_check as checker

    finding, = checker._cc_audit_receipt_evidence(
        {"id": "X_interface_encoding_audit",
         "auditor": "interface_encoding_audit"}, "",
        checker.CheckContext(output_path=tmp_path / "review.md",
                             evidence_dirs=[tmp_path / "out"],
                             rtl_source_root=tmp_path / "rtl"))
    return finding


_NATIVE = pytest.mark.skipif(
    os.environ.get("VIBEIC_REQUIRE_EDA_VERIFICATION") != "1",
    reason="root-owned current-image native acceptance")


def _semantic_role(source, widths):
    audit._DISCOVERY_ISSUES.clear()
    audit._CONFIGURATION.clear()
    audit._CONFIGURATION["native"] = {"status": "MEASURED"}
    modules = {}
    for module in audit.parse_modules(audit.strip_comments(source), "neutral.sv"):
        module.native_widths = widths[module.name]
        modules[module.name] = module
    instances = audit.parse_instances(modules["neutral"].body, "neutral",
                                      native_checked=True)
    return audit._whole_nonencoding_value(
        "link", modules["source"], "payload", modules["sink"], "payload",
        modules["neutral"], modules, instances)


def _predicate_role(source, widths, port="payload"):
    audit._DISCOVERY_ISSUES.clear()
    audit._CONFIGURATION.clear()
    audit._CONFIGURATION["native"] = {"status": "MEASURED"}
    modules = {}
    for module in audit.parse_modules(audit.strip_comments(source), "neutral.sv"):
        module.native_widths = widths[module.name]
        modules[module.name] = module
    instances = audit.parse_instances(modules["neutral"].body, "neutral",
                                      native_checked=True)
    return audit._whole_scalar_predicate(
        "link", modules["source"], port, modules["sink"], port,
        modules["neutral"], modules, instances)


def _bitfield_fixture(change=""):
    source = r"""
module source(input [4:0] data, output [3:0] payload);
  wire [3:0] flags;
  assign flags[0] = data[1:0] == 2'b00;
  assign flags[1] = data[2];
  assign flags[2] = data[3] & !data[0];
  assign flags[3] = data[4];
  assign payload = flags;
endmodule
module sink(input [3:0] payload, left, right, output [3:0] accepted, extra);
  assign accepted[0] = payload[0] ? left[0] : right[0];
  assign accepted[1] = payload[1] ? left[1] : right[1];
  assign accepted[2] = payload[2] ? left[2] : right[2];
  assign accepted[3] = payload[3] ? left[3] : right[3];
  assign extra = 4'b0000;
endmodule
module neutral;
  wire [3:0] link;
  source a(.data(5'b10101), .payload(link));
  sink b(.payload(link), .left(4'b1100), .right(4'b0011), .accepted(), .extra());
endmodule
"""
    substitutions = {
        "partial": ("assign flags[3] = data[4];", ""),
        "unsupported": ("data[1:0] == 2'b00", "data[0] + data[1]"),
        "transform": ("payload = flags;", "payload = flags ^ 4'b0001;"),
        "reference": ("extra = 4'b0000;", "extra = payload;"),
    }
    if change:
        source = source.replace(*substitutions[change])
    return source


def _record_bitfield_consumer(tmp_path):
    from dataclasses import asdict
    finding = _consume(tmp_path)
    (tmp_path / "actual-consumer.json").write_text(
        json.dumps(asdict(finding), indent=2))
    return finding


@_NATIVE
def test_native_exact_control_bitfield_reaches_actual_receipt(tmp_path):
    import hashlib
    import shutil
    retained = Path(os.environ["ISSUE3368_RETAINED_RTL"])
    expected = json.loads(Path(os.environ["ISSUE3368_INPUT_SHA"]).read_text())
    rtl, out = tmp_path / "rtl", tmp_path / "out"
    rtl.mkdir()
    out.mkdir()
    for name in ("serv_decode.v", "serv_immdec.v"):
        original = retained / name
        assert hashlib.sha256(original.read_bytes()).hexdigest() == expected["/subject/rtl/" + name]
        shutil.copyfile(original, rtl / name)
    (rtl / "neutral.v").write_text(r"""
module neutral;
  wire [3:0] link;
  serv_decode #(.PRE_REGISTER(1), .MDU(0)) a(
    .clk(1'b0), .i_wb_rdt(30'b0), .i_wb_en(1'b1), .o_immdec_ctrl(link));
  serv_immdec #(.W(1), .SHARED_RFADDR_IMM_REGS(1)) b(
    .i_clk(1'b0), .i_cnt_en(1'b0), .i_cnt_done(1'b0), .i_immdec_en(4'b0000),
    .i_csr_imm_en(1'b0), .i_ctrl(link), .i_wb_en(1'b1),
    .i_wb_rdt(25'b0), .o_imm());
endmodule
""")
    result = subprocess.run([sys.executable, str(SCRIPT), "--rtl-dir", str(rtl),
        "--top-module", "neutral", "--out-dir", str(out)], capture_output=True, text=True)
    report = json.loads((out / "encoding_audit_report.json").read_text())
    assert result.returncode == 0, result.stdout + result.stderr
    row, = report["interfaces"]
    assert (row["producer_encoding"], row["consumer_encoding"], row["status"]) == (
        "BITFIELD_CONTROL", "BITFIELD_CONTROL", "MATCH")
    assert [r["index"] for r in row["semantic_proof"]["lanes"]] == [0, 1, 2, 3]
    assert _record_bitfield_consumer(tmp_path).state == "PASS"


@_NATIVE
def test_native_bitfield_source_freshness_is_required(tmp_path):
    result, report = _run(tmp_path, _bitfield_fixture())
    assert result.returncode == 0, result.stdout + result.stderr
    assert _record_bitfield_consumer(tmp_path).state == "PASS"
    source = tmp_path / "rtl/neutral.sv"
    source.write_text(source.read_text().replace("data[4]", "!data[4]"))
    assert _record_bitfield_consumer(tmp_path).state == "NOT_MEASURED"


@_NATIVE
@pytest.mark.parametrize("change", ["partial", "unsupported", "transform", "reference"])
def test_native_bitfield_partial_unsupported_transform_or_reference_refuses(tmp_path, change):
    result, report = _run(tmp_path, _bitfield_fixture(change))
    assert result.returncode in (0, 2), result.stdout + result.stderr
    assert all(row["producer_encoding"] != "BITFIELD_CONTROL" for row in report["interfaces"])
    assert _record_bitfield_consumer(tmp_path).state == "NOT_MEASURED"


@_NATIVE
@pytest.mark.parametrize("change", ["lane", "order", "semantic", "missing"])
def test_native_bitfield_claim_must_match_actual_source_contract(tmp_path, change):
    result, report = _run(tmp_path, _bitfield_fixture())
    assert result.returncode == 0, result.stdout + result.stderr
    row, = report["interfaces"]
    # Deliberate forged receipt, also executable with exact pre-fix production.
    # No missing-key/setup failure may stand in for its observed consumer state.
    row["producer_encoding"] = row["consumer_encoding"] = "BITFIELD_CONTROL"
    row["status"] = "MATCH"
    proof = row.setdefault("semantic_proof", {"role": "BITFIELD_CONTROL",
        "lanes": [{"index": 0, "expression": "data[0]"}],
        "native_port_bits": [[1, 2, 3, 4]]})
    if change == "lane":
        proof["lanes"][0]["index"] = 3
    elif change == "order":
        proof["native_port_bits"][-1].reverse()
    elif change == "semantic":
        proof["lanes"][0]["expression"] = "1'b1"
    else:
        del row["semantic_proof"]
    report["summary"].update(matches=1, mismatches=0, not_applicable=0, unknowns=0, verdict="PASS")
    report["semantic_coverage"].update(complete=True, decided=1, not_applicable=0, unknown=0)
    report["interface_population"] = audit._population.binding(report["interfaces"])
    (tmp_path / "out/encoding_audit_report.json").write_text(json.dumps(report))
    assert _record_bitfield_consumer(tmp_path).state == "NOT_MEASURED"


def test_closed_boolean_and_opaque_grammars_are_not_scalar_defaults():
    boolean = r"""
module source(input en, rst, output payload); assign payload = en & ~rst; endmodule
module sink(input payload, output accepted); assign accepted = payload; endmodule
module neutral;
  wire link; source a(.en(1'b1),.rst(1'b0),.payload(link));
  sink b(.payload(link),.accepted());
endmodule
"""
    widths = {"source": {"en": 1, "rst": 1, "payload": 1},
              "sink": {"payload": 1, "accepted": 1},
              "neutral": {"link": 1}}
    producer, consumer = _semantic_role(boolean, widths)
    assert producer.encoding == consumer.encoding == "BOOLEAN_VALUE"

    opaque = boolean.replace(
        "input en, rst, output payload", "input [7:0] en, output [7:0] payload"
    ).replace(
        "assign payload = en & ~rst", "assign payload = en"
    ).replace(
        "input payload, output accepted", "input [7:0] payload, output [7:0] accepted"
    ).replace(
        ".en(1'b1),.rst(1'b0),", ".en(8'h5a),"
    )
    widths = {"source": {"en": 8, "payload": 8},
              "sink": {"payload": 8, "accepted": 8},
              "neutral": {"link": 8}}
    producer, consumer = _semantic_role(opaque, widths)
    assert producer.encoding == consumer.encoding == "OPAQUE_VALUE"


def test_fixed_slice_equality_alias_is_a_bounded_boolean_source_domain():
    source = r"""
module source(input [2:0] funct3, output payload);
  wire comparison = funct3[2:1] == 2'b00;
  assign payload = comparison;
endmodule
module sink(input payload, input left, right, output accepted);
  assign accepted = payload ? left : right;
endmodule
module neutral;
  wire link; source a(.funct3(3'b000),.payload(link));
  sink b(.payload(link),.left(1'b0),.right(1'b1),.accepted());
endmodule
"""
    widths = {"source": {"funct3": 3, "comparison": 1, "payload": 1},
              "sink": {"payload": 1, "left": 1, "right": 1,
                       "accepted": 1},
              "neutral": {"link": 1}}
    consumer, producer_evidence = _predicate_role(source, widths)
    assert consumer.encoding == "PREDICATE"
    assert "fixed slice equality" in producer_evidence


@pytest.mark.parametrize("expression", [
    "funct3[2:1] + 2'b00",
    "funct3[2]",
    "funct3[dynamic:1] == 2'b00",
    "funct3[2:1] == 1'b0",
])
def test_noncomparison_dynamic_or_width_mismatched_alias_stays_unknown(expression):
    source = r"""
module source(input [2:0] funct3, input dynamic, output payload);
  wire comparison = EXPRESSION;
  assign payload = comparison;
endmodule
module sink(input payload, input left, right, output accepted);
  assign accepted = payload ? left : right;
endmodule
module neutral;
  wire link; source a(.funct3(3'b000),.dynamic(1'b0),.payload(link));
  sink b(.payload(link),.left(1'b0),.right(1'b1),.accepted());
endmodule
""".replace("EXPRESSION", expression)
    widths = {"source": {"funct3": 3, "dynamic": 1, "comparison": 1,
                         "payload": 1},
              "sink": {"payload": 1, "left": 1, "right": 1,
                       "accepted": 1},
              "neutral": {"link": 1}}
    assert _predicate_role(source, widths) is None


def test_for_condition_relational_less_equal_is_not_an_assignment():
    source = r"""
module source(input [2:0] funct3, output a);
  wire b = funct3[2:1] == 2'b00;
  integer i;
  reg c;
  always @* for (i = 0; i < 1 && a <= b; i = i + 1) c = 1'b0;
endmodule
module sink(input a, input left, right, output accepted);
  assign accepted = a ? left : right;
endmodule
module neutral;
  wire link; source p(.funct3(3'b000),.a(link));
  sink q(.a(link),.left(1'b0),.right(1'b1),.accepted());
endmodule
"""
    widths = {"source": {"funct3": 3, "a": 1, "b": 1, "c": 1},
              "sink": {"a": 1, "left": 1, "right": 1, "accepted": 1},
              "neutral": {"link": 1}}
    role = _predicate_role(source, widths, "a")
    observed = "UNKNOWN" if role is None else role[0].encoding
    assert observed == "UNKNOWN"


@_NATIVE
def test_retained_259_ids_admit_only_source_bound_comparison_selectors(tmp_path):
    result, report, expected = _run_retained(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    def identity(row):
        return tuple(row[key] for key in (
            "wire_name", "producer_module", "producer_port",
            "consumer_module", "consumer_port"))

    assert len(report["interfaces"]) == 259
    assert sorted(map(identity, report["interfaces"])) == sorted(
        map(identity, expected["interfaces"]))
    target, = [row for row in report["interfaces"]
               if row["wire_name"] == "alu_cmp_eq"
               and row["producer_port"] == "o_alu_cmp_eq"
               and row["consumer_port"] == "i_cmp_eq"]
    assert (target["producer_encoding"], target["consumer_encoding"],
            target["status"]) == ("BIT_VALUE", "PREDICATE", "MATCH")
    assert "fixed slice equality" in target["producer_evidence"]
    unrelated, = [row for row in report["interfaces"]
                  if row["wire_name"] == "immdec_ctrl"
                  and row["producer_port"] == "o_immdec_ctrl"]
    assert unrelated["status"] == "UNKNOWN"


@pytest.mark.parametrize("change", [
    ("assign payload = en", "assign payload = en ^ 8'h1"),
    ("assign accepted = payload", "assign accepted[3:0] = payload[3:0]"),
])
def test_transform_and_partial_write_are_outside_the_opaque_grammar(change):
    source = r"""
module source(input [7:0] en, output [7:0] payload); assign payload = en; endmodule
module sink(input [7:0] payload, output [7:0] accepted); assign accepted = payload; endmodule
module neutral;
  wire [7:0] link; source a(.en(8'h5a),.payload(link));
  sink b(.payload(link),.accepted());
endmodule
""".replace(*change)
    widths = {"source": {"en": 8, "payload": 8},
              "sink": {"payload": 8, "accepted": 8},
              "neutral": {"link": 8}}
    assert _semantic_role(source, widths) is None


def _whole_copy_edge(consumer_statement):
    source = r"""
module source(input [7:0] data, output [7:0] payload);
  assign payload = data;
endmodule
module sink(input [7:0] payload, input [7:0] limit,
            output reg [7:0] accepted, output reg [7:0] i);
  STATEMENT
endmodule
module neutral;
  wire [7:0] link;
  source a(.data(8'h5a), .payload(link));
  sink b(.payload(link), .limit(8'h7f), .accepted(), .i());
endmodule
""".replace("STATEMENT", consumer_statement)
    widths = {"source": {"data": 8, "payload": 8},
              "sink": {"payload": 8, "limit": 8,
                       "accepted": 8, "i": 8},
              "neutral": {"link": 8}}
    return source, widths


@_NATIVE
def test_native_genuine_nonblocking_whole_copy_remains_opaque_value(tmp_path):
    source, widths = _whole_copy_edge(
        "always @* begin accepted <= payload; end")
    producer, consumer = _semantic_role(source, widths)
    assert producer.encoding == consumer.encoding == "OPAQUE_VALUE"
    result, report = _run(tmp_path, source)
    assert result.returncode == 0, result.stdout + result.stderr
    row, = report["interfaces"]
    assert (row["producer_encoding"], row["consumer_encoding"],
            row["status"]) == (
                "OPAQUE_VALUE", "OPAQUE_VALUE", "NOT_APPLICABLE")
    assert _consume(tmp_path).state == "PASS"


@pytest.mark.parametrize("statement", [
    "always @* for (i = 0; i <= payload; i = i + 1) accepted = i;",
    "always @* for (i = payload; i < limit; i = i + 1) accepted = i;",
    "assign accepted = i <= payload;",
])
def test_relational_and_control_header_uses_are_not_whole_copies(statement):
    source, widths = _whole_copy_edge(statement)
    assert _semantic_role(source, widths) is None


def test_whole_copy_after_closed_control_header_remains_opaque_value():
    source, widths = _whole_copy_edge(
        "always @* if (limit == 8'h7f) accepted <= payload;")
    producer, consumer = _semantic_role(source, widths)
    assert producer.encoding == consumer.encoding == "OPAQUE_VALUE"


def _if_else_edge(else_statement):
    source = r"""
module source(input [7:0] data, output [7:0] payload);
  assign payload = data;
endmodule
module sink(input [7:0] payload, input choose, output reg [7:0] accepted);
  always @* if (choose) accepted <= payload;
            else        ELSE_STATEMENT
endmodule
module neutral;
  wire [7:0] link;
  source a(.data(8'h5a), .payload(link));
  sink b(.payload(link), .choose(1'b1), .accepted());
endmodule
""".replace("ELSE_STATEMENT", else_statement)
    widths = {"source": {"data": 8, "payload": 8},
              "sink": {"payload": 8, "choose": 1, "accepted": 8},
              "neutral": {"link": 8}}
    return source, widths


@_NATIVE
def test_native_if_else_whole_copies_remain_opaque_value(tmp_path):
    source, widths = _if_else_edge("accepted <= payload;")
    result, report = _run(tmp_path, source)
    assert result.returncode == 0, result.stdout + result.stderr
    row, = report["interfaces"]
    assert (row["producer_encoding"], row["consumer_encoding"],
            row["status"]) == (
                "OPAQUE_VALUE", "OPAQUE_VALUE", "NOT_APPLICABLE")
    assert _consume(tmp_path).state == "PASS"
    producer, consumer = _semantic_role(source, widths)
    assert producer.encoding == consumer.encoding == "OPAQUE_VALUE"


def test_else_arm_relational_expression_is_not_a_whole_copy():
    source, widths = _if_else_edge("accepted = accepted <= payload;")
    assert _semantic_role(source, widths) is None


@pytest.mark.parametrize("statement", [
    '`define COPY_TEXT "accepted <= payload;"',
    "always @* begin /* accepted <= payload; */ accepted = 8'h00; end",
])
def test_assignment_text_in_string_or_comment_is_not_a_whole_copy(statement):
    source, widths = _whole_copy_edge(statement)
    assert _semantic_role(source, widths) is None


@_NATIVE
def test_native_relational_le_reaches_report_and_receipt_consumer(tmp_path):
    source, _ = _whole_copy_edge("assign accepted = i <= payload;")
    result, report = _run(tmp_path, source)
    assert result.returncode == 0, result.stdout + result.stderr
    row, = report["interfaces"]
    assert (row["consumer_encoding"], row["status"]) == (
        "UNKNOWN", "UNKNOWN")
    assert report["semantic_coverage"]["complete"] is False
    assert _consume(tmp_path).state == "NOT_MEASURED"


def test_receipt_verdict_counts_not_applicable_but_never_unknown_as_complete():
    shared = PROGRAMS.parent / "_shared"
    sys.path.insert(0, str(shared))
    import skill_compliance_check as checker

    row = {"status": "NOT_APPLICABLE",
           "producer_encoding": "BOOLEAN_VALUE",
           "consumer_encoding": "BOOLEAN_VALUE"}
    payload = {
        "producer_returncode": 0,
        "summary": {"verdict": "PASS", "mismatches": 0,
                    "unknowns": 0},
        "interfaces": [row],
        "discovery": {"complete": True},
    }
    assert checker._interface_receipt_verdict(payload) == "PASS"
    payload["summary"].update(verdict="INCONCLUSIVE", unknowns=1)
    payload["interfaces"] = [{**row, "status": "UNKNOWN"}]
    assert checker._interface_receipt_verdict(payload) == "NOT_MEASURED"


@_NATIVE
def test_native_boolean_copy_reaches_the_receipt_consumer(tmp_path):
    result, report = _run(tmp_path, r"""
module source(input logic en, rst, output logic ready);
  assign ready = en & ~rst;
endmodule
module sink(input logic ready, output logic accepted);
  assign accepted = ready;
endmodule
module neutral;
  logic ready;
  source a(.en(1'b1), .rst(1'b0), .ready(ready));
  sink b(.ready(ready), .accepted());
endmodule
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["summary"] == {
        **report["summary"], "total_interfaces": 1, "matches": 0,
        "mismatches": 0, "not_applicable": 1, "unknowns": 0,
        "verdict": "PASS"}
    row, = report["interfaces"]
    assert (row["producer_encoding"], row["consumer_encoding"],
            row["status"]) == (
                "BOOLEAN_VALUE", "BOOLEAN_VALUE", "NOT_APPLICABLE")
    assert report["semantic_coverage"] == {
        "complete": True, "total_interfaces": 1, "decided": 0,
        "not_applicable": 1, "unknown": 0}
    assert _consume(tmp_path).state == "PASS"


@_NATIVE
def test_native_opaque_whole_copy_reaches_the_receipt_consumer(tmp_path):
    result, report = _run(tmp_path, r"""
module source(input logic [7:0] data, output logic [7:0] payload);
  assign payload = data;
endmodule
module sink(input logic [7:0] payload, output logic [7:0] accepted);
  assign accepted = payload;
endmodule
module neutral;
  logic [7:0] payload;
  source a(.data(8'h5a), .payload(payload));
  sink b(.payload(payload), .accepted());
endmodule
""")
    assert result.returncode == 0, result.stdout + result.stderr
    row, = report["interfaces"]
    assert (row["producer_encoding"], row["consumer_encoding"],
            row["status"]) == (
                "OPAQUE_VALUE", "OPAQUE_VALUE", "NOT_APPLICABLE")
    assert _consume(tmp_path).state == "PASS"


@pytest.mark.parametrize("source", [
    r"""
module source(input logic [7:0] data, output logic [7:0] payload);
  assign payload = data ^ (data >> 1);
endmodule
module sink(input logic [7:0] payload, output logic [7:0] accepted);
  assign accepted = payload;
endmodule
module neutral;
  logic [7:0] payload;
  source a(.data(8'h5a), .payload(payload));
  sink b(.payload(payload), .accepted());
endmodule
""",
    r"""
module source(input logic [7:0] data, output logic [7:0] payload);
  assign payload = data;
endmodule
module sink(input logic [7:0] payload, output logic [7:0] accepted);
  assign accepted[3:0] = payload[3:0];
endmodule
module neutral;
  logic [7:0] payload;
  source a(.data(8'h5a), .payload(payload));
  sink b(.payload(payload), .accepted());
endmodule
""",
])
@_NATIVE
def test_transformed_or_partial_value_edges_remain_unknown(tmp_path, source):
    result, report = _run(tmp_path, source)
    assert result.returncode == 0, result.stdout + result.stderr
    row, = report["interfaces"]
    assert row["status"] == "UNKNOWN", row
    assert report["semantic_coverage"]["complete"] is False
    assert _consume(tmp_path).state == "NOT_MEASURED"


@_NATIVE
def test_known_binary_gray_mismatch_still_blocks(tmp_path):
    result, report = _run(tmp_path, r"""
module source(input logic clk, output logic [5:0] count);
  always_ff @(posedge clk) count <= count + 1'b1;
endmodule
module sink(input logic [5:0] count, output logic hit);
  assign hit = (count == 6'b110000);
endmodule
module neutral;
  logic count_clk, hit;
  logic [5:0] count;
  source a(.clk(count_clk), .count(count));
  sink b(.count(count), .hit(hit));
endmodule
""")
    assert result.returncode == 1, result.stdout + result.stderr
    mismatch = [row for row in report["interfaces"]
                if row["status"] == "MISMATCH"]
    assert len(mismatch) == 1, report
    assert _consume(tmp_path).state == "FAIL"


@_NATIVE
def test_semantic_receipt_becomes_not_measured_after_source_change(tmp_path):
    _, report = _run(tmp_path, r"""
module source(input logic en, rst, output logic ready);
  assign ready = en & ~rst;
endmodule
module sink(input logic ready, output logic accepted);
  assign accepted = ready;
endmodule
module neutral;
  logic ready;
  source a(.en(1'b1), .rst(1'b0), .ready(ready));
  sink b(.ready(ready), .accepted());
endmodule
""")
    assert report["summary"]["verdict"] == "PASS"
    source = tmp_path / "rtl/neutral.sv"
    source.write_text(source.read_text().replace("accepted = ready",
                                                 "accepted = ~ready"))
    assert _consume(tmp_path).state == "NOT_MEASURED"
