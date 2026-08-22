#!/usr/bin/env python3
"""Tests for vendor_fpga_reference_table_extraction_check.py (LL-29).

GENERAL: chip-agnostic. Doc may be from any vendor; we just check that
H[01]/BR/IBT/WKP-shaped tables in input/docs/ propagate into L8.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "vendor_fpga_reference_table_extraction_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _put_doc(tmp_path: Path, name: str, text: str):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(text)


def _put_l8(tmp_path: Path, data: dict, name: str = "L8_RTL_CONSTANTS.json"):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(json.dumps(data))


# 1. Silent-skip baseline: no input/docs at all.
def test_no_input_docs_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "skipped" in r.stdout.lower()


# 2. Silent-skip when docs have no FPGA reference table.
def test_docs_without_fpga_table_silent_pass(tmp_path):
    _put_doc(tmp_path, "spec.txt", "Some prose. tSRS = 20us. No vendor table.")
    r = _run(tmp_path)
    assert r.returncode == 0


# 3. Positive PASS — table present in doc AND L8 has matching values.
def test_table_propagated_into_l8_passes(tmp_path):
    _put_doc(tmp_path, "20230103-3.txt",
             "H1_MIN[1]    H1_MAX[192]\n"
             "H0_MIN[196]  H0_MAX[612]\n"
             "BR_MIN[637]  BR_MAX[1314]\n"
             "IBT_MIN[234] IBT_MAX[2000]\n"
             "WKP_MIN[738]\n")
    _put_l8(tmp_path, {
        "rx_classifier_ticks": {
            "h1_min": 1, "h1_max": 192,
            "h0_min": 196, "h0_max": 612,
            "br_min": 637, "br_max": 1314,
            "ibt_min": 234, "ibt_max": 2000,
            "wkp_min": 738,
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


# 4. Negative FAIL — table in doc but L8 has none of those keys.
def test_table_not_extracted_into_l8_fails(tmp_path):
    _put_doc(tmp_path, "fpga_ref.txt",
             "H1_MIN[1]    H1_MAX[192]\n"
             "H0_MIN[196]  H0_MAX[612]\n"
             "BR_MIN[637]  BR_MAX[1314]\n")
    _put_l8(tmp_path, {"some_other_block": {"x": 1}})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "FAIL" in r.stdout


# 5. Negative FAIL — values disagree by >10%.
def test_value_mismatch_fails(tmp_path):
    _put_doc(tmp_path, "20230103-3.txt",
             "H1_MIN[1]    H1_MAX[192]\n"
             "H0_MIN[196]  H0_MAX[612]\n"
             "BR_MIN[637]  BR_MAX[1314]\n")
    _put_l8(tmp_path, {
        "rx_classifier_ticks": {
            "h1_min": 1, "h1_max": 100,    # 192→100, 48% off
            "h0_min": 196, "h0_max": 612,
            "br_min": 637, "br_max": 1314,
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "h1_max" in r.stdout


# 6. Waiver allows mismatch.
def test_waiver_allows_mismatch(tmp_path):
    _put_doc(tmp_path, "20230103-3.txt",
             "H1_MIN[1]    H1_MAX[192]\n"
             "BR_MIN[637]  BR_MAX[1314]\n")
    _put_l8(tmp_path, {
        "rx_classifier_ticks": {"h1_min": 1, "h1_max": 50,
                                 "br_min": 637, "br_max": 1314}
    })
    (tmp_path / "waivers.json").write_text(json.dumps({
        "vendor_fpga_table_alternative":
            "Vendor table superseded by 2026 calibration measurements",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


# 7. Edge case: filename hint 'FPGA' triggers the extractor on H_PAT only.
def test_filename_hint_fpga_with_only_h_pat(tmp_path):
    _put_doc(tmp_path, "vendor_FPGA_table.txt",
             "H1_MIN[1] H1_MAX[192] H0_MIN[196] H0_MAX[612]\n")
    # Without BR_PAT, body pattern alone wouldn't trigger; filename hint does.
    _put_l8(tmp_path, {
        "rx_classifier_ticks": {"h1_min": 1, "h1_max": 192,
                                 "h0_min": 196, "h0_max": 612}
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


# 8. Generic / chip-agnostic — different protocol, different KEY names.
def test_generic_protocol_table_passes(tmp_path):
    _put_doc(tmp_path, "lin_fpga_ref.txt",
             "H1_MIN[5] H1_MAX[20] BR_MIN[40] BR_MAX[100]")
    _put_l8(tmp_path, {
        "rx_classifier_ticks": {
            "h1_min": 5, "h1_max": 20,
            "br_min": 40, "br_max": 100,
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 0


# 9. (LL-29 fix BACKLOG-v13 P1.1) Dual-block file WITH FPGA heading
#    — must pick the FPGA block (NOT the ORG block).
def test_dual_block_fpga_heading_wins(tmp_path):
    """20230103-3.txt-shaped file: FPGA block first, ORG block second.
    The FPGA block has IBT_MIN[234]; ORG has IBT_MIN[274]. Heading-aware
    extractor must pick the FPGA block, so L8 with ibt_min=234 PASSes
    and ibt_min=274 FAILs.
    """
    doc = (
        "FPGA - 20230103-3\n"
        "H1_MIN[1] H1_MAX[192]\n"
        "H0_MIN[196] H0_MAX[612]\n"
        "BR_MIN[637] BR_MAX[1314]\n"
        "IBT_MIN[234] IBT_MAX[2000]\n"
        "WKP_MIN[738]\n"
        "\n"
        "============= ORG ===================\n"
        "H1_MIN[1] H1_MAX[192]\n"
        "H0_MIN[193] H0_MAX[612]\n"
        "BR_MIN[613] BR_MAX[1272]\n"
        "IBT_MIN[274] IBT_MAX[2000]\n"
        "WKP_MIN[750]\n"
    )
    _put_doc(tmp_path, "20230103-3.txt", doc)
    _put_l8(tmp_path, {
        "rx_classifier_ticks": {
            "h1_min": 1, "h1_max": 192,
            "h0_min": 196, "h0_max": 612,
            "br_min": 637, "br_max": 1314,
            "ibt_min": 234,    # FPGA value — must be accepted
            "ibt_max": 2000,
            "wkp_min": 738,
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    # Disagreement detection should also surface a WARN.
    assert "WARN" in r.stdout


def test_dual_block_org_value_fails_when_fpga_is_truth(tmp_path):
    """Same dual-block doc, but L8 has the ORG ibt_min (274). The
    LL-29 fix must FAIL because the FPGA block (which is the truth)
    says 234 and L8 says 274 (>10% relative error)."""
    doc = (
        "FPGA - 20230103-3\n"
        "H1_MIN[1] H1_MAX[192]\n"
        "H0_MIN[196] H0_MAX[612]\n"
        "BR_MIN[637] BR_MAX[1314]\n"
        "IBT_MIN[234] IBT_MAX[2000]\n"
        "WKP_MIN[738]\n"
        "\n"
        "============= ORG ===================\n"
        "IBT_MIN[274] IBT_MAX[2000]\n"
    )
    _put_doc(tmp_path, "20230103-3.txt", doc)
    _put_l8(tmp_path, {
        "rx_classifier_ticks": {
            "h1_min": 1, "h1_max": 192,
            "h0_min": 196, "h0_max": 612,
            "br_min": 637, "br_max": 1314,
            "ibt_min": 274,    # ORG value — must FAIL vs FPGA truth
            "ibt_max": 2000,
            "wkp_min": 738,
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "ibt_min" in r.stdout


# 10. (LL-29 fix) Dual-block file WITHOUT a heading — must pick FIRST.
def test_dual_block_no_heading_first_wins(tmp_path):
    """No heading anywhere; two consecutive blocks of KEY[NN] entries.
    First-block-wins is the deterministic fallback (replaces the
    last-match-wins bug)."""
    doc = (
        "H1_MIN[1] H1_MAX[100]\n"
        "BR_MIN[600] BR_MAX[1300]\n"
        "IBT_MIN[200] IBT_MAX[2000]\n"
        "WKP_MIN[700]\n"
        "\n"
        "----\n"
        "\n"
        "H1_MIN[1] H1_MAX[300]\n"
        "BR_MIN[600] BR_MAX[1300]\n"
        "IBT_MIN[400] IBT_MAX[2000]\n"
        "WKP_MIN[800]\n"
    )
    _put_doc(tmp_path, "no_heading.txt", doc)
    # L8 with the FIRST block's values must PASS.
    _put_l8(tmp_path, {
        "rx_classifier_ticks": {
            "h1_min": 1, "h1_max": 100,
            "br_min": 600, "br_max": 1300,
            "ibt_min": 200, "ibt_max": 2000,
            "wkp_min": 700,
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
