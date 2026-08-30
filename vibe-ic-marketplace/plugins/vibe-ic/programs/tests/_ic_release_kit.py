#!/usr/bin/env python3
"""_ic_release_kit.py — a project on the CHIP path, for the step-37.5ic doc tests.

WHAT IT BUILDS
==============
A project root carrying every artefact class step 37.5ic's product-document
producer and gate read:

    input/project.json                          the design identity
    input/submission_template/SELF_TAPEOUT.txt  the chip-path router file
    phase1/generated_docs/L*.json               the design INPUT layers
    phase3/stage4/gds/<name>.gds                the sign-off layout
    phase3/stage3/pnr/routed.def                the placed and routed die
    phase3/analog/hardmacro/<m>/<m>.lef         one placed macro abstract
    phase3/final/metrics.json                   the 17 sign-off properties
    reports/phase3/sta/post_route_summary.json  post-route timing
    reports/phase3/power.json                   the power estimate
    reports/phase3/drc_signoff.json             the DRC sign-off record
    reports/phase3/lvs_verdict.json             the LVS verdict record

TWO RELEASES BY DEFAULT, AND THE SECOND IS THE CONTROL
======================================================
Every falsification breaks ONE artefact of ONE release and leaves the second
release untouched, in the SAME project, judged in the SAME invocation. A
refusal that also reddens the untouched release is environmental, not
content-earned; a control that stays green is what distinguishes the two.

The two releases are two sign-off GDS streams — that is what a release IS on
the chip path, and it is what `_ic_release_artefacts.releases()` derives the
document directories from.

THE BYTES ARE WRITTEN HERE, not by any helper the programs under test share.
The test and the program must reach the same reading from two independent
directions; a builder shared with the code under test would make them agree by
construction.

chip-AGNOSTIC: no design, vendor, foundry, process-node, SKU or protocol name
appears anywhere below. The PDK string is an OPEN PDK this flow already targets.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Dict, Sequence

#: The release every defect is injected into.
SUBJECT = "die_a"
#: The release no test ever touches. Its verdict is the control.
CONTROL = "die_b"

DESIGN = "widget"
PDK = "gf180mcuD"
MACRO = "block_m"

#: Three signal pins and two supply pins, so signal / supply / total are three
#: DISTINCT numbers (3, 2, 5). Equal numbers would let an arithmetic bug pass.
DEF_OK = """VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN {design} ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 240000 160000 ) ;
COMPONENTS 4 ;
    - u0 INVX1 + PLACED ( 1000 1000 ) N ;
    - u1 INVX1 + PLACED ( 3000 1000 ) N ;
    - u2 DFFX1 + PLACED ( 5000 1000 ) N ;
    - u3 NAND2X1 + PLACED ( 7000 1000 ) N ;
END COMPONENTS
PINS 5 ;
    - clk + NET clk + DIRECTION INPUT + USE SIGNAL
      + PORT
        + LAYER met2 ( -200 -200 ) ( 200 200 )
        + PLACED ( 200 80000 ) N ;
    - rst_n + NET rst_n + DIRECTION INPUT + USE SIGNAL
      + PORT
        + LAYER met2 ( -200 -200 ) ( 200 200 )
        + PLACED ( 200 84000 ) N ;
    - dout + NET dout + DIRECTION OUTPUT + USE SIGNAL
      + PORT
        + LAYER met2 ( -200 -200 ) ( 200 200 )
        + PLACED ( 239800 80000 ) N ;
    - vpwr + NET vpwr + DIRECTION INOUT + USE POWER
      + PORT
        + LAYER met3 ( -200 -200 ) ( 200 200 )
        + PLACED ( 120000 159000 ) N ;
    - vgnd + NET vgnd + DIRECTION INOUT + USE GROUND
      + PORT
        + LAYER met3 ( -200 -200 ) ( 200 200 )
        + PLACED ( 120000 1000 ) N ;
END PINS
END DESIGN
"""

#: The gate-level netlist the ROUTE produced — a SECOND view of the same
#: interface. The gate re-derives the signal pin count from this, never from
#: the DEF the document was written off, so a hand-edited count disagrees with
#: the tree instead of being believed. Supplies are `supply0`/`supply1` nets,
#: the convention `digital_hardmacro_check` states and accepts.
PNR_NETLIST = """// Gate-level netlist, post-route.
module {design} (
    input  wire clk,
    input  wire rst_n,
    output wire dout
);
    supply1 vpwr;
    supply0 vgnd;
    wire n1;
    INVX1  u0 (.A(clk),  .Y(n1));
    INVX1  u1 (.A(n1),   .Y(dout));
endmodule
"""

MACRO_LEF = """VERSION 5.8 ;
BUSBITCHARS "[]" ;
MACRO {macro}
  CLASS BLOCK ;
  ORIGIN 0 0 ;
  SIZE 60.000 BY 40.000 ;
  PIN a
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER met3 ;
        RECT 1.0 1.0 2.0 2.0 ;
    END
  END a
  PIN y
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER met3 ;
        RECT 8.0 1.0 9.0 2.0 ;
    END
  END y
  PIN VPWR
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER met4 ;
        RECT 0.0 0.0 60.0 2.0 ;
    END
  END VPWR
END {macro}
END LIBRARY
"""

#: Every one of the 17 properties `tapeout_docs_gen.release_blockers` decides,
#: clean. The metrics half of the deliverability question is therefore GREEN in
#: the control fixture — which is what makes the artefact-substance refusals
#: below provably NOT the metrics half firing.
METRICS_CLEAN = {
    "design__die__bbox": "0 0 240.0 160.0",
    "design__instance__utilization": 0.42,
    "design__instance__utilization__stdcell": 0.38,
    "power__total": 0.0121,
    "route__drc_errors": 0,
    "magic__drc_error__count": 0,
    "klayout__drc_error__count": 0,
    "klayout__density_error__count": 0,
    "antenna__violating__nets": 0,
    "antenna__violating__pins": 0,
    "design__lvs_error__count": 0,
    "design__lvs_unmatched_device__count": 0,
    "design__lvs_unmatched_net__count": 0,
    "design__lvs_unmatched_pin__count": 0,
    "design__xor_difference__count": 0,
    "timing__setup__ws": 0.42,
    "timing__setup__tns": 0.0,
    "timing__hold__ws": 0.08,
    "timing__hold__tns": 0.0,
    "design__max_slew_violation__count": 0,
    "design__max_cap_violation__count": 0,
    "timing__setup__ws__corner:tt": 0.42,
    "timing__hold__ws__corner:tt": 0.08,
}

STA_SUMMARY = {
    "program": "sta_report_check",
    "passed": True,
    "summary": {
        "worst_setup_slack_ns": 0.42,
        "worst_hold_slack_ns": 0.08,
        "setup_tns_ns": 0.0,
        "corners": [
            {"corner": "tt", "setup_slack_ns": 0.42, "hold_slack_ns": 0.08}],
    },
}

POWER_REPORT = {
    "program": "eda_report_audit:power",
    "passed": True,
    "summary": {"total_power_w": 0.0121,
                "internal_power_w": 0.0061,
                "switching_power_w": 0.0048,
                "leakage_power_w": 0.0012},
}

DRC_SIGNOFF = {
    "program": "drc_report_check",
    "passed": True,
    "verdict": "PASS",
    "findings": [],
    "summary": {"files_found": 2, "checked": True,
                "determined_files": 2, "real_violation_total": 0,
                "terminal_verdict": "CLEAN"},
}

LVS_VERDICT = {
    "program": "lvs_report_check",
    "status": "PASS",
    "passed": True,
    "summary": {"unmatched_nets": 0, "unmatched_devices": 0},
}


def _rec(tag: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HH", 4 + len(payload), tag) + payload


def _ascii(text: str) -> bytes:
    raw = text.encode("ascii")
    return raw + (b"\x00" if len(raw) % 2 else b"")


def _real8(value: float) -> bytes:
    """One GDSII 8-byte real: excess-64 base-16 exponent, 7-byte mantissa.

    NOT an IEEE double — `struct.pack(">d", ...)` yields a UNITS record whose
    scale decodes 262144x wrong, a fixture bug that reads like a real defect.
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


def build_gds(name: str, width_um: float = 240.0,
              height_um: float = 160.0) -> bytes:
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


def build_gds_without_geometry(name: str) -> bytes:
    """A well-formed GDSII library with a structure and NOT ONE SHAPE in it.

    THE DEFECT THIS WHOLE LANDING EXISTS FOR, and it is deliberately not
    truncation or garbage: every record is legal, the file opens, the structure
    is named, `os.path.getsize` is comfortably non-zero, and there is no
    geometry. Every existence check ever written passes over these bytes.
    """
    stamp = struct.pack(">12h", *([2026, 1, 1, 0, 0, 0] * 2))
    out = _rec(0x0002, struct.pack(">h", 600))
    out += _rec(0x0102, stamp)
    out += _rec(0x0206, _ascii("LIB"))
    out += _rec(0x0305, _real8(1e-3) + _real8(1e-9))
    out += _rec(0x0502, stamp)
    out += _rec(0x0606, _ascii(name))
    out += _rec(0x0700)                                        # ENDSTR
    out += _rec(0x0400)                                        # ENDLIB
    return out


def _layers(register_rich: bool) -> Dict[str, dict]:
    """The Phase-1 design INPUT, in BOTH shapes the corpus ships.

    The extracted layers put their content at the top level and the
    skeleton-emitted ones nest it under `fields`. A reader that understands one
    shape reports a false NOT_MEASURED over a document that states the answer.
    """
    regmap = {"doc_class": "regmap", "registers": [],
              "base_address": "0x0000; offsets are relative to the base."}
    regmap["register_groups"] = (
        [{"group": "Control", "fields": ["enable", "mode"]}]
        if register_rich else [])
    if register_rich:
        regmap["registers"] = [{"name": "CTRL", "offset": "0x00"}]
    return {
        "L1_DATASHEET": {
            "doc_class": "datasheet", "ic_name": DESIGN,
            "description": "A synchronous block delivered as a packaged die."},
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
            "module_role": "A synchronous block intended to be operated as a "
                           "standalone packaged part."},
        "L19_CONSTRAINTS_PDK": {
            "doc_id": "L19",
            "fields": {"floorplan_hints": ["keep clear of the seal ring"]}},
        "L21_POWER_INTENT": {
            "doc_id": "L21",
            "fields": {"power_domains": [{"name": "PD_TOP"}],
                       "isolation_cells": [], "level_shifters": []}},
    }


def build_project(root: Path, releases: Sequence[str] = (SUBJECT, CONTROL),
                  register_rich: bool = True,
                  with_layers: bool = True,
                  with_macro: bool = True) -> Path:
    """A project root on the chip path, carrying `releases` as sign-off GDS."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "input" / "project.json").write_text(
        json.dumps({"design": DESIGN, "pdk": PDK}), encoding="utf-8")
    template = root / "input" / "submission_template"
    template.mkdir(parents=True, exist_ok=True)
    (template / "SELF_TAPEOUT.txt").write_text("self tape-out\n",
                                               encoding="utf-8")

    if with_layers:
        docs = root / "phase1" / "generated_docs"
        docs.mkdir(parents=True, exist_ok=True)
        for stem, body in _layers(register_rich).items():
            (docs / f"{stem}.json").write_text(json.dumps(body, indent=2),
                                               encoding="utf-8")

    gds_dir = root / "phase3" / "stage4" / "gds"
    gds_dir.mkdir(parents=True, exist_ok=True)
    for name in releases:
        (gds_dir / f"{name}.gds").write_bytes(build_gds(name))

    pnr = root / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text(DEF_OK.format(design=DESIGN),
                                    encoding="utf-8")
    (pnr / f"{DESIGN}_pnr.v").write_text(PNR_NETLIST.format(design=DESIGN),
                                         encoding="utf-8")

    if with_macro:
        macro_dir = root / "phase3" / "analog" / "hardmacro" / MACRO
        macro_dir.mkdir(parents=True, exist_ok=True)
        (macro_dir / f"{MACRO}.lef").write_text(MACRO_LEF.format(macro=MACRO),
                                                encoding="utf-8")

    final = root / "phase3" / "final"
    final.mkdir(parents=True, exist_ok=True)
    (final / "metrics.json").write_text(json.dumps(METRICS_CLEAN, indent=2),
                                        encoding="utf-8")

    rep = root / "reports" / "phase3"
    (rep / "sta").mkdir(parents=True, exist_ok=True)
    (rep / "sta" / "post_route_summary.json").write_text(
        json.dumps(STA_SUMMARY, indent=2), encoding="utf-8")
    (rep / "power.json").write_text(json.dumps(POWER_REPORT, indent=2),
                                    encoding="utf-8")
    (rep / "drc_signoff.json").write_text(json.dumps(DRC_SIGNOFF, indent=2),
                                          encoding="utf-8")
    (rep / "lvs_verdict.json").write_text(json.dumps(LVS_VERDICT, indent=2),
                                          encoding="utf-8")
    return root


def docs_dir(project: Path, release: str = SUBJECT) -> Path:
    return project / "phase3" / "stage4" / "documentation" / "ic" / release
