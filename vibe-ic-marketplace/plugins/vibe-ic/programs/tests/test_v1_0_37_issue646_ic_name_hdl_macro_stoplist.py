"""Regression for ORGANIC #646 — the phase1 L1 `ic_name` single-token validator
accepted any `tok.isupper() and len>=2`, so an HDL/PDK conditional-compile macro
in RTL/SIMULATION scope (`USE_POWER_PINS`, `SYNTHESIS`, `GL`, `MPRJ_IO_PADS`)
hijacked `ic_name` → flowed to `L9.top_module` → `reference_tb rc=3: Unknown
module type: USE_POWER_PINS`.

Fix (chip-AGNOSTIC):
  1. An HDL/PDK conditional-compile-macro stoplist (`_is_hdl_pdk_macro_token`):
     a fixed deny-set + the unambiguous `USE_*` / `MPRJ_*` macro prefixes —
     rejected BEFORE the all-caps acceptance. Real all-caps chip acronyms
     (AES / JTAG / SHA / MD5) are neither in the set nor USE_/MPRJ_-prefixed.
  2. An explicit-declaration tier (`**Project name:**` / `**Top deliverable:**`)
     placed AFTER folder-name corroboration (no regression on existing picks)
     and BEFORE the token heuristics, so the declared name beats a macro.

ACCEPTANCE (issue): an L1 doc with `**Project name:** foo_chip` + an RTL
`` `ifdef USE_POWER_PINS `` in scope → `ic_name == "foo_chip"`, never
`USE_POWER_PINS`.

NEGATIVE no-leak: real all-caps acronym chip names still validate; a folder-
corroborated name still wins (regression guard for the existing caravel pick).

chip-AGNOSTIC: deny-set + macro-prefix shapes + a generic bold-label grammar;
no chip/vendor/SKU literal.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


# ── (1) the macro stoplist ───────────────────────────────────────────────────

@pytest.mark.parametrize("tok,is_macro", [
    ("USE_POWER_PINS", True), ("SYNTHESIS", True), ("GL", True),
    ("USE_PG_PINS", True),
    ("FORMAL", True), ("SIMULATION", True),
    ("AES", False), ("JTAG", False), ("SHA", False), ("MD5", False),
    ("SPI", False), ("USB", False), ("RISCV", False),
    # ORGANIC #719 — the Caravel-family `MPRJ_*` LITERAL was removed from
    # program logic; without structural context an `MPRJ_*` token is now a
    # normal token (screened structurally instead — see the test below).
    ("MPRJ_IO_PADS", False), ("MPRJ_IO", False),
])
def test_is_hdl_pdk_macro_token(tok, is_macro):
    assert R._is_hdl_pdk_macro_token(tok) is is_macro


# ── ORGANIC #719 — STRUCTURAL guard-macro screen (chip-family-agnostic) ──────
@pytest.mark.parametrize("tok", ["MPRJ_IO_PADS", "FOO_BAR_GUARD", "CFG_DBG"])
def test_structural_guard_macro_screened_any_prefix(tok):
    """A token used as an `ifdef/`ifndef/`define guard in the design is a macro
    REGARDLESS of prefix — this generalises the old Caravel `MPRJ_` literal."""
    guards = R._harvest_guard_macros([f"`ifdef {tok}\n  wire x;\n`endif\n"])
    assert tok in guards
    assert R._is_hdl_pdk_macro_token(tok, guards) is True
    # §4.05: a real acronym NOT used as a guard stays a valid ic_name token
    assert R._is_hdl_pdk_macro_token("AES", guards) is False


@pytest.mark.parametrize("tok,ok", [
    ("USE_POWER_PINS", False), ("SYNTHESIS", False), ("GL", False),
    ("AES", True), ("JTAG", True), ("SHA", True), ("MD5", True),
    ("ChaCha20", True), ("LiteDRAM", True)])
def test_strict_single_token_rejects_macros_keeps_acronyms(tok, ok):
    assert R._is_strict_single_token_ic_name(tok) is ok


def test_strict_single_token_structural_guard_rejected_NOLEAK():
    """ORGANIC #719 — a guard macro (ANY prefix, incl. non-MPRJ) is rejected as
    an ic_name when its guard context is supplied; a real acronym is kept."""
    guards = {"MPRJ_IO_PADS", "FOO_GUARD"}
    assert R._is_strict_single_token_ic_name("MPRJ_IO_PADS", guards) is False
    assert R._is_strict_single_token_ic_name("FOO_GUARD", guards) is False
    assert R._is_strict_single_token_ic_name("AES", guards) is True


# ── (2) the acceptance: explicit declaration beats an in-scope macro ──────────

def test_project_name_declaration_wins_over_macro():
    doc = {
        "L1.md": "# Spec\n\n- **Project name:** foo_chip\n"
                 "- **Top deliverable:** `foo_wrapper`\n",
        "rtl.v": "module foo_wrapper(...);\n`ifdef USE_POWER_PINS\n"
                 " inout vccd1;\n`endif\nendmodule\n",
    }
    name = R._ic_name_from_docs_impl(doc)
    assert name == "foo_chip", name
    assert name != "USE_POWER_PINS"


def test_colon_outside_bold_form():
    doc = {"L1.md": "- **Chip name**: my_soc_top\n"}
    assert R._ic_name_from_docs_impl(doc) == "my_soc_top"


# ── (3) NEGATIVE no-leak / no-regression ─────────────────────────────────────

def test_acronym_chip_name_still_picked_NOLEAK():
    """A real all-caps acronym chip (no explicit decl, no macro) still resolves
    — the stoplist must not eat legitimate names."""
    doc = {"README.md": "# AES\n\nRTL implementation of AES (FIPS-197).\n"}
    assert R._ic_name_from_docs_impl(doc) == "AES"


def test_real_caravel_folder_pick_unchanged_NOREGRESSION():
    """With the real caravel input + project path, the folder-corroborated
    `caravel` pick still wins (Tier 0 before the new explicit-decl Tier 0.7);
    `USE_POWER_PINS` is never the answer. SKIPs off-monorepo."""
    base = require_corpus("_bench7_caravel_v1034_cleanroom/caravel/input/docs")
    if not base.is_dir():
        pytest.skip("real caravel docs not on disk")
    ext = {p.name: p.read_text(errors="ignore") for p in base.glob("L*.md")}
    # No project path → explicit-decl tier yields the declared project name,
    # never the HDL macro.
    name = R._ic_name_from_docs_impl(ext)
    assert name != "USE_POWER_PINS"
    assert "caravel" in name.lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
