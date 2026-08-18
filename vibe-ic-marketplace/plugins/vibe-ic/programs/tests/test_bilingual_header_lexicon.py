"""Issue #500 (MEDIUM) — ONE shared bilingual (CJK + English) header
lexicon for ALL pipe-table families in ``phase1_doc_one_shot_runner.py``.

Background: the pin family received CJK + multi-word group header
vocabulary in #491 round-3 (``_V0_3_2_HEADER_*_TOKENS``), but the SIBLING
families (register map, parameter table, field / doc table) shared the
same English-only assumption and silently dropped CJK-headed tables the
same way the pin family did BEFORE #491.

This file pins:
  (1) per-family TWIN fixtures — SAME rows, English header vs CJK header
      → IDENTICAL extraction results, for the four families that have a
      header-token classifier in the runner:
        * pin          (`_v0_3_2_iter_gfm_pin_tables` / classifier)
        * register-map (`_v1_6_566_extract_csr_rst_grid_rows` / classifier
                        + the RST-grid header PRE-FILTER regex)
        * parameter    (`_v1_6_400_is_parameter_table_header`)
        * field/doc    (`_is_real_submodule_name` deny-list classifier)
  (2) a STRUCTURAL test that EVERY per-family classifier token set in the
      runner derives from the shared lexicon source pin
      (``_header_lexicon.ROLE_TOKENS``) — no English-only island remains.

The discriminating real-doc header line quoted VERBATIM (per the #501
fixture doctrine) is the #491 round-3 CJK port-table header
``| Port group | 寬度 | 方向 | 描述 |`` and the bilingual CSR grid header
``| 位址 | 名稱 | 權限 | 描述 |``.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import _header_lexicon as LEX  # noqa: E402
import phase1_doc_one_shot_runner as P1  # noqa: E402


# ---------------------------------------------------------------------------
# Lexicon sanity — every role carries BOTH English and CJK tokens.
# ---------------------------------------------------------------------------
_MULTILINGUAL_ROLES = (
    "name", "direction", "width", "description", "address", "access",
    "default", "opcode", "value", "register", "parameter", "field",
)


def _has_cjk(tok: str) -> bool:
    return any(ord(ch) > 0x2E7F for ch in tok)


def test_every_multilingual_role_has_english_and_cjk():
    for role in _MULTILINGUAL_ROLES:
        toks = LEX.ROLE_TOKENS[role]
        assert any(not _has_cjk(t) for t in toks), f"{role} missing EN"
        assert any(_has_cjk(t) for t in toks), f"{role} missing CJK"


def test_tokens_for_unions_roles():
    a = LEX.tokens_for("name")
    b = LEX.tokens_for("direction")
    assert LEX.tokens_for("name", "direction") == (a | b)


def test_tokens_for_unknown_role_raises():
    import pytest
    with pytest.raises(KeyError):
        LEX.tokens_for("not_a_role")


# ---------------------------------------------------------------------------
# STRUCTURAL — every per-family classifier token set derives from the
# shared lexicon. If any family re-introduces an English-only island, its
# token set will contain a token absent from `LEX.all_tokens()` and this
# test fails.
# ---------------------------------------------------------------------------
def test_pin_family_tokens_derive_from_lexicon():
    assert P1._V0_3_2_HEADER_NAME_TOKENS == LEX.tokens_for("name")
    assert P1._V0_3_2_HEADER_DIR_TOKENS == LEX.tokens_for("direction")
    assert P1._V0_3_2_HEADER_WIDTH_TOKENS == LEX.tokens_for("width")
    assert P1._V0_3_2_HEADER_DESC_TOKENS == LEX.tokens_for("description")


def test_register_map_tokens_derive_from_lexicon():
    assert P1._V1_6_566_HEADER_ADDR_TOKENS == LEX.tokens_for("address")
    assert P1._V1_6_566_HEADER_NAME_TOKENS == LEX.tokens_for(
        "name", "register")
    assert P1._V1_6_566_HEADER_ACCESS_TOKENS == LEX.tokens_for("access")
    assert P1._V1_6_566_HEADER_DESC_TOKENS == LEX.tokens_for("description")


def test_parameter_tokens_derive_from_lexicon():
    assert P1._V1_6_400_PARAMETER_HEADER_TOKENS == LEX.tokens_for(
        "parameter")


def test_doc_table_tokens_derive_from_lexicon_plus_structure():
    role_part = LEX.tokens_for(
        "name", "direction", "width", "description", "address",
        "access", "default", "value", "parameter", "field", "range",
        "units", "register")
    # every doc-table token is EITHER a lexicon role token OR a declared
    # doc-structure token (submodule / module / section / …) — no
    # English-only island.
    leftover = set(P1._DOC_TABLE_HEADER_TOKENS) - set(role_part) \
        - set(P1._DOC_TABLE_STRUCTURE_TOKENS)
    assert leftover == set(), f"doc-table island: {leftover}"
    # and it does carry the lexicon CJK coverage.
    assert "描述" in P1._DOC_TABLE_HEADER_TOKENS


def test_bullet_port_tokens_derive_from_lexicon_plus_structure():
    role_part = (
        LEX.tokens_for(
            "name", "direction", "width", "description", "access",
            "default", "value", "parameter", "field", "range", "units")
        | LEX.tokens_for("address")
    )
    leftover = set(P1._BULLET_PORT_COMMON_HEADER_TOKENS) - set(role_part) \
        - set(P1._BULLET_PORT_STRUCTURE_TOKENS)
    assert leftover == set(), f"bullet-port island: {leftover}"
    # legitimate port-name stems are STILL not denied.
    for stem in ("data", "addr", "io"):
        assert stem not in P1._BULLET_PORT_COMMON_HEADER_TOKENS


# ---------------------------------------------------------------------------
# TWIN FIXTURE 1 — pin family. Same rows, EN vs CJK header.
# ---------------------------------------------------------------------------
_PIN_EN = """| Signal | Direction | Width | Description |
|---|---|---|---|
| i_clk | input | 1 | system clock |
| i_rst | input | 1 | reset |
| o_dat | output | 8 | data out |
"""
_PIN_CJK = """| 訊號 | 方向 | 寬度 | 描述 |
|---|---|---|---|
| i_clk | input | 1 | system clock |
| i_rst | input | 1 | reset |
| o_dat | output | 8 | data out |
"""
# the #491 round-3 discriminating header, quoted VERBATIM.
_PIN_CJK_GROUP = """| Port group | 寬度 | 方向 | 描述 |
|---|---|---|---|
| i_clk | 1-bit | input | system clock |
| i_rst | 1-bit | input | reset |
| o_dat | 8-bit | output | data out |
"""


def _pin_rows(doc):
    out = []
    for roles, rows, _hdr in P1._v0_3_2_iter_gfm_pin_tables(doc):
        for cells in rows:
            out.append((
                cells[roles["name"]].strip("` "),
                cells[roles["direction"]].strip("` "),
            ))
    return sorted(out)


def test_pin_twin_en_eq_cjk():
    en = _pin_rows(_PIN_EN)
    cjk = _pin_rows(_PIN_CJK)
    assert en == cjk and len(en) == 3, (en, cjk)


def test_pin_twin_en_eq_cjk_group_header_491():
    en = _pin_rows(_PIN_EN)
    grp = _pin_rows(_PIN_CJK_GROUP)
    assert en == grp and len(grp) == 3, (en, grp)


# ---------------------------------------------------------------------------
# TWIN FIXTURE 2 — register-map (CSR RST grid). Same rows, EN vs CJK
# header. Exercises BOTH the header-token classifier AND the RST-grid
# header PRE-FILTER regex (the pre-filter was English-only too).
# ---------------------------------------------------------------------------
_CSR_EN = """
+----------------+---------+-------------+----------------------+
| CSR Address    | Name    | Privilege   | Description          |
+================+=========+=============+======================+
| 0x300          | mstatus | MRW         | Machine status reg   |
+----------------+---------+-------------+----------------------+
| 0x305          | mtvec   | MRW         | Trap vector base     |
+----------------+---------+-------------+----------------------+
"""
# discriminating bilingual CSR header, quoted VERBATIM.
_CSR_CJK = """
+----------------+---------+-------------+----------------------+
| 位址           | 名稱    | 權限        | 描述                 |
+================+=========+=============+======================+
| 0x300          | mstatus | MRW         | Machine status reg   |
+----------------+---------+-------------+----------------------+
| 0x305          | mtvec   | MRW         | Trap vector base     |
+----------------+---------+-------------+----------------------+
"""


def _csr_norm(rows):
    return sorted(
        (r["address"], r["name"], r.get("access"), r.get("description"))
        for r in rows)


def test_register_map_twin_en_eq_cjk():
    en = P1._v1_6_566_extract_csr_rst_grid_rows(_CSR_EN, "csr_en.rst")
    cjk = P1._v1_6_566_extract_csr_rst_grid_rows(_CSR_CJK, "csr_cjk.rst")
    assert len(en) == 2, en
    assert _csr_norm(en) == _csr_norm(cjk), (en, cjk)


def test_register_map_classifier_twin():
    en = P1._v1_6_566_classify_header_cells(
        "| CSR Address | Name | Privilege | Description |")
    cjk = P1._v1_6_566_classify_header_cells(
        "| 位址 | 名稱 | 權限 | 描述 |")
    assert en == cjk
    assert set(en.values()) == {"addr", "name", "access", "desc"}


# ---------------------------------------------------------------------------
# TWIN FIXTURE 3 — parameter table header classifier. EN vs CJK.
# ---------------------------------------------------------------------------
def test_parameter_twin_en_eq_cjk():
    en = P1._v1_6_400_is_parameter_table_header(
        ["Parameter", "Type", "Default", "Description"])
    cjk = P1._v1_6_400_is_parameter_table_header(
        ["參數", "型別", "預設值", "描述"])
    assert en is True and cjk is True
    # bare-word variants too.
    assert P1._v1_6_400_is_parameter_table_header(["Generics"]) is True
    assert P1._v1_6_400_is_parameter_table_header(["配置"]) is True


# ---------------------------------------------------------------------------
# TWIN FIXTURE 4 — field / doc table header deny-list classifier. A header
# token (English OR CJK) must be rejected as an L9 submodule name; a real
# RTL-shaped name must pass either way.
# ---------------------------------------------------------------------------
def test_doc_table_twin_en_eq_cjk():
    # header words rejected, both languages.
    for tok in ("description", "default", "parameter", "register"):
        assert P1._is_real_submodule_name(tok) is False, tok
    for tok in ("描述", "預設值", "參數", "暫存器"):
        assert P1._is_real_submodule_name(tok) is False, tok
    # real RTL-shaped submodule names still accepted (control), same in
    # both fixtures since the row payload is identical.
    for nm in ("uart_rx", "aes_core", "byte_assembler"):
        assert P1._is_real_submodule_name(nm) is True, nm
