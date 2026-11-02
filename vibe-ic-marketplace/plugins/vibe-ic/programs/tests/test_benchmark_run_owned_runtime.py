"""Neutral lifecycle controls. No benchmark data, simulator, or scorer is used."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = (Path(os.environ["ISSUE3789_SOURCE_ROOT"]) if os.environ.get("ISSUE3789_SOURCE_ROOT")
        else Path(__file__).resolve().parents[5])
PROGRAMS = REPO / "vibe-ic-marketplace/plugins/vibe-ic/programs"
sys.path[:0] = [str(PROGRAMS), str(PROGRAMS.parent / "benchmark")]
import benchmark_dispatch as bd

DIGEST = "sha256:" + "a1" * 32
IMAGE_ID = "sha256:" + "b2" * 32
IMAGE = "example.invalid/eda@" + DIGEST


@pytest.fixture
def native(monkeypatch):
    monkeypatch.delenv("VIBEIC_EDA_CONTAINER", raising=False)
    monkeypatch.delenv("VIBEIC_LIBRELANE_LOCAL_ATTESTATION", raising=False)
    monkeypatch.setattr(bd._challenge_exec, "no_container_route", lambda: False)
    pin = bd._runtime_pair._pin
    monkeypatch.setattr(pin, "resolved_image_digest", lambda *a, **k: DIGEST)
    monkeypatch.setattr(pin, "pinned_image_present", lambda env=None: (IMAGE, ""))
    monkeypatch.setattr(pin, "container_pin_state", lambda *a, **k: ("MATCH", ""))
    monkeypatch.setattr(pin, "container_image_id", lambda name: (IMAGE_ID, ""))
    monkeypatch.setattr(pin, "container_image_digest", lambda name: (DIGEST, ""))
    monkeypatch.setattr(pin, "container_image_reference", lambda name: (IMAGE, ""))
    monkeypatch.setattr(pin, "image_repo", lambda env=None: "example.invalid/eda")
    monkeypatch.setattr(bd._challenge_exec, "container_id", lambda name: "c3" * 32)
    supplied = []

    def helper(argv, **kwargs):
        assert argv[0] == "bash" and Path(argv[1]).name == "restart-eda.sh", argv
        assert argv[2] == IMAGE
        env = kwargs["env"]
        assert env["ENSURE_ONLY"] == "1" and env["PULL"] == "0"
        assert env["SOURCE_CONTAINER"] == "vibeic-eda"
        supplied.append(env["NAME"])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(bd.subprocess, "run", helper)
    return supplied


def test_ordinary_fresh_solve_supplies_two_independent_runtimes(tmp_path, monkeypatch, native):
    import benchmark_entry_surface_check as bes
    monkeypatch.setattr(bes, "audit", lambda *a: {"verdict": "PASS"})
    monkeypatch.setattr(bd, "_dispatch_format", lambda *a: "neutral")
    monkeypatch.setattr(bd, "_completeness_adapters", lambda: {})
    selected = []

    class BeforeDesignWork(Exception):
        pass

    def prepared(*args):
        raise BeforeDesignWork

    monkeypatch.setattr(bd, "_prepare_general_solve_run", prepared)
    real_gate = bd._runtime_pair_gate

    def gate(*a, **k):
        rc, record = real_gate(*a, **k)
        assert rc is None, record
        selected.append(record["container"])
        return rc, record

    monkeypatch.setattr(bd, "_runtime_pair_gate", gate)
    for run in (tmp_path / "a", tmp_path / "b"):
        with pytest.raises(BeforeDesignWork):
            bd._cmd_solve_locked("neutral", str(tmp_path), str(run))
        assert not run.exists()  # Supply precedes design staging and fan-out.
    assert len(native) == 2 and selected == native
    assert selected[0] != selected[1]


def test_fresh_name_is_stable_and_recorded_resume_does_not_supply(tmp_path, native):
    first = bd._runtime_pair_gate(tmp_path, "solve", pristine=True)[1]
    second = bd._runtime_pair_gate(tmp_path, "solve", pristine=True)[1]
    assert first["container"] == second["container"] and len(native) == 2
    bd._write_runtime_pair_record(tmp_path, first)
    assert bd._runtime_pair_gate(tmp_path, "resume:retry")[1]["container"] == first["container"]
    assert len(native) == 2


def test_preproof_retries_keep_selected_runtime_after_absence(tmp_path, monkeypatch, native):
    first = bd._runtime_pair_gate(tmp_path, "solve", pristine=True)[1]
    selected = first["container"]
    bd._write_runtime_pair_record(tmp_path, first)
    pin = bd._runtime_pair._pin
    monkeypatch.setattr(pin, "container_pin_state", lambda name, env=None:
                        ("UNREADABLE", "CONTAINER_ABSENT: " + name) if name == selected else ("MATCH", ""))
    for _ in range(3):
        rc, pair = bd._runtime_pair_gate(tmp_path, "resume:ai-route")
        assert rc == 2 and pair["container"] == selected, pair
        argv = bd._solver_argv(Path("/unused/vibe_ic_one_shot_runner.py"),
                               tmp_path / "projects/neutral", "D1", "1")
        assert argv[argv.index("--container") + 1] == selected
    assert len(native) == 1
    assert not bd._native_challenge_identity_path(tmp_path).exists()


def test_explicit_selection_does_not_supply(tmp_path, monkeypatch, native):
    monkeypatch.setenv("VIBEIC_EDA_CONTAINER", "operator-runtime")
    rc, pair = bd._runtime_pair_gate(tmp_path, "solve", pristine=True)
    assert rc is None and pair["container"] == "operator-runtime"
    assert native == []


def test_source_reference_is_not_recomposed_from_configured_repository(tmp_path, monkeypatch, native):
    monkeypatch.setattr(bd._runtime_pair._pin, "image_repo", lambda env=None: "another.invalid/eda")
    assert bd._runtime_pair_gate(tmp_path, "solve", pristine=True)[0] is None
    assert len(native) == 1


def test_helper_refusal_launches_no_design_work(tmp_path, monkeypatch, native):
    monkeypatch.setattr(bd.subprocess, "run", lambda argv, **kw:
                        subprocess.CompletedProcess(argv, 3, "", "incompatible source mounts"))
    rc, record = bd._runtime_pair_gate(tmp_path / "run", "solve", pristine=True)
    assert rc == 2 and record["workers_launched"] == 0
    assert record["evidence"] == ["incompatible source mounts"]
    assert not (tmp_path / "run").exists()


def test_unusable_native_binary_probe_remains_refused(tmp_path, monkeypatch, native):
    source = "module neutral; initial $finish; endmodule\n"
    test = tmp_path / "neutral.sv"
    test.write_text(source)
    project = tmp_path / "project"
    rtl = project / "phase2/stage1/rtl/neutral.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module neutral; endmodule\n")
    completion = bd._candidate_text([rtl])
    candidate = bd._archive_candidate("neutral", project, {"completion": completion}, tmp_path, "PROGRAM")
    declaration = {"backend": "native", "container": "run-a", "container_id": "c3" * 32,
                   "image_id": IMAGE_ID, "image_digest": DIGEST}
    monkeypatch.setattr(bd._progress_run, "run", lambda argv, **kw:
                        subprocess.CompletedProcess(argv, 0, "[]", ""))
    monkeypatch.setattr(bd._challenge_exec, "run_in_container_supervised", lambda name, command, **kw:
                        subprocess.CompletedProcess(command, 127, "", "unusable binary"))
    result = bd._run_verification_challenge(candidate, {"path": str(test),
        "sha256": bd._sha256_text(source), "execution_backend": declaration})
    assert result["status"] == "UNAVAILABLE"
    assert "rc=127" in " ".join(result["reasons"])
    assert all(c.get("stage") != "compile" for c in result["execution"]["commands"])


def test_missing_frozen_runtime_is_never_reissued(tmp_path, monkeypatch, native):
    frozen = {"backend": "native", "container": "historical-runtime",
              "container_id": "c3" * 32, "image_id": IMAGE_ID, "image_digest": DIGEST}
    bd._write_immutable_json(bd._native_challenge_identity_path(tmp_path), frozen)
    monkeypatch.setenv("VIBEIC_EDA_CONTAINER", "another-runtime")
    monkeypatch.setattr(bd._runtime_pair._pin, "container_pin_state",
                        lambda name, env=None: ("UNREADABLE", "CONTAINER_ABSENT: " + name))
    rc, pair = bd._runtime_pair_gate(tmp_path, "resume:retry")
    assert rc == 2 and pair["container"] == "historical-runtime"
    assert native == []
    assert bd._frozen_native_challenge_identity(tmp_path) == frozen


def test_frozen_resume_keeps_original_identity_and_container(tmp_path, monkeypatch, native):
    frozen = {"backend": "native", "container": "historical-runtime",
              "container_id": "c3" * 32, "image_id": IMAGE_ID, "image_digest": DIGEST}
    path = bd._native_challenge_identity_path(tmp_path)
    bd._write_immutable_json(path, frozen)
    before = path.read_bytes()
    monkeypatch.setenv("VIBEIC_EDA_CONTAINER", "new-process-default")
    rc, pair = bd._runtime_pair_gate(tmp_path, "resume:retry")
    assert rc is None and pair["container"] == "historical-runtime"
    argv = bd._solver_argv(Path("/unused/vibe_ic_one_shot_runner.py"), tmp_path / "projects/neutral", "D1", "1")
    assert argv[argv.index("--container") + 1] == "historical-runtime"
    assert path.read_bytes() == before and native == []


@pytest.mark.parametrize("field", ["container_id", "image_id", "image_digest"])
def test_existing_native_drift_refusal_survives(tmp_path, monkeypatch, native, field):
    declaration = {"container": "run-a", "container_id": "c3" * 32,
                   "image_id": IMAGE_ID, "image_digest": DIGEST}
    assert bd._challenge_native_identity(declaration)[1] == ""
    declaration[field] = "different"
    assert "native " + field + " drift" in bd._challenge_native_identity(declaration)[1]


def test_no_docker_and_legacy_host_do_not_supply(tmp_path, monkeypatch, native):
    monkeypatch.setattr(bd._challenge_exec, "no_container_route", lambda: True)
    assert bd._runtime_pair_gate(tmp_path, "solve", pristine=True)[0] is None
    assert native == []
    assert bd._challenge_execution_declaration(tmp_path)["backend"] == "host"


@pytest.mark.parametrize("kind", ["phase1", "solve", "backup", "repair", "same_bytes"])
def test_selected_runtime_reaches_child_argv_and_environment(tmp_path, monkeypatch, kind):
    run = tmp_path / "run"
    project = (run / "program_regates/neutral/request/staged_project" if kind == "same_bytes"
               else run / "projects/neutral")
    (project / "input").mkdir(parents=True)
    (project / "input/phase1_prompt.md").write_text("Neutral lifecycle input.\n")
    bd._write_runtime_pair_record(run, {"verdict": "RUNTIME_PAIR_MATCH", "container": "run-owned-a"})
    runner = tmp_path / "vibe_ic_one_shot_runner.py"
    output = tmp_path / "child.json"
    runner.write_text("import sys,os,json\nfrom pathlib import Path\n"
                      "Path(os.environ['NEUTRAL_CHILD']).write_text(json.dumps("
                      "{'argv':sys.argv,'container':os.environ.get('VIBEIC_EDA_CONTAINER')}))\n")
    monkeypatch.setenv("NEUTRAL_CHILD", str(output))
    monkeypatch.setenv("VIBEIC_EDA_CONTAINER", "unrelated-process-default")
    budget = bd._RunnerBudget(1, 1, 1)
    if kind == "phase1":
        bd._ensure_phase1_frontdoor(runner, project, budget)
    else:
        argv = (bd._solver_argv(runner, project, "D1", "1") if kind == "solve"
                else bd._resume_solver_argv(runner, project, kind != "same_bytes", "D1", "1"))
        budget.run(argv)
    child = json.loads(output.read_text())
    assert child["argv"][child["argv"].index("--container") + 1] == "run-owned-a"
    assert child["container"] == "run-owned-a"
    assert os.environ["VIBEIC_EDA_CONTAINER"] == "unrelated-process-default"


FAKE_DOCKER = r'''#!/usr/bin/env python3
import copy, json, os, sys
from pathlib import Path
a = sys.argv[1:]
p = Path(os.environ['NEUTRAL_STATE'])
s = json.loads(p.read_text())
with open(os.environ['NEUTRAL_LOG'], 'a') as f: f.write(json.dumps(a)+'\n')
fmt = a[a.index('--format')+1] if '--format' in a else ''
name = a[2] if a[:2] == ['container','inspect'] else a[1] if len(a)>1 else ''
def emit(v): print(json.dumps(v))
if a[:2] == ['image','inspect']:
    if fmt == '{{.Id}}': print(s['image'])
    elif 'Entrypoint' in fmt: emit(None)
elif a[:2] == ['container','inspect']:
    sys.exit(0 if name in s['containers'] else 1)
elif a[0] == 'inspect':
    c = s['containers'][name]
    declarations = c.get('declarations', [
        {'Type':m['Type'],'Source':m.get('Name',m['Source']),'Target':m['Destination'],'ReadOnly':not m['RW']}
        for m in c['mounts'] if m['Destination'] != '/work'])
    fields = {'.Id':c['cid'], '.Image':c['image'], '.State.Running':True, '.Mounts':c['mounts'],
              '.HostConfig.Mounts':declarations, '.HostConfig.VolumesFrom':c.get('volumes_from'),
              '.HostConfig.Binds':c.get('binds',[m['Source']+':/work:rw' for m in c['mounts'] if m['Destination']=='/work']),
              '.HostConfig.Tmpfs':None, '.HostConfig.Memory':c.get('memory',1073741824),
              '.HostConfig.MemorySwap':c.get('memory_swap',1073741824),
              '.Config.User':'1000', '.Config.WorkingDir':'/work',
              '.Config.Cmd':['sleep','infinity'], '.Config.Entrypoint':None}
    if fmt.startswith('{{json '): emit(fields[fmt[7:-2]])
    elif fmt == '{{.Config.Image}}': print('example.invalid/eda@'+s['digest'])
    elif fmt == '{{.Config.User}}': print('1000')
    elif fmt == '{{.Config.WorkingDir}}': print('/work')
    elif '.Config.Cmd' in fmt: print('sleep\ninfinity')
    elif '.HostConfig.Binds' in fmt:
        for m in c['mounts']:
            if m['Destination'] == '/work': print(m['Source']+':/work:rw')
    elif '.HostConfig.Mounts' in fmt:
        for m in declarations:
            print(m['Type']+'|'+m.get('Source','')+'|'+m['Target']+'|'+str(m.get('ReadOnly',False)).lower()+'|'+m.get('BindOptions',{}).get('Propagation',''))
    elif '.Mounts' in fmt:
        for m in c['mounts']: print(m['Destination']+'|'+m['Source']+'|'+str(m['RW']).lower())
    elif fmt == '{{.Image}}': print(c['image'])
    elif fmt == '{{.Id}}': print(c['cid'])
elif a[0] == 'run':
    name = a[a.index('--name')+1]
    mounts=[]
    for i,x in enumerate(a):
        if x == '-v':
            src,dst,*opts=a[i+1].split(':')
            mounts.append({'Type':'bind','Source':src,'Destination':dst,
                           'RW':'ro' not in ','.join(opts).split(','),'Propagation':'rprivate'})
    inherited=[]
    effective={}
    if '--volumes-from' in a:
        reference=a[a.index('--volumes-from')+1]
        origin=next(c for n,c in s['containers'].items() if n==reference or c['cid']==reference)
        mounts=copy.deepcopy(origin['mounts'])
        inherited=[reference]
        effective=copy.deepcopy(origin.get('effective_options',{}))
    sizes={'1g':1073741824,'1024m':1073741824,'2g':2147483648}
    def amount(flag):
        if flag not in a:return 0
        value=a[a.index(flag)+1]
        return sizes[value] if value in sizes else int(value)
    s['containers'][name]={'cid':'new-'+name,'image':s['image'],'mounts':mounts,
        'declarations':[], 'volumes_from':inherited,'effective_options':effective,
        'binds':None if inherited else [a[i+1] for i,x in enumerate(a) if x=='-v'],
        'memory':amount('--memory'),'memory_swap':amount('--memory-swap')}
    p.write_text(json.dumps(s));print('new-'+name)
elif a[0] == 'top': print('PID COMMAND\n123 sleep infinity')
elif a[0] in ('rm','rename','stop','start','ps','images'): pass
else: sys.exit(98)
'''


@pytest.fixture
def docker_fixture(tmp_path):
    binpath = tmp_path / "bin"
    binpath.mkdir()
    docker = binpath / "docker"
    docker.write_text(FAKE_DOCKER.replace("#!/usr/bin/env python3", "#!" + sys.executable))
    docker.chmod(0o755)
    mounts = [{"Type": "bind", "Source": str(tmp_path), "Destination": "/work",
               "RW": True, "Propagation": "rprivate"},
              {"Type": "bind", "Source": str(PROGRAMS.parent), "Destination": "/plugin",
               "RW": False, "Propagation": "rprivate"}]
    state = {"image": IMAGE_ID, "digest": DIGEST, "containers": {
        "template": {"cid": "original-template", "image": IMAGE_ID, "mounts": mounts}}}
    statefile, logfile = tmp_path / "state.json", tmp_path / "calls.jsonl"

    def invoke(script, target="target", existing=None, source_image=IMAGE_ID,
               source_config=None, policy="1g"):
        current = copy.deepcopy(state)
        current["containers"]["template"].update(copy.deepcopy(source_config or {}))
        current["containers"]["template"]["image"] = source_image
        if existing:
            current["containers"][target] = copy.deepcopy(existing)
        statefile.write_text(json.dumps(current))
        logfile.write_text("")
        env = {**os.environ, "PATH": str(binpath) + ":" + os.environ["PATH"],
               "NAME": target, "SOURCE_CONTAINER": "template", "ENSURE_ONLY": "1",
               "PULL": "0", "VIBEIC_DOCKER_MEMORY": policy,
               "NEUTRAL_STATE": str(statefile), "NEUTRAL_LOG": str(logfile)}
        cp = subprocess.run(["bash", str(REPO / script), IMAGE], env=env,
                            capture_output=True, text=True, timeout=30)
        calls = [json.loads(x) for x in logfile.read_text().splitlines()]
        return cp, calls, json.loads(statefile.read_text()), current
    return invoke, state["containers"]["template"]


COPIES = ["tools/vibeic-eda/restart-eda.sh",
          "vibe-ic-marketplace/plugins/vibe-ic/tools/vibeic-eda/restart-eda.sh"]


@pytest.mark.parametrize("script", COPIES, ids=["repository", "packaged"])
@pytest.mark.parametrize("existing", [False, True])
def test_ensure_preserves_source_and_stable_target(docker_fixture, script, existing):
    invoke, template = docker_fixture
    target = {**template, "cid": "stable-target"} if existing else None
    cp, calls, after, before = invoke(script, existing=target)
    assert cp.returncode == 0, (cp.stdout, cp.stderr, calls)
    assert after["containers"]["template"] == before["containers"]["template"]
    assert not [c for c in calls if c[0] in {"rm", "rename", "stop", "start", "kill", "exec", "pull"}]
    runs = [c for c in calls if c[0] == "run"]
    assert len(runs) == (0 if existing else 1)
    if existing:
        assert after["containers"]["target"]["cid"] == "stable-target"
    else:
        assert runs[0][-3:] == [IMAGE, "sleep", "infinity"]  # Nix has no entrypoint.


@pytest.mark.parametrize("script", COPIES, ids=["repository", "packaged"])
@pytest.mark.parametrize("defect", ["source_image", "target_image", "target_mount"])
def test_ensure_refuses_incompatible_state_without_mutation(docker_fixture, script, defect):
    invoke, template = docker_fixture
    target = copy.deepcopy(template)
    if defect == "target_image": target["image"] = "different-image"
    if defect == "target_mount": target["mounts"][0]["RW"] = False
    cp, calls, after, before = invoke(script, existing=target,
        source_image="different-image" if defect == "source_image" else IMAGE_ID)
    assert cp.returncode != 0
    assert after == before
    assert not [c for c in calls if c[0] in {"rm", "rename", "stop", "start", "run", "kill", "exec", "pull"}]


@pytest.mark.parametrize("script", COPIES, ids=["repository", "packaged"])
@pytest.mark.parametrize("policy,memory,swap,compatible", [
    ("1g", 2 * 1024**3, 2 * 1024**3, False),
    ("1g", 1024**3, 2 * 1024**3, False),
    ("1024m", 1024**3, 1024**3, True),
    ("0", 0, 0, True),
    ("0", 1024**3, 1024**3, False),
])
def test_ensure_compares_declared_memory_and_swap(docker_fixture, script, policy, memory, swap, compatible):
    invoke, template = docker_fixture
    target = {**copy.deepcopy(template), "cid": "stable-target", "memory": memory, "memory_swap": swap}
    cp, calls, after, before = invoke(script, existing=target, policy=policy)
    assert (cp.returncode == 0) is compatible, (cp.stdout, cp.stderr)
    assert after == before
    assert not [c for c in calls if c[0] in {"rm", "rename", "stop", "start", "run", "kill", "exec", "pull"}]


@pytest.mark.parametrize("script", COPIES, ids=["repository", "packaged"])
@pytest.mark.parametrize("existing", [False, True])
def test_ensure_preserves_nonrecursive_effective_access(docker_fixture, script, existing):
    invoke, template = docker_fixture
    source = copy.deepcopy(template)
    source["declarations"] = [{"Type": "bind", "Source": source["mounts"][1]["Source"],
        "Target": "/plugin", "ReadOnly": True, "BindOptions": {"NonRecursive": True}}]
    source["effective_options"] = {"/plugin": {"NonRecursive": True}}
    target = {**copy.deepcopy(template), "cid": "stable-target", "declarations": []} if existing else None
    cp, calls, after, before = invoke(script, existing=target, source_config=source)
    assert after["containers"]["template"] == before["containers"]["template"]
    if existing:
        assert cp.returncode != 0 and after == before
        assert not [c for c in calls if c[0] in {"rm", "rename", "stop", "start", "run"}]
    else:
        assert cp.returncode == 0, (cp.stdout, cp.stderr)
        assert after["containers"]["target"]["effective_options"] == source["effective_options"]


@pytest.mark.parametrize("script", COPIES, ids=["repository", "packaged"])
def test_ensure_reuses_actual_anonymous_volume_name(docker_fixture, script):
    invoke, template = docker_fixture
    source = copy.deepcopy(template)
    source["mounts"].append({"Type": "volume", "Name": "original-volume", "Source": "/volumes/original-volume/_data",
                             "Destination": "/cache", "RW": True, "Propagation": ""})
    source["declarations"] = [{"Type": "volume", "Target": "/cache", "VolumeOptions": {"NoCopy": True}}]
    cp, calls, after, before = invoke(script, source_config=source)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert after["containers"]["template"] == before["containers"]["template"]
    target = next(m for m in after["containers"]["target"]["mounts"] if m["Type"] == "volume")
    assert target["Name"] == "original-volume"


@pytest.mark.parametrize("script", COPIES, ids=["repository", "packaged"])
def test_explicit_bind_cannot_claim_inherited_nonrecursive_options(docker_fixture, script):
    invoke, template = docker_fixture
    source = copy.deepcopy(template)
    source["declarations"] = [{"Type": "bind", "Source": source["mounts"][1]["Source"],
        "Target": "/plugin", "ReadOnly": True, "BindOptions": {"NonRecursive": True}}]
    target = {**copy.deepcopy(template), "cid": "stable-target", "declarations": [],
              "volumes_from": [source["cid"]], "binds": [source["mounts"][1]["Source"] + ":/plugin:ro"]}
    cp, calls, after, before = invoke(script, existing=target, source_config=source)
    assert cp.returncode != 0
    assert after == before
    assert not [c for c in calls if c[0] in {"rm", "rename", "stop", "start", "run"}]


@pytest.mark.parametrize("script", COPIES, ids=["repository", "packaged"])
def test_inherited_nonrecursive_without_override_reuses_exact_CID(docker_fixture, script):
    invoke, template = docker_fixture
    source = copy.deepcopy(template)
    source["declarations"] = [{"Type": "bind", "Source": source["mounts"][1]["Source"],
        "Target": "/plugin", "ReadOnly": True, "BindOptions": {"NonRecursive": True}}]
    target = {**copy.deepcopy(template), "cid": "stable-target", "declarations": [],
              "volumes_from": [source["cid"]], "binds": None}
    cp, calls, after, before = invoke(script, existing=target, source_config=source)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert after == before
    assert not [c for c in calls if c[0] in {"rm", "rename", "stop", "start", "run"}]


@pytest.mark.parametrize("script", COPIES, ids=["repository", "packaged"])
def test_matching_legacy_volume_options_remain_legal(docker_fixture, script):
    invoke, template = docker_fixture
    source = copy.deepcopy(template)
    source["mounts"].append({"Type": "volume", "Name": "original-volume", "Source": "/volumes/original-volume/_data",
                             "Destination": "/cache", "RW": True, "Propagation": ""})
    source["declarations"] = [{"Type": "volume", "Target": "/cache", "VolumeOptions": {"NoCopy": True}}]
    target = {**copy.deepcopy(source), "cid": "stable-target", "declarations": [],
              "volumes_from": [source["cid"]], "binds": ["original-volume:/cache:nocopy"]}
    cp, calls, after, before = invoke(script, existing=target, source_config=source)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert after == before
    assert not [c for c in calls if c[0] in {"rm", "rename", "stop", "start", "run"}]
