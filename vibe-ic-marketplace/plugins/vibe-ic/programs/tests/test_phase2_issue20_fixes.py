"""tests/test_phase2_issue20_fixes.py — v1.6.88

Closes issue #20 — 4 blockers from #19 partial close:
- Bug 2 (P0): alias-group canonicalization (bus_oe/bus_tx/bus_rx → id_bus)
- Bug 4 (P0): L8 typed clock_domains[] block
- Bug 3 (P0): step_full_stack_tb_gen emits tb_<top>_full.v
- Bug 1 (P1): clock harvester rejects sub-kHz + requires clock-keyword

All fixes are chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
for _p in (str(PROGRAMS), str(PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Bug 2 (P0 BLOCKER) — alias-group canonicalisation
# ---------------------------------------------------------------------------

def test_coalesce_drops_bus_oe_tx_rx_when_id_bus_present():
    """Direct unit test: when canonical id_bus is present alongside
    bus_oe / bus_tx / bus_rx, the decomposition must be dropped."""
    from programs.phase1_one_shot_runner import (
        _coalesce_half_duplex_alias_group,
    )
    ports = [
        {"name": "id_bus",  "direction": "inout"},
        {"name": "bus_oe",  "direction": "output"},
        {"name": "bus_tx",  "direction": "output"},
        {"name": "bus_rx",  "direction": "input"},
        {"name": "clk",     "direction": "input"},
    ]
    out = _coalesce_half_duplex_alias_group(ports)
    names = {p["name"] for p in out}
    assert "id_bus" in names, "canonical id_bus must be kept"
    assert "clk" in names, "unrelated port must be kept"
    for forbidden in ("bus_oe", "bus_tx", "bus_rx"):
        assert forbidden not in names, (
            f"alias-group decomposition leaked: {forbidden}"
        )


def test_coalesce_drops_prefixed_decomposition():
    """Prefixed forms (id_bus_oe / aid_bus_tx) must also be dropped
    when the canonical is present."""
    from programs.phase1_one_shot_runner import (
        _coalesce_half_duplex_alias_group,
    )
    ports = [
        {"name": "id_bus",     "direction": "inout"},
        {"name": "id_bus_oe",  "direction": "output"},
        {"name": "id_bus_tx",  "direction": "output"},
        {"name": "id_bus_rx",  "direction": "input"},
    ]
    out = _coalesce_half_duplex_alias_group(ports)
    names = {p["name"] for p in out}
    assert names == {"id_bus"}, (
        f"prefixed decomposition should be dropped, got {names}"
    )


def test_coalesce_keeps_decomposition_when_no_canonical_present():
    """Reject-test: if only bus_oe/bus_tx/bus_rx exist and there's no
    canonical bus port, the decomposition must be KEPT (some designs
    legitimately expose only the discrete tri-state pins)."""
    from programs.phase1_one_shot_runner import (
        _coalesce_half_duplex_alias_group,
    )
    ports = [
        {"name": "bus_oe", "direction": "output"},
        {"name": "bus_tx", "direction": "output"},
        {"name": "clk",    "direction": "input"},
    ]
    out = _coalesce_half_duplex_alias_group(ports)
    names = {p["name"] for p in out}
    assert names == {"bus_oe", "bus_tx", "clk"}, (
        f"no canonical → decomposition should survive; got {names}"
    )


def test_l9_emitter_collapses_bus_oe_alias_group(tmp_path):
    """Integration test: when L1.pin_table extraction surfaces both
    id_bus AND its tri-state decomposition, the L9 emitter must drop
    the decomposition end-to-end."""
    from programs.phase1_one_shot_runner import (
        gen_l1_datasheet,
        gen_l9_integration_spec,
    )
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    extracted = {
        "pinout_datasheet.txt": (
            "EXAMPLE_CHIP single-wire EXAMPLE_PROTOCOL-class IC.\n"
            "PIN  NAME    I/O\n"
            "1    ID_BUS  inout\n"
            "2    BUS_OE  output\n"
            "3    BUS_TX  output\n"
            "4    BUS_RX  input\n"
            "5    CLK     input\n"
            "6    RESET_N input\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    gen_l9_integration_spec(project, extracted, {"opcodes": []})
    l9 = json.loads(
        (project / "phase1" / "generated_docs"
         / "L9_INTEGRATION_SPEC.json").read_text())
    port_names = {
        (p.get("name") or "").lower()
        for p in (l9.get("top_ports") or [])
    }
    assert "id_bus" in port_names, (
        f"canonical id_bus must survive; got {port_names}"
    )
    for forbidden in ("bus_oe", "bus_tx", "bus_rx"):
        assert forbidden not in port_names, (
            f"alias-group decomposition leaked into L9: {forbidden}"
        )


# ---------------------------------------------------------------------------
# Bug 4 (P0 BLOCKER) — L8 typed clock_domains[] block
# ---------------------------------------------------------------------------

def test_l8_emits_typed_clock_domains_with_freq_hz_role(tmp_path):
    """L8 must carry a typed clock_domains[] block with name + freq +
    role/source/domain_kind so l8_clock_domains_typed_check passes."""
    from programs.phase1_one_shot_runner import (
        gen_l1_datasheet,
        gen_l9_integration_spec,
        gen_l8_timing_waveform,
    )
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    extracted = {
        "pinout_datasheet.txt": (
            "EXAMPLE_CHIP single-wire EXAMPLE_PROTOCOL class.\n"
            "Clock: 50 MHz primary clock input.\n"
            "PIN  NAME    I/O\n"
            "1    CLK     input\n"
            "2    RESET_N input\n"
            "3    ID_BUS  inout\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    gen_l9_integration_spec(project, extracted, {"opcodes": []})
    gen_l8_timing_waveform(project, extracted)
    l8 = json.loads(
        (project / "phase1" / "generated_docs"
         / "L8_RTL_CONSTANTS.json").read_text())
    domains = l8.get("clock_domains")
    assert domains, (
        "L8.clock_domains[] must be a non-empty list when L9 declares "
        "a clk port OR a clock frequency is parsed from source"
    )
    primary = next(
        (d for d in domains
         if d.get("domain_kind") == "primary"
         or (d.get("name") or "").lower() in ("clk", "clk_main")),
        None,
    )
    assert primary is not None, (
        f"no primary clock_domain entry; got {domains}"
    )
    # Must carry a typed frequency in one of freq_hz / freq_mhz /
    # period_ns AND a role/source.
    has_freq = any(k in primary
                   for k in ("freq_hz", "freq_mhz", "period_ns"))
    has_role = any(k in primary
                   for k in ("role", "source", "domain_kind"))
    assert has_freq, f"primary entry missing freq_*: {primary}"
    assert has_role, f"primary entry missing role/source: {primary}"


def test_l8_synthesises_clock_domains_from_l9_when_no_freq_in_source(tmp_path):
    """Even when no clock-frequency declaration is parsed from input,
    if L9.top_ports has a clk-shaped pin, L8 must still emit a typed
    clock_domains[] entry sourced from L9.

    v1.6.89 (#21 Bug 1): _emit_typed_clock_domains was previously
    invoked during gen_l8_timing_waveform (step 9) which runs BEFORE
    L9 lands on disk (step 10) — so the synthesise-from-L9.top_ports
    branch never fired (the v1.6.88 fix shipped INERT). The call
    site moved to a post-pass `_post_emit_typed_clock_domains` that
    runs AFTER L9 is on disk; this test now drives that post-pass
    explicitly."""
    from programs.phase1_one_shot_runner import (
        gen_l1_datasheet,
        gen_l9_integration_spec,
        gen_l8_timing_waveform,
        _post_emit_typed_clock_domains,
    )
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    extracted = {
        "pinout_datasheet.txt": (
            "Generic EXAMPLE_PROTOCOL-class IC.\n"
            "PIN  NAME    I/O\n"
            "1    CLK     input\n"
            "2    RESET_N input\n"
            "3    ID_BUS  inout\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    # Canonical step ordering: L8 (step 9) → L9 (step 10) → post-pass.
    gen_l8_timing_waveform(project, extracted)
    gen_l9_integration_spec(project, extracted, {"opcodes": []})
    _post_emit_typed_clock_domains(project)
    l8 = json.loads(
        (project / "phase1" / "generated_docs"
         / "L8_RTL_CONSTANTS.json").read_text())
    domains = l8.get("clock_domains") or []
    primary = next(
        (d for d in domains
         if (d.get("name") or "").lower() == "clk"),
        None,
    )
    assert primary is not None, (
        "synthesised primary clock_domain entry missing when L9 has "
        f"a clk port; got {domains}"
    )
    # Synthesised entry carries source / role / domain_kind.
    assert primary.get("domain_kind") == "primary"
    assert primary.get("source") or primary.get("role"), (
        f"synthesised entry must carry source or role: {primary}"
    )


def test_l8_clock_domains_skipped_when_no_clk_pin_no_freq(tmp_path):
    """Reject-test: when there's no clk-shaped pin AND no clock
    frequency in source, clock_domains stays empty (the gate's
    SKIP path) — never invents a fake 50 MHz entry."""
    from programs.phase1_one_shot_runner import gen_l8_timing_waveform
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    extracted = {
        "datasheet.txt": "Pure-analog block. No digital clock.\n",
    }
    # Note: no L9 doc emitted — L8 must not invent ports.
    gen_l8_timing_waveform(project, extracted)
    l8 = json.loads(
        (project / "phase1" / "generated_docs"
         / "L8_RTL_CONSTANTS.json").read_text())
    domains = l8.get("clock_domains") or []
    assert domains == [], (
        f"clock_domains should be empty when no L9 + no freq evidence; "
        f"got {domains}"
    )


# ---------------------------------------------------------------------------
# Bug 3 (P0 BLOCKER) — step_full_stack_tb_gen emits tb_<top>_full.v
# ---------------------------------------------------------------------------

def test_step_full_stack_tb_emits_tb_full_v(tmp_path):
    """phase2 runner emits tb_<top>_full.v from L9.top_ports under
    sim_full_stack/, satisfying bit_level_full_stack_tb_check."""
    from programs.design_one_shot_runner import step_full_stack_tb_gen
    project = tmp_path
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk",     "direction": "input",  "width": 1},
            {"name": "reset_n", "direction": "input",  "width": 1},
            {"name": "id_bus",  "direction": "inout",  "width": 1},
        ],
    }))
    result = step_full_stack_tb_gen(project)
    # ORGANIC-20260528: with no concrete L3 golden, the TB-gen emits a
    # connectivity-only skeleton and HONESTLY returns SKIP — it must NOT
    # fabricate a green functional PASS. The TB file is still emitted.
    assert result.status in ("PASS", "SKIP"), (
        f"step_full_stack_tb_gen should PASS/SKIP; got "
        f"status={result.status} detail={result.detail}"
    )
    tb = (project / "phase2" / "stage1" / "sim_full_stack"
          / "tb_chip_top_full.v")
    assert tb.is_file(), f"tb_chip_top_full.v not emitted at {tb}"
    body = tb.read_text()
    assert "module tb_chip_top_full" in body
    assert "u_dut" in body
    # Every L9 port must appear in the TB source.
    assert "id_bus" in body, "L9.top_ports.id_bus missing from TB"
    # Inout port should have tri-state drive scaffolding.
    assert "id_bus_drive" in body, (
        "inout port must carry _drive reg + tri-state assign in TB skel"
    )
    # The emitted results.json must NOT claim a functional PASS off
    # placeholder goldens: no concrete L3 golden → functional_verified
    # is False and no per_vector carries a concrete expected value.
    res = json.loads(
        (project / "phase2" / "stage1" / "sim_full_stack"
         / "results.json").read_text())
    assert res.get("functional_verified") is False, (
        "skeleton with no golden must not report functional_verified")
    assert res["functional_coverage"]["scored_with_golden"] == 0
    for v in res["per_vector"]:
        eb = v.get("expected_bytes")
        assert eb in (None, "") or "XX" not in str(eb).upper(), (
            f"placeholder golden leaked into per_vector: {v}")
        assert v.get("verdict") != "PASS", (
            "no vector may claim PASS without a concrete golden")


def test_step_full_stack_tb_skip_when_l9_missing(tmp_path):
    """Reject-test: SKIP (not FAIL) when L9 is absent — phase1 hasn't
    run yet."""
    from programs.design_one_shot_runner import step_full_stack_tb_gen
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    result = step_full_stack_tb_gen(project)
    assert result.status == "SKIP", (
        f"missing L9 should SKIP, not FAIL; got {result.status}"
    )


# ---------------------------------------------------------------------------
# ORGANIC-20260528 — full-stack TB-gen golden population + honesty.
# ---------------------------------------------------------------------------

def test_full_stack_tb_gen_populates_concrete_golden(tmp_path):
    """When L3 provides concrete response_payload_template hex values,
    the TB-gen populates expected_bytes with the real golden (never
    'XX'), and the results.json scores those vectors with a golden."""
    from programs.design_one_shot_runner import step_full_stack_tb_gen
    project = tmp_path
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "reset_n", "direction": "input", "width": 1},
            {"name": "id_bus", "direction": "inout", "width": 1},
        ],
    }))
    # Every opcode carries a fully-concrete golden response template.
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "opcodes": [
            {"hex": f"0x{0x70 + i:02X}",
             "response_payload_template": [
                 {"byte_offset": 0, "value": f"0x{0x75 + i:02X}"},
                 {"byte_offset": 1, "value": "0x10"},
             ]}
            for i in range(5)
        ],
    }))
    step_full_stack_tb_gen(project)
    res = json.loads(
        (project / "phase2" / "stage1" / "sim_full_stack"
         / "results.json").read_text())
    # No 'XX' placeholder anywhere.
    assert "XX" not in json.dumps(res["per_vector"]).upper()
    # The 5 L3 opcodes are scored with a concrete golden.
    assert res["functional_coverage"]["scored_with_golden"] >= 5
    # Concrete-golden vectors carry the real expected bytes.
    golden_vecs = [v for v in res["per_vector"]
                   if isinstance(v.get("expected_bytes"), str)
                   and v["expected_bytes"]]
    assert golden_vecs, "expected at least one concrete-golden vector"
    assert golden_vecs[0]["expected_bytes"] == "75,10"


def test_full_stack_tb_gen_never_emits_placeholder_pass(tmp_path):
    """Regression: the runner must NEVER write a per_vector entry with
    expected_bytes='XX' + verdict='PASS' (the original false-PASS shape)
    — not even in the >=8 padding loop."""
    from programs.design_one_shot_runner import step_full_stack_tb_gen
    project = tmp_path
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "id_bus", "direction": "inout", "width": 1},
        ],
    }))
    # No L3 → no golden at all → every vector must be UNVERIFIED.
    step_full_stack_tb_gen(project)
    res = json.loads(
        (project / "phase2" / "stage1" / "sim_full_stack"
         / "results.json").read_text())
    assert res["functional_verified"] is False
    for v in res["per_vector"]:
        eb = str(v.get("expected_bytes")).upper()
        assert not (eb == "XX" and v.get("verdict") == "PASS"), (
            f"false-PASS placeholder shape leaked: {v}")
        assert v.get("verdict") != "PASS"


# ---------------------------------------------------------------------------
# Bug 1 (P1) — clock harvester context window + sub-kHz reject
# ---------------------------------------------------------------------------

def test_is_real_clock_freq_rejects_sub_khz():
    """Direct unit test: a 2 Hz value is below the clock floor and
    must be rejected even when clock context is present."""
    from programs.phase1_one_shot_runner import _is_real_clock_freq
    text = "respond within 2 Hz of nominal clock frequency target"
    # Position of "2" in the string.
    span_start = text.index("2 Hz")
    span_end = span_start + len("2 Hz")
    assert _is_real_clock_freq(2, text, span_start, span_end) is False, (
        "2 Hz must be rejected as below clock floor"
    )


def test_is_real_clock_freq_rejects_no_clock_context():
    """A 50 MHz value (= 50_000_000 Hz) without any clock-keyword in
    a ±50-char window must be rejected."""
    from programs.phase1_one_shot_runner import _is_real_clock_freq
    text = "data rate 50 MHz of total bandwidth across the bus pins"
    span_start = text.index("50 MHz")
    span_end = span_start + len("50 MHz")
    # 50 MHz nominally above the floor, but no clock keyword nearby.
    # The window around index includes "data rate", "bandwidth", "bus",
    # but NO clock / clk / freq / oscillator / xtal — must reject.
    assert _is_real_clock_freq(
        50_000_000, text, span_start, span_end) is False, (
        "freq with no clock-keyword context must be rejected"
    )


def test_is_real_clock_freq_accepts_real_clock():
    """Positive control: a 50 MHz value with clock-keyword context
    must be accepted."""
    from programs.phase1_one_shot_runner import _is_real_clock_freq
    text = "system clock at 50 MHz primary input"
    span_start = text.index("50 MHz")
    span_end = span_start + len("50 MHz")
    assert _is_real_clock_freq(
        50_000_000, text, span_start, span_end) is True, (
        "real 50 MHz clock with `clock` keyword nearby must be accepted"
    )
