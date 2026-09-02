#!/usr/bin/env python3
"""Step 15.5ic — the same tree answered 13 of 13 to one caller and 10 of 13 to
the other, because only one of them was told where the PDK is.

THE MEASUREMENT
===============
`flow/phase1_phase2_phase3.yaml` grades step 15.5ic by running

    pad_assignment_gen . --json reports/phase3/pad_assignment.json

with NO PDK arguments. `phase3_one_shot_runner` dispatches the same program
with `--pdk-root/--pdk`, because a design document may DELEGATE the IO cell
library to the PDK. MEASURED on a tree that had completed the pad ring: the
runner's invocation resolved all 13 variables and wrote the config; the flow's
invocation REFUSED with `PAD_CONFIG_VARIABLE_ABSENT` naming exactly three —
`PAD_SITE_NAME`, `PAD_CORNER_SITE_NAME`, `PAD_EDGE_SPACING` — the three that
are properties of the IO CELL LIBRARY and of nothing else. Neither caller was
wrong about its own question, and the disagreement was reported as a defect of
the step.

It is not resolvable in the yaml: the clause is a static string and the PDK
root is a per-host, per-container path.

WHAT THE FIX IS, AND WHY IT IS NOT A SECOND GUESS
=================================================
`io_pad_chip_top_gen` ALREADY read those three values, out of the one IO
library whose LEFs it read, and published them in its own record under
`pdk_declared` with a file:line for each in `pdk_declared_sources`.
`pad_assignment_gen` already reads that record — for the four side lists, the
signal map, the rotations, `PAD_CORNER` and `PAD_FILLERS`. The three were the
only ones left behind. Reading them from the same file is a transcription of
what THIS RUN measured, not a fresh choice of which library the run used.

THE CONTROLS
============
Every direction below has one, because a reader that always finds an answer is
a defaulter and a defaulted pad ring is invented geometry:

  RESOLVES     the no-PDK-argument invocation writes the config, and the three
               values are BYTE-EQUAL to the producer's record.
  DOES NOT     a record with no `pdk_declared` leaves exactly those three owed
  DEFAULT      — no site name, no spacing is invented from anywhere.
  PARTIAL      a record declaring two of the three publishes two and still
  IS PARTIAL   owes the third.
  PROVENANCE   the written config names the producer's file AND the file:line
               the producer read, so the value can be traced to a PDK file
               without this program having opened it.
  PRECEDENCE   an operator slot still wins over the record.

Chip-, PDK- and design-agnostic: the fixture's site names, masters and ports
are invented words with no vendor prefix, and a test asserts the source
carries no PDK literal for these three.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import pad_assignment_gen as PAG

#: Invented names. No vendor prefix anywhere — if this fixture ever needs a
#: real one, the program has grown a dependency on a specific PDK.
_SITE = "FIXTURE_IO_Site"
_CORNER_SITE = "FIXTURE_COR_Site"
_SPACING = "26"
_CORNER_MASTER = "fixture_io__cor"
_FILLERS = ["fixture_io__fill10", "fixture_io__fill1"]
_CFG = "/nowhere/pdks/fixture_tree/libs.tech/librelane/fixture_io/config.tcl"

_PDK_DECLARED = {"PAD_SITE_NAME": _SITE,
                 "PAD_CORNER_SITE_NAME": _CORNER_SITE,
                 "PAD_EDGE_SPACING": _SPACING}
_PDK_SOURCES = {"PAD_SITE_NAME": f"{_CFG}:4",
                "PAD_CORNER_SITE_NAME": f"{_CFG}:5",
                "PAD_EDGE_SPACING": f"{_CFG}:57"}


def _record(pdk_declared, pdk_sources=None):
    """What `io_pad_chip_top_gen` writes, in its own shape."""
    return {
        "program": "io_pad_chip_top_gen",
        "verdict": "WROTE",
        "chip_top_verilog": "phase3/stage3/pnr/chip_top_io.v",
        "derived_answers": {
            "pad_order_by_side": {"south": ["u_pad_a"], "east": ["u_pad_b"],
                                  "north": ["u_pad_c"], "west": ["u_pad_d"]},
            "pad_signal_map": {"u_pad_a": "a", "u_pad_b": "b",
                               "u_pad_c": "c", "u_pad_d": "d"},
            "pad_rotations": {"horizontal": "R0", "vertical": "R90",
                              "corner": "R0"},
            "pad_corner_master": _CORNER_MASTER,
            "pad_fillers": list(_FILLERS),
        },
        "derivation_basis": {"pad_order_by_side": "the design's own document",
                             "pad_signal_map": "instances this producer made",
                             "pad_rotations": {"horizontal": "the library",
                                               "vertical": "the library",
                                               "corner": "the library"},
                             "pad_corner_master": "the PDK's IO config",
                             "pad_fillers": "the PDK's IO config"},
        "pdk_declared": pdk_declared,
        "pdk_declared_sources": pdk_sources if pdk_sources is not None else {},
    }


def _project(tmp_path: Path, pdk_declared, pdk_sources=None) -> Path:
    proj = tmp_path / "proj"
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / PAG.DERIVED_CHIP_TOP_REL).write_text(
        json.dumps(_record(pdk_declared, pdk_sources)))
    return proj


def _run(proj: Path) -> int:
    """The FLOW's own invocation, verbatim: no PDK argument of any kind, and
    from the project directory — a relative `--json` resolves against the CWD,
    which is where the flow's clause runs it."""
    here = os.getcwd()
    os.chdir(proj)
    try:
        return PAG.main([str(proj), "--json",
                         "reports/phase3/pad_assignment.json"])
    finally:
        os.chdir(here)


def _report(proj: Path) -> dict:
    return json.loads((proj / "reports/phase3/pad_assignment.json").read_text())


def _config(proj: Path) -> dict:
    return json.loads(
        (proj / "phase3/stage3/pnr/pad_assignment.json").read_text())


def test_the_flow_declared_invocation_now_resolves_all_thirteen(tmp_path):
    proj = _project(tmp_path, dict(_PDK_DECLARED), dict(_PDK_SOURCES))
    assert _run(proj) == 0
    cfg = _config(proj)
    for var in PAG.PR.REQUIRED_VARS:
        assert var in cfg, f"{var} unresolved by the flow's own invocation"
    assert cfg["PAD_SITE_NAME"] == _SITE
    assert cfg["PAD_CORNER_SITE_NAME"] == _CORNER_SITE
    assert cfg["PAD_EDGE_SPACING"] == _SPACING


def test_a_record_without_the_pdk_block_still_owes_exactly_those_three(tmp_path):
    """THE CONTROL. Nothing is defaulted when the producer published nothing."""
    proj = _project(tmp_path, None)
    assert _run(proj) == 1
    rep = _report(proj)
    owed = [f for f in rep["findings"]
            if f["rule"] == "PAD_CONFIG_VARIABLE_ABSENT"]
    assert len(owed) == 1
    named = owed[0]["variables_owed"]
    assert sorted(v.split(" ")[0] for v in named) == sorted(
        PAG.PDK_LIBRARY_OWNED_VARS)
    assert not (proj / "phase3/stage3/pnr/pad_assignment.json").exists()


def test_two_of_three_publishes_two_and_owes_the_third(tmp_path):
    partial = {k: v for k, v in _PDK_DECLARED.items()
               if k != "PAD_EDGE_SPACING"}
    proj = _project(tmp_path, partial, dict(_PDK_SOURCES))
    assert _run(proj) == 1
    rep = _report(proj)
    named = [f["variables_owed"] for f in rep["findings"]
             if f["rule"] == "PAD_CONFIG_VARIABLE_ABSENT"][0]
    assert [v.split(" ")[0] for v in named] == ["PAD_EDGE_SPACING"]


def test_an_empty_value_is_not_an_answer(tmp_path):
    """An empty string is a declaration nobody made, not a spacing of zero."""
    proj = _project(tmp_path, dict(_PDK_DECLARED, PAD_EDGE_SPACING=""),
                    dict(_PDK_SOURCES))
    assert _run(proj) == 1


def test_the_written_config_can_be_traced_back_to_the_pdk_file(tmp_path):
    proj = _project(tmp_path, dict(_PDK_DECLARED), dict(_PDK_SOURCES))
    assert _run(proj) == 0
    prov = _config(proj)["_provenance"]
    for var in PAG.PDK_LIBRARY_OWNED_VARS:
        assert PAG.DERIVED_CHIP_TOP_REL in prov[var]
        assert _PDK_SOURCES[var] in prov[var], (
            f"{var} names no PDK file:line, so the value cannot be checked "
            f"against the library it came from")


def test_a_source_the_producer_did_not_record_is_said_so_not_invented(tmp_path):
    proj = _project(tmp_path, dict(_PDK_DECLARED), {})
    assert _run(proj) == 0
    prov = _config(proj)["_provenance"]["PAD_SITE_NAME"]
    assert "did not record" in prov


def test_the_declaration_still_wins_over_the_record(tmp_path):
    """PRECEDENCE is unchanged: a tree that answers for itself is unaffected."""
    proj = _project(tmp_path, dict(_PDK_DECLARED), dict(_PDK_SOURCES))
    decl = proj / "input" / "submission_template"
    decl.mkdir(parents=True)
    (decl / "tapeout_declaration.json").write_text(json.dumps(
        {"answers": {"pad_site_name": "OPERATOR_SITE"}}))
    assert _run(proj) == 0
    assert _config(proj)["PAD_SITE_NAME"] == "OPERATOR_SITE"


def test_the_three_variables_are_named_by_variable_not_by_pdk(tmp_path):
    """Chip-agnostic guard. The reader may name the VARIABLES; it may not name
    a PDK, a vendor, a library or a site."""
    src = Path(PAG.__file__).read_text()
    start = src.index("PDK_LIBRARY_OWNED_VARS")
    body = src[start:src.index("def read_derived_chip_top")]
    for literal in ("gf180", "sky130", "sg13", "GF_IO_Site", "librelane"):
        assert literal not in body, f"{literal!r} baked into the reader"
