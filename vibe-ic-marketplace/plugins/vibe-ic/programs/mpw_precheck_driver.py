#!/usr/bin/env python3
"""mpw_precheck LIVE DRIVER (TAPEOUT-SIGNOFF P0#2, driver half).

RETIRED SHUTTLE (vibe-ic#1744) — READ THIS BEFORE TRUSTING A VERDICT FROM HERE
=============================================================================
The counterparty this program addresses, the Efabless/chipIgnite open-MPW
shuttle, CEASED OPERATING IN 2025. It no longer accepts submissions and it no
longer refuses them. Nothing below is broken; it is pointed at a party that
stopped answering.

That distinction is the whole point of keeping this file. A gate we wrote can
be made to pass by editing it; an external refusal cannot. This was the ONE
interface in the tree whose verdict was not ultimately ours, and it is now
aimed at nothing — so a run that produces no evidence here means
NOT DETERMINED, permanently, and never "nothing to worry about".

The LIVE external refusal is `tapeout_readiness_check.py`, which wraps the
shuttle operator's own tool for the currently-running open-MPW path. Ask that
one for a submittability verdict. This file is kept, not deleted, so the
retirement is on the record rather than looking like an orphan.

Doctrine: the Efabless/chipIgnite sky130 open-MPW shuttle gate is
`efabless/mpw_precheck` — a Docker suite that runs a fixed ladder of
license / makefile / default / documentation / consistency / gpio_defines /
XOR / Magic-DRC / KLayout-FEOL-BEOL-offgrid / LVS / oeb checks. Two plugin
pieces already exist:

  * `caravel_integration_runner.step_c1_run_precheck` — emits only the Docker
    *command_hint* and returns NOT_RUN (it PLANS, never RUNS).
  * `mpw_precheck_result_gate.py` — the deterministic PARSER GATE: it CONSUMES a
    COMPLETED precheck run directory and rolls it up to PASS / FAIL / INCOMPLETE
    / SKIPPED_CONDITION.

The missing piece — this program — is the DRIVER that actually RUNS the precheck
and feeds the parser: it resolves the precheck image, mounts the project + the
precheck source + the PDK, invokes `mpw_precheck.py` inside the container the
documented way (input_directory / pdk_path / output_directory / positional
checks — the interface the shipping `efabless/mpw_precheck` image exposes), then
calls `mpw_precheck_result_gate.evaluate()` on the produced run directory to get
an aggregate verdict.

§4.05 (absent evidence NEVER yields PASS): a PASS is only ever the parser gate's
own PASS on a REAL run directory that carries explicit PASSED evidence for every
required check. If the precheck did not actually run — image missing / unpullable,
the Docker orchestration itself failed, or the invocation produced no usable
output directory — the driver returns **BLOCKED** (or defers to the parser's
SKIPPED_CONDITION / INCOMPLETE). It NEVER fabricates a PASS.

Crucial honesty nuance: mpw_precheck exits NON-ZERO when a design check FAILS.
A non-zero container exit that STILL produced a real run directory with real
check logs is a legitimate **FAIL** (deferred to the parser) — NOT a BLOCKED and
NOT a fabricated pass. BLOCKED is reserved for the orchestration never producing
usable evidence at all (no run dir, or a run dir with no parseable logs).

Chip-AGNOSTIC: no chip name or project literal appears in any decision rule. The
project path, PDK path and check list are all parameters. Reuses the check ladder
and Docker command shape modelled by `caravel_integration_runner`.

CLI:
    python3 mpw_precheck_driver.py --input-directory <caravel_project> \\
        --pdk-root <pdk_parent> [--pdk-variant sky130A] \\
        [--precheck-src <project>/dependencies/mpw_precheck] \\
        [--image efabless/mpw_precheck:latest] [--pull] \\
        [--check license --check makefile ...] [--rundir <out>] \\
        [--timeout 3600] [--out-json driver_verdict.json]

Exit 0 = PASS (parser PASS on a real run). Exit 1 = FAIL / INCOMPLETE /
SKIPPED_CONDITION / BLOCKED (hard gate — anything that is not a clean pass).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
try:  # sibling module; programs/ is on sys.path when run as a script
    import _docker_memory as _dmem
except ImportError:  # pragma: no cover - packaged/flattened layouts
    from . import _docker_memory as _dmem  # type: ignore


try:  # sibling module; programs/ is on sys.path when run as a script
    import _watchdog as _wd
except ImportError:  # pragma: no cover - packaged/flattened layouts
    from . import _watchdog as _wd  # type: ignore


# Import the sibling parser gate the same way caravel_integration_runner imports
# its siblings (bare import when programs/ is on sys.path, package-relative else).
try:
    import mpw_precheck_result_gate as gate  # type: ignore
except ImportError:  # pragma: no cover - package-context fallback
    from . import mpw_precheck_result_gate as gate  # type: ignore


ATTRIBUTION = "mpw_precheck_driver (TAPEOUT-SIGNOFF P0#2 driver half)"

#: #1744 — this driver's counterparty ceased operating in 2025. See the RETIRED
#: SHUTTLE banner at the top of this file.
SHUTTLE_STATUS = "RETIRED"

#: `overall_verdict` -> how an aggregator should read it. The three verdicts that
#: mean "we obtained no external answer" all map to NOT_DETERMINED, and against a
#: RETIRED shuttle that state is permanent: there is no run that would clear it.
_VERDICT_CLASS: Dict[str, str] = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "BLOCKED": "NOT_DETERMINED",
    "INCOMPLETE": "NOT_DETERMINED",
    "SKIPPED_CONDITION": "NOT_DETERMINED",
}

# The canonical shuttle image. Overridable; kept identical to the reference the
# plugin already models in caravel_integration_runner.step_c1_run_precheck.
DEFAULT_IMAGE = "efabless/mpw_precheck:latest"

# The precheck ladder caravel_integration_runner.step_c1_run_precheck runs by
# default (the open-source-qualifying set that needs no heavy LVS/DRC deck). A
# caller wanting the full shuttle ladder passes the extra checks explicitly.
DEFAULT_CHECKS: Tuple[str, ...] = (
    "license", "makefile", "default", "documentation",
    "consistency", "gpio_defines", "xor",
)

# Where mpw_precheck.py lives inside the container once the precheck source tree
# is mounted (this mirrors the upstream docker-mount.sh convention).
_CONTAINER_PRECHECK_MOUNT = "/opt/mpw_precheck"

# Map a precheck positional check token -> the parser gate's canonical stage key
# so the driver can hand the parser the SAME required set it asked precheck to
# run. Tokens with no parser stage (should not occur for the standard ladder) are
# simply dropped from the required set with a note.
_CHECK_TO_STAGE: Dict[str, str] = {
    "license": "license",
    "makefile": "makefile",
    "default": "default",
    "documentation": "documentation",
    "consistency": "consistency",
    "gpio_defines": "gpio_defines",
    "gpio": "gpio_defines",
    "xor": "xor",
    "drc": "magic_drc",
    "magic_drc": "magic_drc",
    "klayout_feol": "klayout_feol",
    "klayout_beol": "klayout_beol",
    "klayout_offgrid": "klayout_offgrid",
    "lvs": "lvs",
    "oeb": "oeb",
}


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class DriverReport:
    input_directory: str
    image: str
    pdk_path: str
    precheck_src: str
    checks: List[str]
    ran: bool                       # did the container actually produce a run dir?
    overall_verdict: str            # BLOCKED / PASS / FAIL / INCOMPLETE / SKIPPED_CONDITION
    # #1744 — the shuttle this driver addresses is RETIRED. These two fields are
    # ADDITIVE on purpose: `overall_verdict` keeps its existing vocabulary so no
    # consumer's reading of it changes, and the retirement is published beside
    # it rather than by silently redefining a token others already parse.
    shuttle_status: str = SHUTTLE_STATUS
    # How an aggregator should read `overall_verdict`. BLOCKED against a retired
    # counterparty is NOT a transient orchestration hiccup to be retried — it is
    # permanent, and it is NOT_DETERMINED, which is neither a pass nor a design
    # failure. Naming it stops "the precheck did not run" from being filed next
    # to "the precheck ran and was fine".
    verdict_class: str = ""
    project: str = ""
    docker_returncode: Optional[int] = None
    rundir: Optional[str] = None
    gate_report: Optional[Dict[str, Any]] = None
    blocked_reason: str = ""
    command: List[str] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["verdict_class"] = self.verdict_class or _VERDICT_CLASS.get(
            self.overall_verdict, "NOT_DETERMINED")
        d["emitted_by"] = ATTRIBUTION
        return d


# Types for the two injectable seams (so the orchestration is unit-testable with
# NO live Docker image).
ImageResolver = Callable[[str, bool], Optional[str]]
# docker_runner(cmd, timeout) -> (returncode, stdout, stderr)
DockerRunner = Callable[[List[str], Optional[float]], Tuple[int, str, str]]


# --------------------------------------------------------------------------- #
# Default seam implementations (the live ones)
# --------------------------------------------------------------------------- #
def default_image_resolver(image: str, allow_pull: bool,
                           docker_bin: str = "docker") -> Optional[str]:
    """Return `image` if it is locally available (optionally pulling it), else None.

    Availability is checked with `docker images -q <image>` (empty stdout == not
    present). If `allow_pull` is set and the image is absent, a `docker pull` is
    attempted once. Any docker error (daemon down, docker not installed) resolves
    to None — the driver then reports BLOCKED rather than a fabricated result.
    """
    if not shutil.which(docker_bin):
        return None
    try:
        q = subprocess.run([docker_bin, "images", "-q", image],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if q.returncode == 0 and q.stdout.strip():
        return image
    if not allow_pull:
        return None
    try:
        p = subprocess.run([docker_bin, "pull", image],
                           capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError):
        return None
    return image if p.returncode == 0 else None


def default_docker_runner(cmd: List[str],
                          timeout: Optional[float]) -> Tuple[int, str, str]:
    """Run a docker command, returning (returncode, stdout, stderr).

    `timeout` is the STALL GRACE, not a runtime bound. As
    `subprocess.run(timeout=)` its expiry produced rc 124, which the driver
    books as the MPW precheck's own outcome — a verdict about the design read
    off a number that describes this host. The precheck's honest runtime moves
    with the layout and with host load, so a constant cannot be right for two
    designs. The watchdog kills only a container whose CPU, I/O and output have
    ALL sat flat for the grace, and the partial output is still returned, so a
    precheck that produced logs before it stopped is still parsed. `None` keeps
    its meaning of "no bound at all" and gets the module default grace, which
    still cannot end a job that is working.

    MEASURED: for a `docker run` invocation the launched process is the
    CLIENT, whose own /proc CPU sits FLAT for the whole run even while the
    container burns a full core (containerd-shim reparents the actual work,
    so it is never a ppid-chain descendant of the CLI on host /proc). Output
    growth is a real signal — `mpw_precheck.py` logs as it runs — but a
    silent stretch inside it would otherwise be indistinguishable from a
    hang. When the argv NAMES its container (`--name X`), its CPU is read
    directly by `docker exec`'ing `/proc` — no extra tool dependency, no
    reliance on `ps` being installed in the precheck image."""
    grace = (float(timeout) if timeout is not None
             else _wd.DEFAULT_STALL_GRACE_S)
    argv = [str(c) for c in cmd]
    cpu_probe = None
    if "--name" in argv:
        i = argv.index("--name")
        if i + 1 < len(argv):
            cname = argv[i + 1]

            def cpu_probe(_proc, _cname=cname):  # noqa: E731
                try:
                    r = subprocess.run(
                        ["docker", "exec", _cname, "sh", "-c",
                         "cat /proc/[0-9]*/stat 2>/dev/null"],
                        capture_output=True, text=True, timeout=15)
                except Exception:  # nosec
                    return None
                if r.returncode != 0 or not (r.stdout or "").strip():
                    return None
                tck = _wd._clk_tck()
                total, seen = 0.0, False
                for line in r.stdout.splitlines():
                    cut = line.rfind(")")
                    if cut < 0:
                        continue
                    rest = line[cut + 2:].split()
                    if len(rest) < 13:
                        continue
                    try:
                        total += (float(rest[11]) + float(rest[12])) / tck
                        seen = True
                    except ValueError:  # nosec
                        continue
                return total if seen else None
    res = _wd.run_host_supervised(argv, stall_grace_s=grace,
                                  cpu_probe=cpu_probe)
    if res.outcome == "launch_error":
        # This seam used to let a missing docker binary raise FileNotFoundError
        # out of the function; the supervisor resolves that to a result
        # instead, so it is re-raised here and the contract its callers were
        # written against is unchanged.
        raise FileNotFoundError(res.err)
    return res.rc, res.out or "", res.err or ""


# --------------------------------------------------------------------------- #
# Command construction
# --------------------------------------------------------------------------- #
def _uid_gid() -> str:
    """`uid:gid` for `docker run -u` so the container writes host-owned files.

    Falls back to an empty string on platforms without getuid (the caller then
    omits the -u flag)."""
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:  # pragma: no cover - non-POSIX
        return ""
    return f"{getuid()}:{getgid()}"


def build_docker_command(
    image: str,
    input_directory: Path,
    pdk_root: Path,
    pdk_path: Path,
    precheck_src: Path,
    rundir: Path,
    checks: List[str],
    docker_bin: str = "docker",
) -> List[str]:
    """Assemble the `docker run … mpw_precheck.py …` argv.

    Mirrors upstream docker-mount.sh + run_precheck.sh: the precheck source is
    mounted at /opt/mpw_precheck, the project and the PDK are mounted at their own
    absolute paths (so in-container paths == host paths), and the run directory is
    written under the project mount so the host can read it back for parsing.
    """
    input_directory = input_directory.resolve()
    pdk_root = pdk_root.resolve()
    pdk_path = pdk_path.resolve()
    precheck_src = precheck_src.resolve()
    rundir = rundir.resolve()

    # Named uniquely so `default_docker_runner` can read this container's OWN
    # CPU instead of the `docker run` client's, which never sees it.
    cname = f"vibeic_mpw_{os.getpid()}_{time.time_ns() & 0xFFFFFFFF:x}"
    cmd: List[str] = [docker_bin, "run", "--rm", "--name", cname,
                      *_dmem.docker_memory_flags()]
    uidgid = _uid_gid()
    if uidgid:
        cmd += ["-u", uidgid]
    cmd += [
        "-v", f"{precheck_src}:{_CONTAINER_PRECHECK_MOUNT}",
        "-v", f"{input_directory}:{input_directory}",
        "-v", f"{pdk_root}:{pdk_root}",
    ]
    # If the run directory is NOT already under the project mount, mount it too so
    # the container can write the results where the host will read them.
    if not _is_relative_to(rundir, input_directory):
        rundir.mkdir(parents=True, exist_ok=True)
        cmd += ["-v", f"{rundir}:{rundir}"]
    cmd += [
        "-e", f"INPUT_DIRECTORY={input_directory}",
        "-e", f"PDK_PATH={pdk_path}",
        "-e", f"PDK_ROOT={pdk_root}",
        image,
        "bash", "-c",
        (f"cd {_CONTAINER_PRECHECK_MOUNT} && "
         f"python3 mpw_precheck.py "
         f"--input_directory {input_directory} "
         f"--pdk_path {pdk_path} "
         f"--output_directory {rundir} "
         + " ".join(checks)),
    ]
    return cmd


def _is_relative_to(child: Path, parent: Path) -> bool:
    """Path.is_relative_to backport (py<3.9 safe)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _default_tag() -> str:
    return time.strftime("%d_%b_%Y___%H_%M_%S").upper()


def _required_stages(checks: List[str]) -> Tuple[List[str], List[str]]:
    """Map precheck check tokens to parser stage keys. Returns (stages, dropped)."""
    stages: List[str] = []
    dropped: List[str] = []
    for c in checks:
        key = _CHECK_TO_STAGE.get(c.lower())
        if key and key not in stages:
            stages.append(key)
        elif key is None:
            dropped.append(c)
    return stages, dropped


def drive(
    input_directory: Path,
    pdk_root: Path,
    pdk_variant: str = "sky130A",
    pdk_path: Optional[Path] = None,
    precheck_src: Optional[Path] = None,
    image: str = DEFAULT_IMAGE,
    checks: Optional[List[str]] = None,
    rundir: Optional[Path] = None,
    project: str = "",
    timeout: Optional[float] = 3600.0,
    allow_pull: bool = False,
    image_resolver: Optional[ImageResolver] = None,
    docker_runner: Optional[DockerRunner] = None,
    docker_bin: str = "docker",
) -> DriverReport:
    """Resolve the image, run the precheck in Docker, feed the parser gate.

    Injectable seams (`image_resolver`, `docker_runner`) let the orchestration +
    parser-feed be unit-tested with NO live Docker image. §4.05 is enforced here:
    a PASS is only ever the parser gate's PASS on a REAL produced run directory.
    """
    checks = list(checks) if checks else list(DEFAULT_CHECKS)
    pdk_path = pdk_path or (pdk_root / pdk_variant)
    precheck_src = precheck_src or (input_directory / "dependencies" / "mpw_precheck")
    if rundir is None:
        rundir = input_directory / "precheck_results" / _default_tag()
    resolver = image_resolver or default_image_resolver
    runner = docker_runner or default_docker_runner

    def _blocked(reason: str, cmd: Optional[List[str]] = None,
                 rc: Optional[int] = None) -> DriverReport:
        return DriverReport(
            input_directory=str(input_directory), image=image,
            pdk_path=str(pdk_path), precheck_src=str(precheck_src),
            checks=checks, ran=False, overall_verdict="BLOCKED",
            project=project, docker_returncode=rc, rundir=str(rundir),
            blocked_reason=reason, command=cmd or [],
            notes="§4.05: precheck did not produce usable evidence — BLOCKED, "
                  "never a fabricated PASS. #1744: this shuttle is RETIRED "
                  "(operator ceased operating in 2025), so read this as "
                  "NOT_DETERMINED and PERMANENT — no retry clears it. The live "
                  "external refusal is tapeout_readiness_check.")

    # (1) Resolve the image (availability / optional pull).
    resolved = resolver(image, allow_pull)
    if not resolved:
        return _blocked(
            f"precheck image '{image}' is not available"
            + (" and could not be pulled" if allow_pull else "")
            + f". Pull it with: {docker_bin} pull {image}")

    # (2) Validate the on-disk inputs the container will need.
    if not input_directory.exists():
        return _blocked(f"input directory does not exist: {input_directory}")
    precheck_entry = precheck_src / "mpw_precheck.py"
    if not precheck_entry.exists():
        return _blocked(
            f"mpw_precheck.py not found under precheck source '{precheck_src}'. "
            "Clone it (git clone https://github.com/efabless/mpw_precheck) or "
            "point --precheck-src at the project's dependencies/mpw_precheck.")
    if not pdk_path.exists():
        return _blocked(
            f"PDK variant path does not exist: {pdk_path}. Install the sky130 PDK "
            "(e.g. via volare) and pass --pdk-root <PDK_ROOT> [--pdk-variant sky130A].")

    # (3) Build + run the container.
    rundir.mkdir(parents=True, exist_ok=True)
    cmd = build_docker_command(
        resolved, input_directory, pdk_root, pdk_path, precheck_src,
        rundir, checks, docker_bin=docker_bin)
    try:
        rc, out, err = runner(cmd, timeout)
    except Exception as e:  # noqa: BLE001 - any orchestration crash is a BLOCK
        return _blocked(f"docker orchestration raised: {e!r}", cmd=cmd)

    # (4) Feed the parser gate on the produced run directory.
    #
    # Honesty nuance: a NON-ZERO container exit that STILL produced a real run
    # directory with parseable check logs is a legitimate design FAIL — we defer
    # to the parser, NOT BLOCKED. BLOCKED is only for "no usable evidence at all".
    stages, dropped = _required_stages(checks)
    gate_rep = gate.evaluate(rundir, required=stages or None, project=project)
    gate_dict = gate_rep.as_dict()

    if gate_rep.overall_verdict == "SKIPPED_CONDITION":
        # The container ran but produced no parseable precheck evidence — treat as
        # an orchestration BLOCK, never a pass (§4.05).
        rep = _blocked(
            "precheck container exited (rc="
            f"{rc}) but produced no parseable run directory / logs at {rundir} — "
            "the precheck did not actually complete a check ladder.",
            cmd=cmd, rc=rc)
        rep.gate_report = gate_dict
        rep.stdout_tail = out[-4000:]
        rep.stderr_tail = err[-4000:]
        return rep

    notes = ""
    if dropped:
        notes = ("requested check(s) with no parser stage were not gated: "
                 + ", ".join(dropped))

    return DriverReport(
        input_directory=str(input_directory), image=resolved,
        pdk_path=str(pdk_path), precheck_src=str(precheck_src),
        checks=checks, ran=True,
        overall_verdict=gate_rep.overall_verdict,   # PASS / FAIL / INCOMPLETE
        project=project, docker_returncode=rc, rundir=str(rundir),
        gate_report=gate_dict, command=cmd,
        stdout_tail=out[-4000:], stderr_tail=err[-4000:], notes=notes)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="mpw_precheck LIVE driver — resolve the efabless/mpw_precheck "
                    "image, run it on a Caravel-shaped project, and feed the "
                    "mpw_precheck_result_gate parser for an aggregate verdict "
                    "(§4.05: absent/failed run → BLOCKED, never a fabricated PASS).")
    p.add_argument("--input-directory", type=Path, required=True,
                   help="Absolute path to the Caravel-shaped project.")
    p.add_argument("--pdk-root", type=Path, required=True,
                   help="PDK_ROOT (the parent that holds the PDK variant dir).")
    p.add_argument("--pdk-variant", default="sky130A",
                   help="PDK variant dir name under --pdk-root (default sky130A).")
    p.add_argument("--pdk-path", type=Path, default=None,
                   help="Explicit pdk_path; default <pdk-root>/<pdk-variant>.")
    p.add_argument("--precheck-src", type=Path, default=None,
                   help="mpw_precheck source tree (holds mpw_precheck.py). "
                        "Default <input-directory>/dependencies/mpw_precheck.")
    p.add_argument("--image", default=DEFAULT_IMAGE,
                   help=f"Precheck Docker image (default {DEFAULT_IMAGE}).")
    p.add_argument("--pull", action="store_true",
                   help="Attempt `docker pull` if the image is not local.")
    p.add_argument("--check", action="append", default=[], dest="checks",
                   metavar="CHECK",
                   help="Precheck check token to run (repeatable). Default: the "
                        "open-source ladder license makefile default documentation "
                        "consistency gpio_defines xor.")
    p.add_argument("--rundir", type=Path, default=None,
                   help="Explicit output run directory (default "
                        "<input-directory>/precheck_results/<timestamp>).")
    p.add_argument("--project", default="",
                   help="Optional label for the report (chip-AGNOSTIC — never used "
                        "in a decision rule).")
    p.add_argument("--timeout", type=float, default=3600.0,
                   help="Docker run timeout in seconds (default 3600).")
    p.add_argument("--out-json", type=Path,
                   help="Also write the driver verdict JSON to this path.")
    args = p.parse_args(argv)

    rep = drive(
        input_directory=args.input_directory,
        pdk_root=args.pdk_root,
        pdk_variant=args.pdk_variant,
        pdk_path=args.pdk_path,
        precheck_src=args.precheck_src,
        image=args.image,
        checks=args.checks or None,
        rundir=args.rundir,
        project=args.project,
        timeout=args.timeout,
        allow_pull=args.pull,
    )
    payload = rep.as_dict()
    text = json.dumps(payload, indent=2)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(text, encoding="utf-8")
    print(text)
    return 0 if rep.overall_verdict == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
