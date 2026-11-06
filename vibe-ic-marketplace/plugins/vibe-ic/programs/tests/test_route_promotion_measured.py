"""A promoted route carries its promoter's OWN measurement, and the antenna
report says which route it measured (cmp3 D15).

THE DEFECT. spm x gf180mcuD (lane fxpad, D11+D7+D1 stack): prestream_gate
failed `antenna` with `antenna check: unmeasured (signoff_spef_repair promoted
a re-routed design over the shipped DEF and no antenna check ran on it)`.
signoff_spef_repair never ran. The marker `routed_base_prerepair.def` was
LibreLane step 32's, written at 01:48:36 BEFORE the direct tail, which then
wrote the shipped `spm.def` (01:54:35) and measured it in-session: `Found 0
net violations` / `Found 0 pin violations`, ANTENNA_POSTROUTE_DONE. The report
read the marker as "a later session replaced the measured route".

THE RULE. Every promoter records WHAT it promoted (sha256) and its own
antenna + unrouted measurement of it (`reports/phase3/route_promotion.json`),
and LibreLane step 32 does not promote a candidate it did not measure. The
antenna report credits the promoter's measurement only when the promoted DEF
is the shipped one byte for byte; a promoted DEF a later routing session
rewrote is described by that session's own check; a promoted-and-shipped
route nobody measured stays UNMEASURED, naming its promoter.
"""
import importlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
R = importlib.import_module('phase3_one_shot_runner')
prr = importlib.import_module('librelane_postroute_repair')
contract = importlib.import_module('librelane_contract')

RECORD = 'reports/phase3/route_promotion.json'


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    return path










# ── red on main ──────────────────────────────────────────────────────────────

















# ── control: green on main and on the fix ────────────────────────────────────



















def test_dual_selecting_pregrt_carries_its_census_into_the_report(tmp_path, monkeypatch):
    """The real dual run_in_chain (t102's harness: real closure, docker runs
    faked). pregrt wins; the report the promotion reads must carry the census
    step's own unrouted metric, or the arm could never be promoted."""
    import test_t102_librelane_postroute_repair as t102
    monkeypatch.setattr(t102.native, 'measure', t102._tool_written_native_scene)
    pre_census = dict(t102._base(4.2, 0.40),
                      repair_metrics={'vibeic__prr__changed': 0,
                                      'vibeic__prr__before__unrouted__count': 0})
    scenario = {'32-postdrt-base': t102._base(4.0, -0.3),
                '32-postdrt-cand01': t102._cand(3.99995, -0.2),
                '32-pregrt-base': pre_census,
                '32-pregrt_postdrt-base': t102._base(4.2, 0.10)}
    project, shim, sdc, route = t102._chain_setup(tmp_path, monkeypatch, scenario)
    pre_state = put(project / 'phase3/librelane/21-route-pregrt/13-fill/state_out.json',
                    {'odb': 'p.odb', 'def': 'p.def'})
    report = prr.run_in_chain(project, mode='dual', image='img', pdk='pdk',
                              pdk_root=tmp_path, sdc=sdc, derate=(0.95, 1.05),
                              route_state=route, route_drc=0, programs_dir=shim,
                              variant_arm=lambda lane, extra: {
                                  'final': pre_state,
                                  'route_drc': [{'run': 'drt-run-0', 'markers': 0}]})
    assert report['selected_arm'] == 'pregrt', report.get('selection')
    assert report['adopted'] is None
    assert report['baseline_repair_metrics']['vibeic__prr__before__unrouted__count'] == 0


# --- review wave 58 (R-0929-STEP32-ADOPT): an unmeasured adoption never ships ----
