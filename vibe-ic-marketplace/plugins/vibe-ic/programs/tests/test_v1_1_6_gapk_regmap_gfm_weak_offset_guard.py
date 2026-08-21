"""ORGANIC gapK (REGRESSION of #800, P0) — the regmap_table_extractor GFM
PRIMARY path (`_extract_gfm_pipe_table`) fabricated phantom registers from a
plain `| Field | Value |` datasheet SPEC table.

`'Field' ∈ _GFM_NAME_HDR` and `'Value' ∈ _GFM_OFFSET_HDR`, so a 2-column
`| Field | Value |` table was treated as a register map; the decimal-tolerant
`_GFM_OFFSET_RE` then promoted a BARE DECIMAL buried in the VALUE prose to an
address:

    | Fabricated | 2024       |  ->  0x7e8   (2024 == 0x7e8)
    | Channels   | 6 channels |  ->  0x6
    | Supply     | 1.8 V      |  ->  0x1

The rst-grid path ALREADY guards this case (a WEAK offset header — Value /
Default / Reset Value — requires a real `0x...` token before becoming an
address; see `_rst_header_roles` `offset_weak` + `_flush_rst_grid_table`'s
`_GFM_OFFSET_HEX_RE` gate). The GFM PRIMARY path did NOT have that guard.

#800 (content-based regmap trigger) removed the runner class allow-list gate
(`_REGMAP_TABLE_CLASSES`), so this latent pre-existing #747-r2 GFM-primary-path
weak-offset gap is now reached for a `mixed_signal_adc` (u_hawaii_adc) whose L1
datasheet is full of `| Field | Value |` SPEC tables → 3 phantom registers land
in L4 → `l_doc_structured_field_count_check` FAILs an ADC that legitimately has
ZERO software-visible registers.

FIX (port the existing rst-grid §4.05 weak-offset HEX guard onto the GFM primary
path): tag `cols['offset_weak']` when the matched offset header is a weak role,
then gate the offset-cell match exactly like the rst-grid path —
`_GFM_OFFSET_HEX_RE` for a weak column (a real 0x token required), the
decimal-tolerant `_GFM_OFFSET_RE` for a strong Offset/Address column.

§4.05 MATRIX:
  * (POS)   the u_hawaii_adc `| Field | Value |` doc -> 0 rows (3 phantoms gone);
  * (NEG-1) a genuine register table with a STRONG `Offset` header and a
            bare-decimal offset `4` (non-weak) -> still extracted (decimal
            tolerance preserved for real offset columns — no over-correction);
  * (NEG-2) a genuine 0x-address regmap (#616 GFM shape) -> still fully captured
            (no regression of the legit path);
  * (NEG-3) a WEAK `Value` header that DOES carry a real `0x` token -> still
            extracted (only the bare-decimal promotion is suppressed).

chip-AGNOSTIC: the guard keys off the generic doc-vocabulary WEAK offset headers
(value / default / reset value) already defined in `_GFM_OFFSET_WEAK_HDR`; no
chip / SKU / register-name literal is involved.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import regmap_table_extractor as R  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


def _addrs(text, path="x.md"):
    return {r.get("addr_hex") for r in R.extract_regmap_table(text, path)}


# Genericized from the OBSERVED u_hawaii_adc L1_DATASHEET.md `| Field | Value |`
# SPEC tables: a 2-col Field/Value table whose VALUE cells embed bare decimals
# (a fabrication year, a channel count, a supply voltage).
_FIELD_VALUE_SPEC = (
    "# Block Datasheet\n\n"
    "## Key Facts\n\n"
    "| Field        | Value                          |\n"
    "|--------------|--------------------------------|\n"
    "| Fabricated   | 2024                           |\n"
    "| Channels     | 6 channels                     |\n"
    "| Supply       | 1.8 V                          |\n"
)


def test_gapk_field_value_spec_table_no_phantom_registers():
    """The GFM primary path must NOT fabricate registers from a `| Field | Value |`
    SPEC table — the Value column is a WEAK offset role, so a bare decimal in the
    value prose may never become an address (pre-fix produced 0x7e8 / 0x6 / 0x1)."""
    rows = R.extract_regmap_table(_FIELD_VALUE_SPEC, "L1_DATASHEET.md")
    assert rows == [], (
        "§4.05 LEAK: `| Field | Value |` SPEC table fabricated phantom registers: "
        f"{[(r.get('addr_hex'), r.get('name')) for r in rows]}")


def test_gapk_real_u_hawaii_adc_l1_datasheet_zero_rows():
    """Bind the regression to the ACTUAL benchmark fixture if present: the real
    u_hawaii_adc L1 datasheet (a mixed_signal_adc with ZERO sw-visible registers)
    must extract 0 register rows. Skips gracefully when the bench tree is absent
    so the test is portable (the synthetic case above is the binding floor)."""
    doc = require_corpus("_bench6_v100_r18/u_hawaii_adc/input/docs/L1_DATASHEET.md")
    if not doc.exists():
        import pytest
        pytest.skip("u_hawaii_adc bench fixture not present in this checkout")
    rows = R.extract_regmap_table(doc.read_text(), str(doc))
    assert rows == [], (
        "§4.05 LEAK on the real u_hawaii_adc datasheet: "
        f"{[(r.get('addr_hex'), r.get('name')) for r in rows]}")


def test_gapk_neg1_strong_offset_header_bare_decimal_still_extracted():
    """NEG-no-leak: a GENUINE register table with a STRONG `Offset` header keeps
    the decimal-tolerant match — a bare-decimal offset `0` / `4` is a real byte
    offset and must still be extracted (the fix must not over-correct)."""
    doc = (
        "| Name      | Offset | Description       |\n"
        "|-----------|--------|-------------------|\n"
        "| CTRL      | 0      | control register  |\n"
        "| STATUS    | 4      | status register   |\n"
    )
    by = {r["addr_hex"]: r["name"]
          for r in R.extract_regmap_table(doc, "regs.md")}
    assert by == {"0x0": "CTRL", "0x4": "STATUS"}, (
        f"strong-Offset decimal tolerance regressed; got {by}")


def test_gapk_neg2_genuine_0x_regmap_fully_captured():
    """NEG-no-leak: a genuine 0x-address GFM regmap (#616 shape) must stay fully
    captured — no regression of the legit register path."""
    doc = (
        "| Name                          | Offset | Length | Description         |\n"
        "|-------------------------------|--------|--------|---------------------|\n"
        "| [`ALERT_TEST`](#alert_test)   | 0x0    | 4      | Alert Test Register |\n"
        "| [`KEY_SHARE0_0`](#k)          | 0x14   | 4      | Initial Key Share 0 |\n"
    )
    by = {r["addr_hex"]: r["name"]
          for r in R.extract_regmap_table(doc, "aes_registers.md")}
    assert by == {"0x0": "ALERT_TEST", "0x14": "KEY_SHARE0_0"}, (
        f"genuine 0x regmap regressed; got {by}")


def test_gapk_neg3_weak_value_header_yields_nothing_even_with_a_real_0x_token():
    """REVERSED by #512 (was
    `test_gapk_neg3_weak_value_header_with_real_0x_token_still_extracted`,
    which asserted `{"0x40": "BASE"}`).

    gapK suppressed only the BARE-DECIMAL promotion out of a weak `Value`
    column, and this NEG case pinned that a hex one still became a register.
    #512 measured that residue on a real corpus doc: a `| Value | Name |
    Description |` enumerated-field table produced seven registers that are
    one-hot FIELD ENCODINGS (`AES_ECB @ 0x01` … `AES_NONE @ 0x3f`), and three
    more were welded onto real registers as `also_named`. The base a constant is
    written in does not make it an address. So the rule is now structural and
    base-independent: when a table's ONLY address-role column is headed by a
    VALUE keyword, the table yields no registers — disclosed, not silent.

    gapK's POSITIVE case (the observed `| Field | Value |` datasheet SPEC table
    fabricating three phantoms) and NEG-1 / NEG-2 are unchanged above.
    """
    doc = (
        "| Register | Value  | Description       |\n"
        "|----------|--------|-------------------|\n"
        "| BASE     | 0x40   | base address      |\n"
        "| LIMIT    | 6 ch   | not an address    |\n"
    )
    disc = []
    rows = R.extract_regmap_table(doc, "weak.md", disclosures=disc)
    assert rows == [], f"value-only table still fabricated registers; {rows}"
    assert [d["reason"] for d in disc] == [
        R.NOT_REGISTERS_VALUE_COLUMN_ONLY], disc
    # the dropped hex is NAMED in the disclosure — read, not silently discarded.
    assert disc[0]["addresses_read_and_dropped"] == ["0x40"], disc


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
