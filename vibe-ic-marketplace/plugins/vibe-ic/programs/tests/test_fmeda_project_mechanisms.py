"""Native neutral codeword mechanisms: declaration, complete DC and currentness.

No IC RTL or generated injection testbench is inspected by these tests.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _fmeda_mechanisms as declared
import fmeda_fault_injection_coverage as fi
import fmeda_coverage_check as gate

TOOLS = all(shutil.which(t) for t in ("yosys", "iverilog", "vvp"))
native = pytest.mark.skipif(not TOOLS, reason="native Yosys/slang and Icarus required")


def fixture(project):
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    source = rtl / "component.sv"
    source.write_text("""
module wide_encode(input logic [7:0] data_i, output logic [8:0] code_o);
 assign code_o = {^data_i,data_i};
endmodule
module wide_check(input logic [8:0] code_i, output logic err_o);
 wire [8:0] expected_code;
 wide_encode encoder(.data_i(code_i[7:0]), .code_o(expected_code));
 assign err_o = |(expected_code ^ code_i);
endmodule
module small_encode(input logic [2:0] data_i, output logic [3:0] code_o);
 assign code_o = {^data_i,data_i};
endmodule
module small_check(input logic [3:0] code_i, output logic err_o);
 wire [3:0] expected_code;
 small_encode encoder(.data_i(code_i[2:0]), .code_o(expected_code));
 assign err_o = |(expected_code ^ code_i);
endmodule
module component(input logic [8:0] wide_i, input logic [3:0] small_i,
 output logic wide_error_o, output logic small_error_o);
 wide_check wide_checker(.code_i(wide_i), .err_o(wide_error_o));
 small_check small_checker(.code_i(small_i), .err_o(small_error_o));
endmodule
""")
    l9 = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({"top_module": "component"}))
    mechanisms = []
    for label, width in (("wide", 8), ("small", 3)):
        instance = "component." + label + "_checker"
        mechanisms.append({"id": label, "kind": "parity",
                           "encoder": {"module": label + "_encode", "instance": instance + ".encoder",
                                       "input": "data_i", "output": "code_o"},
                           "checker": {"module": label + "_check", "instance": instance,
                                       "input": "code_i", "detect": "err_o", "corrected_output": None},
                           "data_width": width, "code_width": width + 1})
    doc = {"schema": declared.SCHEMA, "authority": "AUTHOR_ENGINEERING_DECLARATION",
           "top_module": "component", "rtl_files": [{"path": str(source.relative_to(project)),
                                                        "sha256": declared.digest(source)}],
           "mechanisms": mechanisms}
    (project / declared.MANIFEST).write_text(json.dumps(doc))
    return doc, source


def args():
    return SimpleNamespace(asil="D", min_dc=None, max_vectors=64, timeout=20)


def write_doc(project, doc):
    (project / declared.MANIFEST).write_text(json.dumps(doc))


@native
def test_two_native_mechanisms_full_census_and_current_consumer(tmp_path):
    fixture(tmp_path)
    rc, report = fi.run(tmp_path, args())
    assert rc == 0, report
    assert gate.check(report, None, None, tmp_path)["passed"]
    wide, small = report["mechanisms"]
    assert (wide["injected_faults"], small["injected_faults"]) == (576, 32)
    assert len(wide["fault_list"]) == 576 and not wide["fault_list_truncated"]
    assert all(r["match"] is None for r in wide["fault_list"])
    assert all(not r["detect"] and r["code_known"] for r in wide["baseline"])
    # This used to fit the aggregate count while silently dropping raw rows.
    damaged = copy.deepcopy(report)
    damaged["mechanisms"][0]["fault_list"].pop()
    assert not gate.check(damaged, None, None, tmp_path)["passed"]
    raw = tmp_path / wide["raw_evidence"]["path"]
    original = raw.read_bytes()
    lines = raw.read_text().splitlines()
    # Independently remove an actual row rather than depending on a vector value.
    raw.write_text("\n".join(lines[:next(i for i, v in enumerate(lines) if v.startswith("FAULT"))] +
                             lines[next(i for i, v in enumerate(lines) if v.startswith("FAULT")) + 1:]))
    assert not gate.check(report, None, None, tmp_path)["passed"]
    # Updating a transcript checksum cannot conceal an incomplete denominator.
    updated = copy.deepcopy(report)
    updated["mechanisms"][0]["raw_evidence"]["sha256"] = declared.digest(raw)
    assert "census" in gate.check(updated, None, None, tmp_path)["reason"]
    raw.write_bytes(original)
    assert gate.check(report, None, None, tmp_path)["passed"]


@pytest.mark.parametrize("change", ["hash", "missing", "width", "module", "unreachable", "duplicate_id", "top"])
@native
def test_present_invalid_manifest_never_falls_back(tmp_path, change):
    doc, _ = fixture(tmp_path)
    if change == "hash":
        doc["rtl_files"][0]["sha256"] = "0" * 64
    elif change == "missing":
        doc["mechanisms"][0]["checker"].pop("detect")
    elif change == "width":
        doc["mechanisms"][0]["code_width"] = 8
    elif change == "module":
        doc["mechanisms"][0]["checker"]["module"] = "small_check"
    elif change == "unreachable":
        doc["mechanisms"][0]["checker"]["instance"] = "component.unused"
    elif change == "duplicate_id":
        doc["mechanisms"][1]["id"] = "wide"
    else:
        doc["top_module"] = "alternate"
    write_doc(tmp_path, doc)
    rc, report = fi.run(tmp_path, args())
    assert rc == 1 and report["measured"] is False, report
    assert not gate.check({"applicable": False, "verdict": "NOT_APPLICABLE"}, None, None, tmp_path)["passed"]


@native
@pytest.mark.parametrize("target", ["wide", "small"])
def test_disabled_detector_each_mechanism_cannot_hide_behind_other(tmp_path, target):
    doc, source = fixture(tmp_path)
    start = source.read_text()
    code = start.replace("module " + target + "_check", "module " + target + "_check", 1)
    begin = code.index("module " + target + "_check")
    end = code.index("endmodule", begin)
    body = code[begin:end].replace("assign err_o = |(expected_code ^ code_i);", "assign err_o = 1'b0;")
    source.write_text(code[:begin] + body + code[end:])
    doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    rc, report = fi.run(tmp_path, args())
    assert rc == 1, report
    by_id = {r["id"]: r for r in report["mechanisms"]}
    assert by_id[target]["baseline_valid"] and by_id[target]["detected_faults"] == 0
    assert by_id[target]["injected_faults"] > 0
    assert not gate.check(report, None, None, tmp_path)["passed"]
    # Even a lenient combined percentage cannot establish each mechanism floor.
    assert gate.check(report, None, 1, tmp_path)["passed"] is False
    source.write_text(start)
    doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    assert fi.run(tmp_path, args())[0] == 0


@native
def test_currentness_mutations_restore_original_bytes(tmp_path):
    fixture(tmp_path)
    rc, report = fi.run(tmp_path, args())
    assert rc == 0, report
    for rel in [declared.MANIFEST, "phase2/stage1/rtl/component.sv",
                "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
                declared.NATIVE_DIR + "/hierarchy.json", declared.NATIVE_DIR + "/execution.json"]:
        path = tmp_path / rel
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        assert not gate.check(report, None, None, tmp_path)["passed"], rel
        path.write_bytes(original)
        assert gate.check(report, None, None, tmp_path)["passed"], rel
    manifest = tmp_path / declared.MANIFEST
    original = manifest.read_bytes()
    manifest.unlink()
    assert not gate.check(report, None, None, tmp_path)["passed"]
    manifest.write_bytes(original)
    assert gate.check(report, None, None, tmp_path)["passed"]
    legacy = {"applicable": True, "baseline_valid": True, "injected_faults": 10,
              "detected_faults": 10, "verdict": "PASS"}
    assert not gate.check(legacy, None, None, tmp_path)["passed"]
    assert gate.main([str(tmp_path)]) == 1  # declaration requires its report


@native
def test_large_mechanism_cannot_mask_smaller_below_99_percent(tmp_path):
    doc, source = fixture(tmp_path)
    text = source.read_text()
    begin = text.index("module small_check")
    end = text.index("endmodule", begin)
    body = text[begin:end].replace("assign err_o = |(expected_code ^ code_i);",
                                  "assign err_o = (|(expected_code ^ code_i)) && (code_i[2:0] != 3'd0);")
    source.write_text(text[:begin] + body + text[end:])
    doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    rc, report = fi.run(tmp_path, args())
    assert rc == 1, report
    wide, small = report["mechanisms"]
    assert wide["detected_faults"] == 576
    assert (small["detected_faults"], small["injected_faults"]) == (28, 32)
    pooled = fi.compute_dc(sum(r["detected_faults"] for r in report["mechanisms"]),
                           sum(r["injected_faults"] for r in report["mechanisms"]))
    assert pooled > 99 and small["diagnostic_coverage_pct"] < 99
    assert not gate.check(report, None, None, tmp_path)["passed"]


@native
def test_report_asil_cannot_lower_native_campaign_floor(tmp_path):
    doc, source = fixture(tmp_path)
    text = source.read_text()
    begin = text.index("module small_check")
    end = text.index("endmodule", begin)
    body = text[begin:end].replace("assign err_o = |(expected_code ^ code_i);",
                                  "assign err_o = (|(expected_code ^ code_i)) && (code_i[2:0] != 3'd0);")
    source.write_text(text[:begin] + body + text[end:])
    doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    rc, report = fi.run(tmp_path, args())
    assert rc == 1 and report["asil"] == "D"
    assert [(row["detected_faults"], row["injected_faults"])
            for row in report["mechanisms"]] == [(576, 576), (28, 32)]
    assert not gate.check(report, None, None, tmp_path)["passed"]
    lowered = copy.deepcopy(report)
    lowered["asil"] = "A"  # Only the report changes; native transcript and inputs stay fixed.
    assert not gate.check(lowered, None, None, tmp_path)["passed"]
    # An intentional non-D campaign remains available only when the consumer
    # receives that policy independently through its own CLI argument.
    a_args = args()
    a_args.asil = "A"
    a_rc, a_report = fi.run(tmp_path, a_args)
    assert a_rc == 0 and a_report["asil"] == "A"
    assert not gate.check(a_report, None, None, tmp_path)["passed"]
    assert gate.check(a_report, "A", None, tmp_path)["passed"]
    assert not gate.check(a_report, "D", None, tmp_path)["passed"]
    source.write_text(text)
    doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    strict_args = args()
    strict_args.min_dc = 99.5
    strict_rc, strict_report = fi.run(tmp_path, strict_args)
    assert strict_rc == 0 and strict_report["dc_floor_pct"] == 99.5
    assert not gate.check(strict_report, None, None, tmp_path)["passed"]
    assert gate.check(strict_report, None, 99.5, tmp_path)["passed"]


@native
def test_explicit_detection_only_cli_report_cannot_lower_asil_floor(tmp_path):
    doc, source = fixture(tmp_path)
    (tmp_path / declared.MANIFEST).unlink()  # Exercise the new no-manifest CLI path.
    text = source.read_text()
    begin = text.index("module small_check")
    end = text.index("endmodule", begin)
    body = text[begin:end].replace("assign err_o = |(expected_code ^ code_i);",
                                  "assign err_o = (|(expected_code ^ code_i)) && (code_i[2:0] != 3'd0);")
    source.write_text(text[:begin] + body + text[end:])
    report_path = tmp_path / "explicit_report.json"
    producer_args = [
        sys.executable, str(Path(fi.__file__)), str(tmp_path),
        "--enc-module", "small_encode", "--enc-in", "data_i", "--enc-out", "code_o",
        "--dec-module", "small_check", "--dec-in", "code_i", "--detect-port", "err_o",
        "--data-width", "3", "--code-width", "4", "--rtl-file",
        str(source.relative_to(tmp_path)), "--asil", "D", "--json", str(report_path),
    ]
    producer = subprocess.run(producer_args, capture_output=True, text=True)
    report = json.loads(report_path.read_text())
    assert producer.returncode == 1 and report["measured"] is True
    assert (report["detected_faults"], report["injected_faults"]) == (28, 32)

    def consume(*policy):
        return subprocess.run([sys.executable, str(Path(gate.__file__)),
                               str(tmp_path), "--report", str(report_path), *policy],
                              capture_output=True, text=True)

    assert consume().returncode == 1
    report["asil"] = "A"  # The native result, floor, and source remain unchanged.
    report_path.write_text(json.dumps(report))
    assert consume().returncode == 1
    report["mechanism"].pop("source")  # An editable marker cannot choose policy.
    report_path.write_text(json.dumps(report))
    assert consume().returncode == 1
    report["mechanism"]["source"] = "unknown"
    report_path.write_text(json.dumps(report))
    assert consume().returncode == 1
    producer_args[producer_args.index("--asil") + 1] = "A"
    assert subprocess.run(producer_args, capture_output=True, text=True).returncode == 0
    assert json.loads(report_path.read_text())["dc_floor_pct"] is None
    assert consume().returncode == 1
    assert consume("--asil", "A").returncode == 0


@native
@pytest.mark.parametrize("location", ["checker_header", "checker_body", "encoder_dependency", "macro_body"])
def test_parameterized_reachable_instance_cannot_measure_default_module(tmp_path, location):
    doc, source = fixture(tmp_path)
    text = source.read_text()
    if location == "encoder_dependency":
        text = text.replace("module wide_encode(", "module wide_encode #(parameter bit DISABLE = 0) (")
    else:
        if location == "checker_header":
            text = text.replace("module wide_check(", "module wide_check #(parameter bit DISABLE = 0) (")
        elif location == "checker_body":
            text = text.replace("wire [8:0] expected_code;", "parameter bit DISABLE = 0; wire [8:0] expected_code;", 1)
        else:
            text = "`define SETTINGS parameter bit DISABLE = 0;\n" + text
            text = text.replace("wire [8:0] expected_code;", "`SETTINGS\n wire [8:0] expected_code;", 1)
        text = text.replace("assign err_o = |(expected_code ^ code_i);",
                            "assign err_o = DISABLE ? 1'b0 : |(expected_code ^ code_i);", 1)
        text = text.replace("wide_check wide_checker", "wide_check #(.DISABLE(1)) wide_checker")
    source.write_text(text)
    doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    rc, report = fi.run(tmp_path, args())
    assert rc == 1 and not report["measured"], report
    assert "unsupported parameterized mechanism instance" in report["reason"]
    assert not gate.check(report, None, None, tmp_path)["passed"]


@native
def test_unrelated_parameterized_module_remains_outside_selected_boundary(tmp_path):
    doc, source = fixture(tmp_path)
    source.write_text(source.read_text() + "\nmodule unrelated #(parameter bit P=1)(output logic o); assign o=P; endmodule\n")
    doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    rc, report = fi.run(tmp_path, args())
    assert rc == 0, report
    assert gate.check(report, None, None, tmp_path)["passed"]


def test_duplicate_keys_and_symlink_are_refused(tmp_path):
    _, source = fixture(tmp_path)
    manifest = tmp_path / declared.MANIFEST
    original = manifest.read_text()
    manifest.write_text(original.replace('"schema":', '"schema": "duplicate", "schema":', 1))
    with pytest.raises(declared.Refusal, match="duplicate JSON key"):
        declared.declaration(tmp_path)
    manifest.write_text(original)
    target = source.with_name("copy.txt")
    target.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(target)
    with pytest.raises(declared.Refusal, match="symlink"):
        declared.declaration(tmp_path)


@native
@pytest.mark.parametrize("mutation", ["false_alarm", "direction", "unbound_include", "stateful"])
def test_actual_source_semantics_refuse(tmp_path, mutation):
    doc, source = fixture(tmp_path)
    text = source.read_text()
    if mutation == "false_alarm":
        text = text.replace("assign err_o = |(expected_code ^ code_i);", "assign err_o = 1'b1;")
    elif mutation == "direction":
        text = text.replace("input logic [7:0] data_i", "output logic [7:0] data_i")
    elif mutation == "stateful":
        text = text.replace("assign code_o = {^data_i,data_i};",
                            "always_ff @(posedge data_i[0]) code_o <= {^data_i,data_i};", 1)
    else:
        extra = tmp_path / "unlisted.svh"
        extra.write_text("// not part of authored population\n")
        text = f'`include "{extra}"\n' + text
    source.write_text(text)
    doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    rc, report = fi.run(tmp_path, args())
    assert rc == 1, report
    if mutation == "false_alarm":
        assert all(not m["baseline_valid"] for m in report["mechanisms"])
        assert not gate.check(report, None, None, tmp_path)["passed"]
    else:
        assert not report["measured"]


@pytest.mark.parametrize("golden,fault,expected", [(0, 1, True), (1, 1, False), (0, 0, False)])
def test_detection_only_na_is_not_a_correction(golden, fault, expected):
    spec = fi.MechanismSpec("parity", "enc", "d", "c", "chk", "c", None, "err", 1, 2)
    out = "\n".join(f"GOLDEN DATA {d} DETECT {golden} MATCH NA CODE_KNOWN 1\n" +
                    "\n".join(f"FAULT d{d}_b{i} DETECT {fault} MATCH NA" for i in range(2))
                    for d in range(2))
    result, _, rows = declared.census(out, spec, 2)
    assert (result.golden_ok and result.detected == result.injected) is expected
    assert all(row["match"] is None and row["covered"] is bool(fault) for row in rows)


def test_absent_manifest_does_not_take_over_legacy_gate(tmp_path):
    report = {"applicable": False, "reason": "legacy classification"}
    assert gate.check(report, None, None, tmp_path)["verdict"] == "VACUOUS_PASS"


def test_legacy_measured_report_without_source_uses_consumer_default_d(tmp_path):
    report = {"applicable": True, "baseline_valid": True,
              "injected_faults": 10, "detected_faults": 10, "verdict": "PASS"}
    assert gate.check(report, None, None, tmp_path)["passed"]
    report["detected_faults"] = 0
    assert not gate.check(report, None, None, tmp_path)["passed"]
    report["asil"] = "A"
    assert not gate.check(report, None, None, tmp_path)["passed"]
    assert gate.check(report, "A", None, tmp_path)["passed"]


def embedded_fixture(project, implementation="local"):
    """The issue's real endpoint, not a substitute checker or encoder."""
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    function = """function automatic bit encode_tag(input logic [3:0] payload);
      encode_tag=^payload;
    endfunction"""
    sources = []
    if implementation == "package":
        package = rtl / "integrity_pkg.sv"
        package.write_text("package integrity_pkg;\n" + function + "\nendpackage\n")
        sources.append(package)
        function = "import integrity_pkg::*;"
    source = rtl / "protocol_endpoint.sv"
    source.write_text("""module protocol_endpoint(input logic clk_i, rst_n,
      input logic [4:0] request_i, output logic [3:0] payload_o,
      output logic fault_o);
    """ + function + """
      assign payload_o=request_i[3:0];
      assign fault_o=(encode_tag(request_i[3:0])!=request_i[4]);
    endmodule
    """)
    sources.append(source)
    l9 = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({"top_module": "protocol_endpoint"}))
    row = {"id": "request_parity", "kind": "parity",
           "checker": {"module": "protocol_endpoint", "instance": "protocol_endpoint",
                       "input": "request_i", "detect": "fault_o", "corrected_output": None,
                       "constant_inputs": {"clk_i": {"width": 1, "value": 0},
                                           "rst_n": {"width": 1, "value": 1}}},
           "data_width": 4, "code_width": 5,
           "stimulus": {"encoding": "even_parity", "data_bits": [0, 1, 2, 3], "check_bit": 4}}
    doc = {"schema": declared.SCHEMA, "authority": "AUTHOR_ENGINEERING_DECLARATION",
           "top_module": "protocol_endpoint", "rtl_files": [
               {"path": str(p.relative_to(project)), "sha256": declared.digest(p)} for p in sources],
           "mechanisms": [row]}
    write_doc(project, doc)
    return doc, source


@native
@pytest.mark.parametrize("implementation", ["local", "package"])
def test_embedded_real_endpoint_native_cli_and_consumer(tmp_path, implementation):
    embedded_fixture(tmp_path, implementation)
    report_path = tmp_path / "reports/phase2/safety/fmeda_coverage.json"
    assert fi.main([str(tmp_path), "--asil", "D", "--json", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["measured"] and report["verdict"] == "PASS"
    row, = report["mechanisms"]
    assert (row["injected_faults"], row["detected_faults"]) == (80, 80)
    assert len(row["baseline"]) == 16 and row["baseline_valid"]
    assert row["mechanism"]["encoder"] is None
    assert row["mechanism"]["decoder"] == "protocol_endpoint"
    assert row["correction_applicable"] is False
    assert all(fault["match"] is None for fault in row["fault_list"])
    assert gate.main([str(tmp_path), "--require"]) == 0


@native
@pytest.mark.parametrize("mutation", ["tied_low", "false_alarm", "wrong_parity"])
def test_embedded_actual_detector_and_valid_baseline_required(tmp_path, mutation):
    doc, source = embedded_fixture(tmp_path)
    if mutation == "wrong_parity":
        doc["mechanisms"][0]["stimulus"]["encoding"] = "odd_parity"
    else:
        source.write_text(source.read_text().replace(
            "(encode_tag(request_i[3:0])!=request_i[4])",
            "1'b0" if mutation == "tied_low" else "1'b1"))
        doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    rc, report = fi.run(tmp_path, args())
    assert rc == 1 and report["measured"] is True, report
    row, = report["mechanisms"]
    assert row["injected_faults"] == 80 and row["dc_floor_pct"] == 99.0
    if mutation == "tied_low":
        assert row["baseline_valid"] and row["detected_faults"] == 0
        assert row["diagnostic_coverage_pct"] == 0.0
    else:
        assert not row["baseline_valid"]
    assert not gate.check(report, None, None, tmp_path)["passed"]


@native
@pytest.mark.parametrize("mutation", ["missing_type", "wrong_kind", "wrong_width", "duplicate_bit",
    "outside_bit", "missing_bit", "bool_bit", "wrong_constant_width", "missing_constant", "stateful"])
def test_embedded_unsupported_or_incomplete_binding_is_unmeasured(tmp_path, mutation):
    doc, source = embedded_fixture(tmp_path)
    row = doc["mechanisms"][0]
    if mutation == "missing_type":
        row["stimulus"].pop("encoding")
    elif mutation == "wrong_kind":
        row["kind"] = "ecc"
    elif mutation == "wrong_width":
        row["code_width"] = 6
    elif mutation == "duplicate_bit":
        row["stimulus"]["data_bits"] = [0, 0, 2, 3]
    elif mutation == "outside_bit":
        row["stimulus"]["check_bit"] = 5
    elif mutation == "missing_bit":
        row["stimulus"]["data_bits"].pop()
    elif mutation == "bool_bit":
        row["stimulus"]["data_bits"][0] = False
    elif mutation == "wrong_constant_width":
        row["checker"]["constant_inputs"]["clk_i"]["width"] = 2
    elif mutation == "missing_constant":
        row["checker"]["constant_inputs"].pop("rst_n")
    else:
        source.write_text(source.read_text().replace(
            "assign fault_o=", "always_ff @(posedge clk_i) fault_o <="))
        doc["rtl_files"][0]["sha256"] = declared.digest(source)
    write_doc(tmp_path, doc)
    rc, report = fi.run(tmp_path, args())
    assert rc == 1 and report["applicable"] is True and report["measured"] is False, report
    assert report.get("diagnostic_coverage_pct") is None
    assert not gate.check(report, None, None, tmp_path)["passed"]


@native
def test_embedded_consumer_rejects_stale_source_or_stimulus(tmp_path):
    doc, source = embedded_fixture(tmp_path, "package")
    rc, report = fi.run(tmp_path, args())
    assert rc == 0, report
    assert gate.check(report, None, None, tmp_path)["passed"]
    for target in (source, tmp_path / declared.MANIFEST):
        original = target.read_bytes()
        target.write_bytes(original + b"\n")
        assert not gate.check(report, None, None, tmp_path)["passed"]
        target.write_bytes(original)
        assert gate.check(report, None, None, tmp_path)["passed"]
    damaged = copy.deepcopy(report)
    damaged["mechanisms"][0]["mechanism"]["stimulus"]["encoding"] = "odd_parity"
    assert not gate.check(damaged, None, None, tmp_path)["passed"]
