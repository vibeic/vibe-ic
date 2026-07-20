"""Tests for v0.1.67 R22 capture: parity tool nested-shape collapse.

Captured from v0.1.66 loop iter 3 wrap-up: 50 of L3's 51 ABSENT_IN_PROGRAM
findings were nested-children of top-level keys that were entirely absent
from program (burst_type_encodings, response_encodings, lock_encodings,
cache_attribute_encoding_AXI3, etc.). Each missing top-level key was
inflating the count by 3-5 child-flattened ABSENT findings.

R22 collapses: when an entire agent top-level key has no overlap with
program, emit ONE ABSENT_IN_PROGRAM for the top-level key, not N for
each flattened child.

Doctrine: general (works on every doc, no benchmark-specific behaviour),
no cheating (program/agent CONTENT-LEVEL disagreements still surface;
this only collapses the SCHEMA-LEVEL gap to its single root cause).
"""
import importlib
import json
import sys
from pathlib import Path
from _hostpaths import require_repo  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    if "l_doc_parity_diff" in sys.modules:
        del sys.modules["l_doc_parity_diff"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("l_doc_parity_diff")


# ── Single missing top-level key = single ABSENT finding ────────────

def test_one_missing_top_level_dict_becomes_one_absent(tmp_path):
    """Agent has burst_type_encodings.X.Y.Z (3 levels deep); program has
    nothing. R22 emits 1 finding total, not 3+."""
    mod = _load()
    proj = tmp_path / "prog"
    agnt = tmp_path / "agnt"
    proj.mkdir(); agnt.mkdir()
    (proj / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "ic_name": "foo",
    }))
    (agnt / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "burst_type_encodings": {
            "AxBURST[1:0]": {
                "0b00": "FIXED — address is the same for every transfer",
                "0b01": "INCR  — address increments by Number_Bytes",
                "0b10": "WRAP  — like INCR but wraps to a lower address",
            }
        },
    }))
    _stats, findings = mod.diff_all(proj, agnt, source_text=None)
    abs_for_burst = [f for f in findings
                     if f.category == "ABSENT_IN_PROGRAM"
                     and f.key.startswith("burst_type_encodings")]
    assert len(abs_for_burst) == 1, (
        f"R22 collapse failed: expected exactly 1 ABSENT for "
        f"burst_type_encodings; got {len(abs_for_burst)} "
        f"({[f.key for f in abs_for_burst]})")
    assert abs_for_burst[0].key == "burst_type_encodings"


def test_multiple_missing_top_level_keys_each_one_finding(tmp_path):
    """Two missing top-level keys = exactly 2 findings."""
    mod = _load()
    proj = tmp_path / "prog"
    agnt = tmp_path / "agnt"
    proj.mkdir(); agnt.mkdir()
    (proj / "L3_CMD_PROTOCOL.json").write_text(json.dumps({"ic_name": "x"}))
    (agnt / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "burst_type_encodings": {"a": {"b": "1", "c": "2"}},
        "response_encodings": {"x": {"y": "3", "z": "4"}},
    }))
    _stats, findings = mod.diff_all(proj, agnt, source_text=None)
    absent_keys = {f.key for f in findings if f.category == "ABSENT_IN_PROGRAM"}
    assert "burst_type_encodings" in absent_keys
    assert "response_encodings" in absent_keys
    # Each missing top-level emits exactly 1 finding (not flattened)
    assert "burst_type_encodings.a.b" not in absent_keys
    assert "response_encodings.x.y" not in absent_keys


# ── Shared top-level key still expands children correctly ──────────

def test_shared_top_level_key_children_still_diffed(tmp_path):
    """When BOTH program and agent have a top-level key, the diff still
    surfaces missing children at the SHARED-PARENT level — either as
    individual paths OR collapsed into '<sibling-extras>' (v0.1.71 R31).
    Either way, the gap is visible."""
    mod = _load()
    proj = tmp_path / "prog"
    agnt = tmp_path / "agnt"
    proj.mkdir(); agnt.mkdir()
    (proj / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "width_parameters": {"AxLEN_width": {"bits": 8}},
    }))
    (agnt / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "width_parameters": {
            "AxLEN_width": {"AXI3": "4 bits", "AXI4_AXI5": "8 bits"},
            "AxSIZE_width": "3 bits",
        },
    }))
    _stats, findings = mod.diff_all(proj, agnt, source_text=None)
    keys = {f.key for f in findings if f.category == "ABSENT_IN_PROGRAM"}
    # The gap must be visible — either AxSIZE_width directly OR as
    # part of width_parameters.<sibling-extras> collapse.
    surfaced = ("width_parameters.AxSIZE_width" in keys
                or "width_parameters.<sibling-extras>" in keys
                or any("sibling-extras" in k for k in keys))
    assert surfaced, (
        f"Shared top-level key children must still surface as ABSENT; "
        f"got {keys}")


# ── Anti-cheating: hallucinations + content mismatches still flagged ─

def test_hallucinations_still_counted_under_r22(tmp_path):
    """R22 only changes ABSENT counting. HALLUCINATED detection runs on
    its own catalog and must NOT be affected."""
    mod = _load()
    proj = tmp_path / "prog"
    agnt = tmp_path / "agnt"
    proj.mkdir(); agnt.mkdir()
    (proj / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "SUCH ARM TECHNOLOGY",  # hallucination heuristic
    }))
    (agnt / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "AMBA AXI Protocol Specification",
    }))
    # Source text doesn't contain SUCH ARM TECHNOLOGY (test environment)
    _stats, findings = mod.diff_all(proj, agnt, source_text="some unrelated text")
    halluc = [f for f in findings if f.category == "HALLUCINATED"]
    assert len(halluc) >= 1, (
        f"R22 must not suppress HALLUCINATED; got {[(f.category, f.key) for f in findings]}")


def test_real_amba_axi_total_drops_under_r22(tmp_path):
    """End-to-end: R22 must drop the AMBA AXI parity TOTAL meaningfully
    from the v0.1.66 baseline of 339."""
    arm_prog = require_repo("benchmark-data/evaluation/phase1_parity/"
                            "arm_aix/phase1/generated_docs")
    arm_agnt = require_repo("benchmark-data/evaluation/phase1_parity/"
                            "arm_aix/phase1/claude_extracted")
    if not arm_prog.is_dir() or not arm_agnt.is_dir():
        import pytest
        pytest.skip("AMBA AXI benchmark not present on this host")
    mod = _load()
    _stats, findings = mod.diff_all(arm_prog, arm_agnt, source_text=None)
    total = len(findings)
    assert total < 339, (
        f"R22 nested-collapse failed to reduce total findings on AMBA AXI; "
        f"got {total} vs v0.1.66 baseline 339.")


def test_r22_why_string_distinguishes_collapsed_findings():
    """R22-collapsed findings carry a 'why' string that mentions the
    collapse so a downstream consumer can tell them from regular ABSENT."""
    mod = _load()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "prog").mkdir()
        (td / "agnt").mkdir()
        (td / "prog" / "L1_DATASHEET.json").write_text(json.dumps({"a": 1}))
        (td / "agnt" / "L1_DATASHEET.json").write_text(json.dumps(
            {"missing_top": {"sub": "val"}}))
        _stats, findings = mod.diff_all(td / "prog", td / "agnt", source_text=None)
        collapsed = [f for f in findings
                     if f.category == "ABSENT_IN_PROGRAM"
                     and f.key == "missing_top"]
        assert len(collapsed) == 1
        assert ("R22 collapse" in collapsed[0].why
            or "sibling-extras" in collapsed[0].why
            or "did not" in collapsed[0].why)
