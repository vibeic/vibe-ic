#!/usr/bin/env python3
"""Tests for extraction_coverage_check.py (LL-38)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "extraction_coverage_check.py"


def _run(tmp_path: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), *extra],
        capture_output=True, text=True,
    )


def _put_input_doc(tmp_path: Path, name: str, text: str = "doc body"):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(text)


def _put_extracted(tmp_path: Path, name: str, text: str):
    docs = tmp_path / "phase1" / "input_doc"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(text)


def _put_l(tmp_path: Path, name: str, data: dict):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(json.dumps(data, ensure_ascii=False))


def _put_patterns(tmp_path: Path, patterns: dict, *,
                  in_input: bool = False):
    target = tmp_path / "input" if in_input else tmp_path
    if in_input:
        # input/extraction_patterns.json (no phase1/ prefix; this is
        # a project-input override, not the canonical phase1 location).
        target.mkdir(parents=True, exist_ok=True)
        (target / "extraction_patterns.json").write_text(
            json.dumps(patterns, ensure_ascii=False))
    else:
        (target / "phase1").mkdir(parents=True, exist_ok=True)
        (target / "phase1" / "extraction_patterns.json").write_text(
            json.dumps(patterns, ensure_ascii=False))


# 1. Baseline — no generated_docs. Silent skip.
def test_no_generated_docs_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "skip" in r.stdout.lower()


# 2. No matched input docs / no patterns / no extracted_docs — silent skip.
def test_no_matched_input_docs_silent_pass(tmp_path):
    _put_l(tmp_path, "L1.json", {"foo": "bar"})
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "skip" in r.stdout.lower()


# 3. Positive PASS — explicit pattern file matches L docs verbatim.
def test_positive_full_coverage_pass(tmp_path):
    _put_input_doc(tmp_path, "20230103-3.txt",
                   "FPGA - 20230103-3\n"
                   "H1_MIN[1] H1_MAX[192]\n"
                   "H0_MIN[196] H0_MAX[612]\n"
                   "BR_MIN[637] BR_MAX[1314]\n"
                   "IBT_MIN[234] IBT_MAX[2000]\n"
                   "WKP_MIN[738]\n"
                   "RSP_74[91] RSP_E0[15917]\n")
    _put_patterns(tmp_path, {
        "20230103-3.txt": [
            {"literal": "H1_MIN[1]",   "label": "tick"},
            {"literal": "H1_MAX[192]", "label": "tick"},
            {"literal": "H0_MIN[196]", "label": "tick"},
            {"literal": "H0_MAX[612]", "label": "tick"},
            {"literal": "BR_MIN[637]", "label": "tick"},
            {"literal": "BR_MAX[1314]","label": "tick"},
            {"literal": "IBT_MIN[234]","label": "tick"},
            {"literal": "WKP_MIN[738]","label": "tick"},
            {"literal": "RSP_74[91]",  "label": "rsp"},
            {"literal": "RSP_E0[15917]","label": "rsp"},
        ]
    })
    _put_l(tmp_path, "L8.json", {
        "extraction_evidence": {
            "20230103-3.txt": [
                "H1_MIN[1]", "H1_MAX[192]", "H0_MIN[196]", "H0_MAX[612]",
                "BR_MIN[637]", "BR_MAX[1314]", "IBT_MIN[234]",
                "WKP_MIN[738]", "RSP_74[91]", "RSP_E0[15917]",
            ]
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
    assert "100%" in r.stdout
    assert "explicit" in r.stdout


# 4. Negative FAIL — 0% coverage with explicit pattern file.
def test_negative_zero_coverage_fails(tmp_path):
    _put_input_doc(tmp_path, "20230103-3.txt", "vendor_table_data")
    _put_patterns(tmp_path, {
        "20230103-3.txt": [
            {"literal": "H1_MIN[1]",  "label": "tick"},
            {"literal": "WKP_MIN[738]","label": "tick"},
        ]
    })
    _put_l(tmp_path, "L8.json", {"unrelated": "fields"})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "FAIL" in r.stdout
    assert "0%" in r.stdout


# 5. Threshold can be lowered via --threshold.
def test_threshold_override(tmp_path):
    _put_input_doc(tmp_path, "20230103-3.txt", "")
    _put_patterns(tmp_path, {
        "20230103-3.txt": [
            {"literal": f"NEEDLE_{i}", "label": "x"} for i in range(10)
        ] + [{"literal": "WKP_MIN[738]", "label": "tick"}]
    })
    # 1 of 11 hits ≈ 9%.
    _put_l(tmp_path, "L8.json", {"x": "WKP_MIN[738]"})
    r_strict = _run(tmp_path)
    assert r_strict.returncode == 1
    r_lax = _run(tmp_path, "--threshold", "0.05")
    assert r_lax.returncode == 0


# 6. Wave 23 (v0.119.55) — extraction coverage is non-waivable.
#    The legacy `extraction_coverage_acceptable_below_95` waiver no
#    longer suppresses below-threshold FAIL.
def test_waiver_no_longer_suppresses_below_threshold(tmp_path):
    _put_input_doc(tmp_path, "20230103-3.txt", "")
    _put_patterns(tmp_path, {
        "20230103-3.txt": [
            {"literal": f"NEEDLE_{i}", "label": "x"} for i in range(10)
        ] + [{"literal": "WKP_MIN[738]", "label": "tick"}]
    })
    _put_l(tmp_path, "L8.json", {"x": "WKP_MIN[738]"})
    (tmp_path / "waivers.json").write_text(json.dumps({
        "extraction_coverage_acceptable_below_95":
            "First-pass benchmark shows 10% coverage; deferring full "
            "extraction to next iteration; tracked in ticket VENDOR-42.",
    }))
    r = _run(tmp_path)
    # Wave 23 — the waiver no longer pulls the gate to PASS; FAIL.
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    # The error message must direct the agent to extraction_patterns.json
    # (NOT to a waiver).
    assert "waiver" in r.stdout.lower()
    assert "no waiver" in r.stdout.lower() or "NO waiver" in r.stdout


# 7. NEW (v0.119.35): explicit pattern file at <project>/extraction_patterns.json
#    is used in preference to anything else (chip-agnostic protocol).
def test_explicit_patterns_root_used(tmp_path):
    _put_input_doc(tmp_path, "vendor_doc_X.txt", "anything")
    _put_patterns(tmp_path, {
        "vendor_doc_X.txt": [
            {"literal": "MAGIC_TOKEN_42", "label": "test marker"},
        ]
    })
    _put_l(tmp_path, "L_custom.json", {"data": "MAGIC_TOKEN_42 present"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "100%" in r.stdout
    assert "explicit" in r.stdout
    # No WARN since it's explicit, not auto-discovered.
    assert "auto-discovered" not in r.stdout.lower() or \
        "pattern source = explicit" in r.stdout


# 8. NEW: extraction_patterns.json under input/ directory is also accepted.
def test_explicit_patterns_input_dir_used(tmp_path):
    _put_input_doc(tmp_path, "vendor_doc_Y.txt", "anything")
    _put_patterns(tmp_path, {
        "vendor_doc_Y.txt": [
            {"literal": "TOKEN_INPUT_DIR", "label": "test marker"},
        ]
    }, in_input=True)
    _put_l(tmp_path, "L_custom.json", {"data": "TOKEN_INPUT_DIR present"})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "100%" in r.stdout
    assert "explicit" in r.stdout


# 9. NEW: no patterns file but extracted_docs/ exists → auto-discovery + WARN.
def test_autodiscovery_emits_warn(tmp_path):
    # Provide an extracted_docs entry with a high-signal hex literal.
    _put_extracted(tmp_path, "vendor_doc_Z.txt",
                   "Spec table: H1_MIN[1] H1_MAX[192] 0x8C poly 308us wake.")
    # L doc covers exactly that literal so coverage is non-zero.
    _put_l(tmp_path, "L_autocheck.json", {
        "evidence": "0x8C polynomial; H1_MIN[1]; H1_MAX[192]; 308us"
    })
    r = _run(tmp_path, "--threshold", "0.0")
    # threshold 0 → always PASS but should still print WARN.
    assert r.returncode == 0
    combined = (r.stdout + r.stderr).lower()
    assert "warn" in combined
    assert "auto-discovered" in r.stdout.lower()


# 10. NEW: no patterns + no extracted_docs → silent skip (no false FAIL).
def test_no_patterns_no_extracted_silent_skip(tmp_path):
    # Wave 30 (v0.119.62) — when input/docs/ exists but no patterns
    # could be derived, the gate fails closed (the previous silent-
    # skip path was the 35th-attempt 100%-coverage bypass).
    _put_input_doc(tmp_path, "anything.md", "blah")
    _put_l(tmp_path, "L1.json", {"foo": "bar"})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "FAIL" in r.stdout
    assert "Wave 30" in r.stdout
    assert "input/docs/" in r.stdout


# ─────────────────────────────────────────────────────────────────────
# BACKLOG-v13 Wave 6 (v0.119.38) — LL-38 sync with phase1_coverage_report_gen
# ─────────────────────────────────────────────────────────────────────

# 11. NEW (Wave 6): auto-discovery harvests `decimal_addr` family
#     (e.g. @0x42 OTP addresses).
def test_autodiscovery_decimal_addr_family(tmp_path):
    _put_extracted(tmp_path, "otp_map.txt",
                   "OTP layout: word @0x42 holds CRC; word @128 holds rev.")
    # Make sure both literals are reflected in L docs so coverage > 0.
    _put_l(tmp_path, "L7.json",
           {"otp": "see @0x42 (CRC) and @128 (revision)"})
    r = _run(tmp_path, "--threshold", "0.0")
    assert r.returncode == 0
    auto_file = tmp_path / "phase1" / "extraction_patterns.auto.json"
    assert auto_file.is_file()
    persisted = json.loads(auto_file.read_text())
    flat = json.dumps(persisted)
    assert "@0x42" in flat
    assert "@128" in flat
    assert "decimal_addr" in flat


# 12. NEW (Wave 6): auto-discovery harvests `section_ref` family
#     (Section 4.2, Table 7, Figure 3).
def test_autodiscovery_section_ref_family(tmp_path):
    _put_extracted(tmp_path, "datasheet.txt",
                   "See Section 4.2 for timing; Table 7 for opcodes; "
                   "Figure 3 shows the wave.")
    _put_l(tmp_path, "L1.json",
           {"refs": "Section 4.2 timing; Table 7 opcodes; Figure 3 wave"})
    r = _run(tmp_path, "--threshold", "0.0")
    assert r.returncode == 0
    auto_file = tmp_path / "phase1" / "extraction_patterns.auto.json"
    assert auto_file.is_file()
    persisted = json.loads(auto_file.read_text())
    flat = json.dumps(persisted)
    assert "Section 4.2" in flat
    assert "Table 7" in flat
    assert "Figure 3" in flat
    assert "section_ref" in flat


# 13. NEW (Wave 6): auto-discovery scans input/docs/*.txt in addition
#     to extracted_docs/*.txt.
def test_autodiscovery_scans_input_docs_txt(tmp_path):
    # Only put a .txt under input/docs/, no extracted_docs/ at all.
    _put_input_doc(tmp_path, "vendor_spec.txt",
                   "Wake handshake uses 0xC3; H1_MIN[1]=308us.")
    _put_l(tmp_path, "L8.json",
           {"timing": "0xC3 wake; H1_MIN[1]=308us"})
    r = _run(tmp_path, "--threshold", "0.0")
    assert r.returncode == 0
    # WARN must be printed because patterns came from auto-discovery.
    combined = (r.stdout + r.stderr).lower()
    assert "auto-discovered" in r.stdout.lower()
    assert "warn" in combined
    auto_file = tmp_path / "phase1" / "extraction_patterns.auto.json"
    assert auto_file.is_file()
    persisted = json.loads(auto_file.read_text())
    assert "vendor_spec.txt" in persisted


# 14. NEW (Wave 6): English-filler stop-list — common words like THE/AND/MUST
#     must NOT be harvested as patterns.
def test_autodiscovery_english_filler_stoplist(tmp_path):
    _put_extracted(tmp_path, "prose.txt",
                   "THE DEVICE SHALL BE READY WHEN MUST CONDITIONS HOLD "
                   "AND BOTH POWER AND RESET ARE STABLE.")
    # Force at least one real pattern so file is persisted.
    _put_extracted(tmp_path, "real.txt", "OPCODE_RESET token MAGIC_TOKEN_99")
    _put_l(tmp_path, "L1.json", {"x": "OPCODE_RESET MAGIC_TOKEN_99"})
    r = _run(tmp_path, "--threshold", "0.0")
    assert r.returncode == 0
    auto_file = tmp_path / "phase1" / "extraction_patterns.auto.json"
    assert auto_file.is_file()
    persisted = json.loads(auto_file.read_text())
    flat = json.dumps(persisted)
    # Stop-list filler words must be absent.
    for filler in ("THE", "AND", "MUST", "SHALL", "WHEN", "BOTH", "WITH"):
        # Substring check would be too loose (e.g. THE appears inside
        # other tokens). Use entry-key check on the per-doc list.
        for items in persisted.values():
            if not isinstance(items, list):
                continue
            literals = {it.get("literal") for it in items
                        if isinstance(it, dict)}
            assert filler not in literals, (
                f"stop-list token {filler!r} leaked into auto-discovery")


# 15. NEW (Wave 6): per-regex hit cap — auto-discovery must not
#     emit more than _AUTODISCOVERY_PER_REGEX_CAP distinct matches
#     per regex per doc. Wave-on-fix v1.6.10 raised cap from 100 to
#     10000 to align with extraction_coverage_denominator_audit (no
#     cap), so this test now confirms the cap is at least 150 (i.e.
#     all 150 synthesised hex constants land).
def test_autodiscovery_per_regex_cap_high_enough(tmp_path):
    # Synthesise 150 distinct hex constants. With the raised cap they
    # should all be persisted.
    hex_tokens = [f"0x{i:04X}" for i in range(150)]
    _put_extracted(tmp_path, "wide.txt", " ".join(hex_tokens))
    _put_l(tmp_path, "L1.json", {"any": "x"})
    r = _run(tmp_path, "--threshold", "0.0")
    assert r.returncode == 0
    auto_file = tmp_path / "phase1" / "extraction_patterns.auto.json"
    assert auto_file.is_file()
    persisted = json.loads(auto_file.read_text())
    items = persisted.get("wide.txt", [])
    hex_hits = [it for it in items
                if isinstance(it, dict)
                and it.get("literal", "").startswith("0x")]
    assert len(hex_hits) >= 150, (
        f"raised cap should fit all 150 hex constants, got {len(hex_hits)}")


# ─────────────────────────────────────────────────────────────────────
# BACKLOG-v13 Wave 8 (v0.119.40) — numeric_unit must not span newlines.
# Motivation: 1st_benchmark_benchmark_a/phase1_v0119.39-vendor/RESULT.md
# documented 26/988 = 2.6% unmatchable patterns because the regex used
# `\s+` between number and unit, capturing cell-broken PDF rows like
# `'3.5\nV'`. Fix: same-line `[ \t\r]*` gap + post-filter drops \n/\r/\t.
# ─────────────────────────────────────────────────────────────────────

# 16. Cross-line cell-broken text must not produce a `3.5\nV` literal.
def test_numeric_unit_cross_line_not_captured(tmp_path):
    # MARKER_TOKEN forces at least one valid pattern so the .auto.json
    # file is persisted (the gate skips persistence if zero patterns).
    _put_extracted(
        tmp_path, "broken.txt",
        "Vmax\n3.5\nV\nC_load\n600\npF\nR_term\n10\nΩ\nMARKER_TOKEN\n")
    _put_l(tmp_path, "L1.json", {"x": "anything"})
    r = _run(tmp_path, "--threshold", "0.0")
    assert r.returncode == 0, r.stdout + r.stderr
    auto_path = tmp_path / "phase1" / "extraction_patterns.auto.json"
    assert auto_path.is_file()
    auto = json.loads(auto_path.read_text())
    items = auto.get("broken.txt", [])
    literals = [it["literal"] for it in items if isinstance(it, dict)]
    for lit in literals:
        assert "\n" not in lit, f"newline in literal: {lit!r}"
        assert "\r" not in lit, f"CR in literal: {lit!r}"
        assert "\t" not in lit, f"TAB in literal: {lit!r}"


# 17. Same-line `3.5 V` must capture cleanly.
def test_numeric_unit_same_line_captured(tmp_path):
    _put_extracted(
        tmp_path, "good.txt",
        "Datasheet table: 3.5 V supply, 600 pF cap, 25 MHz clock.")
    _put_l(tmp_path, "L1.json",
           {"vals": "3.5 V; 600 pF; 25 MHz"})
    r = _run(tmp_path, "--threshold", "0.0")
    assert r.returncode == 0, r.stdout + r.stderr
    auto = json.loads(
        (tmp_path / "phase1" / "extraction_patterns.auto.json").read_text())
    items = auto.get("good.txt", [])
    literals = [it["literal"] for it in items if isinstance(it, dict)]
    stripped = [lit.replace(" ", "") for lit in literals]
    assert "3.5V" in stripped, (
        f"3.5 V should be captured; literals = {literals}")
    assert "600pF" in stripped, (
        f"600 pF should be captured; literals = {literals}")
    assert "25MHz" in stripped, (
        f"25 MHz should be captured; literals = {literals}")


# 18. Same-line tab-separated literal is dropped by post-filter.
def test_numeric_unit_tab_separated_filtered(tmp_path):
    _put_extracted(
        tmp_path, "tabby.txt",
        "Bandgap output is\t3.5\tV at 25C with\t600\tpF cap.")
    _put_l(tmp_path, "L1.json", {"x": "anything"})
    r = _run(tmp_path, "--threshold", "0.0")
    assert r.returncode == 0, r.stdout + r.stderr
    auto_path = tmp_path / "phase1" / "extraction_patterns.auto.json"
    if auto_path.is_file():
        auto = json.loads(auto_path.read_text())
        for items in auto.values():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict):
                    lit = it.get("literal", "")
                    assert "\t" not in lit, (
                        f"tab-bearing literal leaked: {lit!r}")
