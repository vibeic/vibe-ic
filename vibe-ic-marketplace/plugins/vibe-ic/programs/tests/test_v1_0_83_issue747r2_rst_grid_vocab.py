"""ORGANIC #747 ROUND-2 (REOPEN, P2) — the v1.0.82 rst GRID-table parser branch
was a PARTIAL fix. The border detection + GFM-no-double-count were correct and it
fired on `ibex_cs_registers.rst` (header `| Address | Name | Access | ... |`), but
the NAME/OFFSET header-keyword GATE was too NARROW, so the issue's 33 target hex
tokens were STILL dropped:

  * `ibex_performance_counters.rst` uses `Event Counter` / `Event Selector` as the
    NAME column header (not in the v1.0.82 keyword set) → 0xB04 / 0x324 dropped.
  * the debug-module base address sits in a `Default` column of a *parameters*
    table (no offset keyword) → 0x1A110000 dropped.
  * the interrupt-cause masks sit in a 2-column `| mcause | Description |` table
    with no offset column at all → 0x8000001F / 0xFFFFFFE0 dropped.

`extract_regmap_table()` on `ibex_performance_counters.rst` returned 0 rows pre-fix.

FIX (broaden column-role detection): (1) extend the NAME header keywords
(event counter / event selector / mcause / parameter / …); (2) extend the
OFFSET header keywords (default / reset value / value) as WEAK roles; (3) a
vocabulary-free STRUCTURAL fallback — when the header does not name BOTH a name
and an offset column, the column whose cells consistently hold a real `0x...`
token IS the address and an adjacent identifier column the name (captures the
2-column + Default-column shapes); (4) handle 2-column tables.

§4.05 NO-LEAK (load-bearing):
  * a Description-ONLY column (no 0x, no name keyword) must NOT yield a phantom
    address;
  * a parameter `Default` column of bare decimals (0 / 4 / 40) must NOT fabricate
    `0x0` / `0x4` addresses — only a real `0x...` token may become an address;
  * a no-grid doc stays unchanged;
  * the GFM pipe path still parses with no #616 regression;
  * the v1.0.82 "stray border abutting a GFM table" no-double-count guard holds.

chip-AGNOSTIC: the broadened keywords are generic documentation vocabulary
(event/counter/selector/mcause/parameter/default/value), never a design SKU; the
structural fallback uses no vocabulary at all.

Step-2.6 — the discriminating header lines below are quoted VERBATIM from the real
ibex `.rst` docs under benchmark_run_v0352_0613/ibex/input/docs/.

#512 PARTIALLY REVERSES this fix — read before restoring anything here.
=======================================================================
Items (1) and (3) above stand: the broadened NAME keywords and the structural
fallback both survive, and the Event-Counter / Event-Selector tables still yield
every address they did. Two of #747-r2's conclusions were wrong and are now
inverted in place, each with its reason on the test:

  * a hex cell in a *parameters* table's `Default` column was taken as a
    register address — it is a configuration constant
    (`test_param_default_column_is_not_an_address_space`);
  * the 2-column `| mcause | Description |` table was allowed to emit rows with
    no name at all — a table with no name-bearing column is not a register table
    (`test_mcause_2col_has_no_name_column_so_yields_no_registers`).

Both were measured on the real ibex documents, where they had put five
non-registers into L4. They are DISCLOSED now rather than emitted; the addresses
#747-r2 was chasing are still READ, and named in the disclosure record.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import regmap_table_extractor as R  # noqa: E402


# --- real-shaped fixtures (header rows quoted VERBATIM from the ibex docs) -----

# ibex_performance_counters.rst, Event Counter table. NAME header is
# `Event Counter`; offset header `CSR Address`; the address cell carries a
# parenthetical high-word alias `0xB04 (0xB84)` (primary 0xB04 is the addr); the
# names are rst double-backtick inline literals with a `(h)` suffix.
_EVENT_COUNTER = (
    "+----------------------+----------------+--------------+------------------+\n"
    "| Event Counter        | CSR Address    | Event ID/Bit | Event Name       |\n"
    "+======================+================+==============+==================+\n"
    "| ``mcycle(h)``        | 0xB00 (0xB80)  |            0 | NumCycles        |\n"
    "+----------------------+----------------+--------------+------------------+\n"
    "| ``mhpmcounter4(h)``  | 0xB04 (0xB84)  |            4 | NumCyclesIF      |\n"
    "+----------------------+----------------+--------------+------------------+\n"
)

# ibex_performance_counters.rst, Event Selector table. NAME header
# `Event Selector`; the wanted address is `CSR Address` (0x324), NOT the
# `Reset Value` column (0x0000_0010) — first-offset-wins keeps CSR Address.
_EVENT_SELECTOR = (
    "+----------------------+-------------+-------------+--------------+\n"
    "| Event Selector       | CSR Address | Reset Value | Event ID/Bit |\n"
    "+======================+=============+=============+==============+\n"
    "| ``mhpmevent4(h)``    | 0x324       | 0x0000_0010 |            4 |\n"
    "+----------------------+-------------+-------------+--------------+\n"
)

# ibex_integration.rst Parameters table. NAME header `Name`; the hex base
# address sits in the `Default` column (a WEAK offset header) amid bare-decimal
# defaults (0). Only the genuine 0x... cell may become an address.
_PARAM_DEFAULT = (
    "+------------------------------+---------------------+----------------+----------------------------------+\n"
    "| Name                         | Type/Range          | Default        | Description                      |\n"
    "+==============================+=====================+================+==================================+\n"
    "| ``PMPEnable``                | bit                 | 0              | Enable PMP support               |\n"
    "+------------------------------+---------------------+----------------+----------------------------------+\n"
    "| ``DmBaseAddr``               | int                 | 0x1A110000     | Base address of the Debug Module |\n"
    "+------------------------------+---------------------+----------------+----------------------------------+\n"
)

# ibex_exception_interrupts.rst, 2-column interrupt-cause table. The address is in
# the `mcause` column, the only other column is a prose Description; there is NO
# offset header — the structural fallback must recover the address.
_MCAUSE_2COL = (
    "+-------------+----------------------------------------+\n"
    "| ``mcause``  | Description                            |\n"
    "+=============+========================================+\n"
    "| 0xFFFFFFE0  | Load integrity error internal interrupt|\n"
    "+-------------+----------------------------------------+\n"
    "| 0x8000001F  | External NMI                           |\n"
    "+-------------+----------------------------------------+\n"
)


def _addrs(text, path="x.rst"):
    return {r["addr_hex"] for r in R.extract_regmap_table(text, path)}


# --- BINDING ACCEPTANCE: reproduce 現象 (pre-fix 0 rows → recovered hex) --------

def test_event_counter_name_header(tmp_path):
    p = tmp_path / "ibex_performance_counters.rst"
    p.write_text(_EVENT_COUNTER)
    rows = R.extract_regmap_table(p.read_text(), str(p))
    by = {r["addr_hex"]: r["name"] for r in rows}
    # pre-fix: 0 rows (Event Counter not a NAME keyword + ``name(h)`` unparsed).
    assert "0xb04" in by, f"Event Counter table dropped 0xB04; got {sorted(by)}"
    assert by["0xb04"] == "mhpmcounter4"
    assert by["0xb00"] == "mcycle"
    assert all(r["evidence"]["extraction_strategy"] == "rst_grid_table_match"
               for r in rows)


def test_event_selector_name_header_csr_address_wins(tmp_path):
    p = tmp_path / "perf_sel.rst"
    p.write_text(_EVENT_SELECTOR)
    by = {r["addr_hex"]: r["name"]
          for r in R.extract_regmap_table(p.read_text(), str(p))}
    # CSR Address (0x324) is the wanted addr, NOT Reset Value (0x0000_0010).
    assert "0x324" in by, f"Event Selector dropped 0x324; got {sorted(by)}"
    assert by["0x324"] == "mhpmevent4"
    assert "0x10" not in by and "0x0000_0010" not in by


def test_param_default_column_is_not_an_address_space(tmp_path):
    """REVERSED by #512 (was `test_param_default_column_hex_only`, which
    asserted `"0x1a110000" in addrs`).

    This assertion was the #747-r2 decision that a hex cell in a *parameters*
    table's `Default` column is a register address. It is not: it is the value
    the design is configured with. Left standing it put three Debug-Module
    parameter addresses into a real design's L4 as registers — and they survived
    every gate purely because this table happens to have a name column, which is
    not evidence of being a register. What the parser must decide is whether the
    TABLE describes an address space, and a column headed `Default` says it does
    not. The half of #747-r2 that is still right — a bare-decimal default never
    fabricating `0x0` — is asserted below, now by the stronger rule.
    """
    p = tmp_path / "ibex_integration.rst"
    p.write_text(_PARAM_DEFAULT)
    disc = []
    rows = R.extract_regmap_table(p.read_text(), str(p), disclosures=disc)
    assert rows == [], f"parameter defaults still became registers; {rows}"
    # ... and the bare-decimal `0` default still fabricates nothing.
    assert "0x0" not in {r.get("addr_hex") for r in rows}
    assert [d["reason"] for d in disc] == [
        R.NOT_REGISTERS_VALUE_COLUMN_ONLY], disc
    # DISCLOSED: the hex that was read and dropped is named in the record.
    assert disc[0]["addresses_read_and_dropped"] == ["0x1a110000"], disc
    assert disc[0]["rows_read"] == 2 and disc[0]["registers_emitted"] == 0


def test_mcause_2col_has_no_name_column_so_yields_no_registers(tmp_path):
    """REVERSED by #512 (was `test_mcause_2col_structural_fallback`, which
    asserted both cause codes landed as addresses).

    The structural fallback was allowed to emit address-only rows for this
    2-column shape, so the table produced two registers with `name: ""`. Two
    nameless registers collide on the register-block emitter's single unnamed
    identifier, which is how the defect surfaced; but the collision is the
    symptom. `0x8000001F` is a cause code with the interrupt bit set, not an
    address, and the table says so structurally: it has no name-bearing column,
    so there is no register for a consumer to name, emit or decode.
    """
    p = tmp_path / "ibex_exception_interrupts.rst"
    p.write_text(_MCAUSE_2COL)
    disc = []
    rows = R.extract_regmap_table(p.read_text(), str(p), disclosures=disc)
    assert rows == [], f"nameless cause codes still became registers; {rows}"
    assert [d["reason"] for d in disc] == [
        R.NOT_REGISTERS_NO_NAME_COLUMN], disc
    assert sorted(disc[0]["addresses_read_and_dropped"]) == [
        "0x8000001f", "0xffffffe0"], disc


# --- §4.05 NO-LEAK guards ------------------------------------------------------

def test_description_only_column_no_phantom_address():
    """A grid whose non-name columns are pure prose (no 0x anywhere) must yield
    NO address — the structural fallback must not invent one."""
    doc = (
        "+-------------+----------------------------------+\n"
        "| Field       | Description                      |\n"
        "+=============+==================================+\n"
        "| ``state``   | The current FSM state            |\n"
        "+-------------+----------------------------------+\n"
        "| ``count``   | Number of retries seen so far    |\n"
        "+-------------+----------------------------------+\n"
    )
    assert R.extract_regmap_table(doc, "desc.rst") == [], (
        "§4.05 LEAK: description-only grid produced phantom rows")


def test_all_decimal_default_column_no_phantom():
    """A parameters table whose `Default` column is ALL bare decimals (no 0x)
    must produce NO addresses (every decimal would otherwise become 0x...)."""
    doc = (
        "+----------------+----------------+--------------------------+\n"
        "| Name           | Default        | Description              |\n"
        "+================+================+==========================+\n"
        "| ``WIDTH``      | 8              | data width               |\n"
        "+----------------+----------------+--------------------------+\n"
        "| ``DEPTH``      | 16             | fifo depth               |\n"
        "+----------------+----------------+--------------------------+\n"
    )
    assert _addrs(doc, "params.rst") == set(), (
        "§4.05 LEAK: all-decimal Default column fabricated addresses")


def test_no_grid_doc_unchanged():
    plain = "Just prose about a chip.\nNo tables.\n"
    assert R.extract_regmap_table(plain, "p.txt") == []


def test_gfm_pipe_path_still_parses_no_616_regression():
    gfm = (
        "# AES registers\n\n"
        "| Name                          | Offset | Length | Description         |\n"
        "|-------------------------------|--------|--------|---------------------|\n"
        "| [`ALERT_TEST`](#alert_test)   | 0x0    | 4      | Alert Test Register |\n"
        "| [`KEY_SHARE0_0`](#k)          | 0x14   | 4      | Initial Key Share 0 |\n"
    )
    rows = R.extract_regmap_table(gfm, "aes_registers.md")
    assert {r["name"] for r in rows} == {"ALERT_TEST", "KEY_SHARE0_0"}
    assert {r["evidence"]["extraction_strategy"] for r in rows} == {
        "gfm_pipe_table_match"}, "GFM path regressed / double-counted"
    # the rst branch alone emits nothing on a pure GFM doc.
    assert R._extract_rst_grid_table(gfm, "aes_registers.md") == []


def test_stray_border_abutting_gfm_table_no_double_count():
    """v1.0.82 adversarial-review MEDIUM, preserved: a stray `+---+` border
    directly above a GFM pipe table must NOT make the rst branch re-emit it."""
    doc = ("+-----+\n"
           "| Name   | Offset |\n"
           "|--------|--------|\n"
           "| reg_y  | 0x44   |\n")
    rows = R.extract_regmap_table(doc, "p.md")
    assert len(rows) == 1, [
        (r["name"], r["evidence"]["extraction_strategy"]) for r in rows]
    assert rows[0]["name"] == "reg_y"
    assert rows[0]["evidence"]["extraction_strategy"] == "gfm_pipe_table_match"
