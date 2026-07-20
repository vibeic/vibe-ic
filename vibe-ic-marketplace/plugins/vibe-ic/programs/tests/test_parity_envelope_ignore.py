"""Tests for v0.1.64 R18 capture: l_doc_parity_diff envelope-ignore.

Captured from the recurring 'parity tool over-counts' theme in parity
review. The diff treats every top-level
key in the agent that isn't in the program as ABSENT — including wrapper
metadata (doc_id, fields, evidence, extraction_source on Claude's side;
extraction_evidence, extraction_strategy, schema_version on the program
side). These wrapper keys describe HOW the doc was emitted, not WHAT was
extracted, so counting them inflates the gap.

The R18 envelope-ignore set excludes 20 well-known wrapper keys from the
ABSENT / VALUE_MISMATCH / SHAPE_MISMATCH counters. Substantive content
keys are unaffected.

Doctrine: general (no benchmark-specific keys), no cheating (hallucinations
still counted; structural-content mismatches still counted).
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


# ── Filter helper ───────────────────────────────────────────────────

def test_is_envelope_key_recognises_program_side_wrappers():
    mod = _load()
    for k in ("schema_version", "doc_class", "emitted_by",
                "extraction_evidence", "extraction_strategy",
                "vendor_short_literals"):
        assert mod._is_envelope_key(k), (
            f"{k!r} is a program-side wrapper; must be ignored.")


def test_is_envelope_key_recognises_agent_side_wrappers():
    mod = _load()
    # NOTE: 'fields' is NOT in this list — it's a content wrapper handled
    # by _unwrap_fields normalisation, not by the envelope-ignore filter.
    for k in ("doc_id", "doc_name", "extraction_source",
                "evidence", "extraction_method"):
        assert mod._is_envelope_key(k), (
            f"{k!r} is an agent-side wrapper; must be ignored.")


def test_is_envelope_key_recognises_applicability_metadata():
    mod = _load()
    for k in ("applicability", "ic_class", "rationale", "extraction_status",
                "extraction_hints"):
        assert mod._is_envelope_key(k), (
            f"{k!r} is applicability metadata (R13 gate / na_stub envelope); "
            f"must be ignored.")


def test_is_envelope_key_preserves_substantive_keys():
    """ANTI-FALSE-POSITIVE: real content keys must NOT be ignored."""
    mod = _load()
    for k in ("ic_name", "pin_table", "opcodes", "burst_type",
                "channels", "compliance_requirements",
                "fmax_mhz", "protocol_overview",
                "interconnect", "channel_signal_catalog"):
        assert not mod._is_envelope_key(k), (
            f"{k!r} is substantive content; must NOT be ignored.")


def test_envelope_key_handles_nested_paths():
    """Nested paths like 'extraction_evidence.title' must also be filtered
    (the top-level token is what matters)."""
    mod = _load()
    assert mod._is_envelope_key("extraction_evidence.title")
    assert mod._is_envelope_key("doc_id")
    assert mod._is_envelope_key("evidence[0]")
    assert mod._is_envelope_key("evidence[2].source")
    # 'fields' is NOT in the ignored set — it's the agent's substantive-
    # content wrapper. _unwrap_fields() handles it by lifting its
    # children up to top-level before the diff.
    assert not mod._is_envelope_key("fields")
    assert not mod._is_envelope_key("pin_table[0].name")


# ── _unwrap_fields normalisation ─────────────────────────────────────

def test_unwrap_fields_lifts_substantive_content():
    """Claude wraps content under .fields.*; unwrap lifts it up."""
    mod = _load()
    d = {"doc_id": "L1", "fields": {"ic_name": "AMBA AXI",
                                       "pin_table": [{"name": "AWVALID"}]}}
    out = mod._unwrap_fields(d)
    assert out["ic_name"] == "AMBA AXI"
    assert out["pin_table"] == [{"name": "AWVALID"}]
    assert "fields" not in out


def test_unwrap_fields_preserves_sibling_top_level_keys():
    """Agent often has 'notes' or 'evidence' at the SAME level as 'fields' —
    those must survive the unwrap."""
    mod = _load()
    d = {"doc_id": "L4", "fields": {"register_map_present": False},
         "notes": "stub note"}
    out = mod._unwrap_fields(d)
    assert out["register_map_present"] is False
    assert out["notes"] == "stub note"


def test_unwrap_fields_is_idempotent_on_program_schema():
    """The program never wraps under 'fields' — unwrap must be a no-op."""
    mod = _load()
    d = {"ic_name": "UNKNOWN_IC", "pin_table": [{"name": "AWVALID"}]}
    out = mod._unwrap_fields(d)
    assert out == d


def test_unwrap_fields_handles_non_dict_fields_value():
    """If 'fields' is a list or scalar (schema drift), don't crash."""
    mod = _load()
    for bad in (None, [], "string", 42):
        d = {"doc_id": "L1", "fields": bad, "x": 1}
        out = mod._unwrap_fields(d)
        assert out["x"] == 1


# ── End-to-end: ABSENT count drops vs pre-R18 baseline ────────────────

def test_absent_count_drops_on_real_amba_axi_diff(tmp_path):
    """Re-run l_doc_parity_diff on the real AMBA AXI program + agent
    extractions and confirm ABSENT_IN_PROGRAM is materially lower than the
    v0.1.63 pre-R18 baseline of 361."""
    arm_prog = require_repo("benchmark-data/evaluation/phase1_parity/"
                            "arm_aix/phase1/generated_docs")
    arm_agnt = require_repo("benchmark-data/evaluation/phase1_parity/"
                            "arm_aix/phase1/claude_extracted")
    if not arm_prog.is_dir() or not arm_agnt.is_dir():
        import pytest
        pytest.skip("AMBA AXI benchmark not present on this host")
    mod = _load()
    stats, findings = mod.diff_all(arm_prog, arm_agnt, source_text=None)
    cats = {}
    for f in findings:
        cats[f.category] = cats.get(f.category, 0) + 1
    # The pre-R18 baseline was 361 ABSENT on v0.1.63. R18 must drop this
    # measurably (every L doc loses ~3-6 envelope-key ABSENT findings).
    assert cats.get("ABSENT_IN_PROGRAM", 0) < 361, (
        f"R18 envelope-ignore failed to reduce ABSENT count; got "
        f"{cats.get('ABSENT_IN_PROGRAM', 0)} vs pre-R18 baseline 361. "
        f"Full breakdown: {cats}")


def test_substantive_findings_preserved(tmp_path):
    """Hallucinated content (Cat HALLUCINATED) must still be counted —
    R18 only filters wrapper-metadata keys, not real content discrepancies."""
    mod = _load()
    # Build a synthetic project where program emits a hallucinated ic_name
    # and the substantive key 'pin_table' is missing from program but
    # present in agent.
    proj = tmp_path / "prog"
    agnt = tmp_path / "agnt"
    proj.mkdir(); agnt.mkdir()
    (proj / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "SUCH ARM TECHNOLOGY",
        "doc_class": "L1",  # envelope — ignored
        "extraction_strategy": {"foo": "bar"},  # envelope — ignored
    }))
    (agnt / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "AMBA AXI Protocol",  # value mismatch
        "pin_table": [{"name": "AWVALID"}],  # absent
        "doc_id": "L1",  # envelope — ignored
        "extraction_source": "PDF",  # envelope — ignored
    }))
    stats, findings = mod.diff_all(proj, agnt, source_text=None)
    cats = {f.category: cats_get(cats, f.category) + 1 for cats, f in
             ((d, f) for f in findings for d in [{}])}
    # Reconstruct more carefully
    from collections import Counter
    cnt = Counter(f.category for f in findings)
    assert cnt.get("ABSENT_IN_PROGRAM", 0) >= 1, (
        f"pin_table must surface as ABSENT despite R18; got {dict(cnt)}")
    # Wrapper keys must NOT inflate the count
    for f in findings:
        if f.category in ("ABSENT_IN_PROGRAM", "VALUE_MISMATCH"):
            assert not mod._is_envelope_key(f.key), (
                f"R18 leaked an envelope key into findings: {f}")


def cats_get(d, k):  # silly placeholder so the dict-comp parses
    return d.get(k, 0)
