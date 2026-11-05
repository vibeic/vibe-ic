#!/usr/bin/env python3
"""N9 — the shipped routed netlist declares each supply port exactly once.

MEASURED (subservient x gf180mcuD HARDMACRO, image 0.3.83, OpenROAD
26Q3-3002, 2026-09-28): `phase3/stage3/pnr/subservient_pnr.v` named `VDD, VSS`
five times in its module header and declared `inout VDD;` / `inout VSS;` five
times. iverilog: "'VDD' has already been declared in this scope" (rc 8);
yosys: "Duplicate module port `\\VDD'" (rc 1); OpenSTA read it silently, so
the flow shipped it and a judge found it.

ROOT CAUSE, reproduced in the image on a checkpoint of that run: every
`pdngen` creates a temporary BTerm per supply net that has none and destroys
it again when it gets no BPin. The STA top port the creation callback made is
never removed (dbSta.cc inDbBTermDestroy: "sta::NetworkEdit does not support
port removal"), so the next `pdngen` adds a SECOND port of the same name.
Counted: 1, 2, 3 ports after 1, 2, 3 `pdngen` calls; 0 after
`add_global_connection` / `global_connect` / `set_voltage_domain`; 0 from a
fresh process reading the saved ODB (the database holds no such BTerm). The
flow's PDN EM pre-sweep runs the PDN block once per candidate: 5 on
subservient -> 5 copies, 1 on spm -> 1 copy.

chip-, PDK- and vendor-AGNOSTIC: synthetic netlists only.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROG))





# ── the structural rule ───────────────────────────────────────────────────











# ── the flow: the pre-stream gate freezes only a legal netlist ────────────







def test_the_pnr_step_dedupes_where_the_netlist_is_first_written():
    """The hook sits in step_pnr after the routed DEF is confirmed, so every
    consumer between PnR and the pre-stream gate reads a legal netlist."""
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "step_pnr")
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
             and getattr(c.func, "id", None) == "_dedupe_shipped_netlist_ports"]
    assert calls and any(isinstance(a, ast.Constant) and a.value == "pnr"
                         for c in calls for a in c.args)




# ── review wave 7 ─────────────────────────────────────────────────────────


_REL = "phase3/stage3/pnr/dut_pnr.v"














def test_the_prestream_gate_appends_the_unchecked_row():
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "step_prestream_gate")
    made = {t.id for a in ast.walk(fn) if isinstance(a, ast.Assign)
            and isinstance(a.value, ast.Call)
            and getattr(a.value.func, "id", None) == "_netlist_port_decls_row"
            for t in a.targets if isinstance(t, ast.Name)}
    appended = {a.id for c in ast.walk(fn) if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute) and c.func.attr == "append"
                and getattr(c.func.value, "id", None) == "rows"
                for a in c.args if isinstance(a, ast.Name)}
    assert made and made & appended, (made, appended)
