#!/usr/bin/env python3
"""Fail-closed aggregate-RAM admission for independently launched PVT corners.

This is deliberately a placement-layer policy, rather than a change to the
per-container ceiling.  A corner must reserve its declared Docker memory before
``docker run`` is allowed.  Reservations are held in durable JSON so a second
launcher (and a later invocation after a client crash) sees the promise too.
Swap is never read or budgeted.
"""
from __future__ import annotations

import vibeic_temp as _vtmp

import fcntl
import json
import os
import re
import subprocess
import sys
import math

# Sibling import, resolvable HOWEVER this file is loaded. A caller that loads
# the program by path (`spec_from_file_location`, which is how
# test_issue2104_programs_load_by_path measures every shipped program) does
# not put this directory on sys.path, and a bare `import _docker_memory`
# then raises ModuleNotFoundError -- which is exactly what #2239's first
# version of this import did. Same shim every other user of the helper
# carries.
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _docker_memory as _dmem  # noqa: E402 -- the ONE place a `docker run` gets its ceiling
import _watchdog as _wd  # noqa: E402 -- progress, never a raw clock kill
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

GiB = 1024 ** 3
_SIZE = re.compile(r"^([1-9][0-9]*)([kKmMgGtT])(?:i?[bB])?$")
_BYTES = re.compile(r"^[1-9][0-9]*$")
HOST_STATE_ENV = "VIBEIC_ANALOG_CORNER_ADMISSION_STATE_DIR"
HOST_STATE_DEFAULT = _vtmp.root() / "state/analog-corner-admission"
CORNER_POLL_S = 30.0
CORNER_STALL_GRACE_S = 1800.0


class AdmissionRefused(RuntimeError):
    """A launch that must not reach Docker."""


def parse_bytes(value: str) -> int:
    """Parse a non-zero, whole binary unit reservation; reject ambiguity."""
    m = _SIZE.fullmatch(str(value or "").strip())
    if not m:
        raise AdmissionRefused("memory reservation must be a non-zero whole K/M/G/T value")
    n = int(m.group(1))
    scale = {"k": 1024, "m": 1024 ** 2, "g": GiB, "t": 1024 ** 4}[m.group(2).lower()]
    return n * scale


def declared_reservation(env=None, *, container_memory=None) -> tuple[str, int]:
    env = os.environ if env is None else env
    # The generic Docker ceiling is accepted only when it was explicitly set;
    # its host-percentage default is not a per-corner declaration.
    raw = (env.get("VIBEIC_ANALOG_CORNER_MEMORY") or env.get("VIBEIC_DOCKER_MEMORY") or "").strip()
    if raw:
        return raw, parse_bytes(raw)
    # Docker's HostConfig.Memory is an integer byte count. It is accepted only
    # as the selected A4 container's explicit declared ceiling, never as an
    # inferred host value or a zero/unlimited default.
    fallback = str(container_memory or "").strip()
    if not _BYTES.fullmatch(fallback):
        raise AdmissionRefused("no non-zero declared corner memory reservation")
    # RETURNED IN THE CANONICAL UNIT FORM, not as the raw byte count
    # (vibe-ic, lane icadc 2026-09-15, MEASURED). The string this function
    # returns is consumed TWICE by `parse_bytes` — once in `launch` and once in
    # `docker_run_argv`, which validates what it is about to hand to
    # `docker --memory`. `parse_bytes` requires `_SIZE`, a K/M/G/T suffix, and
    # rejects a bare byte count ON PURPOSE: in a value a human typed into
    # `VIBEIC_ANALOG_CORNER_MEMORY`, `8` is ambiguous and must not be guessed.
    # So returning `HostConfig.Memory` verbatim made the container-derived
    # path — the fallback EVERY invocation takes when no env var is set —
    # unable to reach Docker at all:
    #
    #     _run_block -> _run_ngspice -> _aca.launch -> parse_bytes
    #     AdmissionRefused: memory reservation must be a non-zero whole
    #                       K/M/G/T value
    #
    # Both halves were already tested, SEPARATELY, and neither test fed one's
    # output to the other. Converting HERE — at the single place the string is
    # produced — fixes both consumers and leaves the ambiguity guard on
    # human-supplied strings exactly as strict as it was.
    return _canonical_size(int(fallback)), int(fallback)


def _canonical_size(amount: int) -> str:
    """`amount` bytes as the largest K/M/G/T unit that divides it EXACTLY.

    Exactly, never rounded: the returned string is what `docker --memory` is
    given, so a rounded one would run a container at a size the ledger did not
    reserve. A value no unit divides cannot be expressed in the form every
    consumer here requires, and is refused by name rather than approximated —
    Docker's own ceilings are whole MiB, so this refusal is not reachable from
    a container declaration and exists for the caller that hand-builds one.
    """
    for unit, scale in (("t", 1024 ** 4), ("g", GiB), ("m", 1024 ** 2),
                        ("k", 1024)):
        if amount % scale == 0:
            return f"{amount // scale}{unit}"
    raise AdmissionRefused(
        f"a reservation of {amount} bytes is not a whole K/M/G/T value and "
        f"cannot be expressed as the `docker --memory` limit every consumer "
        f"of this reservation requires")


def host_state_dir(env=None) -> Path:
    env = os.environ if env is None else env
    raw = (env.get(HOST_STATE_ENV) or "").strip()
    return Path(raw) if raw and Path(raw).resolve().is_relative_to(_vtmp.root().resolve()) else _vtmp.root() / "state/analog-corner-admission"


def physical_ram_bytes() -> int:
    try:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        total = 0
    if not isinstance(total, int) or total <= 0:
        raise AdmissionRefused("physical RAM is unavailable; refusing corner launch")
    return total


def headroom_bytes(env=None) -> int:
    env = os.environ if env is None else env
    # A stated default is intentional policy, not inferred free memory.
    return parse_bytes(env.get("VIBEIC_ANALOG_CORNER_HEADROOM", "16GiB"))


def docker_active_reservations(runner=subprocess.run) -> dict[str, int]:
    """Return active labelled reservations keyed by their durable token.

    A pre-token legacy container gets an id-derived key and remains fully
    charged. A token that is also in the ledger is reconciled by
    :meth:`AdmissionLedger._accounted_bytes` rather than charged twice.
    """
    try:
        ps = runner(["docker", "ps", "-q", "--filter", "label=vibeic.corner.admission=1"],
                    capture_output=True, text=True, check=False, timeout=15)
    except Exception as exc:
        raise AdmissionRefused(f"cannot inspect active corner reservations: {exc}") from exc
    if ps.returncode:
        raise AdmissionRefused("cannot inspect active corner reservations")
    ids = (ps.stdout or "").split()
    if not ids:
        return {}
    # THE TEMPLATE IS PASSED TO execve, NOT TO A SHELL, so every character in
    # this string reaches Docker's Go template parser verbatim (lane icadc,
    # 2026-09-15, MEASURED). It used to carry LITERAL backslashes — `\t` as two
    # characters and `\"` around the label key — and Go rejects them:
    #
    #     docker inspect -f '{{.Id}}\t...\"vibeic.corner.token\"...' <id>
    #     rc=64  template parsing error: template: :1: unexpected "\\" in operand
    #
    # `docker_active_reservations` therefore raised
    # `AdmissionRefused("cannot inspect active corner memory reservations")`
    # WHENEVER AT LEAST ONE LABELLED CORNER WAS ALIVE — and returned cleanly
    # only when there were none, which is why it looked healthy at the start of
    # every sweep and failed from the second corner onwards. In
    # `_run_pvt_corners` that refusal is recorded against EVERY pooled corner as
    # `RAM_ADMISSION_REFUSED`, which is the `corners_executed 1/9` /
    # `A4_PVT_SWEEP_NOT_MEASURED` that three tests have been red on main with.
    fmt = '{{.Id}}\t{{.HostConfig.Memory}}\t{{index .Config.Labels "vibeic.corner.token"}}'
    cp = runner(["docker", "inspect", "-f", fmt, *ids],
                capture_output=True, text=True, check=False, timeout=15)
    if cp.returncode:
        raise AdmissionRefused("cannot inspect active corner memory reservations")
    out = {}
    for line in (cp.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            raise AdmissionRefused("active corner reservation is malformed")
        ident, raw, token = (part.strip() for part in parts)
        try:
            amount = int(raw)
        except ValueError as exc:
            raise AdmissionRefused("active corner reservation is malformed") from exc
        if not ident or amount <= 0:
            raise AdmissionRefused("active corner reservation is malformed")
        # Docker renders a missing map entry as ``<no value>``.  Treat it as
        # legacy just like an empty label: otherwise unrelated legacy
        # containers would collapse onto one pseudo-token and could be
        # under-counted.
        key = token if token and token != "<no value>" else f"legacy:{ident}"
        # Duplicate tokens are not normal; charging both is the safe response.
        out[key] = out.get(key, 0) + amount
    return out


def docker_reserved_bytes(runner=subprocess.run) -> int:
    """Compatibility total for callers that do not reconcile ledger tokens."""
    return sum(docker_active_reservations(runner).values())


class AdmissionLedger:
    """Host-authoritative, flock-protected reservations plus project receipts."""
    def __init__(self, project: Path, *, ram_bytes=None, headroom=None, active_bytes=None,
                 active_reservations=None, state_dir=None):
        self.root = Path(project) / "reports" / "analog" / "corner-admission"
        self.root.mkdir(parents=True, exist_ok=True)
        # The state/lock are deliberately NOT beneath project. Different A4
        # projects can share a Docker host and must contend for one budget.
        self.host_root = Path(state_dir) if state_dir is not None else host_state_dir()
        self.host_root.mkdir(parents=True, exist_ok=True)
        self.state = self.host_root / "reservations.json"
        self.lock = self.host_root / "reservations.lock"
        self.ram_bytes = physical_ram_bytes() if ram_bytes is None else ram_bytes
        self.headroom = headroom_bytes() if headroom is None else headroom
        if active_reservations is not None:
            self.active_reservations = active_reservations
        elif active_bytes is not None:
            # Keep old test/consumer injection usable; an integer has no
            # token identity, so it is conservatively external.
            self.active_reservations = lambda: (
                {"legacy:injected": active_bytes()} if active_bytes() > 0 else {})
        else:
            self.active_reservations = docker_active_reservations
        if self.ram_bytes <= self.headroom:
            raise AdmissionRefused("configured headroom leaves no physical-RAM budget")

    @contextmanager
    def _locked(self):
        with self.lock.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    data = json.loads(self.state.read_text()) if self.state.exists() else {"reservations": {}}
                except (OSError, json.JSONDecodeError) as exc:
                    raise AdmissionRefused(f"reservation ledger is unreadable: {exc}") from exc
                yield data
                tmp = self.state.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
                os.replace(tmp, self.state)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _receipt(self, name, record):
        with (self.root / name).open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _accounted_bytes(self, data):
        """Count every promise exactly once across ledger and live Docker.

        Matching token entries represent the same launch. If Docker reports a
        larger value than the durable reservation, retain the larger amount so
        reconciliation cannot turn a mismatch into over-admission.
        """
        reservations = data.get("reservations", {})
        active = self.active_reservations()
        if not isinstance(active, dict) or any(not isinstance(v, int) or v <= 0
                                               for v in active.values()):
            raise AdmissionRefused("active corner reservation accounting is invalid")
        total = 0
        seen = set()
        for token, record in reservations.items():
            if record.get("state") != "reserved":
                continue
            try:
                promised = int(record["bytes"])
            except (KeyError, TypeError, ValueError) as exc:
                raise AdmissionRefused("durable reservation is malformed") from exc
            if promised <= 0:
                raise AdmissionRefused("durable reservation is malformed")
            total += max(promised, active.get(token, 0))
            seen.add(token)
        total += sum(amount for token, amount in active.items() if token not in seen)
        return total, sum(active.values())

    def plan(self, jobs: Iterable[dict], reservation: int):
        """Jobs may carry their OWN `bytes`, and when they do that is what is
        planned against.

        WHY (R-0915-117(2), MEASURED on 8hd-3). A corner's footprint is not a
        property of the host, it is the deck's: saved vectors times the record
        it runs. One declared reservation for every corner under-estimated the
        graded delta_sigma deck by about 4x -- 24 GiB declared against 94.8 GiB
        measured -- so a second corner was admitted that could only have been
        killed some days in, after the first had also been slowed. The estimate
        now comes from the deck (`analog_resolution_stimulus.
        estimated_peak_rss_bytes`), and this is the consumer that had no way to
        take it.

        HETEROGENEOUS SIZES PLAN AGAINST THE LARGEST, not the mean. Concurrency
        here is a promise that the jobs can run TOGETHER; the mean is a promise
        about an average run that no individual job makes. A 0.8 GiB graded
        deck alongside a 3.4 GiB rails deck is planned as two 3.4 GiB jobs.

        A job without `bytes` uses `reservation`, so every existing caller
        plans exactly as it did."""
        jobs = list(jobs)
        sizes = [int(j["bytes"]) for j in jobs
                 if isinstance(j.get("bytes"), (int, float)) and j["bytes"] > 0]
        derived = len(sizes) == len(jobs) and bool(sizes)
        unit = max(sizes) if derived else reservation
        if not jobs or unit <= 0:
            raise AdmissionRefused("every launch plan needs non-empty jobs and a positive reservation")
        with self._locked() as data:
            accounted, active_total = self._accounted_bytes(data)
        budget = self.ram_bytes - self.headroom
        available = max(0, budget - accounted)
        concurrency = available // unit
        record = {"timestamp": time.time(), "ram_bytes": self.ram_bytes,
                  "headroom_bytes": self.headroom, "budget_bytes": budget,
                  "docker_active_bytes": active_total, "accounted_reserved_bytes": accounted,
                  "reservation_bytes": unit, "jobs": [j["id"] for j in jobs],
                  "safe_concurrency": concurrency, "swap_bytes": None,
                  "reservation_source": ("derived_from_each_deck"
                                         if derived else "declared"),
                  "declared_reservation_bytes": reservation,
                  "per_job_bytes": ({j["id"]: int(j["bytes"]) for j in jobs}
                                    if derived else None)}
        self._receipt("plans.jsonl", record)
        return record

    def reserved_bytes(self):
        with self._locked() as data:
            return self._accounted_bytes(data)[0]

    def reserve(self, job_id: str, reservation: int):
        if not job_id or reservation <= 0:
            raise AdmissionRefused("corner id and positive reservation are required")
        with self._locked() as data:
            reservations = data.setdefault("reservations", {})
            accounted, _active_total = self._accounted_bytes(data)
            budget = self.ram_bytes - self.headroom
            if accounted + reservation > budget:
                raise AdmissionRefused("aggregate RAM budget exhausted before Docker launch")
            token = uuid.uuid4().hex
            reservations[token] = {"job_id": job_id, "project": str(self.root.parent.parent.parent), "bytes": reservation,
                                   "state": "reserved", "timestamp": time.time()}
            self._receipt("reservations.jsonl", {"token": token, **reservations[token]})
            return token

    def release(self, token: str, *, outcome: str):
        with self._locked() as data:
            record = data.setdefault("reservations", {}).get(token)
            if record is None or record.get("state") != "reserved":
                raise AdmissionRefused("cannot release an unknown or completed reservation")
            record["state"] = "completed"
            record["completed_at"] = time.time()
            record["outcome"] = outcome
            self._receipt("completions.jsonl", {"token": token, **record})


def docker_run_argv(*, image: str, reservation: str, project: Path,
                   workdir: Path, simulation_args: list[str], name: str | None = None,
                   token: str | None = None) -> list[str]:
    """The one canonical independent-corner invocation; args stay untouched."""
    parse_bytes(reservation)
    # THE CEILING COMES FROM THE ONE HELPER, with the reservation as the
    # explicit limit. #2235 made `_docker_memory.docker_memory_flags` the
    # single place a `docker run` gets its memory flags (both `--memory`
    # and `--memory-swap`, or neither -- `--memory` alone leaves the host's
    # swap open, which is the half of the incident that froze the machine),
    # and `test_no_docker_run_escapes_the_ceiling` holds every run site to
    # it with no allowlist. This site wrote the same two flags by hand; the
    # bytes were right and the door was wrong. `memory_limit` returns an
    # explicit VIBEIC_DOCKER_MEMORY verbatim, so the argv is unchanged.
    argv = ["docker", "run", *_vtmp.docker_mounts(), "--rm", "--init", "--label", "vibeic.corner.admission=1",
            *_dmem.docker_memory_flags({"VIBEIC_DOCKER_MEMORY": reservation})]
    if token:
        argv += ["--label", f"vibeic.corner.token={token}"]
    if name:
        argv += ["--name", name]
    argv += ["-v", f"{Path(project).resolve()}:{Path(project).resolve()}",
             "-w", str(Path(workdir).resolve()), image, *simulation_args]
    return argv


def _docker_query(argv: list[str]):
    return subprocess.run(argv, capture_output=True, text=True, check=False,
                          timeout=15)


def _container_id(name: str) -> str | None:
    """Bind a freshly launched corner to its exact Docker container ID."""
    cp = _docker_query(["docker", "inspect", "-f", "{{.Id}}", name])
    if cp.returncode:
        if any(s in (cp.stderr or "").lower()
               for s in ("no such object", "no such container")):
            return None
        raise AdmissionRefused(f"cannot identify corner container {name}: "
                               f"{(cp.stderr or cp.stdout).strip()}")
    cid = (cp.stdout or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", cid):
        raise AdmissionRefused("corner container ID is malformed")
    return cid


def _container_terminal(name: str, cid: str | None) -> bool:
    cid = cid or _container_id(name)
    if not cid:
        return True
    cp = _docker_query(["docker", "ps", "-q", "--no-trunc", "--filter",
                        f"id={cid}"])
    if cp.returncode:
        raise AdmissionRefused("cannot confirm corner container termination")
    return not (cp.stdout or "").strip()


def _run_corner_supervised(argv: list[str], name: str,
                           recorded_budget_s: float | None):
    """Watch simulator output and CPU of this exact fresh Docker container.

    Host docker-client CPU is not a liveness signal: it can wait idle while
    ngspice works. Docker stats samples the container without executing a
    probe inside it. A positive sample renews the progress lease; the
    recorded budget never kills a progressing simulation.
    """
    bound: list[str | None] = [None]
    activity = [0.0]

    def bind() -> str | None:
        if bound[0] is None:
            bound[0] = _container_id(name)
        return bound[0]

    def cpu_progress(_proc) -> float | None:
        try:
            cid = bind()
        except (AdmissionRefused, OSError, subprocess.TimeoutExpired):
            # Observation failure is not a simulator failure. The stall lease
            # will still expire unless output or another CPU sample advances.
            return None
        if not cid:
            return None
        try:
            cp = _docker_query(["docker", "stats", "--no-stream", "--format",
                                "{{.CPUPerc}}", cid])
        except (OSError, subprocess.TimeoutExpired):
            return None
        if cp.returncode:
            return None
        try:
            percent = float((cp.stdout or "").strip().rstrip("%"))
        except ValueError:
            return None
        if math.isfinite(percent) and percent > 0.5:
            activity[0] += 1.0
        return activity[0]

    def reap(proc, reason: str) -> None:
        try:
            cid = bind()
            if cid:
                _docker_query(["docker", "rm", "-f", cid])
        finally:
            # The Docker client is our own process-group leader. Reap it as
            # well; never signal a name pattern or an unrelated container.
            _wd._default_kill(proc, reason)

    result = _wd.run_supervised(
        argv, cpu_probe=cpu_progress, kill=reap,
        poll_s=CORNER_POLL_S, stall_grace_s=CORNER_STALL_GRACE_S,
        hard_ceiling_s=(recorded_budget_s or _wd.DEFAULT_HARD_CEILING_S))
    return subprocess.CompletedProcess(argv, result.rc, result.out,
                                       result.err), bound[0]


def launch(ledger: AdmissionLedger, *, job_id: str, reservation: str,
           image: str, project: Path, workdir: Path, simulation_args: list[str],
           recorded_budget_s: float | None = None, runner=None):
    """Reserve first; release only after the exact corner container is terminal."""
    amount = parse_bytes(reservation)
    token = ledger.reserve(job_id, amount)
    argv = docker_run_argv(image=image, reservation=reservation, project=project,
                           workdir=workdir, simulation_args=simulation_args,
                           name=f"vibeic-corner-{token[:12]}", token=token)
    name = f"vibeic-corner-{token[:12]}"
    cid = None
    try:
        if runner is None:
            cp, cid = _run_corner_supervised(argv, name, recorded_budget_s)
            if not _container_terminal(name, cid):
                raise AdmissionRefused(
                    f"corner {cid or name} remains live after its launcher returned")
        else:
            # Explicit test/transport injection retains the old runner seam.
            cp = runner(argv, capture_output=True, text=True, check=False)
        ledger.release(token, outcome=f"docker_rc_{cp.returncode}")
        return cp
    except BaseException:
        # Preserve the launch/supervision error if Docker itself is unavailable.
        # In that case terminal state is unknown, so keep the reservation.
        try:
            terminal = runner is not None or _container_terminal(name, cid)
        except (AdmissionRefused, OSError, subprocess.TimeoutExpired):
            terminal = False
        if terminal:
            ledger.release(token, outcome="launcher_exception")
        raise
