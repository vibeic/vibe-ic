#!/usr/bin/env python3
"""vibe-ic#316 salvage — the two layer gates measured on PUBLISHED cells.

WHY THIS FILE EXISTS SEPARATELY FROM THE GATES' OWN UNIT TESTS
--------------------------------------------------------------
#316's own independent verification found 9 of 30 gates declaring `blocks:true`
while wired nowhere, and 2 more whose "swept N runs, zero false positives"
claim was VACUOUS — they SKIPped on all 138 real runs, so they had never
judged a real input at all. A gate justified only by the fixture its author
wrote is in that second category: its unit test proves the logic, and nothing
about production artefacts.

So every gate landed from #316 is anchored HERE, on a cell under
`benchmark-data/`, by name and by measurement. If the cell moves or is not
checked out the test skips — but while it is there, the justification is
falsifiable, and a gate that stops finding its defect will say so.

WHAT IS PINNED
--------------
  1. `l8_sta_clock_period_design_owned_check` FAILs on `opentitan_aes`, whose
     PUBLISHED `phase2/stage1/fpga/chip_top.sdc` reads
     `create_clock -name clk_main -period 20`, i.e. 1000/50 MHz —
     `sdc_gen._DEFAULT_MHZ` verbatim — while its L8 owns neither `clock_mhz`
     nor a `clock_domains[]` frequency. STA closed against a number no design
     input owns.
  2. The gate already on main for that layer, `l8_clock_period_actionability_
     check`, SKIPs that same cell. #316 claimed the landed gate's failure set
     is a strict SUBSET of this one's; this pins the direction of the subset
     so nobody re-files the pair as a duplicate without measuring.
  3. `l21_macro_supply_rail_declared_check` FAILs on `edge_llm_accel` and on
     `u_hawaii_adc`, naming the exact macro pins.
  4. REAL-DATA NEGATIVE CONTROL for L21: the same published cell, copied, with
     the rails its own macro LEF asks for declared into its own L21 — the gate
     PASSes. Defect in -> rc=1; defect out -> rc=0, on real artefacts.
  5. The `u_hawaii_adc` LEFs write a whole pin on ONE line
     (`PIN IOVDD DIRECTION INOUT ; USE POWER ; ... ; END END IOVDD`).
     `phase3_one_shot_runner._parse_macro_supply_pins` — the backend's own
     supply-connect parser, which this gate delegates to — returned `{}` for
     them, so the backend saw zero supply terminals on two staged hard macros.
     That regression is pinned too: the fix is what makes finding 3 visible.

chip-AGNOSTIC: the cells are named as published fixtures, never as detection
inputs. No gate in this repo keys on any name appearing here.
"""
from __future__ import annotations

import json
import shutil
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _published_corpus import corpus_root, skip_reason  # noqa: E402


def _ic_root() -> Path:
    """`ic/` under whichever tree holds the published corpus.

    `_IC` WAS `_PROGRAMS.parents[3] / "benchmark-data" / "ic"`, and that path
    cannot resolve on any host: `benchmark-data/` left this repository at
    `c5d7f2d00` and `git ls-tree -r HEAD -- benchmark-data` matches nothing. So
    every `_cell()` in this module skipped everywhere, forever, over a reason no
    provisioning could satisfy — while the report showed an ordinary skip. This
    module's whole subject is PUBLISHED CELLS, so that is the entire corpus half
    of the file reading as coverage while measuring nothing.

    `corpus_root()` is the repository's own answer, as `test_tool_diagnostic_id_
    gate.py:338` already uses it, and the in-repo path is kept as the fallback so
    a checkout that still carries the tree is read exactly as before.
    """
    root = corpus_root()
    if root is not None and (root / "ic").is_dir():
        return root / "ic"
    return _PROGRAMS.parents[3] / "benchmark-data" / "ic"


_IC = _ic_root()
#: Premises this repo OWNS, so a rule keeps its regression test when the
#: published tree that used to carry the premise is retired (#905).
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
#: The PUBLISHED cell the u_hawaii_adc hardmacro LEFs are read from (#905).
#: These two assertions used to read the IC-LEVEL `u_hawaii_adc/phase3/` tree,
#: which is run output attributable to no plugin version and no PDK. The cell's
#: own LEFs are a DIFFERENT run's bytes (md5 differs) but parse identically —
#: verified before the move: `ldo` -> [(IOVDD, POWER), (VSS, GROUND)] and
#: `delta_sigma` -> unconnected [(VDD, POWER), (VSS, GROUND)] on both trees. So
#: the measurement is unchanged and it now cites a published cell.
_CELL = "v1.9.86_sky130A"
#: The published-cell name contract: v<major>.<minor>.<patch>_<PDK>.
_CELL_RE = re.compile(r"^v\d+\.\d+\.\d+_")

sys.path.insert(0, str(_PROGRAMS))


def _cell(name: str) -> Path:
    p = _IC / name
    if not (p / "phase1" / "generated_docs").is_dir():
        pytest.skip(f"published cell {name} not present under {_IC}: {skip_reason()}")
    return p


def _run(gate: str, project: Path):
    proc = _pr.run(
        [sys.executable, str(_PROGRAMS / gate), str(project)],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


# --------------------------------------------------------------------------- #
# 1 + 2 — L8: a FABRICATED STA period on a published cell, and the landed
#             gate for the same layer that cannot see it.
# --------------------------------------------------------------------------- #
def test_l8_sta_gate_reports_the_fabricated_period_on_the_published_cell():
    cell = _cell("opentitan_aes")

    l8 = json.loads((cell / "phase1" / "generated_docs"
                     / "L8_RTL_CONSTANTS.json").read_text())
    fields = l8.get("fields", l8)
    assert fields.get("clock_mhz") is None, (
        "the premise moved: this cell's L8 now owns a clock_mhz, so it is no "
        "longer the fabricated-period case this test anchors")
    assert not fields.get("clock_domains"), fields.get("clock_domains")

    sdc = cell / "phase2" / "stage1" / "fpga" / "chip_top.sdc"
    if sdc.is_file():
        # The artefact half: sdc_gen's hardcoded default, written out.
        assert "-period 20" in sdc.read_text(), (
            "the published SDC no longer carries the default period")

    rc, out = _run("l8_sta_clock_period_design_owned_check.py", cell)
    assert rc == 1, f"expected FAIL on the published cell, got rc={rc}\n{out}"
    assert "L8-1" in out and "FABRICATED" in out, out


def test_the_landed_l8_gate_skips_the_cell_this_one_fails():
    """Non-duplication, measured — not argued from the two docstrings."""
    cell = _cell("opentitan_aes")
    rc_landed, out_landed = _run(
        "l8_clock_period_actionability_check.py", cell)
    rc_new, _ = _run("l8_sta_clock_period_design_owned_check.py", cell)
    # vibe-ic#1052. The property under test is unchanged — the landed L8 gate
    # must still REFUSE this cell rather than judge it — but the refusal now
    # leaves on the disclosed channel: rc 2 (`_vacuous_exit.RC_VACUOUS`), not
    # the plain 0 it used to launder it through.
    #
    # Pinned to 2 EXACTLY, not `!= 1` and not `in (0, 2)`. A "non-fail" rc is
    # the same laundering one level up: it would re-admit the bare 0 this
    # change exists to remove, and it would swallow rc 3 (PASS_WITH_WAIVERS)
    # and any future tier as if they were this one.
    #
    # Both original halves are KEPT and a third is added. The rc alone is not
    # the disclosure — `_vacuous_exit.announce_vacuous` writes the
    # `VACUOUS_PASS:` sentinel (stderr, so a `--json -` document on stdout
    # stays parseable; `_run` merges both streams). An exit code with no
    # sentinel is an undisclosed skip wearing a disclosed skip's number, so
    # asserting only the rc would let exactly that regress in green.
    assert (rc_landed == 2
            and "skipped" in out_landed.lower()
            and "VACUOUS_PASS:" in out_landed), (
        "the landed L8 gate now judges this cell, or refused it without "
        "disclosing; re-measure whether the two gates still differ before "
        f"keeping both. rc={rc_landed}\n{out_landed}")
    assert rc_new == 1, "the new gate must be the one that sees it"


# --------------------------------------------------------------------------- #
# 3 — L21: a hollow power-intent layer under a published cell's hard macros
# --------------------------------------------------------------------------- #
# 2026-08-12, vibe-ic#905: this was parametrized over TWO cells. The second was
# `u_hawaii_adc`, read at the IC LEVEL — one of the four stray entries #905
# reports, and one this branch retires. `_cell()` skips when the tree is absent,
# so leaving the case in place would have turned a PASSING assertion into a
# SILENT SKIP: measured on both sides, this file goes `8 passed` before the
# retirement to `8 passed, 1 skipped` after it, with no failure anywhere to say
# a rule stopped being exercised. A retirement that buys itself a green run by
# removing the subject is the shape this repo's gates exist to refuse.
#
# So the case is REMOVED HERE, in the diff, where a reviewer sees it — and the
# coverage it carried is kept by `test_l21_fires_on_the_hollow_premise_fixture`
# below, which owns the premise outright instead of borrowing it from published
# run output. The remaining published-cell case is untouched and still runs.
@pytest.mark.parametrize("cell_name,expect_pins", [
    ("edge_llm_accel", ("fakeram45_2048x39", "VDD", "VSS")),
])
def test_l21_gate_fires_on_the_published_cells(cell_name, expect_pins):
    cell = _cell(cell_name)
    l21 = json.loads((cell / "phase1" / "generated_docs"
                      / "L21_POWER_INTENT.json").read_text())
    assert not (l21.get("fields", l21) or {}).get("power_domains"), (
        "the premise moved: this cell's L21 now declares power_domains")

    rc, out = _run("l21_macro_supply_rail_declared_check.py", cell)
    assert rc == 1, f"expected FAIL on {cell_name}, got rc={rc}\n{out}"
    for token in expect_pins:
        assert token in out, f"{token!r} missing from the finding\n{out}"


def test_l21_fires_on_the_hollow_premise_fixture():
    """The L21-1 rule, exercised against a premise this repo OWNS (#905).

    The rule needs exactly two things: an L21 whose `power_domains[]` is empty,
    and a design-staged hard macro whose own LEF types a pin USE POWER / USE
    GROUND. Both live in the fixture, so the assertion no longer depends on run
    output that landed beside the published cells and cannot be silently
    skipped when such a tree is retired.

    This does NOT replace the published-cell case above — a fixture proves the
    rule fires, a published cell proves it fires on real evidence. Both are
    kept, which is why the count of assertions on this rule does not fall.
    """
    fixture = _FIXTURES / "l21_hollow_power_intent"
    assert fixture.is_dir(), f"fixture missing: {fixture}"

    l21 = json.loads((fixture / "phase1" / "generated_docs"
                      / "L21_POWER_INTENT.json").read_text())
    assert not (l21.get("fields", l21) or {}).get("power_domains"), (
        "the fixture's premise moved: its L21 now declares power_domains")

    rc, out = _run("l21_macro_supply_rail_declared_check.py", fixture)
    assert rc == 1, f"expected FAIL on the fixture, got rc={rc}\n{out}"
    for token in ("m_supply_probe", "VDDA", "VSSA"):
        assert token in out, f"{token!r} missing from the finding\n{out}"
    assert "L21-1" in out, out


def test_l21_does_not_fire_on_a_published_cell_with_no_hard_macro():
    """A gate that fires on a correct cell is worse than no gate."""
    cell = _cell("sha256")
    rc, out = _run("l21_macro_supply_rail_declared_check.py", cell)
    assert rc == 2, f"expected SKIP on a macro-less cell, got rc={rc}\n{out}"


# --------------------------------------------------------------------------- #
# 4 — REAL-DATA NEGATIVE CONTROL: same cell, defect removed, gate passes
# --------------------------------------------------------------------------- #
def test_l21_passes_the_same_published_cell_once_the_rails_are_declared(
        tmp_path):
    cell = _cell("edge_llm_accel")
    work = tmp_path / "edge_llm_accel"
    (work / "phase1" / "generated_docs").mkdir(parents=True)
    # Copy only what the gate reads: the macro LEF root and L21.
    src_lef = cell / "input" / "pdk_local"
    if not src_lef.is_dir():
        pytest.skip(f"published macro LEF root not present under {_IC}: {skip_reason()}")
    shutil.copytree(src_lef, work / "input" / "pdk_local")

    l21_src = cell / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"
    doc = json.loads(l21_src.read_text())

    # BEFORE: the published layer, verbatim -> the gate must still fail.
    (work / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text(
        json.dumps(doc))
    rc_before, out_before = _run(
        "l21_macro_supply_rail_declared_check.py", work)
    assert rc_before == 1, f"control setup wrong: rc={rc_before}\n{out_before}"

    # AFTER: declare exactly the rails the macro's OWN LEF asks for.
    fields = doc.setdefault("fields", {}) if "fields" in doc else doc
    fields["power_domains"] = [
        {"name": "PD_TOP", "power_net": "VDD", "ground_net": "VSS"}]
    (work / "phase1" / "generated_docs" / "L21_POWER_INTENT.json").write_text(
        json.dumps(doc))
    rc_after, out_after = _run(
        "l21_macro_supply_rail_declared_check.py", work)
    assert rc_after == 0, (
        "declaring the rails the published macro LEF asks for MUST clear the "
        f"gate — otherwise it is unfixable. rc={rc_after}\n{out_after}")
    assert "[PASS]" in out_after, out_after


# --------------------------------------------------------------------------- #
# 5 — the parser regression that made finding 3 invisible on u_hawaii_adc
# --------------------------------------------------------------------------- #
def test_backend_parser_reads_a_pin_written_entirely_on_one_line():
    """LEF statements are `;`-terminated, not newline-terminated.

    Pinned against the published artefact AND against a synthetic copy, so the
    regression is caught even where benchmark-data is not checked out."""
    from phase3_one_shot_runner import _parse_macro_supply_pins

    inline = (
        "VERSION 5.8 ;\n"
        "MACRO m_blk\n"
        "  CLASS BLOCK ;\n"
        "  PIN PWR_A DIRECTION INOUT ; USE POWER  ; PORT LAYER M2 ; "
        "RECT 0 0 2 2 ; END END PWR_A\n"
        "  PIN GND_A DIRECTION INOUT ; USE GROUND ; PORT LAYER M2 ; "
        "RECT 0 4 2 6 ; END END GND_A\n"
        "  PIN D_IN  DIRECTION INPUT ; USE SIGNAL ; PORT LAYER M2 ; "
        "RECT 0 8 2 10 ; END END D_IN\n"
        "END m_blk\n"
        "END LIBRARY\n")
    got = _parse_macro_supply_pins(inline)
    assert got == {"m_blk": [("PWR_A", "POWER"), ("GND_A", "GROUND")]}, got

    # And the multi-line form the parser already handled must be unchanged.
    block = (
        "MACRO m_blk2\n"
        "  CLASS BLOCK ;\n"
        "  PIN VPWR\n"
        "    DIRECTION INOUT ;\n"
        "    USE POWER ;\n"
        "  END VPWR\n"
        "END m_blk2\n")
    assert _parse_macro_supply_pins(block) == {"m_blk2": [("VPWR", "POWER")]}

    lef = (_IC / "u_hawaii_adc" / _CELL / "phase3" / "analog" / "hardmacro"
           / "ldo" / "ldo.lef")
    if not lef.is_file():
        pytest.skip(f"published hardmacro LEF not present under {_IC}: {skip_reason()}")
    real = _parse_macro_supply_pins(lef.read_text())
    assert real == {"ldo": [("IOVDD", "POWER"), ("VSS", "GROUND")]}, real


def test_the_backend_plan_now_reports_those_pins_instead_of_missing_them():
    """The consequence: `_macro_supply_gc_plan` must SEE the terminals.

    Before the fix it received an empty pin set for these macros, so it
    produced neither a connect entry nor a HARDMACRO_SUPPLY_UNCONNECTED
    finding — the pins were not unconnected, they were invisible."""
    from phase3_one_shot_runner import _macro_supply_gc_plan

    lef = (_IC / "u_hawaii_adc" / _CELL / "phase3" / "analog" / "hardmacro"
           / "delta_sigma" / "delta_sigma.lef")
    if not lef.is_file():
        pytest.skip(f"published hardmacro LEF not present under {_IC}: {skip_reason()}")
    text = lef.read_text()

    conn, unconn = _macro_supply_gc_plan([text], [], [])
    assert [(u["master"], u["pin"], u["use"]) for u in unconn] == [
        ("delta_sigma", "VDD", "POWER"), ("delta_sigma", "VSS", "GROUND")], (
        conn, unconn)

    conn2, unconn2 = _macro_supply_gc_plan([text], ["VDD"], ["VSS"])
    assert not unconn2 and len(conn2) == 2, (conn2, unconn2)


# --------------------------------------------------------------------------- #
# 6 — #905: the hardmacro LEFs are read from a PUBLISHED CELL, not the IC level
# --------------------------------------------------------------------------- #
def test_the_hardmacro_lefs_are_read_from_a_published_cell():
    """The two `_parse_macro_supply_pins` assertions above used to read
    `benchmark-data/ic/u_hawaii_adc/phase3/`, an IC-LEVEL tree: run output
    attributable to no plugin version and no PDK, which `IC_LEVEL_LAYOUT`
    forbids and vibe-ic#905 retires.

    Pin the DESTINATION, not just the current answer. Without this, a future
    edit walks the paths back up to the IC level and nothing says so — and the
    walk-back is invisible, because `lef.is_file()` guards both assertions with
    `pytest.skip`, so a wrong path goes GREEN-but-silent rather than red."""
    assert _CELL_RE.match(_CELL), (
        f"{_CELL!r} is not a v<major>.<minor>.<patch>_<PDK> cell name")

    for block in ("ldo", "delta_sigma"):
        lef = (_IC / "u_hawaii_adc" / _CELL / "phase3" / "analog"
               / "hardmacro" / block / f"{block}.lef")
        rel = lef.relative_to(_IC).parts
        assert rel[1] == _CELL, (
            f"{block}.lef is read from {rel[1]!r}, not the published cell")
        assert _CELL_RE.match(rel[1]), (
            f"{block}.lef is read from a non-cell IC-level entry {rel[1]!r}")
        if lef.is_file():
            # The IC-level copy this moved off must not be what is read.
            stray = _IC / "u_hawaii_adc" / "phase3" / "analog" / "hardmacro" \
                / block / f"{block}.lef"
            assert lef.resolve() != stray.resolve()
