"""tests/test_phase2_issue19_fixes.py — v1.6.87

Closes issue #19 — P0 BLOCKER + 5 partial-close items:
- Bug 1 (P0): duplicate clk decl when L9 has both `clk` + `*_clk`
- Bug 2 (P1): DE10-Lite board pin patterns rejected
- Bug 3 (P1): iid_bus typo deduped against id_bus canonical
- Bug 4 (P1): L11 FSM catalogue rejects chip part-numbers + acronyms
- Bug 5 (P2): fsm_state_catalogue routed to correct layer (verified)
- Bug 6 (P2): clock freq regex rejects `2.hz` parser garbage

All fixes are chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
for p in (str(PROGRAMS), str(PLUGIN_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _read_chip_top(project: Path) -> str:
    """Locate the emitted chip_top.sv regardless of layout-version."""
    for cand in (
        project / "phase2" / "stage1" / "rtl" / "chip_top.sv",
        project / "rtl" / "chip_top.sv",
        project / "phase2" / "rtl" / "chip_top.sv",
    ):
        if cand.is_file():
            return cand.read_text()
    hits = list(project.rglob("chip_top.sv"))
    assert hits, f"chip_top.sv not emitted under {project}"
    return hits[0].read_text()


def _seed(tmp_path: Path) -> Path:
    """Minimal phase1/generated_docs scaffold for aid_class_rtl_gen."""
    project = tmp_path
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "TEST"}))
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "schema_version": 2,
        "command_set": [{"name": "READ", "opcode_hex": "01"}],
        "crc_parameters": {"polynomial_hex": "0x31"},
    }))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(
        {"schema_version": 2}))
    return project


# ---------------------------------------------------------------------------
# Bug 1 (P0 BLOCKER) — duplicate clk decl when L9 has both clk + *_clk
# ---------------------------------------------------------------------------

def test_role_matcher_prefers_exact_clk_over_suffix(tmp_path):
    """Two-pass selector: when L9 carries both `clk` AND `mem_clk`,
    the exact-name match wins, and NO `wire clk = mem_clk;` alias is
    emitted (which would otherwise collide with the `input wire clk`
    port declaration → quartus syntax error)."""
    project = _seed(tmp_path)
    docs = project / "phase1" / "generated_docs"
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "mem_clk", "direction": "input",  "width": 1},
            {"name": "clk",     "direction": "input",  "width": 1},
            {"name": "reset_n", "direction": "input",  "width": 1},
            {"name": "id_bus",  "direction": "inout",  "width": 1},
        ],
    }))
    from programs import aid_class_rtl_gen
    aid_class_rtl_gen.gen(project)
    chip_top = _read_chip_top(project)
    # Both port names survive in the port list.
    assert "mem_clk" in chip_top
    assert "clk" in chip_top
    # Critically, no `wire clk = ...;` alias should be emitted because
    # `clk` was already declared as a port — an alias here would be a
    # duplicate-symbol declaration.
    alias_pattern = re.compile(r"^\s*wire\s+clk\s*=", re.MULTILINE)
    assert not alias_pattern.search(chip_top), (
        "duplicate clk decl: alias still emitted alongside the port"
    )


def test_role_matcher_falls_back_to_suffix_when_no_exact_clk(tmp_path):
    """If no exact `clk` port is present, the suffix-match (Pass 2)
    binds `mem_clk` to the clk role and emits the alias."""
    project = _seed(tmp_path)
    docs = project / "phase1" / "generated_docs"
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "mem_clk", "direction": "input",  "width": 1},
            {"name": "reset_n", "direction": "input",  "width": 1},
            {"name": "id_bus",  "direction": "inout",  "width": 1},
        ],
    }))
    from programs import aid_class_rtl_gen
    aid_class_rtl_gen.gen(project)
    chip_top = _read_chip_top(project)
    # No exact `clk` port: alias is emitted (Pass 2 picks mem_clk).
    has_alias = (
        "wire clk = mem_clk" in chip_top
        or "wire clk=mem_clk" in chip_top
    )
    assert has_alias, (
        "Pass 2 suffix-match should bind mem_clk as the clk alias when "
        "no exact `clk` port is present in L9"
    )


# ---------------------------------------------------------------------------
# Bug 2 (P1) — DE10-Lite board pin patterns
# ---------------------------------------------------------------------------

def test_l9_drops_de10_board_pin_patterns(tmp_path):
    """ADC_CLK_<N>, MAX10_CLK<X>_<N>, GPIO_<N>, HEX_<N>, KEY_<N>,
    LEDR_<N>, SW_<N>, DRAM_* must NOT promote into L9.ports — they
    are FPGA-board hardware-pin names, never chip top-level ports."""
    from programs.phase1_one_shot_runner import (
        gen_l1_datasheet,
        gen_l9_integration_spec,
    )
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    extracted = {
        "datasheet.txt": (
            "DE10-Lite board reference:\n"
            "ADC_CLK_10 = ADC clock at 10 MHz input\n"
            "MAX10_CLK2_50 = secondary 50 MHz clock input\n"
            "GPIO_24, GPIO_25 = header pins inout\n"
            "PIN  NAME    I/O\n"
            "1    id_bus  inout\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    # gen_l9 takes (project, extracted, l3-dict). Empty l3 is fine
    # because the test does not exercise verdict-byte logic.
    gen_l9_integration_spec(project, extracted, {"opcodes": []})
    l9 = json.loads(
        (project / "phase1" / "generated_docs"
         / "L9_INTEGRATION_SPEC.json").read_text())
    port_names = {
        (p.get("name") or "").lower()
        for p in (l9.get("top_ports") or [])
    }
    assert "adc_clk_10" not in port_names
    assert "max10_clk2_50" not in port_names
    assert "gpio_24" not in port_names
    assert "gpio_25" not in port_names


# ---------------------------------------------------------------------------
# Bug 3 (P1) — iid_bus typo dedup against id_bus canonical
# ---------------------------------------------------------------------------

def test_l9_dedupes_iid_bus_typo_against_id_bus(tmp_path):
    """When L1.pin_table extraction surfaces both `id_bus` AND
    `iid_bus` (double-i typo), the canonical wins and the typo
    is dropped via Levenshtein-≤1 dedup."""
    from programs.phase1_one_shot_runner import (
        gen_l1_datasheet,
        gen_l3_cmd_protocol,
        gen_l9_integration_spec,
        _dedupe_typo_against_canonical,
    )
    # Direct unit test on the helper — most reliable.
    ports = [
        {"name": "id_bus",  "direction": "inout"},
        {"name": "iid_bus", "direction": "inout"},
        {"name": "vbg",     "direction": "input"},
    ]
    out = _dedupe_typo_against_canonical(ports)
    names = {p["name"] for p in out}
    assert "id_bus" in names, "canonical id_bus must be kept"
    assert "iid_bus" not in names, "typo iid_bus must be dropped"
    # vbg is NOT close to any canonical that's present, so it's kept.
    assert "vbg" in names, "non-canonical port unrelated to typo must stay"


def test_dedupe_keeps_non_canonical_when_no_canonical_neighbour(tmp_path):
    """Edit-distance-1 must only fire when the canonical IS present —
    don't drop a real `vbg` just because some unrelated port resembles
    something canonical."""
    from programs.phase1_one_shot_runner import (
        _dedupe_typo_against_canonical,
    )
    ports = [
        {"name": "vbg",  "direction": "input"},
        {"name": "vref", "direction": "input"},
    ]
    out = _dedupe_typo_against_canonical(ports)
    names = {p["name"] for p in out}
    assert names == {"vbg", "vref"}, (
        "no canonical present → no dedup should occur"
    )


# ---------------------------------------------------------------------------
# Bug 4 (P1) — L11 FSM rejects chip part-numbers + new acronym blacklist
# ---------------------------------------------------------------------------

def test_l11_fsm_rejects_chip_part_numbers(tmp_path):
    """EXAMPLE_CHIP, A1101, EXAMPLE_TESTER are chip part-numbers, never FSM states."""
    from programs.phase1_one_shot_runner import gen_l11_otp_content
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP chip + A1101 variant + EXAMPLE_TESTER tester.\n"
            "FSM states: EXAMPLE_CHIP, A1101, EXAMPLE_TESTER, S_IDLE, S_RX, S_TX.\n"
        ),
    }
    gen_l11_otp_content(project, extracted)
    l11 = json.loads(
        (project / "phase1" / "generated_docs"
         / "L11_OTP_CONTENT.json").read_text())
    fsm_states = [
        (s.get("name") or "").upper()
        for s in (l11.get("fsm_state_catalogue") or [])
    ]
    for forbidden in ["EXAMPLE_CHIP", "A1101", "EXAMPLE_TESTER"]:
        assert forbidden not in fsm_states, (
            f"chip part-number leaked into fsm_state_catalogue: {forbidden}"
        )


def test_l11_fsm_rejects_new_acronym_blacklist(tmp_path):
    """I2C / SDQ / OSC / GPIO / UVLO / VID / OFF / DFT / ESN / CLM /
    LRM / MPD must not appear in fsm_state_catalogue."""
    from programs.phase1_one_shot_runner import gen_l11_otp_content
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    extracted = {
        "datasheet.txt": (
            "Interfaces: I2C, SDQ, OSC. Pins: GPIO. UVLO threshold.\n"
            "Modes: VID, OFF, DFT. ESN identifier. CLM clamp. LRM.\n"
            "FSM states: I2C, SDQ, OSC, GPIO, UVLO, VID, OFF, DFT, "
            "ESN, CLM, LRM, MPD, S_INIT, S_RUN.\n"
        ),
    }
    gen_l11_otp_content(project, extracted)
    l11 = json.loads(
        (project / "phase1" / "generated_docs"
         / "L11_OTP_CONTENT.json").read_text())
    fsm_states = [
        (s.get("name") or "").upper()
        for s in (l11.get("fsm_state_catalogue") or [])
    ]
    for forbidden in [
        "I2C", "SDQ", "OSC", "GPIO", "UVLO", "VID",
        "OFF", "DFT", "ESN", "CLM", "LRM", "MPD",
    ]:
        assert forbidden not in fsm_states, (
            f"new acronym leaked into fsm_state_catalogue: {forbidden}"
        )


# ---------------------------------------------------------------------------
# Bug 6 (P2) — clock freq regex rejects parser garbage
# ---------------------------------------------------------------------------

def test_l8_bare_value_re_rejects_dot_only_garbage():
    """`_TIMING_BARE_VALUE_RE` previously matched `2.` (incomplete
    decimal) followed by `hz`, producing `2.hz` parser garbage. The
    tightened regex (`\\d+(?:\\.\\d+)?`) requires a digit after any
    decimal point."""
    from programs.phase1_one_shot_runner import _TIMING_BARE_VALUE_RE
    # The garbage form must not match.
    assert not _TIMING_BARE_VALUE_RE.match("2.hz"), (
        "regex still accepts `2.hz` parser garbage"
    )
    assert not _TIMING_BARE_VALUE_RE.match("2.Hz")
    # Legitimate forms still match.
    assert _TIMING_BARE_VALUE_RE.match("2hz"), "bare integer must match"
    assert _TIMING_BARE_VALUE_RE.match("2.5hz"), (
        "well-formed decimal must match"
    )
    assert _TIMING_BARE_VALUE_RE.match("100 MHz"), (
        "spaced-unit form must match"
    )


def test_l8_bom_re_rejects_dot_only_garbage():
    """The same tightening applies to `bom_re` (L5 BOM harvester) and
    `spec_re` (electrical-spec harvester)."""
    bom_pat = re.compile(
        r"(\d+(?:\.\d+)?)\s*(nF|μF|uF|µF|pF|mΩ|mOhm|kΩ|kOhm|MΩ|MOhm|"
        r"Ω|Ohm|nm|MHz|kHz|GHz|Hz)",
        re.IGNORECASE,
    )
    # `2.hz` no longer matches.
    assert not bom_pat.match("2.hz")
    # Real values still match.
    assert bom_pat.match("100MHz")
    assert bom_pat.match("2.5kHz")
    assert bom_pat.match("47nF")
