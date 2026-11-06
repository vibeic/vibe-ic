"""Bounded caller-to-run_chain LOCAL PDK-root integration controls."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import librelane_contract as ll
import librelane_fill_dfm as fill


def test_density_caller_maps_the_selected_pdk_root_to_the_run_chain_cli(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    pdk_root = tmp_path / "configured-pdk-root"
    selected = pdk_root / "pdkFixture"
    selected.mkdir(parents=True)
    gds = project / "fixture.gds"
    gds.write_text("neutral density fixture\n")
    runset = selected / "density.runset"
    runset.write_text("neutral deck fixture\n")
    config = project / "density-config.json"
    config.write_text(json.dumps({
        "meta": {"step": "KLayout.Density"},
        "KLAYOUT_DENSITY_RUNSET": str(runset),
    }) + "\n")

    monkeypatch.setattr(ll._ce, "no_container_route", lambda: True)
    monkeypatch.setattr(ll, "image_capability", lambda *_a, **_k: {})
    attestation = {
        "image": "fixture-image", "image_id": "sha256:" + "1" * 64,
        "repo_digests": [], "cid": "unit-local-cid", "network_mode": "bridge",
        "memory": 1024 ** 3, "memory_swap": 1024 ** 3, "auto_remove": True,
        "attestation_path": "unit-only", "attestation_sha256": "0" * 64,
    }
    monkeypatch.setattr(ll, "local_image_attestation", lambda _image: dict(attestation))
    monkeypatch.setattr(ll, "openroad_home", lambda *_a, **_k: None)
    monkeypatch.setattr(ll, "_check_state", lambda *_a, **_k: None)
    monkeypatch.setattr(fill, "measure_density_ratios", lambda *_a, **_k: {})

    captured = {}
    child_script = (
        "import json,sys; from pathlib import Path; a=sys.argv[1:]; "
        "root=a[a.index('--pdk-root')+1]; "
        "src=Path(a[a.index('--state-in')+1]); "
        "dst=Path(a[a.index('--state-out')+1]); "
        "state=json.loads(src.read_text()); "
        f"state.setdefault('metrics',{{}})[{fill.DENSITY_METRIC!r}]=0; "
        "state['cli_pdk_root']=root; dst.write_text(json.dumps(state)); "
        "print(root)"
    )

    def local_step(cmd, *, log=None, **_kwargs):
        captured["declared_cli_root"] = cmd[cmd.index("--pdk-root") + 1]
        captured["volume_args"] = [cmd[i + 1] for i, value in enumerate(cmd[:-1])
                                   if value == "-v"]
        image_index = cmd.index("fixture-image")
        state_in = cmd[cmd.index("-i") + 1]
        state_out = str(Path(cmd[cmd.index("-o") + 1]) / "state_out.json")
        safe = cmd[:image_index + 1] + [
            "-c", child_script,
            "--pdk-root", captured["declared_cli_root"],
            "--state-in", state_in,
            "--state-out", state_out,
        ]
        # Exercise the real LOCAL Docker-argv parser and real Python child;
        # replace only the EDA CLI body so this remains a software fixture.
        return ll._run_local(safe, probe_deadline_s=15, supervised=False, log=log)

    monkeypatch.setattr(ll, "run_container", local_step)
    initial = project / "initial-state.json"
    initial.write_text(json.dumps({"gds": str(gds.resolve())}) + "\n")
    monkeypatch.setattr(fill, "state_from_direct", lambda *_a, **_k: initial)

    result = fill.run_density(project, "fixture-image", pdk_root, "pdkFixture",
                              gds=gds, lane="root-caller", configs={
                                  "KLayout.Density": config,
                              }, steps=("KLayout.Density",))

    # run_chain localizes the guest namespace before calling the LOCAL
    # container adapter; the child therefore receives the configured host
    # root while the saved record retains the logical /pdk request.
    assert captured["declared_cli_root"] == str(pdk_root.resolve())
    assert captured["volume_args"] == [
        f"{project.resolve()}:{project.resolve()}",
        f"{pdk_root.resolve()}:{ll.PDK_GUEST_ROOT}:ro",
    ]
    state_path = Path(result["state"])
    state = json.loads(state_path.read_text())
    assert state["cli_pdk_root"] == str(pdk_root.resolve())
    root_record = json.loads((state_path.parent / "pdk_root.json").read_text())
    assert root_record["cli_pdk_root"] == str(pdk_root.resolve())
    assert root_record["requested_pdk_root"] == ll.PDK_GUEST_ROOT
    assert root_record["requested_mounts"] == [[str(pdk_root.resolve()), ll.PDK_GUEST_ROOT]]
    assert root_record["mounts_under_it"] == [[str(pdk_root.resolve()), str(pdk_root.resolve())]]


def test_density_caller_refuses_when_the_selected_pdk_is_missing(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    gds = project / "fixture.gds"
    gds.write_text("neutral density fixture\n")
    pdk_root = tmp_path / "configured-pdk-root"
    (pdk_root / "differentPdk").mkdir(parents=True)

    monkeypatch.setattr(ll, "image_capability", lambda *_a, **_k: {})
    monkeypatch.setattr(fill, "state_from_direct", lambda *_a, **_k: pytest.fail(
        "missing selected PDK must refuse before bridge construction"))
    with pytest.raises(ll.Refusal, match="LL_PDK_MISSING"):
        fill.run_density(project, "fixture-image", pdk_root, "pdkFixture",
                         gds=gds, lane="missing-selected-pdk",
                         steps=("KLayout.Density",))


@pytest.mark.parametrize("owner", ["ir_openroad", "sealring_capability", "fill_keepout", "si_sta"])
@pytest.mark.parametrize("profile", ["local_host", "local_none", "remote"])
def test_native_finishing_callers_use_the_current_provider(tmp_path, monkeypatch, owner, profile):
    """Real caller, typed provider and LOCAL parser; neutral native process leaves."""
    import os
    import subprocess
    import _watchdog as watchdog
    import _container_exec as container_exec
    import librelane_signoff as signoff
    from test_librelane_contract import _host_provider
    from test_die_density_finish import _pdk

    monkeypatch.setenv("VIBEIC_DOCKER_MEMORY", "4g")
    if profile.startswith("local_"):
        network = profile.removeprefix("local_")
        monkeypatch.setenv("VIBEIC_LIBRELANE_LOCAL_NETWORK", network)
        project, image = _host_provider(tmp_path, monkeypatch)
        assert image.network_mode == network
    else:
        network = "none"
        monkeypatch.delenv(ll.LOCAL_PROVIDER_ROUTE_ENV, raising=False)
        monkeypatch.setattr(container_exec, "no_container_route", lambda: False)
        image = "registry.invalid/native@sha256:" + "aa" * 32
        project = tmp_path / "project"
        project.mkdir()
    folder = project / "neutral-native"
    folder.mkdir()
    script = folder / "native.tcl"
    script.write_text("# neutral native process input\n")
    log = folder / "native.log"
    root, config = _pdk(tmp_path)
    routed = project / "phase3/stage3/pnr/routed.def"
    routed.parent.mkdir(parents=True, exist_ok=True)
    routed.write_text("COMPONENTS 0 ; END COMPONENTS\n")
    observed = {"owner": owner, "profile": profile, "launches": [], "calls": [],
                "provider": image.as_record() if profile.startswith("local_") else None}
    original_run_container = ll.run_container

    def record_launch(argv, **kwargs):
        observed["launches"].append(list(argv))
        return original_run_container(argv, **kwargs)

    def payload():
        if owner == "sealring_capability":
            return "True\n"
        if owner == "fill_keepout":
            (folder / "placed_keepouts.txt").write_text("DBU 1000\nTOTAL 0\nEND 0\n")
        return "NEUTRAL_NATIVE_STDOUT\n"

    def host_leaf(argv, **kwargs):
        row = {"route": "Docker" if argv[0] == "docker" else "LOCAL", "argv": list(argv)}
        if row["route"] == "LOCAL":
            row.update(network=kwargs["env"]["VIBEIC_LOCAL_NETWORK_MODE"],
                       pythonpath=kwargs["env"]["PYTHONPATH"])
        observed["calls"].append(row)
        return watchdog.SupervisedResult(0, payload(), "", "natural")

    def docker_leaf(argv, **kwargs):
        observed["calls"].append({"route": "Docker", "argv": list(argv)})
        return subprocess.CompletedProcess(argv, 0, payload(), "")

    monkeypatch.setattr(watchdog, "run_host_supervised", host_leaf)
    monkeypatch.setattr(ll.subprocess, "run", docker_leaf)
    try:
        if owner == "ir_openroad":
            metrics = folder / "metrics.json"
            native_command = ["env", "LD_LIBRARY_PATH=/opt/or-tools/lib",
                              "openroad", "-no_init", "-no_splash",
                              "-metrics", str(metrics), "-exit", str(script)]
        observed["completed"] = True
    except ll.Refusal as exc:
        observed["refusal"] = {"code": exc.code, "detail": str(exc)}
        raise
    finally:
        (tmp_path / "NATIVE_FINISHING_PROVIDER_OBSERVATION.json").write_text(
            json.dumps(observed, indent=2) + "\n")
    assert len(observed["calls"]) == len(observed["launches"]) == 1
    call, launch = observed["calls"][0], observed["launches"][0]
    assert launch[launch.index("--network") + 1] == network
    assert launch[launch.index("--memory") + 1] == "4g"
    assert launch[launch.index("--memory-swap") + 1] == "4g" and "--rm" in launch
    if profile.startswith("local_"):
        assert call["route"] == "LOCAL" and call["network"] == network
        assert ("--unshare-net" in call["argv"]) is (network == "none")
        assert call["pythonpath"].split(os.pathsep)[0] == image.librelane_root
        launcher = "import os,sys;os.execvp(sys.argv[1],sys.argv[1:])"
        index = call["argv"].index(launcher)
        assert call["argv"][index - 2:index] == [image.executable, "-c"]
    else:
        assert call["route"] == "Docker"
        assert not any("os.execvp" in str(part) for part in launch)
        if owner in ("ir_openroad", "sealring_capability"):
            at = launch.index("--entrypoint")
