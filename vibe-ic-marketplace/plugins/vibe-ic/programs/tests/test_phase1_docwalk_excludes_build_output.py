"""Regression: the phase1 doc-walker must NOT scoop downstream build output.

A full doc->GDS run leaves phase2/ (RTL + reports) and phase3/ (stage4/
foundry_handoff/README, GDS, DEF/LEF) under the project root. The README rglob
fallback in extract_text_pipeline (depth<=4) used to ingest those READMEs and
cite them in L1, which the RTL-as-oracle leak guard then correctly FAILed at
[14b/15] — halting phase1 BEFORE the [14e2b] auto-dispatch on any benchmark
that had previously been taken to GDS (observed v0.2.14 on the 6 new protocols).
phase1 reads INPUT docs only; build-output dirs are now skip-segments.
"""
import importlib

mod = importlib.import_module("phase1_doc_one_shot_runner")


def _project(tmp_path):
    # Exactly ONE input doc -> len(out)<2 -> the README rglob fallback fires
    # (this is the protocol-benchmark shape that hit the leak).
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "spec.md").write_text(
        "# Protocol specification\nSignal MDC, register PHYAD, 2.5 MHz.\n")
    # Downstream build output that must NOT be re-ingested by phase1:
    fh = tmp_path / "phase3" / "stage4" / "foundry_handoff"
    fh.mkdir(parents=True)
    (fh / "README.txt").write_text(
        "Foundry handoff: chip_top.gds, DEF, LEF. module chip_top(input clk);\n")
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "README.md").write_text("RTL notes: always @(posedge clk) q <= d;\n")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "README.md").write_text("report index readme\n")
    return tmp_path


def test_docwalk_excludes_build_output(tmp_path):
    out = mod.extract_text_pipeline(_project(tmp_path), force=True)
    leaked = [k for k in out
              if any(seg in k for seg in
                     ("phase3", "phase2", "reports", "extracted_docs"))]
    assert not leaked, f"phase1 doc-walker scooped build output: {leaked}"


def test_docwalk_still_ingests_the_real_input_doc(tmp_path):
    # The fix must not suppress the genuine input spec.
    out = mod.extract_text_pipeline(_project(tmp_path), force=True)
    assert any("spec" in k.lower() for k in out), \
        f"real input spec was dropped; keys={list(out)}"
