"""Corpus guard: a protocol pack may OFFER a top-module name, never stamp one.

vibe-ic#831.  ``phase2_scaffold_gen.derive_top_module_name`` ranks
``L9.top_module`` above ``L1.ic_name``, so whatever writes ``L9.top_module``
last decides what the design is called.  Twenty ``*_protocol_synth.py`` packs
wrote it unconditionally with the name of a *reference part*, and the
replacement is a valid Verilog identifier, so nothing downstream could tell a
renamed design from one that really is called that.

WHY THIS GUARD DRIVES THE PACKS INSTEAD OF GREPPING THEM
--------------------------------------------------------
The obvious corpus guard is a source scan for ``d["top_module"] =``.  That
guard validates the SPELLING of the write, not the write — and this corpus
already contains four different spellings of the same act:

    d["top_module"] = "PC16550D"                 15 packs
    _force(d, "top_module", "...")                2 packs (rs485, tpm)
    "top_module": "chip_top"  inside a bulk       3 packs (espi, mdio, usb_pd)
        template later applied with dict.update

The issue itself counted only the first spelling and reported 15; driving the
packs found 20.  A spelling guard would have been green on five packs that
have the defect, and the 21st pack only has to pick a sixth spelling.  So this
guard executes every pack against a seeded document set and reads the RESULT.

AUTO-DISCOVERY: every ``<stem>_protocol_synth.py`` exposing
``apply_<stem>_synth`` is covered with zero new test code, in the same shape
as ``test_protocol_detector_no_misfire.py``.
"""
from __future__ import annotations

import glob
import importlib
import json
import os
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parent.parent

import protocol_pack_identity as identity  # noqa: E402
from phase2_scaffold_gen import derive_top_module_name  # noqa: E402

# The document set a pack expects to find on disk.  Union of every filename
# any pack reads; a pack skips any file that is absent, so a superset is
# correct and keeps a new pack's new document covered automatically.
L_DOCS = (
    "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
    "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
    "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json", "L8_TIMING_WAVEFORM.json",
    "L9_INTEGRATION_SPEC.json", "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
    "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
    "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
    "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
    "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
    "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
    "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
)

# The design under test.  Deliberately a name no protocol pack could know.
DESIGN_IC_NAME = "AcmeWidget42 Sensor Frontend"
DESIGN_TOP = "acme_widget42_top"


def _packs():
    out = []
    for path in sorted(glob.glob(str(PROGRAMS_DIR / "*_protocol_synth.py"))):
        stem = os.path.basename(path)[: -len("_protocol_synth.py")]
        try:
            mod = importlib.import_module(f"{stem}_protocol_synth")
        except Exception:  # pragma: no cover - import guarded elsewhere
            continue
        fn = getattr(mod, f"apply_{stem}_synth", None)
        if callable(fn):
            out.append((stem, fn))
    return out


PACKS = _packs()
PACK_IDS = [s for s, _ in PACKS]


def test_discovery_found_the_pack_corpus():
    """The guard is worthless if it silently discovers nothing.

    `pytest` exits 0 when no tests ran, and a parametrisation over an empty
    list is exactly that failure wearing a green shirt.
    """
    assert len(PACKS) >= 80, (
        f"expected the ~86-file *_protocol_synth.py corpus, discovered "
        f"{len(PACKS)}: {PACK_IDS[:10]}")


def _drive(tmp_path, stem, fn, l9_seed, l1_seed=None):
    gd = tmp_path / stem
    gd.mkdir(parents=True, exist_ok=True)
    for name in L_DOCS:
        if name == "L9_INTEGRATION_SPEC.json":
            payload = dict(l9_seed)
        elif name == "L1_DATASHEET.json":
            payload = dict(l1_seed if l1_seed is not None
                           else {"ic_name": DESIGN_IC_NAME})
        else:
            payload = {"ic_name": DESIGN_IC_NAME}
        (gd / name).write_text(json.dumps(payload))
    # `is_<proto>` is passed True: the guard asks what a pack does WHEN IT
    # FIRES.  Whether it should have fired is a different guard's question
    # (test_protocol_detector_no_misfire.py).
    fn(gd, True, DESIGN_IC_NAME)
    l9 = json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text())
    l1 = json.loads((gd / "L1_DATASHEET.json").read_text())
    return l1, l9


@pytest.mark.parametrize("stem,fn", PACKS, ids=PACK_IDS)
def test_pack_does_not_overwrite_a_design_supplied_top_module(
        tmp_path, stem, fn):
    """CONTROL A — the defect itself, in the shape Phase 1 actually emits.

    `phase1_doc_one_shot_runner` never leaves `L9.top_module` unset: every
    extractor that produces one records WHERE it came from in
    `top_module_extraction_strategy`, and `l1_ic_name_fallback` means "this
    name is the design's own `L1.ic_name`".  A pack that overwrites that is
    renaming a design that named itself.

    Bidirectional: measured at e3aa9b126 this assertion fails for 20 packs
    (hbm3 dali ddr lin lpddr5 nfc onfi sata modbus nvme sdmmc zigbee uart ufs
    spi rs485 tpm espi mdio usb_pd) and passes for the rest.
    """
    l1, l9 = _drive(tmp_path, stem, fn, {
        "ic_name": DESIGN_IC_NAME,
        "top_module": DESIGN_TOP,
        "top_module_extraction_strategy": "l1_ic_name_fallback",
    })
    assert l9.get("top_module") == DESIGN_TOP, (
        f"{stem}_protocol_synth overwrote a design-supplied L9.top_module "
        f"({DESIGN_TOP!r}, provenance l1_ic_name_fallback) with "
        f"{l9.get('top_module')!r}. A pack knows the name of a REFERENCE "
        f"implementation of its protocol; it does not know the name of THIS "
        f"design. Offer it via protocol_pack_identity."
        f"offer_reference_top_module instead.")
    assert derive_top_module_name(l1, l9, DESIGN_IC_NAME) == DESIGN_TOP


@pytest.mark.parametrize("stem,fn", PACKS, ids=PACK_IDS)
def test_pack_does_not_overwrite_an_unprovenanced_top_module(tmp_path, stem, fn):
    """CONTROL A' — fail-safe when provenance is ABSENT, not just unfamiliar.

    A hand-authored or AI-extracted L9 records no strategy at all (54 of the
    197 tracked L9 documents in this repository are in that shape).  "Could
    not measure the provenance" must resolve to "leave the design's name
    alone", never to "assume it is mine to take".
    """
    _, l9 = _drive(tmp_path, stem, fn, {
        "ic_name": DESIGN_IC_NAME,
        "top_module": DESIGN_TOP,
    })
    assert l9.get("top_module") == DESIGN_TOP, (
        f"{stem}_protocol_synth overwrote an L9.top_module whose provenance "
        f"is unrecorded. Unknown provenance must fail safe toward the "
        f"document, not toward the pack.")


@pytest.mark.parametrize("stem,fn", PACKS, ids=PACK_IDS)
def test_pack_may_fill_the_gap_and_never_leaves_a_lying_provenance(
        tmp_path, stem, fn):
    """CONTROL B — the REVERSE case, plus the invariant that broke in publish.

    `canonical_chip_top_sentinel` is the one strategy that means Phase 1
    exhausted every extractor and nothing in the design named a top module.
    That IS a gap, and a pack filling it is the point of the pack — the issue
    asks that such a design "still gets a usable top module rather than
    falling to `dut` unannounced".

    The invariant: if the value CHANGED, the provenance must say so.  Pre-fix,
    15 published documents carry a pack's reference name next to
    `top_module_extraction_strategy == "l1_ic_name_fallback"` — a tag another
    program earned, left standing over a value it did not produce, so a
    consumer reading the provenance is told a falsehood with no way to check.
    """
    seeded = "chip_top"
    l1, l9 = _drive(tmp_path, stem, fn, {
        "ic_name": DESIGN_IC_NAME,
        "top_module": seeded,
        "top_module_extraction_strategy": "canonical_chip_top_sentinel",
    })
    top = l9.get("top_module")
    strategy = l9.get("top_module_extraction_strategy")

    assert identity.is_bare_identifier(top), (
        f"{stem}_protocol_synth left L9.top_module = {top!r}, which is not a "
        f"bare Verilog identifier. derive_top_module_name would coerce it, "
        f"and a coerced name is byte-identical to a real one downstream.")
    assert derive_top_module_name(l1, l9, DESIGN_IC_NAME) != "dut", (
        f"{stem}_protocol_synth left the design with the anonymous fallback.")

    if top != seeded:
        assert strategy == identity.PACK_STRATEGY, (
            f"{stem}_protocol_synth changed L9.top_module {seeded!r} -> "
            f"{top!r} but left top_module_extraction_strategy = {strategy!r}. "
            f"The value and its provenance now disagree and nothing "
            f"downstream can tell.")


@pytest.mark.parametrize("stem,fn", PACKS, ids=PACK_IDS)
def test_pack_never_claims_a_provenance_it_did_not_earn(tmp_path, stem, fn):
    """CONTROL C — the pack must not forge a DESIGN-derived provenance.

    Stamping `rtl_filesystem_scan` would make a pack's guess indistinguishable
    from a name really read out of the design's RTL, and would defeat
    CONTROL A on the next run.
    """
    _, l9 = _drive(tmp_path, stem, fn, {
        "ic_name": DESIGN_IC_NAME,
        "top_module": "chip_top",
        "top_module_extraction_strategy": "canonical_chip_top_sentinel",
    })
    strategy = l9.get("top_module_extraction_strategy")
    assert strategy in ("canonical_chip_top_sentinel", identity.PACK_STRATEGY), (
        f"{stem}_protocol_synth stamped top_module_extraction_strategy = "
        f"{strategy!r}. A pack may only ever claim "
        f"{identity.PACK_STRATEGY!r}.")


# ---------------------------------------------------------------------------
# The chokepoint's own unit contract
# ---------------------------------------------------------------------------

def test_offer_declines_prose_and_keeps_it_as_documentation():
    """The RS-485 case: a sentence is documentation, not an identifier."""
    prose = ("RS485_transceiver (external chip) + "
             "UART_with_DE/RE#_direction_control (on-chip)")
    l9 = {}
    assert identity.offer_reference_top_module(l9, prose) is None
    assert l9["reference_design"] == prose
    assert "top_module" not in l9
    # And the truncation it used to cause is real, not hypothetical:
    assert derive_top_module_name({}, {"top_module": prose}, None) == \
        "RS485_transceiver"


def test_offer_fills_a_gap_and_stamps_its_own_provenance():
    l9 = {"top_module": "chip_top",
          "top_module_extraction_strategy": "canonical_chip_top_sentinel"}
    assert identity.offer_reference_top_module(l9, "PC16550D") == "PC16550D"
    assert l9["top_module"] == "PC16550D"
    assert l9["top_module_extraction_strategy"] == identity.PACK_STRATEGY
    assert l9["reference_design"] == "PC16550D"


def test_offer_stands_down_for_every_design_derived_strategy():
    for strategy in ("rtl_filesystem_scan", "staged_rtl_structural_top",
                     "doc_module_decl_or_heading", "l1_ic_name_fallback",
                     "a_strategy_invented_after_this_test_was_written"):
        l9 = {"top_module": "acme_top",
              "top_module_extraction_strategy": strategy}
        assert identity.offer_reference_top_module(l9, "PC16550D") is None, \
            strategy
        assert l9["top_module"] == "acme_top", strategy
        assert l9["top_module_extraction_strategy"] == strategy, strategy
        assert l9["reference_design"] == "PC16550D", strategy


def test_merge_pack_payload_routes_top_module_but_merges_the_rest():
    l9 = {"top_module": "acme_top",
          "top_module_extraction_strategy": "rtl_filesystem_scan"}
    identity.merge_pack_payload(
        l9, {"top_module": "chip_top", "submodules": [{"name": "core"}]})
    assert l9["top_module"] == "acme_top"
    assert l9["submodules"] == [{"name": "core"}]
    assert l9["reference_design"] == "chip_top"


def test_offer_refuses_an_empty_reference_name():
    with pytest.raises(ValueError):
        identity.offer_reference_top_module({}, "   ")
