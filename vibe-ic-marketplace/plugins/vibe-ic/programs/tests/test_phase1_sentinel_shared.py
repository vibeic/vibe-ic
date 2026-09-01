"""Tests for v0.62 Bug #3 + Bug #4 fixes.

Bug #3 (apb-peripheral inheritance): apb-peripheral was forced to fill
serial-protocol fields (frame_format, aid_bit_timing, ...) because it
inherited from protocol-ic. Fix: re-parented under digital-ic directly.

Bug #4 (sentinel inconsistency): `protocol_present:false` was honored by
phase1_doc_presence_check but not by phase1_consistency_check's
R_clock_freq_positive / R_layer_documents_present. Fix: extract sentinel
logic into shared `_phase1_sentinel.py` module; both gates query it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROG_DIR))

import _phase1_sentinel as ps  # noqa: E402
import phase1_doc_presence_check as dpc  # noqa: E402
import phase1_consistency_check as cc  # noqa: E402


# ---------------------------------------------------------------------------
# Bug #4 — shared module API
# ---------------------------------------------------------------------------
def test_shared_module_exports_constants():
    """SENTINEL_OPTIONAL_LAYERS frozen at the documented set."""
    assert ps.SENTINEL_OPTIONAL_LAYERS == frozenset({"L3", "L8R"})


def test_dir_form_returns_false_when_no_sentinel(tmp_path):
    (tmp_path / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "X"}))
    assert ps.is_no_protocol_sentinel_active_in_dir(tmp_path) is False


def test_dir_form_returns_true_when_l3_declares_sentinel(tmp_path):
    (tmp_path / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "protocol_present": False, "reason": "memory-mapped",
    }))
    assert ps.is_no_protocol_sentinel_active_in_dir(tmp_path) is True


def test_dir_form_returns_true_when_l1_declares_sentinel(tmp_path):
    (tmp_path / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "X", "protocol_present": False,
    }))
    assert ps.is_no_protocol_sentinel_active_in_dir(tmp_path) is True


def test_dir_form_handles_malformed_json(tmp_path):
    (tmp_path / "L1_DATASHEET.json").write_text("not json {{")
    # Should treat as no sentinel rather than crash
    assert ps.is_no_protocol_sentinel_active_in_dir(tmp_path) is False


def test_docs_form_mirrors_dir_form():
    """In-memory dict form returns same answer as filesystem form."""
    assert ps.is_no_protocol_sentinel_active_in_docs({}) is False
    assert ps.is_no_protocol_sentinel_active_in_docs({
        "L1": {"ic_name": "X"},
    }) is False
    assert ps.is_no_protocol_sentinel_active_in_docs({
        "L1": {"ic_name": "X", "protocol_present": False},
    }) is True
    assert ps.is_no_protocol_sentinel_active_in_docs({
        "L3": {"protocol_present": False},
    }) is True


# ---------------------------------------------------------------------------
# Bug #4 — both gates honour sentinel via shared module
# ---------------------------------------------------------------------------
def _seed_no_protocol_docs(d: Path) -> None:
    """Write a minimal 8-layer set + sentinel; deliberately skip L3 + L8R."""
    files = {
        "L1_DATASHEET.json": {
            "ic_name": "MEM_X",
            "protocol_present": False,
            "reason": "memory-mapped, register-pointer access only",
        },
        "L2_FRS.json": {"requirements": ["x"]},
        "L4_REGMAP.json": {"register_map": [{"name": "CTRL"}]},
        "L5_ADI_SPEC.json": {"signals": []},
        "L6_CONTROL_LOGIC.json": {"submodule_control_logic": {"core": {}}},
        "L7_TEST_DEBUG.json": {"test_modes": [{"name": "BIST"}]},
        "L8_TIMING_WAVEFORM.json": {"reset_timing": {"por_to_clk_valid_us": 1}},
        "L9_INTEGRATION_SPEC.json": {
            "dtop_top_level": {"name": "mem_x_top"},
            "submodules": [{"name": "mem_x_core"}],
            "instantiation_order": ["u_mem_x_core (MEM_X_CORE)"],
        },
    }
    for fname, body in files.items():
        (d / fname).write_text(json.dumps(body))


def test_doc_presence_passes_with_sentinel_skipping_l3_l8r(tmp_path):
    _seed_no_protocol_docs(tmp_path)
    findings = dpc.check(tmp_path)
    errors = [f for f in findings if f.severity == "error"]
    assert errors == [], f"unexpected errors: {[(f.rule, f.message) for f in errors]}"


def test_consistency_no_longer_false_fails_clock_freq_when_sentinel_active(tmp_path):
    """Bug #4 regression: R_clock_freq_positive used to FAIL with
    'value was None' on no-protocol ICs because L8R was absent.
    With shared sentinel, it skips with 'info'."""
    _seed_no_protocol_docs(tmp_path)
    docs = cc.load_docs(tmp_path)
    findings = cc.evaluate(docs, cc.RULES)
    clock_findings = [f for f in findings if f.rule_id == "R_clock_freq_positive"]
    assert len(clock_findings) == 1
    f = clock_findings[0]
    assert f.passed, (
        f"R_clock_freq_positive should skip cleanly on no-protocol IC, "
        f"got passed={f.passed}, detail={f.detail!r}"
    )
    assert "sentinel" in f.detail.lower()


def test_consistency_no_longer_false_fails_layers_present_when_sentinel_active(tmp_path):
    """Bug #4 regression: R_layer_documents_present used to report L3/L8R
    as missing on no-protocol ICs."""
    _seed_no_protocol_docs(tmp_path)
    docs = cc.load_docs(tmp_path)
    findings = cc.evaluate(docs, cc.RULES)
    layers_findings = [f for f in findings if f.rule_id == "R_layer_documents_present"]
    assert len(layers_findings) == 1
    f = layers_findings[0]
    assert f.passed, (
        f"R_layer_documents_present should pass when only L3/L8R missing "
        f"AND sentinel active, got detail={f.detail!r}"
    )


def test_consistency_still_fails_on_genuinely_missing_layers(tmp_path):
    """Defensive: sentinel only exempts L3/L8R. Missing L1/L2/L4 still FAIL."""
    # Write only L3 sentinel + L1 — every other layer absent
    (tmp_path / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "X"}))
    (tmp_path / "L3_CMD_PROTOCOL.json").write_text(json.dumps({"protocol_present": False}))
    docs = cc.load_docs(tmp_path)
    findings = cc.evaluate(docs, cc.RULES)
    layers_findings = [f for f in findings if f.rule_id == "R_layer_documents_present"]
    assert len(layers_findings) == 1
    assert not layers_findings[0].passed
    # The detail should NOT mention L3 or L8R as missing
    assert "L3" not in layers_findings[0].detail
    assert "L8R" not in layers_findings[0].detail
    # But L2/L4/etc SHOULD be flagged
    assert "L2" in layers_findings[0].detail


def test_consistency_without_sentinel_still_fails_clock_freq_when_l8r_missing(tmp_path):
    """Defensive: without sentinel, R_clock_freq_positive must still FAIL
    when L8R.clock_frequency_hz absent (legacy protocol-IC behavior)."""
    # Write 9 layers but no sentinel + no L8R clock_freq
    files = {
        "L1_DATASHEET.json": {"ic_name": "X"},  # no protocol_present
        "L2_FRS.json": {"requirements": ["x"]},
        "L3_CMD_PROTOCOL.json": {"commands": []},
        "L4_REGMAP.json": {"register_map": []},
        "L5_ADI_SPEC.json": {"signals": []},
        "L6_CONTROL_LOGIC.json": {"submodule_control_logic": {}},
        "L7_TEST_DEBUG.json": {"test_modes": []},
        "L8_TIMING_WAVEFORM.json": {},
        "L8_RTL_CONSTANTS.json": {},  # missing clock_frequency_hz
        "L9_INTEGRATION_SPEC.json": {},
    }
    for fname, body in files.items():
        (tmp_path / fname).write_text(json.dumps(body))
    docs = cc.load_docs(tmp_path)
    findings = cc.evaluate(docs, cc.RULES)
    clock_findings = [f for f in findings if f.rule_id == "R_clock_freq_positive"]
    assert len(clock_findings) == 1
    assert not clock_findings[0].passed, (
        "R_clock_freq_positive MUST still fail when L8R is present but "
        "clock_frequency_hz missing AND no sentinel — that's a real bug"
    )


def test_consistency_accepts_current_l8r_clock_schema(tmp_path):
    """The current producer emits clock_mhz + clock_domains, not the retired
    top-level clock_frequency_hz field."""
    _seed_no_protocol_docs(tmp_path)
    (tmp_path / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "protocol_present": True, "commands": [{"name": "sample"}],
    }))
    (tmp_path / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_mhz": 1,
        "clock_domains": [{"name": "clk", "freq_hz": 1_000_000}],
    }))
    findings = cc.evaluate(cc.load_docs(tmp_path), cc.RULES)
    clock = [f for f in findings if f.rule_id == "R_clock_freq_positive"]
    assert len(clock) == 1
    assert clock[0].passed, clock[0].detail


def test_consistency_rejects_nonpositive_current_l8r_clock_schema(tmp_path):
    _seed_no_protocol_docs(tmp_path)
    (tmp_path / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "protocol_present": True, "commands": [{"name": "sample"}],
    }))
    (tmp_path / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_mhz": 0,
        "clock_domains": [{"name": "clk", "freq_hz": 0}],
    }))
    findings = cc.evaluate(cc.load_docs(tmp_path), cc.RULES)
    clock = [f for f in findings if f.rule_id == "R_clock_freq_positive"]
    assert len(clock) == 1
    assert not clock[0].passed


# ---------------------------------------------------------------------------
# Bug #3 — apb-peripheral class chain no longer inherits protocol-ic
# ---------------------------------------------------------------------------
def test_apb_peripheral_chain_excludes_protocol_ic():
    """v0.62: apb-peripheral re-parented from protocol-ic to digital-ic."""
    # flow #486: tools.phase1_engine + agents/class_kb are SHIPPED in-plugin
    # resources; resolve them via the plugin-root resolver (works on both
    # the source monorepo and the flattened install cache).
    from _plugin_tree import plugin_root, plugin_path
    sys.path.insert(0, str(plugin_root()))
    from tools.phase1_engine.gap_detect import _parent_chain, _load_yaml

    KB = plugin_path("agents", "class_kb")
    tree = _load_yaml(KB / "class-tree.yaml")
    chain = _parent_chain("apb-peripheral", tree)
    assert "protocol-ic" not in chain, (
        f"apb-peripheral must NOT inherit protocol-ic; chain: {chain}"
    )
    assert "digital-ic" in chain, (
        f"apb-peripheral should still inherit digital-ic; chain: {chain}"
    )
    assert "any-ic" in chain  # root


def test_apb_peripheral_no_longer_requires_serial_protocol_facts():
    """Most concrete consequence of Bug #3 fix: apb-peripheral requires
    no L3/L8 serial-protocol fields."""
    from _plugin_tree import plugin_root, plugin_path
    sys.path.insert(0, str(plugin_root()))
    from tools.phase1_engine.gap_detect import (
        _parent_chain, _aggregate_required_facts, _load_yaml,
    )

    KB = plugin_path("agents", "class_kb")
    tree = _load_yaml(KB / "class-tree.yaml")
    chain = _parent_chain("apb-peripheral", tree)
    required = _aggregate_required_facts(chain, KB / "templates")

    serial_only_paths = {
        "frame_format.start_bit",
        "frame_format.crc",
        "frame_format.bit_encoding",
        "command_set",
        "aid_bit_timing",
        "wake_timing",
        "response_timing",
        "bit_period_cycles",
        "crc8_polynomial",
        "crc8_init",
    }
    actual_paths = {
        e.get("path")
        for layer_entries in required.values()
        for e in layer_entries
        if e.get("required")
    }
    leaked = actual_paths & serial_only_paths
    assert not leaked, (
        f"apb-peripheral leaks serial-protocol-only required facts: {leaked}"
    )


def test_uart_peripheral_still_inherits_protocol_ic():
    """Defensive: Bug #3 fix only detached APB; uart-peripheral is a
    genuine serial framed protocol and MUST keep inheriting protocol-ic."""
    from _plugin_tree import plugin_root, plugin_path
    sys.path.insert(0, str(plugin_root()))
    from tools.phase1_engine.gap_detect import _parent_chain, _load_yaml

    KB = plugin_path("agents", "class_kb")
    tree = _load_yaml(KB / "class-tree.yaml")
    chain = _parent_chain("uart-peripheral", tree)
    assert "protocol-ic" in chain, (
        f"uart-peripheral should still inherit protocol-ic; chain: {chain}"
    )
