"""Parent-measured, source/input-bound installation admission for Step 9.

This is an installation probe, not a resource lease or a native result. It
measures an immutable image and its synthesis entrypoints before the ordinary
Registry is finalized. The existing worker and supervised LibreLane process
remain the only synthesis producer.
"""
from __future__ import annotations
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Mapping

import execution_modes as em


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_receipt_digest(receipt: Mapping[str, object]) -> bool:
    """Check the canonical content digest of an already parent-issued receipt."""
    if not isinstance(receipt, Mapping):
        return False
    payload = dict(receipt)
    supplied = payload.pop("receipt_sha256", None)
    return (isinstance(supplied, str) and
            re.fullmatch(r"[0-9a-f]{64}", supplied) is not None and
            supplied == _sha(_canonical(payload)))


@dataclass(frozen=True)
class InstallationRequest:
    schema: int
    step_id: str
    project: str
    top: str
    image_ref: str
    image_id: str
    source_sha: str
    source_files: Mapping[str, str]
    input_hashes: Mapping[str, str]
    pdk_name: str
    pdk_root: str
    pdk_tree_sha256: str
    config_hashes: Mapping[str, str]
    model_hashes: Mapping[str, str]
    engine_contract: Mapping[str, object]


@dataclass(frozen=True)
class InstallationReceipt:
    schema: int
    status: str
    step_id: str
    project: str
    top: str
    image_ref: str
    image_id: str
    repo_digests: tuple[str, ...]
    tool_commands: tuple[Mapping[str, object], ...]
    librelane_facts_sha256: str
    source_sha: str
    source_files: Mapping[str, str]
    source_closure_sha256: str
    input_hashes: Mapping[str, str]
    pdk_name: str
    pdk_root: str
    pdk_tree_sha256: str
    config_hashes: Mapping[str, str]
    model_hashes: Mapping[str, str]
    engine_contract: Mapping[str, object]
    measured_at_utc: str
    receipt_sha256: str


_TOOL_PROBE = r'''set -eu
printf 'python='; command -v python3
python3 -c 'import librelane; print("librelane=" + str(getattr(librelane,"__version__", "")))'
python3 -m librelane --help >/dev/null
python3 -m librelane.steps run --help >/dev/null
printf 'yosys_path='; command -v yosys
printf 'yosys_version='; yosys -V
'''


def _image_identity(image_ref: str, docker: str) -> tuple[str, tuple[str, ...]]:
    if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image_ref):
        raise em.Refusal("STEP9_IMAGE_NOT_PINNED", image_ref)
    import _container_exec as container_exec
    if container_exec.no_container_route():
        import librelane_contract as ll
        identity = ll.local_image_attestation(image_ref)
        image_id = identity.get("image_id")
        repo_digests = tuple(identity.get("repo_digests") or ())
        if (not isinstance(image_id, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
                or image_ref not in repo_digests
                or not all(isinstance(ref, str) for ref in repo_digests)):
            raise em.Refusal("STEP9_IMAGE_IDENTITY_MISMATCH", image_ref)
        return image_id, repo_digests
    try:
        done = subprocess.run([docker, "image", "inspect", "--format",
                               "{{.Id}} {{json .RepoDigests}}", image_ref],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise em.Refusal("STEP9_IMAGE_UNAVAILABLE", repr(exc)) from exc
    if done.returncode:
        raise em.Refusal("STEP9_IMAGE_UNAVAILABLE", (done.stderr or "")[-300:])
    try:
        image_id, raw = done.stdout.strip().split(" ", 1)
        repo_digests = tuple(json.loads(raw))
    except (ValueError, TypeError) as exc:
        raise em.Refusal("STEP9_IMAGE_IDENTITY_UNREADABLE", done.stdout[-300:]) from exc
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) or image_ref not in repo_digests:
        raise em.Refusal("STEP9_IMAGE_IDENTITY_MISMATCH", image_ref)
    return image_id, repo_digests


def request_for(*, project: Path, top: str, image_ref: str, image_id: str,
                source_sha: str, source_files: Mapping[str, str],
                input_hashes: Mapping[str, str], pdk_name: str, pdk_root: Path,
                pdk_manifest: Mapping[str, object], config_hashes: Mapping[str, str],
                model_hashes: Mapping[str, str], engine_contract: Mapping[str, object]) -> InstallationRequest:
    return InstallationRequest(
        1, "9", str(project.resolve()), top, image_ref, image_id, source_sha,
        dict(source_files), dict(input_hashes), pdk_name, str(pdk_root.resolve()),
        _sha(_canonical(pdk_manifest)), dict(config_hashes), dict(model_hashes),
        dict(engine_contract))


def measure_installation(request: InstallationRequest, *, facts: Mapping[str, object],
                         docker: str = "docker") -> InstallationReceipt:
    """Probe exact pinned image CLI/tool facts through LibreLane's supervised seam."""
    if request.schema != 1 or not re.fullmatch(r"(?:9|A[1-9])", request.step_id):
        raise em.Refusal("STEP9_INSTALLATION_REQUEST_INVALID", str(request.step_id))
    image_id, repo_digests = _image_identity(request.image_ref, docker)
    if image_id != request.image_id:
        raise em.Refusal("STEP9_IMAGE_IDENTITY_MISMATCH", image_id)
    if not isinstance(facts, Mapping) or facts.get("image_id") != image_id:
        raise em.Refusal("STEP9_IMAGE_FACTS_UNBOUND", image_id)
    flows = facts.get("flows")
    if not isinstance(flows, Mapping) or not flows.get("Chip"):
        raise em.Refusal("STEP9_CHIP_FLOW_UNMEASURED", image_id)
    required_steps = (request.engine_contract.get("native_steps")
                      if isinstance(request.engine_contract, Mapping) else None)
    if request.step_id == "9" and (not isinstance(required_steps, (list, tuple)) or
            not set(required_steps).issubset(set(flows["Chip"]))):
        raise em.Refusal("STEP9_NATIVE_STEPS_UNMEASURED", image_id)
    import librelane_contract as ll
    from _docker_memory import docker_memory_flags
    argv = [docker, "run", *docker_memory_flags(), "--rm", "--network", "none",
            "--entrypoint", "sh", request.image_ref, "-c", _TOOL_PROBE]
    result = ll.run_container(argv, probe_deadline_s=180)
    if result.returncode:
        raise em.Refusal("STEP9_TOOL_PROBE_FAILED",
                         f"image={request.image_id} rc={result.returncode}: " +
                         (result.stderr or result.stdout or "")[-500:])
    rows = []
    for line in (result.stdout or "").splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name in ("python", "librelane", "yosys_path", "yosys_version"):
            rows.append({"name": name, "value": value.strip(), "rc": result.returncode})
    if {row["name"] for row in rows} != {"python", "librelane", "yosys_path", "yosys_version"}:
        raise em.Refusal("STEP9_TOOL_FACTS_INCOMPLETE", repr(rows))
    facts_sha = _sha(_canonical(dict(facts)))
    source_closure_sha = _sha(_canonical(dict(sorted(request.source_files.items()))))
    payload = dict(schema=1, status="MEASURED", step_id=request.step_id,
        project=request.project, top=request.top, image_ref=request.image_ref,
        image_id=image_id, repo_digests=repo_digests, tool_commands=tuple(rows),
        librelane_facts_sha256=facts_sha, source_sha=request.source_sha,
        source_files=dict(request.source_files), source_closure_sha256=source_closure_sha,
        input_hashes=dict(request.input_hashes), pdk_name=request.pdk_name,
        pdk_root=request.pdk_root, pdk_tree_sha256=request.pdk_tree_sha256,
        config_hashes=dict(request.config_hashes), model_hashes=dict(request.model_hashes),
        engine_contract=dict(request.engine_contract),
        measured_at_utc=datetime.now(timezone.utc).isoformat())
    return InstallationReceipt(**payload, receipt_sha256=_sha(_canonical(payload)))


def verify_installation(receipt: Mapping[str, object], request: InstallationRequest,
                        *, facts: Mapping[str, object],
                        input_files: Mapping[str, Path], docker: str = "docker") -> InstallationReceipt:
    """Parent re-reads all bindings and image identity before adapter admission."""
    if not isinstance(receipt, Mapping):
        raise em.Refusal("STEP9_INSTALLATION_RECEIPT_MISSING", request.image_ref)
    try:
        typed = InstallationReceipt(**dict(receipt))
    except (TypeError, ValueError) as exc:
        raise em.Refusal("STEP9_INSTALLATION_RECEIPT_INVALID", repr(exc)) from exc
    payload = asdict(typed)
    supplied = payload.pop("receipt_sha256")
    if supplied != _sha(_canonical(payload)):
        raise em.Refusal("STEP9_INSTALLATION_RECEIPT_DIGEST_MISMATCH", request.image_ref)
    expected = asdict(request)
    for field in expected:
        if getattr(typed, field if field != "image_ref" else "image_ref", None) != expected[field]:
            raise em.Refusal("STEP9_INSTALLATION_RECEIPT_BINDING_MISMATCH", field)
    image_id, repo_digests = _image_identity(request.image_ref, docker)
    if (typed.status != "MEASURED" or typed.image_id != image_id or
            tuple(typed.repo_digests) != repo_digests or
            typed.librelane_facts_sha256 != _sha(_canonical(dict(facts))) or
            typed.source_closure_sha256 != _sha(_canonical(dict(sorted(request.source_files.items()))))):
        raise em.Refusal("STEP9_INSTALLATION_RECEIPT_STALE", request.image_ref)
    if set(input_files) != set(request.input_hashes):
        raise em.Refusal("STEP9_INSTALLATION_INPUT_SET_CHANGED", request.project)
    for name, expected_hash in request.input_hashes.items():
        path = Path(input_files[name])
        if path.is_symlink() or not path.is_file() or em.digest(path) != expected_hash:
            raise em.Refusal("STEP9_INSTALLATION_INPUT_CHANGED", name)
    manifest_path = Path(input_files.get("pdk/tree-manifest.json", ""))
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        raise em.Refusal("STEP9_PDK_MANIFEST_UNREADABLE", str(manifest_path)) from exc
    if (not isinstance(manifest, dict) or manifest.get("schema") != "vibe-ic/step9-pdk-tree/1"
            or _sha(_canonical(manifest)) != request.pdk_tree_sha256
            or Path(str(manifest.get("root", ""))).resolve() != Path(request.pdk_root)):
        raise em.Refusal("STEP9_PDK_MANIFEST_BINDING_MISMATCH", str(manifest_path))
    for row in manifest.get("files", []):
        if not isinstance(row, dict):
            raise em.Refusal("STEP9_PDK_MANIFEST_INVALID", str(manifest_path))
        path = Path(request.pdk_root) / str(row.get("path", ""))
        if (path.is_symlink() or not path.is_file() or em.digest(path) != row.get("sha256")):
            raise em.Refusal("STEP9_PDK_INPUT_CHANGED", str(path))
    for name, expected_hash in request.source_files.items():
        path = Path(name)
        if path.is_symlink() or not path.is_file() or em.digest(path) != expected_hash:
            raise em.Refusal("STEP9_INSTALLATION_SOURCE_CHANGED", name)
    return typed
