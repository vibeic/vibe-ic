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


def _layers(register_rich: bool) -> Dict[str, dict]:
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
            "clock_and_reset_waveform": {
                "reset": "active low, released synchronously"}},
        "L9_INTEGRATION_SPEC": {
            "top_module": DESIGN,
            "module_role": "A synchronous block intended to be placed as a "
                           "macro by the integrating design."},
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
                  with_layers: bool = True) -> Path:
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
        for stem, body in _layers(register_rich).items():
            (docs / f"{stem}.json").write_text(json.dumps(body, indent=2),
                                               encoding="utf-8")

    kit = root / "phase3" / "stage4" / "hardmacro"
    kit.mkdir(parents=True, exist_ok=True)
    for name in packages:
        (kit / f"{name}.lef").write_text(LEF.format(name=name),
                                         encoding="utf-8")
        (kit / f"{name}.lib").write_text(LIB.format(name=name),
                                         encoding="utf-8")
        (kit / f"{name}.v").write_text(VERILOG.format(name=name),
                                       encoding="utf-8")
        (kit / f"{name}.gds").write_bytes(build_gds(name))
    return root


def docs_dir(project: Path, release: str = SUBJECT) -> Path:
    return project / "phase3" / "stage4" / "documentation" / "ip" / release
