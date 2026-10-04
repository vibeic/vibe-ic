#!/usr/bin/env python3
"""_release_kit.py — a project on the IP path, for the step-37.5ip doc tests.

WHAT IT BUILDS, AND WHY THE BYTES ARE WRITTEN HERE
==================================================
A project root carrying everything step 37.5ip's release-document producer and
gate read:

    input/project.json                     the design identity
    input/submission_template/NO_TEMPLATE.txt   the IP-path router file
    phase1/generated_docs/L*.json          the design INPUT layers
    phase3/stage4/hardmacro/<name>.{lef,lib,gds,v}   the delivered kit

The GDSII stream is CONSTRUCTED from record bytes here rather than by any
helper the programs under test share, for the reason
`test_digital_hardmacro_check` already records about its own builder: the test
and the gate must reach the same bounding box from two independent directions,
and a builder shared with the code under test would make them agree by
construction.

TWO PACKAGES BY DEFAULT, AND THAT IS THE CONTROL
================================================
Every falsification in `test_release_docs_check` breaks ONE thing in ONE
release and leaves the second release untouched, in the SAME project, judged in
the SAME invocation. A refusal that also reddens the untouched release is
environmental, not content-earned; a control that stays green is what
distinguishes the two. It is the same shape `flow-change-acceptance` demands
of any flow-level change, applied inside one run rather than across two.

chip-AGNOSTIC: no design, vendor, foundry, process-node or protocol name
appears anywhere below. The PDK string is an OPEN PDK this flow already
targets.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Dict, Sequence

#: The delivered package this project's defects are injected into.
SUBJECT = "block_a"
#: The delivered package no test ever touches. Its verdict is the control.
CONTROL = "block_b"

DESIGN = "widget"
PDK = "gf180mcuD"

#: Three signal pins and two supply pins, so the signal / supply / total split
#: the gate cross-checks has three distinct numbers (3, 2, 5). Equal numbers
#: would let an arithmetic bug pass unnoticed.
LEF = """VERSION 5.8 ;
BUSBITCHARS "[]" ;
MACRO {name}
  CLASS BLOCK ;
  FOREIGN {name} 0 0 ;
  ORIGIN 0 0 ;
  SIZE 120.000 BY 80.000 ;
  PIN clk
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER met3 ;
        RECT 1.0 1.0 2.0 2.0 ;
    END
  END clk
  PIN rst_n
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER met3 ;
        RECT 4.0 1.0 5.0 2.0 ;
    END
  END rst_n
  PIN dout
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER met3 ;
        RECT 8.0 1.0 9.0 2.0 ;
    END
  END dout
  PIN VPWR
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER met4 ;
        RECT 0.0 0.0 120.0 2.0 ;
    END
  END VPWR
  PIN VGND
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER met4 ;
        RECT 0.0 78.0 120.0 80.0 ;
    END
  END VGND
  OBS
    LAYER met1 ;
      RECT 10.0 10.0 100.0 70.0 ;
  END
END {name}
END LIBRARY
"""

LIB = """library ({name}_lib) {{
  delay_model : table_lookup ;
  time_unit : "1ns" ;
  cell ({name}) {{
    area : 9600.0 ;
    pg_pin (VPWR) {{ voltage_name : VPWR ; pg_type : primary_power ; }}
    pg_pin (VGND) {{ voltage_name : VGND ; pg_type : primary_ground ; }}
    pin (clk) {{ direction : input ; capacitance : 0.01 ; clock : true ; }}
    pin (rst_n) {{ direction : input ; capacitance : 0.01 ; }}
    pin (dout) {{
      direction : output ;
      timing () {{
        related_pin : "clk" ;
        cell_rise (scalar) {{ values ("0.42") ; }}
        cell_fall (scalar) {{ values ("0.39") ; }}
      }}
    }}
  }}
}}
"""

#: A blackbox simulation view: the LOGICAL interface only, with the supplies as
#: `supply0`/`supply1` nets. That is the convention `digital_hardmacro_check`
#: states and accepts, and it is why the gate settles the SIGNAL pin count
#: against this view and the TOTAL against the document's own component rows.
VERILOG = """// Blackbox simulation view.
module {name} (
    input  wire clk,
    input  wire rst_n,
    output wire dout
);
    supply1 VPWR;
    supply0 VGND;
endmodule
"""


def _rec(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HH", 4 + len(payload), tag) + payload


def _ascii(text: str) -> bytes:
    raw = text.encode("ascii")
    return raw + (b"\x00" if len(raw) % 2 else b"")


def _real8(value: float) -> bytes:
    """One GDSII 8-byte real: excess-64 base-16 exponent, 7-byte mantissa.

    NOT an IEEE double. Writing `struct.pack(">d", ...)` here produces a stream
    whose UNITS record decodes to a scale 262144x wrong, and the outline check
    then reports a 100% mismatch on a kit that is correct — a fixture bug that
    reads exactly like a real defect.
    """
    if value == 0:
        return b"\x00" * 8
    sign = 0x80 if value < 0 else 0
    value = abs(value)
    exponent = 64
    while value >= 1.0:
        value /= 16.0
        exponent += 1
    while value < 1.0 / 16.0:
        value *= 16.0
        exponent -= 1
    mantissa = int(round(value * (1 << 56)))
    if mantissa >= (1 << 56):
        mantissa >>= 4
        exponent += 1
    return bytes([sign | exponent]) + mantissa.to_bytes(7, "big")


def build_gds(name: str, width_um: float = 120.0,
              height_um: float = 80.0) -> bytes:
    """A GDSII stream whose one structure has a `width_um x height_um` bbox."""
    stamp = struct.pack(">12h", *([2026, 1, 1, 0, 0, 0] * 2))
    out = _rec(0x0002, struct.pack(">h", 600))                 # HEADER
    out += _rec(0x0102, stamp)                                 # BGNLIB
    out += _rec(0x0206, _ascii("LIB"))                         # LIBNAME
    out += _rec(0x0305, _real8(1e-3) + _real8(1e-9))           # UNITS
    out += _rec(0x0502, stamp)                                 # BGNSTR
    out += _rec(0x0606, _ascii(name))                          # STRNAME
    out += _rec(0x0800)                                        # BOUNDARY
    out += _rec(0x0D02, struct.pack(">h", 66))                 # LAYER
    out += _rec(0x0E02, struct.pack(">h", 20))                 # DATATYPE
    x1, y1 = int(width_um * 1000), int(height_um * 1000)
    points = [(0, 0), (x1, 0), (x1, y1), (0, y1), (0, 0)]
    out += _rec(0x1003, b"".join(struct.pack(">ii", x, y) for x, y in points))
    out += _rec(0x1100)                                        # ENDEL
    out += _rec(0x0700)                                        # ENDSTR
    out += _rec(0x0400)                                        # ENDLIB
    return out


def _write_current_kit(root: Path, packages: Sequence[str]) -> None:
    """Stage the current hardmacro receipt consumed by the live IP gate.

    The release-document fixture used to stop at the four delivered views.
    Since ``digital_hardmacro_check`` became a current-production consumer,
    that tree is correctly refused unless the receipt binds the signed-off
    DEF/GDS, route declaration, timing inputs, and the views it delivers.
    This is a software fixture for that contract: every byte is local, hashed
    by ``_physical_current``, and the execution markers are explicit.
    """
    if not packages:
        return

    import sys
    programs = Path(__file__).resolve().parents[1]
    if str(programs) not in sys.path:
        sys.path.insert(0, str(programs))
    import _owner_declared as owner_declared
    import _physical_current as current
    import _tapeout_declaration as declaration

    project = Path(root)
    design = SUBJECT if SUBJECT in packages else packages[0]
    hardmacro = project / "phase3/stage4/hardmacro"
    pnr = project / "phase3/stage3/pnr"
    constraints = project / "phase3/stage3/constraints"
    extracted = project / "phase3/stage3/extracted"
    sta = project / "phase3/stage3/sta"
    gds_dir = project / "phase3/stage4/gds"
    for directory in (pnr, constraints, extracted, sta, gds_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # The selected DEF and GDS are the producer's source subjects.  Their
    # design/top-cell identity agrees with the selected package and the GDS
    # output below is byte-identical to this signed-off input.
    (pnr / "routed.def").write_text(
        f"VERSION 5.8 ;\nDESIGN {design} ;\nEND DESIGN\n",
        encoding="utf-8")
    source_gds = gds_dir / f"{design}.gds"
    source_gds.write_bytes((hardmacro / f"{design}.gds").read_bytes())
    timing_netlist = pnr / f"{design}_pnr.v"
    timing_netlist.write_bytes((hardmacro / f"{design}.v").read_bytes())
    (constraints / "signoff.sdc").write_text(
        "create_clock -period 20 [get_ports clk]\n", encoding="utf-8")
    (extracted / f"{design}.spef").write_text(
        '*SPEF "IEEE 1481-1998"\n*DESIGN "' + design + '"\n',
        encoding="utf-8")
    (sta / f"{design}.rpt").write_text(
        "Startpoint: clk\nEndpoint: dout\nslack (MET) 0.50\n",
        encoding="utf-8")

    technology = project / "reports/phase3/technology_units.json"
    technology.parent.mkdir(parents=True, exist_ok=True)
    technology.write_text(json.dumps({"pdk": PDK}, indent=2) + "\n",
                           encoding="utf-8")

    pdk = project / "input/pdk"
    (pdk / "liberty").mkdir(parents=True, exist_ok=True)
    (pdk / "magic").mkdir(parents=True, exist_ok=True)
    (pdk / "liberty" / "timing.lib").write_text(
        "library(fixture) { cell(fixture) { area: 1; } }\n",
        encoding="utf-8")
    (pdk / "magic" / "fixture.magicrc").write_text(
        "# SOFTWARE_FIXTURE_ONLY magic configuration\n", encoding="utf-8")

    route = project / declaration.DECLARATION_REL
    route.parent.mkdir(parents=True, exist_ok=True)
    doc = declaration.blank_declaration()
    doc, _ignored = declaration.merge_answers(
        doc, {"deliverable": declaration.DELIVERABLE_HARDMACRO})
    owner_declared.attest(doc)
    route.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    log = hardmacro / "digital_lef.log"
    timing_log = hardmacro / "timing_model.log"
    log.write_text("DIGITAL_LEF_WRITE_DONE SOFTWARE_FIXTURE_ONLY\n",
                   encoding="utf-8")
    timing_log.write_text("TIMING_MODEL_DONE SOFTWARE_FIXTURE_ONLY\n",
                          encoding="utf-8")
    timing_recipe = hardmacro / "timing_recipe.tcl"
    lef_recipe = hardmacro / "lef_recipe.tcl"
    timing_recipe.write_text("# SOFTWARE_FIXTURE_ONLY timing recipe\n",
                             encoding="utf-8")
    lef_recipe.write_text("# SOFTWARE_FIXTURE_ONLY LEF recipe\n",
                          encoding="utf-8")

    inputs = {
        "def": current.entry(project, pnr / "routed.def"),
        "gds": current.entry(project, source_gds),
        "route": current.entry(project, route),
        "technology": current.entry(project, technology),
        "timing_netlist": current.entry(project, timing_netlist),
        "timing_sdc": current.entry(project, constraints / "signoff.sdc"),
        "timing_spef": current.entry(project, extracted / f"{design}.spef"),
        "timing_sta_report": current.entry(project, sta / f"{design}.rpt"),
        "timing_recipe": current.entry(project, timing_recipe),
        "pdk_timing_liberty": current.entry(project, pdk / "liberty/timing.lib"),
        "pdk_magicrc": current.entry(project, pdk / "magic/fixture.magicrc"),
        "lef_recipe": current.entry(project, lef_recipe),
    }
    outputs = {
        "lef": current.entry(project, hardmacro / f"{design}.lef"),
        "liberty": current.entry(project, hardmacro / f"{design}.lib"),
        "gds": current.entry(project, hardmacro / f"{design}.gds"),
        "verilog": current.entry(project, hardmacro / f"{design}.v"),
        "log": current.entry(project, log),
        "timing_log": current.entry(project, timing_log),
    }
    record = current.build(
        project, "37.5ip", "stage4", design, PDK, "magic+opensta",
        inputs, outputs,
        {"rc": 0, "argv": ["magic+opensta", "SOFTWARE_FIXTURE_ONLY"],
         "timing": {"rc": 0, "argv": ["opensta", "SOFTWARE_FIXTURE_ONLY"]}},
    )
    (hardmacro / "current_kit.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")


def _layers(register_rich: bool, bus_width: int = 1) -> Dict[str, dict]:
    """The Phase-1 design INPUT this producer reads, in the shapes it ships in.

    Two shapes deliberately: the extracted layers put their content at the top
    level and the skeleton-emitted ones nest it under `fields`. Both are in the
    corpus, so both are in the fixture — a reader that understands only one
    reports a false NOT_MEASURED over a document that plainly states the answer.
    """
    regmap = {"doc_class": "regmap", "registers": [],
              "base_address": "Defined at integration; offsets are relative."}
    if register_rich:
        regmap["register_groups"] = [
            {"group": "Control", "fields": ["enable", "mode"]}]
    else:
        regmap["register_groups"] = []
    return {
        "L1_DATASHEET": {
            "doc_class": "datasheet", "ic_name": DESIGN,
            "description": "A synchronous block delivered as a hard macro."},
        "L4_REGMAP": regmap,
        "L7_TEST_DEBUG": {
            "test_modes": [{"name": "scan"}],
            "debug_observability": [{"name": "state"}]},
        "L8_TIMING_WAVEFORM": {
            "timing_windows": [{"name": "setup"}],
            "timing_constants": [{"name": "clock_to_out"}],
            "clock_mhz": 50.0,
            "clock_domains": [{
                "name": "clk", "freq_mhz": 50.0, "period_ns": 20.0,
                "role": "primary",
            }],
            "clock_and_reset_waveform": {
                "reset": "active low, released synchronously"}},
        "L9_INTEGRATION_SPEC": {
            "top_module": DESIGN,
            "module_role": "A synchronous block intended to be placed as a "
                           "macro by the integrating design.",
            "ports": [
                {"name": "clk", "direction": "input", "width": 1,
                 "description": "Rising-edge clock."},
                {"name": "rst_n", "direction": "input", "width": 1,
                 "description": "Active-low reset."},
                {"name": "dout", "direction": "output", "width": bus_width,
                 "msb": bus_width - 1, "lsb": 0,
                 "description": "Hardened result bus."},
            ],
            "parameters": [{
                "name": "DATA_WIDTH", "default": str(bus_width),
                "description": "Width frozen into the delivered macro.",
            }]},
        # `fields`-nested, the skeleton-emitter's shape.
        "L19_CONSTRAINTS_PDK": {
            "doc_id": "L19",
            "fields": {"floorplan_hints": ["keep clear of the seal ring"]}},
        "L21_POWER_INTENT": {
            "doc_id": "L21",
            "fields": {"power_domains": [{"name": "PD_TOP"}],
                       "isolation_cells": [], "level_shifters": []}},
    }


def build_project(root: Path, packages: Sequence[str] = (SUBJECT, CONTROL),
                  register_rich: bool = True,
                  with_layers: bool = True,
                  bus_width: int = 1) -> Path:
    """A project root on the IP path, carrying `packages` as delivered kits."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "input" / "project.json").write_text(
        json.dumps({"design": DESIGN, "pdk": PDK}), encoding="utf-8")
    template = root / "input" / "submission_template"
    template.mkdir(parents=True, exist_ok=True)
    (template / "NO_TEMPLATE.txt").write_text("cell delivery\n",
                                              encoding="utf-8")

    if with_layers:
        docs = root / "phase1" / "generated_docs"
        docs.mkdir(parents=True, exist_ok=True)
        for stem, body in _layers(register_rich, bus_width).items():
            (docs / f"{stem}.json").write_text(json.dumps(body, indent=2),
                                               encoding="utf-8")

        achieved = root / "reports" / "phase3" / "achievable_fmax.json"
        achieved.parent.mkdir(parents=True, exist_ok=True)
        achieved.write_text(json.dumps({
            "spec_period_ns": 20.0,
            "achievable_period_ns": 12.5,
            "achievable_fmax_mhz": 80.0,
            "worst_setup_slack_ns": 7.5,
            "relaxation_applied": False,
        }, indent=2), encoding="utf-8")

    kit = root / "phase3" / "stage4" / "hardmacro"
    kit.mkdir(parents=True, exist_ok=True)
    for name in packages:
        lef = LEF.format(name=name)
        if bus_width > 1:
            scalar = """  PIN dout
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER met3 ;
        RECT 8.0 1.0 9.0 2.0 ;
    END
  END dout
"""
            assert scalar in lef
            bits = "".join(
                "  PIN dout[{bit}]\n"
                "    DIRECTION OUTPUT ;\n"
                "    USE SIGNAL ;\n"
                "    PORT\n"
                "      LAYER met3 ;\n"
                "        RECT {x}.0 1.0 {x2}.0 2.0 ;\n"
                "    END\n"
                "  END dout[{bit}]\n".format(
                    bit=bit, x=8 + bit * 3, x2=9 + bit * 3)
                for bit in range(bus_width))
            lef = lef.replace(scalar, bits, 1)
        (kit / f"{name}.lef").write_text(lef, encoding="utf-8")
        (kit / f"{name}.lib").write_text(LIB.format(name=name),
                                         encoding="utf-8")
        verilog = VERILOG.format(name=name)
        if bus_width > 1:
            verilog = verilog.replace(
                "output wire dout", f"output wire [{bus_width - 1}:0] dout")
        (kit / f"{name}.v").write_text(verilog, encoding="utf-8")
        (kit / f"{name}.gds").write_bytes(build_gds(name))
    _write_current_kit(root, packages)
    return root


def docs_dir(project: Path, release: str = SUBJECT) -> Path:
    return project / "phase3" / "stage4" / "documentation" / "ip" / release
