"""tests/test_phase1_issue12_cross_ic_fingerprint.py — v1.6.79

Cross-IC fingerprint check. After phase1 runs on TWO different
IC-class fixtures (e.g. block cipher vs memory controller), no
non-empty sub-field under L1-L23 should have IDENTICAL content
between them. If any does, that field carries a hardcoded
EXAMPLE_PROTOCOL-class scaffold instead of doing real per-source extraction.
"""
from __future__ import annotations
import json
from pathlib import Path
from programs.phase1_one_shot_runner import (
    gen_l1_datasheet, gen_l2_frs, gen_l3_cmd_protocol, gen_l4_regmap,
    gen_l5_adi_spec, gen_l6_control_logic, gen_l7_test_debug,
    gen_l8_timing_waveform, gen_l9_integration_spec,
    gen_l10_test_cases, gen_l11_otp_content,
    gen_l12_behavioral, gen_l13_lab_calibration,
)
import pytest

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path):
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


def _read(project, name):
    return json.loads((project / _GEN_DIR / f"{name}.json").read_text())


def _gen_all(project, extracted):
    """Run all 13 layer generators in dependency order (some
    layers read prior layers)."""
    gen_l1_datasheet(project, extracted)
    gen_l2_frs(project, extracted)
    gen_l3_cmd_protocol(project, extracted, l2={})
    l3 = _read(project, "L3_CMD_PROTOCOL")
    gen_l4_regmap(project, extracted)
    gen_l5_adi_spec(project, extracted)
    gen_l6_control_logic(project, extracted)
    gen_l7_test_debug(project, extracted)
    gen_l8_timing_waveform(project, extracted)
    gen_l9_integration_spec(project, extracted, l3)
    gen_l10_test_cases(project, extracted, l3)
    gen_l11_otp_content(project, extracted)
    gen_l12_behavioral(project, extracted, l3)
    gen_l13_lab_calibration(project, extracted)


def test_no_identical_non_empty_sibling_fields_between_aes_and_dram(tmp_path_factory):
    """Two thin-input projects (AES block cipher vs LiteDRAM memory
    controller) must not have IDENTICAL content for ANY non-empty
    sub-field across L1-L23. Any such match is evidence of a
    hardcoded scaffold rather than per-source extraction."""

    aes_proj = _seed(tmp_path_factory.mktemp("aes"))
    aes_extracted = {
        "README.md": "# AES-128/256 cipher core\n\nNIST FIPS 197 hardware implementation.\n"
                     "Pure combinational rounds.\nKey expansion in dedicated module.\n",
    }
    _gen_all(aes_proj, aes_extracted)

    dram_proj = _seed(tmp_path_factory.mktemp("dram"))
    dram_extracted = {
        "README.md": "# LiteDRAM\n\nSmall footprint configurable DRAM controller.\n"
                     "ECC over 64-bit data path.\nDDR3/DDR4 PHY support.\n",
    }
    _gen_all(dram_proj, dram_extracted)

    layers = ["L1_DATASHEET", "L2_FRS", "L3_CMD_PROTOCOL", "L4_REGMAP",
              "L5_ADI_SPEC", "L6_CONTROL_LOGIC", "L7_TEST_DEBUG",
              "L8_RTL_CONSTANTS", "L9_INTEGRATION_SPEC", "L10_TEST_CASES",
              "L11_OTP_CONTENT", "L12_BEHAVIORAL_SEQUENCES", "L13_LAB_CALIBRATION"]

    suspect_fields = []
    for layer in layers:
        try:
            aes_doc = _read(aes_proj, layer)
            dram_doc = _read(dram_proj, layer)
        except FileNotFoundError:
            continue
        # Collect leaf-level fields from both. Any field whose value is
        # non-empty AND identical across both projects is a candidate
        # hardcode. Skip schema-fixed fields (schema_version, etc.) and
        # known-shared fields (chip_class_hint, etc.).
        SKIP = {"schema_version", "_schema", "ic_class_hint", "doc_class",
                "extraction_strategy", "extraction_evidence",
                "no_pin_table_in_input", "no_protocol_overview_in_input",
                "no_crc_parameters_in_input", "no_registers_in_input",
                "no_analog", "no_fsm_in_input", "no_test_modes_in_input",
                "no_timing_constants_in_input", "no_integration_in_input",
                "no_test_cases_in_input", "no_otp_layout_in_input",
                "no_behavioral_sequences_in_input", "no_lab_calibration_in_input",
                "no_verdict_byte_in_input", "no_payload_semantics_in_input",
                "no_debug_observability_in_input", "no_verification_strategy_in_input",
                "no_engineer_mode_unlock_in_input", "no_rx_classifier_ticks_in_input",
                "no_clock_mhz_in_input", "no_clock_domains_in_input",
                "no_top_module_in_input", "no_submodules_in_input",
                "no_internal_wires_in_input", "no_calibration_steps_in_input",
                "no_lab_equipment_in_input", "no_rig_pin_assignments_in_input",
                "no_l13_test_cases_in_input",
                "no_opcodes_in_input", "no_fsm_states_in_input",
                "no_otp_layout_in_input_l4",
                # v1.6.130 (#51 Fix 1) — placeholder_opcode_count is a
                # structural counter that is 0 for any project with no
                # opcodes (both AES and LiteDRAM here). Not a fingerprint
                # scaffold — the field is non-zero only on rich-input
                # projects whose extractor saw opcodes but couldn't
                # resolve names.
                "placeholder_opcode_count",
                # v1.6.245 (#106) — opcode_synthesis_skipped_reason
                # is a structural explanation emitted whenever the
                # opcode-synthesis precondition gate fires (no
                # half-duplex declaration AND no opcode/command
                # table heading in input/docs/). Both AES and
                # LiteDRAM legitimately hit the same gate-skip path
                # with the same reason; the field is non-empty
                # only when the gate skipped synthesis, which is a
                # structural property of the input, not a chip-class
                # scaffold leak.
                "opcode_synthesis_skipped_reason",
                # Structural skip-counters — emitted as 0 whenever the
                # corresponding emit-gate was never tripped on a given
                # project. Both AES and LiteDRAM are thin-input projects
                # that legitimately skip the per-keyword vsuite cap (L7)
                # and the peripheral-only emit path (L8), so both report
                # 0. The counter is non-zero only on rich-input projects
                # where the gate actually fired; a shared 0 is a property
                # of the input, not a chip-class scaffold leak.
                "vsuite_per_kw_cap_skipped_v1_6_373",
                "peripheral_only_emit_skipped_v1_6_376",
                # for #454 — same structural-skip-counter family. Counts the
                # `<hex> <MNEMONIC>` rows the L3 free-form opcode walker
                # matched and then refused on their SHAPE (connector
                # pin-assignment row, rate/capacity prose, numeric-range
                # upper bound). Both fixtures are thin-input projects with
                # no such rows, so both legitimately report 0; the counter
                # is non-zero only on a project whose docs actually carry
                # that shape. A shared 0 is a property of the input.
                "non_command_row_refusal_count",
                # for #505 — same structural-skip-counter family. Number
                # of DISTINCT state machines L6/L9 attribute their states
                # to, grouped from extractor provenance. Both fixtures
                # are thin-input projects with no FSM evidence at all, so
                # both legitimately report 0 alongside an empty
                # `fsm_machines[]`. The count is non-zero only when a
                # project's own documents declare or describe a machine;
                # a shared 0 is a property of the input.
                "fsm_machine_count",
                # vibe-ic#522 — `_generator` records WHICH RELEASE OF THE
                # PLUGIN wrote the file (version + L-doc taxonomy digest +
                # last writer). It is identical across every document of
                # every design BY CONSTRUCTION, and that is the point of
                # it: it says nothing whatsoever about the part. This
                # gate looks for a scaffold leak — content that should
                # have differed between an AES core and a DRAM controller
                # and did not — so a field that describes the TOOL rather
                # than the CHIP is the one shape that can never be
                # evidence of one. (Contrast `ic_name` below, which is
                # skipped only for its fallback VALUE.)
                "_generator",
                # Empty/null sentinel structurally-shared values are fine.
                # They're not "identical hardcodes" — they're "neither
                # had evidence, both null".
                }
        for key, aes_val in aes_doc.items():
            if key in SKIP:
                continue
            # Skip ANY no_<X>_in_input flag and any other boolean —
            # flag-shaped fields are structurally allowed to match
            # across projects (both had the same gap).
            if isinstance(aes_val, bool):
                continue
            if aes_val in (None, [], {}, ""):
                continue
            if dram_doc.get(key) == aes_val:
                # Allow ic_name fallback ("EXAMPLE_CHIP") — that's the picker
                # default, not a sibling-field scaffold. Allow common
                # bring_up_sequence/calibration_tables that come from
                # OTP-section enumeration logic — these are structurally
                # legitimate (every OTP-bearing project shares them).
                # v1.6.189 (#76 P1) — also allow top_module="chip_top"
                # as a structural default. The runner emits `chip_top`
                # as the universal canonical top-module name (see
                # aid_class_rtl_gen MAIN_FSM / chip_top.sv templates);
                # this is a runner-level default, not an EXAMPLE_PROTOCOL-class
                # scaffold leak.
                if key in ("ic_name", "bring_up_sequence",
                           "calibration_tables", "top_module",
                           # v1.6.273 — for #135 ORGANIC. Provenance
                           # marker for the top_module extraction strategy.
                           # Strategy enum values (`rtl_filesystem_scan`,
                           # `doc_module_decl_or_heading`, `l1_ic_name_fallback`,
                           # `canonical_chip_top_sentinel`) are by design
                           # the same string across chips that share the
                           # same extraction path. Not a chip-class
                           # scaffold leak.
                           "top_module_extraction_strategy",
                           # v1.6.273 — for #138 ORGANIC. L1.description
                           # extraction evidence dict carries the source
                           # path and extraction strategy. When both
                           # projects' READMEs share the same H1-chip-name
                           # anchor shape, the evidence dict is
                           # structurally identical (same source path
                           # `input/docs/README.md`, line 1, anchor
                           # `markdown_h1_chip_name`). Per-chip content
                           # differs in the description string itself.
                           "description_evidence",
                           # L9 top-module-pins fallback evidence dict.
                           # When NEITHER project's input docs carry a
                           # module declaration, both fall back to
                           # L1.ic_name via the same canonical
                           # `fallback_explicit_v1_6_581` strategy
                           # marker, so the evidence dict is structurally
                           # identical (same reason / fallback_source /
                           # strategy marker). Same family as
                           # top_module_extraction_strategy and
                           # description_evidence above — a shared
                           # extraction-path marker, not a chip-class
                           # scaffold leak.
                           "top_module_pins_evidence",
                           # ORGANIC #580 — the digital-only L5 skeleton's
                           # structural N/A markers. Two digital-only ICs
                           # legitimately share `NOT_APPLICABLE` + the
                           # canonical reason string (same deterministic
                           # emitter path by design); per-chip content
                           # lives in ic_name. Same family as the strategy
                           # markers above.
                           "applicability",
                           "applicability_reason",
                           # source_documents is the per-project input
                           # file list — both fixtures stage a single
                           # `input/docs/README.md`, so the RELATIVE path
                           # list coincides. A real-input filename echo,
                           # not a scaffold leak.
                           "source_documents",
                           # v1.7.74 — for #507. L4's two MEASUREMENT
                           # records: what the input declared against
                           # what the layer carries, and whether the
                           # register cap cut anything. Both are
                           # statements ABOUT the extraction, not about
                           # the design, and two projects whose inputs
                           # declare no address-valued enum and whose
                           # register list never reaches the cap
                           # legitimately record the same zero — with
                           # the same written reason, which is the
                           # point. Per-chip content lives in
                           # registers[]. Same family as the strategy /
                           # applicability markers above.
                           "input_declared_registers",
                           "register_cap_v1_7_74"):
                    continue
                suspect_fields.append(f"{layer}.{key} = {aes_val!r}")

    assert not suspect_fields, (
        f"v1.6.79 cross-IC fingerprint match — these fields are identical "
        f"between AES and LiteDRAM, suggesting hardcoded EXAMPLE_PROTOCOL-class "
        f"scaffold:\n  " + "\n  ".join(suspect_fields)
    )
