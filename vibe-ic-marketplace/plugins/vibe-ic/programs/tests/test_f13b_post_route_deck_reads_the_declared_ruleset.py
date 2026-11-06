"""F13b -- the post-route SPEF extraction in pnr.tcl reads the OpenRCX ruleset
the PDK DECLARES, through the reader step 22 uses (F13, v1.25.33).

`_post_route_spef_repair_tcl` globbed `rules.openrcx.*.nom.magic` (then `.nom`,
then IHP's `openrcx/*.nom.magic.rules`) under the PDK root and derived the
sign-off max deck by `string map {.nom. .max.}`. Nothing declares the `.magic`
file: on the 0.3.79 image gf180mcuD declares `rules.openrcx.gf180mcuD.<c>`,
sky130A `.<c>.calibre`, ihp-sg13g2 `openrcx/IHP_rcx_patterns.rules` (F13's
measurements). F13 moved step 22 and the ship repair (`_max_captable_c`) onto
the declaration; this deck -- the SPEF the in-flow sign-off DRV repair sizes
against -- still took the undeclared model.

Now: `step_pnr` resolves `_openrcx_ruleset_declaration(pdk, container)`,
records it beside pnr.tcl (`_write_rcx_declaration_record`), and hands it to
the deck. nom for the measurement, max for the DRV repair (nom, disclosed,
when no max is declared). UNREADABLE, or a declaration without nom, REFUSES:
no extraction and no repair on a substituted model.

chip-AGNOSTIC: fixture PDK `fix`.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))



# Every tool command is a no-op, except the one this file is about.
_STUB = ('proc unknown {args} { return "" }\n'
         'proc extract_parasitics {args} { puts "EXTRACT_WITH: $args" }\n')


















def test_step_pnr_hands_the_deck_the_recorded_declaration():
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("def step_pnr(")
    body = src[i:src.index("\ndef ", i + 10)]
    call = body.index("spef_repair_block = _post_route_spef_repair_tcl(")
    pre = body[:call]
    assert "_prs_rcx_decl = _openrcx_ruleset_declaration(pdk, container)" in pre
    assert "_write_rcx_declaration_record(out_dir, _prs_rcx_decl)" in pre
    assert "rcx_declaration=_prs_rcx_decl" in body[call:call + 800]
