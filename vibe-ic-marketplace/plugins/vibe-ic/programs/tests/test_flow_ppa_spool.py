import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import flow_ppa_spool as spool


@pytest.mark.parametrize("native_exit", [0, 2])
def test_self_contained_trial_returns_native_failure_and_relocates_views(tmp_path, native_exit):
    project = tmp_path / "inputs"
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    (docs / "requirements.md").write_text("Synchronous counter macro.\n")
    outbox, results = tmp_path / "jobs", tmp_path / "returned"
    job = spool.publish(project, outbox, ("candidate", {}), cpus=2,
                        flow_args=["--route", "ip"], level=2, image="local/eda:unit")
    folder = outbox / job
    assert not list(outbox.glob(".*"))
    spec = json.loads((folder / "job.json").read_text())
    assert spec == {"cpus": 2, "label": "Native PPA trial candidate", "container": job,
                    "priority": 0, "keep_run": False}
    subprocess.run(["bash", "-n", str(folder / "run.sh")], check=True)
    entry = folder / "plugin/programs/vibe_ic_one_shot_runner.py"
    entry.write_text('''import json,sys
from pathlib import Path
project=Path(sys.argv[1])
reports=project/'reports';reports.mkdir()
step=project/'steps/native_mapping';step.mkdir(parents=True)
view=step/'unit.odb';view.write_text('neutral native view')
(step/'config.json').write_text(json.dumps({'CLOCK_PERIOD':10,'PDK':'process',
 'STD_CELL_LIBRARY':'cells','STA_CORNERS':['typical']}))
(step/'state_out.json').write_text(json.dumps({'odb':str(view)}))
(step/'state_out.json').chmod(0o444)
report={'steps':[{'name':'native_mapping','status':STATUS,
 'native_metrics':{'design__instance__area':100,'power__total':1,'timing__setup__ws':2},
 'native_steps':[{'name':'Yosys.Synthesis','ran':True,'exit_code':CODE,'reports':str(step)}]}]}
(reports/'flow_engine.json').write_text(json.dumps(report))
sys.exit(CODE)
'''.replace("STATUS", repr("PASS" if native_exit == 0 else "FAIL")).replace("CODE", str(native_exit)))
    env = {**os.environ, "VIBEIC_TMP": str(tmp_path / "scratch"), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, str(folder / "plugin/programs/flow_ppa_spool.py"), "worker"]
    run = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True)
    assert run.returncode == native_exit, run.stderr
    spool.finish(folder, run.returncode)
    returned = results / job
    returned.mkdir(parents=True)
    shutil.copyfile(folder / "metrics.json", returned / "metrics.json")
    shutil.copytree(folder / "reports", returned / "reports")
    (returned / "exit-code.txt").write_text(str(run.returncode))
    payload = returned / "reports/project.tar.gz"
    complete = payload.read_bytes()
    payload.write_bytes(complete[:len(complete) // 2])
    output = tmp_path / "candidate"
    assert spool.collect(job, results, output) is None
    assert not output.exists()
    payload.write_bytes(complete)
    row = spool.collect(job, results, output)
    assert row["exit_code"] == native_exit
    assert row["all_pass"] == (native_exit == 0)
    assert row["metrics"]["power__total"] == 1
    assert row["cpu_seconds"] > 0
    assert row["project"] == str(output)
    state = json.loads((output / "steps/native_mapping/state_out.json").read_text())
    assert Path(state["odb"]).read_text() == "neutral native view"
    assert str(folder) not in state["odb"]


def test_container_launch_failure_stays_unmeasured(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({
        "name": "reference", "overrides": {}, "ppa_level": 2}))
    spool.finish(tmp_path, 125)
    row = json.loads((tmp_path / "metrics.json").read_text())
    assert row["exit_code"] == 125 and row["all_pass"] is False
    assert row["state"] == "NOT_MEASURED" and row["metrics"] == {}
