"""v1.3.53 R9 — port the phase3 v1.3.46 incremental antenna repair->reroute
loop to the MCP `eda_pnr` tool (the SECONDARY, agentic PnR path).

Background
----------
`phase3_one_shot_runner.py._antenna_repair_tcl` got the incremental antenna loop
in v1.3.46: `repair_antennas <diode> -iterations 1` (NO GRT-0121), the full
`global_route` DROPPED, and an OUTER `check_antennas`->break-on-0->repair->
`detailed_route` loop to a cap, then a final in-session `check_antennas`.

The MCP `eda_pnr` tool (`mcp-eda/src/index.js`) emits its OWN OpenROAD Tcl (it
does NOT delegate to the phase3 runner) and, before v1.3.53, ran a bare
`detailed_route` with NO antenna repair at all — a parity gap. v1.3.53 R9 ports
the loop JS-side as a pure emitter (`src/lib/pnr_antenna.mjs::antennaRepairTcl`)
and wires it into the `enable_detailed_route` path between `detailed_route` and
`write_def`, with the diode master sourced from the PDK config (chip-AGNOSTIC —
never hardcoded in the Tcl-gen logic).

What is tested
--------------
1.  The emitted block (obtained by running the real JS emitter under node) has
    the phase3 loop SHAPE: `-iterations 1` (not 5), no full `global_route`
    COMMAND inside the block (comment lines stripped, mirroring the phase3
    test), the `check_antennas`->break-on-0 convergence gate, and the terminal
    `ANTENNA_POSTROUTE_DONE` marker. The diode cell is a POSITIONAL arg.
2.  The emitted block survives a REAL Tcl parse/eval in tclsh with every tool
    command stubbed (OpenROAD is a Tcl interpreter) and reaches
    ANTENNA_POSTROUTE_DONE — the same fidelity check the phase3 test uses.
3.  No-diode PDK -> the emitter SKIPS (ANTENNA_REPAIR_SKIPPED, no
    repair_antennas), mirroring the phase3 skip-when-no-diode branch.
4.  index.js wires the emitter into the detailed_route path and sources the
    diode master from the PDK config (data), and the sky130 diode master
    matches the phase3 runner's PdkConfig.antenna_diode_cell cell-for-cell
    (provable parity).

chip-AGNOSTIC / PDK-agnostic.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import pytest

import sys
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"
ANTENNA_MJS = MCP_ROOT / "src" / "lib" / "pnr_antenna.mjs"

node = shutil.which("node")
tclsh = shutil.which("tclsh")
needs_node = pytest.mark.skipif(node is None, reason="node not installed")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")

_STUB = 'proc unknown {args} { return "" }\n'
_DIODE = "sky130_fd_sc_hd__diode_2"


def _emit(diode) -> str:
    """Run the REAL JS emitter under node and return the emitted Tcl block."""
    arg = "null" if diode is None else repr(str(diode)).replace("'", '"')
    js = (f"import({str(ANTENNA_MJS)!r}).then(m => "
          f"process.stdout.write(m.antennaRepairTcl({arg})))")
    r = _pr.run([node, "-e", js], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _cmd_lines(block: str) -> str:
    """COMMAND lines only (strip Tcl `#` comment lines) — a doctrine comment
    naming a banned command (e.g. the dropped `global_route`) must never trip a
    command-shape assertion. Mirrors the phase3 test's _cmd_lines."""
    return "\n".join(
        ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))


# ── the emitted-block SHAPE (mirror of the phase3 v1.3.46 test) ──────────────

@needs_node
def test_antenna_block_repair_iterations_is_one_not_five():
    cmds = _cmd_lines(_emit(_DIODE))
    assert "-iterations 1" in cmds
    assert "-iterations 5" not in cmds
    # diode cell is a POSITIONAL arg to repair_antennas
    assert f"repair_antennas {_DIODE} -iterations 1" in cmds


@needs_node
def test_antenna_block_drops_full_global_route():
    """No `global_route` COMMAND inside the antenna block (the full reroute is
    exactly what caused the phase3 ibex ~1900-net timeout). Comments may still
    explain WHY it was dropped, hence the command-line-only scan."""
    cmds = _cmd_lines(_emit(_DIODE))
    assert "global_route" not in cmds
    # incremental dirty-net-only reroute IS present
    assert "detailed_route -verbose 0" in cmds


@needs_node
def test_antenna_block_has_incremental_outer_loop_and_break_on_zero():
    cmds = _cmd_lines(_emit(_DIODE))
    assert "set _ant_cap" in cmds
    assert "for {set _i 0} {$_i < $_ant_cap} {incr _i}" in cmds
    assert "check_antennas" in cmds
    assert "$_nv == 0" in cmds
    assert "break" in cmds
    assert "ANTENNA_POSTROUTE_DONE" in _emit(_DIODE)


@needs_node
def test_antenna_block_skips_when_pdk_has_no_diode():
    block = _emit(None)
    assert "ANTENNA_REPAIR_SKIPPED" in block
    assert "repair_antennas" not in block


@needs_node
@needs_tclsh
def test_antenna_block_parses_and_evaluates_in_tclsh():
    """The emitted block must survive a REAL Tcl parse/eval (OpenROAD is a Tcl
    interpreter). tclsh with every tool command stubbed exercises the identical
    parser; the block must reach ANTENNA_POSTROUTE_DONE with returncode 0."""
    block = _emit(_DIODE)
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "ant.tcl"
        script.write_text(_STUB + block)
        r = _pr.run([tclsh, str(script)], capture_output=True,
                           text=True)
    assert r.returncode == 0, r.stderr
    assert "missing close-bracket" not in r.stderr
    assert "ANTENNA_POSTROUTE_DONE" in r.stdout


# ── index.js wiring + PDK-config-sourced diode + phase3 parity ───────────────

def test_index_js_wires_emitter_into_detailed_route_path():
    src = INDEX_JS.read_text()
    assert 'from "./lib/pnr_antenna.mjs"' in src
    # the emitter is called with the PDK-config diode (data), not a literal
    assert "antennaRepairTcl(cfg.antenna_diode_cell)" in src


def test_index_js_sources_diode_from_pdk_config_not_tcl_logic():
    """The diode master is a per-PDK config field (data), so the Tcl-generation
    logic never hardcodes a cell name — mirrors phase3's PdkConfig field."""
    src = INDEX_JS.read_text()
    assert 'antenna_diode_cell: "sky130_fd_sc_hd__diode_2"' in src
    assert 'antenna_diode_cell: "gf180mcu_fd_sc_mcu7t5v0__antenna"' in src
    # custom PDK: null unless the caller supplies one -> SKIP, never invented
    assert "antenna_diode_cell: customOpts.custom_antenna_diode || null" in src


def _resolve_phase3_runner():
    """Locate the plugin's phase3_one_shot_runner.py whether this mcp-eda tree
    is the plugin-embedded copy (…/plugins/vibe-ic/mcp-eda/) or a repo-root copy
    (mcp-eda/). Returns None if not co-located (isolated checkout) -> skip."""
    cands = [MCP_ROOT.parent / "programs" / "phase3_one_shot_runner.py"]
    for up in Path(__file__).resolve().parents:
        cands.append(up / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                     / "programs" / "phase3_one_shot_runner.py")
        cands.append(up / "plugins" / "vibe-ic" / "programs"
                     / "phase3_one_shot_runner.py")
    for c in cands:
        if c.is_file():
            return c
    return None


def test_sky130_diode_matches_phase3_runner_cell_for_cell():
    """The MCP sky130 diode master must be the SAME cell the phase3 runner uses,
    so both PnR paths repair antennas identically (parity, not drift)."""
    p3 = _resolve_phase3_runner()
    if p3 is None:
        pytest.skip("phase3 runner not co-located in this checkout")
    p3src = p3.read_text()
    m = re.search(r'antenna_diode_cell\s*=\s*"([^"]+)"', p3src)
    assert m, "phase3 runner has no antenna_diode_cell literal"
    phase3_diode = m.group(1)
    assert phase3_diode == _DIODE
    assert f'antenna_diode_cell: "{phase3_diode}"' in INDEX_JS.read_text()
