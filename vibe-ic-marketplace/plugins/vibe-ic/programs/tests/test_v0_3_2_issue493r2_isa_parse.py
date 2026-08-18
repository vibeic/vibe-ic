"""tests/test_v0_3_2_issue493r2_isa_parse.py — v0.3.2

ROUND-2 fix for REOPENED GitHub issue #493 (IP-catalog ISA-extension
matcher), chip-AGNOSTIC.

FIELD COUNTER-EVIDENCE this file closes:
  The round-1 self-test only ever used the PACKED single-letter spellings
  (rv32imf / rv32imc / rv32i), so it never exercised the real RISC-V
  multi-letter extension spellings. Against the real spellings the base-ISA
  parser false-fired:

    _ext_in_base_isa('F', 'rv32izifencei')  ->  True   (BUG: the 'f' inside
        the Zifencei multi-letter token was treated as a packed single
        letter 'F')
    _ext_in_base_isa('F', 'rv32izfinx')     ->  True   (same class)

  The underscore forms (rv64gc_zifencei) were only ACCIDENTALLY correct
  (the old [a-z]+ regex stopped at '_').

ROUND-2 FIX validated here:
  _ext_in_base_isa parses the post-base letter block per the canonical
  RISC-V ISA-string grammar:
    * single-letter extensions run ONLY until the first z/x that starts a
      multi-letter token;
    * z*/x* tokens (zifencei, zfinx, zicsr, xcustom, ...) are whole tokens
      (split on '_' too); a single-letter query MUST NOT match inside one;
    * a whole-token query (e.g. 'zfinx') DOES match the matching z*/x*
      token.
  AND the same token-awareness extends to the field / scoped / full-text
  fallbacks in _evaluate_match_rule so the end-to-end FPU mis-fire is
  closed, not just the base-ISA helper.

FIELD ACCEPTANCE replayed end-to-end (test_*_field_acceptance_*):
  a project fixture whose ISA string is the REAL rv32izifencei spelling →
  query_catalog yields NO fpu match; a mandatory-F ISA still matches.

KEEP-INTACT note: the round-1 halves the field agent marked OK (the prune
path in ip_catalog_pull and the provenance removal-event in
provenance_output_hash_completeness_check) are NOT touched by this fix and
are NOT re-tested here — they keep their own round-1 coverage.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
_PLUGIN_ROOT = _PROGRAMS.parent

import ip_catalog_query as cat  # noqa: E402


# ===========================================================================
# Layer the round-1 self-test MISSED: _ext_in_base_isa on the REAL spellings
# ===========================================================================
def test_zifencei_does_not_false_fire_F():
    # The exact field-named failing case. 'f' is buried inside the Zifencei
    # multi-letter token and must NOT be reported as a single-letter F.
    assert cat._ext_in_base_isa("f", "rv32izifencei") is False
    assert cat._ext_in_base_isa("F", "RV32IZIFENCEI") is False  # case-insens


def test_zfinx_does_not_false_fire_F():
    # rv32izfinx — same class; 'f' inside Zfinx must not match single F.
    assert cat._ext_in_base_isa("f", "rv32izfinx") is False


def test_zfinx_token_query_matches_whole_token():
    # A whole-token query DOES match the z*/x* token (no underscore form).
    assert cat._ext_in_base_isa("zfinx", "rv32izfinx") is True
    assert cat._ext_in_base_isa("zifencei", "rv32izifencei") is True


def test_packed_single_letters_still_correct():
    # rv32imf / rv64gc — the F/G semantics the round-1 packed-form tests
    # already relied on must remain correct.
    assert cat._ext_in_base_isa("f", "rv32imf") is True
    assert cat._ext_in_base_isa("m", "rv32imf") is True
    assert cat._ext_in_base_isa("i", "rv32imf") is True
    # rv64gc: 'g' and 'c' are genuine single letters; 'f' is NOT literally
    # spelled (it is only implied by G — the literal-grammar matcher must
    # not invent it).
    assert cat._ext_in_base_isa("g", "rv64gc") is True
    assert cat._ext_in_base_isa("c", "rv64gc") is True
    assert cat._ext_in_base_isa("f", "rv64gc") is False


def test_underscore_forms_now_principled_not_accidental():
    # rv64gc_zifencei — underscore separates a whole z*/x* token. The 'f'
    # in zifencei must not match single F; 'g' still matches; the whole
    # token matches a whole-token query.
    assert cat._ext_in_base_isa("f", "rv64gc_zifencei") is False
    assert cat._ext_in_base_isa("g", "rv64gc_zifencei") is True
    assert cat._ext_in_base_isa("c", "rv64gc_zifencei") is True
    assert cat._ext_in_base_isa("zifencei", "rv64gc_zifencei") is True


def test_zicsr_and_multiple_z_tokens():
    # rv32izicsr_zifencei — multiple z tokens; single-letter run is just 'i'.
    assert cat._ext_in_base_isa("i", "rv32izicsr_zifencei") is True
    assert cat._ext_in_base_isa("f", "rv32izicsr_zifencei") is False
    assert cat._ext_in_base_isa("c", "rv32izicsr_zifencei") is False  # in zicsr
    assert cat._ext_in_base_isa("zicsr", "rv32izicsr_zifencei") is True
    assert cat._ext_in_base_isa("zifencei", "rv32izicsr_zifencei") is True


def test_x_custom_token_does_not_leak_single_letters():
    # rv32imxcustom — an X* vendor token must not donate single letters.
    assert cat._ext_in_base_isa("m", "rv32imxcustom") is True
    assert cat._ext_in_base_isa("c", "rv32imxcustom") is False  # inside xcustom
    assert cat._ext_in_base_isa("xcustom", "rv32imxcustom") is True


# ===========================================================================
# Token-aware single-letter membership helper (the second leak of the same
# class: 'f' buried in a multi-letter run anywhere in the text)
# ===========================================================================
def test_single_letter_token_present_grammar():
    # standalone list/word tokens count
    assert cat._single_letter_ext_token_present("f", "M, F, D") is True
    assert cat._single_letter_ext_token_present("f", "m f d") is True
    # buried in a multi-letter alphabetic run does NOT count
    assert cat._single_letter_ext_token_present("f", "zifencei") is False
    assert cat._single_letter_ext_token_present("f", "floating") is False
    assert cat._single_letter_ext_token_present("f", "zfinx") is False


def test_ext_field_contains_token_aware():
    # buried-only mention → not present
    assert cat._ext_field_contains(
        "F", "", "", "isa is rv32izifencei") is False
    assert cat._ext_field_contains(
        "F", "m, c, zifencei", "", "") is False
    # genuine single-letter token / base-ISA → present
    assert cat._ext_field_contains("F", "m, f, d", "", "") is True
    assert cat._ext_field_contains("F", "", "", "isa rv32imf") is True
    # whole multi-letter query still matches
    assert cat._ext_field_contains("zfinx", "", "", "isa rv32izfinx") is True


# ===========================================================================
# Rule-level: the FPU 'contains F' term over packed-vs-real spellings
# ===========================================================================
def _facts_from_l2(project: Path, l2: dict):
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L2_FRS.json").write_text(json.dumps(l2))
    return cat.load_project_facts(project)


def test_rule_real_zifencei_isa_suppresses_F(tmp_path):
    facts = _facts_from_l2(
        tmp_path / "p",
        {"cpu_isa": "rv32izifencei", "cpu_family": "risc-v",
         "cpu_extensions": "M, C, Zifencei"})
    ok, _ = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok is False


def test_rule_real_zfinx_isa_suppresses_F(tmp_path):
    facts = _facts_from_l2(
        tmp_path / "p",
        {"cpu_isa": "rv32izfinx", "cpu_family": "risc-v",
         "cpu_extensions": "M, Zfinx"})
    ok, _ = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok is False


def test_rule_mandatory_F_still_fires(tmp_path):
    facts = _facts_from_l2(
        tmp_path / "p",
        {"cpu_isa": "rv32imf", "cpu_extensions": "M, F"})
    ok, conf = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok and conf == pytest.approx(0.9)


def test_rule_optional_only_F_still_suppressed(tmp_path):
    # round-1 optional-suppression must still hold (regression guard).
    facts = _facts_from_l2(
        tmp_path / "p",
        {"cpu_isa": "rv32imc", "cpu_extensions": "M, C; F (optional)"})
    ok, _ = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok is False


# ===========================================================================
# FIELD ACCEPTANCE — end-to-end via the REAL catalog
# ===========================================================================
def _mk_cpu_project(root: Path, l2: dict) -> Path:
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L2_FRS.json").write_text(json.dumps(l2))
    return root


def test_field_acceptance_real_zifencei_no_fpu(tmp_path):
    """FIELD ACCEPTANCE: a project fixture whose ISA string is the REAL
    rv32izifencei spelling → query_catalog yields NO fpu match."""
    proj = _mk_cpu_project(
        tmp_path / "zifencei",
        {"cpu_isa": "rv32izifencei", "cpu_arch": "bit-serial",
         "cpu_family": "risc-v",
         "cpu_extensions": "M, C, Zifencei (no FPU implemented)"})
    matches = cat.query_catalog(
        proj, catalog_dir=_PLUGIN_ROOT / "ip-catalog", min_confidence=0.4)
    names = [m.ip_name for m in matches]
    assert "fpu_single" not in names, names


def test_field_acceptance_real_zfinx_no_fpu(tmp_path):
    proj = _mk_cpu_project(
        tmp_path / "zfinx",
        {"cpu_isa": "rv32izfinx", "cpu_family": "risc-v",
         "cpu_extensions": "M, Zfinx"})
    matches = cat.query_catalog(
        proj, catalog_dir=_PLUGIN_ROOT / "ip-catalog", min_confidence=0.4)
    names = [m.ip_name for m in matches]
    assert "fpu_single" not in names, names


def test_field_acceptance_isa_only_zifencei_no_fpu(tmp_path):
    # No cpu_extensions field at all — the leak previously fired via the
    # scoped/full-text fallback over the raw rv32izifencei JSON.
    proj = _mk_cpu_project(
        tmp_path / "isaonly",
        {"cpu_isa": "rv32izifencei", "cpu_family": "risc-v"})
    matches = cat.query_catalog(
        proj, catalog_dir=_PLUGIN_ROOT / "ip-catalog", min_confidence=0.4)
    names = [m.ip_name for m in matches]
    assert "fpu_single" not in names, names


def test_field_acceptance_mandatory_F_still_matches_fpu(tmp_path):
    """FIELD ACCEPTANCE: a mandatory-F ISA still matches the FPU."""
    proj = _mk_cpu_project(
        tmp_path / "man",
        {"cpu_isa": "rv32imf", "cpu_family": "risc-v",
         "cpu_extensions": "M, F"})
    matches = cat.query_catalog(
        proj, catalog_dir=_PLUGIN_ROOT / "ip-catalog", min_confidence=0.4)
    names = [m.ip_name for m in matches]
    assert "fpu_single" in names, names
