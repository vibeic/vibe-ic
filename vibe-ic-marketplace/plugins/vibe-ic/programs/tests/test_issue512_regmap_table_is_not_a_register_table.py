"""#512 — five L4 "registers" on a real design are an interrupt-cause table and
three Debug-Module parameter addresses; the emitter-contract gate caught only
the two that happened to be nameless.

MEASURED (re-derivation of `benchmark-data/ic/ibex` from `input/` only)::

    L4 registers by extraction_strategy
      hdl_typedef_enum_address_v1_7_74   102     0 nameless
      rst_grid_csr_v1_6_566               42     0 nameless   <- the real CSRs
      rst_grid_table_match                 5     2 nameless   <- all five wrong
      asciidoc_rowspan_fields              1

    (EMPTY)          0xffffffe0   ibex_exception_interrupts   internal interrupt
    (EMPTY)          0x8000001f   ibex_exception_interrupts   External NMI
    DmBaseAddr       0x1a110000   ibex_integration            Debug Module base
    DmHaltAddr       0x1a110800   ibex_integration            Debug Mode entry
    DmExceptionAddr  0x1a110808   ibex_integration            Debug exception

`l4_regmap_phase2_emitter_contract_check` FAILed on the two nameless ones only
("1 Verilog identifier(s) are claimed by 2 different L4 registers"). Naming or
dropping just those turns the gate green and leaves three fabricated registers
standing, because carrying a name is not evidence of being a register.

THE RULE, decided by the TABLE's own structure — never by prose, a design name,
a document filename or a token spelling
=======================================
  R1  A table whose ONLY address-role column was claimed by a VALUE header
      (`default` / `value` / `reset value`) describes no address space. Such a
      header states what a thing is SET TO, not where it LIVES. A table that
      ALSO carries a strong `address` / `offset` / `csr address` header is
      unaffected — that column IS the address space.
  R2  A table with no NAME-bearing column yields no registers. The absent name
      is not a gap in the extraction; it is the document saying this column is
      not an address space. Interrupt-cause tables, memory-map segment tables
      and error-code tables have this shape in every vendor's documentation.
  R3  A row read and not emitted is DISCLOSED. Silence is the same defect one
      layer down: the flow otherwise cannot tell "the documents declare no such
      register" from "we read it and threw it away".

FALSIFIABLE BOTH WAYS (driven, not inspected)
=============================================
  * the 42 `rst_grid_csr_v1_6_566` rows on the same documents are byte-identical
    before and after — pinned here on the verbatim CSR-table shape;
  * a corpus re-derivation over the 71 design roots that have `input/docs/`
    staged loses registers in exactly two designs and gains none: the five above
    and seven one-hot FIELD ENCODINGS on a second design's `| Value | Name |
    Description |` tables (`AES_ECB @ 0x01` … `AES_NONE @ 0x3f`), which the same
    R1 removes and which are likewise not registers.

chip-AGNOSTIC: pure table-grammar and generic documentation vocabulary; no
vendor, SKU, design or register spelling appears in the decision.
"""
import collections
import json
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import regmap_table_extractor as R  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


# --- fixtures quoted VERBATIM from the real documents the defect was measured on

# ibex_exception_interrupts.rst — 2 columns, no name column. The wrapped
# continuation rows are kept so the fixture is the real shape, not a tidied one.
_CAUSE_TABLE = (
    "The possible ``mcause`` values for an internal interrupt are listed below:\n"
    "\n"
    "+-------------+------------------------------------------+\n"
    "| ``mcause``  | Description                              |\n"
    "+=============+==========================================+\n"
    "| 0xFFFFFFE0  | Load integrity error internal interrupt. |\n"
    "|             | Only generated when SecureIbex == 1.     |\n"
    "+-------------+------------------------------------------+\n"
    "| 0x8000001F  | External NMI                             |\n"
    "+-------------+------------------------------------------+\n"
)

# ibex_integration.rst Parameters table — a NAME column, and the only
# address-role column the header can name is `Default`.
_PARAMETERS_TABLE = (
    "+---------------------+------------+------------+--------------------------+\n"
    "| Name                | Type/Range | Default    | Description              |\n"
    "+=====================+============+============+==========================+\n"
    "| ``PMPEnable``       | bit        | 0          | Enable PMP support       |\n"
    "+---------------------+------------+------------+--------------------------+\n"
    "| ``DmBaseAddr``      | int        | 0x1A110000 | Base address of the DM   |\n"
    "+---------------------+------------+------------+--------------------------+\n"
    "| ``DmHaltAddr``      | int        | 0x1A110800 | Address to jump to when  |\n"
    "+---------------------+------------+------------+--------------------------+\n"
    "| ``DmExceptionAddr`` | int        | 0x1A110808 | Address on an exception  |\n"
    "+---------------------+------------+------------+--------------------------+\n"
)

# ibex_cs_registers.rst — the REAL CSR table shape the other half of the L4 comes
# from: >= 3 columns, one a NAME, one an ACCESS type, and a STRONG address header.
_CSR_TABLE = (
    "+---------+-------------+-------+----------------------------------+\n"
    "| Address | Name        | Access| Description                      |\n"
    "+=========+=============+=======+==================================+\n"
    "| 0x300   | ``mstatus`` | WARL  | Machine Status                   |\n"
    "+---------+-------------+-------+----------------------------------+\n"
    "| 0x305   | ``mtvec``   | WARL  | Machine Trap-Vector Base Address |\n"
    "+---------+-------------+-------+----------------------------------+\n"
    "| 0x341   | ``mepc``    | WARL  | Machine Exception Program Counter|\n"
    "+---------+-------------+-------+----------------------------------+\n"
)

# aes_registers.md — an enumerated one-hot FIELD-VALUE table (GFM pipe shape).
# `Value` is the only address-role header; the hex is an encoding, not a place.
_ENUM_VALUE_TABLE = (
    "### CTRL_SHADOWED . MODE\n"
    "\n"
    "| Value | Name     | Description                          |\n"
    "|:------|:---------|:-------------------------------------|\n"
    "| 0x01  | AES_ECB  | 6'b00_0001: Electronic Codebook mode |\n"
    "| 0x02  | AES_CBC  | 6'b00_0010: Cipher Block Chaining    |\n"
    "| 0x3f  | AES_NONE | 6'b11_1111: invalid values map here  |\n"
)


def _rows(doc, path="d.rst"):
    return R.extract_regmap_table(doc, path)


def _emitted(doc, path="d.rst"):
    return {(r.get("addr_hex"), r.get("name")) for r in _rows(doc, path)}


def _drive(doc, path="d.rst"):
    disc = []
    rows = R.extract_regmap_table(doc, path, disclosures=disc)
    return rows, disc


# --- R2: a table with no name-bearing column is not a register table ----------

def test_cause_table_yields_no_registers():
    rows, disc = _drive(_CAUSE_TABLE, "ibex_exception_interrupts.txt")
    assert rows == [], (
        "a 2-column cause table still produced registers: "
        f"{[(r.get('addr_hex'), r.get('name')) for r in rows]}")
    assert [d["reason"] for d in disc] == [R.NOT_REGISTERS_NO_NAME_COLUMN]


def test_cause_table_addresses_are_disclosed_not_silently_dropped():
    """R3 — the record has to name what it declined, or the flow cannot tell an
    absent register from a discarded one."""
    _rows_, disc = _drive(_CAUSE_TABLE, "ibex_exception_interrupts.txt")
    assert len(disc) == 1, disc
    rec = disc[0]
    assert rec["source"] == "ibex_exception_interrupts.txt"
    assert sorted(rec["addresses_read_and_dropped"]) == [
        "0x8000001f", "0xffffffe0"], rec
    assert rec["registers_emitted"] == 0
    assert rec["rows_read"] >= 2
    assert rec["header"] == ["``mcause``", "Description"], rec
    assert "no name-bearing column" in rec["detail"]


def test_no_nameless_register_is_ever_emitted():
    """The defect's own signature: the emitter declares one `reg` per register,
    so two registers named "" collide on a single Verilog identifier. No path
    may emit one."""
    for doc in (_CAUSE_TABLE, _PARAMETERS_TABLE, _CSR_TABLE, _ENUM_VALUE_TABLE):
        for r in _rows(doc):
            assert (r.get("name") or "").strip(), (
                f"nameless register emitted from:\n{doc[:120]}\n{r}")


# --- R1: an address role claimed only by a VALUE column is not an address space

def test_parameter_default_column_yields_no_registers():
    """The three NAMED non-registers. They are dropped for the same structural
    reason as the nameless pair, not spared for having names."""
    rows, disc = _drive(_PARAMETERS_TABLE, "ibex_integration.txt")
    assert rows == [], (
        "Debug-Module parameter addresses still became registers: "
        f"{[(r.get('addr_hex'), r.get('name')) for r in rows]}")
    assert [d["reason"] for d in disc] == [R.NOT_REGISTERS_VALUE_COLUMN_ONLY]
    assert sorted(disc[0]["addresses_read_and_dropped"]) == [
        "0x1a110000", "0x1a110800", "0x1a110808"], disc


def test_named_non_registers_are_not_spared_by_having_names():
    """Guards the exact half-fix the issue names: a change that only stops the
    nameless rows treats the gate, not the defect. Emitting `DmBaseAddr` while
    refusing the cause codes would pass every other test in this file."""
    named = {n for (_a, n) in _emitted(_PARAMETERS_TABLE, "ibex_integration.txt")}
    assert named == set(), f"named parameter addresses survived: {named}"


def test_enum_value_table_yields_no_registers_gfm_path():
    """The same rule on the GFM pipe path — measured on a second design, where
    it removed seven one-hot field encodings that had become registers."""
    rows, disc = _drive(_ENUM_VALUE_TABLE, "aes_registers.md")
    assert rows == [], (
        "enumerated field values still became registers: "
        f"{[(r.get('addr_hex'), r.get('name')) for r in rows]}")
    assert [d["reason"] for d in disc] == [R.NOT_REGISTERS_VALUE_COLUMN_ONLY]
    assert sorted(disc[0]["addresses_read_and_dropped"]) == [
        "0x01", "0x02", "0x3f"], disc


# --- the other direction: the real register tables must survive UNCHANGED -----

def test_real_csr_table_survives_unchanged():
    """A >=3-column table with a NAME column, an ACCESS type and a STRONG
    address header is exactly what a register table looks like."""
    got = _emitted(_CSR_TABLE, "ibex_cs_registers.txt")
    assert got == {("0x300", "mstatus"), ("0x305", "mtvec"),
                   ("0x341", "mepc")}, got
    _r, disc = _drive(_CSR_TABLE, "ibex_cs_registers.txt")
    assert disc == [], f"a clean CSR table should disclose nothing; {disc}"


@pytest.mark.parametrize("weak_hdr", ["Reset Value", "Default", "Value"])
def test_strong_address_column_beside_a_value_column_still_extracts(weak_hdr):
    """R1 must never fire on a table that DOES name an address space. Both
    column orders, because column order must not decide whether a real address
    column is seen (`_rst_header_roles` is strong-preferred)."""
    strong_first = (
        f"+----------------+-------------+-------------+\n"
        f"| Event Selector | CSR Address | {weak_hdr} |\n"
        f"+================+=============+=============+\n"
        f"| ``mhpmevent4`` | 0x324       | 0x0000_0010 |\n"
        f"+----------------+-------------+-------------+\n")
    weak_first = (
        f"+----------------+-------------+-------------+\n"
        f"| Event Selector | {weak_hdr} | CSR Address |\n"
        f"+================+=============+=============+\n"
        f"| ``mhpmevent4`` | 0x0000_0010 | 0x324       |\n"
        f"+----------------+-------------+-------------+\n")
    for doc, label in ((strong_first, "strong-first"), (weak_first, "weak-first")):
        got = _emitted(doc, "perf.rst")
        assert got == {("0x324", "mhpmevent4")}, f"{label}: {got}"


def test_structural_fallback_still_recovers_a_named_address_column():
    """R2 removes the NAMELESS structural emit, not the structural fallback: a
    grid whose headers are in no keyword set still yields its registers when an
    identifier column is there to name them."""
    doc = (
        "+-----------+----------+---------------------+\n"
        "| Location  | Mnemonic | What it does        |\n"
        "+===========+==========+=====================+\n"
        "| 0x40      | ctrl     | starts the engine   |\n"
        "+-----------+----------+---------------------+\n"
        "| 0x44      | status   | reports busy        |\n"
        "+-----------+----------+---------------------+\n")
    assert _emitted(doc, "x.rst") == {("0x40", "ctrl"), ("0x44", "status")}


def test_partially_named_table_emits_the_named_rows_and_discloses_the_rest():
    """A table that names most of its rows keeps them; the unnamed rows are
    dropped and counted, so the record states how many survived."""
    doc = (
        "+-----------+----------+---------------------+\n"
        "| Location  | Mnemonic | What it does        |\n"
        "+===========+==========+=====================+\n"
        "| 0x40      | ctrl     | starts the engine   |\n"
        "+-----------+----------+---------------------+\n"
        "| 0x48      |          | reserved            |\n"
        "+-----------+----------+---------------------+\n")
    rows, disc = _drive(doc, "x.rst")
    assert {(r["addr_hex"], r["name"]) for r in rows} == {("0x40", "ctrl")}
    assert [d["reason"] for d in disc] == [R.ROW_DROPPED_NO_NAME], disc
    assert disc[0]["rows_dropped"] == 1
    assert disc[0]["registers_emitted"] == 1
    assert disc[0]["addresses_read_and_dropped"] == ["0x48"], disc


# --- the disclosure channel itself --------------------------------------------

def test_disclosures_default_off_leaves_behaviour_identical():
    """The channel is caller-supplied: no global state, no I/O, and omitting it
    changes nothing about what is extracted."""
    for doc in (_CAUSE_TABLE, _PARAMETERS_TABLE, _CSR_TABLE, _ENUM_VALUE_TABLE):
        without = R.extract_regmap_table(doc, "d.rst")
        with_ = R.extract_regmap_table(doc, "d.rst", disclosures=[])
        assert without == with_


def test_bare_architecture_register_spelling_as_a_header_yields_nothing():
    """#512 also removed one architecture's specific CSR spelling from the NAME
    header vocabulary: a token naming one architecture's register is not
    documentation vocabulary, and column roles must come from table shape. This
    drives the shape the token used to cover — a BARE header cell, no inline
    markup — and it must be decided the same way as the marked-up one: a
    2-column address/prose table has no name column, so no registers."""
    doc = (
        "+-------------+------------------------------+\n"
        "| mcause      | Description                  |\n"
        "+=============+==============================+\n"
        "| 0xFFFFFFE0  | Load integrity error         |\n"
        "+-------------+------------------------------+\n")
    rows, disc = _drive(doc, "d.rst")
    assert rows == [], f"a bare CSR-spelling header resurrected rows; {rows}"
    assert [d["reason"] for d in disc] == [R.NOT_REGISTERS_NO_NAME_COLUMN]


def test_a_table_with_no_address_column_at_all_discloses_nothing():
    """An absent address column is not a dropped address — there is nothing to
    report, and reporting it would drown the real records."""
    doc = (
        "+-----------+----------------------------------+\n"
        "| Field     | Description                      |\n"
        "+===========+==================================+\n"
        "| ``state`` | The current FSM state            |\n"
        "+-----------+----------------------------------+\n")
    rows, disc = _drive(doc, "d.rst")
    assert rows == [] and disc == []


# --- driven end-to-end over the real documents the defect was measured on -----
#
# Everything above is a fixture. These re-derive L4 from a real design's staged
# `input/docs/` through the same two functions the runner calls, because the
# load-bearing numbers (5 gone, 42 kept) are pipeline numbers: `gen_l4_regmap`
# owns the specialised CSR reader and `_post_emit_pdf_regmap_table_rows` owns
# the extractor + the address dedup between them.

def _rederive_l4(tmp_path, docs_dir):
    """Re-derive L4 in a scratch project from a corpus design's input/docs/.
    The corpus itself is read-only — nothing is written back into it."""
    sys.path.insert(0, str(PROGRAMS))
    import phase1_doc_one_shot_runner as PH
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    shutil.copytree(docs_dir, proj / "input" / "docs")
    extracted = PH._cap_extracted_for_scan(
        PH.extract_text_pipeline(proj, force=True))
    PH.gen_l1_datasheet(proj, extracted)
    PH.gen_l4_regmap(proj, extracted)
    PH._post_emit_pdf_regmap_table_rows(proj)
    l4 = json.loads(
        (proj / "phase1/generated_docs/L4_REGMAP.json").read_text())
    return proj, [r for r in (l4.get("registers") or []) if isinstance(r, dict)]


def _by_strategy(registers):
    c = collections.Counter()
    for r in registers:
        ev = r.get("evidence")
        st = (ev.get("extraction_strategy") if isinstance(ev, dict) else None)
        c[st or r.get("extraction_strategy") or "(none)"] += 1
    return c


def test_real_design_keeps_its_csr_rows_and_drops_the_five(tmp_path):
    """BOTH directions on one re-derivation of the real documents.

    Before: 150 registers — 102 HDL-enum, 42 CSR-table, 5 grid-table (2 of them
    nameless), 1 rowspan. After: the same 102 / 42 / 1, and the 5 are gone.
    The 42 is the constraint that makes this falsifiable in the other
    direction — a rule broad enough to also take the real CSR table would be
    caught here, and the two tables sit in the same document set.
    """
    docs = require_repo("benchmark-data", "ic", "ibex", "input", "docs")
    _proj, regs = _rederive_l4(tmp_path, docs)
    census = _by_strategy(regs)
    assert census["rst_grid_csr_v1_6_566"] == 42, (
        f"the real CSR table changed; census={dict(census)}")
    assert census["rst_grid_table_match"] == 0, (
        "grid-table non-registers survived; "
        f"{[(r.get('addr_hex'), r.get('name')) for r in regs if (r.get('evidence') or {}).get('extraction_strategy') == 'rst_grid_table_match']}")
    assert census["hdl_typedef_enum_address_v1_7_74"] == 102, dict(census)
    assert len(regs) == 145, f"expected 145 registers, got {len(regs)}"


def test_real_design_emits_no_nameless_register(tmp_path):
    """The gate's own complaint, re-derived: two registers named "" collided on
    one Verilog identifier. Zero nameless records is the invariant."""
    docs = require_repo("benchmark-data", "ic", "ibex", "input", "docs")
    _proj, regs = _rederive_l4(tmp_path, docs)
    nameless = [r for r in regs if not (r.get("name") or "").strip()]
    assert nameless == [], f"{len(nameless)} nameless register(s): {nameless[:3]}"


def test_real_design_writes_the_disclosure_sidecar(tmp_path):
    """R3 end-to-end: the dropped tables reach disk with their reason, so a
    reader of L4 can tell an absent register from a discarded one."""
    import _path_layout as _pl
    docs = require_repo("benchmark-data", "ic", "ibex", "input", "docs")
    proj, _regs = _rederive_l4(tmp_path, docs)
    import phase1_doc_one_shot_runner as PH
    for out_dir in (_pl.phase1_dir(proj), _pl.reports_phase1_dir(proj)):
        f = out_dir / PH.REGMAP_NOT_REGISTERS_FILENAME
        assert f.is_file(), f"disclosure not written to {f}"
        payload = json.loads(f.read_text())
        reasons = {t["reason"] for t in payload["tables"]}
        assert reasons == {R.NOT_REGISTERS_NO_NAME_COLUMN,
                           R.NOT_REGISTERS_VALUE_COLUMN_ONLY}, payload
        dropped = {a for t in payload["tables"]
                   for a in t["addresses_read_and_dropped"]}
        # every address the five non-registers carried is named in the record.
        assert {"0xffffffe0", "0x8000001f", "0x1a110000",
                "0x1a110800", "0x1a110808"} <= dropped, sorted(dropped)


def test_disclosure_file_is_written_even_when_nothing_was_dropped(tmp_path):
    """A file that says `[]` is the statement that nothing was dropped; an
    absent file is not that statement."""
    import _path_layout as _pl
    import phase1_doc_one_shot_runner as PH
    docs = require_repo("benchmark-data", "ic", "opentitan_aes", "input", "docs")
    proj, _regs = _rederive_l4(tmp_path, docs)
    f = _pl.phase1_dir(proj) / PH.REGMAP_NOT_REGISTERS_FILENAME
    payload = json.loads(f.read_text())
    assert payload["count"] == len(payload["tables"])
    assert "meaning" in payload and payload["produced_by"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
