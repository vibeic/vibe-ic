#!/usr/bin/env python3
"""pytest_fleet_shard.py — run ONE targeted selection across several hosts and
merge the result into ONE report the landing gate can read, or refuse.

WHY THIS EXISTS
===============
The targeted pytest arm is 82-84% of a landing round (measured: 1612.26 s of a
1947.86 s round), and while it runs the host is idle — load 1.38 on 32 cores,
exactly one python3 above 20% CPU, for 2083 test cases. Four more 32-core hosts
sit at load < 2 beside it. The work is already file-parallel; only the SCHEDULE
is serial.

WHAT IT DOES NOT DO
===================
It does not touch the pytest progress protocol. Each selected file still runs in
its own supervisor process with its own protocol instance, so the
(schema, nonce, pid, seq) triple that refuses a stale or foreign event is
checked exactly as it is in a single-file run. That is why `-n 12` under xdist
is refused by the driver and this is not: xdist workers are CHILDREN of one
session interleaving into ONE event stream; these are independent sessions.

THREE RULES THIS FILE IS BUILT AROUND
=====================================
1. SAME CASES, SAME FILE ATTRIBUTION. The merged report is emitted in GLOBAL
   SELECTION ORDER, not shard order, and every suite keeps the file name the
   per-file driver gave it. Which host ran a file must be invisible in the
   report, or a red becomes unattributable and the NORECORD machinery — which
   derives the ran-file set from the `file` attribute — silently narrows.

2. A SHARD THAT FAILS TO REPORT IS A REFUSAL FOR THE WHOLE ARM. Not a smaller
   denominator. Every file that host was given becomes NORECORD by name, and
   the exit code is the driver's own RC_NORECORD. "Three of four hosts
   answered" is not a verdict; it is three quarters of one.

3. THE TRANSFER IS PART OF THE BUDGET. Preparing each host's tree is timed and
   printed with the same weight as the tests, because a 6x speedup that spends
   five minutes on rsync is not a 6x speedup.

WHAT IT DROPS, STATED HERE AND NOT FOLDED INTO THE SPEEDUP
==========================================================
The whole-selection aggregate session — one pytest process over every selected
file, which is the only arm that can see a failure that appears when file A runs
before file B — is NOT run by this layer. Sharding a selection across four
hosts partitions the order space; it cannot preserve it. This layer prints
`AGGREGATE_NOT_ASKED` and its caller must decide what to do about that. It is
never allowed to look like an aggregate that passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

RC_OK = 0
RC_RED = 1
RC_NORECORD = 2
RC_CANNOT_ASK = 3

_ROOT_TAG = "testsuites"
_PROCESS_SUFFIX = "::process_exit"
_DEFAULT_JOBS_PER_HOST = 16
_DEFAULT_STALL_AFTER = 300.0


@dataclass
class Shard:
    """One host's share of the selection and everything it reported back."""

    host: str
    tree: str
    files: List[str]
    index: int
    log_path: Path
    junit_path: Path
    jobs: int = _DEFAULT_JOBS_PER_HOST
    exclusive: bool = False
    rc: Optional[int] = None
    sentinel_rc: Optional[int] = None
    prepare_seconds: Optional[float] = None
    run_seconds: Optional[float] = None
    refusal: str = ""
    suites_by_file: Dict[str, List[ET.Element]] = field(default_factory=dict)
    process_suites: Dict[str, ET.Element] = field(default_factory=dict)
    norecord_reasons: Dict[str, str] = field(default_factory=dict)
    write_guard_reports: int = 0

    @property
    def refused(self) -> bool:
        return bool(self.refusal)


# ────────────────────────── selection and balancing ──────────────────────────

def read_selection(path: Path) -> List[str]:
    out: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def load_cost_map(path: Optional[Path]) -> Dict[str, float]:
    """Seconds per file from a previous round's merged JUnit, if offered.

    A cost map only changes WHICH host gets WHICH file. It can never change what
    is run or what is reported, so a stale or absent map degrades the wall clock
    and nothing else. That is why it is read defensively and never fails a run.
    """
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"FLEET_COSTMAP_UNUSABLE  {path} — balancing by file count only",
              flush=True)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: float(v) for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, (int, float)) and v >= 0}


def costmap_from_junit(junit: Path) -> Dict[str, float]:
    """Sum every case's `time` per source file from a merged xunit1 report."""
    cost: Dict[str, float] = {}
    try:
        root = ET.parse(str(junit)).getroot()
    except (OSError, ET.ParseError):
        return cost
    for suite in root.iter("testsuite"):
        name = suite.get("name") or ""
        if name.endswith(_PROCESS_SUFFIX):
            continue
        total = 0.0
        for case in suite.iter("testcase"):
            try:
                total += float(case.get("time") or 0.0)
            except ValueError:
                pass
        if name:
            cost[name] = cost.get(name, 0.0) + total
    return cost


def balance(selection: Sequence[str], n_bins: int,
            cost: Dict[str, float]) -> List[List[str]]:
    """Longest-processing-time-first onto `n_bins`.

    The arm's cost is concentrated: 90% of cases are under 0.1 s and the top ten
    FILES are half the case seconds. Splitting such a corpus evenly BY COUNT
    puts several of the heavy files on one host and makes that host the wall
    clock. LPT is the standard 4/3-approximation for exactly this shape and
    needs nothing but a per-file estimate.

    With no estimate it degrades to round-robin over the SELECTOR'S OWN ORDER,
    which is sorted by path — so consecutive files are directory neighbours and
    round-robin spreads each directory across all hosts rather than handing one
    host a whole cluster.
    """
    bins: List[List[str]] = [[] for _ in range(n_bins)]
    if not cost:
        for i, path in enumerate(selection):
            bins[i % n_bins].append(path)
        return bins
    loads = [0.0] * n_bins
    # Deterministic: ties broken by path, so the same inputs always shard the
    # same way and two rounds are comparable.
    ordered = sorted(selection, key=lambda p: (-cost.get(p, 0.0), p))
    for path in ordered:
        target = min(range(n_bins), key=lambda i: (loads[i], i))
        bins[target].append(path)
        loads[target] += cost.get(path, 0.0)
    return bins


# ─────────────────────────────── remote plumbing ──────────────────────────────

def _ssh(host: str, command: str, *, timeout: Optional[float] = None
         ) -> Tuple[int, str]:
    argv = ["ssh", "-n", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15", host, command]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"ssh to {host} exceeded {timeout}s"
    except OSError as exc:
        return 125, f"ssh to {host} could not start: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _scp_to(host: str, local: Path, remote: str) -> Tuple[int, str]:
    argv = ["scp", "-q", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15", str(local), f"{host}:{remote}"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 125, f"scp to {host} failed: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _scp_from(host: str, remote: str, local: Path) -> Tuple[int, str]:
    argv = ["scp", "-q", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15", f"{host}:{remote}", str(local)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 125, f"scp from {host} failed: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


_PREPARE_SCRIPT = r"""
set -u
TREE="$1"; SHA="$2"; ORIGIN="$3"
if [ -d "$TREE/.git" ] || [ -f "$TREE/.git" ]; then
  have="$(git -C "$TREE" rev-parse HEAD 2>/dev/null || echo none)"
  if [ "$have" = "$SHA" ]; then echo "PREPARE_OK reused $TREE"; exit 0; fi
fi
if [ -n "$ORIGIN" ]; then
  git -C "$ORIGIN" cat-file -e "$SHA^{commit}" 2>/dev/null \
    || git -C "$ORIGIN" fetch -q --all 2>/dev/null || true
  if [ -d "$TREE" ]; then git -C "$ORIGIN" worktree remove --force "$TREE" 2>/dev/null || rm -rf "$TREE"; fi
  git -C "$ORIGIN" worktree add -q --detach "$TREE" "$SHA" || exit 3
  echo "PREPARE_OK created $TREE"
  exit 0
fi
echo "PREPARE_FAIL no origin clone and no usable tree at $TREE"
exit 3
"""


#: The tools this suite actually gates on, counted in the suite itself:
#: `shutil.which("iverilog")` appears 228 times, `vvp` 114, `docker` 27,
#: `tclsh` 23, `yosys` 19, `verilator` 12, and the tail once or twice each. A
#: test that SKIPS when its tool is missing and PASSES when it is present makes
#: the verdict depend on WHICH HOST got the file — which is precisely what a
#: sharded arm must never do.
DEFAULT_CENSUS_TOOLS = (
    "iverilog", "vvp", "yosys", "verilator", "tclsh", "docker", "openroad",
    "klayout", "magic", "netgen", "ngspice", "sv2v", "quartus_sh", "gh", "git",
    "pdftotext", "tesseract", "soffice", "libreoffice", "python3", "pytest",
)

#: `which` is NECESSARY AND NOT SUFFICIENT, and this suite proved it. Two hosts
#: that agreed on every binary above still disagreed on SEVEN
#: `gds_geometry_signoff_wiring` cases, pass on one and skip on the other,
#: because that fixture does not ask `which klayout` — it calls the repo's own
#: `_klayout_launch.find_runner()`, which also considers an EDA container. So
#: the census additionally runs the suite's OWN capability resolvers, in the
#: candidate tree, and compares what THEY answer.
#: A probe is `<module>:<expression>`, evaluated ON THE HOST, IN THE CANDIDATE
#: TREE, with the module bound to `m` and the tree's programs dir to `PROGRAMS`.
#: An expression rather than a bare callable because the capability that moved
#: seven verdicts is COMPOSITE: a KLayout runner exists on all four hosts, and
#: on two of them it is a container whose bind mounts do not COVER the checkout,
#: so the fixture skips. `find_runner() is not None` answers True everywhere and
#: would have certified a fleet that then dropped seven cases.
DEFAULT_CAPABILITY_PROBES = (
    "_klayout_launch:"
    "(lambda r: r is not None and bool(r.covers(PROGRAMS)))(m.find_runner())",
)

_FINGERPRINT_SCRIPT = r"""
set -u
TREE="$1"; SUBDIR="$2"; PROBES="$3"; shift 3
cd "$TREE/$SUBDIR" 2>/dev/null || true
PROBES="$PROBES" python3 -c '
import json, os, pathlib, shutil, sys
PROGRAMS = pathlib.Path(os.getcwd()) / "programs"
sys.path.insert(0, str(PROGRAMS))
out = {"python": sys.version.split()[0]}
try:
    import pytest
    out["pytest"] = pytest.__version__
except Exception:
    out["pytest"] = None
out["tools"] = {t: bool(shutil.which(t)) for t in sys.argv[1:]}
caps = {}
for spec in filter(None, os.environ.get("PROBES", "").split("\n")):
    mod, _, expr = spec.partition(":")
    try:
        m = __import__(mod)
        caps[spec] = bool(eval(expr, {"m": m, "PROGRAMS": PROGRAMS}))
    except Exception as exc:
        caps[spec] = "UNASKABLE: %s" % type(exc).__name__
out["capabilities"] = caps
print(json.dumps(out, sort_keys=True))
' "$@"
"""


def host_fingerprint(host: str, tools: Sequence[str], tree: str, subdir: str,
                     probes: Sequence[str]) -> Tuple[Optional[dict], str]:
    """What this host would let the suite SEE, not merely that it is reachable."""
    cmd = ("bash -s -- "
           + " ".join(shlex.quote(x) for x in
                      [tree, subdir, "\n".join(probes), *tools]))
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, cmd]
    try:
        proc = subprocess.run(argv, input=_FINGERPRINT_SCRIPT,
                              capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"{exc}"
    if proc.returncode != 0:
        return None, (proc.stderr or "").strip()[:200]
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1]), ""
    except (ValueError, IndexError) as exc:
        return None, f"unreadable fingerprint: {exc}"


def fingerprint_diff(prints: Dict[str, dict]) -> List[str]:
    """Name every way two hosts would answer the SAME test differently."""
    diffs: List[str] = []
    hosts = sorted(prints)
    base_host = hosts[0]
    base = prints[base_host]
    for host in hosts[1:]:
        other = prints[host]
        for key in ("python", "pytest"):
            if base.get(key) != other.get(key):
                diffs.append(f"{key}: {base_host}={base.get(key)!r} "
                             f"{host}={other.get(key)!r}")
        bt = base.get("tools") or {}
        ot = other.get("tools") or {}
        for tool in sorted(set(bt) | set(ot)):
            if bt.get(tool) != ot.get(tool):
                diffs.append(
                    f"tool {tool}: {base_host}="
                    f"{'present' if bt.get(tool) else 'ABSENT'} "
                    f"{host}={'present' if ot.get(tool) else 'ABSENT'}")
        bc = base.get("capabilities") or {}
        oc = other.get("capabilities") or {}
        for cap in sorted(set(bc) | set(oc)):
            if bc.get(cap) != oc.get(cap):
                diffs.append(f"capability {cap}: {base_host}={bc.get(cap)!r} "
                             f"{host}={oc.get(cap)!r}")
    return diffs


def prepare_host(host: str, tree: str, sha: str, origin: str
                 ) -> Tuple[bool, float, str]:
    """Put the candidate commit on `host` at `tree`. Timed, because it counts."""
    t0 = time.monotonic()
    cmd = ("bash -s -- " + shlex.quote(tree) + " " + shlex.quote(sha)
           + " " + shlex.quote(origin))
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, cmd]
    try:
        proc = subprocess.run(argv, input=_PREPARE_SCRIPT, capture_output=True,
                              text=True, timeout=900)
        rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (subprocess.TimeoutExpired, OSError) as exc:
        rc, out = 125, f"prepare on {host} failed: {exc}"
    dt = time.monotonic() - t0
    return rc == 0, dt, out.strip()


_REMOTE_RUNNER = r"""
set -u
TREE="$1"; SUBDIR="$2"; SEL="$3"; JUNIT="$4"; JOBS="$5"; STALL="$6"; DRIVER="$7"
shift 7
rm -f "$JUNIT"
cd "$TREE/$SUBDIR" || { echo "FLEET_SHARD_END rc=90"; exit 90; }
# A DRIVER OUTSIDE THE SUBJECT TREE puts ITS OWN directory on the child's
# PYTHONPATH, not the subject's. Restoring the subject's `programs` keeps the
# session's import environment the same as an in-tree driver's, so measuring the
# scheduler does not quietly also change what the tests import.
case "$DRIVER" in
  "$TREE"/*) : ;;
  *) export PYTHONPATH="$TREE/$SUBDIR/programs${PYTHONPATH:+:$PYTHONPATH}" ;;
esac
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 "$DRIVER" \
  --selection "$SEL" --junit "$JUNIT" \
  --stall-after "$STALL" \
  --parallel-per-file \
  --fallback-jobs "$JOBS" \
  --stop-after-failures 0 \
  -- "$@"
rc=$?
echo "FLEET_SHARD_END rc=$rc"
exit 0
"""


def run_shard(shard: Shard, subdir: str, jobs: int, stall_after: float,
              pytest_argv: Sequence[str], run_id: str,
              driver: str = "programs/pytest_per_file_junit.py") -> None:
    """Ship the shard's selection, run the per-file driver, bring it all back."""
    remote_sel = f"/tmp/fleet_{run_id}_sel_{shard.index}.txt"
    remote_junit = f"/tmp/fleet_{run_id}_junit_{shard.index}.xml"
    local_sel = shard.log_path.parent / f"sel_{shard.index}.txt"
    local_sel.write_text("\n".join(shard.files) + "\n", encoding="utf-8")

    rc, out = _scp_to(shard.host, local_sel, remote_sel)
    if rc != 0:
        shard.refusal = f"selection could not be shipped: {out.strip()}"
        return

    cmd = ("bash -s -- " + " ".join(shlex.quote(x) for x in [
        shard.tree, subdir, remote_sel, remote_junit, str(jobs),
        str(stall_after), driver, *pytest_argv]))
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=10", "-o", "ConnectTimeout=15",
            shard.host, cmd]
    t0 = time.monotonic()
    try:
        with shard.log_path.open("wb") as log:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=log,
                                    stderr=subprocess.STDOUT)
            proc.communicate(_REMOTE_RUNNER.encode())
            shard.rc = proc.returncode
    except OSError as exc:
        shard.run_seconds = time.monotonic() - t0
        shard.refusal = f"ssh could not run the shard: {exc}"
        return
    shard.run_seconds = time.monotonic() - t0

    rc, out = _scp_from(shard.host, remote_junit, shard.junit_path)
    if rc != 0 or not shard.junit_path.exists():
        shard.refusal = (f"the shard report was not retrievable "
                         f"(scp rc={rc}): {out.strip()[:200]}")
        return


# ───────────────────────────── shard verification ─────────────────────────────

def verify_and_ingest(shard: Shard) -> None:
    """Decide whether this host ANSWERED, before believing a single case of it.

    A shard is only believed when ALL of these hold. Any one missing makes every
    file it was given UNKNOWN, because a partial answer read as a whole one is
    exactly how a landing gate stops being able to refuse anything.
    """
    if shard.refused:
        return
    try:
        log = shard.log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        shard.refusal = f"the shard log could not be read: {exc}"
        return

    # (1) The remote wrapper must have reached its own last line. Without this
    #     a dropped ssh channel and a finished run look the same from here.
    sentinel = [ln for ln in log.splitlines()
                if ln.startswith("FLEET_SHARD_END rc=")]
    if not sentinel:
        shard.refusal = ("the remote runner never reached its end sentinel — "
                         "the channel or the host was lost mid-shard")
        return
    try:
        shard.sentinel_rc = int(sentinel[-1].split("rc=", 1)[1].strip())
    except ValueError:
        shard.refusal = "the end sentinel carried no readable rc"
        return
    if shard.sentinel_rc == 90:
        shard.refusal = "the candidate tree was not usable on this host"
        return
    if shard.sentinel_rc == RC_CANNOT_ASK:
        shard.refusal = "the per-file driver could not be asked on this host"
        return

    # (2) The driver must have printed its own summary. A driver killed midway
    #     can still leave a parseable JUnit PREFIX; parseability is not
    #     completeness.
    if "=== pytest junit summary" not in log:
        shard.refusal = ("the per-file driver produced no summary — its record "
                         "is incomplete, not clean")
        return

    # (3) The driver must have been asked for exactly this shard's files.
    asked = None
    for line in log.splitlines():
        if line.startswith("  asked      "):
            try:
                asked = int(line.split()[-1])
            except ValueError:
                pass
    if asked is None or asked != len(shard.files):
        shard.refusal = (f"the driver reports asked={asked} but this shard is "
                         f"{len(shard.files)} file(s) — the denominators "
                         f"disagree")
        return

    # (4) The report must parse.
    try:
        root = ET.parse(str(shard.junit_path)).getroot()
    except (OSError, ET.ParseError) as exc:
        shard.refusal = f"the shard report did not parse: {exc}"
        return

    for line in log.splitlines():
        if line.startswith("NORECORD  "):
            rest = line[len("NORECORD  "):]
            parts = rest.split("  ", 1)
            if parts:
                shard.norecord_reasons[parts[0].strip()] = (
                    parts[1].strip() if len(parts) > 1 else "")

    own = set(shard.files)
    for suite in list(root):
        if suite.tag != "testsuite":
            continue
        name = suite.get("name") or ""
        if name.endswith(_PROCESS_SUFFIX):
            path = name[: -len(_PROCESS_SUFFIX)]
            if path in own:
                shard.process_suites[path] = suite
            continue
        if name in own:
            shard.suites_by_file.setdefault(name, []).append(suite)
        else:
            # A case that cannot be attributed to a file this host was given is
            # not a bonus; it means the report is about a different run.
            shard.refusal = (f"the shard report carries a suite named {name!r}, "
                             f"which is not in this shard's selection")
            return

    # (5) THE WRITE GUARD MUST HAVE REPORTED ON EVERY SESSION THIS HOST RAN.
    #     `gatekeeper-land.sh` refuses a green targeted arm whose output carries
    #     no `suite_write_guard:` line, because a green bought by quietly
    #     removing the guard looks exactly like an honest one. Moving the arm to
    #     four hosts moves that output off the gate's stdout, so the assertion
    #     has to be made HERE or it stops being made at all.
    shard.write_guard_reports = sum(
        1 for line in log.splitlines() if "suite_write_guard:" in line)
    recorded_here = len(shard.suites_by_file)
    if recorded_here and shard.write_guard_reports < recorded_here:
        shard.refusal = (
            f"only {shard.write_guard_reports} suite_write_guard report(s) for "
            f"{recorded_here} recorded file(s) — some session ran WITHOUT the "
            f"write guard, so 'the suite wrote nothing' was never checked "
            f"there")
        return


# ──────────────────────────────── merge ───────────────────────────────────────

def merge_global(selection: Sequence[str], shards: Sequence[Shard],
                 out_path: Path) -> int:
    """ONE report, in GLOBAL SELECTION ORDER, with per-file names untouched.

    The single-host driver writes suites in selection order, names each one
    after its file, and appends one `pytest_per_file_process` case per recorded
    file. This reproduces that EXACTLY, so which host ran a file leaves no trace
    in the report and a differential across two rounds compares like with like.
    """
    by_file: Dict[str, List[ET.Element]] = {}
    proc_by_file: Dict[str, ET.Element] = {}
    for shard in shards:
        if shard.refused:
            continue
        for path, suites in shard.suites_by_file.items():
            by_file.setdefault(path, []).extend(suites)
        proc_by_file.update(shard.process_suites)

    root = ET.Element(_ROOT_TAG, {"name": "pytest tests"})
    total = 0
    for path in selection:
        for suite in by_file.get(path, []):
            root.append(suite)
            total += len(list(suite.iter("testcase")))
        proc = proc_by_file.get(path)
        if proc is not None:
            root.append(proc)
            total += len(list(proc.iter("testcase")))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(str(out_path), encoding="utf-8",
                               xml_declaration=True)
    return total


def _suite_counts(suite: ET.Element) -> Tuple[int, int]:
    cases = 0
    red = 0
    for case in suite.iter("testcase"):
        cases += 1
        if any(child.tag in ("failure", "error") for child in case):
            red += 1
    return cases, red


# ──────────────────────────────── main ────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--selection", required=True)
    ap.add_argument("--junit", required=True)
    ap.add_argument("--host", action="append", default=[], metavar="USER@HOST",
                    help="a fleet host; repeat once per shard")
    ap.add_argument("--tree", required=True,
                    help="absolute path of the candidate worktree ON EACH HOST")
    ap.add_argument("--origin", default="",
                    help="a clone on each host that already has the objects; "
                         "the candidate worktree is created from it")
    ap.add_argument("--sha", default="",
                    help="the commit every host must be at; required unless "
                         "--no-prepare")
    ap.add_argument("--subdir", default=".",
                    help="path under the tree to run pytest from")
    ap.add_argument("--driver", default="programs/pytest_per_file_junit.py",
                    help="the per-file driver to run ON EACH HOST; relative "
                         "paths resolve under the tree's --subdir")
    ap.add_argument("--jobs-per-host", type=int, default=_DEFAULT_JOBS_PER_HOST)
    ap.add_argument("--stall-after", type=float, default=_DEFAULT_STALL_AFTER)
    ap.add_argument("--no-prepare", action="store_true",
                    help="assume every host already carries the candidate; the "
                         "transfer cost is then reported as 0 BECAUSE IT WAS "
                         "NOT PAID HERE, not because it is free")
    ap.add_argument("--cost-map", default=None,
                    help="json {file: seconds} used only for balancing")
    ap.add_argument("--cost-from-junit", default=None,
                    help="a previous merged report to derive the cost map from")
    ap.add_argument("--emit-cost-map", default=None,
                    help="write this round's per-file seconds here")
    ap.add_argument("--tool", action="append", default=[],
                    help="a tool whose presence must be IDENTICAL on every "
                         "host; repeat. Defaults to the tools this suite "
                         "actually gates on")
    ap.add_argument("--capability-probe", action="append", default=[],
                    metavar="MODULE:CALLABLE",
                    help="a resolver IN THE CANDIDATE TREE whose answer must be "
                         "identical on every host; repeat. `which` alone is not "
                         "enough — seven cases moved between pass and skip on "
                         "two hosts with identical binaries")
    ap.add_argument("--skip-homogeneity-check", action="store_true",
                    help="DO NOT USE FOR A LANDING VERDICT. Runs the shards on "
                         "hosts that were never proven equivalent, so a "
                         "pass/skip difference caused by the draw becomes "
                         "invisible. Present only so the preflight itself can "
                         "be measured against a run without it")
    ap.add_argument("--exclusive", action="append", default=[],
                    help="a selected file that must not run BESIDE any other "
                         "file on the same host; repeat. Such a file plants a "
                         "path in the shared tree and reverts it, which its "
                         "OWN write guard tolerates and a NEIGHBOUR's does "
                         "not")
    ap.add_argument("--exclusive-list", default=None,
                    help="a file of --exclusive paths, one per line")
    ap.add_argument("--keep-remote", action="store_true")
    ap.add_argument("pytest_argv", nargs=argparse.REMAINDER)
    a = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    pytest_argv = list(a.pytest_argv)
    if pytest_argv and pytest_argv[0] == "--":
        pytest_argv = pytest_argv[1:]
    if not pytest_argv:
        print("[SKIP] pytest_fleet_shard: no pytest command after `--`, so "
              "nothing was run — that is NOT a pass.", file=sys.stderr)
        return RC_CANNOT_ASK
    if not a.host:
        print("[SKIP] pytest_fleet_shard: no --host was given.",
              file=sys.stderr)
        return RC_CANNOT_ASK
    if not a.no_prepare and not a.sha:
        print("[SKIP] pytest_fleet_shard: --sha is required so every host can "
              "be proven to carry the SAME candidate.", file=sys.stderr)
        return RC_CANNOT_ASK

    sel_path = Path(a.selection)
    try:
        selection = read_selection(sel_path)
    except OSError as exc:
        print(f"[SKIP] pytest_fleet_shard: selection unreadable ({exc}).",
              file=sys.stderr)
        return RC_CANNOT_ASK
    if not selection:
        print("[SKIP] pytest_fleet_shard: the selection is EMPTY. An empty "
              "corpus is not evidence that anything passed.", file=sys.stderr)
        return RC_CANNOT_ASK

    run_id = f"{os.getpid()}_{int(time.time())}"
    work = Path(tempfile.mkdtemp(prefix="fleet_shard_"))
    t_round0 = time.monotonic()

    # ── HOMOGENEITY PREFLIGHT ──
    # MEASURED ON THIS FLEET, 2026-08-18: iverilog+yosys on one host, iverilog
    # only on a second, NEITHER on the other two. Five test outcomes moved
    # between `pass` and `skip` purely because of which host drew the file —
    # `test_generated_sv_compiles_if_iverilog` and four `mbist_wrapper_gen`
    # cases. A sharded arm whose verdict depends on the draw is not a verdict,
    # so this refuses BEFORE running rather than producing a fast wrong answer.
    census_tools = a.tool or list(DEFAULT_CENSUS_TOOLS)
    census_probes = a.capability_probe or list(DEFAULT_CAPABILITY_PROBES)
    if not a.skip_homogeneity_check:
        t_fp = time.monotonic()
        prints: Dict[str, dict] = {}
        errs: Dict[str, str] = {}
        fp_threads = []

        def _fp(h: str) -> None:
            got, err = host_fingerprint(h, census_tools, a.tree, a.subdir,
                                        census_probes)
            if got is None:
                errs[h] = err
            else:
                prints[h] = got

        for h in a.host:
            th = threading.Thread(target=_fp, args=(h,), daemon=True)
            th.start()
            fp_threads.append(th)
        for th in fp_threads:
            th.join()
        fp_seconds = time.monotonic() - t_fp
        print(f"FLEET_HOMOGENEITY  {fp_seconds:.2f}s  "
              f"answered={len(prints)}/{len(a.host)}", flush=True)
        diffs = fingerprint_diff(prints) if len(prints) > 1 else []
        if errs or diffs:
            for h, err in sorted(errs.items()):
                print(f"FLEET_HETEROGENEOUS  {h} could not be fingerprinted: "
                      f"{err}", flush=True)
            for d in diffs:
                print(f"FLEET_HETEROGENEOUS  {d}", flush=True)
            print("SHARD_NORECORD  the fleet is not homogeneous, so which host "
                  "drew a file would change its outcome — the arm is REFUSED, "
                  "not sharded", flush=True)
            for path in selection:
                print(f"NORECORD  {path}  the fleet failed its homogeneity "
                      f"preflight — this file's result is UNKNOWN, not clean")
            print("AGGREGATE_NOT_ASKED  no whole-selection session was run")
            print("=== pytest junit summary")
            print("  mode       fleet-shard")
            print(f"  asked      {len(selection)}")
            print("  recorded   0")
            print(f"  NORECORD   {len(selection)}")
            print("  NOTRUN     0")
            print("  red cases  0")
            print(f"  merged     {a.junit}  (0 test case(s))")
            merge_global(selection, [], Path(a.junit))
            return RC_NORECORD

    # ── TRANSFER, TIMED. It is in the budget or the speedup is not real. ──
    prepare_seconds = 0.0
    if not a.no_prepare:
        t0 = time.monotonic()
        results: Dict[str, Tuple[bool, float, str]] = {}
        threads = []

        def _prep(h: str) -> None:
            results[h] = prepare_host(h, a.tree, a.sha, a.origin)

        for h in a.host:
            th = threading.Thread(target=_prep, args=(h,), daemon=True)
            th.start()
            threads.append(th)
        for th in threads:
            th.join()
        prepare_seconds = time.monotonic() - t0
        for h in a.host:
            ok, dt, out = results.get(h, (False, 0.0, "no result"))
            print(f"FLEET_PREPARE  {h}  {dt:.2f}s  "
                  f"{'OK' if ok else 'FAILED'}  {out.splitlines()[-1] if out else ''}",
                  flush=True)
        failed = [h for h in a.host if not results.get(h, (False,))[0]]
        if failed:
            # A host that cannot be given the candidate is not a host that can
            # be dropped: dropping it silently shrinks the denominator.
            for h in failed:
                print(f"SHARD_NORECORD  {h}  the candidate tree could not be "
                      f"prepared", flush=True)
            print(f"FLEET_PREPARE_TOTAL  {prepare_seconds:.2f}s  "
                  f"FAILED_HOSTS={len(failed)}", flush=True)
            for path in selection:
                print(f"NORECORD  {path}  a fleet host could not be prepared — "
                      f"this file's result is UNKNOWN, not clean")
            print("AGGREGATE_NOT_ASKED  no whole-selection session was run")
            print("=== pytest junit summary")
            print("  mode       fleet-shard")
            print(f"  asked      {len(selection)}")
            print("  recorded   0")
            print(f"  NORECORD   {len(selection)}")
            print("  NOTRUN     0")
            print("  red cases  0")
            print(f"  merged     {a.junit}  (0 test case(s))")
            merge_global(selection, [], Path(a.junit))
            return RC_NORECORD
    print(f"FLEET_PREPARE_TOTAL  {prepare_seconds:.2f}s", flush=True)

    # ── BALANCE ──
    cost = load_cost_map(Path(a.cost_map) if a.cost_map else None)
    if not cost and a.cost_from_junit:
        cost = costmap_from_junit(Path(a.cost_from_junit))
        if cost:
            print(f"FLEET_COSTMAP  {len(cost)} file(s) from "
                  f"{a.cost_from_junit}", flush=True)
    # ── THE EXCLUSIVE LANE ──
    # A file that plants a path in the shared tree and reverts it passes its OWN
    # write guard and fails every NEIGHBOUR's, because the neighbour snapshots
    # before and compares after. MEASURED on this suite: four such paths, from
    # two selected files, cost twelve otherwise-green sessions a non-zero
    # process rc. Ordering cannot fix it — the damage is concurrent, not prior —
    # so those files get a host on which nothing else runs.
    exclusive = list(a.exclusive)
    if a.exclusive_list:
        try:
            exclusive += read_selection(Path(a.exclusive_list))
        except OSError as exc:
            print(f"[SKIP] pytest_fleet_shard: --exclusive-list unreadable "
                  f"({exc}).", file=sys.stderr)
            return RC_CANNOT_ASK
    exclusive = [p for p in selection if p in set(exclusive)]
    if exclusive and len(a.host) < 2:
        print("[SKIP] pytest_fleet_shard: an exclusive lane needs a host of "
              "its own, so at least two --host are required.", file=sys.stderr)
        return RC_CANNOT_ASK

    parallel_hosts = a.host[:-1] if exclusive else list(a.host)
    parallel_files = [p for p in selection if p not in set(exclusive)]
    bins = balance(parallel_files, len(parallel_hosts), cost)
    shards = [Shard(host=h, tree=a.tree, files=bins[i], index=i,
                    log_path=work / f"shard_{i}.log",
                    junit_path=work / f"shard_{i}.xml",
                    jobs=a.jobs_per_host)
              for i, h in enumerate(parallel_hosts)]
    if exclusive:
        i = len(shards)
        shards.append(Shard(host=a.host[-1], tree=a.tree, files=exclusive,
                            index=i, log_path=work / f"shard_{i}.log",
                            junit_path=work / f"shard_{i}.xml",
                            jobs=1, exclusive=True))
    for s in shards:
        est = sum(cost.get(p, 0.0) for p in s.files)
        print(f"FLEET_SHARD  {s.index}  {s.host}  files={len(s.files)}  "
              f"width={s.jobs}{'  EXCLUSIVE' if s.exclusive else ''}  "
              f"estimated={est:.1f}s", flush=True)

    # ── RUN, ALL HOSTS AT ONCE ──
    t0 = time.monotonic()
    threads = []
    for s in shards:
        th = threading.Thread(
            target=run_shard,
            args=(s, a.subdir, s.jobs, a.stall_after, pytest_argv,
                  run_id, a.driver),
            daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    run_seconds = time.monotonic() - t0
    for s in shards:
        verify_and_ingest(s)
        print(f"FLEET_SHARD_DONE  {s.index}  {s.host}  "
              f"{(s.run_seconds or 0.0):.2f}s  ssh_rc={s.rc}  "
              f"driver_rc={s.sentinel_rc}  "
              f"{'REFUSED: ' + s.refusal if s.refused else 'reported'}",
              flush=True)

    # ── A SHARD THAT FAILED TO REPORT REFUSES THE WHOLE ARM ──
    refused = [s for s in shards if s.refused]
    for s in refused:
        print(f"SHARD_NORECORD  {s.host}  {s.refusal}", flush=True)

    total_cases = merge_global(selection, shards, Path(a.junit))

    recorded: List[str] = []
    norecord: List[Tuple[str, str]] = []
    empty: List[Tuple[str, int]] = []
    red_total = 0
    bad_rc = False
    owner = {p: s for s in shards for p in s.files}
    for path in selection:
        shard = owner.get(path)
        if shard is None or shard.refused:
            why = (shard.refusal if shard is not None
                   else "no host was given this file")
            norecord.append((path, why))
            continue
        suites = shard.suites_by_file.get(path, [])
        if not suites:
            norecord.append((path, shard.norecord_reasons.get(
                path, "the host reported no record for this file")))
            continue
        recorded.append(path)
        cases = 0
        for suite in suites:
            c, r = _suite_counts(suite)
            cases += c
            red_total += r
        if cases == 0:
            empty.append((path, 0))
        proc = shard.process_suites.get(path)
        if proc is not None:
            for prop in proc.iter("property"):
                if prop.get("name") == "process_rc" and prop.get("value") != "0":
                    bad_rc = True

    for path, why in norecord:
        # The per-file driver's own NORECORD text already ends in this clause;
        # re-appending it printed the sentence twice.
        tail = "" if "UNKNOWN, not clean" in why else (
            " — this file's result is UNKNOWN, not clean")
        print(f"NORECORD  {path}  {why}{tail}")
    for path, _ in empty:
        print(f"EMPTY     {path}  a report was written and it carries no test "
              f"case")

    if a.emit_cost_map:
        try:
            Path(a.emit_cost_map).write_text(
                json.dumps(costmap_from_junit(Path(a.junit)), indent=1,
                           sort_keys=True), encoding="utf-8")
        except OSError:
            pass

    guard_reports = sum(s.write_guard_reports for s in shards)
    print(f"suite_write_guard: {guard_reports} session report(s) across "
          f"{len(shards) - len(refused)} answering shard(s); every recorded "
          f"file's session reported")
    print("AGGREGATE_NOT_ASKED  the fleet shard layer runs no whole-selection "
          "session; cross-file/order semantics were NOT measured here")
    print("=== pytest junit summary")
    print("  mode       fleet-shard")
    print(f"  asked      {len(selection)}")
    print(f"  recorded   {len(recorded)}")
    print(f"  NORECORD   {len(norecord)}")
    print("  NOTRUN     0")
    print(f"  red cases  {red_total}")
    print(f"  hosts      {len(a.host)}  refused={len(refused)}")
    print(f"  prepare    {prepare_seconds:.2f}s")
    print(f"  shards     {run_seconds:.2f}s  "
          + "  ".join(f"[{s.index}]{(s.run_seconds or 0.0):.0f}s"
                      for s in shards))
    print(f"  round      {time.monotonic() - t_round0:.2f}s")
    print(f"  merged     {a.junit}  ({total_cases} test case(s))")

    if not a.keep_remote:
        for s in shards:
            _ssh(s.host, f"rm -f /tmp/fleet_{run_id}_sel_{s.index}.txt "
                         f"/tmp/fleet_{run_id}_junit_{s.index}.xml",
                 timeout=30)

    if norecord or refused:
        return RC_NORECORD
    if red_total or bad_rc:
        return RC_RED
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
