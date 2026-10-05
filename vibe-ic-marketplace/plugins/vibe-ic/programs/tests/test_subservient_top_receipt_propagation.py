"""Focused Phase-2 supplied-top propagation controls."""
import hashlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as R  # noqa: E402


def _project(tmp_path, top="subservient"):
    project = tmp_path / "p"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / f"{top}.v").write_text(f"module {top}(input clk, output q); assign q = clk; endmodule\n")
    # An unrelated root makes structural guessing ambiguous; the producer
    # receipt is the only source-backed way to select the supplied top.
    (rtl / "unrelated.v").write_text("module unrelated(input a, output b); assign b = a; endmodule\n")
    top_path = rtl / f"{top}.v"
    top_hash = hashlib.sha256(top_path.read_bytes()).hexdigest()
    out = project / "plugin_output"
    out.mkdir()
    (out / "declaration.json").write_text(json.dumps({
        "supplied_rtl": {
            "source": "phase2/stage1/rtl/SOURCE_MANIFEST.json",
            "files": [{
                "input": f"input/{top}.v",
                "staged": f"phase2/stage1/rtl/{top}.v",
                "status": "staged",
                "staged_sha256": top_hash,
            }],
            "top": {
                "value": top,
                "defined_in": f"phase2/stage1/rtl/{top}.v",
            },
        }
    }))
    return project


def test_supplied_top_receipt_reaches_phase2_synth_request(tmp_path):
    assert R._phase2_synth_top(_project(tmp_path), "chip_top") == "subservient"


def test_existing_chip_top_name_remains_authoritative(tmp_path):
    project = _project(tmp_path)
    rtl = project / "phase2" / "stage1" / "rtl"
    (rtl / "chip_top.v").write_text("module chip_top(input clk, output q); assign q = clk; endmodule\n")
    assert R._phase2_synth_top(project, "chip_top") == "chip_top"


def test_missing_or_stale_declared_top_fails_closed(tmp_path, monkeypatch):
    project = _project(tmp_path)
    (project / "plugin_output" / "declaration.json").write_text(json.dumps({
        "supplied_rtl": {"top": {"value": "chip_top"}}
    }))
    assert R._phase2_synth_top(project, "chip_top") == "chip_top"

    seen = {}
    def fake_run(argv, **kwargs):
        seen["script"] = argv[2]
        return 1, "", "ERROR: chip_top is not a valid top-level module"
    monkeypatch.setattr(R, "_run", fake_run)
    row = R.step_yosys_synth(project, "chip_top", container="missing")
    assert row.status == "FAIL"
    assert "synth -top chip_top" in seen["script"]


def test_disagreeing_staged_declarations_fail_closed(tmp_path):
    project = _project(tmp_path)
    rtl = project / "phase2" / "stage1" / "rtl"
    (rtl / "other_top.v").write_text(
        "module other_top(input clk, output q); assign q = clk; endmodule\n")
    l9 = project / "phase1" / "generated_docs"
    l9.mkdir(parents=True)
    (l9 / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "other_top"}))
    assert R._phase2_synth_top(project, "chip_top") == "chip_top"


def test_changed_staged_source_invalidates_receipt(tmp_path):
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "subservient.v").write_text(
        "module subservient(input clk, output q); assign q = ~clk; endmodule\n")
    assert R._phase2_synth_top(project, "chip_top") == "chip_top"
