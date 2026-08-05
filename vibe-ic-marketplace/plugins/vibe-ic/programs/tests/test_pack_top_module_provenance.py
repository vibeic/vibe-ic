"""A protocol pack must not name somebody else's design.

`L9.top_module` is the field `phase2_scaffold_gen.derive_top_module_name`
ranks FIRST — above `L1.ic_name` — before sanitizing the winner into the
design's Verilog top-module identifier. Whatever sits in it becomes the
name the RTL, the QSF and the full-stack testbench bind to.

Every assertion below is written against that OBSERVABLE PROPERTY — what
an L9 document ends up saying, and what identifier the scaffold generator
derives from it. None of them reads `_pack_top_module`'s internals beyond
the two public entry points, so a different correct fix passes them too.

The reverse cases are the ones that matter here, and there are three
distinct over-corrections to catch:

  * REVERSE-1  Deleting `top_module` to stop a pack writing it. That is
               the obvious fix and it BREAKS
               `l_doc_structured_field_count_check`, which counts a
               non-empty `top_module` as one of the >=3 typed structural
               fields L9 owes. Tested end-to-end against the real gate.
  * REVERSE-2  Reverting every pack write, including the one from the
               pack that DID name the design. A UART spec's top module
               should still come out of the UART pack.
  * REVERSE-3  Narrowing until nothing is ever reverted — a fix that
               changes no behaviour and reads as a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _pack_top_module as ptm                     # noqa: E402
from phase2_scaffold_gen import derive_top_module_name  # noqa: E402


# --------------------------------------------------------------------------
# The one enumeration of every protocol pack that writes L9.top_module.
#
# `(module, apply_fn, settled_ic_name, pack_reference_top)`. Every pack
# below routes its reference literal through `_pack_top_module.apply`; the
# fourth column is the literal that pack supplies. This is the SAME set the
# field-count sweep enumerates — the two behavioural sweeps below read it so
# there is one place to add a pack and no pack can be covered by one sweep
# and silently missed by the other.
#
# Provenance of the fourth column: `grep -n "_ptm.apply" *_protocol_synth.py`.
# --------------------------------------------------------------------------
_ALL_PACKS = [
    ("spi_protocol_synth", "apply_spi_synth",
     "SPI Block (S12SPIV4)", "SPI"),
    ("uart_protocol_synth", "apply_uart_synth",
     "PC16550D UART", "PC16550D"),
    ("sdmmc_protocol_synth", "apply_sdmmc_synth",
     "SD Memory Card", "SD_Memory_Card"),
    ("nvme_protocol_synth", "apply_nvme_synth",
     "NVM Express (NVMe) Base Specification Rev 1.4", "NVMe_Controller"),
    ("tpm_protocol_synth", "apply_tpm_synth",
     "TPM 2.0 Library Part 1: Architecture (TCG)",
     "TPM_2_0_Library_Architecture"),
    ("modbus_protocol_synth", "apply_modbus_synth",
     "Modbus Application Protocol V1.1b3 (Modbus.org)", "modbus_server_top"),
    ("lin_protocol_synth", "apply_lin_synth", "LIN bus 2.2A", "lin_node"),
    ("dali_protocol_synth", "apply_dali_synth",
     "DALI (IEC 62386)", "dali_control_gear_top"),
    ("sata_protocol_synth", "apply_sata_synth",
     "Serial ATA AHCI 1.3.1", "AHCI_HBA"),
    ("onfi_protocol_synth", "apply_onfi_synth", "ONFI 4.1", "ONFI_NAND_Target"),
    ("nfc_protocol_synth", "apply_nfc_synth",
     "NFC / ISO 14443", "NFC_ISO14443_Stack"),
    ("ufs_protocol_synth", "apply_ufs_synth",
     "Universal Flash Storage (JEDEC JESD220, UFS 4.0)", "UFS_Device"),
    ("zigbee_protocol_synth", "apply_zigbee_synth",
     "IEEE 802.15.4 + Zigbee LR-WPAN SoC", "ieee802154_zigbee_soc"),
    ("hbm3_protocol_synth", "apply_hbm3_synth",
     "High Bandwidth Memory 3 (JEDEC JESD238)", "HBM3_stack_on_interposer"),
    ("lpddr5_protocol_synth", "apply_lpddr5_synth",
     "LPDDR5 SDRAM (JEDEC JESD209-5)", "LPDDR5_SDRAM_component"),
    ("ddr_protocol_synth", "apply_ddr_synth",
     "DDR3 SDRAM (JEDEC JESD79-3C)", "DDR3_SDRAM_component"),
    ("rs485_protocol_synth", "apply_rs485_synth", "RS-485 (TIA/EIA-485-A)",
     "RS485_transceiver (external chip) + "
     "UART_with_DE/RE#_direction_control (on-chip)"),
]


# --------------------------------------------------------------------------
# The forward property: a pack's reference name does not become the
# design's identifier when the design already had one.
# --------------------------------------------------------------------------

def test_design_declared_top_module_survives_a_pack():
    """R1 — an input that declared `module <name>` keeps its name."""
    l9 = {
        "ic_name": "my_flash_ctrl",
        "top_module": "my_flash_ctrl",
        "top_module_extraction_strategy": "rtl_filesystem_scan",
    }
    ptm.apply(l9, "SPI")
    assert l9["top_module"] == "my_flash_ctrl"
    assert l9["top_module_extraction_strategy"] == "rtl_filesystem_scan"
    # and the identifier the scaffold derives is the design's, not the pack's
    assert derive_top_module_name({"ic_name": "my_flash_ctrl"}, l9,
                                  None) == "my_flash_ctrl"


@pytest.mark.parametrize("strategy", sorted(ptm.DESIGN_OWNED_STRATEGIES))
def test_every_design_owned_provenance_is_honoured(strategy):
    l9 = {"ic_name": "acc_top", "top_module": "acc_top",
          "top_module_extraction_strategy": strategy}
    ptm.apply(l9, "PC16550D")
    assert l9["top_module"] == "acc_top", (
        f"a pack overwrote a top module the design's own input named "
        f"(strategy={strategy})")


def test_pack_records_its_reference_name_in_a_descriptive_field():
    """The matched reference is recorded where no identifier comes from."""
    l9 = {"ic_name": "acc_top", "top_module": "acc_top",
          "top_module_extraction_strategy": "doc_module_decl_or_heading"}
    ptm.apply(l9, "PC16550D")
    rec = l9[ptm.REFERENCE_FIELD]
    assert rec["name"] == "PC16550D"
    assert rec["applied_to_top_module"] is False
    # No identifier is derived from the descriptive field: the scaffold
    # generator reads top_module / ic_name, and neither now carries it.
    assert "PC16550D" not in derive_top_module_name(
        {"ic_name": "acc_top"}, l9, None)


def test_pack_write_updates_the_provenance_it_invalidates():
    """R2 — the document stops claiming a provenance that is no longer true.

    This is the false-certificate half: 31 committed L9 documents carry a
    pack literal while asserting `l1_ic_name_fallback`.
    """
    l9 = {
        "ic_name": "SPI Block (S12SPIV4)",
        "top_module": "SPI_Block",
        "top_module_extraction_strategy": "l1_ic_name_fallback",
    }
    ptm.apply(l9, "SPI")
    assert l9["top_module"] == "SPI"
    assert l9["top_module_extraction_strategy"] != "l1_ic_name_fallback", (
        "the document still claims the name was derived from L1.ic_name "
        "after a pack replaced it with a reference literal")
    assert l9["top_module_extraction_strategy"] == ptm.PACK_DEFAULT_STRATEGY


def test_pack_write_never_leaves_top_module_empty():
    for start in ({}, {"top_module": ""}, {"top_module": "chip_top"}):
        l9 = dict(start, ic_name="x")
        ptm.apply(l9, "AHCI_HBA")
        assert l9.get("top_module"), f"top_module emptied from {start!r}"


# --------------------------------------------------------------------------
# The foreign-claim property, from the repo's own measured cases.
# --------------------------------------------------------------------------

def _run_two_packs(settled_ic, first_pack, first_top, second_ic):
    """Pack A writes top_module; pack B then wins the identity contest."""
    l9 = {
        "ic_name": "pre_pack_name",
        "top_module": "pre_pack_name",
        "top_module_extraction_strategy": "l1_ic_name_fallback",
    }
    # pack A: writes its own ic_name across the L docs, then its top module
    l9["ic_name"] = first_pack
    ptm.apply(l9, first_top)
    # pack B: co-fires later, writes ic_name, has no top_module of its own
    l9["ic_name"] = second_ic
    ptm.reconcile(l9, settled_ic)
    return l9


@pytest.mark.parametrize(
    "settled_ic,pack_ic,pack_top",
    [
        # measured in benchmark-data/evaluation/phase1_parity/*
        ("Bluetooth Low Energy 5.2 (Bluetooth Core Specification)",
         "PC16550D UART", "PC16550D"),
        ("IO-Link Interface (SDCI, IEC 61131-9)",
         "PC16550D UART", "PC16550D"),
        ("DDR4 SDRAM (JEDEC JESD79-4)",
         "DDR3 SDRAM (JEDEC JESD79-3C)", "DDR3_SDRAM_component"),
        ("GDDR6 SGRAM (JEDEC JESD250)",
         "High Bandwidth Memory 3 (JEDEC JESD238)",
         "HBM3_stack_on_interposer"),
        ("Quad/Octal SPI (xSPI / QSPI / OSPI, JESD251)",
         "SPI Block (S12SPIV4)", "SPI"),
        ("SAS_Controller", "Serial ATA AHCI 1.3.1", "AHCI_HBA"),
    ],
)
def test_a_foreign_packs_name_does_not_survive(settled_ic, pack_ic, pack_top):
    l9 = _run_two_packs(settled_ic, pack_ic, pack_top, settled_ic)
    assert l9["top_module"] != pack_top, (
        f"a design whose settled ic_name is {settled_ic!r} still tops out "
        f"as {pack_top!r}, which belongs to {pack_ic!r}")
    assert l9["top_module"] == "pre_pack_name"
    assert l9["top_module_extraction_strategy"] == "l1_ic_name_fallback"
    # the observable end state: the scaffold generator no longer derives
    # the foreign part name
    assert derive_top_module_name({"ic_name": settled_ic}, l9,
                                  None) == "pre_pack_name"


def test_foreign_claim_is_recorded_not_silently_dropped():
    l9 = _run_two_packs("Bluetooth Low Energy 5.2", "PC16550D UART",
                        "PC16550D", "Bluetooth Low Energy 5.2")
    rec = l9[ptm.REFERENCE_FIELD]
    assert rec["foreign_claim"] is True
    assert rec["name"] == "PC16550D"
    assert rec["settled_ic_name"] == "Bluetooth Low Energy 5.2"


# --------------------------------------------------------------------------
# REVERSE-2: the over-correction that reverts the RIGHT pack too.
# --------------------------------------------------------------------------

def test_the_identity_owners_own_name_is_kept():
    """A UART spec's top module still comes from the UART pack.

    This is the case a fix that reverts every pack write would break, and
    it is the reverse of every parametrised case above.
    """
    l9 = {
        "ic_name": "PC16550D UART",
        "top_module": "PC16550D_UART",
        "top_module_extraction_strategy": "l1_ic_name_fallback",
    }
    ptm.apply(l9, "PC16550D")
    change = ptm.reconcile(l9, "PC16550D UART")
    assert change is None, "reverted the pack that DID name this design"
    assert l9["top_module"] == "PC16550D"
    assert l9["top_module_extraction_strategy"] == ptm.PACK_DEFAULT_STRATEGY


def test_reconcile_leaves_non_pack_provenance_alone():
    """A name phase 1 derived is not this reconciler's business."""
    for strategy in ("l1_ic_name_fallback", "canonical_chip_top_sentinel",
                     "rtl_filesystem_scan"):
        l9 = {"ic_name": "a", "top_module": "chip_top",
              "top_module_extraction_strategy": strategy}
        assert ptm.reconcile(l9, "completely_different") is None
        assert l9["top_module"] == "chip_top"
        assert l9["top_module_extraction_strategy"] == strategy


# --------------------------------------------------------------------------
# REVERSE-3: the over-correction that is vacuous.
# --------------------------------------------------------------------------

def test_the_rule_is_not_vacuous():
    """At least one reachable input must actually change, in each direction."""
    reverted = _run_two_packs("design_x", "PC16550D UART", "PC16550D",
                              "design_x")
    assert reverted["top_module"] == "pre_pack_name"

    kept = {"ic_name": "PC16550D UART", "top_module": "PC16550D_UART",
            "top_module_extraction_strategy": "l1_ic_name_fallback"}
    ptm.apply(kept, "PC16550D")
    ptm.reconcile(kept, "PC16550D UART")
    assert kept["top_module"] == "PC16550D"

    protected = {"ic_name": "d", "top_module": "d_top",
                 "top_module_extraction_strategy": "rtl_filesystem_scan"}
    ptm.apply(protected, "PC16550D")
    assert protected["top_module"] == "d_top"


# --------------------------------------------------------------------------
# REVERSE-1: the gate the obvious fix breaks.
# --------------------------------------------------------------------------

#: What phase 1 leaves in L9 before any pack runs, in the shape the gate
#: reads. `top_module` + `top_ports` = exactly 2 of the 3 typed structural
#: fields the gate demands, plus `fsm_states` for the third — so the gate
#: verdict turns on whether `top_module` survives, which is the point.
#: `l1_ic_name_fallback` is phase 1's majority stamp (117 of 172 committed
#: L9 documents carry it).
_PRE_PACK_L9 = {
    "schema_version": 2,
    "doc_class": "integration_spec",
    "top_module": "design_declared_top",
    "top_module_extraction_strategy": "l1_ic_name_fallback",
    "top_ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst_n", "direction": "input", "width": 1},
    ],
    "fsm_states": [{"name": "IDLE"}, {"name": "BUSY"}],
}


def _l9_from_pack(pack_module, apply_fn_name, ic_name, tmp_path):
    """Run a real pack against a real generated_docs dir; return its L9."""
    import importlib

    gd = tmp_path / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(_PRE_PACK_L9) + "\n")
    for name in ("L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
                 "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
                 "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
                 "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
                 "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
                 "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
                 "L17_CHANNEL_CATALOG.json", "L19_CONSTRAINTS_PDK.json",
                 "L20_POWER_INTENT.json", "L22_VERIFICATION_PLAN.json",
                 "L23_BRINGUP_PLAN.json"):
        p = gd / name
        if not p.is_file():
            p.write_text(json.dumps({"schema_version": 2}) + "\n")
    mod = importlib.import_module(pack_module)
    getattr(mod, apply_fn_name)(gd, True, ic_name)
    return json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text())


@pytest.mark.parametrize(
    "pack_module,apply_fn,ic_name",
    [(m, fn, ic) for (m, fn, ic, _top) in _ALL_PACKS],
)
def test_l9_field_count_gate_still_passes_for_every_patched_pack(
        pack_module, apply_fn, ic_name, tmp_path):
    """The gate the obvious fix — "just stop writing top_module" — breaks.

    `l_doc_structured_field_count_check` counts a non-empty `top_module`
    toward L9's >=3 typed structural fields. This asserts the substance
    the gate reads, on an L9 each patched pack actually produced.
    """
    l9 = _l9_from_pack(pack_module, apply_fn, ic_name, tmp_path)
    assert isinstance(l9.get("top_module"), str) and l9["top_module"], (
        f"{pack_module} left L9.top_module empty — "
        f"l_doc_structured_field_count_check loses a typed field")


@pytest.mark.parametrize("pack_module,apply_fn,ic_name,pack_top", _ALL_PACKS)
def test_a_real_pack_does_not_rename_a_design_declared_top(
        pack_module, apply_fn, ic_name, pack_top, tmp_path):
    """R1, end-to-end through the real pack, not through the helper.

    This is the guard that stands between EVERY pack and the defect, and it
    is behavioural on purpose. It drives the real pack against an L9 whose
    own input declared `module my_own_block` (strategy `rtl_filesystem_scan`,
    a `DESIGN_OWNED_STRATEGY`) and asserts the pack left that name alone.

    Because it reads the OBSERVED end state — what `top_module` holds and
    what identifier `derive_top_module_name` produces — it catches a raw
    overwrite regardless of how the source spelled it: `d["top_module"] =`,
    `d['top_module'] =`, `_force(d, 'top_module', ...)`, an f-string, a
    concatenation, all land the same runtime value and all fail here. A
    source-text detector that keys on one quoting of one call site cannot
    say that; a behavioural one needs no enumeration of spellings. It is
    also why a DIFFERENT correct fix — one that keeps a local assignment but
    consults `_pack_top_module.decide` first — passes: the property, not the
    call site, is what is asserted.

    Extended from 4 packs to all 17 (`_ALL_PACKS`): the four originally
    listed were the only ones a behavioural test distinguished pre-fix from
    post-fix, leaving the other 13 guarded by source text alone.
    """
    import importlib

    gd = tmp_path / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    declared = dict(_PRE_PACK_L9)
    declared["top_module"] = "my_own_block"
    declared["top_module_extraction_strategy"] = "rtl_filesystem_scan"
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(declared) + "\n")
    for name in ("L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
                 "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
                 "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
                 "L8_TIMING_WAVEFORM.json", "L10_TEST_CASES.json",
                 "L11_OTP_CONTENT.json", "L12_BEHAVIORAL_SEQUENCES.json",
                 "L13_LAB_CALIBRATION.json", "L17_CHANNEL_CATALOG.json",
                 "L19_CONSTRAINTS_PDK.json", "L20_POWER_INTENT.json",
                 "L22_VERIFICATION_PLAN.json", "L23_BRINGUP_PLAN.json"):
        (gd / name).write_text(json.dumps({"schema_version": 2}) + "\n")

    mod = importlib.import_module(pack_module)
    getattr(mod, apply_fn)(gd, True, ic_name)
    l9 = json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text())

    assert l9["top_module"] == "my_own_block", (
        f"{pack_module} renamed a design whose own RTL declares "
        f"`module my_own_block` to {l9['top_module']!r}")
    assert derive_top_module_name({"ic_name": ic_name}, l9,
                                  None) == "my_own_block"
    assert l9[ptm.REFERENCE_FIELD]["name"] == pack_top


def _runner_tail_reconcile(gd):
    """What the runner does at the tail of the protocol-synth chain.

    Kept as a small local mirror rather than importing the 63k-line
    runner: it reads the two documents off disk and calls the reconciler,
    which is exactly the runner's step. It is not a stand-in for the fix
    — `reconcile` behaves identically whether or not the packs were
    patched; what changes is whether the packs left it anything to act on.
    """
    l9_path = gd / "L9_INTEGRATION_SPEC.json"
    l9 = json.loads(l9_path.read_text())
    l1 = json.loads((gd / "L1_DATASHEET.json").read_text())
    ptm.reconcile(l9, l1.get("ic_name"))
    l9_path.write_text(json.dumps(l9) + "\n")
    return l9


def test_two_real_packs_end_to_end_the_loser_does_not_keep_the_identifier(
        tmp_path):
    """The headline case, driven through both real packs and the runner tail.

    A Bluetooth document mentions start bits and stop bits, so the UART
    detector fires alongside the BLE detector. The UART pack writes
    `top_module`; the BLE pack has none and writes only `ic_name`. The
    committed artefact for `ble` records `top_module: "PC16550D"`.
    """
    import importlib

    gd = tmp_path / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(_PRE_PACK_L9) + "\n")
    for name in ("L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
                 "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
                 "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
                 "L8_TIMING_WAVEFORM.json", "L10_TEST_CASES.json",
                 "L11_OTP_CONTENT.json", "L12_BEHAVIORAL_SEQUENCES.json",
                 "L13_LAB_CALIBRATION.json", "L17_CHANNEL_CATALOG.json",
                 "L19_CONSTRAINTS_PDK.json", "L20_POWER_INTENT.json",
                 "L22_VERIFICATION_PLAN.json", "L23_BRINGUP_PLAN.json"):
        (gd / name).write_text(json.dumps({"schema_version": 2}) + "\n")

    ble_name = "Bluetooth Low Energy 5.2 (Bluetooth Core Specification)"
    importlib.import_module("uart_protocol_synth").apply_uart_synth(
        gd, True, "PC16550D UART")
    importlib.import_module("ble_protocol_synth").apply_ble_synth(
        gd, True, ble_name)
    l9 = _runner_tail_reconcile(gd)

    settled = json.loads((gd / "L1_DATASHEET.json").read_text())["ic_name"]
    assert settled == ble_name, "fixture precondition: BLE won the identity"
    assert l9["top_module"] != "PC16550D", (
        "a Bluetooth design still tops out as a 1980s UART part; "
        f"L1.ic_name={settled!r}")
    assert derive_top_module_name({"ic_name": settled}, l9,
                                  None) != "PC16550D"
    # and the field is still populated — the gate keeps its credit
    assert l9["top_module"]


def test_l9_field_count_gate_verdict_is_unchanged_by_this_fix(tmp_path):
    """Run the REAL gate predicate on a real pack's L9, both ways."""
    from l_doc_structured_field_count_check import _check_l_doc

    l9 = _l9_from_pack("spi_protocol_synth", "apply_spi_synth",
                       "SPI Block (S12SPIV4)", tmp_path)
    ok, why = _check_l_doc(9, l9, None, "unknown", tmp_path)
    assert ok, f"L9 lost its typed-field credit after the fix: {why}"

    # And the reverse, which is what makes the assertion above mean
    # something: drop ONLY `top_module` from the very same document. The
    # gate must now FAIL — proving `top_module` is load-bearing here and
    # that "just stop writing it" costs L9 a gate.
    stripped = dict(l9)
    stripped.pop("top_module", None)
    ok2, why2 = _check_l_doc(9, stripped, None, "unknown", tmp_path)
    assert not ok2, (
        "the gate passes an L9 with `top_module` removed, so the positive "
        f"assertion above proves nothing about this field ({why2})")


# --------------------------------------------------------------------------
# Behavioural sweep: every pack routes through the one decision, in any
# quoting style.
#
# This REPLACES an earlier source-text regex
# (`test_no_protocol_pack_assigns_l9_top_module_directly`) that matched only
# a double-quoted `d["top_module"] =` / `_force(d, "top_module"`. That
# detector named a spelling, not the fact, and failed in BOTH directions:
#
#   * it MISSED the same overwrite written `d['top_module'] = "..."` — a
#     single quote reintroduced the full defect (a design-declared top
#     renamed, its `rtl_filesystem_scan` provenance left standing as a false
#     certificate) while the suite stayed green; and
#   * it REJECTED a behaviourally-correct fix that kept a local assignment
#     after consulting `_pack_top_module.decide`.
#
# The property is quote-agnostic, so the guard must be too. Driving each
# real pack and reading the OBSERVED end state cannot be evaded by how the
# assignment was spelled, and cannot misfire on a different correct routing.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("pack_module,apply_fn,ic_name,pack_top", _ALL_PACKS)
def test_every_pack_routes_top_module_through_the_one_decision(
        pack_module, apply_fn, ic_name, pack_top, tmp_path):
    """R2, end-to-end: a pack that DOES fill an ungoverned top module leaves
    an honest provenance stamp behind it.

    Complementary direction to `test_a_real_pack_does_not_rename_a_design_
    declared_top`: here the L9 carries only a phase-1 fallback
    (`l1_ic_name_fallback`, NOT a `DESIGN_OWNED_STRATEGY`), so the pack is
    allowed to supply its reference literal. The two facts asserted are the
    two a raw overwrite — in ANY quoting style — cannot produce:

      * the reference literal is recorded in `REFERENCE_FIELD` (the pack
        went through `apply`, not around it); and
      * `top_module_extraction_strategy` is restamped to
        `PACK_DEFAULT_STRATEGY`, so the document stops asserting the
        pre-pack provenance it no longer has.

    A raw `d['top_module'] = "<literal>"` sets neither: no `REFERENCE_FIELD`,
    and the stale `l1_ic_name_fallback` stamp survives. Both assertions fail,
    for whatever quoting the reintroduction used.
    """
    import importlib

    gd = tmp_path / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(_PRE_PACK_L9) + "\n")
    for name in ("L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
                 "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
                 "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
                 "L8_TIMING_WAVEFORM.json", "L10_TEST_CASES.json",
                 "L11_OTP_CONTENT.json", "L12_BEHAVIORAL_SEQUENCES.json",
                 "L13_LAB_CALIBRATION.json", "L17_CHANNEL_CATALOG.json",
                 "L19_CONSTRAINTS_PDK.json", "L20_POWER_INTENT.json",
                 "L22_VERIFICATION_PLAN.json", "L23_BRINGUP_PLAN.json"):
        (gd / name).write_text(json.dumps({"schema_version": 2}) + "\n")

    mod = importlib.import_module(pack_module)
    getattr(mod, apply_fn)(gd, True, ic_name)
    l9 = json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text())

    rec = l9.get(ptm.REFERENCE_FIELD)
    assert isinstance(rec, dict) and rec.get("name") == pack_top, (
        f"{pack_module} did not record its reference literal {pack_top!r} in "
        f"{ptm.REFERENCE_FIELD} — it wrote L9.top_module around "
        f"_pack_top_module.apply, not through it (got {rec!r})")
    assert l9.get("top_module_extraction_strategy") == ptm.PACK_DEFAULT_STRATEGY, (
        f"{pack_module} filled L9.top_module but left the provenance stamp at "
        f"{l9.get('top_module_extraction_strategy')!r}; the document still "
        f"claims a name it no longer carries (the false-certificate shape)")
