"""A4 producer refusals must remain actionable when no artefact is written."""
from pathlib import Path
import subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import analog_one_shot_runner as runner
from types import SimpleNamespace

def test_a4_missing_result_keeps_producer_stderr(monkeypatch,tmp_path):
    project=tmp_path/'project'; (project/'phase3/analog/vreg_alpha').mkdir(parents=True)
    calls=[]
    def fake_run(argv,**kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv,2,'','PRODUCER_REFUSAL: selected image unavailable')
    monkeypatch.setattr(runner._pr,'run',fake_run)
    args=SimpleNamespace(container='bounded-a4-test',pdk='sky130',allow_deterministic_stubs=False)
    result=runner.step_for_block(project,{'name':'vreg_alpha','type':'ldo'},'A4_corner_sweep',args)
    assert result.status=='PASS_WITH_WAIVERS'
    assert 'PRODUCER_REFUSAL: selected image unavailable' in result.detail
    assert calls
