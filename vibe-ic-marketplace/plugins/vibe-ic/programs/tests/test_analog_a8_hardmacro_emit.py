#!/usr/bin/env python3
"""An analog block had no route to a real abstract, and Phase 3 needs one.

MEASURED. `digital_hardmacro_gen` writes a REAL abstract by Magic through the
PDK's own magicrc, and makes a DEF a precondition — an analog block has none
and never will; it is drawn, not placed. The only other producer was the
runner's deterministic stub (a 100x100 LEF with no pins, and its own text says
so). So A8 sat at VACUOUS_PASS while OpenROAD refused the digital top with
`ORD-2013: LEF master <block> not found`. The capability was never absent:
`lef write -hide` reads the pins from the layout's own port labels.

chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_a8_hardmacro_emit as E  # noqa: E402


def test_rails_and_signals_come_from_the_blocks_own_topology():
    topo = {"ports": ["vdd", "vss", "vin", "vout"],
            "rails": {"vdd": "vdd", "vss": "vss"}}
    assert E.block_ports(topo) == (["vdd", "vss"], ["vin", "vout"])


def test_a_block_that_names_its_rails_differently_needs_no_change_here():
    topo = {"ports": ["avdd", "agnd", "sig"],
            "rails": {"vdd": "avdd", "vss": "agnd"}}
    assert E.block_ports(topo) == (["avdd", "agnd"], ["sig"])


def test_ports_with_no_declared_rails_are_all_signals():
    assert E.block_ports({"ports": ["a", "b"]}) == ([], ["a", "b"])


def test_the_lef_tcl_writes_the_abstract_form():
    tcl = E.build_lef_tcl("blk", "/x/blk.gds", "/x/blk.lef")
    assert "gds read /x/blk.gds" in tcl
    assert "load blk" in tcl
    # `-hide` IS the abstract; without it Magic writes the full geometry and
    # the "abstract" is the implementation again.
    assert "lef write /x/blk.lef -hide" in tcl


def test_the_interface_verilog_declares_every_port_and_marks_no_direction():
    v = E.interface_verilog("blk", ["vdd", "vss"], ["vin", "vout"])
    for p in ("vdd", "vss", "vin", "vout"):
        assert f"inout {p};" in v
    assert "module blk (" in v and "endmodule" in v
    # the A8 gate refuses a file that calls itself a stub, and rightly: an
    # interface is not a behavioural model and must not pretend to be one.
    for marker in ("behavioral stub", "placeholder hardmacro",
                   "do not tape out", "ai_authored_methodology_stub"):
        assert marker not in v.lower()
    assert len(v.encode()) >= 150


def test_the_interface_liberty_declares_pg_pins_and_no_timing_arc():
    lib = E.interface_liberty("blk", ["vdd", "vss"], ["vin", "vout"])
    assert 'pg_pin (vdd)' in lib and 'primary_power' in lib
    assert 'pg_pin (vss)' in lib and 'primary_ground' in lib
    assert 'pin (vin)' in lib and 'is_analog : true' in lib
    # An analog macro has no arc to declare at this level, and inventing one
    # would be a lie a signoff tool would then act on.
    assert "timing" not in lib.replace("interface_timing", "")
    assert len(lib.encode()) >= 200


def test_the_technology_is_read_from_the_layout_that_was_drawn(tmp_path: Path):
    """The abstract has to be written by the technology the layout was DRAWN
    in, and the layout says which that is on line 2 of every .mag Magic
    writes. Picking "the only PDK installed" is not available: a full EDA
    image installs several (four, on the pinned one)."""
    d = tmp_path / "b"
    d.mkdir()
    (d / "layout.mag").write_text("magic\ntech some-tech\nmagscale 1 2\n")
    assert E.layout_tech(d) == "some-tech"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert E.layout_tech(empty) is None
    nomag = tmp_path / "nomag"
    nomag.mkdir()
    (nomag / "x.mag").write_text("magic\ntimestamp 1\n")
    assert E.layout_tech(nomag) is None


def test_a_missing_gds_is_a_named_refusal_not_a_stub(tmp_path: Path):
    p = tmp_path / "proj"
    (p / "phase3" / "analog" / "ldo").mkdir(parents=True)
    r = E.emit_block(p, "ldo", "", "/nowhere")
    assert r["emitted"] is False and r["rc"] == 1
    assert "GDS" in r["reason"]


def test_block_names_come_from_the_shared_loader(tmp_path: Path):
    """A block-list entry is a dict (name + spec + evidence), not a string.
    Rolling a reader here cost a run: `str(entry)` became a 2 KB path the
    filesystem refused with "File name too long" — a refusal that reads like a
    design problem and is a parser problem."""
    p = tmp_path / "proj"
    a = p / "phase3" / "analog"
    a.mkdir(parents=True)
    (a / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "ldo", "spec": {"specs": [1, 2, 3]}},
                    "delta_sigma"]}))
    assert sorted(E.declared_blocks(p)) == ["delta_sigma", "ldo"]


# ---------------------------------------------------------------------------
# An abstract whose obstruction abuts its pins has no pin access.
#
# MEASURED: `lef write -hide` tiles the macro's internal metal as OBS right up
# to each pin — the cut-out around one pin was the pin rectangle plus 0.1 um,
# which is less than a via. OpenROAD's detailed router refused all seven macro
# instances with `DRT-0073 No access point for <inst>/<pin>`, AFTER floorplan,
# PDN, CTS and global route had all completed. Magic's own `-pinonly` is not
# the remedy: it shrinks the pin to a 0.1 x 0.3 um sliver and still writes the
# obstruction.
# ---------------------------------------------------------------------------

_LEF = """MACRO blk
  CLASS BLOCK ;
  SIZE 10.000 BY 10.000 ;
  PIN p
    PORT
      LAYER Metal2 ;
        RECT 4.000 4.000 5.000 4.300 ;
    END
  END p
  OBS
      LAYER Metal2 ;
        RECT 0.000 0.000 10.000 10.000 ;
      LAYER Metal3 ;
        RECT 0.000 0.000 10.000 10.000 ;
  END
END blk
"""


def test_the_halo_is_cut_only_from_the_pins_own_layer():
    out, n = E.carve_pin_access(_LEF, 0.5)
    assert n == 1
    m2 = out.split("LAYER Metal2 ;")[2].split("LAYER Metal3")[0]
    rects = [tuple(float(v) for v in r)
             for r in E._RECT_RE.findall(m2)]
    # the original single rect is gone, replaced by pieces around the halo
    assert (0.0, 0.0, 10.0, 10.0) not in rects
    assert len(rects) == 4
    # nothing covers the halo any more
    for (x1, y1, x2, y2) in rects:
        assert not (x1 < 5.5 and x2 > 3.5 and y1 < 4.8 and y2 > 3.5)
    # the OTHER layer is untouched — the obstruction is real blockage and
    # dropping it is how a clean-looking die gets coupling nobody modelled
    m3 = out.split("LAYER Metal3 ;")[1]
    assert "RECT 0.000 0.000 10.000 10.000 ;" in m3


def test_rect_minus_is_exact_on_every_side():
    a = (0.0, 0.0, 10.0, 10.0)
    assert E._rect_minus(a, (20.0, 20.0, 30.0, 30.0)) == [a]      # disjoint
    assert E._rect_minus(a, (-1.0, -1.0, 11.0, 11.0)) == []       # covered
    left = E._rect_minus(a, (5.0, -1.0, 11.0, 11.0))
    assert left == [(0.0, 0.0, 5.0, 10.0)]


def test_the_carve_default_did_not_move_on_a_refuted_hypothesis():
    """The carve was suspected of causing thousands of Magic `Illegal overlap
    between obsmN and metalN` entries (which abort LVS). MEASURED with it
    fully OFF: 3,719 entries against 3,716 with it on. Not the cause — so the
    default stays where the best measured die was produced, and the knob
    stays available for a caller who wants the whole obstruction back."""
    import inspect
    src = inspect.getsource(E)
    assert 'A8_PIN_ACCESS_CLEARANCE_UM", "0.6"' in src
    # …and 0 must still mean "do not carve at all"
    assert "if halo <= 0" in src


def test_a_lef_with_no_pins_is_returned_unchanged():
    out, n = E.carve_pin_access("MACRO blk\n  OBS\n  END\nEND blk\n", 0.5)
    assert n == 0


# ---------------------------------------------------------------------------
# vibe-ic#2010 items 4 and 8 — the Magic run is supervised, the report atomic.
# ---------------------------------------------------------------------------

def test_a_marked_exec_is_routed_through_the_shared_watchdog(monkeypatch):
    """Item 8 (watchdog compliance). `_docker_exec(..., marker=)` delegates to
    `_docker_watchdog.run_docker_supervised` with THIS module's raw exec
    injected — the same shape `design_one_shot_runner` uses — and a call
    without a marker stays a short bounded probe."""
    import _docker_watchdog as _dw
    seen = {}

    def fake(container, cmd, marker, *, docker_exec_raw, log_path=None, **kw):
        seen.update(container=container, cmd=cmd, marker=marker,
                    raw=docker_exec_raw)
        return 0, "supervised", ""

    monkeypatch.setattr(_dw, "run_docker_supervised", fake)
    assert E._docker_exec("c", "magic -dnull x.tcl", marker="x.tcl") == (0, "supervised", "")
    assert seen["marker"] == "x.tcl" and seen["raw"] is E._docker_exec_raw
    # no marker -> the raw probe (host shell when container is '')
    rc, out, _ = E._docker_exec("", "echo probe")
    assert rc == 0 and out.strip() == "probe" and seen["cmd"] == "magic -dnull x.tcl"


def test_the_lef_write_carries_a_marker_from_its_own_argv(tmp_path: Path,
                                                          monkeypatch):
    """The long tool run in `emit_block` names its script as the marker, so
    the watchdog can find the process it supervises in the container's own
    process table."""
    p = tmp_path / "proj"
    b = p / "phase3" / "analog" / "blk"
    b.mkdir(parents=True)
    (b / "blk.gds").write_bytes(b"\x00" * 16)
    (b / "blk.mag").write_text("magic\ntech sometech\n")
    (b / "topology.json").write_text(json.dumps(
        {"ports": ["vdd", "vss", "vin"], "rails": {"p": "vdd", "n": "vss"}}))
    monkeypatch.setattr(E, "magicrc_for", lambda *a, **k: "/pdk/x.magicrc")
    calls = []

    def fake_exec(container, cmd, timeout=900, *, marker=None, log_path=None):
        calls.append({"cmd": cmd, "marker": marker})
        (p / "phase3" / "analog" / "hardmacro" / "blk" / "blk.lef").write_text(
            "MACRO blk\n  PIN vdd\n    USE POWER ;\n  END vdd\nEND blk\n")
        return 0, "", ""

    monkeypatch.setattr(E, "_docker_exec", fake_exec)
    r = E.emit_block(p, "blk", "c", "/pdk")
    assert r["emitted"] is True, r
    long_runs = [c for c in calls if "magic" in c["cmd"]]
    assert long_runs and all(c["marker"] and c["marker"] in c["cmd"]
                             for c in long_runs), calls


def test_the_json_report_is_written_atomically(tmp_path: Path, monkeypatch):
    """Item 4 (declared reports are written atomically)."""
    import _atomic_artefact as _aa
    p = tmp_path / "proj"
    a = p / "phase3" / "analog"
    a.mkdir(parents=True)
    (a / "analog_block_list.json").write_text(json.dumps({"blocks": ["blk"]}))
    monkeypatch.setattr(E, "emit_block", lambda *a, **k: {
        "block": "blk", "emitted": True, "rc": 0, "lef_bytes": 1, "pins": 1})
    out = tmp_path / "r" / "a8.json"
    out.parent.mkdir()
    assert E.main([str(p), "--json", str(out)]) == 0
    assert json.loads(out.read_text())["blocks"][0]["block"] == "blk"
    assert not [f for f in out.parent.iterdir() if _aa.is_temp_artefact(f)]
