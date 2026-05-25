"""Tests for input_docs_coverage_check.py (v0.50).

Covers: all-covered pass, missing-doc fail, manifest-only coverage, layer-only
coverage, mixed coverage.
"""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "input_docs_coverage_check.py"


def _setup(tmp: Path, doc_names, layers: dict = None, manifest_text: str = None):
    (tmp / "input" / "docs").mkdir(parents=True)
    for n in doc_names:
        (tmp / "input" / "docs" / n).write_text("dummy")
    (tmp / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    for name, obj in (layers or {}).items():
        (tmp / "phase1" / "generated_docs" / f"{name}.json").write_text(json.dumps(obj))
    if manifest_text is not None:
        (tmp / "input_docs_coverage.md").write_text(manifest_text)


def _run(tmp: Path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp)],
        capture_output=True, text=True,
    )
    try:
        return r.returncode, json.loads(r.stdout)
    except json.JSONDecodeError:
        return r.returncode, {"_raw": r.stdout, "_err": r.stderr}


def test_all_covered_via_layers_passes(tmp_path):
    _setup(tmp_path,
           doc_names=["spec.pdf", "registers.xlsx"],
           layers={
               "L1_DATASHEET": {"provenance": {"sources": ["input/docs/spec.pdf"]}},
               "L4_REGMAP":    {"provenance": {"sources": ["input/docs/registers.xlsx"]}},
           })
    code, out = _run(tmp_path)
    assert out.get("pass") is True, out
    assert code == 0


def test_one_doc_missing_fails(tmp_path):
    _setup(tmp_path,
           doc_names=["spec.pdf", "registers.xlsx"],
           layers={"L1_DATASHEET": {"provenance": {"sources": ["input/docs/spec.pdf"]}}})
    code, out = _run(tmp_path)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "input_doc_coverage" in rules
    missing = [f["doc"] for f in out["findings"]]
    assert "registers.xlsx" in missing


def test_manifest_md_only_passes(tmp_path):
    _setup(tmp_path,
           doc_names=["timing.txt"],
           layers={},
           manifest_text="# Coverage\n- timing.txt → pulse widths, verified by rx_phy tb")
    code, out = _run(tmp_path)
    assert out.get("pass") is True, out


def test_stem_match_works(tmp_path):
    """Doc name 'CMD_protocol.xlsx' cited only as 'CMD_protocol' should match."""
    _setup(tmp_path,
           doc_names=["CMD_protocol.xlsx"],
           layers={"L3_CMD_PROTOCOL": {"derived_from": "CMD_protocol table"}})
    code, out = _run(tmp_path)
    assert out.get("pass") is True, out


def test_empty_docs_dir_fails(tmp_path):
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    code, out = _run(tmp_path)
    assert out.get("pass") is False
    assert "no files found" in out.get("error", "")


def test_weak_contribution_phrase_warns(tmp_path):
    """v0.50.1 — 'reviewed for context' phrase must be flagged even if doc
    is technically cited in the coverage manifest."""
    _setup(tmp_path,
           doc_names=["measure_timing.pptx"],
           layers={},
           manifest_text=(
               "| measure_timing.pptx | Measurement sequence diagrams. "
               "Reviewed for context; did not contribute RTL constants. |"
           ))
    code, out = _run(tmp_path)
    # coverage is satisfied (filename in manifest), but WARN must fire
    rules = [f["rule"] for f in out.get("findings", [])]
    assert "weak_contribution_claim" in rules


def test_detailed_contribution_passes(tmp_path):
    """A proper per-item contribution description must NOT trigger the WARN."""
    _setup(tmp_path,
           doc_names=["timing.pptx"],
           layers={},
           manifest_text=(
               "| timing.pptx | Slide 2 table: IBT=22.7us, RSP_Time=22.7us, "
               "BR range 9.4-18.4us. | rtl/as3616_params.vh CYC_IBT=91 |"
           ))
    code, out = _run(tmp_path)
    rules = [f["rule"] for f in out.get("findings", [])]
    assert "weak_contribution_claim" not in rules
