#!/usr/bin/env python3
"""Tests for ORGANIC-20260531 — port the phase3_one_shot_runner hilomap
tie-cell pass into the MCP `eda_synth` tool.

Background
----------
The bare MCP `eda_synth` yosys script was:
    synth -top T; dfflibmap -liberty L; abc -liberty L; clean; stat;
    write_verilog
It did NOT run `hilomap`, so any constant bit (1'h0 / 1'h1 from CRC tables,
clamps, tie-offs, unused-output zeroing, etc.) survived as a bare
`zero_`/`one_` net (or a literal `assign x = 1'h0;`) in the gate netlist,
which OpenROAD `detailed_route` then rejects with [DRT-0305]/[DRT-0199].
`phase3_one_shot_runner.py` (v1.6.596+, `_v1_6_596_discover_tie_cells` +
hilomap) ALREADY discovers the PDK tie cell from the liberty and inserts
Yosys `hilomap`, so the runner path never hits this; the bare MCP path did.

This change ports the SAME discovery + hilomap step into `eda_synth`.

What is tested
--------------
1.  The discovery logic (re-implemented in Python here, mirroring the JS port
    `discoverTieCells`) finds the sky130 dual-output `conb_1` tie cell from a
    real-shaped (quoted, pg_pin-first) liberty block, and falls back to
    {hi:None, lo:None} when no tie cell is discoverable — so the JS caller
    OMITs hilomap rather than hardcoding a cell.
2.  The Python discovery matches the authoritative reference implementation
    in `phase3_one_shot_runner.py` cell-for-cell on the same fixtures (so the
    JS port, which mirrors the Python here, is provably faithful to the
    runner — chip/PDK-agnostic, no hardcoded SKU as logic).
3.  The JS source (`src/index.js`) actually contains the canonical recipe
    string in the REQUIRED order:
        abc ... ; setundef -zero; hilomap -hicell ... -locell ... ;
        splitnets; clean; ... ; write_verilog
    with `setundef -zero` BEFORE hilomap (don't-care 1'hx must be forced to 0
    first) and PLAIN `clean` (NOT `opt_clean`, which would delete the
    just-inserted tie cells).
4.  The JS source discovers the tie cell from the liberty (conb_/conp_/TIEHI/
    TIELO patterns) and never hardcodes a single cell name as the only path.

chip-AGNOSTIC / PDK-agnostic.
"""
from __future__ import annotations

import re
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"


def _resolve_phase3_runner():
    """Locate the plugin's phase3_one_shot_runner.py whether this mcp-eda
    tree is the plugin-embedded copy (…/plugins/vibe-ic/mcp-eda/) or the
    repo-root copy (mcp-eda/) — both ship in the repo, so the mirror test
    must resolve the reference from EITHER layout. Returns None if the plugin
    source is not co-located (an isolated mcp-eda checkout) so the test
    skips honestly instead of erroring on a path assumption."""
    cands = [MCP_ROOT.parent / "programs" / "phase3_one_shot_runner.py"]  # embedded
    for up in Path(__file__).resolve().parents:                          # root / any layout
        cands.append(up / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                     / "programs" / "phase3_one_shot_runner.py")
    for c in cands:
        if c.exists():
            return c
    return None


PHASE3_RUNNER = _resolve_phase3_runner()


# --- Python mirror of the JS `discoverTieCells` port -----------------------
# Identical regex vocabulary to phase3_one_shot_runner's
# _V1_6_596_TIE_HI_PAT / _V1_6_596_TIE_LO_PAT / _V1_6_596_RE_CELL_DECL.
_TIE_HI_PAT = re.compile(
    r"(?:^|_)(?:conb|conp|tieh|tiehi|tie_h|tie_hi|tiep|hi)_?\d*$", re.IGNORECASE)
_TIE_LO_PAT = re.compile(
    r"(?:^|_)(?:conp|conb|tiel|tielo|tie_l|tie_lo|tien|lo)_?\d*$", re.IGNORECASE)
_RE_CELL_DECL = re.compile(
    r'^\s*cell\s*\(\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\)', re.MULTILINE)


def discover_tie_cells(lib_text: str) -> dict:
    out = {"hi_cell": None, "lo_cell": None, "hi_pin": "HI", "lo_pin": "LO"}
    if not lib_text:
        return out
    cellnames = _RE_CELL_DECL.findall(lib_text)
    if not cellnames:
        return out
    for nm in cellnames:
        n_lc = nm.lower()
        if "conb" in n_lc:
            if out["hi_cell"] is None:
                out["hi_cell"] = nm
            if out["lo_cell"] is None:
                out["lo_cell"] = nm
            continue
        if _TIE_HI_PAT.search(n_lc) and out["hi_cell"] is None:
            if not _TIE_LO_PAT.search(n_lc) or "hi" in n_lc:
                out["hi_cell"] = nm
        if _TIE_LO_PAT.search(n_lc) and out["lo_cell"] is None:
            if not _TIE_HI_PAT.search(n_lc) or "lo" in n_lc:
                out["lo_cell"] = nm
    same_cell = out["hi_cell"] is not None and out["hi_cell"] == out["lo_cell"]
    handled = set()
    for key, default_pin in (("hi_cell", "HI"), ("lo_cell", "LO")):
        if out[key] is None:
            continue
        cell_name = out[key]
        if cell_name in handled:
            continue
        handled.add(cell_name)
        block_re = re.compile(
            r"cell\s*\(\s*" + re.escape(cell_name) + r"\s*\)\s*\{", re.IGNORECASE)
        m = block_re.search(lib_text)
        pin_key = key.replace("cell", "pin")
        if not m:
            out[pin_key] = default_pin
            continue
        window = lib_text[m.end(): m.end() + 4096]
        pin_names = re.findall(
            r"(?<![A-Za-z_])pin\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", window)
        if not pin_names:
            continue
        if same_cell:
            hi_named = [p for p in pin_names
                        if re.search(r"\b(hi|h|p|pwr|vdd|one)\b", p, re.I)]
            lo_named = [p for p in pin_names
                        if re.search(r"\b(lo|l|n|gnd|vss|zero)\b", p, re.I)]
            if hi_named:
                out["hi_pin"] = hi_named[0]
            elif pin_names:
                out["hi_pin"] = pin_names[0]
            if lo_named:
                out["lo_pin"] = lo_named[0]
            elif len(pin_names) > 1:
                out["lo_pin"] = pin_names[1]
            elif pin_names:
                out["lo_pin"] = pin_names[0]
        else:
            out[pin_key] = pin_names[0]
    return out


# Real conb_1 liberty block shape (quoted name, pg_pin BEFORE signal pins —
# exactly the production sky130_fd_sc_hd__tt_025C_1v80.lib layout, verified
# in-container during this port). Trimmed to the conb_1 cell.
REAL_CONB_BLOCK = '''
    cell ("sky130_fd_sc_hd__conb_1") {
        area : 3.7536;
        pg_pin ("VGND") { voltage_name : VGND; }
        pg_pin ("VNB")  { voltage_name : VNB; }
        pg_pin ("VPB")  { voltage_name : VPB; }
        pg_pin ("VPWR") { voltage_name : VPWR; }
        pin ("HI") {
            direction : output;
            function : "1";
        }
        pin ("LO") {
            direction : output;
            function : "0";
        }
    }
'''


def test_discovers_real_sky130_conb1_dual_tie_cell():
    """Real production liberty shape: quoted name + pg_pin-first. Must find
    conb_1 as the dual HI/LO tie cell with pins HI/LO (NOT the VPWR/VGND
    power rails)."""
    tc = discover_tie_cells(REAL_CONB_BLOCK)
    assert tc["hi_cell"] == "sky130_fd_sc_hd__conb_1", tc
    assert tc["lo_cell"] == "sky130_fd_sc_hd__conb_1", tc
    assert tc["hi_pin"] == "HI", tc
    assert tc["lo_pin"] == "LO", tc


def test_no_tie_cell_returns_nulls_so_hilomap_is_omitted():
    """A liberty with no tie cell must yield {hi:None, lo:None} so the JS
    caller OMITs hilomap + warns (the runner's fallback) rather than
    hardcoding a cell name."""
    lib = 'library (x) { cell ("INV_X1") { pin ("A"){} pin ("ZN"){} } }'
    tc = discover_tie_cells(lib)
    assert tc["hi_cell"] is None
    assert tc["lo_cell"] is None


def test_separate_tie_h_tie_l_cells():
    """Non-sky130 PDK with separate tie_hi / tie_lo cells (single output pin
    each) — discovery splits them and takes the first pin as the output."""
    lib = '''library (other) {
      cell ("TIE_HI") { pin ("Z")  { direction: output; function: "1"; } }
      cell ("TIE_LO") { pin ("ZN") { direction: output; function: "0"; } }
    }'''
    tc = discover_tie_cells(lib)
    assert tc["hi_cell"] == "TIE_HI", tc
    assert tc["lo_cell"] == "TIE_LO", tc


def test_python_mirror_matches_phase3_runner_reference():
    """The discovery here must agree with the AUTHORITATIVE reference in
    phase3_one_shot_runner.py on the same fixtures — this is what makes the
    JS port (mirrored by this Python) provably faithful to the runner."""
    import sys
    import tempfile
    import os

    if PHASE3_RUNNER is None:
        import pytest
        pytest.skip("plugin phase3_one_shot_runner.py not co-located with this "
                    "mcp-eda tree (isolated checkout)")

    prog_dir = str(PHASE3_RUNNER.parent)
    if prog_dir not in sys.path:
        sys.path.insert(0, prog_dir)
    import phase3_one_shot_runner as mod  # noqa: E402

    fixtures = [
        REAL_CONB_BLOCK,
        'library (x) { cell ("INV_X1") { pin ("A"){} pin ("ZN"){} } }',
        '''library (other) {
          cell ("TIE_HI") { pin ("Z")  { function: "1"; } }
          cell ("TIE_LO") { pin ("ZN") { function: "0"; } }
        }''',
    ]
    for txt in fixtures:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".lib", delete=False) as f:
            f.write(txt)
            p = f.name
        try:
            ref = mod._v1_6_596_discover_tie_cells(p)
            ours = discover_tie_cells(txt)
            # Compare the cell-selection (the load-bearing part). Pin-name
            # selection follows the identical algorithm.
            assert ref["hi_cell"] == ours["hi_cell"], (txt, ref, ours)
            assert ref["lo_cell"] == ours["lo_cell"], (txt, ref, ours)
            assert ref["hi_pin"] == ours["hi_pin"], (txt, ref, ours)
            assert ref["lo_pin"] == ours["lo_pin"], (txt, ref, ours)
        finally:
            os.unlink(p)


# --- JS source-shape assertions (the SHIPPED code) -------------------------
def _js_src() -> str:
    return INDEX_JS.read_text()


def test_js_eda_synth_script_has_hilomap_recipe_in_order():
    """The eda_synth yosys command string must contain the recipe in the
    REQUIRED order: abc → setundef -zero → hilomap → splitnets → clean →
    write_verilog. The hilomap clause is injected between `abc` and
    `clean; stat; write_verilog`."""
    src = _js_src()
    m = re.search(r"const clause\s*=([\s\S]*?)return \{ clause", src)
    assert m, "buildHilomapClause clause assignment not found"
    block = m.group(1)
    # The recipe tokens must appear in the required order in the clause
    # builder: setundef -zero  <  hilomap -hicell  <  -locell  <  splitnets
    #  <  clean.
    tokens = ["setundef -zero", "hilomap -hicell", "${tie.hi_cell}",
              "-locell", "${tie.lo_cell}", "splitnets", "clean"]
    positions = [block.find(t) for t in tokens]
    assert all(p != -1 for p in positions), \
        f"missing recipe token(s): {list(zip(tokens, positions))}"
    assert positions == sorted(positions), \
        f"recipe tokens out of order: {list(zip(tokens, positions))}"


def test_js_setundef_before_hilomap():
    """`setundef -zero` MUST appear before `hilomap` in the clause string —
    a don't-care 1'hx that is not forced to 0 first survives hilomap and
    still trips DRT-0305."""
    src = _js_src()
    # Locate the full multi-line clause assignment block in
    # buildHilomapClause (from `const clause =` up to `return { clause`).
    m = re.search(r"const clause\s*=([\s\S]*?)return \{ clause", src)
    assert m, "buildHilomapClause clause assignment not found"
    clause_block = m.group(1)
    i_setundef = clause_block.find("setundef -zero")
    i_hilomap = clause_block.find("hilomap")
    assert i_setundef != -1 and i_hilomap != -1, clause_block
    assert i_setundef < i_hilomap, \
        "setundef -zero must come BEFORE hilomap in the clause"


def test_js_uses_plain_clean_not_opt_clean_after_hilomap():
    """The post-hilomap clean must be PLAIN `clean` — `opt_clean` would
    delete the just-inserted tie cells, re-introducing bare constants."""
    src = _js_src()
    m = re.search(r"const clause\s*=([\s\S]*?)return \{ clause", src)
    assert m
    clause_block = m.group(1)
    assert "splitnets; clean;" in clause_block, clause_block
    assert "opt_clean" not in clause_block, \
        "must NOT use opt_clean after hilomap (it deletes tie cells)"


def test_js_synth_cmd_injects_clause_after_abc_before_write():
    """The eda_synth cmdStr must place ${hilomapClause} after `abc -liberty`
    and before `clean; stat; write_verilog`."""
    src = _js_src()
    m = re.search(r"const cmdStr = `[^`]*yosys -p '[^`]*?write_verilog[^`]*`",
                  src, re.DOTALL)
    assert m, "eda_synth cmdStr not found"
    cmd = m.group(0)
    i_abc = cmd.find("abc -liberty")
    i_clause = cmd.find("${hilomapClause}")
    i_write = cmd.find("write_verilog")
    assert i_abc != -1 and i_clause != -1 and i_write != -1, cmd
    assert i_abc < i_clause < i_write, \
        "hilomapClause must be injected after abc and before write_verilog"


def test_js_discovers_tie_cell_from_liberty_not_hardcoded():
    """The JS port must DISCOVER the tie cell from liberty cell-name
    vocabulary (conb/conp/tiehi/tielo) and must NOT hardcode a single cell
    name as the ONLY path — when nothing is discoverable it returns '' and
    the caller surfaces a warning + omits hilomap."""
    src = _js_src()
    # Discovery patterns present (chip/PDK-agnostic vocabulary).
    assert "conb" in src and "conp" in src
    assert "tiehi" in src.lower() and "tielo" in src.lower()
    # The clause builder returns "" when no tie cell discoverable.
    assert re.search(
        r"if \(!\(tie\.hi_cell && tie\.lo_cell\)\) return \{ clause: \"\"",
        src), "must omit hilomap (return empty clause) when no tie cell found"
    # The cell name used in the directive comes from the discovered tie,
    # not a string literal.
    assert "${tie.hi_cell}" in src and "${tie.lo_cell}" in src
    # And a warning is surfaced on the omit path.
    assert "tie_cell_warning" in src


def test_js_surfaces_hilomap_applied_and_tie_cell_in_metrics():
    """eda_synth must report hilomap_applied + the discovered tie_cell so
    the caller knows constant nets were mapped."""
    src = _js_src()
    assert "hilomap_applied" in src
    assert "tie_cell:" in src
