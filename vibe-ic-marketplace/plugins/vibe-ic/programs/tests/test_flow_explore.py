import json
import os
from pathlib import Path
import itertools

import pytest

import flow_explore as explorer


@pytest.mark.parametrize("status,area,power,baseline_pass,selected", [
    ("PASS", 80, 2, True, "allow_min_drive"),
    ("PASS", 80, 5, True, "reference"),
    ("PASS", 100, 2, True, "allow_min_drive"),
    ("FAIL", 1, .1, True, "reference"),
    ("NOT_MEASURED", 1, .1, True, "reference"),
    ("PASS", 80, None, True, "reference"),
    ("FAIL", 1, .1, False, None),
])
def test_public_variants_select_by_all_pass_and_declared_objective(
        tmp_path, monkeypatch, status, area, power, baseline_pass, selected):
    if len(os.sched_getaffinity(0)) < 2:
        pytest.skip("Two available CPUs are required to exercise parallel public runs")
    project, output = tmp_path / "project", tmp_path / "exploration"
    (project / "input").mkdir(parents=True)
    source = project / "unit.v"
    source.write_text("module unit; endmodule\n")
    (project / "reports").mkdir()
    (project / "reports/original.txt").write_text("retained source results\n")
    original = {"SYNTH_STRATEGY": "AREA 0"}
    (project / explorer.OVERRIDES).parent.mkdir(parents=True)
    (project / explorer.OVERRIDES).write_text(json.dumps(original))
    (project / "input/case.json").write_text(json.dumps({"status": status,
        "area": area, "power": power, "baseline_pass": baseline_pass}))
    entry = tmp_path / "public.py"
    entry.write_text('''import json, os, sys, time
from pathlib import Path
p=Path(sys.argv[1])
assert sys.argv[2:]==['--route','ip','--ppa-level','0']
assert not (p/'reports/original.txt').exists()
c=json.loads((p/'input/case.json').read_text())
overrides=json.loads((p/'work/flow/native_overrides.json').read_text())
allow='*_1' not in overrides.get('EXTRA_EXCLUDED_CELLS',['*_1'])
(p/'affinity.json').write_text(json.dumps(sorted(os.sched_getaffinity(0))))
started=time.monotonic()
time.sleep(.15 if allow else .02)
status=c['status'] if allow else 'PASS' if c['baseline_pass'] else 'FAIL'
metrics={'design__instance__area':c['area'] if allow else 100,
         'power__total':c['power'] if allow else 3,'timing__setup__ws':2}
(p/'native').mkdir()
(p/'native/config.json').write_text(json.dumps({'CLOCK_PERIOD':10,
    'PDK':'process','STD_CELL_LIBRARY':'cells','STA_CORNERS':['nominal'],
    'EXTRA_EXCLUDED_CELLS':overrides.get('EXTRA_EXCLUDED_CELLS',['*_1'])}))
(p/'reports').mkdir(exist_ok=True)
(p/'reports/flow_engine.json').write_text(json.dumps({'steps':[
    {'name':'native_analysis','status':status,'native_metrics':metrics,
     'native_steps':[{'name':'native_analysis','reports':str(p/'native')}]}]}))
(p/'interval.json').write_text(json.dumps([started,time.monotonic()]))
sys.exit({'PASS':0,'FAIL':1,'NOT_MEASURED':2}[status])
''')
    monkeypatch.setattr(explorer, "ENTRY", entry)

    result = explorer.explore(project, output, cpus=2, jobs=2, ppa_level=1,
                              flow_args=["--route", "ip"])

    assert result["selected"] == selected
    assert len(result["variants"]) == 7
    assert result["ppa_level"] == 1
    observed = [(set(json.loads((Path(row["project"]) / "affinity.json").read_text())),
                 json.loads((Path(row["project"]) / "interval.json").read_text()))
                for row in result["variants"]]
    assert len(set.union(*(cores for cores, _ in observed))) == 2
    assert all(observed[0][1][1] <= interval[0] for _, interval in observed[1:])
    for (a_cores, a), (b_cores, b) in itertools.combinations(observed, 2):
        if a_cores & b_cores:
            assert a[1] <= b[0] or b[1] <= a[0]
    assert any(a[0] < b[1] and b[0] < a[1]
               for (_, a), (_, b) in itertools.combinations(observed[1:], 2))
    adopted = json.loads((project / explorer.OVERRIDES).read_text())
    if selected:
        assert adopted == next(row["overrides"] for row in result["variants"] if row["name"] == selected)
        assert adopted["SYNTH_STRATEGY"] == original["SYNTH_STRATEGY"]
    else:
        assert adopted == original
    assert source.read_text() == "module unit; endmodule\n"
    assert (project / "reports/original.txt").read_text() == "retained source results\n"
    assert sorted(path.name for path in (project / "input").iterdir()) == ["case.json"]
    assert explorer.OVERRIDES.parent == Path("work/flow")
    summary = (output / "RESULT.md").read_text()
    assert all(row["name"] in summary for row in result["variants"])


def test_variants_preserve_other_native_exclusions_and_settings(tmp_path):
    (tmp_path / explorer.OVERRIDES).parent.mkdir(parents=True)
    (tmp_path / explorer.OVERRIDES).write_text(json.dumps({
        "EXTRA_EXCLUDED_CELLS": ["custom*", "*_1"], "FP_CORE_UTIL": 40}))
    variants = dict(explorer.variants(tmp_path))
    from flow_config import native_excluded_cells
    excluded = native_excluded_cells(variants["reference"])
    allowed = variants["allow_min_drive"]["EXTRA_EXCLUDED_CELLS"]
    assert set(excluded) - set(allowed) == {"*_1"}
    assert set(allowed) - set(excluded) == set()
    assert "custom*" in allowed
    assert all(value["FP_CORE_UTIL"] == 40 for value in variants.values())
