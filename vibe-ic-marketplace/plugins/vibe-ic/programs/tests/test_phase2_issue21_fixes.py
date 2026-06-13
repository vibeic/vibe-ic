"""tests/test_phase2_issue21_fixes.py — v1.6.89

Closes issue #21 — 4 bugs from #20 partial close + 2 orthogonal:
- Bug 1 (P0): _emit_typed_clock_domains was INERT in v1.6.88 because
  it was wired into gen_l8_timing_waveform (step 9) which runs BEFORE
  L9 is on disk (step 10). Moved into a new post-pass
  `_post_emit_typed_clock_domains` that runs AFTER
  _post_fix_l8_rtl_consts_flag.
- Bug 2 (P0): _is_real_clock_freq was applied only on the ingest
  path. Mirror it inside l8_clock_domains_typed_check._scan_freq_mentions
  so the gate-side filter rejects sub-kHz / no-clock-context hits
  the same way.
- Bug 3 (P1): L9 submodule extractor accepted doc-table headers like
  `Type` / `Description` / `Notes`. Add `_DOC_TABLE_HEADER_TOKENS`
  + `_is_real_submodule_name` filter applied to both strategy A
  (RTL `module` decls) and strategy B (prose extraction).
- Bug 4 (P1): aid_class_rtl_gen chip_top must emit explicit
  `<bus>_rx_masked = <bus>_rx & ~<bus>_oe` net so self_rx_mask_check
  can pair the half-duplex bus OE with a sibling-named RX signal.

All fixes are chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
for _p in (str(PROGRAMS), str(PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Bug 1 (P0) — _emit_typed_clock_domains must run AFTER L9 is on disk
# ---------------------------------------------------------------------------

def test_emit_typed_clock_domains_no_op_when_l9_absent(tmp_path):
    """REJECT-test: if _emit_typed_clock_domains is invoked while L9
    is still absent (the v1.6.88 bug), the synthesise-from-L9.top_ports
    branch must early-return and produce no entries. This documents
    why the call site had to move out of step 9."""
    from programs.phase1_one_shot_runner import _emit_typed_clock_domains
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    # NO L9 file — simulates the v1.6.88 step-ordering bug.
    clock_domains = []  # empty starting state
    _emit_typed_clock_domains(project, clock_domains, [])
    assert clock_domains == [], (
        "When L9 is absent, _emit_typed_clock_domains must early-return. "
        "If this assertion fires the runner is back to silent failure."
    )


def test_post_emit_typed_clock_domains_synthesises_primary_after_l9(tmp_path):
    """v1.6.89: the post-pass invocation runs AFTER L9 is on disk and
    must successfully synthesise a typed primary clock_domains[] entry
    from L9.top_ports."""
    from programs.phase1_one_shot_runner import (
        _post_emit_typed_clock_domains,
    )
    project = tmp_path
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    # L9 declares a clk-shaped pin — the post-pass should read it.
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk",     "direction": "input", "width": 1},
            {"name": "reset_n", "direction": "input", "width": 1},
            {"name": "id_bus",  "direction": "inout", "width": 1},
        ],
    }))
    # L8_RTL_CONSTANTS exists with empty clock_domains[] — that's the
    # v1.6.88 INERT-fix state.
    l8_path = docs / "L8_RTL_CONSTANTS.json"
    l8_path.write_text(json.dumps({
        "schema_version": 2,
        "doc_class": "rtl_constants",
        "ic_name": "TEST",
        "clock_domains": [],
        "no_clock_domains_in_input": True,
    }))
    _post_emit_typed_clock_domains(project)
    rtl = json.loads(l8_path.read_text())
    domains = rtl.get("clock_domains") or []
    assert len(domains) >= 1, (
        f"v1.6.89 post-pass must synthesise primary domain from "
        f"L9.top_ports clk pin; got {domains}"
    )
    primary = next((d for d in domains
                    if d.get("domain_kind") == "primary"), None)
    assert primary is not None, (
        f"v1.6.89: synthesised entry must carry domain_kind=primary; "
        f"got {domains}"
    )
    # Typed shape required by l8_clock_domains_typed_check.
    assert "name" in primary
    assert any(k in primary
               for k in ("freq_hz", "freq_mhz", "period_ns")), (
        f"typed shape requires freq_hz / freq_mhz / period_ns; "
        f"got {primary}"
    )
    assert any(k in primary
               for k in ("role", "source", "kind", "parent")), (
        f"typed shape requires role / source / kind / parent; "
        f"got {primary}"
    )


# ---------------------------------------------------------------------------
# Bug 2 (P0) — gate-side _is_real_clock_freq filter
# ---------------------------------------------------------------------------

def test_gate_side_clock_freq_filter_rejects_sub_khz_tolerance(tmp_path):
    """REJECT-test for v1.6.88: sub-kHz `2 Hz` tolerance prose hit
    must NOT count as a distinct clock-frequency mention. v1.6.88
    fixed this on the ingest side only — the gate's own
    _scan_freq_mentions still trusted the bare regex. v1.6.89 mirrors
    the filter inside the gate."""
    from programs.l8_clock_domains_typed_check import _scan_freq_mentions
    project = tmp_path
    extracted = project / "phase1" / "input_doc"
    extracted.mkdir(parents=True, exist_ok=True)
    (extracted / "spec.txt").write_text(
        "Tolerance: respond within 2 Hz of nominal output.\n"
        "Reference frequency for production calibration is 100 Hz.\n"
        "System clock at 50 MHz primary clock.\n"
    )
    freqs = _scan_freq_mentions(project)
    # 2 Hz / 100 Hz must be filtered: sub-kHz + tolerance prose.
    norm = {f.lower().replace(" ", "") for f in freqs}
    assert "2hz" not in norm, (
        f"sub-kHz `2 Hz` tolerance hit must be filtered; got {freqs}"
    )
    assert "100hz" not in norm, (
        f"sub-kHz `100 Hz` reference hit must be filtered; got {freqs}"
    )
    # 50 MHz must survive — it's a real clock mention with `clock`
    # keyword nearby.
    assert any("50" in f and "mhz" in f.lower() for f in freqs), (
        f"50 MHz real clock must be retained; got {freqs}"
    )


def test_gate_side_filter_rejects_freq_without_clock_keyword(tmp_path):
    """A bare `2 MHz` mention without any clock-keyword token in the
    ±50-char window must NOT count. Mirrors the ingest-side context
    check."""
    from programs.l8_clock_domains_typed_check import _scan_freq_mentions
    project = tmp_path
    extracted = project / "phase1" / "input_doc"
    extracted.mkdir(parents=True, exist_ok=True)
    (extracted / "spec.txt").write_text(
        # MHz unit but no clock vocabulary anywhere near.
        "The acceptable spurious-emission level is below 2 MHz amplitude.\n"
        "Audio bandwidth measured up to 20 kHz response.\n"
        # Real clock context.
        "Primary system clock at 12 MHz.\n"
    )
    freqs = _scan_freq_mentions(project)
    norm = {f.lower().replace(" ", "") for f in freqs}
    # 2 MHz spurious emission has no clock-keyword in window → filtered.
    assert "2mhz" not in norm, (
        f"`2 MHz` without clock-keyword must be filtered; got {freqs}"
    )
    # 12 MHz primary system clock survives.
    assert any("12" in f and "mhz" in f.lower() for f in freqs), (
        f"12 MHz primary clock must be retained; got {freqs}"
    )


# ---------------------------------------------------------------------------
# Bug 3 (P1) — L9 submodule extractor rejects doc-table headers
# ---------------------------------------------------------------------------

def test_is_real_submodule_name_rejects_doc_headers():
    """Direct unit test of _is_real_submodule_name."""
    from programs.phase1_one_shot_runner import _is_real_submodule_name
    # Doc-table headers must REJECT.
    for hdr in ("Type", "Name", "Description", "Notes", "Function",
                "Owner", "Status", "Source", "Field", "Value", "ID",
                "type", "name", "description", "Block", "Component"):
        assert not _is_real_submodule_name(hdr), (
            f"doc-table header {hdr!r} must be rejected"
        )
    # Too short must REJECT.
    for s in ("", "a", "ab", "abc", "rx"):
        assert not _is_real_submodule_name(s), (
            f"too-short name {s!r} must be rejected"
        )
    # Real RTL submodule names must ACCEPT.
    for nm in ("crc8", "rx_phy", "tx_phy", "byte_assembler",
                "wake_gen", "main_fsm", "otp_mem", "aes_core",
                "spi_master", "uart_rx", "div_clock"):
        assert _is_real_submodule_name(nm), (
            f"real submodule name {nm!r} must be accepted"
        )


def test_l9_submodule_extractor_rejects_type_header_token(tmp_path):
    """End-to-end: when datasheet prose includes a `Submodule:` line
    whose value is the table-header token `Type`, the extractor must
    NOT record `Type` as a submodule."""
    from programs.phase1_one_shot_runner import gen_l9_integration_spec
    project = tmp_path
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    extracted = {
        "datasheet.txt": (
            "Submodule list:\n"
            "Submodule: Type\n"            # ← doc-table header leak
            "Submodule: Description\n"     # ← doc-table header leak
            "Submodule: crc8\n"            # ← real submodule
            "Submodule: byte_assembler\n"  # ← real submodule
        ),
    }
    l3_stub = {"verdict_byte_hex": "F2", "verdict_byte_offset": 6}
    gen_l9_integration_spec(project, extracted, l3_stub)
    l9 = json.loads((docs / "L9_INTEGRATION_SPEC.json").read_text())
    submods = l9.get("submodules") or []
    names_lower = [s.get("name", "").lower() for s in submods]
    forbidden = {"type", "description", "name", "notes", "submodule",
                 "block", "component"}
    for f in forbidden:
        assert f not in names_lower, (
            f"doc-table header {f!r} leaked into L9.submodules: {submods}"
        )
    # Real submodules survive.
    assert "crc8" in names_lower, (
        f"real submodule `crc8` must be retained; got {submods}"
    )
    assert "byte_assembler" in names_lower, (
        f"real submodule `byte_assembler` must be retained; got {submods}"
    )


# ---------------------------------------------------------------------------
# Bug 4 (P1) — chip_top emits `<bus>_rx_masked = <bus>_rx & ~<bus>_oe`
# ---------------------------------------------------------------------------

def _seed_aid_project(project: Path) -> None:
    """Minimal L1/L3/L8/L9 stub so aid_class_rtl_gen.gen() can emit."""
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "TEST"}))
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "schema_version": 2,
        "command_set": [{"name": "READ", "opcode_hex": "01"}],
        "crc_parameters": {"polynomial_hex": "0x31"},
    }))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "schema_version": 2,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "schema_version": 2,
        "doc_class": "rtl_constants",
        "ic_name": "TEST",
        "rx_classifier_ticks": None,
        "timing_constants": [],
        "clock_domains": [],
    }))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk",     "direction": "input", "width": 1},
            {"name": "reset_n", "direction": "input", "width": 1},
            {"name": "id_bus",  "direction": "inout", "width": 1},
        ],
    }))


def _read_chip_top(project: Path) -> str:
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


def test_chip_top_emits_rx_masked_and_not_oe_pattern(tmp_path):
    """v1.6.89 (#21 Bug 4): chip_top must emit
    `id_bus_rx_masked = id_bus_rx & ~id_bus_oe`
    so self_rx_mask_check pairs the OE with a sibling-named RX."""
    from programs import aid_class_rtl_gen
    project = tmp_path / "aid_proj"
    _seed_aid_project(project)
    aid_class_rtl_gen.gen(project)
    chip_top = _read_chip_top(project)
    assert "id_bus_rx_masked" in chip_top, (
        "v1.6.89 must emit `id_bus_rx_masked` net into chip_top"
    )
    assert "id_bus_rx" in chip_top, (
        "v1.6.89 must emit `id_bus_rx` alias into chip_top so "
        "self_rx_mask_check sibling-name detection succeeds"
    )
    assert "id_bus_oe" in chip_top, (
        "v1.6.89 must emit `id_bus_oe` alias into chip_top"
    )
    # Specifically the AND-NOT pattern. v1.6.90 (#22 Bug 1):
    # mask uses the literal OE name (id_bus_drive_low), not the
    # alias (id_bus_oe), so the gate's literal-name proximity scan
    # finds it.
    pat = re.compile(
        r"id_bus_rx_masked\s*=\s*id_bus_rx\s*&\s*~\s*id_bus_drive_low",
        re.IGNORECASE)
    assert pat.search(chip_top), (
        f"v1.6.90: missing AND-NOT mask pattern "
        f"`id_bus_rx_masked = id_bus_rx & ~id_bus_drive_low`; "
        f"chip_top body:\n{chip_top[:2000]}"
    )


def test_chip_top_rx_masked_alias_present_in_asic_variant(tmp_path):
    """Mirror in the ASIC chip_top variant (CHIP_TOP_ASIC). The same
    self-RX masking idiom is required for both FPGA and ASIC top
    layouts."""
    from programs import aid_class_rtl_gen
    src = aid_class_rtl_gen.CHIP_TOP_ASIC
    # v1.6.90 (#22 Bug 1): literal OE (id_bus_drive_low) in mask.
    pat = re.compile(
        r"id_bus_rx_masked\s*=\s*id_bus_rx\s*&\s*~\s*id_bus_drive_low",
        re.IGNORECASE)
    assert pat.search(src), (
        "v1.6.90: CHIP_TOP_ASIC must also carry the AND-NOT mask "
        "pattern keyed on literal OE `id_bus_drive_low`; chip-"
        "AGNOSTIC self-RX masking applies to every half-duplex "
        "single-wire IC regardless of FPGA-vs-ASIC top."
    )
