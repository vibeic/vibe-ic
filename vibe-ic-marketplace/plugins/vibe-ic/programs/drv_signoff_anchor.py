"""Read the installed PDK threshold source from the pinned EDA image.

The capture plan only names the PDK and library.  The config bytes and version
come from the image without a host bind mount, and the judge repeats this read.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _docker_memory  # noqa: E402
import librelane_contract as _ll  # noqa: E402


def pdk_source_identity(provenance: dict, *, project: Path) -> dict:
    """Read the existing PDK producer's Docker or typed LOCAL witness."""
    if provenance.get("source") == "declared":
        # A native in-image run deliberately records an explicitly supplied
        # PDK_ROOT as ``declared``: the outer container, not a nested Docker
        # probe, owns both that path and the immutable image identity.  Bind
        # those two existing authorities independently.  Do not manufacture a
        # resolved-image derivation for a root the producer did not resolve.
        pdk = provenance.get("pdk")
        declared_by = provenance.get("declared_by")
        root = Path(str(provenance.get("path") or ""))
        if (not isinstance(pdk, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", pdk)
                or declared_by not in {
                    "env VIBEIC_LIBRELANE_PDK_ROOT",
                    "phase3/librelane_switch.json pdk_root_host",
                }
                or not root.is_absolute() or root.is_symlink()
                or not (root / pdk).is_dir()):
            raise ValueError("declared PDK source differs from producer")
        image = _ll.resolve_image(project, record=False)
        provider = _ll._provider_for_image(image)
        if provider is not None:
            if (Path(provider.pdk_root).resolve() != root.resolve()
                    or provider.pdk not in (None, pdk)):
                raise ValueError("declared PDK source differs from producer")
            return {"pdk": pdk, "image": image, "image_id": str(provider),
                    "provider": provider.as_record()}
        try:
            attestation = _ll.local_image_attestation(image)
        except _ll.Refusal as exc:
            raise ValueError("declared PDK image is not locally attested") from exc
        return {"pdk": pdk, "image": image,
                "image_id": attestation["image_id"]}
    if provenance.get("source") != "local_provider":
        derivation = provenance["derivation"]
        return {"pdk": derivation["pdk"], "image": derivation["image"],
                "image_id": derivation["image_id"]}
    from librelane_signoff_evidence import _retained_local_provider
    try:
        provider = _retained_local_provider(
            project, provenance.get("provider"), provenance.get("identity"))
    except (ValueError, _ll.Refusal):
        raise ValueError("installed PDK LOCAL provider differs from producer") from None
    if (Path(provenance["path"]).resolve() != Path(provider.pdk_root).resolve() or
            not provenance.get("pdk") or
            (provider.pdk and provider.pdk != provenance["pdk"])):
        raise ValueError("installed PDK LOCAL provider differs from producer")
    # The named PDK witness and the tool's selected runtime are separate roles.
    # RCX and capture must retain the runtime identity they actually execute.
    image = _ll.resolve_image(project, record=False)
    provider = _ll._provider_for_image(image)
    if provider is None:
        raise ValueError("installed PDK LOCAL provider differs from producer")
    return {"pdk": provenance["pdk"], "image": image,
            "image_id": str(provider), "provider": provider.as_record()}


_IMAGE_PROBE = r'''
import hashlib, json, os, pathlib, sys
pdk, library = sys.argv[1:]
root = pathlib.Path(os.environ.get("PDK_ROOT", "/foss/pdks"))
suffix = (pdk, "libs.tech", "librelane", library, "config.tcl")
matches = [path for path in root.rglob("config.tcl")
           if path.is_file() and path.parts[-len(suffix):] == suffix]
if len(matches) != 1:
    raise SystemExit("expected exactly one installed PDK config, found %d" % len(matches))
path = matches[0]
parts = path.parts
version = parts[parts.index("versions") + 1] if "versions" in parts else None
print(json.dumps({"path": str(path),
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "pdk_commit": version}))
'''


def image_pdk_anchor(image: str, pdk: str, library: str) -> dict:
    """Return a fresh, image-owned source identity; fail closed on ambiguity."""
    if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", value)
               for value in (pdk, library)):
        raise ValueError("PDK/library identity invalid")
    # The same memory ceiling as every other container this plugin creates.
    network, command = _ll.native_tool_command(
        image, ["python3", "-c", _IMAGE_PROBE, pdk, library])
    provider = _ll._provider_for_image(image)
    environment = ["-e", "PDK_ROOT=" + provider.pdk_root] if provider else []
    process = _ll.run_container(
        ["docker", "run", *_docker_memory.docker_memory_flags(), "--rm", "--network", network,
         *environment, image, "--skip", *command],
        probe_deadline_s=90)
    if process.returncode:
        raise ValueError("installed PDK config probe failed: " + process.stderr[-300:])
    try:
        record = json.loads(process.stdout.strip().splitlines()[-1])
        if not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            raise ValueError("image PDK digest malformed")
        return record
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("installed PDK config identity unreadable") from exc
