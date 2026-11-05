"""#3246: port shapes can discover candidates, but cannot bind safety semantics."""
import copy
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import fmeda_fault_injection_coverage as producer
import fmeda_coverage_check as consumer


def _project(tmp_path, rtl):
    rtl_dir = tmp_path / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "neutral.sv").write_text(rtl)
    return rtl_dir


FALSE_PAIR = """module stream_expand(input logic clk_i, rst_n,
  input logic [7:0] seed_i, output logic [15:0] stream_o);
  assign stream_o={seed_i,seed_i}; endmodule
module stream_slice(input logic clk_i,rst_n,
  input logic [15:0] stream_i,output logic [7:0] bytes_o,
  output logic fault_o);
  assign bytes_o=stream_i[7:0]; assign fault_o=1'b0; endmodule
"""

EMBEDDED = """module protocol_endpoint(input logic clk_i,rst_n,
  input logic [4:0] request_i, output logic [3:0] payload_o,
  output logic fault_o);
  function automatic bit encode_tag(input logic [3:0] payload);
    encode_tag=^payload; endfunction
  assign payload_o=request_i[3:0];
  assign fault_o=(encode_tag(request_i[3:0])!=request_i[4]); endmodule
"""


def test_rst_ni_is_never_selected_as_protected_encoder_data():
    # The old component parser knew glued rstni but missed rst_ni.
    assert producer._is_clk_rst("rst_ni") is True
    assert producer._is_clk_rst("reset_n") is True
    assert producer._is_clk_rst("data_in") is False


def test_old_auto_report_cannot_borrow_real_hamming_counts_for_pass():
    # Exact native positive counts: 112 injected, 112 detected, valid baseline,
    # 100% DC versus 99% ASIL-D floor. The only changed fact is the OLD
    # producer's source marker. Its shape-only selection has no binding proof.
    bound = {
        "applicable": True, "measured": True, "asil": "D",
        "injected_faults": 112, "detected_faults": 112,
        "baseline_valid": True, "diagnostic_coverage_pct": 100.0,
        "dc_floor_pct": 99.0, "verdict": "PASS",
        "mechanism": {"source": "explicit"},
    }
    explicit = consumer.check(bound, None, None)
    assert explicit["passed"] is True and explicit["verdict"] == "PASS"
    legacy = copy.deepcopy(bound)
    legacy["mechanism"]["source"] = "auto-detected"
    before_counts = (legacy["injected_faults"], legacy["detected_faults"],
                     legacy["baseline_valid"], legacy["dc_floor_pct"])
    refused = consumer.check(legacy, None, None)
    assert (legacy["injected_faults"], legacy["detected_faults"],
            legacy["baseline_valid"], legacy["dc_floor_pct"]) == before_counts
    assert refused["verdict"] == "NOT_MEASURED"
    assert refused["passed"] is False
    assert refused["recomputed_dc_pct"] is None


def _run(project):
    class Args:
        rtl_dir = "phase2/stage1/rtl"
        doc = None
        enc_module = dec_module = None
        enc_in, enc_out = "data_in", "code_out"
        dec_in, dec_out = "code_in", None
        detect_port = None
        data_width, code_width = 4, 7
        rtl_file = []
        asil = "D"
        min_dc = None
        max_vectors, timeout = 64, 30
    return producer.run(project, Args())


def test_exact_width_reshape_is_unbound_not_measured_ecc(tmp_path):
    rtl_dir = _project(tmp_path, FALSE_PAIR)
    candidate = producer.detect_safety_mechanism(rtl_dir)
    assert candidate.enc_module == "stream_expand"
    assert candidate.dec_module == "stream_slice"
    assert candidate.data_width == 8 and candidate.code_width == 16
    rc, report = _run(tmp_path)
    assert rc != 0
    assert report["applicable"] is True
    assert report["measured"] is False
    assert report["diagnostic_coverage_pct"] is None
    assert report["verdict"] == "NOT_MEASURED"
    assert report["mechanism_binding"] == "UNBOUND"
    assert "mechanism_kind" not in report
    assert report["mechanism_candidate"]["encoder"] == "stream_expand"
    assert consumer.check(report, None, None)["passed"] is False
    assert not (tmp_path / producer.FI_TB_RELPATH).exists()


def test_embedded_parity_is_applicable_unknown_not_na(tmp_path):
    rtl_dir = _project(tmp_path, EMBEDDED)
    candidate = producer.detect_safety_mechanism(rtl_dir)
    assert candidate.dec_module == "protocol_endpoint"
    assert candidate.enc_module is None
    rc, report = _run(tmp_path)
    assert rc != 0
    assert report["applicable"] is True
    assert report["measured"] is False
    assert report["diagnostic_coverage_pct"] is None
    assert report["verdict"] == "NOT_MEASURED"
    assert report["mechanism_binding"] == "UNBOUND"
    assert "mechanism_kind" not in report
    assert report["mechanism_candidate"]["decoder"] == "protocol_endpoint"
    verdict = consumer.check(report, None, None)
    assert verdict["verdict"] == "NOT_MEASURED"
    assert verdict["passed"] is False
    contradiction = dict(report, applicable=False, verdict="NOT_APPLICABLE")
    assert consumer.check(contradiction, None, None)["passed"] is False
    assert not (tmp_path / producer.FI_TB_RELPATH).exists()
