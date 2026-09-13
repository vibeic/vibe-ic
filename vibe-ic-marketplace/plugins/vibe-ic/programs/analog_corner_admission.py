#!/usr/bin/env python3
"""Fail-closed aggregate-RAM admission for independently launched PVT corners.

This is deliberately a placement-layer policy, rather than a change to the
per-container ceiling.  A corner must reserve its declared Docker memory before
``docker run`` is allowed.  Reservations are held in durable JSON so a second
launcher (and a later invocation after a client crash) sees the promise too.
Swap is never read or budgeted.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable

GiB = 1024 ** 3
_SIZE = re.compile(r"^([1-9][0-9]*)([kKmMgGtT])(?:i?[bB])?$")


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


def declared_reservation(env=None) -> tuple[str, int]:
    env = os.environ if env is None else env
    # The generic Docker ceiling is accepted only when it was explicitly set;
    # its host-percentage default is not a per-corner declaration.
    raw = (env.get("VIBEIC_ANALOG_CORNER_MEMORY") or env.get("VIBEIC_DOCKER_MEMORY") or "").strip()
    return raw, parse_bytes(raw)


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


def docker_reserved_bytes(runner=subprocess.run) -> int:
    """Return active labelled corner reservations; a Docker error is a refusal."""
    try:
        ps = runner(["docker", "ps", "-q", "--filter", "label=vibeic.corner.admission=1"],
                    capture_output=True, text=True, check=False, timeout=15)
    except Exception as exc:
        raise AdmissionRefused(f"cannot inspect active corner reservations: {exc}") from exc
    if ps.returncode:
        raise AdmissionRefused("cannot inspect active corner reservations")
    ids = (ps.stdout or "").split()
    if not ids:
        return 0
    cp = runner(["docker", "inspect", "-f", "{{.HostConfig.Memory}}", *ids],
                capture_output=True, text=True, check=False, timeout=15)
    if cp.returncode:
        raise AdmissionRefused("cannot inspect active corner memory reservations")
    try:
        return sum(int(x) for x in (cp.stdout or "").split() if int(x) > 0)
    except ValueError as exc:
        raise AdmissionRefused("active corner reservation is malformed") from exc


class AdmissionLedger:
    """A small flock-protected durable reservation ledger scoped to a project."""
    def __init__(self, project: Path, *, ram_bytes=None, headroom=None, active_bytes=None):
        self.root = Path(project) / "reports" / "analog" / "corner-admission"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = self.root / "reservations.json"
        self.lock = self.root / "reservations.lock"
        self.ram_bytes = physical_ram_bytes() if ram_bytes is None else ram_bytes
        self.headroom = headroom_bytes() if headroom is None else headroom
        self.active_bytes = docker_reserved_bytes if active_bytes is None else active_bytes
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

    def plan(self, jobs: Iterable[dict], reservation: int):
        jobs = list(jobs)
        if not jobs or reservation <= 0:
            raise AdmissionRefused("every launch plan needs non-empty jobs and a positive reservation")
        active = self.active_bytes()
        budget = self.ram_bytes - self.headroom
        local = self.reserved_bytes()
        if active < 0 or local < 0:
            raise AdmissionRefused("reservation accounting is invalid")
        available = max(0, budget - active - local)
        concurrency = available // reservation
        record = {"timestamp": time.time(), "ram_bytes": self.ram_bytes,
                  "headroom_bytes": self.headroom, "budget_bytes": budget,
                  "docker_active_bytes": active, "ledger_reserved_bytes": local,
                  "reservation_bytes": reservation, "jobs": [j["id"] for j in jobs],
                  "safe_concurrency": concurrency, "swap_bytes": None}
        self._receipt("plans.jsonl", record)
        return record

    def reserved_bytes(self):
        with self._locked() as data:
            return sum(int(v["bytes"]) for v in data.get("reservations", {}).values()
                       if v.get("state") == "reserved")

    def reserve(self, job_id: str, reservation: int):
        if not job_id or reservation <= 0:
            raise AdmissionRefused("corner id and positive reservation are required")
        with self._locked() as data:
            reservations = data.setdefault("reservations", {})
            local = sum(int(v["bytes"]) for v in reservations.values() if v.get("state") == "reserved")
            active = self.active_bytes()
            budget = self.ram_bytes - self.headroom
            if active + local + reservation > budget:
                raise AdmissionRefused("aggregate RAM budget exhausted before Docker launch")
            token = uuid.uuid4().hex
            reservations[token] = {"job_id": job_id, "bytes": reservation,
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
                   workdir: Path, simulation_args: list[str], name: str | None = None) -> list[str]:
    """The one canonical independent-corner invocation; args stay untouched."""
    parse_bytes(reservation)
    argv = ["docker", "run", "--rm", "--init", "--label", "vibeic.corner.admission=1",
            "--memory", reservation, "--memory-swap", reservation]
    if name:
        argv += ["--name", name]
    argv += ["-v", f"{Path(project).resolve()}:{Path(project).resolve()}",
             "-w", str(Path(workdir).resolve()), image, *simulation_args]
    return argv


def launch(ledger: AdmissionLedger, *, job_id: str, reservation: str,
           image: str, project: Path, workdir: Path, simulation_args: list[str],
           runner=subprocess.run):
    """Reserve first, then and only then invoke the independently-running Docker corner."""
    amount = parse_bytes(reservation)
    token = ledger.reserve(job_id, amount)
    argv = docker_run_argv(image=image, reservation=reservation, project=project,
                           workdir=workdir, simulation_args=simulation_args,
                           name=f"vibeic-corner-{token[:12]}")
    try:
        cp = runner(argv, capture_output=True, text=True, check=False)
        ledger.release(token, outcome=f"docker_rc_{cp.returncode}")
        return cp
    except BaseException:
        ledger.release(token, outcome="launcher_exception")
        raise
