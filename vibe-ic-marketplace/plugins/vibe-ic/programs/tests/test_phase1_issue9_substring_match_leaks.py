"""tests/test_phase1_issue9_substring_match_leaks.py — v1.6.68

Closes GitHub issue #9 — cross-project leakage hypothesised as
extraction_pattern cache pollution, root-caused as TWO substring-
match defects:

  * `_infer_vendor`: `if v in concat` — 3-letter `"ams"` matched
    inside English words like `streams` / `params` / `frameworks`,
    so AES / ChaCha / SHA-256 thin-input projects falsely got
    `vendor: "ams"` from substring hits in their own READMEs.

  * `aliases_index` emit + `_alias_present_in_docs`: same plain
    substring `in` check made 2-3-char aliases like `D-` / `Dn` /
    `Dp` / `EXAMPLE_PROTOCOL` match inside `D-flip-flop` / `D-cache` / `paid` /
    `said` / `afraid`. Result: EXAMPLE_PROTOCOL-class single-wire-protocol
    vocabulary surfaced in totally unrelated thin-input projects'
    `aliases_index`.

The v1.6.68 fixes apply word-boundary regex match + minimum-length
floor + provenance per entry, all per the durable rule
`feedback_general_fixes_no_false_alert.md` (general fix, no false
alert).
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import (
    _infer_vendor,
    _apply_alias_normalization,
    gen_l1_datasheet,
)
import pytest

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path: Path) -> Path:
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


# ---------------------------------------------------------------------------
# _infer_vendor — substring leak fix
# ---------------------------------------------------------------------------

def test_infer_vendor_does_not_leak_ams_into_stream_cipher() -> None:
    """ChaCha is a STREAM cipher. Its README contains the word
    `stream`, which contains the substring `ams`. v1.6.66 returned
    vendor=`ams`. v1.6.68 word-boundary match returns
    `see datasheet`."""
    extracted = {
        "README.md": (
            "Verilog 2001 implementation of the ChaCha stream cipher.\n"
        ),
    }
    assert _infer_vendor(extracted) == "see datasheet"


def test_infer_vendor_does_not_leak_ams_via_params_or_frameworks() -> None:
    cases = [
        "Programmable parameter set defines round count.\n",
        "Verification framework runs cocotb tests.\n",
        "Top-level params: KEY_W=128, ROUNDS=10.\n",
        "Multiple data streams supported in parallel.\n",
    ]
    for src in cases:
        v = _infer_vendor({"spec.txt": src})
        assert v == "see datasheet", \
            f"false-positive ams leak on {src!r} → {v!r}"


def test_infer_vendor_real_ams_ag_mention_populates() -> None:
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP single-wire authentication IC, ams AG.\n"
            "Manufactured by ams AG, Austria.\n"
        ),
    }
    assert _infer_vendor(extracted) == "ams"


def test_infer_vendor_does_not_leak_apple_substring() -> None:
    """`apple` substring in `pineapple` / `applet` / `application`."""
    cases = [
        "Java applet for OTP burn console.\n",
        "Application note 42 covers the wake sequence.\n",
        "Pineapple-shaped clock icon in the GUI.\n",
    ]
    for src in cases:
        v = _infer_vendor({"spec.txt": src})
        assert v != "apple", f"false-positive apple leak on {src!r}"


def test_infer_vendor_does_not_leak_microchip_via_fpga_platform_heading(
        ) -> None:
    """v1.6.69 — closes issue #9 v1.6.68 follow-up. AES / ChaCha /
    SHA-256 thin-input project READMEs use `### Microchip IGLOO 2 ###`
    headings to describe the FPGA platform vendor for test boards,
    NOT the IP manufacturer. v1.6.68 plain `\\bmicrochip\\b` regex
    falsely returned `Microchip` for all three. v1.6.69 platform-
    vendor negative-context filter rejects."""
    cases = [
        ("aes",
         "Verilog AES core.\n\n### Microchip IGLOO 2 ###\n"
         "Used as FPGA test target.\n"),
        ("chacha",
         "ChaCha stream cipher.\n\n### Microchip IGLOO2 ###\n"
         "### Microchip PolarFire ###\n"
         "Both FPGA platforms tested.\n"),
        ("sha256",
         "SHA-256 hash.\n\n### Microchip ###\n"
         "FPGA evaluation board details follow.\n"),
    ]
    for label, src in cases:
        v = _infer_vendor({"README.md": src})
        assert v == "see datasheet", \
            f"{label}: false-positive Microchip leak → {v!r}"


def test_infer_vendor_does_not_leak_xilinx_via_fpga_platform_heading(
        ) -> None:
    """Same regression class for Xilinx / Altera / Intel platform
    mentions — the platform-vendor filter is general."""
    cases = [
        "AES core.\n### Xilinx Virtex-7 ###\nFPGA target.\n",
        "DRAM controller.\n### Intel Cyclone V ###\nEval board.\n",
        "SerDes.\n### Altera Stratix IV ###\nReference design.\n",
        "Hash core.\n### Lattice ECP5 ###\nFPGA kit.\n",
    ]
    for src in cases:
        v = _infer_vendor({"spec.txt": src})
        # The vendors above aren't in the canonical match list anyway;
        # what matters is that NONE leaks through as the IP vendor.
        assert v == "see datasheet", \
            f"platform-vendor leak on {src!r} → {v!r}"


def test_infer_vendor_real_microchip_with_manufacturer_context() -> None:
    """When `Microchip Technology` (manufacturer suffix) or
    `manufactured by Microchip` appears, AND no FPGA platform
    context is nearby, the vendor IS Microchip — accept it."""
    extracted = {
        "datasheet.txt": (
            "ATSAMD21 microcontroller, Microchip Technology Inc.\n"
            "Manufactured by Microchip in Arizona.\n"
            "© 2024 Microchip.\n"
        ),
    }
    assert _infer_vendor(extracted) == "Microchip"


def test_infer_vendor_open_source_github_url_returns_see_datasheet() -> None:
    """v1.6.69 — verifier suggestion 3. README with github.com URL
    and no copyright-with-vendor → open-source IP → vendor=
    `see datasheet` regardless of any vendor-name tokens elsewhere."""
    extracted = {
        "README.md": (
            "# Open-source AES core\n\n"
            "https://github.com/secworks/aes\n"
            "Manufactured by Microchip Technology was the test "
            "platform.\n"  # platform-context will reject anyway
        ),
    }
    # Open-source bypass should fire FIRST.
    assert _infer_vendor(extracted) == "see datasheet"


def test_infer_vendor_aggregate_no_leakage_across_ic_classes() -> None:
    """Issue-#9 fingerprint reproduction: AES / ChaCha / SHA-256 /
    DRAM all return `see datasheet`, NOT `ams`."""
    cases = [
        "Verilog implementation of AES symmetric block cipher.\n",
        "Verilog 2001 implementation of the ChaCha stream cipher.\n",
        "SHA-256 cryptographic hash, FIPS 180.\n",
        "Small footprint configurable DRAM core, supports streams.\n",
    ]
    for src in cases:
        v = _infer_vendor({"README.md": src})
        assert v == "see datasheet", \
            f"vendor leak on {src!r} → {v!r}"


# ---------------------------------------------------------------------------
# aliases_index — substring leak fix
# ---------------------------------------------------------------------------

def _seed_l1_for_aliases(tmp_path: Path, body: dict) -> Path:
    project = _seed(tmp_path)
    (project / _GEN_DIR / "L1_DATASHEET.json").write_text(
        json.dumps(body)
    )
    return project


def test_aliases_index_does_not_leak_dminus_via_d_flip_flop(
        tmp_path: Path) -> None:
    """`D-` substring matches inside `D-flip-flop` / `D-cache` /
    `D-FF`. v1.6.66 emitted `{canonical: DMINUS, aliases: [Dn, D-]}`
    on AES / ChaCha projects whose READMEs mention D-flip-flops.
    v1.6.68 word-boundary match + short-alias-strict-rule rejects."""
    project = _seed_l1_for_aliases(tmp_path, {
        "schema_version": 2,
        "ic_name": "AES",
    })
    extracted = {
        "README.md": (
            "Verilog AES core. Internal D-flip-flops for state.\n"
            "Pipelined D-cache stages.\n"
        ),
    }
    _apply_alias_normalization(project, extracted)
    l1 = json.loads(
        (project / _GEN_DIR / "L1_DATASHEET.json").read_text()
    )
    canons = {a["canonical"]
              for a in l1.get("aliases_index", [])}
    assert "DMINUS" not in canons
    assert "DPLUS" not in canons


def test_aliases_index_does_not_leak_aid_via_paid_said_afraid(
        tmp_path: Path) -> None:
    """`EXAMPLE_PROTOCOL` substring matches inside `paid` / `said` / `afraid`.
    v1.6.66 emitted `{canonical: EXAMPLE_PROTOCOL, aliases: [...]}` on networking
    IP project whose README mentions packets being `said` / `paid`.
    v1.6.68 word-boundary match rejects."""
    project = _seed_l1_for_aliases(tmp_path, {
        "schema_version": 2,
        "ic_name": "Taxi Transport Library",
    })
    extracted = {
        "README.md": (
            "Networking IP. Packets are said to be paid in tokens.\n"
            "Don't be afraid of the AXI handshake complexity.\n"
        ),
    }
    _apply_alias_normalization(project, extracted)
    l1 = json.loads(
        (project / _GEN_DIR / "L1_DATASHEET.json").read_text()
    )
    canons = {a["canonical"]
              for a in l1.get("aliases_index", [])}
    assert "EXAMPLE_PROTOCOL" not in canons


def test_aliases_index_real_aid_class_extracted_with_provenance(
        tmp_path: Path) -> None:
    """When the AID alias really IS in source (canonical AND alias
    both present on word boundaries), v1.6.68 short-alias-strict
    rule still permits the entry — and it now carries a
    `source_doc` provenance pointer.

    AID is a class-gated alias (v1.6.359 half-duplex gate), so the
    project's L2 must declare the half-duplex single-wire class
    before the entry may surface — exactly the real AID scenario."""
    project = _seed_l1_for_aliases(tmp_path, {
        "schema_version": 2,
        "ic_name": "EXAMPLE_CHIP",
    })
    # AID is half-duplex-class-gated; seed L2 with the half-duplex
    # single-wire class_path so the v1.6.359 gate opens for the
    # genuine-AID scenario this test exercises.
    (project / _GEN_DIR / "L2_FRS.json").write_text(
        json.dumps({"class_path": "protocol/half_duplex_bus/aid"})
    )
    extracted = {
        "EXAMPLE_CHIP_Datasheet.txt": (
            "EXAMPLE_CHIP implements the AID protocol "
            "(Apple ID Bus / AID-class authentication).\n"
            "Apple Identification class single-wire protocol.\n"
        ),
    }
    _apply_alias_normalization(project, extracted)
    l1 = json.loads(
        (project / _GEN_DIR / "L1_DATASHEET.json").read_text()
    )
    aid_entries = [a for a in l1.get("aliases_index", [])
                   if a["canonical"] == "AID"]
    assert len(aid_entries) == 1
    aid = aid_entries[0]
    # v1.6.68 — every entry now has source_doc provenance.
    assert "source_doc" in aid
    assert "EXAMPLE_CHIP_Datasheet" in aid["source_doc"]


def test_aliases_index_short_aliases_require_both_sides(
        tmp_path: Path) -> None:
    """Short aliases (<4 chars) on both canonical and alias side
    require BOTH-side evidence to emit. A doc that mentions ONLY
    `D-` (e.g. `D-flip-flop` post-fix gets word-boundary-rejected,
    but a doc that mentions `D+` and `D-` cleanly should NOT emit
    DMINUS unless the canonical `DMINUS` is also visible somewhere
    or `Dn` / `D-` are in source on word boundaries)."""
    project = _seed_l1_for_aliases(tmp_path, {
        "schema_version": 2,
        "ic_name": "TestIP",
    })
    # Source mentions `D-` ONLY inside `D-flip-flop` (substring,
    # not word-boundary) — must NOT emit.
    extracted = {
        "README.md": (
            "TestIP uses standard D-flip-flops and D-FFs.\n"
        ),
    }
    _apply_alias_normalization(project, extracted)
    l1 = json.loads(
        (project / _GEN_DIR / "L1_DATASHEET.json").read_text()
    )
    canons = {a["canonical"]
              for a in l1.get("aliases_index", [])}
    assert "DMINUS" not in canons
    assert "DPLUS" not in canons


# ---------------------------------------------------------------------------
# Cross-IC fingerprint guard — the issue #9 primary complaint
# ---------------------------------------------------------------------------

def test_no_aid_or_vendor_leakage_across_3_thin_input_classes(
        tmp_path_factory) -> None:
    """Aggregate guard reproducing the verifier's 11-project
    fingerprint: 3 thin-input pure-digital IPs (AES, ChaCha,
    Networking) processed in any order must NOT pick up
    `vendor: ams` or `aliases_index: [{canonical: EXAMPLE_PROTOCOL, ...}]`."""
    cases = {
        "aes":     "Verilog AES core. Symmetric block cipher.\n"
                    "Internal D-flip-flops feed state register.\n",
        "chacha":  "Verilog 2001 implementation of the ChaCha "
                    "stream cipher.\nMultiple data streams.\n",
        "taxi":    "Networking IP. Packets said to be paid.\n"
                    "Don't be afraid of AXI complexity.\n",
    }
    for label, src in cases.items():
        proj = _seed(tmp_path_factory.mktemp(label))
        # Drive L1 through gen_l1_datasheet then aliases pass.
        gen_l1_datasheet(proj, {"README.md": src})
        from programs.phase1_one_shot_runner import (
            _apply_alias_normalization as _atl,
        )
        _atl(proj, {"README.md": src})
        l1 = json.loads(
            (proj / _GEN_DIR / "L1_DATASHEET.json").read_text()
        )
        # Vendor must not be `ams`.
        ord_info = l1.get("ordering_info", {})
        assert ord_info.get("vendor") != "ams", \
            f"{label}: vendor leak ({ord_info!r})"
        # aliases_index must not carry EXAMPLE_PROTOCOL-class entries.
        canons = {a["canonical"]
                  for a in l1.get("aliases_index", [])}
        forbidden = {"EXAMPLE_PROTOCOL", "DMINUS", "DPLUS",
                     "WAKE_PULSE", "WakePulse"}
        leaked = forbidden & canons
        assert not leaked, \
            f"{label}: EXAMPLE_PROTOCOL-class aliases leak {leaked}"
