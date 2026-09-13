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
from typing import Iterable

GiB = 1024 ** 3
_SIZE = re.compile(r"^([1-9][0-9]*)([kKmMgGtT])(?:i?[bB])?$")
_BYTES = re.compile(r"^[1-9][0-9]*$")
HOST_STATE_ENV = "VIBEIC_ANALOG_CORNER_ADMISSION_STATE_DIR"
HOST_STATE_DEFAULT = Path("/var/tmp/vibeic-analog-corner-admission")


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
    return fallback, int(fallback)


def host_state_dir(env=None) -> Path:
    env = os.environ if env is None else env
    raw = (env.get(HOST_STATE_ENV) or "").strip()
    return Path(raw) if raw else HOST_STATE_DEFAULT


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
    fmt = "{{.Id}}\\t{{.HostConfig.Memory}}\\t{{index .Config.Labels \\\"vibeic.corner.token\\\"}}"
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
        jobs = list(jobs)
        if not jobs or reservation <= 0:
            raise AdmissionRefused("every launch plan needs non-empty jobs and a positive reservation")
        with self._locked() as data:
            accounted, active_total = self._accounted_bytes(data)
        budget = self.ram_bytes - self.headroom
        available = max(0, budget - accounted)
        concurrency = available // reservation
        record = {"timestamp": time.time(), "ram_bytes": self.ram_bytes,
                  "headroom_bytes": self.headroom, "budget_bytes": budget,
                  "docker_active_bytes": active_total, "accounted_reserved_bytes": accounted,
                  "reservation_bytes": reservation, "jobs": [j["id"] for j in jobs],
                  "safe_concurrency": concurrency, "swap_bytes": None}
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
    argv = ["docker", "run", "--rm", "--init", "--label", "vibeic.corner.admission=1",
            "--memory", reservation, "--memory-swap", reservation]
    if token:
        argv += ["--label", f"vibeic.corner.token={token}"]
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
                           name=f"vibeic-corner-{token[:12]}", token=token)
    try:
        cp = runner(argv, capture_output=True, text=True, check=False)
        ledger.release(token, outcome=f"docker_rc_{cp.returncode}")
        return cp
    except BaseException:
        ledger.release(token, outcome="launcher_exception")
        raise
