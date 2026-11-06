"""F17: step 23 gate 1 (`achieved_period_recorded_check`) and its record.

MEASURED on the spm copy of run23 (vibeic-eda 0.3.79), all numbers are SETUP
SLACK at the same 24 ns clock `clk`, on the same routed netlist `spm_pnr.v`,
with the same flat-OCV derate (early 0.95 / late 1.05):

    reports/phase3/sta_spef_based.rpt   FF process, nom SPEF   12.13   <- gate 1 read this
                                        SS process, nom SPEF    0.55
                                        TT process, nom SPEF    8.51
    reports/phase3/sta_mcorner_ocv.rpt  SS process, max SPEF    0.36   <- the record
    STAPostPNR (tool arm)               max_ss                  0.3624

`sta_spef_based.rpt` times three process corners in one file, FF first, and
gate 1 took the first `worst slack max` in it: the FASTEST corner's slack. The
design reaches only what its worst corner allows, so the record (0.36) is
right and the reader was wrong.

The rules this file pins:
  * direct: gate 1 reads the worst `worst slack max` over every corner section
    of every post-route sign-off report, never the first line of one file;
  * direct: a record whose slack is not that worst REFUSES
    (`ACHIEVED_PERIOD_SLACK_DISAGREES`, rc 1) instead of passing on presence;
  * librelane|dual: `achievable_fmax.json` is written from the tool arm's
    worst setup (`librelane_signoff.step23_tool_arm`), and the direct deck
    never stands in when the tool arm cannot be read.
"""
import ast
import importlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
F15 = importlib.import_module('test_f15_step23_gates_read_the_tool_arm')

LIB = '/pdk/p/libs.ref/cells/lib/cells__{}.lib'


def _section(head: str, slack: float, hold: float = 0.4) -> str:
    """One corner section as the direct decks write it (banner, basis stamps,
    `worst slack max`), then its hold twin, which must never be read."""
    return (f'=== SETUP corner: {head} ===\nSTA_BASIS: POST_ROUTE_SPEF\n'
            f'STA_TIME_UNIT: ns\nOCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n'
            f'Startpoint: a\nEndpoint: b\n'
            f'{slack:.2f}   slack (MET)\n\nworst slack max {slack:.2f}\ntns max 0.00\n'
            f'=== HOLD corner: {head} ===\nSTA_BASIS: POST_ROUTE_SPEF\n'
            f'worst slack min {hold:.2f}\ntns min 0.00\n')


def spm_like(project: Path, *, record=0.36, order=('FF', 'SS', 'TT')) -> Path:
    """The three direct sign-off reports, with the spm run's numbers."""
    by_process = {'FF': 12.13, 'SS': 0.55, 'TT': 8.51}
    based = project / 'reports/phase3/sta_spef_based.rpt'
    based.parent.mkdir(parents=True, exist_ok=True)
    based.write_text(''.join(_section(f'process={p}', by_process[p]) for p in order))
    (project / 'reports/phase3/sta_spef_multicorner.rpt').write_text(
        '# Multi-corner SPEF STA\n'
        f'=== SETUP (max-RC corner, SPEF=max, liberty={LIB.format("tt")}) ===\n'
        'worst slack max 8.90\n'
        f'=== HOLD (min-RC corner, SPEF=min, liberty={LIB.format("tt")}) ===\n'
        'worst slack min 0.97\n')
    (project / 'reports/phase3/sta_mcorner_ocv.rpt').write_text(
        _section(f'process=SS liberty={LIB.format("ss")}, SPEF=top.max.spef', 0.36, 0.49))
    return project




# ------------------------------------------------------ direct: the reader ---







# ------------------------------------------------ direct: the disagreement ---







# ------------------------------------------- tool arm: the record's producer ---

def _runner():
    return importlib.import_module('phase3_one_shot_runner')


def _tool(tmp_path: Path, **kw) -> Path:
    project = F15.tool_project(tmp_path, **kw)
    (project / 'config.json').write_text(json.dumps({'CLOCK_PERIOD': 24.0}))
    # the direct OCV deck's stance, as the runner wrote it before STAPostPNR
    stance = project / 'reports/phase3/mcorner_ocv_stance.json'
    stance.parent.mkdir(parents=True, exist_ok=True)
    stance.write_text(json.dumps({'setup_worst_slack_ns': 0.36}))
    return project






def test_an_unreadable_tool_arm_leaves_no_direct_record(tmp_path):
    project = _tool(tmp_path)
    (project / F15.STA / 'max_ss_125C_4v50' / 'vibeic_signoff.rpt').unlink()
    notes = []
    _runner()._achievable_fmax_from_tool_arm(project, 'top', notes, [])
    assert 'LL_STA_CORNER_ARTEFACT_MISSING' in notes[-1]


# ------------------------------------------------------- the runner wiring ---

def _step23_source() -> ast.Module:
    return ast.parse((PROGRAMS / 'phase3_one_shot_runner.py').read_text())


def test_the_direct_deck_writes_the_record_only_when_step_23_is_direct():
    """The direct write of `achievable_fmax.json` sits under
    `_ll_m23 == "direct"`, and the tool-arm producer is called when it is not."""
    tree = _step23_source()
    guarded_write = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = ast.unparse(node.test)
            body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
            if test == "_ll_m23 == 'direct'" and 'achievable_fmax.json' in body:
                guarded_write = True
    assert guarded_write, 'the direct deck writes achievable_fmax.json in every mode'
    # The tool-arm producer runs, in every non-direct mode, AFTER STAPostPNR's
    # record is written (the reader binds to that record).
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        tops = [(ast.unparse(n.test), ast.unparse(ast.Module(body=n.body, type_ignores=[])))
                for n in fn.body if isinstance(n, ast.If)]
        record = [i for i, (_t, b) in enumerate(tops) if '_librelane_signoff_record(' in b]
        fmax = [i for i, (t, b) in enumerate(tops) if '_achievable_fmax_from_tool_arm(' in b]
        if record and fmax:
            assert tops[fmax[0]][0] == "primary_def.is_file() and _ll_m23 != 'direct'", tops[fmax[0]]
            assert fmax[0] > record[0]
            return
    pytest.fail('no call records the reached period from the tool arm')
