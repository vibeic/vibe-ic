"""The at-speed ATPG Liberty must follow the DESIGN, not a hard-coded literal.

REGRESSION for the PDK-SELECTION half of a measured DT1 defect (spm x
gf180mcuD, plugin v1.12.51): a gf180mcu design was gate-levelised against a
SKY130 Liberty, so none of its cells had a functional model and the at-speed
ATPG died on its first fault.

`_resolve_design_liberty` consulted, in order, an explicit flag, a project PDK
glob, the flow's recorded corner in `phase2/stage2/constraints/pvt_matrix.json`,
and finally a HARD-CODED shared-OSS library. The trap is an ORDERING one: this
producer is a PHASE-2 step, but `pvt_matrix.json` is written by PHASE 3. On the
measured run the producer resolved its Liberty at 18:23:34.723 and
`pvt_matrix.json` appeared at 18:23:38.933 — 4.2 s too late. That source could
not be consulted, so resolution fell through to the literal.

The natural control in the same run: DT2 (path-delay) ran two minutes later,
through the SAME shared resolver, and recorded the correct gf180 Liberty. Same
code, same project, later clock reading. The defect is ordering, not logic.

The fix adds the Liberty SYNTHESIS ITSELF LOADED
(`phase2/stage2/synth/stats.json`) as a source ranked above `pvt_matrix.json`.
That file was written at 18:23:13.618 — 21.1 s BEFORE the producer ran — and it
names the library the netlist's cells LITERALLY CAME FROM. It is correct by
construction rather than by clock reading, and it is chip/PDK/vendor-agnostic:
whatever synth loaded is what the ATPG reads.

This is the SECONDARY fix. The load-bearing guard is pinned in
`test_dt1_tool_crash_is_not_a_coverage_number.py`, which refuses an unlevelised
core whatever the resolver chose. Shipping only this one would leave the next
tool crash free to lie the same way.

Every pre-existing source keeps its precedence — the controls below pin that.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
SCRIPT = PROG / "transition_fault_atpg_run.py"
assert SCRIPT.exists()

sys.path.insert(0, str(PROG))
import transition_fault_atpg_run as tdf  # noqa: E402
import lec_run  # noqa: E402

# Measured artefacts, reproduced. These are EVIDENCE, never inputs to the logic.
_RIGHT_LIB = ("/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/"
              "gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib")


def _write_synth_stats(project: Path, liberty) -> None:
    d = {"schema": "synth_area_stats/1", "top_module": "spm"}
    if liberty is not None:
        d["chip_area_unit_evidence"] = {"established": True, "liberty": liberty}
    (project / "phase2" / "stage2" / "synth").mkdir(parents=True, exist_ok=True)
    (project / "phase2" / "stage2" / "synth" / "stats.json").write_text(
        json.dumps(d))


def test_synth_recorded_liberty_beats_the_hardcoded_fallback(tmp_path):
    """The measured ordering bug, reproduced: no project PDK glob, and no
    pvt_matrix.json yet (a phase-3 artefact this phase-2 producer runs ahead
    of). Resolution must reach the library SYNTH loaded, never the literal."""
    _write_synth_stats(tmp_path, _RIGHT_LIB)
    assert not (tmp_path / "phase2/stage2/constraints/pvt_matrix.json").exists()
    got = tdf._resolve_design_liberty(tmp_path, None)
    assert got == _RIGHT_LIB
    assert got != lec_run.DEFAULT_LIBERTY


def test_absent_synth_record_leaves_resolution_exactly_as_before(tmp_path):
    """CONTROL — a project with no synth record must resolve exactly as it did
    before this change. The new source only fills a gap where resolution
    previously fell through; it never displaces a working answer."""
    assert tdf._resolve_design_liberty(tmp_path, None) == lec_run.DEFAULT_LIBERTY
    _write_synth_stats(tmp_path, None)          # file present, records none
    assert tdf._resolve_design_liberty(tmp_path, None) == lec_run.DEFAULT_LIBERTY


def test_explicit_and_project_pdk_still_win(tmp_path):
    """CONTROL — the new source must not outrank the two sources above it."""
    _write_synth_stats(tmp_path, _RIGHT_LIB)
    assert tdf._resolve_design_liberty(tmp_path, "/x/my.lib") == "/x/my.lib"
    lib = tmp_path / "input" / "pdk" / "liberty"
    lib.mkdir(parents=True)
    (lib / "commercial_pdk_demo_typ.lib").write_text("library(x){}")
    assert tdf._resolve_design_liberty(tmp_path, None) == (
        "input/pdk/liberty/commercial_pdk_demo_typ.lib")


def test_flow_recorded_corner_still_wins_when_it_exists(tmp_path):
    """CONTROL — when the phase-3 corner record DOES exist (a re-grade, or any
    later pass), it must still be consulted; the new source must not shadow a
    source that outranks nothing it should outrank. Here synth records none, so
    the corner is the first hit."""
    _write_synth_stats(tmp_path, None)
    con = tmp_path / "phase2" / "stage2" / "constraints"
    con.mkdir(parents=True)
    (con / "pvt_matrix.json").write_text(json.dumps(
        {"primary_corner": "TT", "corners": [{"label": "TT",
                                              "liberty": _RIGHT_LIB}]}))
    assert tdf._resolve_design_liberty(tmp_path, None) == _RIGHT_LIB


def test_synth_recorded_liberty_is_read_by_key_not_by_pinned_path():
    """The reader must survive the surrounding block being renamed — a schema
    move must not silently switch this source off and drop resolution back to
    the hard-coded fallback."""
    assert tdf.synth_recorded_liberty(
        {"some_other_block": {"liberty": _RIGHT_LIB}}) == _RIGHT_LIB
    assert tdf.synth_recorded_liberty(
        {"corners": [{"liberty": _RIGHT_LIB}]}) == _RIGHT_LIB
    # CONTROL: nothing that is not a .lib path is accepted as one.
    assert tdf.synth_recorded_liberty({"liberty": "none"}) == ""
    assert tdf.synth_recorded_liberty({}) == ""
    assert tdf.synth_recorded_liberty({"netlist": "spm_synth.v"}) == ""


def test_resolver_carries_no_new_chip_or_pdk_literal():
    """chip/PDK/vendor-AGNOSTIC: the new source names no library. The only
    library literal the resolver may still reach is the pre-existing shared
    default it imports from lec_run."""
    src = SCRIPT.read_text()
    body = src.split("def synth_recorded_liberty(", 1)[1].split("\ndef _resolve_design_liberty", 1)[0]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("#"))
    for literal in ("sky130", "gf180", "sg13", "nangate", "asap7", "spm"):
        assert literal not in code.lower(), f"chip/PDK literal {literal!r} in code"
