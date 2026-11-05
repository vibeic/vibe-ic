"""R2 Step9 provider controls: native-only, canonical and fail-closed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execution_native_installation as installation
import execution_native_worker as native_worker













def test_step9_image_identity_uses_current_local_attestation_without_docker(monkeypatch):
    image_id = "sha256:" + "1" * 64
    reference = "registry.invalid/tools@sha256:" + "2" * 64
    import _container_exec as container_exec
    import librelane_contract as ll
    monkeypatch.setattr(container_exec, "no_container_route", lambda: True)
    monkeypatch.setattr(ll, "local_image_attestation", lambda image: {
        "image": reference, "image_id": image_id, "repo_digests": [reference]})
    monkeypatch.setattr(installation.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("LOCAL identity reached Docker"))

    assert installation._image_identity(reference, "docker") == (image_id, (reference,))




def _local_workdir_argv(project: Path, workdir: str) -> list[str]:
    samepath = str(project.resolve())
    return ["docker", "run", "--rm", "-v", f"{samepath}:{samepath}",
            "--workdir", workdir, "--entrypoint", "python3", "unit-image",
            "-c", "import os; print(os.getcwd())"]


def test_local_workdir_runs_child_from_mapped_docker_directory(tmp_path, monkeypatch):
    """Unit seam only: assert the actual child cwd, with image authority mocked."""
    import _container_exec as container_exec
    import librelane_contract as ll

    project = tmp_path / "project"
    project.mkdir()
    observed = {}
    monkeypatch.setattr(container_exec, "no_container_route", lambda: True)
    monkeypatch.setattr(container_exec, "local_exec_mode", lambda owner: None)
    attestation = {"network_mode": None, "memory": 0, "memory_swap": -1,
                   "auto_remove": True, "cid": "unit-cid"}
    monkeypatch.setattr(ll, "local_image_attestation", lambda image: dict(attestation))

    class Child:
        # This completed protocol fixture owns no OS process. The supervisor
        # must neither watch container init nor wait forever for a missing API.
        pid = None
        returncode = 0
        def wait(self, timeout=None):
            return self.returncode
        def poll(self):
            return self.returncode
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def communicate(self, timeout=None):
            return "unit output", ""

    def popen(command, **kwargs):
        observed["command"] = command
        observed["cwd"] = kwargs.get("cwd")
        return Child()

    monkeypatch.setattr(ll.subprocess, "Popen", popen)
    result = ll._run_local(_local_workdir_argv(project, str(project)),
                           probe_deadline_s=1, supervised=False, log=None)
    assert result.returncode == 0
    assert observed["cwd"] == project.resolve()
    assert observed["cwd"].is_dir()


def test_local_workdir_runs_real_child_in_mapped_directory(tmp_path, monkeypatch):
    """Real Python child through LOCAL; only image attestation is a unit seam."""
    import _container_exec as container_exec
    import librelane_contract as ll

    project = tmp_path / "project"
    project.mkdir()
    marker = "relative-file-read-from-real-child\n"
    (project / "cwd-proof.txt").write_text(marker)
    monkeypatch.setattr(container_exec, "no_container_route", lambda: True)
    attestation = {"network_mode": None, "memory": 0, "memory_swap": -1,
                   "auto_remove": True, "cid": "unit-cid"}
    monkeypatch.setattr(ll, "local_image_attestation", lambda image: dict(attestation))
    script = ("import os; from pathlib import Path; print(os.getcwd()); "
              "print(Path('cwd-proof.txt').read_text(), end='')")
    argv = ["docker", "run", "--rm", "-v", f"{project.resolve()}:/guest-project",
            "--workdir", "/guest-project", "--entrypoint", "python3", "unit-image",
            "-c", script]

    result = ll._run_local(argv, probe_deadline_s=10, supervised=False, log=None)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(project.resolve()), marker.rstrip()]
    print("REAL_CHILD_WORKDIR_RESULT " + json.dumps({
        "returncode": result.returncode,
        "stdout_lines": result.stdout.splitlines(),
        "requested_guest_cwd": "/guest-project",
    }, sort_keys=True))


@pytest.mark.parametrize("workdir", ["relative-dir", "/unmapped/workdir"])
def test_local_workdir_refuses_unmapped_or_relative_paths(tmp_path, monkeypatch, workdir):
    import _container_exec as container_exec
    import librelane_contract as ll

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(container_exec, "no_container_route", lambda: True)
    monkeypatch.setattr(container_exec, "local_exec_mode", lambda owner: None)
    monkeypatch.setattr(ll, "local_image_attestation",
                        lambda image: pytest.fail("invalid --workdir reached image attestation"))
    with pytest.raises(ll.Refusal, match="LL_LOCAL_WORKDIR_INVALID"):
        ll._run_local(_local_workdir_argv(project, workdir),
                      probe_deadline_s=1, supervised=False, log=None)


def test_local_workdir_refuses_missing_directory_without_scratch_fallback(tmp_path, monkeypatch):
    import _container_exec as container_exec
    import librelane_contract as ll

    project = tmp_path / "project"
    project.mkdir()
    missing = project / "missing"
    monkeypatch.setattr(container_exec, "no_container_route", lambda: True)
    monkeypatch.setattr(container_exec, "local_exec_mode", lambda owner: None)
    monkeypatch.setattr(ll, "local_image_attestation",
                        lambda image: pytest.fail("missing --workdir reached image attestation"))
    with pytest.raises(ll.Refusal, match="LL_LOCAL_WORKDIR_INVALID"):
        ll._run_local(_local_workdir_argv(project, str(missing)),
                      probe_deadline_s=1, supervised=False, log=None)


def test_local_workdir_refuses_conflicting_caller_cwd(tmp_path, monkeypatch):
    import _container_exec as container_exec
    import librelane_contract as ll

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(container_exec, "no_container_route", lambda: True)
    monkeypatch.setattr(container_exec, "local_exec_mode", lambda owner: None)
    monkeypatch.setattr(ll, "local_image_attestation",
                        lambda image: pytest.fail("conflicting cwd reached image attestation"))
    with pytest.raises(ll.Refusal, match="LL_LOCAL_WORKDIR_INVALID"):
        ll._run_local(_local_workdir_argv(project, str(project)),
                      probe_deadline_s=1, supervised=False, log=None,
                      cwd=tmp_path)


def _worker_installation_spec():
    image_ref = "registry.invalid/tools@sha256:" + "2" * 64
    image_id = "sha256:" + "1" * 64
    payload = {"schema": 1, "status": "MEASURED", "step_id": "9",
               "image_ref": image_ref, "image_id": image_id}
    receipt = {**payload, "receipt_sha256": hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()}
    return {"schema": 1, "step_id": "9", "image_id": image_id,
            "native_installation_request": {
                "schema": 1, "step_id": "9", "image_ref": image_ref,
                "image_id": image_id},
            "native_installation_receipt": receipt,
            "native_installation_receipt_sha256": receipt["receipt_sha256"]}, image_ref


def test_native_worker_uses_parent_bound_reference_not_config_image_id():
    spec, image_ref = _worker_installation_spec()
    assert native_worker._pinned_image_reference(spec) == image_ref
    assert image_ref != spec["image_id"]
