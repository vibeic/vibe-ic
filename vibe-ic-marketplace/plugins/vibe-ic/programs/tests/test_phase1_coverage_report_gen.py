#!/usr/bin/env python3
"""Tests for phase1_coverage_report_gen.py (BACKLOG-v13 Wave 4)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "phase1_coverage_report_gen.py"


def _run(tmp_path: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), *extra],
        capture_output=True, text=True,
    )


def _put_l(tmp_path: Path, name: str, data: dict):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(json.dumps(data, ensure_ascii=False))


def _put_patterns(tmp_path: Path, patterns: dict, *, in_input: bool = False):
    target = tmp_path / "input" if in_input else tmp_path
    if in_input:
        target.mkdir(parents=True, exist_ok=True)
        (target / "extraction_patterns.json").write_text(
            json.dumps(patterns, ensure_ascii=False))
    else:
        (target / "phase1").mkdir(parents=True, exist_ok=True)
        (target / "phase1" / "extraction_patterns.json").write_text(
            json.dumps(patterns, ensure_ascii=False))


def _put_extracted(tmp_path: Path, name: str, text: str):
    docs = tmp_path / "phase1" / "input_doc"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(text)


# --------------------------------------------------------------------
# 1. Baseline — no patterns + no L docs → no files generated.
# --------------------------------------------------------------------
def test_baseline_no_artifacts(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    md = tmp_path / "reports" / "phase1" / "extraction_coverage_report.md"
    js = tmp_path / "reports" / "phase1" / "extraction_coverage_report.json"
    assert not md.exists()
    assert not js.exists()
    combined = (r.stdout + r.stderr).lower()
    assert ("no patterns" in combined
            or "no extracted docs" in combined
            or "skip" in combined)


# --------------------------------------------------------------------
# 2. Explicit patterns + 100% L docs → both .md and .json with 100.
# --------------------------------------------------------------------
def test_explicit_full_coverage(tmp_path):
    _put_patterns(tmp_path, {
        "20230103-3.txt": [
            {"literal": "H1_MIN[1]", "label": "tick"},
            {"literal": "WKP_MIN[738]", "label": "tick"},
        ]
    })
    _put_l(tmp_path, "L8.json", {
        "evidence": "H1_MIN[1] and WKP_MIN[738] are both present"
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    md = (tmp_path / "reports" / "phase1" / "extraction_coverage_report.md").read_text()
    js = json.loads(
        (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").read_text()
    )
    assert "100" in md
    assert js["overall"]["hit"] == 2
    assert js["overall"]["total"] == 2
    assert js["overall"]["pct"] == 100.0
    assert js["pattern_source"] == "phase1/extraction_patterns.json"
    assert js["ll38_verdict"] == "PASS"
    # per_doc structure
    assert len(js["per_doc"]) == 1
    assert js["per_doc"][0]["doc"] == "20230103-3.txt"
    assert js["per_doc"][0]["missing_literals"] == []


# --------------------------------------------------------------------
# 3. Partial coverage → both reports show miss list populated.
# --------------------------------------------------------------------
def test_partial_coverage(tmp_path):
    _put_patterns(tmp_path, {
        "doc_a.txt": [
            {"literal": "HIT_TOKEN", "label": "ok"},
            {"literal": "MISS_TOKEN", "label": "gap"},
            {"literal": "ANOTHER_MISS", "label": "gap2"},
        ]
    })
    _put_l(tmp_path, "L1.json", {"x": "HIT_TOKEN only"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    js = json.loads(
        (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").read_text()
    )
    assert js["overall"]["hit"] == 1
    assert js["overall"]["total"] == 3
    md = (tmp_path / "reports" / "phase1" / "extraction_coverage_report.md").read_text()
    assert "MISS_TOKEN" in md
    assert "ANOTHER_MISS" in md
    assert "HIT_TOKEN" in md
    # Below threshold → LL-38 verdict FAIL.
    assert js["ll38_verdict"] == "FAIL"


# --------------------------------------------------------------------
# 4. Auto-discovery path — no explicit patterns, but extracted_docs/
#    has a high-signal token that the L docs cite.
# --------------------------------------------------------------------
def test_autodiscover_pattern_source(tmp_path):
    _put_extracted(
        tmp_path, "vendor.txt",
        "spec uses 0x8C poly with H1_MIN[1] tick at 308us"
    )
    _put_l(tmp_path, "L8.json", {
        "evidence": "0x8C polynomial; H1_MIN[1]; 308us"
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    js = json.loads(
        (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").read_text()
    )
    assert js["pattern_source"] == "auto-discovered"
    # autodiscovery harvested >0 patterns and at least our token hit.
    assert js["overall"]["total"] > 0


# --------------------------------------------------------------------
# 5. --json-only flag → only .json emitted.
# --------------------------------------------------------------------
def test_json_only_flag(tmp_path):
    _put_patterns(tmp_path, {
        "doc.txt": [{"literal": "TOK", "label": "x"}]
    })
    _put_l(tmp_path, "L1.json", {"x": "TOK"})
    r = _run(tmp_path, "--json-only")
    assert r.returncode == 0
    assert (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").exists()
    assert not (tmp_path / "reports" / "phase1" / "extraction_coverage_report.md").exists()


# --------------------------------------------------------------------
# 6. --md-only flag → only .md emitted.
# --------------------------------------------------------------------
def test_md_only_flag(tmp_path):
    _put_patterns(tmp_path, {
        "doc.txt": [{"literal": "TOK", "label": "x"}]
    })
    _put_l(tmp_path, "L1.json", {"x": "TOK"})
    r = _run(tmp_path, "--md-only")
    assert r.returncode == 0
    assert (tmp_path / "reports" / "phase1" / "extraction_coverage_report.md").exists()
    assert not (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").exists()


# --------------------------------------------------------------------
# 7. Invalid project dir → exit 2.
# --------------------------------------------------------------------
def test_invalid_project_dir(tmp_path):
    bogus = tmp_path / "does_not_exist"
    r = subprocess.run(
        [sys.executable, str(PROG), str(bogus)],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ====================================================================
# BACKLOG-v13 Wave 5 — expanded auto-discovery tests.
# ====================================================================

# --------------------------------------------------------------------
# 8. Auto-discovery harvests across all six regex families and
#    persists the patterns to extraction_patterns.auto.json.
# --------------------------------------------------------------------
def test_autodiscover_six_families_and_persist(tmp_path):
    text = (
        "CRC poly 0x8C with init 0xFF. The H1_MIN[1] tick is 308us. "
        "See Section 5.2 and Table 14. RD_DIS bit lives at @0x60. "
        "Bandgap reads 1.25V at 25MHz. THE filler word should be ignored."
    )
    _put_extracted(tmp_path, "vendor.txt", text)
    _put_l(tmp_path, "L8.json", {
        "evidence": (
            "0x8C polynomial; 0xFF init; H1_MIN[1] tick 308us; "
            "Section 5.2; Table 14; @0x60; 1.25V; 25MHz; RD_DIS"
        )
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    js = json.loads(
        (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").read_text()
    )
    assert js["pattern_source"] == "auto-discovered"
    auto = json.loads(
        (tmp_path / "phase1" / "extraction_patterns.auto.json").read_text()
    )
    # Persisted file mentions the source doc + has labels
    assert "vendor.txt" in auto
    literals = [it["literal"] for it in auto["vendor.txt"]]
    # Hex constant family
    assert "0x8C" in literals
    # Bracket-kv family
    assert "H1_MIN[1]" in literals
    # Numeric+unit family
    assert any("308us" in lit.replace(" ", "") for lit in literals)
    # Section ref family
    assert any("Section 5.2" in lit for lit in literals)
    # Decimal addr family
    assert "@0x60" in literals
    # Upper ident family (RD_DIS) — and stop-list filtered THE
    assert "RD_DIS" in literals
    assert "THE" not in literals
    # Stdout cited the persistence
    assert "phase1/extraction_patterns.auto.json" in r.stdout


# --------------------------------------------------------------------
# 9. Auto-discovery also scans input/docs/*.txt (Wave 5 expansion).
# --------------------------------------------------------------------
def test_autodiscover_from_input_docs(tmp_path):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.txt").write_text(
        "OPCODE 0xE0 programs OTP. ID_BUS at 1.8V supply.")
    _put_l(tmp_path, "L3.json", {
        "evidence": "0xE0 programs OTP; 1.8V supply on ID_BUS"
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    js = json.loads(
        (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").read_text()
    )
    assert js["pattern_source"] == "auto-discovered"
    assert js["overall"]["total"] > 0
    # Ensure the input/docs source was actually parsed
    assert any(
        d["doc"] == "spec.txt" for d in js["per_doc"]
    )


# --------------------------------------------------------------------
# 10. Auto-discovery per-regex cap is high enough to admit a realistic
#     vendor-doc literal load. Wave-on-fix v1.6.10 raised cap 100 →
#     10000 to align with extraction_coverage_denominator_audit (no
#     cap), so this test now confirms 250 distinct hex constants all
#     persist.
# --------------------------------------------------------------------
def test_autodiscover_per_regex_cap(tmp_path):
    hexes = " ".join(f"0x{n:04X}" for n in range(250))
    _put_extracted(tmp_path, "huge.txt", hexes)
    _put_l(tmp_path, "L1.json", {"x": "0x0000"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    auto = json.loads(
        (tmp_path / "phase1" / "extraction_patterns.auto.json").read_text()
    )
    hex_items = [
        it for it in auto["huge.txt"]
        if it["label"].startswith("auto-discovered (hex_const)")
    ]
    assert len(hex_items) >= 250, (
        f"Raised cap should admit all 250 hex constants; got {len(hex_items)}")


# --------------------------------------------------------------------
# 11. Auto-discovery skipped (persist=False path) when no source docs.
# --------------------------------------------------------------------
def test_autodiscover_no_sources(tmp_path):
    # No extracted_docs/ and no input/docs/ — auto-file must NOT exist.
    _put_l(tmp_path, "L1.json", {"x": "TOK"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp_path / "phase1" / "extraction_patterns.auto.json").exists()


# ====================================================================
# BACKLOG-v13 Wave 8 (v0.119.40) — numeric_unit cross-line literal fix.
# Motivated by 1st_benchmark_benchmark_a/phase1_v0119.39-vendor/RESULT.md:
# the auto-discovery `numeric_unit` regex used `\s+` between number and
# unit, capturing cell-broken PDF rows like `'3.5\nV'`. These literals
# carry a real LF byte; json.dumps escapes LF to `\\n` so they can
# never substring-match the L*.json haystack. 26 such artefacts cost
# 962/988 = 97.4% coverage on a project that should have been 100%.
# Fix: gap is `[ \t\r]*` (same-line only); plus belt-and-suspenders
# drop any literal carrying \n / \r / \t.
# ====================================================================

# --------------------------------------------------------------------
# 12. Cross-line cell-broken PDF text MUST NOT produce a `3.5\nV`
#     literal in the auto-discovery output.
# --------------------------------------------------------------------
def test_numeric_unit_cross_line_not_captured(tmp_path):
    # Simulate a cell-broken PDF row: number on one line, unit on next.
    # Include one same-line ALL_CAPS ident so the auto-discovery file
    # actually gets persisted (no patterns -> no file write).
    text = "Param\nValue\n3.5\nV\n600\npF\n10\nΩ\nMARKER_TOKEN here\n"
    _put_extracted(tmp_path, "broken_table.txt", text)
    _put_l(tmp_path, "L1.json", {"x": "anything"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    auto = json.loads(
        (tmp_path / "phase1" / "extraction_patterns.auto.json").read_text())
    items = auto.get("broken_table.txt", [])
    literals = [it["literal"] for it in items if isinstance(it, dict)]
    # No cross-line literals.
    for lit in literals:
        assert "\n" not in lit, (
            f"cross-line literal leaked: {lit!r}")
        assert "\r" not in lit, (
            f"CR literal leaked: {lit!r}")
        assert "\t" not in lit, (
            f"TAB literal leaked: {lit!r}")
    # Specifically the broken combinations must not appear.
    flat = json.dumps(literals)
    assert "3.5\\nV" not in flat
    assert "600\\npF" not in flat
    assert "10\\nΩ" not in flat


# --------------------------------------------------------------------
# 13. Same-line `3.5 V` MUST capture as a single literal.
# --------------------------------------------------------------------
def test_numeric_unit_same_line_space_captured(tmp_path):
    text = "Bandgap output is 3.5 V at 25C. Current draw 600 pF total."
    _put_extracted(tmp_path, "good_table.txt", text)
    _put_l(tmp_path, "L1.json", {"x": "3.5 V; 600 pF"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    auto = json.loads(
        (tmp_path / "phase1" / "extraction_patterns.auto.json").read_text())
    items = auto.get("good_table.txt", [])
    literals = [it["literal"] for it in items if isinstance(it, dict)]
    # Strip whitespace for comparison since regex may include it.
    stripped = [lit.replace(" ", "") for lit in literals]
    assert any("3.5V" == s for s in stripped), (
        f"3.5 V should have been captured, literals = {literals}")
    assert any("600pF" == s for s in stripped), (
        f"600 pF should have been captured, literals = {literals}")


# --------------------------------------------------------------------
# 14. Same-line tab-separated `3.5\tV` SHOULD be safely DROPPED by the
#     belt-and-suspenders filter even if the regex captures it (the
#     fixed regex allows `[ \t\r]*` so it could match — but the post-
#     filter strips literals containing TAB to keep the JSON haystack
#     match consistent). The point: never let `\t` into a literal.
# --------------------------------------------------------------------
def test_numeric_unit_tab_separated_filtered(tmp_path):
    text = "Bandgap output is\t3.5\tV at 25C."
    _put_extracted(tmp_path, "tab_table.txt", text)
    _put_l(tmp_path, "L1.json", {"x": "anything"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    auto_path = tmp_path / "phase1" / "extraction_patterns.auto.json"
    if auto_path.exists():
        auto = json.loads(auto_path.read_text())
        for items in auto.values():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict):
                    lit = it.get("literal", "")
                    assert "\t" not in lit, (
                        f"tab-bearing literal leaked: {lit!r}")


# ====================================================================
# Wave 9 (v0.119.41) — dump-field defence.
# Motivated by 1st_benchmark_benchmark_a/phase2_v0119.40-vendor/RESULT.md:
# the agent created an `LX_DUMP` catch-all field containing verbatim
# input doc text to lift coverage to 100% trivially. Wave 9 adds a
# size + LCS ratio detector that excludes such fields from the
# primary tally and emits an evidence_quality_distribution.
# ====================================================================

def _put_input_doc(tmp_path: Path, name: str, text: str):
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


def test_wave9_legit_structured_l_doc_credits_full(tmp_path):
    """Legit structured L doc → all data points credit, quality=high."""
    _put_patterns(tmp_path, {
        "spec.txt": [
            {"literal": "0x8C", "label": "crc_poly"},
            {"literal": "GET_ID", "label": "opcode"},
        ],
    })
    _put_l(tmp_path, "L8.json", {
        "crc_poly": "0x8C",
        "opcodes": ["GET_ID", "PUT_ID"],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    js = json.loads(
        (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").read_text()
    )
    qd = js["evidence_quality_distribution"]
    assert qd["high"] == 2, qd
    assert qd["low"] == 0, qd
    assert qd["missing"] == 0, qd
    assert js["overall"]["pct"] == 100.0
    assert js["dump_fields"] == []


def test_wave9_dump_field_excluded_from_primary(tmp_path):
    """L doc with `LX_DUMP` literal copy of input doc → data points
    found ONLY in the dump field get quality=low and are EXCLUDED
    from the primary coverage tally; report flags WARN."""
    big_text = ("Verbatim doc copy. " * 5000) + " GET_ID 0x8C"
    _put_input_doc(tmp_path, "spec.txt", big_text)
    _put_patterns(tmp_path, {
        "spec.txt": [
            {"literal": "GET_ID", "label": "opcode"},
            {"literal": "0x8C", "label": "crc_poly"},
        ],
    })
    # Only LX_DUMP carries the literals — no structured L doc cites
    # them.
    _put_l(tmp_path, "LX_DUMP.json", {
        "LX_DUMP": big_text,
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    js = json.loads(
        (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").read_text()
    )
    # The dump field must be detected.
    assert len(js["dump_fields"]) >= 1, js["dump_fields"]
    df = js["dump_fields"][0]
    assert df["classification"] == "DUMP"
    assert df["lcs_ratio"] >= 0.80, df
    # Data points found only in the dump must NOT be credited primary.
    qd = js["evidence_quality_distribution"]
    assert qd["low"] >= 2, qd
    assert qd["high"] == 0, qd
    assert js["overall"]["hit"] == 0, js["overall"]
    # Stdout flags WARN for dump.
    assert "WARN" in r.stdout and "dump" in r.stdout.lower(), r.stdout


def test_wave9_dump_threshold_under_50kb_still_credited(tmp_path):
    """Edge: a 49 KB field is under the dump-size threshold and must
    still be credited, even if it's a verbatim copy of the input doc.
    (Wave 9 only attacks the >=50 KB AND >=80% case to avoid penalising
    medium-size structured documents.)"""
    # 49 KB of text.
    txt_49kb = "x" * 49_000
    _put_input_doc(tmp_path, "spec.txt", txt_49kb + " MARKER")
    _put_patterns(tmp_path, {
        "spec.txt": [{"literal": "MARKER", "label": "tok"}],
    })
    _put_l(tmp_path, "L1.json", {"big_field": txt_49kb + " MARKER"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    js = json.loads(
        (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").read_text()
    )
    # No dump fields detected (under threshold).
    assert js["dump_fields"] == [], js["dump_fields"]
    # Literal credited primary.
    assert js["overall"]["hit"] == 1, js["overall"]
    qd = js["evidence_quality_distribution"]
    assert qd["high"] == 1, qd


def test_wave9_quality_distribution_in_report(tmp_path):
    """The MD/JSON report must include the evidence_quality_distribution
    block."""
    _put_patterns(tmp_path, {
        "spec.txt": [
            {"literal": "TOK_HIT", "label": "ok"},
            {"literal": "TOK_MISS", "label": "gap"},
        ],
    })
    _put_l(tmp_path, "L1.json", {"x": "TOK_HIT only"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    md = (tmp_path / "reports" / "phase1" / "extraction_coverage_report.md").read_text()
    assert "Evidence quality distribution" in md, md
    js = json.loads(
        (tmp_path / "reports" / "phase1" / "extraction_coverage_report.json").read_text()
    )
    qd = js["evidence_quality_distribution"]
    assert qd["high"] == 1, qd
    assert qd["missing"] == 1, qd
