#!/usr/bin/env python3
"""Regression for ORGANIC #746 P2 — the P0 doc-completeness gate must CREDIT a
C-macro register-field alias whose register AND field are both captured
structurally in L4_REGMAP (landed by #736).

現象: a programmer's-guide / SDK-header doc quotes autogen register-access
C-macros of the canonical shape

        <PREFIX>_<REGISTER>_<FIELD>[_<SUFFIX>]

e.g. `PREFIX_CTRL_SHADOWED_OPERATION_OFFSET`, `..._MASK`. Phase 1 captures the
REGISTER name AND the FIELD name structurally in L4_REGMAP (`registers[].name`
+ `registers[].fields[].field_name`), but NEVER the concatenated macro string.
The completeness gate did a flat substring search with no alias credit, so the
whole macro was reported MISSING and the doc spuriously FAILed the 100% per-doc
floor (evidence run: a programmers-guide doc 66/77=85.7% FAIL, 11 missing
C-macros). This is the GATE's missing alias-credit — NOT the #736 L4 extractor.

FIX (chip-AGNOSTIC, Bucket B, additive): a deterministic register-macro
alias-credit pass — for each still-MISSING token of the macro shape, CREDIT it
iff it contains `_<register_name>_` for some L4 register AND the tail (after the
register name) equals a `field_name` of THAT register, optionally followed by
exactly one member of the CLOSED suffix set {OFFSET,MASK,SHIFT,WIDTH,LSB,MSB,
FIELD,VALUE,REG,BIT}. Credit source = 'program_alias'.

§4.05 NO-LEAK (load-bearing): a token whose register OR field is ABSENT from L4
stays MISSING — an unrelated CMOS/PRNG/AHB macro is NOT credited; a
`<reg>_<wrongfield>` where wrongfield isn't a field of THAT register is NOT
credited.

chip-AGNOSTIC: keys on the L4 register/field names structurally + a closed
suffix set; NO chip / vendor / SKU literal in detection logic.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "phase1_doc_input_completeness_check.py"

_spec = importlib.util.spec_from_file_location(
    "phase1_doc_input_completeness_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ── fixture builder ──────────────────────────────────────────────────────────
def _make_l4_project(tmp_path: Path, registers) -> Path:
    """Build a project with a tiny L4_REGMAP.json carrying the given
    registers[] (name + fields[].field_name)."""
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L4_REGMAP.json").write_text(
        json.dumps({"registers": registers}))
    return proj


_REGS = [
    {"name": "CTRL_SHADOWED", "fields": [{"field_name": "OPERATION"}]},
]


# ── (1) the issue's two-token assertion: credit the real macro, hold the foreign
def test_cmacro_credited_unrelated_stays_missing(tmp_path):
    """DIRECT end-state: a `<PREFIX>_CTRL_SHADOWED_OPERATION_OFFSET` macro whose
    register+field both land in L4 is CREDITED (program_alias, no longer
    missing); an unrelated `PREFIX_PRNG_SEED_OFFSET` (register PRNG absent from
    L4) stays MISSING."""
    proj = _make_l4_project(tmp_path, _REGS)
    blobs = mod._load_generated_haystacks(proj)
    rfm = mod._load_l4_register_field_map(proj)
    assert "CTRL_SHADOWED" in rfm and "OPERATION" in rfm["CTRL_SHADOWED"]

    # The real macro — pre-fix MISSING (substring search fails), post-fix
    # credited via the structural register+field alias.
    layers, src = mod._attribute_token(
        "PREFIX_CTRL_SHADOWED_OPERATION_OFFSET", blobs, rfm)
    assert src == "program_alias", f"macro not credited: {src}"
    assert layers == ["L4_REGMAP"]

    # The unrelated macro — register PRNG is absent from L4 → stays MISSING.
    layers2, src2 = mod._attribute_token(
        "PREFIX_PRNG_SEED_OFFSET", blobs, rfm)
    assert src2 == "missing", f"unrelated macro wrongly credited: {src2}"
    assert layers2 == []


# ── (2) pre-fix repro: without the alias map the macro is MISSING ────────────
def test_prefix_substring_search_misses_the_macro(tmp_path):
    """The defect 現象: with NO regfield_map (the pre-#746 behaviour) the macro
    is MISSING even though register+field are both in the L4 json text."""
    proj = _make_l4_project(tmp_path, _REGS)
    blobs = mod._load_generated_haystacks(proj)
    # both substrings present...
    assert "CTRL_SHADOWED" in blobs["L4_REGMAP"]["raw"]
    assert "OPERATION" in blobs["L4_REGMAP"]["raw"]
    # ...but the concatenated macro is not, and without alias map → missing.
    layers, src = mod._attribute_token(
        "PREFIX_CTRL_SHADOWED_OPERATION_OFFSET", blobs, None)
    assert src == "missing" and layers == []


# ── (3) the full closed suffix set is credited ───────────────────────────────
@pytest.mark.parametrize(
    "suffix",
    ["OFFSET", "MASK", "SHIFT", "WIDTH", "LSB", "MSB",
     "FIELD", "VALUE", "REG", "BIT"])
def test_all_closed_suffixes_credited(tmp_path, suffix):
    proj = _make_l4_project(tmp_path, _REGS)
    rfm = mod._load_l4_register_field_map(proj)
    tok = f"PREFIX_CTRL_SHADOWED_OPERATION_{suffix}"
    assert mod._regmacro_alias_credit(tok, rfm), tok


def test_bare_macro_no_suffix_credited(tmp_path):
    """`<PREFIX>_<REG>_<FIELD>` with no trailing suffix is still credited."""
    proj = _make_l4_project(tmp_path, _REGS)
    rfm = mod._load_l4_register_field_map(proj)
    assert mod._regmacro_alias_credit(
        "PREFIX_CTRL_SHADOWED_OPERATION", rfm)


def test_multi_token_field_name_longest_match(tmp_path):
    """A multi-token field (MANUAL_OPERATION) must match the whole field, not
    just its leading OPERATION token."""
    proj = _make_l4_project(tmp_path, [
        {"name": "CTRL_SHADOWED",
         "fields": [{"field_name": "OPERATION"},
                    {"field_name": "MANUAL_OPERATION"}]}])
    rfm = mod._load_l4_register_field_map(proj)
    assert mod._regmacro_alias_credit(
        "PREFIX_CTRL_SHADOWED_MANUAL_OPERATION_MASK", rfm)


# ── (4) §4.05 NO-LEAK — register OR field absent → stays MISSING ─────────────
def test_noleak_foreign_register_not_credited(tmp_path):
    """A register absent from L4 (PRNG / AHB / CMOS) is never credited even with
    a closed-set suffix."""
    proj = _make_l4_project(tmp_path, _REGS)
    rfm = mod._load_l4_register_field_map(proj)
    for tok in ("PREFIX_PRNG_SEED_OFFSET",
                "PREFIX_AHB_HADDR_MASK",
                "PREFIX_CMOS_BIAS_OFFSET"):
        assert not mod._regmacro_alias_credit(tok, rfm), tok


def test_noleak_wrong_field_for_register_not_credited(tmp_path):
    """A field that exists in L4 but belongs to a DIFFERENT register is not
    credited against this register — the field must belong to THAT register."""
    proj = _make_l4_project(tmp_path, [
        {"name": "CTRL_SHADOWED", "fields": [{"field_name": "OPERATION"}]},
        {"name": "STATUS", "fields": [{"field_name": "OUTPUT_VALID"}]}])
    rfm = mod._load_l4_register_field_map(proj)
    # OUTPUT_VALID is a field of STATUS, not CTRL_SHADOWED.
    assert not mod._regmacro_alias_credit(
        "PREFIX_CTRL_SHADOWED_OUTPUT_VALID_OFFSET", rfm)
    # OPERATION is a field of CTRL_SHADOWED, not STATUS.
    assert not mod._regmacro_alias_credit(
        "PREFIX_STATUS_OPERATION_OFFSET", rfm)


def test_noleak_unknown_suffix_not_credited(tmp_path):
    """A tail token outside the CLOSED suffix set → not credited."""
    proj = _make_l4_project(tmp_path, _REGS)
    rfm = mod._load_l4_register_field_map(proj)
    assert not mod._regmacro_alias_credit(
        "PREFIX_CTRL_SHADOWED_OPERATION_BOGUS", rfm)
    # extra token after a valid suffix is also rejected.
    assert not mod._regmacro_alias_credit(
        "PREFIX_CTRL_SHADOWED_OPERATION_OFFSET_EXTRA", rfm)


def test_noleak_no_prefix_token_not_credited(tmp_path):
    """The macro shape requires a PREFIX token before the register — a bare
    `<REG>_<FIELD>_<SUFFIX>` with the register at position 0 is not the macro
    shape and is not credited."""
    proj = _make_l4_project(tmp_path, _REGS)
    rfm = mod._load_l4_register_field_map(proj)
    assert not mod._regmacro_alias_credit(
        "CTRL_SHADOWED_OPERATION_OFFSET", rfm)


def test_noleak_empty_regfield_map_credits_nothing():
    """No L4 registers → the alias pass credits nothing (fail-safe)."""
    assert not mod._regmacro_alias_credit(
        "PREFIX_CTRL_SHADOWED_OPERATION_OFFSET", {})


# ── (5) full gate end-state: doc FAIL → PASS via alias credit, no-leak doc FAILs
def _write_doc(proj: Path, name: str, text: str):
    d = proj / "phase1" / "input_doc"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


def test_gate_end_state_macro_doc_passes_unrelated_doc_fails(tmp_path):
    """END-STATE through main(): a doc of ONLY creditable register macros PASSes
    the 100% floor; a doc whose macros reference an absent register FAILs."""
    # >=10 distinct macros so we clear the SKIP_LOW_TOKENS floor.
    regs = [
        {"name": "CTRL_SHADOWED",
         "fields": [{"field_name": "OPERATION"}, {"field_name": "MODE"},
                    {"field_name": "KEY_LEN"},
                    {"field_name": "MANUAL_OPERATION"}]},
        {"name": "TRIGGER",
         "fields": [{"field_name": "DATA_OUT_CLEAR"},
                    {"field_name": "KEY_IV_DATA_IN_CLEAR"}]},
        {"name": "STATUS",
         "fields": [{"field_name": "OUTPUT_VALID"},
                    {"field_name": "INPUT_READY"}]},
    ]
    proj = _make_l4_project(tmp_path, regs)
    macros = []
    for reg, fld in (("CTRL_SHADOWED", "OPERATION"),
                     ("CTRL_SHADOWED", "MODE"),
                     ("CTRL_SHADOWED", "KEY_LEN"),
                     ("CTRL_SHADOWED", "MANUAL_OPERATION"),
                     ("TRIGGER", "DATA_OUT_CLEAR"),
                     ("TRIGGER", "KEY_IV_DATA_IN_CLEAR"),
                     ("STATUS", "OUTPUT_VALID"),
                     ("STATUS", "INPUT_READY")):
        macros.append(f"PREFIX_{reg}_{fld}_OFFSET")
        macros.append(f"PREFIX_{reg}_{fld}_MASK")
    _write_doc(proj, "programmers_guide.txt",
               "Register access macros:\n" + "\n".join(macros) + "\n")
    rc = mod.main([str(proj)])
    rep = json.loads((proj / "reports" / "phase1"
                      / "phase1_input_vs_generated_completeness.json")
                     .read_text())
    assert rc == 0 and rep["verdict"] == "PASS", rep
    assert rep["alias_captured_tokens_count"] >= len(macros), rep
    assert rep["tokens_missing_everywhere"] == 0, rep


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
