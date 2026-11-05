"""FX_SPM_DEF_STREAM: what the routed DEF of a core-only block declares, who
rewrites it, and what the Magic stream ships from it.

Three linked defects, measured on the same-RTL spm x gf180mcuD core-only run
(stack33 + N4 + N5, image 0.3.83):

1. N7 -- the routed DEF declared no supply PINS (VDD/VSS lived only in
   SPECIALNETS) while the GDS and the power-aware netlist both carry them as
   ports; the judge's LVS kept exactly one top-level port mismatch. LibreLane
   promotes the PDN straps to pins (`define_pdn_grid -pins`).
2. `drc_feedback_repair` rewrote `routed.def` / `<top>.def` after the router's
   ledger row (PROVENANCE_HASH_MISMATCH) and left the Metal2 keep-out it made
   for its scoped reroute in the DEF it published.
3. The Magic stream read that keep-out as `obsm2` (no `-noblockage`), streamed
   it to the blockage datatype, and the PDK's magic deck counted it as metal
   (M2.3, the one remaining Magic DRC box).

The Tcl the runner and the feedback step generate is EXECUTED here under
tclsh with the EDA commands stubbed; only the tools' file writes are faked.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import drc_feedback_repair as feedback  # noqa: E402
import provenance_output_hash_completeness_check as prov_check  # noqa: E402

from _tcl_walk import walk as _walk  # noqa: E402


def _tclsh(script: str, tmp_path: Path) -> str:
    """Run a Tcl script the way the program runs Tcl: host tclsh, else the
    runner's EDA container, else a NOT_MEASURED FAILURE (`_tcl_walk`), never a
    skip. The script is the walker; it takes no deck."""
    out, err, route = _walk(script, "", tmp_path)
    assert "TCL_DONE" in out, f"Tcl did not finish via {route}:\n{out}\n{err}"
    return out


# --------------------------------------------------------------------------
# 1. N7 -- the core grid promotes its straps to supply pins on a core-only
#    block, and only there.
# --------------------------------------------------------------------------

CELL_LEF = """\
MACRO cellA
  CLASS CORE ;
  SIZE 2 BY 10 ;
  PIN PWR
    USE POWER ;
    PORT
      LAYER lower1 ;
        RECT 0 9.7 2 10.3 ;
    END
  END PWR
  PIN GND
    USE GROUND ;
    PORT
      LAYER lower1 ;
        RECT 0 -0.3 2 0.3 ;
    END
  END GND
END cellA
"""

TECH_LEF = """\
LAYER lower1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.5 ;
  WIDTH 0.2 ;
END lower1
LAYER upperV
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 1.0 ;
  WIDTH 0.4 ;
END upperV
LAYER upperH
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 1.0 ;
  WIDTH 0.4 ;
END upperH
"""

RING = {
    "layers": ["upperV", "upperH"],
    "widths": [0.8, 0.9],
    "spacings": [0.6, 0.7],
    "core_offset_um": 4.0,
    "connect_to_pad_layers": ["padFacing"],
    "connects": [["padFacing", "upperH"]],
    "min_clearance_um": 0.3,
}




# A database stand-in: every command the deck calls that is not modelled is
# absorbed by `unknown`; `define_pdn_grid` records its arguments; the block's
# instances are the ones the test places.
_DB_STUB = r"""
namespace eval ord {}
namespace eval odb {}
set ::grid_calls {}
rename unknown _tcl_unknown
proc unknown {args} { return "" }
proc define_pdn_grid {args} { lappend ::grid_calls $args }
proc ord::get_db_block {} { return blk }
proc blk {m args} {
  switch -- $m {
    getInsts { return $::insts }
    default { return "" }
  }
}
proc inst_core {m args} {
  switch -- $m { getMaster { return m_core } isPlaced { return 1 }
                 getPlacementStatus { return PLACED } default { return "" } }
}
proc inst_pad {m args} {
  switch -- $m { getMaster { return m_pad } isPlaced { return 1 }
                 getPlacementStatus { return FIRM } default { return "" } }
}
proc m_core {m args} {
  switch -- $m { isPad { return 0 } getType { return CORE } default { return "" } }
}
proc m_pad {m args} {
  switch -- $m { isPad { return 1 } getType { return PAD_POWER } default { return "" } }
}
"""










# --------------------------------------------------------------------------
# 3. The Magic stream never ships a DEF routing blockage as mask geometry.
# --------------------------------------------------------------------------



# --------------------------------------------------------------------------
# 2. The feedback reroute removes its own keep-outs and declares its rewrite.
# --------------------------------------------------------------------------

BASE = '''VERSION 5.8 ;
DESIGN unit ;
UNITS DISTANCE MICRONS 1000 ;
NETS 2 ;
  - target ( i Z ) + USE SIGNAL
      + ROUTED Metal1 ( 100000 100000 ) Via1_X ;
  - other ( j A ) + USE SIGNAL
      + ROUTED Metal2 ( 200000 200000 ) ( 201000 * ) ;
END NETS
END DESIGN
'''

# OpenROAD stand-in for the reroute script: an obstruction table the script's
# own create/destroy calls act on, and a `write_def` that records what is
# left in the database so the fake tool can write it into the DEF.
_OR_STUB = r"""
namespace eval ord {}
namespace eval odb {}
set ::obs $::pre_existing
set ::n 0
proc read_lef {args} {}
proc read_def {args} {}
proc set_routing_layers {args} {}
proc global_route {args} {}
proc detailed_route {args} {}
proc check_antennas {args} {}
proc create_obstruction {args} {
  set o "_[incr ::n]_p_odb__dbObstruction"
  lappend ::obs $o
  return $o
}
proc odb::dbObstruction_destroy {o} {
  set i [lsearch -exact $::obs $o]
  set ::obs [lreplace $::obs $i $i]
}
proc odb::dbWire_destroy {w} {}
proc ord::get_db_block {} { return blk }
proc blk {m args} {
  switch -- $m { getObstructions { return $::obs } findNet { return netobj } }
}
proc netobj {m args} { return wireobj }
proc write_def {path} { puts "OBSTRUCTIONS_IN_DB [llength $::obs] $::obs" }
"""


def _run_trial_script(script: Path, tmp_path: Path, pre=()) -> tuple[int, str]:
    out = _tclsh(f"set ::pre_existing {{{' '.join(pre)}}}\n" + _OR_STUB
                 + script.read_text() + "\nputs TCL_DONE\n", tmp_path)
    line = next(ln for ln in out.splitlines()
                if ln.startswith("OBSTRUCTIONS_IN_DB"))
    parts = line.split()
    return int(parts[1]), out


def _rdb(count):
    item = ("<item><category>'CO.6a'</category><values><value>"
            "edge-pair: (99.79,100;99.79,100.01)/(99.80,100;99.80,100.01)"
            "</value></values></item>")
    return ('<report-database><items>' + item * count
            + '</items></report-database>')


def _project(tmp_path: Path) -> tuple[Path, SimpleNamespace]:
    project = tmp_path / 'unit'
    pnr = project / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    (project / 'reports/phase3').mkdir(parents=True)
    (pnr / 'unit.def').write_text(BASE)
    (pnr / 'routed.def').write_text(BASE)
    (pnr / 'pnr.tcl').write_text(
        'set_routing_layers -signal Metal2-Metal5 -clock Metal3-Metal5\n')
    sha = 'sha256:' + hashlib.sha256(BASE.encode()).hexdigest()
    # The router's own ledger row, exactly as the runner writes it.
    (project / 'provenance.jsonl').write_text(json.dumps({
        'record': 'invocation', 'tool': 'openroad', 'version': 'x',
        'version_capture': 'probed', 'command': 'openroad pnr.tcl',
        'exec_route': 'container', 'exit_code': 0, 'duration_ms': 1,
        'duration_s': 0.001, 'measured': True,
        'timestamp': '2026-09-27T19:28:29Z',
        'outputs': {'phase3/stage3/pnr/routed.def': sha,
                    'phase3/stage3/pnr/unit.def': sha}}) + '\n')
    pdk = SimpleNamespace(drc_deck='/pdk/gf180mcu.drc', tech_lef='/pdk/tech.lef',
                          cell_lef='/pdk/cell.lef', macro_lefs=[],
                          cell_gds='/pdk/cell.gds', macro_gds=[],
                          lefdef_layermap='/pdk/map')
    return project, pdk


def _fake_eda(tmp_path: Path, seen: dict):
    """Only the EDA tools' FILE WRITES are faked. The reroute script is run
    under tclsh against the obstruction table, and the DEF the fake writes
    carries a BLOCKAGES row for every keep-out the script left in the db --
    which is what OpenROAD's `write_def` does."""
    def fake(_image, _project, argv, *, env=None):
        if argv[0] == 'klayout' and env is not None:
            Path(env['GDS_OUT']).write_bytes(
                Path(env['DEF']).read_bytes() + b'G' * 2048)
            return SimpleNamespace(returncode=0, stdout='GDS_WRITTEN', stderr='')
        if argv[0] == 'klayout':
            output = Path(next(v.split('=', 1)[1] for v in argv
                               if v.startswith('report=')))
            gds = Path(next(v.split('=', 1)[1] for v in argv
                            if v.startswith('input=')))
            output.write_text(_rdb(0 if b'100200 100000' in gds.read_bytes()
                                   else 1))
            return SimpleNamespace(returncode=0, stdout=(
                'Starting DRC: executing 1 deck(s).\n'
                'Executing deck CO.6a_metal1_eol_overlap from '
                '/pdk/rule_decks/contact.rb\nExecuting rule CO.6a'), stderr='')
        script = Path(argv[-1])
        if script.name == 'pins.tcl':
            return SimpleNamespace(returncode=0, stdout=(
                'FEEDBACK_PIN i/Z 99900 99900 100100 100100\n'), stderr='')
        if script.name == 'antenna.tcl':
            return SimpleNamespace(returncode=0, stdout=(
                '[INFO ANT-0002] Found 0 net violations.\n'
                '[INFO ANT-0001] Found 0 pin violations.\n'), stderr='')
        assert script.name == 'trial.tcl'
        left, _ = _run_trial_script(script, tmp_path)
        seen['obstructions_left'] = left
        out = Path(script.read_text().split('write_def {', 1)[1]
                   .split('}', 1)[0])
        candidate = BASE.replace('100000 100000', '100200 100000')
        if left:
            candidate = candidate.replace(
                'NETS 2 ;',
                f'BLOCKAGES {left} ;\n'
                + '    - LAYER Metal2 RECT ( 99990 99890 ) ( 100210 100110 ) ;\n'
                * left + 'END BLOCKAGES\nNETS 2 ;')
        out.write_text(candidate)
        return SimpleNamespace(returncode=0, stdout=(
            '[INFO DRT-0702] Post-route verification: 0 violation(s).\n'
            '[INFO DRT-0633] Scoped detailed routing: 1 net(s) named, 1 of 1 '
            'other net(s) held fixed (their existing wire is an obstruction '
            'and is not rewritten).\n'
            '[INFO DRT-0634] Scoped detailed routing touched 1 net(s) in the '
            'database and left 1 net(s) byte-identical. Named: target.\n'
            '[INFO DRT-0711] Scoped detailed routing: whole-design violations '
            '0 on entry, 0 on exit (delta +0).\n'
            '[INFO ANT-0002] Found 0 net violations.\n'
            '[INFO ANT-0001] Found 0 pin violations.\n'), stderr='')
    return fake


def test_published_route_carries_no_feedback_keepout(tmp_path, monkeypatch):
    project, pdk = _project(tmp_path)
    seen: dict = {}
    monkeypatch.setattr(feedback, '_docker', _fake_eda(tmp_path, seen))
    result = feedback.run(project, 'unit', pdk, 'sha256:' + '0' * 64,
                          stream_script_text='print("EDA stream")\n')
    assert result['status'] == 'PASS', result
    assert result['initial_source_sha256'] != result['source_sha256']
    pnr = project / 'phase3/stage3/pnr'
    for name in ('unit.def', 'routed.def'):
        text = (pnr / name).read_text()
        assert '100200 100000' in text          # the reroute was published
        assert 'BLOCKAGES' not in text, name    # its keep-out was not
    assert seen['obstructions_left'] == 0


def test_reroute_removes_only_the_keepouts_it_made(tmp_path):
    scratch = tmp_path / 'trial'
    scratch.mkdir()
    project = tmp_path / 'unit'
    (project / 'phase3/stage3/pnr').mkdir(parents=True)
    (project / 'phase3/stage3/pnr/pnr.tcl').write_text(
        'set_routing_layers -signal Metal2-Metal5 -clock Metal3-Metal5\n')
    rule = {'obstruction_layer': 'Metal2'}
    mapped = [{'via_um': (100.0, 100.0), 'net': 'target'},
              {'via_um': (120.0, 100.0), 'net': 'target'}]
    captured = {}

    def fake(_image, _project, argv, *, env=None):
        captured['script'] = Path(argv[-1])
        return SimpleNamespace(returncode=1, stdout='', stderr='stop')

    orig = feedback._docker
    feedback._docker = fake
    try:
        feedback._reroute('img', project, ['/pdk/t.lef'], tmp_path / 'in.def',
                          mapped, rule, scratch, 0.11)
    finally:
        feedback._docker = orig
    left, out = _run_trial_script(captured['script'], tmp_path,
                                  pre=['_design_keepout_p_odb__dbObstruction'])
    assert left == 1, out
    assert 'OBSTRUCTIONS_IN_DB 1 _design_keepout_p_odb__dbObstruction' in out
    assert 'FEEDBACK_OBSTRUCTIONS_REMOVED: 2' in out




def test_cli_publication_is_declared_in_the_ledger(tmp_path, monkeypatch):
    """The program's own CLI publishes by default; its rewrite must carry the
    same ledger declaration the runner's call site writes (review MINOR)."""
    project, pdk = _project(tmp_path)
    seen: dict = {}
    monkeypatch.setattr(feedback, '_docker', _fake_eda(tmp_path, seen))
    # the CLI streams with the run's own script file (no text override)
    (project / 'phase3/stage3/pnr/stream_out.py').write_text('print("EDA stream")\n')
    pdk_json = tmp_path / 'pdk.json'
    pdk_json.write_text(json.dumps(vars(pdk)))
    rc = feedback.main([str(project), '--top', 'unit', '--image',
                        'sha256:' + '0' * 64, '--pdk-json', str(pdk_json)])
    assert rc == 0
    _verdict, findings = prov_check.audit(project)
    bad = [f for f in findings if f.rule == 'PROVENANCE_HASH_MISMATCH']
    assert not bad, [f.detail for f in bad]
    rows = [json.loads(ln) for ln in
            (project / 'provenance.jsonl').read_text().splitlines()]
    newest = [r for r in rows
              if 'phase3/stage3/pnr/routed.def' in (r.get('outputs') or {})][-1]
    assert 'drc_feedback_repair CLI' in newest['command']
    assert newest['inputs'] == {
        str((project / 'phase3/stage3/pnr/unit.def').resolve()):
        'sha256:' + hashlib.sha256(BASE.encode()).hexdigest()}
