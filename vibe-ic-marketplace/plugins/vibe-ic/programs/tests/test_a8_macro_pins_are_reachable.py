"""A8 asks WHERE the macro's pins are, not only whether they exist
(analog decision q2-pin-layer).

MEASURED on u_hawaii_adc (vibeic-eda 0.3.79): the harness the decision ran
through OpenROAD routed to Metal4 pins that touch the macro edge with 0
violations, and to the same pins moved inside the `-hide` obstruction with 13
(shorts against the macro). The PDN planner lands on a full-height TopMetal1
supply stripe and refuses a short stub. A cut-layer pin is refused by every
router. None of that is visible to a gate that counts PIN names, so the gate
now asks four things of every pin A5 DECLARED (`layout_provenance.json`):

  * it is on the layer A5 drew it on                  PIN_LAYER_MISMATCH
  * that layer is a routing layer (a signal pin not
    on the lowest one)                                PIN_NOT_ROUTING_LAYER
  * a signal pin touches the macro boundary           SIGNAL_PIN_NOT_ON_EDGE
  * PnR's own PDN planner reaches every supply pin    PG_PIN_UNREACHABLE

and the A8 producer now declares the signal pins INOUT/SIGNAL (OpenROAD reads
a bare PIN as INPUT) and reports the PINs it measured in the LEF it wrote.
"""
from __future__ import annotations

import json
import hashlib
import shlex
import subprocess
import sys
from pathlib import Path

import _plugin_tree  # noqa: F401 — puts programs/ on sys.path

import analog_a8_hardmacro_emit as E  # noqa: E402
import phase3_one_shot_runner as P3  # noqa: E402

PROG = Path(_plugin_tree.plugin_path("programs")) / \
    "analog_a8_hardmacro_gen_check.py"

# The PDK layer table as A5 records it (`pins_basis.tech_lef_layers`), for a
# generic seven-metal stack. Written out, not derived, so the unchanged gate
# can be run against the same fixture.
TECH = [{"name": "CONT", "type": "CUT"}]
for _i, (_n, _d, _p, _w) in enumerate(
        [("M1", "HORIZONTAL", 0.48, 0.16), ("M2", "VERTICAL", 0.48, 0.2),
         ("M3", "HORIZONTAL", 0.48, 0.2), ("M4", "VERTICAL", 0.48, 0.2),
         ("M5", "HORIZONTAL", 0.48, 0.2), ("TM1", "VERTICAL", 2.28, 1.64),
         ("TM2", "HORIZONTAL", 4.0, 2.0)]):
    TECH.append({"name": _n, "type": "ROUTING", "direction": _d,
                 "pitch": _p, "width": _w})
    TECH.append({"name": f"V{_i + 1}", "type": "CUT"})
TECH.pop()

DECLARED = [
    {"net": "vin", "lef_layer": "TM1", "lef_type": "ROUTING", "rail": True,
     "use": "power"},
    {"net": "vss", "lef_layer": "TM1", "lef_type": "ROUTING", "rail": True,
     "use": "ground"},
    {"net": "vref", "lef_layer": "M4", "lef_type": "ROUTING", "rail": False,
     "use": "signal"},
    {"net": "vout", "lef_layer": "M4", "lef_type": "ROUTING", "rail": False,
     "use": "signal"},
]

HEAD = ("VERSION 5.7 ;\nMACRO blk\n  CLASS BLOCK ;\n  FOREIGN blk ;\n"
        "  ORIGIN 0 0 ;\n  SIZE 100.000 BY 50.000 ;\n")
OBS = ("  OBS\n      LAYER M2 ;\n        RECT 0 0 100 50 ;\n  END\n"
       "END blk\nEND LIBRARY\n")


def _pin(name, use, layer, rect):
    return (f"  PIN {name}\n    DIRECTION INOUT ;\n    USE {use} ;\n"
            f"    PORT\n      LAYER {layer} ;\n        RECT {rect} ;\n"
            f"    END\n  END {name}\n")


GOOD = {"vin": ("POWER", "TM1", "10 0 11.64 50"),
        "vss": ("GROUND", "TM1", "20 0 21.64 50"),
        "vref": ("SIGNAL", "M4", "40 0 40.5 5"),
        "vout": ("SIGNAL", "M4", "60 0 60.5 5")}


def _project(tmp_path, pins, declared=True):
    project = tmp_path / "proj"
    a = project / "phase3" / "analog"
    (a / "blk").mkdir(parents=True)
    (a / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "blk", "type": "ldo"}]}))
    (a / "blk" / "topology.json").write_text(json.dumps(
        {"ports": ["vin", "vss", "vref", "vout"],
         "rails": {"vdd": "vin", "vss": "vss"}}))
    (a / "blk" / "corner_results.json").write_text(json.dumps(
        {"design_content": "structure_and_geometry"}))
    if declared:
        pg_snapshot = a / "blk" / "a5_stdcell_pg.lef"
        pg_snapshot.write_text(
            "MACRO fixture_cell\n  SIZE 10 BY 2 ;\n"
            "  PIN VPWR\n    USE POWER ;\n    PORT\n"
            "      LAYER M1 ;\n      RECT 0 1.8 10 2 ;\n"
            "    END\n  END VPWR\n"
            "  PIN VGND\n    USE GROUND ;\n    PORT\n"
            "      LAYER M1 ;\n      RECT 0 0 10 0.2 ;\n"
            "    END\n  END VGND\nEND fixture_cell\n")
        measured = P3._discover_pg_from_lef(str(pg_snapshot), "M")
        assert measured is not None
        (a / "blk" / "layout_provenance.json").write_text(json.dumps(
            {"pins": DECLARED, "pins_basis": {
                "tech_lef_layers": TECH,
                "core_pg": {
                    "result": "MEASURED",
                    "method": "phase3_one_shot_runner._discover_pg_from_lef",
                    "snapshot": "phase3/analog/blk/a5_stdcell_pg.lef",
                    "source": "/fixture/pdk/fixture_stdcell.lef",
                    "source_sha256": hashlib.sha256(
                        pg_snapshot.read_bytes()).hexdigest(),
                    "metal_prefix": "M",
                    "power_pin": measured[0], "ground_pin": measured[1],
                    "followpin_layer": measured[2],
                    "rail_width_um": measured[3],
                },
            }}))
    h = a / "hardmacro" / "blk"
    h.mkdir(parents=True)
    body = "".join(_pin(n, *pins[n]) for n in ("vin", "vss", "vref", "vout"))
    (h / "blk.lef").write_text(HEAD + body + OBS)
    (h / "blk.lib").write_text("library (blk) {\n" + "  /* interface */\n" * 12
                               + "  cell (blk) { area : 1.0; }\n}\n")
    (h / "blk.v").write_text("module blk (\n    inout vin,\n    inout vss,\n"
                             "    inout vref,\n    inout vout\n);\n"
                             "// analog macro interface: the supplies are the "
                             "block's own\n// declared rails; analog ports "
                             "carry no direction\nendmodule\n")
    return project


def _gate(project):
    cp = subprocess.run([sys.executable, str(PROG), str(project),
                         "--block", "blk"], capture_output=True, text=True)
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")


def _with(**changes):
    pins = dict(GOOD)
    pins.update(changes)
    return pins


def test_edge_signal_pins_and_full_height_supply_stripes_pass(tmp_path):
    """The control: the geometry the decision measured as routable and
    powered."""
    rc, out = _gate(_project(tmp_path, GOOD))
    assert rc == 0, out


def test_a_pin_on_a_cut_layer_is_refused(tmp_path):
    rc, out = _gate(_project(tmp_path, _with(vref=("SIGNAL", "V2",
                                                   "40 0 40.5 5"))))
    assert (rc, "A8_HARDMACRO_PIN_NOT_ROUTING_LAYER" in out) == (1, True), out


def test_a_signal_pin_on_the_lowest_routing_layer_is_refused(tmp_path):
    pins = _with(vref=("SIGNAL", "M1", "40 0 40.5 5"))
    project = _project(tmp_path, pins)
    prov = project / "phase3" / "analog" / "blk" / "layout_provenance.json"
    doc = json.loads(prov.read_text())
    doc["pins"][2]["lef_layer"] = "M1"
    prov.write_text(json.dumps(doc))
    rc, out = _gate(project)
    assert (rc, "A8_HARDMACRO_PIN_NOT_ROUTING_LAYER" in out) == (1, True), out


def test_a_pin_off_its_declared_layer_is_refused(tmp_path):
    rc, out = _gate(_project(tmp_path, _with(vout=("SIGNAL", "M5",
                                                   "60 0 60.5 5"))))
    assert (rc, "A8_HARDMACRO_PIN_LAYER_MISMATCH" in out) == (1, True), out


def test_a_signal_pin_inside_the_obstruction_is_refused(tmp_path):
    """3 um inside the edge: the `-hide` OBS covers everything around it."""
    rc, out = _gate(_project(tmp_path, _with(vref=("SIGNAL", "M4",
                                                   "40 3 40.5 8"))))
    assert (rc, "A8_HARDMACRO_SIGNAL_PIN_NOT_ON_EDGE" in out) == (1, True), out


def test_a_supply_stub_the_pdn_planner_cannot_cross_is_refused(tmp_path):
    """A 2 um supply stub instead of a full-height stripe: PnR's own planner
    cannot guarantee a strap crosses it."""
    rc, out = _gate(_project(tmp_path, _with(vin=("POWER", "TM1",
                                                  "10 0 11.64 2"))))
    assert (rc, "A8_HARDMACRO_PG_PIN_UNREACHABLE" in out) == (1, True), out


def test_a_block_whose_layout_declares_no_pins_is_judged_as_before(tmp_path):
    """No A5 pin record: the new questions are not asked, so a package the
    gate passed before still passes."""
    rc, out = _gate(_project(tmp_path, _with(vref=("SIGNAL", "M4",
                                                   "40 3 40.5 8")),
                             declared=False))
    assert rc == 0, out


# ── the producer ──────────────────────────────────────────────────────────
BARE_LEF = ("MACRO blk\n  SIZE 100 BY 50 ;\n"
            "  PIN vdd\n    PORT\n      LAYER TM1 ;\n        RECT 1 0 3 50 ;\n"
            "    END\n  END vdd\n"
            "  PIN vin\n    PORT\n      LAYER M4 ;\n        RECT 5 0 6 4 ;\n"
            "    END\n  END vin\n"
            "  OBS\n      LAYER M2 ;\n        RECT 0 0 100 50 ;\n  END\n"
            "END blk\n")


def _emit(tmp_path, monkeypatch):
    p = tmp_path / "proj"
    b = p / "phase3" / "analog" / "blk"
    b.mkdir(parents=True)
    (b / "blk.gds").write_bytes(b"\x00" * 16)
    (b / "blk.mag").write_text("magic\ntech sometech\n")
    (b / "topology.json").write_text(json.dumps(
        {"ports": ["vdd", "vss", "vin"],
         "rails": {"vdd": "vdd", "vss": "vss"}}))
    monkeypatch.setattr(E, "magicrc_for", lambda *a, **k: "/pdk/x.magicrc")
    monkeypatch.setenv("A8_PIN_ACCESS_CLEARANCE_UM", "0")
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
        "simulator": "ngspice-fixture",
        "image_digest": "sha256:" + "a" * 64,
    }, ""))

    def fake_exec(container, cmd, timeout=900, *, marker=None, log_path=None):
        tcl = p / "phase3" / "analog" / "hardmacro" / "blk" / "blk_lef.tcl"
        write = next(
            (shlex.split(line) for line in tcl.read_text().splitlines()
             if line.startswith("lef write ")),
            None,
        )
        assert write is not None and write[:2] == ["lef", "write"]
        Path(write[2]).write_text(BARE_LEF)
        return 0, "", ""

    monkeypatch.setattr(E, "_docker_exec", fake_exec)
    r = E.emit_block(p, "blk", "c", "/pdk")
    lef = (p / "phase3" / "analog" / "hardmacro" / "blk" / "blk.lef"
           ).read_text()
    return r, lef


def _pin_block(lef, name):
    return lef.split(f"PIN {name}\n", 1)[1].split(f"END {name}", 1)[0]


def test_a_signal_pin_is_declared_inout_signal(tmp_path, monkeypatch):
    """A bare PIN is read by OpenROAD as INPUT; an analog port is INOUT."""
    r, lef = _emit(tmp_path, monkeypatch)
    blk = _pin_block(lef, "vin")
    assert ("DIRECTION INOUT ;" in blk, "USE SIGNAL ;" in blk) == \
        (True, True), lef
    assert "USE POWER ;" in _pin_block(lef, "vdd"), lef


def test_the_reported_pin_count_is_the_lefs_not_the_topologys(tmp_path,
                                                              monkeypatch):
    """Three ports declared, two PINs written: the record says two."""
    r, _lef = _emit(tmp_path, monkeypatch)
    assert r["pins"] == 2, r
