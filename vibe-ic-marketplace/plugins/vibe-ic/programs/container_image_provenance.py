#!/usr/bin/env python3
"""container_image_provenance.py — record, and on request enforce, which IMAGE the run's `--container` actually executes.

Why this exists
---------------
Every containerised step in the flow is dispatched as
`docker exec <container> ...`, so `--container` names a **container**, not an
image. Nothing in the runner ever asked which image that container was started
from. Two consequences, both measured on a real sign-off run:

  1. **Stale-container substitution (silent).** The default container name
     resolves to whatever long-running container happens to exist. An operator
     who has pulled and intends to run image `X` can have the entire run execute
     on an older image `Y` — every tool version, every PDK, every sign-off
     number — with NOTHING in the run record naming `Y`. The run looks clean and
     is attributed to the wrong toolchain.

  2. **Image-ref passed as a container name (soft degradation).** Passing the
     natural thing — an image ref like `repo/name:tag` — matches no container, so
     `docker exec` fails for every step. The runner does not stop; steps fall
     through to their "container unavailable" branches (e.g. the SV-frontend
     fallback reports `could not create container workdir`) and the run reports a
     downstream tool FAILURE rather than the real cause.

This program makes the image identity FIRST-CLASS: recorded always, enforced on
request. It is chip-, PDK- and tool-AGNOSTIC.

Usage
-----
    container_image_provenance.py --container vibeic-eda
    container_image_provenance.py --container vibeic-eda \\
        --require-image vibeic-eda:0.2.30 --json reports/container_image.json

Exit codes
----------
    0 = identity resolved (and matched --require-image when given), OR an
        honest SKIP (docker binary absent). The JSON always says which.
    1 = the named container does not exist
    2 = the container exists but its image does not match --require-image
    3 = usage / io error
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

_INSPECT_FMT = (
    "{{.Name}}\t{{.Config.Image}}\t{{.Image}}\t{{.State.Running}}\t{{.Created}}"
)


def looks_like_image_ref(value: str) -> bool:
    """Heuristic: does this string look like an IMAGE ref rather than a
    container name? Used ONLY to enrich the error message — never to change
    behaviour, so a container legitimately named with a ':' is unaffected."""
    return ":" in value or "/" in value


def inspect_container(name: str) -> Dict[str, object]:
    """Return the container's image identity, or an explicit not-found record.

    Never raises and never fabricates: a missing docker binary is reported as
    `docker_absent`, not as a pass."""
    if shutil.which("docker") is None:
        return {"status": "docker_absent", "container": name}
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--format", _INSPECT_FMT, name],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "inspect_error", "container": name, "error": str(exc)}

    if proc.returncode != 0:
        return {
            "status": "not_found",
            "container": name,
            "stderr": (proc.stderr or "").strip(),
        }

    parts = (proc.stdout or "").strip().split("\t")
    if len(parts) < 5:
        return {
            "status": "inspect_error",
            "container": name,
            "error": "unexpected docker inspect output: " + repr(proc.stdout),
        }
    return {
        "status": "ok",
        "container": parts[0].lstrip("/"),
        "image_ref": parts[1],
        "image_id": parts[2],
        "running": parts[3] == "true",
        "created": parts[4],
    }


def _resolve_image_id(ref: str) -> Optional[str]:
    """Resolve an image ref to its content-addressed id, so `--require-image`
    can be given as a tag OR an id and still compare correctly."""
    if shutil.which("docker") is None:
        return None
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", ref],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or "").strip() or None if proc.returncode == 0 else None


#: `sha256:<64 hex>` — the exact identity shape, the SAME spelling `_eda_pin`
#: uses. Kept as a literal fallback only for the case where `_eda_pin` cannot be
#: imported; `_registry_digest_of` prefers the pin module so there is one
#: authority on what a digest is.
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _registry_digest_of(ref: Optional[str]) -> Optional[str]:
    """The REGISTRY digest `ref` names — from `<repo>@sha256:…` or from a bare
    `sha256:…` — else None.

    A bare `sha256:<hex>` is genuinely ambiguous: it is the spelling of a local
    config Id (`docker inspect --format '{{.Image}}'`) AND the spelling of a
    manifest digest (`_eda_pin.IMAGE_DIGEST`). This returns it under the second
    reading; `verify` tries the first reading separately, so both are honoured
    and neither is guessed at.
    """
    if not ref:
        return None
    ref = str(ref).strip()
    try:
        import _eda_pin as _pin
        named = _pin.reference_digest(ref)
        if named:
            return named
        return ref if _pin.DIGEST_RE.match(ref) else None
    except Exception:                                       # noqa: BLE001
        head, sep, tail = ref.partition("@")
        if sep and head and _DIGEST_RE.match(tail):
            return tail
        return ref if _DIGEST_RE.match(ref) else None


def _repo_digests_of(image: str) -> "tuple[tuple[str, ...], str]":
    """`(repo_digests, why_not)` of the image `image` names, LOCAL metadata only.

    Delegates to `_eda_pin.local_repo_digests`, which already owns the docker
    call and the `{{json .RepoDigests}}` parsing (including the tab-field quirk
    the repo's fake docker produces). Never touches the network.
    """
    try:
        import _eda_pin as _pin
        return _pin.local_repo_digests(image)
    except Exception as exc:                                # noqa: BLE001
        return (), f"repo digests unreadable: {type(exc).__name__}: {exc}"


def verify(container: str, require_image: Optional[str] = None) -> Dict[str, object]:
    """Resolve identity and compare against `require_image` when supplied."""
    rec = inspect_container(container)

    if rec["status"] == "docker_absent":
        # The canonical runner may already be inside the pinned image. Reuse
        # the same host-CID proof as LibreLane and native installation admission;
        # an image string in the environment is never execution evidence.
        try:
            from librelane_contract import local_image_attestation
            identity = local_image_attestation(require_image)
        except Exception as exc:
            rec["verdict"] = "SKIP"
            rec["reason"] = (
                "docker binary not on PATH — image identity unverifiable: "
                f"{type(exc).__name__}: {exc}")
            return rec
        rec.update(status="ok", execution_route="local",
                   requested_container=container, container=identity["cid"],
                   image_ref=identity["image"], image_id=identity["image_id"],
                   image_repo_digests=identity["repo_digests"], running=True,
                   attestation_path=identity["attestation_path"],
                   attestation_sha256=identity["attestation_sha256"],
                   matched_by="host_cid_attestation", verdict="PASS",
                   reason="resolved current LOCAL container %s -> %s (%s)" % (
                       identity["cid"], identity["image"], identity["image_id"][:19]))
        if require_image:
            rec.update(require_image=require_image, image_match=True)
        return rec

    if rec["status"] == "not_found":
        rec["verdict"] = "FAIL"
        reason = "no container named %r" % container
        if looks_like_image_ref(container):
            # The hint must be a command that actually WORKS — and which plain
            # `docker run` form works is a property of the IMAGE, not of this
            # program, so the hint must not commit to one of them.
            #
            # An earlier revision asserted that `<image> --skip sleep infinity`
            # "exits immediately, because its container command is the literal
            # --skip", and replaced it with a bare `<image> sleep infinity`.
            # MEASURED on the image this repo ships
            # (ghcr.io/vibeic/vibeic-eda:0.2.30, docker 29.6.2):
            #
            #   docker inspect --format '{{.Config.Entrypoint}} {{.Config.Cmd}}'
            #     -> [/dockerstartup/scripts/ui_startup.sh] [--wait]
            #   run ... <image> --skip sleep infinity -> Running=true  Exit=0
            #   run ... <image> sleep infinity        -> Running=false Exit=1
            #        docker logs: [ERROR] Unexpected option "sleep"
            #
            # i.e. exactly backwards: because the image declares an ENTRYPOINT
            # launcher, trailing args are that launcher's FLAGS, and `--skip` is
            # the documented flag meaning "skip the UI startup and exec the
            # given command". The repo's own tooling already agrees —
            # tools/vibeic-eda/restart-eda.sh uses `CMD=( --skip sleep infinity )`
            # and tools/vibeic-eda/README.md documents the same form.
            #
            # Neither form is universally right: an image with NO entrypoint
            # launcher needs the bare command. So name BOTH and say which
            # applies when, instead of hardcoding a guess about one image's
            # entrypoint into a general program. chip-, tool- and image-AGNOSTIC.
            # `--init` is part of the suggestion, not decoration. The command below
            # makes `sleep` PID 1, and PID 1 owns reaping; `sleep` never calls wait(),
            # so every orphaned tool becomes a permanent zombie — and a zombie reports
            # its LIFETIME-AVERAGE %CPU, which makes an idle host read as busy in every
            # check that asks. Measured: 11 defunct yosys printing 96.5 / 89.1 / 16.5 on
            # a host with one running process (vibeic-eda#65).
            reason += (
                " — this looks like an IMAGE ref. --container names a CONTAINER "
                "(docker exec <container>), not an image. Start one first: "
                "tools/vibeic-eda/restart-eda.sh (it pins the tag and then "
                "verifies the container's image id), or plainly: "
                "docker run -d --init --memory 48g --memory-swap 48g "
                "--name <name> %s sleep infinity — and if the "
                "image declares an ENTRYPOINT launcher, pass its skip flag "
                "before the command, e.g. "
                "docker run -d --init --memory 48g --memory-swap 48g "
                "--name <name> %s --skip sleep infinity "
                "(check `docker image inspect --format "
                "'{{.Config.Entrypoint}}' %s`)." % (container, container,
                                                    container)
            )
        rec["reason"] = reason
        return rec

    if rec["status"] != "ok":
        rec["verdict"] = "FAIL"
        rec.setdefault("reason", "container inspect failed")
        return rec

    # A CONTAINER THAT IS NOT RUNNING CANNOT EXECUTE THE TOOLCHAIN IT NAMES.
    # `inspect_container` has always reported `running` (parts[3] of
    # _INSPECT_FMT) and this decision never consulted it, so the pin was keyed
    # on the container EXISTING and carrying the right image -- not on it being
    # able to run anything. `--require-image`'s own CLI help has always read
    # "image ref or id the container MUST be running": the intent was
    # documented and unimplemented.
    #
    # MEASURED 2026-09-07 on 8HD-6 (lane rbsha4), from docker's own timestamps:
    # a container was created at 08:52:39.748Z and EXITED at 08:52:39.942Z; a
    # run launched at 08:52:44Z with --require-image was NOT refused, and one
    # step later the run said so itself -- "[#902 sim-toolchain DIVERGED]
    # container was declared (image ...) but verilator ran on the HOST ... the
    # run VERIFIED one toolchain and USED another". The ABSENT-container branch
    # above already refuses for exactly this reason ("every step verdict from
    # here would be measured against a toolchain this run cannot attest to");
    # a named-but-dead container reaches the same end by a quieter road, and
    # #902 caught the consequence one step later and per-tool, not the pin.
    #
    # Placed BEFORE the require_image comparison on purpose: the image a dead
    # container "runs" is not a toolchain any step will execute, so MISMATCH vs
    # match is not the question worth answering about it.
    if not rec.get("running"):
        rec["verdict"] = "FAIL"
        rec["reason"] = (
            "container %r exists but is NOT RUNNING, so it can execute nothing "
            "and every tool would silently fall back to the host: the run would "
            "be measured against a toolchain it cannot attest to. Start it, e.g. "
            "docker start %s (or recreate it), then re-run."
            % (container, container))
        return rec

    rec["verdict"] = "PASS"
    rec["reason"] = "resolved %s -> %s (%s)" % (
        container, rec["image_ref"], rec["image_id"][:19])

    if require_image:
        want_id = _resolve_image_id(require_image)
        got_id = rec["image_id"]
        matched = (require_image == rec["image_ref"]
                   or require_image == got_id
                   or (want_id is not None and want_id == got_id))
        rec["require_image"] = require_image
        rec["require_image_id"] = want_id

        # ── A REGISTRY DIGEST IS NOT A CONFIG DIGEST, AND BOTH NAME THE IMAGE ──
        # Everything above compares `require_image` against the CONFIG digest
        # (`docker inspect --format '{{.Image}}'`) or against the literal string
        # the container was started with. The plugin's own pin is neither: it is
        # a MANIFEST digest (`_eda_pin.IMAGE_DIGEST`), which docker records on
        # the image as a RepoDigest and which `docker image inspect` cannot
        # resolve on its own — so `_resolve_image_id` returns None and the
        # comparison fell through to MISMATCH.
        #
        # MEASURED 2026-09-16 on 8HD-6 (lane icsha3), one container, one process:
        #   _eda_pin.pinned_image_present()
        #     -> ('192.168.1.112:5000/vibeic-eda@sha256:89a8fd72…', '')   # held
        #   verify('icsha3-eda', _eda_pin.IMAGE_DIGEST)
        #     -> MISMATCH "…(unresolved)… the run would silently execute a
        #        DIFFERENT toolchain than the one pinned"
        # The container ran EXACTLY those bytes. Two modules, one fact, opposite
        # answers — and the refusal a lane sees is indistinguishable from a real
        # stale-container substitution, which is the alarm this program exists to
        # raise. (The 2026-09-15 08:05->08:30 fleet correction is this same
        # confusion read the other way round.)
        #
        # This is NOT a relaxation. A RepoDigest belongs to the image the
        # container is actually running: matching one proves the container holds
        # the demanded bytes, which is a STRICTER statement than the tag equality
        # already accepted above. A genuinely stale container carries different
        # RepoDigests and still MISMATCHes — `test_stale_container_*` pins that.
        want_digest = _registry_digest_of(require_image)
        if not matched and want_digest is not None:
            held, why = _repo_digests_of(got_id)
            rec["image_repo_digests"] = list(held)
            if why:
                rec["repo_digest_probe"] = why
            if any(_registry_digest_of(d) == want_digest for d in held):
                matched = True
                rec["matched_by"] = "repo_digest"

        rec["image_match"] = matched
        if not matched:
            rec["verdict"] = "MISMATCH"
            held_note = ""
            if want_digest is not None:
                held = rec.get("image_repo_digests") or []
                held_note = (
                    "; that image's repo digests are %s" % (
                        ", ".join(str(h) for h in held) if held
                        else "none (%s)" % (rec.get("repo_digest_probe")
                                            or "the image records none")))
            rec["reason"] = (
                "container %r runs image %s (%s) but --require-image %s (%s) was "
                "demanded — the run would silently execute a DIFFERENT toolchain "
                "than the one pinned%s" % (
                    container, rec["image_ref"], got_id[:19],
                    require_image, (want_id or "unresolved")[:19], held_note)
            )
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--container", required=True,
                    help="container NAME the run dispatches docker exec to")
    ap.add_argument("--require-image", default=None,
                    help="image ref or id the container MUST be running; "
                         "mismatch exits 2")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the identity record here (always written, "
                         "whatever the verdict)")
    args = ap.parse_args(argv)

    rec = verify(args.container, args.require_image)

    if args.json_out:
        try:
            out = Path(args.json_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
        except OSError as exc:
            print("container_image_provenance: cannot write %s: %s"
                  % (args.json_out, exc), file=sys.stderr)
            return 3

    print("container_image_provenance: %s: %s" % (rec["verdict"], rec["reason"]))

    if rec["verdict"] == "MISMATCH":
        return 2
    if rec["verdict"] == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
