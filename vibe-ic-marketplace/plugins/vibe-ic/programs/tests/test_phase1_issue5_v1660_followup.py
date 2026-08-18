"""tests/test_phase1_issue5_v1660_followup.py — v1.6.61

Direct regression tests for the v1.6.60 follow-up failures the
verifier agent posted on GitHub issue #5 (with verbatim input
fixtures lifted from the comment):

1. **chacha** — README is Setext-style ("chacha\\n========"), prose
   says "Verilog 2001 implementation of the ChaCha stream cipher".
   v1.6.60 returned UNKNOWN_IC because:
     * the strict single-token rule rejected `ChaCha` (no digits, no
       known prefix); only the looser CamelCase / BiCapital rule
       lets it through.
     * Setext H1 was not recognised.
   v1.6.61 fixes both.

2. **taxi** — H1 `# Taxi Transport Library`. v1.6.60 returned
   `XCVU095` (Xilinx Virtex UltraScale+ part number) because it
   was mentioned 3+ times in the README and Tier 1.5 chip-style
   fired before Tier 3 H1. Fix: extend `_FPGA_BOARD_RE` to cover
   Xilinx XC* families.

3. **liteiclink** — README has ASCII-art logo in fenced code
   block (no ATX H1). Setext-style "[> Intro" non-standard heading.
   Prose: "LiteICLink provides ...". v1.6.60 returned UNKNOWN_IC.
   Fix: new Tier 2.5 captures the syntactic subject of
   `<IP> provides|implements|is|wraps|...`.

4. **litescope** — Prose: "LiteScope provides ... embedded logic
   analyzer". v1.6.60 returned `Analyzer`. Fix: Tier 2.5 prefers
   the syntactic subject (`LiteScope`) over later nouns.

5. **L6 truncated state names** — v1.6.60 emitted state names
   `S_Y`, `S_HI`, `S_A`, `CLM`, `MPD` (3-char fragments). Fix:
   require ≥4 chars total in `_add_state`.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import (
    _ic_name_from_docs,
    _is_fpga_board_name,
    _is_strict_single_token_ic_name,
    gen_l6_control_logic,
)
import pytest


# ---------------------------------------------------------------------------
# 1. chacha — Setext H1 + ChaCha BiCapital identifier.
# ---------------------------------------------------------------------------

CHACHA_README = """\
[![build-openlane-sky130](https://github.com/secworks/chacha/actions/workflows/ci.yml/badge.svg?branch=master&event=push)](https://github.com/secworks/chacha/actions/workflows/ci.yml)

chacha
========

Verilog 2001 implementation of the ChaCha stream cipher.
"""


def test_chacha_real_readme_returns_chacha() -> None:
    """Verbatim chacha README from issue-#5 v1.6.60 follow-up."""
    extracted = {"README.md": CHACHA_README}
    name = _ic_name_from_docs(extracted)
    assert name == "ChaCha", f"got {name!r}"


def test_strict_single_token_accepts_bicapital() -> None:
    """v1.6.61: tokens with ≥2 internal capitals (CamelCase /
    BiCapital) are real IP identifiers."""
    assert _is_strict_single_token_ic_name("ChaCha")
    assert _is_strict_single_token_ic_name("BlowFish")
    assert _is_strict_single_token_ic_name("LiteScope")
    assert _is_strict_single_token_ic_name("LiteICLink")
    assert _is_strict_single_token_ic_name("OpenRISC")
    # Mixed-case English nouns still rejected (1 cap each):
    assert not _is_strict_single_token_ic_name("Analyzer")
    assert not _is_strict_single_token_ic_name("Module")
    assert not _is_strict_single_token_ic_name("Controller")


def test_setext_h1_recognised() -> None:
    """A Setext underline H1 (`Title\\n=====`) is now picked up
    alongside ATX `# Title`."""
    extracted = {
        "README.md": (
            "MyChipIP\n"
            "========\n\n"
            "body text.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    # MyChipIP has 3 caps → strict-single-token passes
    assert "MyChipIP" in name


# ---------------------------------------------------------------------------
# 2. taxi — XCVU095 must NOT be picked.
# ---------------------------------------------------------------------------

TAXI_README = """\
# Taxi Transport Library

A configurable transport-layer IP for Xilinx FPGAs.

Supported devices include XCVU095, XCVU125, XCKU115, XCZU9EG, and Alveo U250.
The reference build target is XCVU095. XCVU095 is the primary tested part.
"""


def test_taxi_real_readme_returns_h1_not_xcvu095() -> None:
    extracted = {"README.md": TAXI_README}
    name = _ic_name_from_docs(extracted)
    assert name != "XCVU095"
    assert "Taxi" in name


def test_xilinx_xc_part_numbers_rejected_as_ic_names() -> None:
    for part in ("XCVU095", "XCVU125", "XCKU115", "XCZU9EG",
                 "XCVH1582", "XC7Z020", "XC7A100T"):
        assert _is_fpga_board_name(part), part


def test_real_ip_names_not_falsely_rejected_as_xc_boards() -> None:
    """Don't accidentally classify real IP names starting with X."""
    for name in ("XOR", "Xtea", "XilinxIP",
                 "AES", "ChaCha20", "EXAMPLE_CHIP"):
        assert not _is_fpga_board_name(name), name


# ---------------------------------------------------------------------------
# 3. liteiclink — Tier 2.5 subject pattern.
# ---------------------------------------------------------------------------

LITEICLINK_README = """\
```
                               __   _ __      ___________   _      __
                              / /  (_) /____ /  _/ ___/ /  (_)__  / /__
                             / /__/ / __/ -_)/ // /__/ /__/ / _ \\/  '_/
                            /____/_/\\__/\\__/___/\\___/____/_/_//_/_/\\_\\

                                Copyright 2017-2024 / EnjoyDigital

                            Small footprint and configurable Inter-Chip
                             communication cores powered by Migen & LiteX
```

[![](https://github.com/enjoy-digital/liteiclink/workflows/ci/badge.svg)](https://github.com/enjoy-digital/liteiclink)

[> Intro
--------
LiteICLink provides small footprint and configurable inter chip communication
cores.
"""


def test_liteiclink_real_readme_returns_liteiclink() -> None:
    extracted = {"README.md": LITEICLINK_README}
    name = _ic_name_from_docs(extracted)
    assert name == "LiteICLink", f"got {name!r}"


def test_subject_pattern_X_provides() -> None:
    extracted = {
        "README.md": "MyIP provides a thing.\n",
    }
    # MyIP has 2 caps → strict-single-token passes
    assert _ic_name_from_docs(extracted) == "MyIP"


def test_subject_pattern_rejects_generic_pronoun_subjects() -> None:
    """`This provides ...` / `It implements ...` must not return
    `This` / `It` as IC name."""
    cases = [
        "This provides a thing.\n",
        "It implements a protocol.\n",
        "We support multiple modes.\n",
        "Module provides reset.\n",  # Module is in stopwords
    ]
    for src in cases:
        extracted = {"README.md": src}
        name = _ic_name_from_docs(extracted)
        assert name not in {"This", "It", "We", "Module"}, \
            f"{src!r} → {name!r}"


# ---------------------------------------------------------------------------
# 4. litescope — subject pattern wins over later nouns.
# ---------------------------------------------------------------------------

LITESCOPE_README = """\
[> Intro
--------
LiteScope provides a small footprint and configurable embedded logic analyzer that you
can use in your FPGA and aims to provide a free, portable and flexible
alternative to vendor's solutions!
"""


def test_litescope_real_readme_returns_litescope_not_analyzer() -> None:
    extracted = {"README.md": LITESCOPE_README}
    name = _ic_name_from_docs(extracted)
    assert name == "LiteScope", f"got {name!r}"
    assert name != "Analyzer"


# ---------------------------------------------------------------------------
# 5. L6 — state-name min length 4.
# ---------------------------------------------------------------------------

def _seed_with_l2(tmp_path: Path, half_duplex: bool = False) -> Path:
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (project / "phase1" / "generated_docs" / "L2_FRS.json").write_text(
        json.dumps({"protocol_overview": {"half_duplex": half_duplex}})
    )
    return project


def _read_l6(project: Path) -> dict:
    return json.loads(
        (project / "phase1" / "generated_docs"
         / "L6_CONTROL_LOGIC.json").read_text()
    )


def test_l6_rejects_3char_state_fragments(tmp_path: Path) -> None:
    """v1.6.60 follow-up: prose extraction returned `S_Y`, `S_HI`,
    `S_A`, `CLM`, `MPD`. v1.6.61 enforces ≥4-char minimum so the
    3-char fragments are filtered. 4-char real states (`IDLE`,
    `BUSY`) still pass."""
    project = _seed_with_l2(tmp_path)
    extracted = {
        "fsm_spec.txt": (
            "FSM behavior:\n"
            "in IDLE state the device waits.\n"
            "in BUSY state the device is active.\n"
            "in S_Y state ... (junk)\n"
            "in S_A state ... (junk)\n"
            "in CLM state ... (junk)\n"
            "in MPD state ... (junk)\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    # 4-char real states accepted:
    assert "IDLE" in state_names
    assert "BUSY" in state_names
    # 3-char fragments rejected:
    assert "S_Y" not in state_names
    assert "S_A" not in state_names
    assert "CLM" not in state_names
    assert "MPD" not in state_names


def test_l6_4char_idle_busy_done_accepted(tmp_path: Path) -> None:
    project = _seed_with_l2(tmp_path)
    extracted = {
        "doc.txt": (
            "Transitions: IDLE -> BUSY -> DONE\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    assert state_names >= {"IDLE", "BUSY", "DONE"}


# ---------------------------------------------------------------------------
# Regression guard — make sure prior wins still pass.
# ---------------------------------------------------------------------------

def test_aes_still_works_after_v1661() -> None:
    extracted = {
        "README.md": "# the AES core\n\nVerilog implementation of AES.\n",
    }
    name = _ic_name_from_docs(extracted)
    assert "AES" in name


def test_example_chip_still_works_after_v1661() -> None:
    extracted = {
        "EXAMPLE_CHIP_Datasheet.txt": (
            "EXAMPLE_CHIP EXAMPLE_PROTOCOL-class authentication IC.\n"
            "EXAMPLE_CHIP implements a CMAC over the FIPS 180 secure hash.\n"
            "EXAMPLE_CHIP specifications follow.\n"
            "Reset: EXAMPLE_CHIP enters S_IDLE on power-up.\n"
            "Power: see EXAMPLE_CHIP datasheet section 3.\n"
        ),
    }
    assert _ic_name_from_docs(extracted) == "EXAMPLE_CHIP"


def test_litedram_still_works_after_v1661() -> None:
    extracted = {
        "README.md": "# LiteDRAM\n\nA fast DRAM controller.\n",
    }
    assert _ic_name_from_docs(extracted) == "LiteDRAM"
