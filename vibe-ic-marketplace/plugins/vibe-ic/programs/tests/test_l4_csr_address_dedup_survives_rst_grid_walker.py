"""L4 address-dedup must SURVIVE the rst-grid CSR walker.

v1.6.270 added an address-keyed dedup pass to `gen_l4_regmap` for the
exact shape RV-style CSR docs produce: the same register appears TWICE —
once in the summary table (canonical name) and once in the section walker
(synthesised `csr_<addr>` name, because the name lookback could not
recover the canonical name from the heading). That pass keys on ADDRESS
ONLY and prefers the non-synthesised name, precisely so one address ends
up owned by one register.

v1.6.566's rst-grid CSR walker then runs AFTER that pass and appends its
rows keyed on the COMPOSITE `(address, name)`. A pre-existing entry whose
name was synthesised (`csr_341`) can never match the walker's canonical
name (`wstat`) for the same address, so the walker APPENDS a second
register at an address that already has one — re-creating exactly the
duplicate shape v1.6.270 exists to eliminate. Nothing re-merges
afterwards.

Downstream, `l4_regmap_phase2_emitter_contract_check` FAILs phase 1 with
"N address(es) are claimed by more than one register — the address decode
emit_regs_v() scaffolds is ambiguous", so the whole run halts at phase 1.

Whether a given address survives is pure coincidence: it depends on
whether some OTHER pre-walker extractor happened to also emit the
canonical name (making the composite key match). In the fixture below
0x340 is named twice pre-walker and collapses correctly, while 0x341 is
only ever named by the walker and duplicates — same doc, same grammar.

chip-AGNOSTIC: generic widget vocabulary; the defect is in the dedup
ordering, not in any chip's register names.
"""
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as R  # noqa: E402


# Mirrors the canonical RV-doc shape with NO chip vocabulary:
#   * a summary grid table naming each register in double backticks
#   * a per-register section whose heading puts the name in BARE
#     parentheses — a form none of the `_csr_name_lookback_patterns`
#     match, so the section walker synthesises `csr_<addr>`.
_TWO_SHAPES = """Widget Control Registers
========================

Register Map
------------

+---------+--------------------+--------+-----------------------------------+
| Address | Name               | Access | Description                       |
+=========+====================+========+===================================+
|  0x340  | ``wctl``           | RW     | Widget control register           |
+---------+--------------------+--------+-----------------------------------+
|  0x341  | ``wstat``          | R      | Widget status register            |
+---------+--------------------+--------+-----------------------------------+

Register Details
----------------

Widget Control (wctl)
---------------------

CSR Address: ``0x340``

Reset Value: ``0x0000_0000``

Controls widget operation.

Widget Status (wstat)
---------------------

CSR Address: ``0x341``

Reset Value: ``0x0000_0000``

Reports widget status.
"""

# A doc with two genuinely DISTINCT addresses and no second shape — the
# no-leak control: dedup must not collapse distinct addresses.
_DISTINCT_ONLY = """Sensor Registers
================

+---------+--------------------+--------+-----------------------------------+
| Address | Name               | Access | Description                       |
+=========+====================+========+===================================+
|  0x100  | ``sctl``           | RW     | Sensor control                    |
+---------+--------------------+--------+-----------------------------------+
|  0x104  | ``sdata``          | R      | Sensor data                       |
+---------+--------------------+--------+-----------------------------------+
"""


def _registers_for(doc_name, text):
    with tempfile.TemporaryDirectory() as td:
        res = R.gen_l4_regmap(Path(td), {doc_name: text})
        path = Path(res.path)
        assert path.exists(), f"gen_l4_regmap wrote no {path.name}"
        return json.loads(path.read_text()).get("registers", [])


def _by_address(registers):
    by = defaultdict(list)
    for r in registers:
        addr = r.get("address")
        if isinstance(addr, str) and addr.startswith("0x"):
            by[addr.lower()].append(r)
    return by


def test_no_address_is_claimed_by_two_registers():
    """The invariant the phase2 emitter contract depends on."""
    registers = _registers_for("widget_regs.rst", _TWO_SHAPES)
    by = _by_address(registers)
    duplicated = {
        addr: [r.get("name") for r in rs]
        for addr, rs in by.items() if len(rs) > 1
    }
    assert not duplicated, (
        "address(es) claimed by more than one register — the address "
        f"decode emit_regs_v() scaffolds is ambiguous: {duplicated}"
    )


def test_canonical_name_wins_over_synthesised_placeholder():
    """`csr_<addr>` is a placeholder for "name unknown". When the
    canonical name is recovered it must REPLACE the placeholder, not sit
    beside it."""
    registers = _registers_for("widget_regs.rst", _TWO_SHAPES)
    by = _by_address(registers)
    for addr, expected in (("0x340", "wctl"), ("0x341", "wstat")):
        entries = by.get(addr)
        assert entries, f"{addr} vanished from the register map"
        names = [r.get("name") for r in entries]
        assert expected in names, (
            f"{addr}: canonical name {expected!r} lost; got {names}")
        assert not any(
            isinstance(n, str) and n.lower() == f"csr_{addr[2:]}"
            for n in names), (
            f"{addr}: synthesised placeholder survived alongside the "
            f"canonical name; got {names}")


def test_distinct_addresses_are_not_over_merged():
    """No-leak: the dedup must key on address, so two DIFFERENT
    addresses stay two registers."""
    registers = _registers_for("sensor_regs.rst", _DISTINCT_ONLY)
    by = _by_address(registers)
    for addr in ("0x100", "0x104"):
        assert len(by.get(addr, [])) == 1, (
            f"{addr}: expected exactly one register, got "
            f"{[r.get('name') for r in by.get(addr, [])]}")
    names = {r.get("name") for r in registers}
    assert {"sctl", "sdata"} <= names, (
        f"distinct registers were over-merged; names={names}")


def test_real_rv_style_doc_has_no_duplicate_addresses():
    """Integration on the real vendor doc that exposed this: every
    address must be owned by exactly one register."""
    # Repo-relative so the proof travels with any checkout; skipped
    # (never failed) when benchmark-data is not vendored alongside.
    repo_root = PLUGIN.parent.parent.parent
    matches = sorted(
        (repo_root / "benchmark-data" / "ic").glob(
            "*/input/docs/*cs_registers.rst"))
    if not matches:
        import pytest
        pytest.skip("vendor CSR doc fixture not present in this checkout")
    doc = matches[0]
    registers = _registers_for(doc.name, doc.read_text())
    by = _by_address(registers)
    duplicated = {
        addr: [r.get("name") for r in rs]
        for addr, rs in by.items() if len(rs) > 1
    }
    assert not duplicated, (
        f"{len(duplicated)} address(es) claimed by more than one "
        f"register: {duplicated}")
