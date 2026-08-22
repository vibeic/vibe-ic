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


def verify(container: str, require_image: Optional[str] = None) -> Dict[str, object]:
    """Resolve identity and compare against `require_image` when supplied."""
    rec = inspect_container(container)

    if rec["status"] == "docker_absent":
        rec["verdict"] = "SKIP"
        rec["reason"] = "docker binary not on PATH — image identity unverifiable"
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
                "docker run -d --init --name <name> %s sleep infinity — and if the "
                "image declares an ENTRYPOINT launcher, pass its skip flag "
                "before the command, e.g. "
                "docker run -d --init --name <name> %s --skip sleep infinity "
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
        rec["image_match"] = matched
        if not matched:
            rec["verdict"] = "MISMATCH"
            rec["reason"] = (
                "container %r runs image %s (%s) but --require-image %s (%s) was "
                "demanded — the run would silently execute a DIFFERENT toolchain "
                "than the one pinned" % (
                    container, rec["image_ref"], got_id[:19],
                    require_image, (want_id or "unresolved")[:19])
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
