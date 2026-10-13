"""A declaration must not state a framing the oracle measured otherwise (U5).

MEASURED on spm IC run v5c (192.168.1.120, run_v5c, 2026-09-29):

  * ``plugin_output/declaration.json`` said ``"latency_cycles": 1``. The RTL
    generator wrote that constant; ``spec_declaration_emit`` then carried it
    as ``existing_declaration`` with ``provenance_verified: false``.
  * ``phase2/stage1/sim_full_stack/arith_oracle_manifest.json`` said
    ``"calibrated_latency": 2`` ("measured by the oracle TB framing search
    (single framing matched every vector)"). The RTL registers the serial
    input (``yr``) AND the product bit (``pr``): two stages.
  * ``reports/phase2/gates/spec_required_artifacts.json`` read ``PASS`` —
    "all 5 spec-REQUIRED free choice(s) declared with a real value".

Two rules, both driven through the real programs:

  1. the emitter does not keep an UNVERIFIED value over a MEASURED one;
  2. the required-artifact gate FAILs a declaration whose field disagrees with
     the measurement, whoever wrote it (an author's ``--set`` included).

Synthetic project, no design name: the contract table and the manifest carry
the same field names and values the measured run did.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS_DIR = Path(__file__).resolve().parents[1]
EMITTER = PROGRAMS_DIR / "spec_declaration_emit.py"
GATE = PROGRAMS_DIR / "spec_required_artifact_check.py"

DECL = "plugin_output/declaration.json"
MANIFEST = "phase2/stage1/sim_full_stack/arith_oracle_manifest.json"

CONTRACT = """# L7 — verification plan

## 7.0 Plugin declaration requirements

Plugin 在開始 RTL 設計前,**必須**於 `plugin_output/declaration.json` 聲明下列項目:

| 欄位 | 必填 | 範例值 | 說明 |
|---|---|---|---|
| `bit_order` | ✅ | `"LSB_first"` / `"MSB_first"` | serial bit order |
| `latency_cycles` | ✅ | integer | cycles from input bit to output bit |
"""

# The run's manifest, field for field (declared_* is the copy of the
# declaration; calibrated_* is the measurement).
V5C_MANIFEST = {
    "program": "arith_oracle_tb_gen",
    "verdict": "TB_EMITTED",
    "topology": "serial_parallel",
    "declared_bit_order": "LSB",
    "declared_latency": 1,
    "framing": "self-calibrated (in_order x out_order x offset search)",
    "calibrated_bit_order": "LSB_first",
    "calibrated_out_bit_order": "LSB_first",
    "calibrated_latency": 2,
    "calibrated_source": ("measured by the oracle TB framing search (single "
                          "framing matched every vector); NOT copied from "
                          "declaration.json"),
}


# Metadata-only guards below retain their original numeric obligations using
# a neutral, explicitly tagged settled measurement. The historical originless
# V5C payload above is retained verbatim; it is not relabeled native evidence.
SETTLED_METADATA_CONTROL = dict(V5C_MANIFEST,
                                calibrated_latency_origin="settled_edge_offset")

def _project(tmp_path: Path, *, declaration=None, manifest=SETTLED_METADATA_CONTROL,
             contract: str = CONTRACT) -> Path:
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "L7_verification_plan.md").write_text(
        contract, encoding="utf-8")
    if manifest is not None:
        (proj / MANIFEST).parent.mkdir(parents=True)
        (proj / MANIFEST).write_text(json.dumps(manifest))
    if declaration is not None:
        (proj / DECL).parent.mkdir(parents=True)
        (proj / DECL).write_text(json.dumps(declaration))
    return proj


def _emit(proj: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(EMITTER), str(proj), *args],
                          capture_output=True, text=True)


def _gate(proj: Path) -> tuple[subprocess.CompletedProcess, dict]:
    out = proj / "reports" / "phase2" / "gates" / "spec_required_artifacts.json"
    cp = subprocess.run([sys.executable, str(GATE), str(proj)],
                        capture_output=True, text=True)
    return cp, json.loads(out.read_text())


def _decl(proj: Path) -> dict:
    return json.loads((proj / DECL).read_text())


def _sidecar(proj: Path) -> dict:
    return json.loads((proj / "plugin_output" /
                       "declaration.provenance.json").read_text())


# 1. The producer --------------------------------------------------------------

def test_measured_latency_replaces_an_unverified_carried_value(tmp_path):
    """v5c: the file carried 1 with no provenance, the oracle measured 2."""
    proj = _project(tmp_path, declaration={"bit_order": "LSB_first",
                                           "latency_cycles": 1})
    cp = _emit(proj)
    assert cp.returncode == 0, cp.stderr
    assert _decl(proj)["latency_cycles"] == 2, (
        "an unverified carried latency survived a measurement that says "
        "otherwise: %r" % _decl(proj))
    rec = _sidecar(proj)["fields"]["latency_cycles"]
    assert rec["provenance"] == "oracle_measurement"
    assert rec["provenance_verified"] is True
    assert rec["replaced_value"] == 1
    assert rec["provenance_detail"].endswith(":calibrated_latency")
    # and the gate agrees with what was written
    gcp, report = _gate(proj)
    assert gcp.returncode == 0, report
    assert report["verdict"] == "PASS"


def test_a_rerun_keeps_the_measurement_and_follows_a_new_one(tmp_path):
    """The measured value is re-measured, not frozen by its own sidecar."""
    proj = _project(tmp_path, declaration={"bit_order": "LSB_first",
                                           "latency_cycles": 1})
    assert _emit(proj).returncode == 0
    assert _emit(proj).returncode == 0
    assert _decl(proj)["latency_cycles"] == 2
    m = dict(SETTLED_METADATA_CONTROL, calibrated_latency=3)
    (proj / MANIFEST).write_text(json.dumps(m))
    assert _emit(proj).returncode == 0
    assert _decl(proj)["latency_cycles"] == 3


def test_an_author_declared_value_is_never_replaced(tmp_path):
    """--set is a declaration; a disagreeing measurement is the gate's FAIL,
    not the emitter's licence to overwrite the author."""
    proj = _project(tmp_path)
    cp = _emit(proj, "--set", "bit_order=LSB_first", "--set",
               "latency_cycles=1")
    assert cp.returncode == 0, cp.stderr
    assert _decl(proj)["latency_cycles"] == 1
    assert _sidecar(proj)["fields"]["latency_cycles"]["provenance"] == \
        "author_declared"
    gcp, report = _gate(proj)
    assert gcp.returncode == 1
    assert report["verdict"] == "FAIL"
    row = report["results"][0]
    assert row["status"] == "FAIL_MEASUREMENT_DISAGREES", row
    assert row["measurement_disagreements"] == [{
        "field": "latency_cycles", "declared": 1, "measured": 2,
        "measured_at": MANIFEST + ":calibrated_latency"}]


# 2. The gate ------------------------------------------------------------------

def test_gate_fails_the_v5c_declaration(tmp_path):
    """The run's own declaration + sidecar + manifest: PASS on main."""
    proj = _project(tmp_path, declaration={
        "bit_order": "LSB_first", "integer_encoding": "unsigned",
        "latency_cycles": 1, "reset_polarity": "active_high",
        "size_param": 32})
    gcp, report = _gate(proj)
    assert gcp.returncode == 1, report
    row = report["results"][0]
    assert row["status"] == "FAIL_MEASUREMENT_DISAGREES", row
    assert "latency_cycles declared 1, measured 2" in row["substance_reason"]


def test_gate_fails_a_contractless_declaration_too(tmp_path):
    """No field table: the arithmetic emitter's path, judged as JSON."""
    contract = ("# L7\n\nThe Plugin MUST produce "
                "`plugin_output/declaration.json` before authoring.\n")
    proj = _project(tmp_path, contract=contract,
                    declaration={"latency_cycles": 1, "size_param": 32})
    gcp, report = _gate(proj)
    assert gcp.returncode == 1, report
    row = report["results"][0]
    assert row["substance_source"] == "JSON"
    assert row["status"] == "FAIL_MEASUREMENT_DISAGREES", row


def test_gate_passes_when_declaration_and_measurement_agree(tmp_path):
    proj = _project(tmp_path, declaration={"bit_order": "LSB_first",
                                           "latency_cycles": 2})
    gcp, report = _gate(proj)
    assert gcp.returncode == 0, report
    assert report["results"][0]["status"] == "PASS"


def test_no_measurement_changes_nothing(tmp_path):
    """No manifest: nothing measured, nothing compared, verdict as before."""
    proj = _project(tmp_path, manifest=None,
                    declaration={"bit_order": "LSB_first", "latency_cycles": 1})
    assert _emit(proj).returncode == 0
    assert _decl(proj)["latency_cycles"] == 1
    gcp, report = _gate(proj)
    assert gcp.returncode == 0, report


def test_declared_copy_in_the_manifest_is_not_a_measurement(tmp_path):
    """A manifest with only `declared_latency` measured nothing."""
    m = {k: v for k, v in V5C_MANIFEST.items()
         if not k.startswith("calibrated_")}
    proj = _project(tmp_path, manifest=m,
                    declaration={"bit_order": "LSB_first", "latency_cycles": 5})
    gcp, report = _gate(proj)
    assert gcp.returncode == 0, report


def test_split_in_out_order_does_not_judge_bit_order(tmp_path):
    """One `bit_order` field cannot state two measured orders."""
    m = dict(SETTLED_METADATA_CONTROL, calibrated_out_bit_order="MSB_first")
    proj = _project(tmp_path, manifest=m,
                    declaration={"bit_order": "MSB_first", "latency_cycles": 2})
    gcp, report = _gate(proj)
    assert gcp.returncode == 0, report


# 3. Round 2 (review wave58) ----------------------------------------------------

DESIGNATED = """# L7

The Plugin MUST declare `plugin_output/declaration.json` before authoring:

| Field | Required | Example |
|---|---|---|
| `bit_order` | Yes | `"LSB_first"` / `"MSB_first"` |
| `latency_cycles` | Yes | `1`(primary)/ `2`(secondary) |
"""


def test_a_spec_designated_latency_is_judged_not_overwritten(tmp_path):
    """Integrity MAJOR (A): the spec designates 1, the RTL does 2, and a
    generator-written file carries 1. The measurement must not launder the
    file to 2 and PASS: the design does not meet its spec."""
    proj = _project(tmp_path, contract=DESIGNATED,
                    declaration={"bit_order": "LSB_first", "latency_cycles": 1})
    assert _emit(proj).returncode == 0
    assert _decl(proj)["latency_cycles"] == 1
    gcp, report = _gate(proj)
    assert gcp.returncode == 1, report
    assert report["results"][0]["status"] == "FAIL_MEASUREMENT_DISAGREES"


def test_a_spec_designation_the_file_does_not_carry_still_fails(tmp_path):
    """Integrity MAJOR (C): the file agrees with the measurement, the spec's
    single designation does not -- verify compares the designation too."""
    proj = _project(tmp_path, contract=DESIGNATED,
                    declaration={"bit_order": "LSB_first", "latency_cycles": 2})
    gcp, report = _gate(proj)
    assert gcp.returncode == 1, report
    diff = report["results"][0]["measurement_disagreements"]
    assert diff and diff[0]["declared_by"].startswith("spec designation")


def test_an_rtl_declared_latency_is_judged_not_overwritten(tmp_path):
    proj = _project(tmp_path, declaration={"bit_order": "LSB_first",
                                           "latency_cycles": 1})
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "// DECLARED CHOICES\n// latency_cycles = 1\nmodule top; endmodule\n")
    assert _emit(proj, "--from-rtl-declaration").returncode == 0
    assert _decl(proj)["latency_cycles"] == 1
    assert _gate(proj)[0].returncode == 1


def test_a_carried_author_declaration_survives_a_runner_rerun(tmp_path):
    """Guard M6: the runner re-runs the emitter WITHOUT --set; the author's
    carried (verified) 1 must stay 1 and keep failing the gate."""
    proj = _project(tmp_path)
    assert _emit(proj, "--set", "bit_order=LSB_first",
                 "--set", "latency_cycles=1").returncode == 0
    assert _emit(proj).returncode == 0
    assert _decl(proj)["latency_cycles"] == 1
    assert _sidecar(proj)["fields"]["latency_cycles"]["provenance"] == \
        "author_declared"
    gcp, report = _gate(proj)
    assert gcp.returncode == 1
    assert report["results"][0]["status"] == "FAIL_MEASUREMENT_DISAGREES"


def test_a_declared_bit_order_the_oracle_measured_otherwise_fails(tmp_path):
    """Guard M8: in/out orders agree (LSB), the file declares MSB."""
    proj = _project(tmp_path, declaration={"bit_order": "MSB_first",
                                           "latency_cycles": 2})
    gcp, report = _gate(proj)
    assert gcp.returncode == 1
    assert [d["field"] for d in
            report["results"][0]["measurement_disagreements"]] == ["bit_order"]


def test_spellings_the_oracle_accepts_are_the_same_framing(tmp_path):
    """`arith_oracle_tb_gen.read_declared_conventions` reads these as the
    measured LSB / 2; the gate must too (no false FAIL)."""
    for i, decl in enumerate(({"bit_order": "LSB-first", "latency_cycles": 2},
                              {"bit_order": "lsb_first", "latency_cycles": 2},
                              {"bit_order": "LSB_first", "latency_cycles": "2"})):
        proj = _project(tmp_path / str(i), declaration=decl)
        gcp, report = _gate(proj)
        assert gcp.returncode == 0, (decl, report["results"][0])


def test_the_generator_declares_the_latency_its_rtl_has():
    """R-0929-SPM-LATENCY: counted on the emitted structure, not restated."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import serial_parallel_mul_synth as spm
    spec = dict(topology="serial_parallel", operator="*", top="t", clk="clk",
                rst="rst", rst_active_low=False, reset_mode="synchronous",
                parallel="x", serial_in="y", serial_out="p",
                size_param="size", size_default=8, size_min=None)
    rtl = spm.emit_rtl(spec)
    assert spm.serial_path_latency(rtl, "y", "p") == 2
    assert spm.plugin_declaration(spec)["latency_cycles"] == 2
    # one more register on the output path is one more cycle
    deeper = rtl.replace("assign p = pr;",
                         "reg q2;\n    always @(posedge clk) q2 <= pr;\n"
                         "    assign p = q2;")
    assert deeper != rtl
    assert spm.serial_path_latency(deeper, "y", "p") == 3
