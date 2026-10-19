"""Native neutral codeword mechanisms: declaration, complete DC and currentness.

No IC RTL or generated injection testbench is inspected by these tests.
"""
import copy
import json
from pathlib import Path
import shutil
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
