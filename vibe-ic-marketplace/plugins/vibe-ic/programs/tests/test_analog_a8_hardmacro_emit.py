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
import re
import sys
from pathlib import Path

import pytest

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
    monkeypatch.setattr(E, "load_native_measurement", lambda *a, **k: ({
        "liberty_value": 1.0,
        "liberty_power_unit": "1uW",
        "measurement_sha256": "m" * 64,
        "metric": "cell_leakage_power",
        "value": 1.0,
        "unit": "uW",
        "provenance": "real_ngspice",
        "source_netlist": "phase3/analog/blk/post_layout_extracted.spice",
        "source_netlist_sha256": "n" * 64,
        "native_log": "phase3/analog/blk/a8_native_measurement.ngspice.log",
        "native_log_sha256": "l" * 64,
        "simulator": "ngspice-47",
        "image_digest": "sha256:" + "a" * 64,
        "native_binary": {"path": "/usr/bin/ngspice", "sha256": "c" * 64,
                          "selection": "discovered"},
    }, ""))
    monkeypatch.setattr(E, "_selected_native_binary", lambda *a, **k: (
        {"path": "/usr/bin/ngspice", "sha256": "c" * 64,
         "selection": "discovered"}, ""))
    calls = []

    def fake_exec(container, cmd, timeout=900, *, marker=None, log_path=None):
        calls.append({"cmd": cmd, "marker": marker})
        hdir = p / "phase3" / "analog" / "hardmacro" / "blk"
        output = Path(re.search(r"(?m)^lef write (.+) -hide$", (hdir / marker).read_text()).group(1))
        assert output.is_file() and output.read_bytes() == b""
        assert output != hdir / "blk.lef"
        output.write_text(
            "MACRO blk\n  PIN vdd\n    USE POWER ;\n  END vdd\nEND blk\n")
        return 0, "", ""

    monkeypatch.setattr(E, "_docker_exec", fake_exec)
    r = E.emit_block(p, "blk", "c", "/pdk")
    assert r["emitted"] is True, r
    manifest = json.loads((p / "phase3" / "analog" / "hardmacro" /
                           "blk" / "a8_views_provenance.json").read_text())
    assert manifest["producer"] == "analog_a8_hardmacro_emit"
    assert manifest["source_gds_sha256"] == r["source_gds_sha256"]
    assert manifest["native_measurement"]["native_binary"]["sha256"] == "c" * 64
    assert set(manifest["views"]) == {".lef", ".lib", ".gds", ".v"}
    assert manifest["characterization_scope"]["timing_arcs"] == "NOT_MEASURED"
    assert manifest["characterization_scope"]["full_timing_characterization"] is False
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


# ---------------------------------------------------------------------------
# A SUPPLY PIN WITH NO `USE` IS A SIGNAL PIN.
#
# `lef write` emits every pin the same way — no DIRECTION, no USE — so a hard
# macro's supplies arrive at the digital flow as ordinary signals. `pdngen`
# then does not know the macro has a power connection to make and plans the
# grid as though the macro's area were free silicon.
# ---------------------------------------------------------------------------

_PG_LEF = """MACRO blk
  PIN vdd
    PORT
      LAYER Metal3 ;
        RECT 0 0 1 1 ;
    END
  END vdd
  PIN vss
    PORT
    END
  END vss
  PIN sig
    PORT
    END
  END sig
END blk
"""


def test_the_declared_rails_become_pg_pins():
    out, n = E.annotate_pg_pins(_PG_LEF, {"vdd": "vdd", "vss": "vss"})
    assert n == 2
    vdd = out.split("PIN vdd")[1].split("END vdd")[0]
    vss = out.split("PIN vss")[1].split("END vss")[0]
    sig = out.split("PIN sig")[1].split("END sig")[0]
    assert "USE POWER ;" in vdd and "DIRECTION INOUT ;" in vdd
    assert "USE GROUND ;" in vss
    # a signal pin is untouched
    assert "USE" not in sig and "DIRECTION" not in sig
    # the geometry is untouched
    assert "RECT 0 0 1 1 ;" in out


def test_the_design_names_its_own_rails():
    """The ROLE is the design's vocabulary; the NET is whatever this block
    calls it. A design that names its supply `avdd` is served by its own
    declaration and no supply name is hard-coded in the producer."""
    lef = _PG_LEF.replace("PIN vdd", "PIN avdd").replace(
        "END vdd", "END avdd")
    out, n = E.annotate_pg_pins(lef, {"vdd": "avdd", "vss": "vss"})
    assert n == 2
    assert "USE POWER ;" in out.split("PIN avdd")[1].split("END avdd")[0]


def test_a_role_the_table_cannot_place_is_left_alone():
    out, n = E.annotate_pg_pins(_PG_LEF, {"bias": "vdd"})
    assert n == 0 and out == _PG_LEF


def test_no_rails_declared_is_a_no_op():
    out, n = E.annotate_pg_pins(_PG_LEF, {})
    assert n == 0 and out == _PG_LEF


def _write_native_measurement_fixture(tmp_path: Path, *, value=0.5,
                                       unit="mW", declared_ports=None):
    project = tmp_path / "proj"
    b = project / "phase3" / "analog" / "blk"
    b.mkdir(parents=True)
    (project / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["blk"]}))
    (b / "layout.mag").write_text("magic\ntech sky130A\n")
    gds = b / "blk.gds"
    gds.write_bytes(b"real-gds-bytes")
    net = b / "post_layout_extracted.spice"
    net.write_text(".subckt blk vdd vss vin vout\n.ends blk\n")
    log = b / "a8_native_measurement.ngspice.log"
    log.write_text("ngspice-47\npwr = 0.0005\n")
    topo = {"ports": ["vdd", "vss", "vin", "vout"],
            "rails": {"vdd": "vdd", "vss": "vss"}}
    (b / "topology.json").write_text(json.dumps(topo))
    rec = {
        "schema": E._A8_MEASUREMENT_SCHEMA,
        "status": "MEASURED",
        "block": "blk",
        "metric": "cell_leakage_power",
        "value": value,
        "unit": unit,
        "provenance": "real_ngspice",
        "simulator": "ngspice-47",
        "image_digest": "sha256:" + "a" * 64,
        "native_binary": {"path": "/usr/bin/ngspice", "sha256": "c" * 64,
                          "selection": "discovered"},
        "declared_ports": (declared_ports if declared_ports is not None
                            else topo["ports"]),
        "source_layout": "phase3/analog/blk/layout.mag",
        "source_layout_sha256": E._sha256(b / "layout.mag"),
        "source_gds": "phase3/analog/blk/blk.gds",
        "source_gds_sha256": E._sha256(gds),
        "source_netlist": "phase3/analog/blk/post_layout_extracted.spice",
        "source_netlist_sha256": E._sha256(net),
        "native_log": "phase3/analog/blk/a8_native_measurement.ngspice.log",
        "native_log_sha256": E._sha256(log),
    }
    (b / E._A8_MEASUREMENT).write_text(json.dumps(rec))
    return project, b, topo


def _select_fixture_binary(monkeypatch):
    monkeypatch.setattr(E, "_selected_native_binary", lambda *a, **k: (
        {"path": "/usr/bin/ngspice", "sha256": "c" * 64,
         "selection": "discovered"}, ""))


def test_missing_native_measurement_refuses_before_magic(tmp_path: Path):
    project, b, topo = _write_native_measurement_fixture(tmp_path)
    (b / E._A8_MEASUREMENT).unlink()
    got, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert got is None and "native ngspice measurement" in why


def test_missing_native_binary_identity_is_not_measured(tmp_path: Path):
    project, b, topo = _write_native_measurement_fixture(tmp_path)
    path = b / E._A8_MEASUREMENT
    rec = json.loads(path.read_text())
    del rec["native_binary"]
    path.write_text(json.dumps(rec))
    got, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert why == "native binary provenance is absent or malformed"
    assert got is None


def test_stale_native_measurement_refuses(tmp_path: Path):
    project, b, topo = _write_native_measurement_fixture(tmp_path)
    (b / "blk.gds").write_bytes(b"mutated-after-measurement")
    got, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert got is None and "source_gds_sha256" in why


def test_native_measurement_value_must_match_native_log(tmp_path: Path):
    project, b, topo = _write_native_measurement_fixture(
        tmp_path, value=0.0009, unit="W")
    got, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert got is None and "does not match native" in why


@pytest.mark.parametrize("value,unit", [
    (0.0005, "W"), (0.5, "mW"), (500, "uW"),
    (500000, "nW"), (500000000, "pW"),
])
def test_native_measurement_units_preserve_matching_positive(tmp_path: Path,
                                                             value, unit):
    project, b, topo = _write_native_measurement_fixture(
        tmp_path, value=value, unit=unit)
    got, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert got is not None, why
    assert got["liberty_value"] == pytest.approx(500)


def test_loader_rejects_wrong_extraction_top_even_with_current_hash(tmp_path: Path):
    project, b, topo = _write_native_measurement_fixture(tmp_path)
    net = b / "post_layout_extracted.spice"
    net.write_text(".subckt wrong_block vdd vss vin vout\n.ends wrong_block\n")
    path = b / E._A8_MEASUREMENT
    rec = json.loads(path.read_text())
    rec["source_netlist_sha256"] = E._sha256(net)
    path.write_text(json.dumps(rec))
    got, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert got is None and "exact declared top-cell" in why


def test_declared_a3_subject_binding_is_emitted_by_a8(tmp_path: Path):
    project, b, topo = _write_native_measurement_fixture(tmp_path)
    (b / "spec.json").write_text(json.dumps({
        "block": "blk",
        "interface": {"pins": [{"name": p} for p in topo["ports"]]},
    }))
    a3 = b / "blk.sp"
    a3.write_text("* A3 netlist\n")
    sidecar = b / "netlist_provenance.json"
    sidecar.write_text(json.dumps({
        "block": "blk",
        "_provenance": {
            "design_content": "structure_and_geometry",
            "rendered_from": {
                "topology_json": {
                    "path": "phase3/analog/blk/topology.json",
                    "sha256": E._sha256(b / "topology.json"),
                },
                "spec_json": {
                    "path": "phase3/analog/blk/spec.json",
                    "sha256": E._sha256(b / "spec.json"),
                },
            },
            "artifact_sha256": E._sha256(a3),
        },
    }))
    measurement, why = E.load_native_measurement(
        project, "blk", b / "blk.gds", topo)
    assert measurement is not None, why
    bound, why = E._attach_declared_subject_binding(
        project, "blk", topo, measurement)
    assert bound is not None, why
    assert bound["design_content"] == "structure_and_geometry"
    binding = bound["subject_binding"]
    assert binding["block"] == "blk"
    assert binding["a3_netlist"] == "phase3/analog/blk/blk.sp"
    saved = json.loads((b / E._A8_MEASUREMENT).read_text())
    assert saved["subject_binding"] == binding


def test_missing_declared_a3_subject_stays_unbound(tmp_path: Path):
    project, b, topo = _write_native_measurement_fixture(tmp_path)
    measurement, why = E.load_native_measurement(
        project, "blk", b / "blk.gds", topo)
    assert measurement is not None, why
    same, why = E._attach_declared_subject_binding(
        project, "blk", topo, measurement)
    assert same is not None and "netlist_provenance" in why
    saved = json.loads((b / E._A8_MEASUREMENT).read_text())
    assert "subject_binding" not in saved and "design_content" not in saved


def test_extraction_requires_exact_declared_top_cell(tmp_path: Path,
                                                    monkeypatch):
    project, b, topo = _write_native_measurement_fixture(tmp_path)
    (b / E._A8_MEASUREMENT).unlink()
    monkeypatch.setattr(E, "layout_tech", lambda _b: "sky130A")
    monkeypatch.setattr(E, "magicrc_for", lambda *a, **k: "/pdk/sky130A.magicrc")
    monkeypatch.setattr(E, "_native_model_contract", lambda *a, **k: (
        {"path": "/pdk/models.lib", "section": "mos_tt",
         "sha256": "a" * 64}, ""))
    monkeypatch.setattr(E, "_native_ngspice_binary",
                        lambda *a, **k: ("/usr/bin/ngspice", ""))
    monkeypatch.setattr(E, "_remote_sha256", lambda *a: ("c" * 64, ""))
    monkeypatch.setattr(E, "_runtime_image_digest",
                        lambda *a, **k: ("sha256:" + "b" * 64, ""))
    monkeypatch.setattr(E._mx, "build_extraction_tcl",
                        lambda *a, **k: "extract")

    def fake_exec(container, cmd, timeout=900, *, marker=None, log_path=None):
        if "magic" in cmd:
            stage = b / ".a8_native_stage"
            stage.mkdir(parents=True, exist_ok=True)
            (stage / "blk_extracted.spice").write_text(
                ".subckt wrong_block vdd vss vin vout\n.ends wrong_block\n")
            return 0, "Cell wrong_block read from current working directory\n", ""
        raise AssertionError("ngspice must not run after wrong top-cell refusal")

    monkeypatch.setattr(E, "_docker_exec", fake_exec)
    rec, why = E._native_measurement_produce(
        project, "blk", "container", "/pdk", b / "blk.gds", topo)
    assert rec is None and "exact declared top-cell" in why
    assert not (b / E._A8_MEASUREMENT).exists()


def test_nonpositive_native_measurement_refuses(tmp_path: Path):
    project, b, topo = _write_native_measurement_fixture(tmp_path, value=0.0)
    got, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert got is None and "finite and > 0" in why


def test_native_measurement_emits_non_degenerate_leakage_liberty(tmp_path: Path,
                                                                  monkeypatch):
    project, b, _topo = _write_native_measurement_fixture(tmp_path)
    _select_fixture_binary(monkeypatch)
    lef = """MACRO blk
  PIN vdd
    PORT
      LAYER Metal3 ; RECT 0 0 1 1 ;
    END
  END vdd
  PIN vss
    PORT
      LAYER Metal3 ; RECT 1 0 2 1 ;
    END
  END vss
  PIN vin
    PORT
      LAYER Metal3 ; RECT 2 0 3 1 ;
    END
  END vin
  PIN vout
    PORT
      LAYER Metal3 ; RECT 3 0 4 1 ;
    END
  END vout
  SIZE 4 BY 4 ;
END blk
"""
    monkeypatch.setattr(E, "magicrc_for", lambda *a, **k: "/pdk/sky130A.magicrc")

    def fake_exec(container, cmd, timeout=900, *, marker=None, log_path=None):
        h = project / "phase3/analog/hardmacro/blk"
        output = Path(re.search(r"(?m)^lef write (.+) -hide$", (h / marker).read_text()).group(1))
        output.write_text(lef)
        return 0, "A8_LEF_OK", ""

    monkeypatch.setattr(E, "_docker_exec", fake_exec)
    result = E.emit_block(project, "blk", "container", "/pdk")
    assert result["emitted"] is True, result
    lib = (project / "phase3/analog/hardmacro/blk/blk.lib").read_text()
    assert "cell_leakage_power : 500;" in lib
    assert "cell_rise" not in lib and "cell_fall" not in lib
    manifest = json.loads((project /
                           "phase3/analog/hardmacro/blk/a8_views_provenance.json").read_text())
    assert manifest["native_measurement"]["metric"] == "cell_leakage_power"


def test_missing_measurement_uses_ordinary_producer_path(tmp_path: Path,
                                                         monkeypatch):
    project, b, _topo = _write_native_measurement_fixture(tmp_path)
    (b / E._A8_MEASUREMENT).unlink()
    produced = {
        "liberty_value": 500.0,
        "liberty_power_unit": "1uW",
        "measurement_sha256": "m" * 64,
        "metric": "cell_leakage_power",
        "value": 0.0005,
        "unit": "W",
        "provenance": "real_ngspice",
        "source_netlist": "phase3/analog/blk/post_layout_extracted.spice",
        "source_netlist_sha256": "n" * 64,
        "native_log": "phase3/analog/blk/a8_native_measurement.ngspice.log",
        "native_log_sha256": "l" * 64,
        "simulator": "ngspice-47",
        "image_digest": "sha256:" + "a" * 64,
    }
    calls = []
    reads = iter([(None, "missing"), (produced, "")])
    monkeypatch.setattr(E, "load_native_measurement",
                        lambda *a, **k: next(reads))
    monkeypatch.setattr(E, "_native_measurement_produce",
                        lambda *a, **k: (calls.append(a[1]) or (produced, "")))
    monkeypatch.setattr(E, "magicrc_for", lambda *a, **k: "/pdk/sky130A.magicrc")

    lef = """MACRO blk
  PIN vdd
    PORT
      LAYER Metal3 ; RECT 0 0 1 1 ;
    END
  END vdd
  PIN vss
    PORT
      LAYER Metal3 ; RECT 1 0 2 1 ;
    END
  END vss
  PIN vin
    PORT
      LAYER Metal3 ; RECT 2 0 3 1 ;
    END
  END vin
  PIN vout
    PORT
      LAYER Metal3 ; RECT 3 0 4 1 ;
    END
  END vout
  SIZE 4 BY 4 ;
END blk
"""

    def fake_exec(container, cmd, timeout=900, *, marker=None, log_path=None):
        h = project / "phase3/analog/hardmacro/blk"
        output = Path(re.search(r"(?m)^lef write (.+) -hide$", (h / marker).read_text()).group(1))
        output.write_text(lef)
        return 0, "A8_LEF_OK", ""

    monkeypatch.setattr(E, "_docker_exec", fake_exec)
    result = E.emit_block(project, "blk", "container", "/pdk")
    assert result["emitted"] is True, result
    assert calls == ["blk"]


def test_declared_port_mismatch_is_not_aliased(tmp_path: Path):
    project, b, topo = _write_native_measurement_fixture(tmp_path,
                                                         declared_ports=[
                                                             "IOVDD", "VSS",
                                                             "VREF", "VOUT"])
    got, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert got is None and "declared_ports" in why


def _source_power_fixture(tmp_path, monkeypatch, *, native_rc=0, diagnostic=""):
    """Neutral wiring control; transport values are not native qualification."""
    project, b, _old = _write_native_measurement_fixture(tmp_path)
    (b / E._A8_MEASUREMENT).unlink()
    topo = {"ports": ["vp", "vn", "control", "out"], "rails": {"vdd": "vp", "vss": "vn"}}
    (b / "topology.json").write_text(json.dumps(topo))
    bindings = []
    for filename, section in (("device.lib", "nom"), ("passive.lib", "rnom"), ("capacitive.lib", "cnom")):
        model = b / filename
        model.write_text(f".lib {section}\n* source-owned neutral model\n.endl {section}\n")
        bindings.append(f".lib {filename} {section}")
    (b / "blk.sp").write_text("\n".join(bindings + [".subckt blk vp vn control out", "R1 vp out 11k", ".ends blk", ""]))
    (b / "tb_blk.sp").write_text(
        '* delivered source conditions\n.include blk.sp\nVMAIN vp vn 2.3\nVZERO vn 0 0\n'
        'VREF control vn 0.4\nXDUT vp vn control out blk\nRLOAD out vn 7k\n'
        '.control\ntran 1n 1u\n.endc\n.end\n')
    monkeypatch.setattr(E, "magicrc_for", lambda *a: "/pdk/neutral.magicrc")
    monkeypatch.setattr(E, "_native_ngspice_binary", lambda *a: ("/usr/bin/ngspice", ""))
    monkeypatch.setattr(E, "_remote_sha256", lambda *a: ("c" * 64, ""))
    monkeypatch.setattr(E, "_runtime_image_digest", lambda *a: ("sha256:" + "b" * 64, ""))
    def native(container, cmd, timeout=900, *, marker=None, log_path=None):
        if marker == "a8_extract.tcl":
            (b / ".a8_native_stage/blk_extracted.spice").write_text(
                '.subckt blk vp vn control out\nR1 vp out 11k\n.ends blk\n')
            return 0, "neutral extraction transport", ""
        if marker == "a8_native_measurement.sp":
            (b / "a8_native_ngspice.log").write_text(diagnostic + "idd = 0.0002\npwr = 0.00046\n")
            return native_rc, "", ""
        raise AssertionError(cmd)
    monkeypatch.setattr(E, "_docker_exec", native)
    return project, b, topo


def test_delivered_measurement_deck_ignores_prose_comments(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch)
    template = b / "tb_blk.sp"
    template.write_text(template.read_text() + "\n* not VFAKE vp vn PWL(0 0 1n 99)\n")
    rec, why = E._native_measurement_produce(project, "blk", "", "/pdk", b / "blk.gds", topo)
    assert rec is not None, why
    deck = (b / "a8_native_measurement.sp").read_text()
    assert "VFAKE" not in deck
    assert "VMAIN vp vn 2.3" in deck


def test_current_native_op_preserves_all_models_sources_and_loads(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch)
    rec, why = E._native_measurement_produce(project, "blk", "", "/pdk", b / "blk.gds", topo)
    assert rec is not None, why
    deck = (b / "a8_native_measurement.sp").read_text()
    assert all(binding in deck for binding in (".lib device.lib nom", ".lib passive.lib rnom", ".lib capacitive.lib cnom"))
    assert "VMAIN vp vn 2.3" in deck and "VREF control vn 0.4" in deck
    assert "RLOAD out vn 7k" in deck and "XU vp vn control out blk" in deck
    assert "abs(i(VMAIN)*(v(vp)-v(vn)))" in deck
    assert "tran 1n 1u" not in deck and "*1.2" not in deck
    assert len(rec["model_bindings"]) == 3
    assert rec["measured_current_a"] == pytest.approx(0.0002)
    loaded, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert loaded is not None, why
    assert loaded["liberty_value"] == pytest.approx(460)


@pytest.mark.parametrize("native_rc,diagnostic", [(1, "unknown subckt\n"), (0, "Error: unresolved passive model\n")])
def test_current_native_failure_cannot_publish_plausible_power(tmp_path, monkeypatch, native_rc, diagnostic):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch, native_rc=native_rc, diagnostic=diagnostic)
    rec, why = E._native_measurement_produce(project, "blk", "", "/pdk", b / "blk.gds", topo)
    assert rec is None and "ngspice rc=" in why
    assert not (b / E._A8_MEASUREMENT).exists()


def test_native_residual_failure_cannot_publish_plausible_power(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch,
        diagnostic=";;RESIDUAL_FAIL node=rail err=1.2 unit=V tol=1e-06 strict=0\n")
    rec, why = E._native_measurement_produce(project, "blk", "", "/pdk", b / "blk.gds", topo)
    assert rec is None and "invalid operating point (RESIDUAL_FAIL)" in why
    assert not (b / E._A8_MEASUREMENT).exists()


def test_receipt_consumer_refuses_native_residual_even_when_power_matches(tmp_path):
    project, b, topo = _write_native_measurement_fixture(tmp_path)
    path = b / E._A8_MEASUREMENT
    rec = json.loads(path.read_text())
    log = project / rec["native_log"]
    log.write_text(log.read_text() + ";;RESIDUAL_FAIL node=rail err=1 unit=V tol=1e-06 strict=0\n")
    rec["native_log_sha256"] = E._sha256(log)
    path.write_text(json.dumps(rec))
    loaded, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert loaded is None and "invalid operating point" in why


@pytest.mark.parametrize("positive,negative,expected", [
    ("vp", "0", "v(vp)"), ("0", "vn", "(-v(vn))"),
    ("vp", "vn", "(v(vp)-v(vn))"), ("0", "0", "0")])
def test_native_control_voltage_handles_ground_without_a_vector_zero(positive, negative, expected):
    assert E._terminal_voltage_expression(positive, negative) == expected


def test_current_native_measurement_rejects_missing_model_binding(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch)
    rec, why = E._native_measurement_produce(project, "blk", "", "/pdk", b / "blk.gds", topo)
    assert rec is not None, why
    rec["model_bindings"].pop()
    (b / E._A8_MEASUREMENT).write_text(json.dumps(rec))
    loaded, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert loaded is None and "all delivered model libraries" in why


def test_current_native_measurement_rejects_changed_source_bias(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch)
    rec, why = E._native_measurement_produce(project, "blk", "", "/pdk", b / "blk.gds", topo)
    assert rec is not None, why
    tb = b / "tb_blk.sp"
    tb.write_text(tb.read_text().replace("VMAIN vp vn 2.3", "VMAIN vp vn 2.1"))
    loaded, why = E.load_native_measurement(project, "blk", b / "blk.gds", topo)
    assert loaded is None and "binding is stale" in why


def test_native_op_uses_declared_poweron_plateau_without_transient(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch)
    tb = b / "tb_blk.sp"
    tb.write_text(tb.read_text().replace("VMAIN vp vn 2.3", "VMAIN vp vn pwl(0 0 100n 2.3 20u 2.3)"))
    extracted = b / "post_layout_extracted.spice"
    text, binding = E._delivered_measurement_deck(project, "blk", extracted, topo["ports"], "blk", topo)
    assert "VMAIN vp vn dc 2.3\n" in text
    assert "pwl(" not in text
    assert binding["power_sources"][0]["dc_plateau"] == "2.3"
    assert binding["power_sources"][0]["source_value"] == "pwl(0 0 100n 2.3 20u 2.3)"
    assert binding["power_sources"][0]["dc_selection"] == "pwl_terminal_plateau"
    assert binding["source_testbench_sha256"] == E._sha256(tb)
    assert "tran 1n 1u" not in text


def test_native_op_explicit_dc_takes_precedence_over_poweron_waveform(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch)
    tb = b / "tb_blk.sp"
    tb.write_text(tb.read_text().replace("VMAIN vp vn 2.3", "VMAIN vp vn dc 2.1 pwl(0 0 100n 2.3 20u 2.3)"))
    extracted = b / "post_layout_extracted.spice"
    before = extracted.read_bytes()
    text, binding = E._delivered_measurement_deck(project, "blk", extracted, topo["ports"], "blk", topo)
    assert "VMAIN vp vn dc 2.1\n" in text and "pwl(" not in text
    assert binding["power_sources"][0]["dc_selection"] == "explicit_dc"
    assert binding["power_sources"][0]["dc_plateau"] == "2.1"
    assert extracted.read_bytes() == before
    assert "RLOAD out vn 7k" in text


@pytest.mark.parametrize("source,expected", [
    ("", 1e-5), (".options reltol=1e-3", 1e-5),
    (".option reltol=1e-7", 1e-7), (".options reltol=2u", 2e-6),
])
def test_native_op_precision_never_loosens_source_reltol(source, expected):
    cards, binding = E._native_op_precision([source])
    assert cards == [f".options reltol={expected:.12g}"]
    assert binding["reltol"] == expected
    assert binding["residual_acceptance"] == "unchanged_native_check"


def test_native_op_source_precision_expression_is_not_overwritten():
    cards, binding = E._native_op_precision([".param tol=1e-8", ".options reltol={tol}"])
    assert cards == []
    assert binding["source_reltol"] == ["{tol}"]
    assert binding["selection"] == "source_expression_preserved"


def test_native_op_solver_defaults_gear_and_preserves_an_explicit_method():
    cards, binding = E._native_op_solver([])
    assert cards == [".options method=gear"]
    assert binding["method"] == "gear" and binding["num_threads"] == 1
    assert binding["omp_wait_policy"] == "PASSIVE" and binding["gomp_spincount"] == 0
    cards, binding = E._native_op_solver([".options method=trap trtol=1"])
    assert cards == [] and binding["method"] == "trap"
    assert binding["selection"] == "delivered_source"


def test_selected_native_binary_is_bound_and_scheduled(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(E, "_docker_exec_raw", lambda *a, **k: (0, "", ""))
    native = E._docker_exec
    commands = []
    def capture(*args, **kwargs):
        commands.append(args[1])
        return native(*args, **kwargs)
    monkeypatch.setattr(E, "_docker_exec", capture)
    rec, why = E._native_measurement_produce(project, "blk", "", "/pdk", b / "blk.gds", topo,
                                             ngspice_bin="/candidate/ngspice")
    assert rec is not None, why
    assert rec["native_binary"] == {"path": "/candidate/ngspice", "sha256": "c" * 64, "selection": "explicit"}
    assert "OMP_WAIT_POLICY=PASSIVE GOMP_SPINCOUNT=0 /candidate/ngspice -b" in commands[-1]
    assert ".options method=gear" in (b / "a8_native_measurement.sp").read_text()
    assert "set num_threads=1" in (b / "a8_native_measurement.sp").read_text()


def test_changed_selected_native_binary_cannot_publish_measurement(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch)
    digests = iter([("c" * 64, ""), ("d" * 64, "")])
    monkeypatch.setattr(E, "_remote_sha256", lambda *a: next(digests))
    rec, why = E._native_measurement_produce(project, "blk", "", "/pdk", b / "blk.gds", topo)
    assert rec is None and "binary changed" in why
    assert not (b / E._A8_MEASUREMENT).exists()


def test_explicit_different_binary_does_not_reuse_cached_native_measurement(tmp_path, monkeypatch):
    project, b, topo = _source_power_fixture(tmp_path, monkeypatch)
    rec, why = E._native_measurement_produce(project, "blk", "", "/pdk", b / "blk.gds", topo)
    assert rec is not None, why
    calls = []
    monkeypatch.setattr(E, "_docker_exec_raw", lambda *a, **k: (0, "", ""))
    def produce(*args, **kwargs):
        calls.append(kwargs["ngspice_bin"])
        return None, "replacement native execution deliberately stopped"
    monkeypatch.setattr(E, "_native_measurement_produce", produce)
    result = E.emit_block(project, "blk", "", "/pdk", ngspice_bin="/candidate/ngspice")
    assert calls == ["/candidate/ngspice"] and result["emitted"] is False
    assert "different selected binary" in result["reason"]


def test_discovered_different_binary_does_not_reuse_cached_native_measurement(tmp_path, monkeypatch):
    project, b, _topo = _write_native_measurement_fixture(tmp_path)
    monkeypatch.setattr(E, "_native_ngspice_binary", lambda *a: ("/current/ngspice", ""))
    monkeypatch.setattr(E, "_remote_sha256", lambda *a: ("d" * 64, ""))
    calls = []
    def produce(*args, **kwargs):
        calls.append(args[1])
        return None, "replacement native execution deliberately stopped"
    monkeypatch.setattr(E, "_native_measurement_produce", produce)
    result = E.emit_block(project, "blk", "", "/pdk")
    assert calls == ["blk"]
    assert result["emitted"] is False
    assert "different selected binary" in result["reason"]


@pytest.mark.parametrize("native_rc,native_text", [(1, "MACRO failed\n"), (0, "")])
def test_native_lef_failure_preserves_prior_delivery(tmp_path, monkeypatch, native_rc, native_text):
    project, b, topo = _write_native_measurement_fixture(tmp_path)
    _select_fixture_binary(monkeypatch)
    h = project / "phase3/analog/hardmacro/blk"
    h.mkdir(parents=True)
    delivered = h / "blk.lef"
    delivered.write_text("prior native delivery\n")
    monkeypatch.setattr(E, "magicrc_for", lambda *a, **k: "/pdk/native.magicrc")
    def native(container, cmd, timeout=900, *, marker=None, log_path=None):
        output = Path(re.search(r"(?m)^lef write (.+) -hide$", (h / marker).read_text()).group(1))
        assert output != delivered and output.is_file() and output.read_bytes() == b""
        output.write_text(native_text)
        return native_rc, "", "native failure"
    monkeypatch.setattr(E, "_docker_exec", native)
    result = E.emit_block(project, "blk", "container", "/pdk")
    assert result["emitted"] is False and result["rc"] == 2
    assert delivered.read_text() == "prior native delivery\n"
    assert not list(h.glob(".blk-native-lef-*"))
