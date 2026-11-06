"""Tests for the orchestrator + Phase-1-ingestion + catalog-query fixes.

Covers four chip-AGNOSTIC fixes:

  1. Orchestrator auto-runs Phase 1 in docs mode for Path-B vendor-docs
     projects (decision function only — no docker run).
  2. Phase-1 input-mode detector treats a populated raw-docs dir as
     docs mode unless it contains layer-JSON (L*.json).
  3. memmap prose ranges ("0x0000 - 0x3FFF") yield BOTH endpoints as
     indexed_register_address constants with provenance.
  4. ip_catalog_query: scoped structured-L2 fallback, SoC-top
     preference + depends_on auto-include, F-extension negation guard.

All tests run WITHOUT docker.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as p1doc      # noqa: E402
import ip_catalog_query as cat                  # noqa: E402


# ===========================================================================
# Fix 1 — orchestrator auto-runs phase1 docs mode for Path-B
# ===========================================================================
















# ===========================================================================
# Fix 2 — input-mode detector: raw docs = docs mode unless layer-JSON
# ===========================================================================






# ===========================================================================
# Fix 3 — memmap prose range → both endpoints as constants
# ===========================================================================
def test_fix3_range_yields_both_endpoints():
    extracted = {"datasheet.md": "The RAM region occupies 0x0000 - 0x3FFF."}
    consts = p1doc._extract_memmap_range_constants(extracted)
    addrs = {c["address"].lower() for c in consts}
    assert "0x0000" in addrs
    assert "0x3fff" in addrs
    assert len(consts) == 2
    for c in consts:
        assert c["kind"] == "indexed_register_address"
        assert c["range"] == "0x0000 - 0x3FFF"
        assert c["evidence"] == "input/docs/datasheet.md"
        assert "0x0000 - 0x3FFF" in c["evidence_line"]
    eps = {c["endpoint"] for c in consts}
    assert eps == {"low", "high"}


def test_fix3_endash_emdash_supported():
    extracted = {"f.md": "Flash 0x40000000–0x4FFFFFFF and ROM 0x0—0xFF"}
    consts = p1doc._extract_memmap_range_constants(extracted)
    addrs = {c["address_int"] for c in consts}
    assert 0x40000000 in addrs and 0x4FFFFFFF in addrs
    assert 0x0 in addrs and 0xFF in addrs


def test_fix3_inverted_or_equal_range_skipped():
    extracted = {"f.md": "bad 0xFF - 0x00 and equal 0x10 - 0x10"}
    consts = p1doc._extract_memmap_range_constants(extracted)
    assert consts == []


def test_fix3_no_range_no_constants():
    extracted = {"f.md": "register CTRL at 0x10 read/write"}
    consts = p1doc._extract_memmap_range_constants(extracted)
    assert consts == []


def test_fix3_address_int_correct():
    extracted = {"m.md": "0x0000 - 0x3FFF"}
    consts = p1doc._extract_memmap_range_constants(extracted)
    by_ep = {c["endpoint"]: c for c in consts}
    assert by_ep["low"]["address_int"] == 0
    assert by_ep["high"]["address_int"] == 0x3FFF


# ===========================================================================
# Fix 4 — ip_catalog_query SoC-top / structured-L2 / negation
# ===========================================================================
def _write_l2(project: Path, l2: dict):
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L2_FRS.json").write_text(json.dumps(l2))


def _facts_from_l2(project: Path, l2: dict):
    _write_l2(project, l2)
    return cat.load_project_facts(project)


# -- 4a scoped fallback + lowered confidence -------------------------------
def test_fix4a_discrete_key_beats_substring(tmp_path):
    """Discrete structured key match (0.9) ranks above scoped substring."""
    proj = tmp_path / "p"
    facts = _facts_from_l2(proj, {"cpu_isa": "rv32imc"})
    ok, conf = cat._evaluate_match_rule("L2.cpu_isa starts with 'rv32'", facts)
    assert ok and conf == pytest.approx(0.9)


def test_fix4a_scoped_substring_lowered(tmp_path):
    """No discrete key, but value appears in the L2 section text →
    scoped substring hit at lowered confidence (< structured)."""
    proj = tmp_path / "p"
    # cpu_isa not a discrete key; "rv32" only present as free text in L2.
    facts = _facts_from_l2(proj, {"description": "a rv32 based core"})
    ok, conf = cat._evaluate_match_rule("L2.cpu_isa starts with 'rv32'", facts)
    assert ok
    assert conf <= cat._CONF_SCOPED_SUBSTR
    assert conf < 0.9


def test_fix4a_scoped_does_not_leak_other_layers(tmp_path):
    """A structured-L2 predicate must NOT fire on text that lives only in
    a different layer (scoped to L2 only)."""
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_FRS.json").write_text(json.dumps({"function": "crypto"}))
    (gd / "L4_REG.json").write_text(json.dumps({"note": "rv32 memory map"}))
    facts = cat.load_project_facts(proj)
    ok, _ = cat._evaluate_match_rule("L2.cpu_isa starts with 'rv32'", facts)
    assert ok is False


# -- 4c extension-negation guard -------------------------------------------
def test_fix4c_integer_only_suppresses_f(tmp_path):
    """ISA contains 'F' must NOT fire for an integer-only spec."""
    proj = tmp_path / "p"
    facts = _facts_from_l2(
        proj, {"cpu_isa": "rv32i", "cpu_arch": "integer-only, no FPU"})
    ok, _ = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok is False


def test_fix4c_explicit_no_f_excludes(tmp_path):
    proj = tmp_path / "p"
    facts = _facts_from_l2(proj, {"cpu_isa": "rv32i", "notes": "no F extension"})
    ok, _ = cat._evaluate_match_rule("L2.cpu_isa contains 'F'", facts)
    assert ok is False


def test_fix4c_f_present_still_matches(tmp_path):
    """Guard must not over-suppress: real F-extension still matches."""
    proj = tmp_path / "p"
    facts = _facts_from_l2(proj, {"cpu_extensions": "M, F, D"})
    ok, conf = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok and conf == pytest.approx(0.9)


# -- 4b SoC-top detection + preference + depends_on -------------------------
def test_fix4b_is_soc_top_detection():
    leaf = {"ip_name": "core", "rtl_files": ["core_alu.v", "core_dec.v"]}
    top = {"ip_name": "soc", "rtl_files": ["foo.v", "chip_top.v"]}
    arch_top = {"ip_name": "x", "implements": {"architecture": "soc_wrapper"}}
    explicit = {"ip_name": "y", "is_soc_top": True}
    assert cat._is_soc_top(leaf) is False
    assert cat._is_soc_top(top) is True
    assert cat._is_soc_top(arch_top) is True
    assert cat._is_soc_top(explicit) is True


def test_fix4b_soc_top_preferred_over_leaf(tmp_path, monkeypatch):
    """When a SoC-top and a leaf core match at equal confidence, the
    SoC-top ranks first."""
    proj = tmp_path / "p"
    _write_l2(proj, {"cpu_family": "risc-v"})
    cat_dir = tmp_path / "ip-catalog"
    (cat_dir / "_schema").mkdir(parents=True)
    (cat_dir / "_schema" / "x.json").write_text("{}")
    leaf_dir = cat_dir / "cpu" / "leaf"
    top_dir = cat_dir / "cpu" / "top"
    leaf_dir.mkdir(parents=True)
    top_dir.mkdir(parents=True)
    rule = "L2.cpu_family == 'risc-v'"
    (leaf_dir / "manifest.yaml").write_text(
        "ip_name: leafcore\nlicense: MIT\n"
        f"matches_when:\n  - \"{rule}\"\n"
        "rtl_files:\n  - leafcore_alu.v\n")
    (top_dir / "manifest.yaml").write_text(
        "ip_name: socttop\nlicense: MIT\n"
        f"matches_when:\n  - \"{rule}\"\n"
        "rtl_files:\n  - socttop_top.v\n")
    matches = cat.query_catalog(proj, catalog_dir=cat_dir, min_confidence=0.4)
    names = [m.ip_name for m in matches]
    assert "socttop" in names and "leafcore" in names
    assert names.index("socttop") < names.index("leafcore")


def test_fix4b_depends_on_auto_included(tmp_path):
    """A matched IP's depends_on entry is auto-pulled even if it does not
    independently match."""
    proj = tmp_path / "p"
    _write_l2(proj, {"cpu_family": "risc-v"})
    cat_dir = tmp_path / "ip-catalog"
    (cat_dir / "_schema").mkdir(parents=True)
    (cat_dir / "_schema" / "x.json").write_text("{}")
    main_dir = cat_dir / "cpu" / "main"
    dep_dir = cat_dir / "lib" / "prim"
    main_dir.mkdir(parents=True)
    dep_dir.mkdir(parents=True)
    (main_dir / "manifest.yaml").write_text(
        "ip_name: maincpu\nlicense: MIT\n"
        "matches_when:\n  - \"L2.cpu_family == 'risc-v'\"\n"
        "depends_on:\n  - primlib\n")
    # primlib has NO matches_when that fires (keys on absent field)
    (dep_dir / "manifest.yaml").write_text(
        "ip_name: primlib\nlicense: MIT\n"
        "matches_when:\n  - \"L2.cpu_family == 'nonexistent'\"\n")
    matches = cat.query_catalog(proj, catalog_dir=cat_dir, min_confidence=0.4)
    names = [m.ip_name for m in matches]
    assert "maincpu" in names
    assert "primlib" in names  # auto-included via depends_on
