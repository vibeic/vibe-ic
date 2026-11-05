#!/usr/bin/env python3
"""FX_P2 (3a) — a pin Phase 1 harvests from the STAGED RTL top is typed like
every doc-derived pin: `rtl_name` and `aliases`.

MEASURED on subservient (reused serv 1.4.0, 8HD-4, 2026-09-28): phase 2's
final_audit FAILed `l1_pin_table_aliases_typed_check` — "6/15 pin entries miss
typed depth (aliases missing on 6)". The six were exactly the rows whose
`extraction_strategy` is the staged-top harvest (o_sram_waddr, o_sram_wdata,
o_sram_wen, o_sram_raddr, i_sram_rdata, o_sram_ren); the nine doc rows carried
`aliases: []` and `rtl_name`. The gate was right: the producer never wrote the
fields. The row IS the RTL's port declaration, so its RTL name is a measured
fact of the input, and no synonym was read for it.

Driven through the real generators (`gen_l1_datasheet`, `gen_l9_integration_spec`,
the L9->L1 post-emit crosswalk) and the real gate. chip-AGNOSTIC: a synthetic staged top.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase1_doc_one_shot_runner as P1  # noqa: E402

VENDOR_TOP = """
module widget (
  input  wire       clk_i,
  input  wire       rst_ni,
  output wire [8:0] mem_raddr_o,
  output wire       mem_ren_o,
  input  wire [7:0] mem_rdata_i,
  output wire       done_o
);
endmodule
"""

DOC = """# Widget

## Signals

| Signal | Direction | Description |
| --- | --- | --- |
| done_o | output | Completion strobe. |
| clk_i | input | Core clock. |
"""


def _project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "widget_interfaces.md").write_text(DOC)
    (proj / "reports").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": "crypto_accelerator"}))
    vdir = proj / "input" / "vendor_rtl"
    vdir.mkdir(parents=True)
    (vdir / "widget.v").write_text(VENDOR_TOP)
    docs = {f.name: f.read_text()
            for f in (proj / "input" / "docs").iterdir()}
    P1.gen_l1_datasheet(proj, docs)
    P1.gen_l9_integration_spec(proj, docs, {})
    # the post-emit hook that copies L9's ports into L1.pin_table — the rows
    # the gate reads, as the one-shot runner calls it.
    P1._post_emit_crosswalk_l9_ports_to_l1_pin_table_v1_6_555(proj)
    return proj


def _l(proj: Path, name: str) -> dict:
    return json.loads((proj / "phase1" / "generated_docs" / name).read_text())


def test_harvested_pins_carry_rtl_name_and_aliases(tmp_path):
    proj = _project(tmp_path)
    ports = {p["name"]: p for p in _l(proj, "L9_INTEGRATION_SPEC.json")
             ["top_ports"]}
    harvested = [n for n in ("rst_ni", "mem_raddr_o", "mem_ren_o",
                             "mem_rdata_i") if n in ports]
    assert harvested, sorted(ports)
    for n in harvested:
        assert ports[n].get("rtl_name") == n, ports[n]
        assert ports[n].get("aliases") == [], ports[n]


def test_the_alias_gate_accepts_the_l1_this_producer_writes(tmp_path):
    proj = _project(tmp_path)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "l1_pin_table_aliases_typed_check.py"),
         str(proj)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout, r.stdout
