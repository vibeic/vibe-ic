"""#638 — Comportable-style interface bullet block + Inter-Module-Signals
Act-role table harvest into L1.pin_table.

The auto-generated "Comportable" register-tool interface convention declares
the canonical top-level interface as a bullet block (Primary/Other Clocks +
Bus Device/Host Interfaces) plus an "Inter-Module Signals" pipe-table whose
DIRECTION is an `Act` (req/rcv/rsp) role column rather than an input/output
cell. Before #638 NONE of these were harvested:
  (a) the primary clock(s) and the primary device bus were dropped entirely;
  (b) the Inter-Module-Signals `req_rsp` bus row (e.g. `tl`) was dropped; and
  (c) the `<name>` token in the narrative intro sentence could leak as a
      phantom input port.

These tests invoke the REAL `gen_l1_datasheet` entry-point on synthetic
fixtures shaped like the 現象 and assert the END STATE (the on-disk
L1_DATASHEET.json pin_table), plus NEGATIVE no-leak cases (empty doc,
`*none*` bus, foreign doc, uni-only inter-signal table).
"""
import json
import sys
import tempfile
from pathlib import Path

_PROG_DIR = Path(__file__).resolve().parents[1]
if str(_PROG_DIR) not in sys.path:
    sys.path.insert(0, str(_PROG_DIR))

import phase1_doc_one_shot_runner as p1  # noqa: E402


# A defect-artifact fixture shaped exactly like the round-2 aes_interfaces.md
# 現象: a Comportable intro sentence (bold-backtick module name), a
# Primary/Other-Clock + Bus-Device-Interface bullet block, an Inter-Module
# Signals Act-role table (with the `tl` req_rsp/rsp device-bus row), and a
# secondary "Other Signals" input/output table that the old extractor caught.
_COMPORTABLE_DOC = """# Hardware Interfaces
<!-- BEGIN CMDGEN util/regtool.py --interfaces ./hw/ip/acc/data/acc.hjson -->
Referring to the [Comportable guideline](https://example/comportability), \
the module **`acc`** has the following hardware interfaces defined
- Primary Clock: **`clk_i`**
- Other Clocks: **`clk_edn_i`**
- Bus Device Interfaces (TL-UL): **`tl`**
- Bus Host Interfaces (TL-UL): *none*
- Peripheral Pins for Chip IO: *none*
- Interrupts: *none*

## Inter-Module Signals

| Port Name      | Package::Struct        | Type    | Act   |   Width | Description   |
|:---------------|:-----------------------|:--------|:------|--------:|:--------------|
| idle           | prim_mubi_pkg::mubi4   | uni     | req   |       1 |               |
| lc_escalate_en | lc_ctrl_pkg::lc_tx     | uni     | rcv   |       1 |               |
| edn            | edn_pkg::edn           | req_rsp | req   |       1 |               |
| keymgr_key     | keymgr_pkg::hw_key_req | uni     | rcv   |       1 |               |
| tl             | tlul_pkg::tl           | req_rsp | rsp   |       1 |               |
<!-- END CMDGEN -->

### Other Signals

Signal             | Direction        | Type                   | Description
-------------------|------------------|------------------------|------------
`idle_o`           | `output`         | `logic`                | Idle indication.
`lc_escalate_en_i` | `input`          | `lc_ctrl_pkg::lc_tx_t` | Escalation enable.
`edn_o`            | `output`         | `edn_pkg::edn_req_t`   | Entropy request.
`edn_i`            | `input`          | `edn_pkg::edn_rsp_t`   | Entropy input.
`keymgr_key_i`     | `input`          | `keymgr::hw_key_req_t` | Key sideload.
"""


def _run_l1(docs):
    """Invoke the REAL gen_l1_datasheet entry-point and return the on-disk
    pin_table list."""
    res = p1.gen_l1_datasheet(Path(tempfile.mkdtemp()), docs)
    data = json.loads(Path(res.path).read_text())
    return data.get("pin_table", [])


def _names(pins):
    return {p.get("name") for p in pins}


# --------------------------------------------------------------------------
# POSITIVE: the three facets the issue names are now harvested.
# --------------------------------------------------------------------------
def test_facet_a_primary_and_other_clocks_harvested():
    pins = _run_l1({"acc_interfaces.md": _COMPORTABLE_DOC})
    names = _names(pins)
    assert "clk_i" in names, "Primary Clock bullet must be harvested"
    assert "clk_edn_i" in names, "Other Clocks bullet must be harvested"
    # Clock ports are input clk-class.
    for pin in pins:
        if pin.get("name") in ("clk_i", "clk_edn_i"):
            assert pin.get("mode") == "input"
            assert pin.get("extraction_strategy") == "comportable_clock_bullet_v638"


def test_facet_b_intermodule_req_rsp_bus_row_harvested():
    pins = _run_l1({"acc_interfaces.md": _COMPORTABLE_DOC})
    names = _names(pins)
    assert "tl" in names, "Inter-Module-Signals req_rsp bus row `tl` must be harvested"
    tl = [p for p in pins if p.get("name") == "tl"][0]
    assert tl.get("mode") == "inout", "req_rsp struct bus is bidirectional"
    assert tl.get("extraction_strategy") == "comportable_intermodule_act_v638"


def test_facet_c_module_name_not_promoted_as_phantom_port():
    pins = _run_l1({"acc_interfaces.md": _COMPORTABLE_DOC})
    names_lower = {(p.get("name") or "").lower() for p in pins}
    assert "acc" not in names_lower, (
        "the Comportable intro module name must NOT become a phantom port")


def test_secondary_other_signals_table_still_harvested():
    # Round-1 behaviour preserved: the input/output Other-Signals table is
    # still picked up (no regression).
    pins = _run_l1({"acc_interfaces.md": _COMPORTABLE_DOC})
    names = _names(pins)
    for expected in ("idle_o", "edn_o", "keymgr_key_i"):
        assert expected in names


# --------------------------------------------------------------------------
# NEGATIVE no-leak cases — an empty / under-populated / foreign input must
# STILL be caught (no phantom ports manufactured).
# --------------------------------------------------------------------------
def test_no_leak_empty_doc():
    assert list(p1._v638_comportable_interface_harvest("")) == []
    assert p1._v638_comportable_module_name("") is None


def test_no_leak_none_bus_emits_no_bus_port():
    doc = (
        "the module `foo` has the following hardware interfaces defined\n"
        "- Primary Clock: `clk_i`\n"
        "- Bus Device Interfaces (TL-UL): *none*\n"
        "- Bus Host Interfaces (TL-UL): *none*\n"
        "- Interrupts: *none*\n"
    )
    out = list(p1._v638_comportable_interface_harvest(doc))
    names = {r["name"] for r in out}
    # The real clock survives; the *none* device/host bus emits nothing.
    assert names == {"clk_i"}


def test_no_leak_foreign_doc_emits_nothing():
    # A plain SPI doc with an ordinary input/output table has no Comportable
    # bullet block and no Act-role table — the harvester must emit nothing
    # (the normal GFM walker handles its input/output rows separately).
    foreign = (
        "# SPI Controller\n\n"
        "| Signal | Direction | Width |\n"
        "|--------|-----------|-------|\n"
        "| sclk   | output    | 1     |\n"
        "| mosi   | output    | 1     |\n"
    )
    assert list(p1._v638_comportable_interface_harvest(foreign)) == []


def test_no_leak_uni_only_intersignal_table_emits_nothing():
    # An Inter-Module-Signals table with only `uni`-Type rows (which already
    # surface direction-suffixed in the Other-Signals table) must NOT emit a
    # duplicate base-name port — only `req_rsp` struct bus rows are harvested.
    uni_only = (
        "## Inter-Module Signals\n\n"
        "| Port Name | Type | Act | Width |\n"
        "|-----------|------|-----|-------|\n"
        "| idle | uni | req | 1 |\n"
        "| esc  | uni | rcv | 1 |\n"
    )
    assert list(p1._v638_comportable_interface_harvest(uni_only)) == []


def test_no_leak_module_name_deny_only_fires_on_convention_sentence():
    # The module-name deny is keyed strictly to the Comportable intro
    # sentence shape; a doc that merely uses the same word as a real port
    # name is not affected.
    assert p1._v638_comportable_module_name(
        "# SPI Controller\n| sclk | output | 1 |\n") is None
    assert p1._v638_comportable_module_name(
        "the module `bar` has the following hardware interface\n") == "bar"
