"""Adversarial-review remediation for the v1.0.80 batch — TWO reproduced
MEDIUM over-harvest findings in phase1_doc_one_shot_runner.

FINDING (1) #670 reference-link LABEL-DEFINITION pass OVER-HARVESTS bibliography
links. `_v1_0_44_harvest_dv_checklist_table`'s label pass (`_V1_0_44_DV_LABEL_DEF`,
gated ONLY on a `*checklist*` filename) credited ANY `[UPPER_SNAKE]: <target>`
line as a DV item. A `*checklist*` doc that ALSO carries a `## See Also`
bibliography of external reference links (`[OPENTITAN_REPO]: https://…` /
`[GITHUB_CI]: …` / `[JIRA_BOARD]: …`) had those external links fabricated into
the verification scenarios. REPRO (captured BEFORE the fix):
    HARVESTED = ['github_ci', 'jira_board', 'opentitan_repo',
                 'sim_smoke_test_passing']   # 3 external links are NOT items.

REMEDIATION: the label pass now credits a `[TOKEN]: <target>` label ONLY when
(a) the token is corroborated by a pipe-table item reference `[TOKEN][]` in the
SAME doc, OR (b) its target is a same-document / relative fragment (NOT an
external repo/CI/issue/www URL). The V-stage milestone tokens (relative
`../README.md#anchor` targets that ALSO appear as `[TOKEN][]` table rows) STILL
land; the bibliography external links do NOT.

FINDING (2) #736 Name-column bit-field walker FALSE-FIRES on a pinout/signal
table. `_v1_0_80_parse_namecol_bitfield_table` needed only {Bit|Bits}+
{Name|Field}+len(hdr)>=3, so a `| Bit | Dir | Name | Description |` pinout table
under `## INTERFACE` was harvested as a spurious register AND flipped
`no_registers_in_input` to False. REPRO (captured BEFORE the fix):
    1 register INTERFACE, fields clk_i/rst_ni, no_registers_in_input=False.

REMEDIATION: (a) SKIP a table whose header carries a port-DIRECTION column
(Dir|Direction|I/O|IO|InOut). (b) require register evidence (address/offset OR a
wavejson reg block OR a match to an already-detected register) before CREATING a
new register record — a bare Name-column table never flips
`no_registers_in_input`. The #736 motivating register table (with Offset
addresses + a wavejson reg block) STILL harvests its fields; the existing
`| Bit | R/W | Description |` form is untouched.

chip-AGNOSTIC: pure URI-scheme / port-direction / column-header token shapes; NO
chip / vendor / SKU literal (names appear ONLY in fixture prose).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402

# Reuse the binding round-12 fixture (V-stage tokens must STILL land).
from test_v1_0_80_issue670_vstage_checklist_harvest import (  # noqa: E402
    DESIGN_THEN_VERIF_CHECKLIST,
)

_GEN_DIR = Path("phase1") / "generated_docs"


def _names(rows):
    return {r["name"] for r in rows}


# ════════════════════════════════════════════════════════════════════════════
# FINDING (1) #670 — bibliography external links must NOT be harvested
# ════════════════════════════════════════════════════════════════════════════

# The reviewer's EXACT failing input: a checklist doc with one V1 table row
# (a real verification item) PLUS a `## See Also` section of external
# reference-link definitions (repo / CI / issue-tracker URLs).
CHECKLIST_WITH_BIBLIOGRAPHY = """## Verification Checklist

### V1

 Type         | Item                          | Resolution  | Note
--------------|-------------------------------|-------------|------
Tests         | [SIM_SMOKE_TEST_PASSING][]    | Done        |

[SIM_SMOKE_TEST_PASSING]: ../README.md#sim_smoke_test_passing

## See Also

[OPENTITAN_REPO]: https://github.com/lowrisc/opentitan
[GITHUB_CI]: https://github.com/some/ci/actions
[JIRA_BOARD]: https://jira.example.com/board/ABC
"""


def test_bibliography_external_links_not_harvested_REMEDIATION():
    """The reviewer's repro: the 3 external `## See Also` reference links must
    NOT become fabricated verification items (pre-fix: all 3 over-harvested)."""
    rows = R._v1_0_44_harvest_dv_checklist_table(
        {"aes_checklist.md": CHECKLIST_WITH_BIBLIOGRAPHY})
    names = _names(rows)
    for ext in ("opentitan_repo", "github_ci", "jira_board"):
        assert ext not in names, (
            f"bibliography external link {ext} STILL over-harvested as a DV item")
    # The genuine V-stage table item is still credited.
    assert "sim_smoke_test_passing" in names


def test_external_target_schemes_all_excluded_REMEDIATION():
    """Every common external target scheme (http/https/git/ssh/mailto/www/
    bare-host) is excluded when the token is NOT a table-item ref."""
    doc = {"x_checklist.md": (
        "[A_HTTPS]: https://example.com/x\n"
        "[B_HTTP]: http://example.org/y\n"
        "[C_GIT]: git@github.com:o/r.git\n"
        "[D_SSH]: ssh://host/path\n"
        "[E_MAIL]: mailto:dev@example.com\n"
        "[F_WWW]: www.example.net/z\n"
        "[G_HOST]: example.io/page\n")}
    assert R._v1_0_44_harvest_dv_checklist_table(doc) == [], (
        "an external-target reference link leaked through the label pass")


def test_table_item_ref_corroborates_even_if_target_ambiguous():
    """A token that appears as a `[TOKEN][]` pipe-table item reference is a
    genuine checklist item and is credited even if its label target is unusual
    — corroboration overrides the external-target skip."""
    doc = {"y_checklist.md": (
        "| Item | Resolution |\n|------|------------|\n"
        "| [REAL_ITEM][] | Done |\n\n"
        "[REAL_ITEM]: https://example.com/anchor\n")}
    names = _names(R._v1_0_44_harvest_dv_checklist_table(doc))
    assert "real_item" in names, (
        "table-corroborated token wrongly dropped by the external-target skip")


# ── #670 motivating case still passes (the binding round-12 repro) ───────────

def test_670_motivating_vstage_tokens_still_land_GUARD():
    """GUARD: the original #670 fix's motivating case — the 4 cited V-stage
    milestone tokens (relative `../README.md#anchor` targets that ALSO appear as
    `[TOKEN][]` table rows) must STILL land after tightening the label pass."""
    rows = R._v1_0_44_harvest_dv_checklist_table(
        {"aes_checklist.md": DESIGN_THEN_VERIF_CHECKLIST})
    names = _names(rows)
    for tok in ("fpv_main_assertions_proven", "sim_nightly_regression_setup",
                "dv_doc_testplan_reviewed", "v2_checklist_scoped"):
        assert tok in names, f"V-stage token {tok} REGRESSED by the remediation"
    # D-stage + full-stage harvest invariant from the original fix holds.
    for tok in ("spec_complete", "csr_defined", "lint_setup"):
        assert tok in names, f"D-stage token {tok} regressed"
    assert len(rows) >= 33, (
        f"premature-cap regression: only {len(rows)} rows (V-stage lost)")


def test_670_relative_anchor_label_only_still_lands_GUARD():
    """GUARD: a `*checklist*` doc whose tokens carry relative fragment targets
    (no external URL) still harvests via the label pass even without a table."""
    doc = {"my_checklist.md": (
        "[FPV_MAIN_ASSERTIONS_PROVEN]: ../README.md#fpv\n"
        "[SIM_NIGHTLY_REGRESSION_SETUP]: ../README.md#sim\n")}
    names = _names(R._v1_0_44_harvest_dv_checklist_table(doc))
    assert "fpv_main_assertions_proven" in names
    assert "sim_nightly_regression_setup" in names


# ════════════════════════════════════════════════════════════════════════════
# FINDING (2) #736 — pinout/signal table must NOT be harvested as a register
# ════════════════════════════════════════════════════════════════════════════

# The reviewer's EXACT failing input.
PINOUT_DOC = ("## INTERFACE\n\n"
              "| Bit | Dir | Name | Description |\n"
              "|---|---|---|---|\n"
              "| 0 | in | clk_i | Clock |\n"
              "| 1 | in | rst_ni | Reset |\n")


def test_pinout_table_not_harvested_as_register_REMEDIATION(tmp_path: Path):
    """The reviewer's repro: a `| Bit | Dir | Name | Description |` pinout table
    under `## INTERFACE` must NOT become a spurious register and must NOT flip
    no_registers_in_input (pre-fix: 1 register INTERFACE / flag=False)."""
    (tmp_path / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    R.gen_l4_regmap(tmp_path, {"pinout.md": PINOUT_DOC})
    l4 = json.loads((tmp_path / _GEN_DIR / "L4_REGMAP.json").read_text())
    regs = l4.get("registers") or []
    assert all(r.get("name") != "INTERFACE" for r in regs), (
        f"pinout table STILL harvested as a register: {regs}")
    assert l4.get("no_registers_in_input") is True, (
        "honest 'no registers' signal STILL masked (flag flipped to False)")


def test_direction_column_table_skipped_at_parser_REMEDIATION():
    """The parser skips ANY table carrying a port-direction column shape; a
    register field table (no Dir column) is untouched."""
    for dircol in ("Dir", "Direction", "I/O", "IO", "InOut", "input/output"):
        sig = (f"| Bit | {dircol} | Name | Description |\n"
               "|---|---|---|---|\n| 0 | in | clk_i | Clock |\n")
        assert R._v1_0_80_parse_namecol_bitfield_table(sig) == [], (
            f"{dircol}-column signal table NOT skipped")


def test_mode_access_type_table_still_a_register_NOLEAK():
    """`Mode` is a legitimate register access-type header (NOT a direction) — a
    `| Bits | Mode | Name | Description |` register table STILL parses."""
    mode_tbl = ("| Bits | Mode | Name | Description |\n"
                "|---|---|---|---|\n| 0 | rw | enable | Enable. |\n")
    fields = R._v1_0_80_parse_namecol_bitfield_table(mode_tbl)
    assert fields and fields[0]["field_name"] == "enable", (
        "Mode access-type register table wrongly skipped as a signal table")


def test_bare_namecol_table_no_address_does_not_create_register(tmp_path: Path):
    """Belt-and-braces evidence gate: a bare Name-column field table with NO
    address and NO Dir column (so the parser DOES emit fields) still must not
    fabricate a fresh register nor flip the flag when no register evidence
    (address/offset/wavejson) exists and no detected register matches."""
    bare = ("## SOME_SIGNALS\n\n"
            "| Bits | Type | Name | Description |\n"
            "|---|---|---|---|\n| 0 | x | foo_sig | A signal. |\n")
    (tmp_path / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    R.gen_l4_regmap(tmp_path, {"signals.md": bare})
    l4 = json.loads((tmp_path / _GEN_DIR / "L4_REGMAP.json").read_text())
    regs = l4.get("registers") or []
    assert all(r.get("name") != "SOME_SIGNALS" for r in regs), (
        f"bare no-address Name-column table fabricated a register: {regs}")
    assert l4.get("no_registers_in_input") is True, (
        "no-address Name-column table STILL flipped no_registers_in_input")


# ── #736 motivating case still passes ────────────────────────────────────────

NAMECOL_REG_DOC = """## ALERT_TEST
Alert Test Register
- Offset: `0x0`
- Reset default: `0x0`

### Fields

|  Bits  |  Type  |  Reset  | Name                  | Description                   |
|:------:|:------:|:-------:|:----------------------|:------------------------------|
|  31:2  |        |         |                       | Reserved                      |
|   1    |   wo   |   0x0   | fatal_fault           | Write 1 to trigger an alert.  |
|   0    |   wo   |   0x0   | recov_ctrl_update_err | Write 1 to trigger an alert.  |

## CTRL
Control Register
- Offset: `0x10`
- Reset default: `0x1`

### Fields

|  Bits  |  Type  |  Reset  | Name   | Description    |
|:------:|:------:|:-------:|:-------|:---------------|
|  31:1  |        |         |        | Reserved       |
|   0    |   rw   |   0x1   | enable | Enable the IP. |

## TRIGGER
- Offset: `0x20`

### Fields

```wavejson
{"reg": [{"name": "start", "bits": 1, "attr": ["rw"]}, {"bits": 7}, {"name": "stop", "bits": 1, "attr": ["rw"]}]}
```
"""


def test_736_motivating_register_table_still_harvests_GUARD(tmp_path: Path):
    """GUARD: the original #736 fix's motivating case — real register field
    tables (with Offset addresses) + a wavejson reg block must STILL harvest
    their registers and bit-field detail, and clear the false flag."""
    (tmp_path / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    R.gen_l4_regmap(tmp_path, {"aes_registers.md": NAMECOL_REG_DOC})
    l4 = json.loads((tmp_path / _GEN_DIR / "L4_REGMAP.json").read_text())
    regs = l4.get("registers") or []
    by_name = {r.get("name"): r for r in regs}
    assert {"ALERT_TEST", "CTRL", "TRIGGER"} <= set(by_name), (
        f"motivating registers REGRESSED: {sorted(by_name)}")
    total_fields = sum(len(r.get("fields") or []) for r in regs)
    assert total_fields >= 5, f"bit-field detail lost: {total_fields} fields"
    assert l4.get("no_registers_in_input") is False, (
        "real registers present but flag not cleared")
    at = by_name["ALERT_TEST"]
    assert any(f.get("field_name") == "fatal_fault"
               and f.get("access") == "WO"
               for f in (at.get("fields") or []))


def test_736_existing_desc_form_untouched_NOLEAK():
    """The existing `| Bit | R/W | Description |` form is still NOT claimed by
    the Name-column walker (owned by the legacy grid parser)."""
    desc_form = (
        "| Bit # | R/W | Description |\n"
        "|-------|-----|-------------|\n"
        "| 7:0   | RW  | **MODE**: select mode |\n"
        "| 15:8  | RO  | **STAT**: status |\n")
    assert R._v1_0_80_parse_namecol_bitfield_table(desc_form) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
