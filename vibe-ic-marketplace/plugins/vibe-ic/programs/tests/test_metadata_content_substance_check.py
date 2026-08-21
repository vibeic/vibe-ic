"""tests/test_metadata_content_substance_check.py — v1.6.51

Catches phase1 metadata files that satisfy v1.6.26 canonical-taxonomy
by location alone but ship empty / near-empty content."""
from __future__ import annotations

import json
from pathlib import Path

from programs.metadata_content_substance_check import (
    audit, _SUBSTANCE_REQUIREMENTS,
)


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


# ---------------------------------------------------------------------------
# Vacuous PASS — no whitelisted files present.
# ---------------------------------------------------------------------------

def test_vacuous_pass_no_files(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, findings, summary = audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []
    assert all(not v["present"] for v in summary.values())


# ---------------------------------------------------------------------------
# PASS — every present file meets substance.
# ---------------------------------------------------------------------------

def test_pass_extraction_patterns_with_entries_array_form(tmp_path: Path):
    p = tmp_path / "proj"
    _w(p / "phase1" / "extraction_patterns.json",
       [{"name": "addr_re", "pattern": "0x[0-9A-Fa-f]+"}])
    verdict, findings, _ = audit(p)
    assert verdict == "PASS"
    assert findings == []


def test_pass_extraction_patterns_dict_of_lists_keyed_by_filename(
        tmp_path: Path) -> None:
    """Real phase1 layout: top-level keys are source filenames,
    each value is a list of pattern entries; `_comment` /
    `_schema_version` are skipped as metadata."""
    p = tmp_path / "proj"
    _w(p / "phase1" / "extraction_patterns.json", {
        "_comment": "Canonical extraction patterns auto-seeded by ...",
        "datasheet.txt": [
            {"literal": "0xFF00", "label": "auto-discovered (hex)"}],
        "appnote.txt": [
            {"literal": "@8", "label": "auto-discovered (decimal_addr)"}],
    })
    verdict, findings, summary = audit(p)
    assert verdict == "PASS", findings
    rel = "phase1/extraction_patterns.json"
    assert summary[rel]["entries"] == 2  # `_comment` excluded


def test_fail_extraction_patterns_dict_only_metadata_no_entries(
        tmp_path: Path) -> None:
    """`_comment` alone with no real per-file entries fails min=1."""
    p = tmp_path / "proj"
    _w(p / "phase1" / "extraction_patterns.json", {
        "_comment": "phase1 runner placeholder, no patterns yet",
    })
    verdict, findings, _ = audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "EMPTY_OR_BELOW_MIN"
    assert findings[0].observed_entries == 0


def test_pass_extraction_patterns_dict_with_patterns_key(tmp_path: Path):
    p = tmp_path / "proj"
    _w(p / "phase1" / "extraction_patterns.json",
       {"patterns": [{"name": "addr_re", "pattern": "0x[0-9A-Fa-f]+"}]})
    verdict, findings, _ = audit(p)
    assert verdict == "PASS"
    assert findings == []


def test_pass_completeness_check_config(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _w(p / "phase1" / "completeness_check_config.json",
       {"version": 1, "checks": [{"id": "x", "kind": "regex"}]})
    verdict, _, _ = audit(p)
    assert verdict == "PASS"


def test_pass_ai_deep_review_patches_empty_is_permitted(tmp_path: Path):
    p = tmp_path / "proj"
    _w(p / "phase1" / "ai_deep_review_patches.json", {"patches": {}})
    verdict, findings, _ = audit(p)
    # ai_deep_review_patches min_entries = 0; empty is OK.
    assert verdict == "PASS"
    assert findings == []


def test_pass_ai_deep_review_patches_legacy_array_form(tmp_path: Path):
    p = tmp_path / "proj"
    _w(p / "phase1" / "ai_deep_review_patches.json", [])
    verdict, findings, _ = audit(p)
    assert verdict == "PASS"
    assert findings == []


def test_pass_ai_deep_review_patches_with_real_entries(tmp_path: Path):
    p = tmp_path / "proj"
    _w(p / "phase1" / "ai_deep_review_patches.json", {
        "patches": {
            "L4_REGMAP": [
                {"literal": "ADDR[91]",
                 "extraction_strategy": "ai_deep_review_patch"}],
            "L11_OTP_CONTENT": [
                {"literal": "OTP[60]",
                 "extraction_strategy": "ai_deep_review_patch"}],
        }})
    verdict, _, summary = audit(p)
    assert verdict == "PASS"
    rel = "phase1/ai_deep_review_patches.json"
    assert summary[rel]["entries"] == 2


# ---------------------------------------------------------------------------
# FAIL — empty content slips taxonomy.
# ---------------------------------------------------------------------------

def test_fail_empty_extraction_patterns_object(tmp_path: Path) -> None:
    """Backlog example #1: `phase1/extraction_patterns.json → {}`.
    Empty dict is treated as the dict-of-lists shape with zero entries
    (all-lists is vacuously true on an empty dict's values), so the
    rule is EMPTY_OR_BELOW_MIN. Either rule is acceptable as long as
    the verdict is FAIL — the doctrine is "empty content cannot pass
    taxonomy alone", not which classification the gate picks."""
    p = tmp_path / "proj"
    _w(p / "phase1" / "extraction_patterns.json", {})
    verdict, findings, _ = audit(p)
    assert verdict == "FAIL"
    assert len(findings) == 1
    assert findings[0].rule in ("BROKEN_SCHEMA", "EMPTY_OR_BELOW_MIN")
    assert findings[0].observed_entries in (None, 0)


def test_fail_extraction_patterns_auto_empty_array(tmp_path: Path) -> None:
    """Backlog example #2: `extraction_patterns.auto.json →
    {"patterns": []}`."""
    p = tmp_path / "proj"
    _w(p / "phase1" / "extraction_patterns.auto.json", {"patterns": []})
    verdict, findings, _ = audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "EMPTY_OR_BELOW_MIN"
    assert findings[0].observed_entries == 0
    assert findings[0].min_entries == 1


def test_fail_completeness_check_config_empty_checks(tmp_path: Path) -> None:
    """Backlog example #3:
    `completeness_check_config.json → {"version":1,"checks":[]}`."""
    p = tmp_path / "proj"
    _w(p / "phase1" / "completeness_check_config.json",
       {"version": 1, "checks": []})
    verdict, findings, _ = audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "EMPTY_OR_BELOW_MIN"


def test_fail_completeness_check_config_missing_checks_key(tmp_path: Path):
    p = tmp_path / "proj"
    _w(p / "phase1" / "completeness_check_config.json", {"version": 1})
    verdict, findings, _ = audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "BROKEN_SCHEMA"


def test_fail_ai_deep_review_patches_naked_empty_dict(tmp_path: Path) -> None:
    """`ai_deep_review_patches.json → {}` (no `patches` key) is
    malformed even though patches==0 is allowed."""
    p = tmp_path / "proj"
    _w(p / "phase1" / "ai_deep_review_patches.json", {})
    verdict, findings, _ = audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "BROKEN_SCHEMA"


# ---------------------------------------------------------------------------
# FAIL — invalid JSON.
# ---------------------------------------------------------------------------

def test_fail_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    f = p / "phase1" / "extraction_patterns.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{not: valid json,,,")
    verdict, findings, _ = audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "INVALID_JSON"


# ---------------------------------------------------------------------------
# Mixed: some files PASS, one FAILs → overall FAIL.
# ---------------------------------------------------------------------------

def test_partial_fail_one_empty_amid_three_substantive(tmp_path: Path):
    p = tmp_path / "proj"
    _w(p / "phase1" / "extraction_patterns.json",
       [{"name": "x", "pattern": "."}])
    _w(p / "phase1" / "extraction_patterns.auto.json",
       [{"name": "y", "pattern": "."}])
    _w(p / "phase1" / "completeness_check_config.json",
       {"checks": [{"id": "c"}]})
    # ai_deep_review_patches present but malformed.
    _w(p / "phase1" / "ai_deep_review_patches.json",
       {"unexpected_key": "value"})
    verdict, findings, _ = audit(p)
    assert verdict == "FAIL"
    assert len(findings) == 1
    assert findings[0].rel_path == "phase1/ai_deep_review_patches.json"


# ---------------------------------------------------------------------------
# Schema declarative-completeness — every requirement has a handler.
# ---------------------------------------------------------------------------

def test_every_requirement_has_known_shape() -> None:
    """If a future PR adds a new whitelisted slot, it must declare a
    shape this gate's handler dispatcher already supports. This test
    keeps the dict + handler set in lock-step."""
    from programs.metadata_content_substance_check import _SHAPE_HANDLERS
    for rel, spec in _SUBSTANCE_REQUIREMENTS.items():
        assert spec["shape"] in _SHAPE_HANDLERS, (
            f"{rel}: declared shape {spec['shape']!r} has no handler "
            f"in _SHAPE_HANDLERS")
