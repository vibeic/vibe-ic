#!/usr/bin/env python3
"""benchmark_dispatch.py — entry point for /vibe-ic-benchmark.

Reads BENCHMARK_REGISTRY.json, picks the correct run-shape per
open-benchmark-methodology skill § 2, sets up the run dir scaffold, and prints
the canonical next-step commands (clone dataset / drive runner or gates /
invoke scorer / write RESULT.md). Does NOT itself perform the AI authoring
step — the agent does that, guided by the per-shape blind_instructions_*.md.

Usage:
    python3 benchmark_dispatch.py <bench>                       # check status + show plan
    python3 benchmark_dispatch.py <bench> --solve --dataset <ds> --run <dir>
    python3 benchmark_dispatch.py <bench> --resume --dataset <ds> --run <dir>
    python3 benchmark_dispatch.py <bench> --score --dataset <ds> --run <dir>
    python3 benchmark_dispatch.py --list                         # list all known benchmarks
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse, atexit, hashlib, hmac, json, os, secrets, shutil, subprocess, sys, tempfile
import concurrent.futures
import contextlib
import fcntl
import math
import re
import signal
import shlex
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, TypeVar

from _atomic_artefact import write_json as _atomic_write_json
from _atomic_artefact import write_text as _atomic_write_text
from _atomic_artefact import write_bytes as _atomic_write_bytes
import _runtime_pair_preflight as _runtime_pair
import _container_exec as _challenge_exec

HARNESS = Path(__file__).resolve().parent.parent / "benchmark"
REGISTRY = HARNESS / "BENCHMARK_REGISTRY.json"
EXPERT_AGENT_MD = Path(__file__).resolve().parent.parent / "agents" / "ic-expert-agent.md"

_COORDINATOR_LOCK = ".benchmark_dispatch.coordinator.lock"


def _reject_duplicate_json_pairs(pairs):
    """Build one JSON object while refusing every repeated member name.

    ``json.loads`` otherwise applies last-key-wins semantics.  Route responses
    are signed evidence, so a payload whose meaning depends on that overwrite
    is malformed at every object depth, including nested metadata and evidence
    records.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value):
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _finite_json_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number is forbidden: {value}")
    return parsed


def _strict_json_loads(raw):
    """Parse RFC8259 JSON evidence with duplicate and non-finite refusal."""
    return json.loads(raw, object_pairs_hook=_reject_duplicate_json_pairs,
                      parse_constant=_reject_nonfinite_json_constant,
                      parse_float=_finite_json_float)


class _CoordinatorBusy(RuntimeError):
    """A second solve/resume coordinator targeted the same run root."""


@contextlib.contextmanager
def _run_root_coordinator_lock(run_p: Path, operation: str):
    """Own all run-root shared writes for one solve/resume invocation.

    The lock file is intentionally persistent so a refused second coordinator
    can name the last recorded owner.  Ownership itself is the kernel ``flock``
    and is released on close, including exception exits; the JSON is only a
    diagnostic, never evidence that a stale process still owns the run.
    """
    run_p = Path(run_p).resolve()
    run_p.mkdir(parents=True, exist_ok=True)
    lock_p = run_p / _COORDINATOR_LOCK
    lock_f = lock_p.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock_f.seek(0)
            owner = lock_f.read().strip() or "owner metadata unavailable"
            raise _CoordinatorBusy(
                "another benchmark_dispatch coordinator owns run root "
                f"{run_p}: {owner}") from exc
        lock_f.seek(0)
        lock_f.truncate()
        lock_f.write(json.dumps({
            "schema": "vibeic.benchmark.run_root_lock.v1",
            "operation": str(operation),
            "pid": os.getpid(),
            "run_root": str(run_p),
        }, sort_keys=True) + "\n")
        lock_f.flush()
        yield
    finally:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        finally:
            lock_f.close()


T = TypeVar("T")
R = TypeVar("R")


def _ordered_parallel_map(items: Iterable[T], worker: Callable[[T], R],
                          jobs: int) -> list[R]:
    """Run unique-project work concurrently and return input-order results."""
    rows = list(items)
    if jobs <= 1 or len(rows) <= 1:
        return [worker(row) for row in rows]
    ordered: list[R | None] = [None] * len(rows)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(worker, row): i for i, row in enumerate(rows)}
        for future in concurrent.futures.as_completed(futures):
            ordered[futures[future]] = future.result()
    return [row for row in ordered if row is not None]


@dataclass(frozen=True)
class _ProcessOutcome:
    rc: int | None
    error: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    invocation_id: str | None = None
    receipt_path: str | None = None
    receipt_sha256: str | None = None
    invocation: dict | None = None


_RUNNER_REPORT_NAMES = ("phase1_one_shot.json", "phase2_one_shot.json",
                        "phase3_one_shot.json", "vibe_ic_one_shot.json")
_RUNNER_CONTEXT_ENV = "VIBEIC_RUNNER_INVOCATION_CONTEXT"


def _runner_source_snapshot(argv: list[str]) -> dict:
    """Identity of the executable and actual script, including invocation options.

    The dispatcher is a consumer, not a substitute for argv[1]'s producer.
    Resolve executable names through PATH just as subprocess does.
    """
    def source(value: str) -> dict:
        path = Path(value).resolve(strict=True)
        raw = path.read_bytes()
        return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}

    executable = shutil.which(argv[0]) or argv[0]
    return {"argv": list(argv), "executable": source(executable),
            "runner": source(argv[1]), "consumer": source(__file__)}


def _bind_runner_report(summary: dict, project: Path, producer: str,
                        report_name: str, *, context: dict | None = None) -> dict:
    """Called by the actual report writer, before publishing its measured data.

    Standalone producers have no dispatch generation and retain their ordinary
    format. A dispatched producer states its generation and material itself;
    the caller must not add this field to a report it merely found on disk.
    This is provenance, never a successful gate verdict.
    """
    if context is None:
        raw = os.environ.get(_RUNNER_CONTEXT_ENV)
        if raw is None:
            return summary
        context = _strict_json_loads(raw)
    project = Path(project).resolve()
    if context["project"] != str(project):
        return summary  # an internal isolated child has its own report subject
    if (context["source"] != _runner_source_snapshot(context["argv"])
            or report_name not in _RUNNER_REPORT_NAMES):
        raise ValueError("RUNNER_REPORT_UNBOUND: producer context/source differs")
    producer_path = Path(producer).resolve(strict=True)
    return {**summary, "runner_binding": {
        "schema": "vibeic.runner_report_binding.v1",
        "invocation_id": context["invocation_id"],
        "project": str(project), "argv": context["argv"],
        "source": context["source"], "report_name": report_name,
        "producer": {"path": str(producer_path),
                     "sha256": hashlib.sha256(producer_path.read_bytes()).hexdigest()},
        "material": _runner_material_snapshot(project),
    }}


def _runner_report_snapshot(project: Path) -> dict:
    """Bind canonical reports to their bytes and filesystem generation.

    Filesystem generation is retained for audit, not used as gate generation.
    No receipt in runner_invocations is itself a runner report.
    """
    reports = {}
    for name in _RUNNER_REPORT_NAMES:
        path = project / "reports" / "orchestrator" / name
        try:
            raw = path.read_bytes()
            stat = path.stat()
            document = _strict_json_loads(raw)
            valid = isinstance(document, dict)
        except (OSError, ValueError):
            continue
        reports[name] = {
            "sha256": hashlib.sha256(raw).hexdigest(), "valid": valid,
            "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns,
            "inode": stat.st_ino, "size": stat.st_size,
            "project": document.get("project") if valid else None,
            "runner_binding": document.get("runner_binding") if valid else None,
        }
    return reports


def _runner_fresh_reports(before: dict, after: dict) -> list[str]:
    """A rewrite of old identical bytes is replay, even with a new inode/mtime.

    Native producers' generation binding changes for every invocation, including
    legitimate repeated measurements of identical RTL and identical verdicts.
    Legacy reports remain usable when they have genuinely new report content.
    """
    return [name for name, record in after.items() if record["valid"]
            and record["sha256"] != before.get(name, {}).get("sha256")]


def _runner_report_binding_reason(receipt: dict, *, require_phase2: bool) -> str | None:
    """The same report subject/generation check at collect, freeze and reentry."""
    fresh = _runner_fresh_reports(receipt["reports_before"], receipt["reports_after"])
    for name, record in receipt["reports_after"].items():
        if name not in fresh:
            continue  # an earlier phase's retained history is not this producer
        declared_project = record.get("project")
        if declared_project is not None and (
                not isinstance(declared_project, str)
                or Path(declared_project).resolve() != Path(receipt["project"])):
            return "RUNNER_REPORT_UNBOUND: report explicitly names another project"
        binding = record.get("runner_binding")
        if binding is None:
            if receipt["reports_before"].get(name, {}).get("runner_binding") is not None:
                return "RUNNER_REPORT_UNBOUND: report dropped its producer generation binding"
            return "RUNNER_REPORT_UNBOUND: fresh report has no producer generation binding"
        try:
            if (binding["schema"] != "vibeic.runner_report_binding.v1"
                    or binding["invocation_id"] != receipt["invocation_id"]
                    or binding["project"] != receipt["project"]
                    or binding["argv"] != receipt["argv"]
                    or binding["source"] != receipt["source_before"]
                    or binding["report_name"] != name):
                raise ValueError("report invocation/source differs")
            producer = binding["producer"]
            if hashlib.sha256(Path(producer["path"]).read_bytes()).hexdigest() != producer["sha256"]:
                raise ValueError("report producer source changed")
            # Phase 1 can precede legitimate RTL generation in the same run.
            # Its historical output population is not phase 2's measurement.
            if (name != "phase1_one_shot.json" or not require_phase2):
                if binding["material"] != receipt["material_after"]:
                    raise ValueError("report input/output material differs")
        except (OSError, ValueError, KeyError, TypeError):
            return "RUNNER_REPORT_UNBOUND: report generation/source/material does not bind this invocation"
    return None


def _runner_refusal_line(process: _ProcessOutcome) -> tuple[str, str] | None:
    """Return the owning runner's refusal token and verbatim line, if any."""
    for line in ((process.stderr or "").splitlines()
                 + (process.stdout or "").splitlines()):
        refusal = re.match(r"^REFUSED:\s*([A-Z][A-Z0-9_]*)\b", line)
        if refusal:
            return refusal[1], line
    return None


def _runner_material_snapshot(project: Path) -> dict:
    """Bind the input and emitted file populations, without opening escapes.

    The before/after pair records legitimate Program output changes. Consumers
    require the AFTER population and bytes, never the pre-generation RTL.
    """
    project = Path(project).resolve()
    material = {}
    for label, relative in (("input", "input"),
                            ("output_rtl", "phase2/stage1/rtl")):
        root = project / relative
        files = {}
        if root.exists() or root.is_symlink():
            root.resolve().relative_to(project)
            for directory, dirs, names in os.walk(root, followlinks=False):
                # Directory links are not traversed by os.walk. Record them
                # explicitly; an unmeasured dependency cannot be accepted.
                for name in list(dirs):
                    path = Path(directory) / name
                    if path.is_symlink():
                        raise ValueError(f"runner material directory link: {path}")
                for name in sorted(names):
                    path = Path(directory) / name
                    path.resolve().relative_to(project)
                    raw = path.read_bytes()
                    files[str(path.relative_to(root))] = {
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "size": len(raw),
                        **({"link": os.readlink(path)} if path.is_symlink() else {}),
                    }
        material[label] = files
    prompt = project / "input" / "phase1_prompt.md"
    material["prompt_sha256"] = (_sha256_text(prompt.read_text(errors="replace"))
                                  if prompt.is_file() else None)
    material["output_rtl_sha256"] = _sha256_text(_candidate_text(_rtl_files(project)))
    return material


def _runner_receipt_paths(project: Path, invocation: dict) -> None:
    """Check the record and separately archived stream bytes together."""
    archive = project / "reports" / "orchestrator" / "runner_invocations"
    Path(invocation["record_path"]).resolve().relative_to(archive.resolve())
    for stream in ("stdout", "stderr"):
        value = invocation[stream]
        if value is None:
            if invocation[stream + "_path"] is not None or invocation[stream + "_sha256"] is not None:
                raise ValueError("unavailable capture has fabricated log evidence")
            continue
        path = Path(invocation[stream + "_path"])
        path.resolve().relative_to(archive.resolve())
        if (path.read_bytes() != value.encode("utf-8")
                or _sha256_text(value) != invocation[stream + "_sha256"]):
            raise ValueError(stream + " log changed")


def _material_matches_repaired_output(expected: dict, current: dict) -> bool:
    """Allow only the working RTL output to differ for a proven repair."""
    if not isinstance(expected, dict) or not isinstance(current, dict):
        return False
    output_keys = {"output_rtl", "output_rtl_sha256"}
    return ({key: value for key, value in expected.items()
             if key not in output_keys}
            == {key: value for key, value in current.items()
                if key not in output_keys}
            and expected.get("output_rtl") != current.get("output_rtl")
            and expected.get("output_rtl_sha256")
            != current.get("output_rtl_sha256"))


def _runner_diagnostics(process: _ProcessOutcome, argv: list[str],
                        project: Path, *, require_phase2: bool = True,
                        allow_repaired_output: bool = False,
                        repaired_output_sha256: str | None = None) -> dict | None:
    """Disclose pre-gate refusals without interpreting rc as a gate verdict.

    BLOCKING only for unbound/stale evidence or a named refusal before ANY
    fresh canonical report. Nonzero exits with usable reports keep the ordinary
    collection/gate contract. Logs alone never establish a successful gate.
    """
    project = Path(project).resolve()
    diagnostic = {
        "invocation_id": getattr(process, "invocation_id", None),
        "receipt_path": getattr(process, "receipt_path", None),
        "receipt_sha256": getattr(process, "receipt_sha256", None),
        "project": str(project), "argv": list(argv), "rc": process.rc,
    }
    try:
        raw = Path(diagnostic["receipt_path"] or "").read_bytes()
        receipt = _strict_json_loads(raw)
        _runner_receipt_paths(project, receipt)
        latest = _strict_json_loads((project / "reports" / "orchestrator" / "runner_invocations"
                             / "latest.json").read_bytes())
        if not (hashlib.sha256(raw).hexdigest() == process.receipt_sha256
                and receipt["invocation_id"] == process.invocation_id == latest["invocation_id"]
                and receipt["argv"] == latest["argv"] == list(argv)
                and receipt["project"] == latest["project"] == str(project)
                and receipt["rc"] == process.rc and receipt["error"] == process.error
                and receipt["stdout"] == process.stdout and receipt["stderr"] == process.stderr
                and receipt["reports_after"] == _runner_report_snapshot(project)):
            raise ValueError("runner binding changed")
        current_material = _runner_material_snapshot(project)
        if (allow_repaired_output
                and (not isinstance(repaired_output_sha256, str)
                     or current_material.get("output_rtl_sha256")
                     != repaired_output_sha256)):
            return {**diagnostic, "status": "MATERIAL_MISMATCH",
                    "reason_class": "RUNNER_MATERIAL_UNBOUND",
                    "reason": "RUNNER_MATERIAL_UNBOUND: repaired RTL hash is not the admitted hash"}
        repaired_output_bound = (
            allow_repaired_output
            and isinstance(repaired_output_sha256, str)
            and current_material.get("output_rtl_sha256") == repaired_output_sha256)
        if (receipt["material_after"] != current_material
                and not (repaired_output_bound
                         and _material_matches_repaired_output(
                             receipt["material_after"], current_material))):
            return {**diagnostic, "status": "MATERIAL_MISMATCH",
                    "reason_class": "RUNNER_MATERIAL_UNBOUND",
                    "reason": "RUNNER_MATERIAL_UNBOUND: input or output file population/content changed after invocation"}
        if not (receipt["source_before"] == receipt["source_after"]
                == _runner_source_snapshot(argv)):
            return {**diagnostic, "status": "SOURCE_MISMATCH",
                    "reason_class": "RUNNER_SOURCE_UNBOUND",
                    "reason": "RUNNER_SOURCE_UNBOUND: actual runner executable/source/options changed"}
    except (OSError, ValueError, KeyError, TypeError):
        return {**diagnostic, "status": "INVOCATION_MISMATCH",
                "reason_class": "RUNNER_INVOCATION_UNBOUND",
                "reason": "RUNNER_INVOCATION_UNBOUND: missing, changed or mismatched runner receipt/reports"}
    fresh = _runner_fresh_reports(receipt["reports_before"], receipt["reports_after"])
    diagnostic["fresh_reports"] = fresh
    binding_reason = _runner_report_binding_reason(receipt, require_phase2=require_phase2)
    if binding_reason:
        diagnostic = {**diagnostic, "report_binding_error": binding_reason,
                      "report_binding_status": "REPORT_BINDING_MISMATCH"}
        refusal = _runner_refusal_line(process)
        if refusal:
            # A fresh report that lost its producer binding remains unusable.
            # Keep the binding failure primary while retaining the runner's
            # actual refusal stream as secondary diagnostic metadata.
            diagnostic = {**diagnostic, "actual_refusal_class": refusal[0],
                          "actual_refusal": refusal[1]}
        return {**diagnostic, "status": "REPORT_BINDING_MISMATCH",
                "reason_class": "RUNNER_REPORT_UNBOUND", "reason": binding_reason}
    if not fresh:
        refusal = _runner_refusal_line(process)
        if refusal:
            return {**diagnostic, "status": "REFUSED_PRE_GATE",
                    "reason_class": refusal[0], "reason": refusal[1]}
    phase2 = "phase2_one_shot.json"
    if require_phase2 and phase2 in receipt["reports_after"] and phase2 not in fresh:
        return {**diagnostic, "status": "STALE_RUNNER_REPORT",
                "reason_class": "RUNNER_REPORT_NOT_FRESH",
                "reason": "RUNNER_REPORT_NOT_FRESH: phase2 report predates this invocation or replays identical report bytes"}
    # Some alternate subprocess implementations do not supply captured streams.
    # Their receipt still binds the invocation/reports, but cannot disclose a
    # stdout/stderr diagnostic. Never invent empty logs for an unavailable capture.
    if process.stdout is None or process.stderr is None:
        return None
    return {**diagnostic, "status": ("REPORTS_AVAILABLE" if fresh else "NO_FRESH_REPORTS")}


def _collect_runner_result(process: _ProcessOutcome, argv: list[str],
                           fmt: str, pid: str, project: Path, **kwargs) -> dict:
    """One producer/consumer boundary shared by solve, resume and regate."""
    import benchmark_io_adapter as bio
    diagnostic = _runner_diagnostics(process, argv, project)
    if diagnostic and diagnostic.get("reason"):
        return {"id": pid, "ok": False, "reason": diagnostic["reason"],
                "runner_diagnostics": diagnostic}
    if process.error:
        return {"id": pid, "ok": False, "reason": process.error,
                "runner_diagnostics": diagnostic}
    got = bio.collect(fmt, pid, project, **kwargs)
    # The collector reads the same material just measured, even if another
    # writer moved a file during that read. Task freezing repeats this check.
    after = _runner_diagnostics(process, argv, project)
    if after and after.get("reason"):
        return {"id": pid, "ok": False, "reason": after["reason"],
                "runner_diagnostics": after}
    if diagnostic:
        got = {**got, "runner_diagnostics": diagnostic}
    return got


def _runner_terminal_error(rc, stdout: str, stderr: str) -> str | None:
    """BLOCKING process refusals, distinct from ordinary gate verdicts (rc 1)."""
    if rc == 0:
        return None
    for line in (stderr + "\n" + stdout).splitlines():
        if line.startswith(("REFUSED:", "CONCURRENT_RUN_REFUSED:")):
            return "RUNNER_INVOCATION_REFUSED: " + line
        if rc == 2 and (line.startswith("ERROR:") or "error: " in line
                        and line.startswith("vibe_ic_one_shot_runner.py:")):
            return "RUNNER_INVOCATION_REFUSED: " + line
    if rc is not None and rc < 0:
        return f"RUNNER_WORKER_FAILED: terminated by signal {-rc}"
    if stderr.startswith("Traceback (most recent call last):"):
        return "RUNNER_WORKER_FAILED: " + stderr.splitlines()[-1]
    return None


def _runner_reentry_reason(task: dict, result: dict, *,
                           allow_repaired_output: bool = False,
                           repaired_output_sha256: str | None = None) -> str | None:
    """Legacy refusal exits cannot establish that the stored gates ran.

    Normal rc 0/1 remains supported, including bounded NOT_MEASURED outcomes.
    A receipt from a refused/failed invocation is never a gate measurement.
    """
    verification = task.get("program_verification") or {}
    if not isinstance(verification, dict):
        return "Program verification record is malformed"
    invocation = verification.get("runner_invocation")
    if isinstance(invocation, dict):
        if invocation.get("status") != "COMPLETED":
            return str(invocation.get("error") or "RUNNER_INVOCATION_NOT_MEASURED")
        try:
            project = Path(task["project"]).resolve()
            invocation_project = Path(invocation["project"]).resolve()
            if invocation_project != project:
                regate = _verified_program_regate(task)
                if (regate is None or invocation_project !=
                        (Path(regate["archive_path"]) / "staged_project").resolve()):
                    raise ValueError("invocation project is not this task's gate producer")
            if _strict_json_loads(Path(invocation["record_path"]).read_text()) != invocation:
                raise ValueError("invocation record changed")
            diagnostic = _stored_runner_diagnostics(
                invocation, allow_repaired_output=allow_repaired_output,
                repaired_output_sha256=repaired_output_sha256)
            if diagnostic and diagnostic.get("reason"):
                raise ValueError(diagnostic["reason"])
            current_material = _runner_material_snapshot(project)
            if (allow_repaired_output
                    and (not isinstance(repaired_output_sha256, str)
                         or current_material.get("output_rtl_sha256")
                         != repaired_output_sha256)):
                raise ValueError("repaired RTL hash is not the admitted hash")
            repaired_output_bound = (
                allow_repaired_output
                and isinstance(repaired_output_sha256, str)
                and current_material.get("output_rtl_sha256") == repaired_output_sha256)
            if (invocation["material_after"] != current_material
                    and not (repaired_output_bound
                             and _material_matches_repaired_output(
                                 invocation["material_after"],
                                 current_material))):
                raise ValueError("working input/output population or content changed")
            _runner_frozen_material(invocation, task["candidate_snapshot"])
            if (invocation.get("project") != str(invocation_project)
                    or invocation.get("rc") != verification.get("runner_rc")
                    or invocation.get("output_rtl_sha256") != task.get("rtl_sha256")
                    or invocation.get("prompt_sha256") != task.get("prompt_sha256")):
                raise ValueError("invocation does not bind this task")
            if verification.get("runner_argv") != invocation["argv"]:
                raise ValueError("invocation options differ from the frozen task")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return f"RUNNER_INVOCATION_NOT_MEASURED: {exc}"
        return None
    rc = verification.get("runner_rc", result.get("rc"))
    if type(rc) is int and rc not in (0, 1):
        return f"RUNNER_INVOCATION_NOT_MEASURED: legacy exit {rc} has no invocation evidence"
    return None


def _stored_runner_diagnostics(invocation: dict, *,
                               allow_repaired_output: bool = False,
                               repaired_output_sha256: str | None = None) -> dict | None:
    """Re-use the live collection contract for a frozen invocation record."""
    path = Path(invocation["record_path"])
    raw = path.read_bytes()
    if _strict_json_loads(raw) != invocation:
        raise ValueError("invocation record changed")
    process = _ProcessOutcome(
        rc=invocation["rc"], error=invocation["error"],
        stdout=invocation["stdout"], stderr=invocation["stderr"],
        invocation_id=invocation["invocation_id"], receipt_path=str(path),
        receipt_sha256=hashlib.sha256(raw).hexdigest(), invocation=invocation)
    diagnostic = _runner_diagnostics(
        process, invocation["argv"], Path(invocation["project"]),
        allow_repaired_output=allow_repaired_output,
        repaired_output_sha256=repaired_output_sha256)
    if process.error:
        raise ValueError(process.error)
    return diagnostic


def _runner_frozen_material(invocation: dict, candidate: dict) -> None:
    """The frozen RTL population and raw bytes must be the measured output."""
    expected = {name: {"sha256": record["sha256"], "size": record["size"]}
                for name, record in invocation["material_after"]["output_rtl"].items()
                if "/" not in name and Path(name).suffix in {".v", ".sv"}}
    paths = [Path(p) for p in candidate["rtl_paths"]]
    actual = {}
    for index, path in enumerate(paths):
        raw = path.read_bytes()
        prefix = f"{index:02d}_"
        if not path.name.startswith(prefix):
            raise ValueError("frozen RTL filename differs from archive population")
        actual[path.name[len(prefix):]] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    if actual != expected or len(actual) != len(paths):
        raise ValueError("frozen RTL population/content differs from runner output")


def _own_child_pids() -> list[int]:
    """This process's DIRECT children, from /proc. Never a name pattern.

    Every lane on this fleet runs the same script names, so matching by name
    is how one run kills another's work. Kernel-reported children of THIS pid
    are the only honest population.
    """
    pids: list[int] = []
    try:
        tasks = list(Path(f"/proc/{os.getpid()}/task").iterdir())
    except OSError:
        return pids
    for task in tasks:
        try:
            raw = (task / "children").read_text()
        except OSError:
            continue
        pids.extend(int(tok) for tok in raw.split() if tok.isdigit())
    return sorted(set(pids))


def _kill_live_runner_groups(sig: int = signal.SIGTERM) -> int:
    """Signal each live runner's process GROUP. Returns how many were signalled.

    MEASURED 2026-09-06 (RTLLM run, finding BR-07): killing
    `benchmark_dispatch --solve` left 21 runner processes running for about 15
    minutes against an abandoned run dir, at host load 22+. A pool that
    outlives the run it belongs to burns a shared machine on work nobody will
    read.

    The GROUP, not the child: the runner spawns its own tools, and signalling
    only the direct child leaves exactly the grandchildren BR-07 observed.
    Every runner is started with `start_new_session=True`, so each child is
    its own group leader and `killpg(child_pid)` reaches its whole subtree.
    """
    own = os.getpgrp()
    signalled = 0
    for pid in _own_child_pids():
        try:
            pgid = os.getpgid(pid)
        except OSError:
            continue
        # NEVER our own group. If a child ever failed to get a session of its
        # own, its "group" is the coordinator's, and signalling it would kill
        # the coordinator and everything sharing its terminal -- turning a
        # cleanup into the outage it exists to prevent.
        if pgid == own:
            continue
        try:
            os.killpg(pgid, sig)
            signalled += 1
        except (ProcessLookupError, PermissionError, OSError):
            continue
    return signalled


_ORPHAN_GUARD_INSTALLED = False


def _install_orphan_guard() -> None:
    """Take the worker pool down with the coordinator. Idempotent.

    Covers SIGTERM, SIGINT and SIGHUP, and normal or exceptional exit. It does
    NOT cover SIGKILL, which runs no handler: surviving `kill -9` needs
    PR_SET_PDEATHSIG on each child, and the only way to set it from CPython is
    `preexec_fn`, which the standard library documents as unsafe in the
    presence of threads -- and this pool IS threads. Trading a possible
    fork-time deadlock in every solve for the -9 case is not a trade this
    makes silently; the limit is stated instead.

    Call it from the MAIN THREAD. `signal.signal` refuses anywhere else, and
    the pool's workers are threads -- installing it only from `run()` would
    leave the atexit half alone, which SIGTERM does not reach. MEASURED: with
    the thread-only install, SIGINT took the pool down (CPython turns it into
    KeyboardInterrupt, so atexit runs) and SIGTERM did not.
    """
    global _ORPHAN_GUARD_INSTALLED                       # noqa: PLW0603
    if _ORPHAN_GUARD_INSTALLED:
        return
    _ORPHAN_GUARD_INSTALLED = True
    atexit.register(_kill_live_runner_groups)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            previous = signal.getsignal(sig)
        except (ValueError, OSError):
            continue

        def handler(signum, frame, _previous=previous):
            _kill_live_runner_groups()
            if callable(_previous) and _previous not in (
                    signal.SIG_IGN, signal.SIG_DFL):
                return _previous(signum, frame)
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
            return None

        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            # Not the main thread, or the platform refuses: the atexit half
            # still stands, and nothing is claimed that is not installed.
            continue


class _RunnerBudget:
    """Bound runner-heavy concurrency and per-worker tool thread budgets.

    A whole runner invocation is conservatively treated as a heavy slot.  This
    bounds every synth/LEC it may reach without requiring the dispatcher to
    duplicate the runner's internal step map.  ``jobs`` and ``heavy_jobs`` are
    separate so staging/collection fan-out can remain wider than EDA pressure.
    """

    def __init__(self, jobs: int, heavy_jobs: int | None,
                 worker_threads: int):
        if jobs < 1:
            raise ValueError("--jobs must be >= 1")
        self.jobs = int(jobs)
        self.heavy_jobs = int(heavy_jobs if heavy_jobs is not None else jobs)
        if self.heavy_jobs < 1 or self.heavy_jobs > self.jobs:
            raise ValueError("--heavy-jobs must be between 1 and --jobs")
        if worker_threads < 0:
            raise ValueError("--worker-threads must be >= 0")
        self._heavy = threading.BoundedSemaphore(self.heavy_jobs)
        # Per-invocation wall-clock ceiling, env-tunable. Unset (default)
        # keeps the historical unbounded behaviour; set, it stops ONE
        # problem's runner from eating the whole run's budget. A value that
        # does not parse as a positive number REFUSES here rather than
        # degrading to "no ceiling" — a bound that silently turns itself off
        # reports a safety it does not provide.
        self.timeout_s: float | None = None
        raw_timeout = os.environ.get("VIBEIC_SOLVE_RUNNER_TIMEOUT_S")
        if raw_timeout is not None and raw_timeout.strip():
            try:
                self.timeout_s = float(raw_timeout)
            except ValueError:
                raise ValueError(
                    "VIBEIC_SOLVE_RUNNER_TIMEOUT_S must be a number of "
                    f"seconds, got {raw_timeout!r}") from None
            if self.timeout_s <= 0:
                raise ValueError(
                    "VIBEIC_SOLVE_RUNNER_TIMEOUT_S must be > 0, got "
                    f"{raw_timeout!r}")
        self._env: dict[str, str] | None = None
        if worker_threads or self.jobs > 1:
            threads = (int(worker_threads) if worker_threads else
                       max(1, (os.cpu_count() or self.jobs) // self.heavy_jobs))
            self._env = os.environ.copy()
            for name in ("VIBEIC_EDA_THREADS", "VIBEIC_OPENROAD_THREADS",
                         "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                         "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
                self._env[name] = str(threads)

    def run(self, argv: list[str], *,
            expected_repaired_output_sha256: str | None = None) -> _ProcessOutcome:
        """Run ONE runner invocation in its own SESSION.

        `start_new_session` is what lets the coordinator take the whole pool
        with it: each child becomes its own process-group leader, so
        `killpg(child_pid)` reaches the tools the runner started rather than
        just the runner. Without it, killing the coordinator leaves the pool
        running -- the orphaned 21 processes measured in BR-07.

        This stays `subprocess.run`, deliberately. It is the seam the existing
        suite fakes the runner at; moving to `Popen` silently bypassed every
        one of those fakes and invoked the real runner, which is a far worse
        failure than the one being fixed.
        """
        _install_orphan_guard()
        kwargs = {"capture_output": True, "text": True,
                  "start_new_session": True}
        if self._env is not None:
            kwargs["env"] = self._env
        if self.timeout_s is not None:
            kwargs["timeout"] = self.timeout_s
        argv = [str(arg) for arg in argv]
        invocation_id = uuid.uuid4().hex
        # Only the canonical runner owns this positional project protocol.
        # Other budget commands may use argv[2] as a file (e.g. a pidfile).
        project = (Path(argv[2]).resolve() if len(argv) > 2
                   and Path(argv[1]).name == "vibe_ic_one_shot_runner.py"
                   and not argv[2].startswith("-") else None)
        rc, error, stdout, stderr = None, None, None, None
        before, after = {}, {}
        material_before = material_after = None
        source_before = source_after = None
        started_ns = finished_ns = None
        try:
            with self._heavy:
                before = _runner_report_snapshot(project) if project else {}
                material_before = _runner_material_snapshot(project) if project else None
                source_before = _runner_source_snapshot(argv) if project else None
                started_ns = time.time_ns()
                if project:
                    _atomic_write_json(project / "reports" / "orchestrator" / "runner_invocations" / "latest.json", {
                        "invocation_id": invocation_id, "argv": argv,
                        "project": str(project), "started_ns": started_ns,
                    })
                    # A private per-call env, including when worker_threads=0.
                    # Never mutate a shared worker environment across siblings.
                    kwargs["env"] = dict(kwargs.get("env") or os.environ)
                    kwargs["env"][_RUNNER_CONTEXT_ENV] = json.dumps({
                        "invocation_id": invocation_id, "argv": argv,
                        "project": str(project), "source": source_before,
                    }, sort_keys=True)
                launch_snapshot = getattr(_D1_LAUNCH_CONTEXT, "snapshot", None)
                if launch_snapshot is not None:
                    owner_project, task, route, activation = _D1_LAUNCH_CONTEXT.authority
                    _require_route_admission(owner_project.parent.parent, task, route)
                    if (_read_current_receipt(owner_project, "route_decision")["receipt"] != route
                            or _read_current_receipt(owner_project, "d1_activation")["receipt"] != activation):
                        raise ValueError("D1_SNAPSHOT_CURRENT_AUTHORITY_REPLACED")
                    _assert_d1_snapshot_current(launch_snapshot)
                    context = _strict_json_loads(kwargs["env"][_RUNNER_CONTEXT_ENV])
                    context["d1_snapshot_sha256"] = launch_snapshot.digest
                    kwargs["env"][_RUNNER_CONTEXT_ENV] = json.dumps(context, sort_keys=True)
                if expected_repaired_output_sha256 is not None:
                    current_output_sha256 = _runner_material_snapshot(project).get(
                        "output_rtl_sha256")
                    if current_output_sha256 != expected_repaired_output_sha256:
                        raise ValueError(
                            "RUNNER_MATERIAL_UNBOUND: repaired RTL changed at runner launch")
                proc = subprocess.run(argv, **kwargs)
                rc = int(proc.returncode)
                stdout = getattr(proc, "stdout", None)
                stderr = getattr(proc, "stderr", None)
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = exc.stdout, exc.stderr
            error = (f"RUNNER_WORKER_FAILED: TimeoutExpired: runner exceeded "
                     f"VIBEIC_SOLVE_RUNNER_TIMEOUT_S={self.timeout_s:g}s "
                     f"and was killed")
        except Exception as exc:                         # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        finally:
            finished_ns = time.time_ns()
            after = _runner_report_snapshot(project) if project else {}
            try:
                material_after = _runner_material_snapshot(project) if project else None
                source_after = _runner_source_snapshot(argv) if project else None
            except (OSError, ValueError) as exc:
                error = f"RUNNER_MATERIAL_UNBOUND: {exc}; runner_error={error}"
        # TimeoutExpired may carry bytes even when text=True was requested.
        stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
        fresh = _runner_fresh_reports(before, after)
        if error is None:
            terminal_error = _runner_terminal_error(rc, stdout or "", stderr or "")
            # A killed/crashed worker cannot complete a gate. Fresh bounded
            # handoff reports remain usable; a process failure is different.
            if terminal_error and terminal_error.startswith("RUNNER_WORKER_FAILED:"):
                error = terminal_error
            elif not fresh:
                error = terminal_error
            if project and not fresh and error is None and rc not in (0, 1):
                error = f"RUNNER_INVOCATION_NOT_MEASURED: exit {rc} published no fresh runner report"
        receipt_path = receipt_sha256 = invocation = None
        if project:
            path = project / "reports" / "orchestrator" / "runner_invocations" / f"{invocation_id}.json"
            receipt = {
                "schema": "vibeic.runner_invocation.v1", "invocation_id": invocation_id,
                "argv": argv, "project": str(project), "rc": rc, "error": error,
                "d1_snapshot_sha256": getattr(getattr(_D1_LAUNCH_CONTEXT, "snapshot", None), "digest", None),
                "stdout": stdout, "stderr": stderr,
                "started_ns": started_ns, "finished_ns": finished_ns,
                "reports_before": before, "reports_after": after,
                "material_before": material_before, "material_after": material_after,
                "source_before": source_before, "source_after": source_after,
                "prompt_sha256": (material_after or {}).get("prompt_sha256"),
                "output_rtl_sha256": (material_after or {}).get("output_rtl_sha256"),
                "record_path": str(path),
                "status": ("REFUSED" if error and "RUNNER_INVOCATION_REFUSED" in error
                           else "WORKER_ERROR" if error else "COMPLETED"),
            }
            try:
                for stream, value in (("stdout", stdout), ("stderr", stderr)):
                    stream_path = path.with_suffix(f".{stream}.txt")
                    receipt[stream + "_path"] = str(stream_path) if value is not None else None
                    receipt[stream + "_sha256"] = _sha256_text(value) if value is not None else None
                    if value is not None:
                        _write_immutable_text(stream_path, value)
                _write_immutable_json(path, receipt)
                receipt_path = str(path)
                receipt_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
                invocation = receipt
            except OSError as exc:
                error = f"RUNNER_DIAGNOSTICS_WRITE_FAILED: {exc}; runner_error={error}"
        return _ProcessOutcome(rc, error, stdout, stderr, invocation_id,
                               receipt_path, receipt_sha256, invocation)


@dataclass(frozen=True)
class _SolveWorkerOutcome:
    index: int
    problem_id: str
    result_json: str
    review_task_json: str | None
    backup_task_json: str | None
    log_line: str


@dataclass(frozen=True)
class _ResumeRunnerOutcome:
    problem_id: str
    rc: int | None
    collected_json: str | None
    error: str | None
    diagnostics_json: str | None = None
    invocation: dict | None = None


def _phase_error_attribution() -> dict:
    """Named no-measurement record for a project worker that could not finish."""
    row = {"status": "NOT_MEASURED", "reason": "PROJECT_WORKER_ERROR"}
    return {
        "phase1_routing": dict(row),
        "phase2_solving": dict(row),
        "phase3_verifying": dict(row),
        "phase4_debugging": dict(row),
    }


# ORGANIC-20260605-shapec-lesson-digest-injection — surface captured lessons to
# blind single-shot authors. The renderer was hoisted to the shared module
# `_lesson_digest` so the PRODUCTION spec-to-rtl path (design_one_shot_runner
# step_rtl_gen WAIVE) surfaces the SAME corpus to runner-driven authors. This
# thin alias preserves the historical `benchmark_dispatch._render_lesson_digest`
# helper name while the only public authoring entry remains `--solve`.
#
# CONSUME CONTRACT (#733 — staged != consumed): the rendered digest header makes
# it MANDATORY that BEFORE authoring each design the author keyword-match the
# design genre against each section's "When to apply" and apply every matched
# section (Section 4-E: apply unless the spec states otherwise). The digest is
# blindness-clean — `_lesson_digest` scrubs benchmark design identifiers so no
# design-name->solution association is surfaced.
from _lesson_digest import render_lesson_digest as _render_lesson_digest  # noqa: E402


def _load_registry() -> dict:
    return _strict_json_loads(REGISTRY.read_text())


def _entry(name: str) -> dict:
    reg = _load_registry()
    e = reg.get("benchmarks", {}).get(name)
    if not e:
        raise SystemExit(
            f"Benchmark '{name}' not in registry. Known: "
            + ", ".join(sorted(reg.get('benchmarks', {}).keys())))
    return e


# THE HOST-REQUIREMENT MODEL LIVES IN ONE PLACE (`benchmark_setup`), AND THIS
# IS THE EDGE THAT REACHES IT. `_env_check` used to probe two tools of its own
# — iverilog and the container — while `benchmark_setup` already carried the
# seven-probe summary AND the per-SHAPE requirement table (`needs`), and
# nothing invoked it. Two answers to "is this host ready" is the drift shape
# this repo keeps removing: the weaker one is the one every caller saw, so a
# Shape-D run missing `docker`, or a Shape-A/B run missing `yosys`, printed a
# clean environment line and then failed inside the runner.
import benchmark_setup as _setup                       # noqa: E402
# R-0915-85 — the five words, imported. See `benchmark_io_adapter`: the export
# door below read `SKIPPED-BY-ENTRY`, which no producer writes any more, and
# refused every supplied-RTL export while looking like a working guard.
import verdict as _V                                     # noqa: E402


def _env_check():
    """The host probe, delegated to the module that owns it.

    Returns `benchmark_setup.env_summary()` — a SUPERSET of the two keys this
    function used to return (`iverilog`, `iic_eda_running` are both still
    present and mean the same thing), so every existing reader keeps working
    and the requirement table below can be asked about the other five.
    """
    return _setup.env_summary()


def _requirement_report(entry: dict, env: dict) -> tuple[list, list]:
    """`(needed, missing)` for one registry entry, per `benchmark_setup.needs`.

    The shape->requirement mapping is NOT restated here. `needs()` is the one
    table, and a shape added to it is answered by this dispatcher for free.
    """
    needed = sorted(_setup.needs(entry))
    return needed, [k for k in needed if not env.get(k)]


def cmd_list():
    reg = _load_registry()
    print(f"{'BENCHMARK':<22}{'SHAPE':<8}STATUS")
    print("-" * 80)
    for name, e in reg.get("benchmarks", {}).items():
        print(f"{name:<22}{e.get('shape',''):<8}{e.get('status','')}")


def cmd_show(bench: str):
    e = _entry(bench)
    print(f"# {e.get('title', bench)}")
    print(f"  Shape: {e['shape']}     Status: {e.get('status')}")
    # § 4.1 + § 8.1 of open-benchmark-methodology (user directive 2026-06-04,
    # BINDING, supersedes the 2026-05-29 re-attempt-FAILing-set default):
    # DEFAULT on "run X benchmark" with no qualifier = CLEAN-ROOM FULL re-run.
    print()
    print("# DEFAULT BEHAVIOUR (per skill § 4.1 + § 8.1, 2026-06-04 user policy):")
    print("# 'run <bench>' with no flag = CLEAN-ROOM FULL re-run. A fresh agent")
    print("# authors EVERY problem from the spec alone, blind to any prior run.")
    print("# The authoring context starts EMPTY. A clean-room run MUST NOT read:")
    print("#   (1) prior run samples / artifacts,")
    print("#   (2) agent memory,")
    print("#   (3) any cached result in storage (prior pass_at_1.json / scores).")
    print("# --solve creates a FRESH run dir and stages INPUT only; the")
    print("# benchmark_clean_room_check.py guard FAILs a contaminated run so it")
    print("# cannot be scored as canonical.")
    print("#")
    print("# Partial prior-failure runs are not a benchmark result. Every canonical")
    print("# invocation processes the complete current dataset through this path.")
    print()
    if "dataset" in e:
        ds = e["dataset"]
        if "repo" in ds:
            print(f"  Dataset repo: {ds['repo']}")
        if "huggingface" in ds:
            print(f"  Dataset HF:   {ds['huggingface']}")
        if "license" in ds:
            print(f"  License:      {ds['license']}")
    if e.get("blocker"):
        print(f"  BLOCKER: {e['blocker']}")
        print()
        print("This benchmark is Shape E (blocked / out-of-scope). Document it in your RESULT but do NOT publish a number.")
        return
    print()
    print("## Recommended invocation")
    shape = e["shape"]
    if bench in _BENCH_FORMAT:
        fmt = _BENCH_FORMAT[bench]
        bi = (HARNESS / "blind_instructions_shape_cvdp.md"
              if fmt == "cvdp" else
              HARNESS / ("blind_instructions_shape_b.md"
                         if shape == "B" else "blind_instructions_shape_c.md"))
        print("  1. Use a fresh run directory; do not use a separate scaffold "
              "or benchmark-specific authoring harness.")
        print("  2. Stage EVERY input and issue an AI-first route task:")
        print(f"     python3 {Path(__file__).name} {bench} --solve "
              "--dataset <DATASET> --run <RUNDIR>")
        print(f"  3. Complete input-only AI routing per: {bi}")
        print("     needs_ai_routing.jsonl binds each model decision to the prompt;")
        print("     resume once to run the normal Program path, then complete")
        print("     the resulting blind AI backup/review/repair worklists.")
        print("     needs_ai_backup.jsonl authors only runner-declared WAIVEs;")
        print("     needs_ai_review.jsonl reviews every exact candidate hash.")
        print(f"  4. Resume until {_ACCEPTANCE_REPORT} is COMPLETE:")
        print(f"     python3 {Path(__file__).name} {bench} --resume "
              "--dataset <DATASET> --run <RUNDIR>")
        score_tail = (" --scorer-root <CVDP_BENCHMARK_ROOT>"
                      if fmt == "cvdp" else "")
        print("  5. Run the official scorer on accepted candidates only:")
        print(f"     python3 {Path(__file__).name} {bench} --score "
              f"--dataset <DATASET> --run <RUNDIR>{score_tail}")
    elif shape == "A":
        print("  /vibe-ic-all <project>     # full doc→GDS (benchmark_clean style)")
        print("  Then run skill `benchmark-verify` for the six-pillar verification.")
    elif shape == "D":
        bi = HARNESS / "blind_instructions_shape_d.md"
        scorer = HARNESS / "score_cocotb_mcp.py"
        print(f"  1. Clone dataset: git clone {e['dataset']['repo']} <DATASET>")
        print(f"  2. Pick a problem; project = <DATASET>/<problem_dir>")
        print(f"  3. Drive: vibe_ic_one_shot_runner.py <project> --pdk sky130A")
        print(f"  4. Score: python3 {scorer} --project <project> --top <dut> --rtl work/rtl/<dut>.sv --mount-root <ROOT>")
        print(f"  Blind instructions: {bi}")
    elif isinstance(e.get("flow"), dict):
        # #532 round-2 (adversarial review): composite shapes ("C/D") carry
        # their own documented flow — surface it instead of an empty section.
        for k, v in e["flow"].items():
            print(f"  {k}: {v}")
        if e.get("scorer"):
            print(f"  scorer: {e['scorer']}")
        if e.get("triage"):
            print(f"  triage: {e['triage']}")
    else:
        raise SystemExit(
            f"unhandled shape {shape!r} for {bench!r} and no flow dict in "
            f"the registry entry — refusing to print an empty plan")



# ── OUR OWN GOLDEN CORPUS, CAPTURED AT THE MOMENT THE HOST SAYS PASS ─────────
# `benchmark_golden_capture` records a HOST-VERIFIED, vibe-ic-AUTHORED solution
# tagged with the plugin version + AI model that produced it, in a corpus kept
# SEPARATE from the downloaded `reference_solution` (user directive
# 2026-06-22). The only place that verdict exists is the scorer's
# `pass_at_1.json`, and nothing read it back — so the corpus stayed empty and
# the "how do our solutions evolve across plugin versions / models" question it
# was built to answer had no data at all.
#
# WHY THE MODEL IS REQUIRED AND NOT DEFAULTED. Nothing on this host knows which
# model authored the samples; a default would stamp every row with a guess and
# the cross-version diff would compare two rows that are not comparable. The
# capture is therefore requested explicitly, and refuses without `--ai-model`
# rather than inventing one.
_GOLDEN_DEFAULT_DB = os.path.expanduser("~/vibe_golden/vibe_golden.sqlite")


def _sample_for(run_p: Path, shape: str, ident_value: str) -> Path | None:
    """The on-disk sample the scorer graded, by the harness's own naming.

    Shape B writes `<design>.v` (or `.sv`); Shape C writes `<Prob>_sample01.sv`.
    Returns None when nothing is there — a PASS with no readable sample is not
    capturable and is reported, never captured as an empty solution.
    """
    leaf = ident_value.split("/")[-1]
    cands = ([run_p / "samples" / f"{leaf}_sample01.sv"] if shape == "C"
             else [run_p / "samples" / f"{leaf}.v", run_p / "samples" / f"{leaf}.sv"])
    for c in cands:
        if c.is_file():
            return c
    return None


def capture_goldens(run_p: Path, bench: str, ai_model: str,
                    db: str | None = None, backup: str | None = None) -> dict:
    """Capture every HOST-VERIFIED PASS in `pass_at_1.json` as our own golden.

    Returns a report dict. Counts are stated with their denominator: "captured
    N of M PASSing problems" — a capture count alone would not say how many it
    could not reach.
    """
    import benchmark_golden_capture as _gold             # noqa: PLC0415
    from l_doc_generator_stamp import plugin_version     # noqa: PLC0415

    summary_p = run_p / "pass_at_1.json"
    if not summary_p.is_file():
        return {"captured": 0, "passing": 0,
                "why": f"no {summary_p} — the scorer wrote no verdict to capture"}
    doc = _strict_json_loads(summary_p.read_text())
    shape = doc.get("shape", "")
    results = doc.get("results") or []
    ident = "design" if shape == "B" else "problem"
    version = plugin_version() or "UNSTAMPED"
    scorer = doc.get("tool", "")
    db_path = db or _GOLDEN_DEFAULT_DB
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    passing = [r for r in results if r.get("verdict") == "PASS"]
    captured, unreachable = 0, []
    for r in passing:
        pid = str(r.get(ident, "")).split("/")[-1]
        sample = _sample_for(run_p, shape, str(r.get(ident, "")))
        if sample is None:
            unreachable.append(pid)
            continue
        _gold.capture(db_path, bench, pid, str(sample), None, version, ai_model,
                      host_verdict="PASS", scorer=scorer, run_id=str(run_p),
                      **({"backup": backup} if backup else {}))
        captured += 1
    return {"captured": captured, "passing": len(passing),
            "total_scored": len(results), "db": db_path,
            "plugin_version": version, "ai_model": ai_model,
            "sample_not_found": unreachable}


# A candidate is not accepted merely because Program emitted it. A blind AI
# must review the frozen Program result; rejection requires executable proof.
_REVIEW_TASK_SCHEMA = "vibeic.benchmark.ai_review_task.v3"
_AI_REVIEW_SCHEMA = "vibeic.benchmark.ai_review.v2"
_ACCEPTANCE_SCHEMA = "vibeic.benchmark.program_first_ai_review.v3"
_CANDIDATE_SCHEMA = "vibeic.benchmark.candidate_snapshot.v1"
_CHALLENGE_SCHEMA = "vibeic.benchmark.ai_verification_challenge.v1"
_CHALLENGE_SUPERSESSION_SCHEMA = \
    "vibeic.benchmark.challenge_supersession.v1"
_AI_REPAIR_RECORD_SCHEMA = "vibeic.benchmark.ai_repair_record.v1"
_ROUTE_TASK_SCHEMA = "vibeic.task_route_task.v1"
_AI_ROUTE_SCHEMA = "vibeic.task_route_review.v1"
_ROUTE_WORKLIST = "needs_ai_routing.jsonl"
_ROUTE_INPUT_ANCHOR = "route_input_anchor.json"
_REVIEW_WORKLIST = "needs_ai_review.jsonl"
_BACKUP_WORKLIST = "needs_ai_backup.jsonl"
_REPAIR_WORKLIST = "needs_ai_repair.jsonl"
_CLARIFICATION_WORKLIST = "needs_spec_clarification.jsonl"
_ENHANCEMENT_WORKLIST = "program_enhancement_candidates.jsonl"
_ACCEPTANCE_REPORT = "program_first_ai_review_acceptance.json"
_REVIEW_CORRECTION_SCHEMA = "vibeic.benchmark.ai_review_correction.v1"
_PROGRAM_REGATE_SCHEMA = "vibeic.benchmark.program_regate.v1"
_PRE_GATE_INPUT_SCHEMA = "vibeic.benchmark.pre_gate_input.v1"

#: A verification challenge has three substantive outcomes -- the candidate
#: PASSed it, the candidate FAILed it, or the challenge itself is INVALID --
#: and one that is not an outcome at all. UNAVAILABLE means the host has no
#: simulator, so nothing about this candidate was established either way.
#: Folding it into "not FAIL" charges the AI reviewer with an unproven finding
#: on the strength of a missing tool; folding it into "not PASS" charges the
#: repair with failing a test nobody ran. Both are a MISSING CAPABILITY
#: rendered as a DEFECT IN THE SUBJECT, so it gets its own status and its own
#: name in the acceptance report.
_CHALLENGE_UNAVAILABLE = "UNAVAILABLE"
#: A joint candidate+challenge compile whose every error cites candidate RTL.
#: This is the strongest available evidence that the candidate itself is
#: broken, but it does not prove the AI's specific semantic claim, so it is
#: neither FAIL nor INVALID: FAIL would endorse an assertion no simulation
#: ran, and INVALID would charge the test with the candidate's own defect.
_CHALLENGE_CANDIDATE_BROKEN = "CANDIDATE_BROKEN"
_NOT_MEASURED = "NOT_MEASURED"


def _safe_problem_id(problem_id: str) -> str:
    return re.sub(r"[^-\w.]", "_", str(problem_id))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _task_project(task: dict) -> Optional[Path]:
    """The review task's own project directory, or None.

    The three sites that derive `program_review_obligations` compare their
    results against each other, so they must read the project the SAME way or
    every task reads as stale.
    """
    raw = str((task or {}).get("project") or "")
    return Path(raw) if raw else None


def _review_obligation_id(item: dict) -> str:
    """Stable identity for one Program-extracted review obligation."""
    material = json.dumps({
        "kind": str(item.get("kind") or ""),
        "requirement": str(item.get("requirement") or ""),
        "evidence": str(item.get("evidence") or ""),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(material)[:16]


#: An advisory gate verdict the runner ROUTED and nothing consumed.
#:
#: `gate_directed_rtl_repair` classifies a gate finding it cannot mechanically
#: repair as ESCALATE: the gate is confident about the SHAPE but only a spec can
#: say whether that shape is a defect here. The runner records the verdict under
#: the step's `extras` and moves on, so an ESCALATE reaches no consumer at all —
#: not the repairer, by design, and not the reviewer, by omission.
#:
#: RTLLM 2026-09-07, `asyn_fifo`. `counter_decode_lookahead_phase_check` ran in
#: `determinism_gates` and named both signals exactly:
#:
#:     defect: counter-decode-lookahead-phase   verdict: FINDING
#:     router_verdict: ESCALATE                 blocking: false
#:       wptr <- lookahead of waddr_bin:  wptr <= bin2gray(waddr_bin + wen);
#:       rptr <- lookahead of raddr_bin:  rptr <= bin2gray(raddr_bin + ren);
#:
#: The gate was RIGHT. The reference registers the gray code of the CURRENT
#: binary value; this candidate registered the gray of the LOOKAHEAD, publishing
#: both pointers one cycle early, and it failed the official testbench. Nothing
#: repaired it — correctly, since a leading level is legal when a spec asks for
#: one. But the blind reviewer was never told either, so its FIFO challenge never
#: drove the full/empty boundary where the phase is observable, and it recorded a
#: semantic PASS on a candidate the Program had already described in writing.
#:
#: Routing these to the reviewer costs nothing and is the difference between a
#: measurement taken and a measurement thrown away.
_ROUTED_ESCALATION_VERDICTS = frozenset({"FINDING", "ESCALATE"})


#: Statuses that are a REQUIRED gate REPORTING A FAILURE. Deliberately only the
#: unambiguous three: this list decides what HOLDS a deliverable, and widening
#: it to statuses that merely mean "not run" (BLOCKED) or "not applicable"
#: (SKIP / SKIPPED-BY-ENTRY / WAIVED / ADVISORY) would be the blanket
#: all-history-green rule #2216 explicitly forbids. MEASURED on the published
#: VerilogEval-Human corpus: 61 accepted rows carry 163 FAIL steps and NOT ONE
#: of them is an in-scope site gate, so this predicate blocks none of them.
_GATE_FAILED = frozenset({"FAIL", "REFUSED", "ERROR"})

#: Statuses that mean the gate DID NOT REPORT — the run never got an answer out
#: of it. Not a pass and not a failure: a hole. MEASURED: `rtl_validate` is
#: BLOCKED on 44 of those 61 accepted rows and absent on the other 17, so this
#: is the ordinary state of a required in-scope gate today, and the accepting
#: message has been claiming those gates passed.
_GATE_UNMEASURED = frozenset({"BLOCKED", "INCOMPLETE", "NOT_MEASURED", ""})


def _required_gate_ledger(solve_result: Any) -> dict:
    """Which REQUIRED IN-SCOPE Program gates this run declared, and what each
    actually said — the ledger #2216 says does not exist.

    THE GAP THIS CLOSES. The accept path asks four questions: is the artefact
    owned by the runner, does the reviewed hash still match, is Phase-1
    provenance intact, and did the RTL-OWNING gate (`rtl_gen`) reach an allowed
    status. It then prints `ACCEPTED by PROGRAM gates`, which is a claim about
    EVERY required gate. No question it asked can see a second, downstream,
    in-scope gate that FAILED on the same RTL. Measured on the real collector
    with the issue's own probe: `rtl_gen=PASS, rtl_validate=FAIL` collects
    `ok=True` and reaches that message.

    SCOPE IS READ, NEVER INVENTED, from two records the run already publishes:

      * `step_preflight.RUNNER_PLANS["design_one_shot_runner"].sites` — the
        runner's OWN ordered (site, flow-step-span) declaration, the same table
        `--exit-step` prunes against, so "in scope" here means exactly what the
        runner meant when it decided which sites to dispatch;
      * the run's declared ``exit`` in solve_report.

    The shared `step_preflight.exit_pruned_sites` defines the exit boundary.
    Named exits use dispatch order; numeric exits use span HEADs because a
    span is one dispatch and cannot be stopped mid-span. A numeric exit cannot
    establish the scope of a non-numeric span.

    WHAT IS DELIBERATELY *NOT* CLAIMED. A gate the ledger cannot place on the
    flow (`sdc_gen`, `final_audit`, `lec_equivalence`, …) is recorded under
    ``unscoped`` and NEVER blocks. Guessing a step id for it would be inventing
    the scope oracle this function exists to read, and blocking on a guess
    would fail 61 published candidates whose out-of-exit FAILs are #2208's
    producer/consumer defect, not a defect in the reviewed RTL.

    ELIGIBILITY IS THREE-VALUED, and the third value is the point:
      * ``INELIGIBLE`` — a required in-scope gate REPORTED a failure;
      * ``ELIGIBLE``   — every required in-scope gate reported an allowed status;
      * ``NOT_MEASURED`` — a required in-scope gate never reported at all.
        Never collapsed into either neighbour. Reporting a hole as ELIGIBLE is
        the defect; reporting it as INELIGIBLE would fail 61 published
        candidates for a state nobody measured.

    Pure: reads one dict, returns one dict. chip-AGNOSTIC.
    """
    ledger = {
        "schema": "vibeic.benchmark.required_gate_ledger.v1",
        "declared_exit": None, "in_scope": {}, "out_of_scope": {},
        "unscoped": {}, "failed_required": [], "unmeasured_required": [],
        "eligibility": _NOT_MEASURED,
        "scope_source": ("step_preflight.RUNNER_PLANS[design_one_shot_runner]"
                         " + solve_report.exit"),
    }
    if not isinstance(solve_result, dict):
        ledger["why"] = "solve_report row is malformed, so no gate is placeable"
        return ledger
    ledger["declared_exit"] = solve_result.get("exit")
    phases = solve_result.get("phases")
    p3 = (phases or {}).get("phase3_verifying") if isinstance(phases, dict) else None
    if not isinstance(p3, dict):
        ledger["why"] = "solve_report carries no Program gate record"
        return ledger
    recorded: dict = {}
    for key in ("ran", "not_attempted"):
        block = p3.get(key)
        if isinstance(block, dict):
            for name, status in block.items():
                recorded[str(name)] = str(status)
    if not recorded:
        ledger["why"] = "the Program gate record names no gate"
        return ledger

    try:
        import step_preflight as _spf                     # noqa: PLC0415
        plan = _spf.RUNNER_PLANS.get("design_one_shot_runner")
        sites = [(str(n), [str(x) for x in span])
                 for n, span in (plan.sites if plan else ())]
    except Exception:                                     # noqa: BLE001
        sites = []
    if not sites:
        ledger["unscoped"] = dict(sorted(recorded.items()))
        ledger["why"] = ("the runner's own site plan is unreadable, so no gate "
                         "can be placed on the flow")
        return ledger

    pruned = _spf.exit_pruned_sites(sites, ledger["declared_exit"])
    if pruned is None:
        ledger["unscoped"] = dict(sorted(recorded.items()))
        ledger["why"] = (f"declared exit {ledger['declared_exit']!r} is not an "
                         f"orderable flow step id or named site, so nothing can be scoped")
        return ledger

    pruned = set(pruned)
    named_exit = ledger["declared_exit"] in {name for name, _ in sites}
    placed = set()
    for name, span in sites:
        scope_known = named_exit or bool(span and str(span[0]).isdigit())
        in_scope = scope_known and name not in pruned
        if name not in recorded:
            # A site the run never recorded at all. In scope, and it did not
            # report — that is a hole, and it is named as one.
            if in_scope:
                ledger["in_scope"][name] = "(absent)"
                ledger["unmeasured_required"].append(name)
            continue
        placed.add(name)
        status = recorded[name]
        if not scope_known:
            ledger["unscoped"][name] = status
            continue
        if in_scope:
            ledger["in_scope"][name] = status
            if status.upper() in _GATE_FAILED:
                ledger["failed_required"].append(name)
            elif status.upper() in _GATE_UNMEASURED:
                ledger["unmeasured_required"].append(name)
        else:
            ledger["out_of_scope"][name] = status
    for name, status in recorded.items():
        if name not in placed and name not in ledger["unscoped"]:
            ledger["unscoped"][name] = status

    for key in ("in_scope", "out_of_scope", "unscoped"):
        ledger[key] = dict(sorted(ledger[key].items()))
    ledger["failed_required"] = sorted(set(ledger["failed_required"]))
    ledger["unmeasured_required"] = sorted(set(ledger["unmeasured_required"]))
    if ledger["failed_required"]:
        ledger["eligibility"] = "INELIGIBLE"
    elif ledger["unmeasured_required"]:
        ledger["eligibility"] = _NOT_MEASURED
    elif ledger["in_scope"]:
        ledger["eligibility"] = "ELIGIBLE"
    return ledger


def _gate_evidence_freshness_reasons(project: Path, result: dict) -> list[str]:
    """BLOCKING: acceptance/export must not reuse a stale gate snapshot.

    Derive both ledgers with the existing policy, including NOT_MEASURED for
    BLOCKED. Compare gate evidence, not the whole attribution: AI review adds
    fields to the latter without changing the Program's measured gates.
    """
    import flow_phase_attribution as fpa                 # noqa: PLC0415
    try:
        rep, why = fpa.step_report(project)
        if rep is None:
            return [f"current Program gate evidence is unavailable: {why}"]
        current = {
            "exit": result.get("exit"),
            "phases": {"phase3_verifying": fpa.phase3_verifying(rep, why)},
        }
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return [f"current Program gate evidence is unreadable: {exc}"]
    if _required_gate_ledger(current) != _required_gate_ledger(result):
        return ["Program gate evidence changed since the solve snapshot; "
                "the reviewed evidence is stale"]
    return []


def _gate_status_note(ledger: dict) -> str:
    """One line stating what the gates ACTUALLY said, for the accepting
    message. Never the words "by PROGRAM gates" over an unmeasured ledger."""
    elig = str(ledger.get("eligibility") or _NOT_MEASURED)
    if elig == "ELIGIBLE":
        return (f"PROGRAM gates ELIGIBLE "
                f"({len(ledger.get('in_scope') or {})} in-scope PASS)")
    if elig == "INELIGIBLE":
        return ("PROGRAM gates INELIGIBLE: "
                + ", ".join(ledger.get("failed_required") or []))
    holes = ledger.get("unmeasured_required") or []
    return ("PROGRAM gate eligibility NOT_MEASURED"
            + (f" ({', '.join(holes)} did not report)" if holes else ""))


def _program_gate_escalations(project: Optional[Path]) -> list:
    """Advisory gate findings this project raised that nothing acted on.

    §4.05 NO-LEAK, and why this is admissible: every value read here is derived
    by a gate from the CANDIDATE RTL and the PROMPT, the two artefacts the
    reviewer already holds. No oracle, golden, hidden harness, official
    testbench or score is opened. The reviewer learns what the Program SUSPECTS
    ABOUT THE BYTES IT IS REVIEWING — never what the answer is.

    Deterministic: the result is part of a hashed contract recomputed
    independently at three call sites, so findings are emitted in a stable
    order. Missing or unreadable evidence yields [] — an absent record is not a
    finding, and inventing an obligation from one would block a candidate on
    nothing.
    """
    if project is None:
        return []
    try:
        doc = _strict_json_loads(
            (Path(project) / "reports" / "orchestrator"
             / "phase2_one_shot.json").read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict):
        return []
    out = []
    for step in doc.get("steps") or []:
        if not isinstance(step, dict):
            continue
        extras = step.get("extras")
        if not isinstance(extras, dict):
            continue
        for advisory in extras.values():
            if not isinstance(advisory, dict):
                continue          # e.g. `advisory_only: true`, a bare flag
            gate = advisory.get("gate")
            findings = advisory.get("findings")
            if not (isinstance(gate, str) and gate):
                continue
            if not (isinstance(findings, list) and findings):
                continue
            routed = str(advisory.get("router_verdict") or "") == "ESCALATE"
            unconsumed = (
                str(advisory.get("verdict") or "") in _ROUTED_ESCALATION_VERDICTS
                and advisory.get("blocking") is False)
            if not (routed or unconsumed):
                continue          # a BLOCKING finding already stopped the step
            named = []
            for f in findings:
                if not isinstance(f, dict):
                    continue
                signal = f.get("signal")
                if not (isinstance(signal, str) and signal):
                    continue
                statement = f.get("statement")
                named.append((signal,
                              statement if isinstance(statement, str) else ""))
            if not named:
                continue
            out.append({
                "gate": gate,
                "defect": str(advisory.get("defect") or gate),
                "step": str(step.get("name") or ""),
                "signals": sorted(set(named)),
            })
    out.sort(key=lambda e: (e["gate"], e["step"]))
    return out


def _gate_escalation_obligation(escalation: dict) -> dict:
    """One routed escalation, as an obligation a test must DISCRIMINATE."""
    signals = ", ".join(sig for sig, _ in escalation["signals"])
    return {
        "kind": "gate_escalation",
        "requirement": (
            f"PROGRAM gate {escalation['gate']} reports "
            f"{escalation['defect']} on this exact candidate, naming "
            f"{signals}. The gate is ADVISORY, so nothing repaired it and the "
            f"candidate still carries the shape described. Your executable "
            f"test must reach the behaviour that would DIFFER if the finding "
            f"is real; a test that never exercises it does not discharge this "
            f"obligation. If the prompt sanctions that shape, say so in "
            f"findings and quote the prompt line that does."),
        "evidence": "; ".join(
            f"{sig}: {stmt}" for sig, stmt in escalation["signals"])[:400],
        "coverage_tokens": [sig for sig, _ in escalation["signals"]],
        "source_step": escalation["step"],
    }


def _program_review_obligation_contract(prompt_text: str,
                                        candidate: dict,
                                        project: Optional[Path] = None) -> dict:
    """Extract the structural minimum an AI PASS test must cover.

    ``spec_coverage_check`` is the existing benchmark-agnostic Program reader.
    This adapter does not invent a second extractor: it turns that reader's
    exact block-eligible items into a hash-bound handoff for AI Backup.
    """
    import spec_coverage_check as coverage                 # noqa: PLC0415

    rtl_text = _candidate_text(
        [Path(str(p)) for p in candidate.get("rtl_paths") or []])
    report = coverage.run(
        {"user_prompt": prompt_text}, rtl_text, None, None, True)
    obligations = []
    for item in report.get("items") or []:
        if not item.get("block_eligible", True):
            continue
        row = {
            "kind": item.get("kind"),
            "requirement": item.get("requirement"),
            "evidence": item.get("evidence"),
            "coverage_tokens": item.get("coverage_tokens") or [],
        }
        row["id"] = _review_obligation_id(row)
        obligations.append(row)
    # Gate escalations the runner ROUTED and nothing consumed. APPENDED, never
    # replacing the structural minimum: the two answer different questions, and
    # a project with no escalation must produce the identical contract it
    # produced before this existed.
    escalations = _program_gate_escalations(project)
    for escalation in escalations:
        row = _gate_escalation_obligation(escalation)
        row["id"] = _review_obligation_id(row)
        obligations.append(row)
    core = {
        "schema": "vibeic.benchmark.program_review_obligations.v1",
        "actor": ("programs/spec_coverage_check.py" + (
            " + routed PROGRAM gate escalations" if escalations else "")),
        "policy": "BLOCKING_STRUCTURAL_MINIMUM",
        "obligation_count": len(obligations),
        "obligations": obligations,
    }
    return {
        **core,
        "sha256": _sha256_text(json.dumps(
            core, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"))),
    }


def _program_review_coverage_result(prompt_text: str, candidate: dict,
                                    challenges: list[dict]) -> dict:
    """Measure active AI tests against Program's structural obligations."""
    import spec_coverage_check as coverage                 # noqa: PLC0415

    rtl_text = _candidate_text(
        [Path(str(p)) for p in candidate.get("rtl_paths") or []])
    test_parts = []
    for challenge in challenges:
        path = Path(str(challenge.get("path") or ""))
        text = path.read_text(errors="replace")
        if _sha256_text(text) != challenge.get("sha256"):
            raise ValueError(
                f"active verification challenge hash changed at {path}")
        test_parts.append(text)
    report = coverage.run(
        {"user_prompt": prompt_text}, rtl_text,
        "\n\n".join(test_parts), None, True)
    gaps = []
    for item in report.get("items") or []:
        if item.get("covered") is not False \
                or not item.get("block_eligible", True):
            continue
        row = {
            "kind": item.get("kind"),
            "requirement": item.get("requirement"),
            "evidence": item.get("evidence"),
            "coverage_tokens": item.get("coverage_tokens") or [],
            "coverage_note": item.get("coverage_note"),
        }
        row["id"] = _review_obligation_id(row)
        gaps.append(row)
    return {
        "schema": "vibeic.benchmark.program_review_coverage.v1",
        "actor": "programs/spec_coverage_check.py",
        "status": "PASS" if not gaps else "FAIL",
        "active_challenge_sha256": [c.get("sha256") for c in challenges],
        "checklist_items": report.get("checklist_items"),
        "covered": report.get("covered"),
        "coverage_gaps": report.get("coverage_gaps"),
        "blocking_gaps": report.get("blocking_gaps"),
        "blocking_gap_items": gaps,
    }


def _rtl_files(project: Path) -> list[Path]:
    rtl_dir = Path(project) / "phase2" / "stage1" / "rtl"
    return sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v")))


def _candidate_text(paths: list[Path]) -> str:
    return "\n".join(Path(p).read_text(errors="replace") for p in paths)


def _write_immutable_text(path: Path, value: str) -> None:
    """Write evidence once; a hash-addressed artefact may never be replaced."""
    path = Path(path)
    if path.is_file():
        if path.read_text(errors="replace") != value:
            raise ValueError(f"immutable evidence changed at {path}")
        return
    _atomic_write_text(path, value)


def _write_immutable_json(path: Path, value: dict) -> None:
    """JSON form of :func:`_write_immutable_text`."""
    path = Path(path)
    if path.is_file():
        try:
            current = _strict_json_loads(path.read_text(errors="replace"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"immutable evidence unreadable at {path}: {exc}") from exc
        if current != value:
            raise ValueError(f"immutable evidence changed at {path}")
        return
    _atomic_write_json(path, value)


def _write_immutable_bytes(path: Path, value: bytes) -> None:
    """Preserve measured RTL bytes, including source newline encoding."""
    if path.is_file():
        if path.read_bytes() != value:
            raise ValueError(f"immutable evidence changed at {path}")
        return
    _atomic_write_bytes(path, value)


def _archive_candidate(problem_id: str, project: Path, got: dict,
                       run_p: Path, candidate_origin: str, *,
                       archive_key: str | None = None) -> dict:
    """Freeze the exact gated candidate before an AI can edit the work tree."""
    project, run_p = Path(project).resolve(), Path(run_p).resolve()
    source_paths = _rtl_files(project)
    completion = str(got.get("completion") or "")
    rtl_hash = _sha256_text(completion)
    safe = _safe_problem_id(problem_id)
    origin = _safe_problem_id(archive_key or candidate_origin).lower()
    root = run_p / "candidate_snapshots" / safe / f"{origin}-{rtl_hash}"
    frozen_paths: list[str] = []
    for index, source in enumerate(source_paths):
        frozen = root / "rtl" / f"{index:02d}_{source.name}"
        _write_immutable_bytes(frozen, source.read_bytes())
        frozen_paths.append(str(frozen.resolve()))
    completion_path = root / "completion.txt"
    payload_path = root / "response_payload.json"
    _write_immutable_text(completion_path, completion)
    _write_immutable_json(payload_path, got)
    record = {
        "schema": _CANDIDATE_SCHEMA,
        "id": str(problem_id),
        "candidate_origin": candidate_origin,
        "rtl_sha256": rtl_hash,
        "rtl_paths": frozen_paths,
        "completion_path": str(completion_path.resolve()),
        "response_payload_path": str(payload_path.resolve()),
        "source_rtl_paths": [str(p.resolve()) for p in source_paths],
    }
    manifest = root / "manifest.json"
    record["manifest_path"] = str(manifest.resolve())
    _write_immutable_json(manifest, record)
    return record


def _program_version() -> str:
    """The running Program's own version, or "" when the manifest is unreadable.

    An empty string is reported as-is. A retry that cannot name which Program
    produced which bytes is not evidence, and a default would invent one.
    """
    from l_doc_generator_stamp import plugin_version     # noqa: PLC0415
    try:
        return str(plugin_version() or "")
    except Exception:                                    # noqa: BLE001
        return ""


def _pre_gate_input_root(run_p: Path, problem_id: str, signed_hash: str) -> Path:
    return (Path(run_p).resolve() / "pre_gate_inputs"
            / _safe_problem_id(problem_id) / str(signed_hash))


def _archive_pre_gate_input(run_p: Path, problem_id: str,
                            source_paths: list[Path], signed_hash: str) -> dict:
    """Freeze the exact SIGNED bytes the PROGRAM gates are about to consume.

    The gates may normalize this RTL in place, and that overwrite destroys the
    only copy of what the author actually signed. When a later Program fix
    changes the transform there is then nothing to re-enter FROM: the frozen
    output is unwanted, and re-signing it would attribute a Program mutation to
    the author. Preserving the input at this boundary makes the pair
    (signed input sha, gate output sha) a recorded fact rather than something
    reconstructed after the fact.

    Immutable: a second call with the same bytes is a no-op, and different
    bytes under the same hash raise rather than overwrite.
    """
    root = _pre_gate_input_root(run_p, problem_id, signed_hash)
    frozen: list[str] = []
    for index, source in enumerate(source_paths):
        target = root / "rtl" / f"{index:02d}_{source.name}"
        _write_immutable_text(target, source.read_text(errors="replace"))
        frozen.append(str(target.resolve()))
    record = {
        "schema": _PRE_GATE_INPUT_SCHEMA,
        "id": str(problem_id),
        "rtl_sha256": str(signed_hash),
        "rtl_paths": frozen,
        "source_rtl_paths": [str(Path(p).resolve()) for p in source_paths],
        "program_version": _program_version(),
    }
    manifest = root / "manifest.json"
    record["manifest_path"] = str(manifest.resolve())
    _write_immutable_json(manifest, record)
    return record


def _bind_pre_gate_output(preserved: dict, output_hash: str) -> dict:
    """Record the (signed input -> gate output) pair the gates just produced.

    One immutable file per pair, so which Program turned which signed input
    into which frozen output is readable later without re-running anything.
    """
    record = {
        "schema": _PRE_GATE_INPUT_SCHEMA,
        "id": str(preserved.get("id")),
        "signed_input_sha256": str(preserved.get("rtl_sha256")),
        "gate_output_sha256": str(output_hash),
        "input_manifest_path": str(preserved.get("manifest_path")),
        "program_version": _program_version(),
    }
    path = (Path(str(preserved["manifest_path"])).parent
            / f"gate_output_{output_hash}.json")
    _write_immutable_json(path, record)
    return {**record, "binding_path": str(path.resolve())}


def _preserved_input_paths(preserved: dict) -> list[Path]:
    return [Path(str(p)) for p in preserved.get("rtl_paths") or []]


def _pre_gate_input_manifest(regate: dict) -> dict | None:
    """The preserved signed-input manifest a regate names, or None.

    None means "could not read it or it does not verify" -- never an empty
    default. The bytes on disk must still hash to the signed input hash the
    record claims, or the record describes something that is no longer there.
    """
    path = Path(str((regate or {}).get("input_manifest_path") or ""))
    try:
        preserved = _strict_json_loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(preserved, dict) \
            or preserved.get("schema") != _PRE_GATE_INPUT_SCHEMA:
        return None
    signed = str(preserved.get("rtl_sha256") or "")
    if signed != str(regate.get("signed_input_sha256") or ""):
        return None
    paths = _preserved_input_paths(preserved)
    if not paths or not all(q.is_file() for q in paths):
        return None
    try:
        if _sha256_text(_candidate_text(paths)) != signed:
            return None
    except OSError:
        return None
    return preserved


def _program_output_repair_contract(author_contract: dict, identity: dict,
                                    material: dict) -> dict:
    """Separate PROGRAM declaration; never edit the author's signed preimage.

    Only explicit reentry uses this after validating the original declaration
    and the actual invocation. Keep every source/fragment/configuration
    obligation and bind its candidate hashes to that invocation's output.
    """
    derived = _strict_json_loads(json.dumps(author_contract))
    derived["author"] = {"kind": "PROGRAM", "program_identity": identity}
    derived["candidate_sha256"] = material["output_rtl_sha256"]
    outputs = material["output_rtl"]

    def output_hash(path):
        if not isinstance(path, str):
            raise ValueError("Program output declaration lacks an exact source path")
        key = path[4:] if path.startswith("rtl/") else path
        return outputs[key]["sha256"]

    preservation = derived["preservation"]
    preservation.pop("candidate_sha256", None)
    for row in preservation["sources"]:
        row["candidate_sha256"] = output_hash(row["path"])
    matrix = derived["elaboration_matrix"]
    path = matrix.get("source_path", matrix.get("source"))
    if isinstance(path, dict):
        path = path.get("path")
    matrix["candidate_sha256"] = output_hash(path)
    return derived


def _verified_program_regate(task: dict) -> dict | None:
    """The regate record ONLY if every one of its bindings still holds.

    Returns None -- leaving every existing refusal exactly as it was -- unless
    the task carries a complete `program_regate` whose preserved input is still
    on disk with the signed bytes, whose recorded new output is this task's own
    frozen candidate, and whose Program version actually moved. A record that
    fails ANY of these is not evidence and is treated as absent.
    """
    regate = task.get("program_regate")
    if not isinstance(regate, dict):
        return None
    if regate.get("schema") != _PROGRAM_REGATE_SCHEMA:
        return None
    signed = str(regate.get("signed_input_sha256") or "")
    produced = str(regate.get("new_output_sha256") or "")
    before = str(regate.get("program_version_before") or "")
    after = str(regate.get("program_version_after") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", signed):
        return None
    if produced != str(task.get("rtl_sha256") or ""):
        return None
    if not before or not after or before == after:
        return None
    preserved = _pre_gate_input_manifest(regate)
    if preserved is None or str(preserved.get("id")) != str(task.get("id")):
        return None
    # The named "before" version is not decoration: it must be the Program
    # that actually produced the preserved input.
    if before != str(preserved.get("program_version") or ""):
        return None
    # A hash pair alone cannot move the author's signature to a preimage.
    # Reuse the retained current producer/collector receipts and immutable
    # declaration from the explicit operation. An unchanged unwanted output
    # is not recovery evidence and retains its final-signature refusal.
    if produced == regate.get("stale_output_sha256"):
        return None
    try:
        run_p = Path(task["project"]).resolve().parent.parent
        archive = _regate_path(regate["archive_path"], run_p, exists=False)
        if not archive.is_dir():
            return None
        if _read_json_regular(archive / "complete.json") != regate:
            return None
        declaration_path = _regate_path(regate["output_contract_path"], run_p)
        if declaration_path != archive / "output_contract.json":
            return None
        if hashlib.sha256(declaration_path.read_bytes()).hexdigest() != regate["output_contract_sha256"]:
            return None
        declaration = _read_json_regular(declaration_path)
        preimage_path = _regate_path(archive / "preimage_contract.json", run_p)
        if hashlib.sha256(preimage_path.read_bytes()).hexdigest() != declaration["preimage_contract_sha256"]:
            return None
        preimage = _read_json_regular(preimage_path)
        invocation = task["program_verification"]["runner_invocation"]
        author_path = _regate_path(task["repair_provenance"]["path"], run_p)
        author_hash = hashlib.sha256(author_path.read_bytes()).hexdigest()
        if (declaration["schema"] != _PROGRAM_REGATE_SCHEMA
                or declaration["actor"] != "PROGRAM"
                or declaration["program_identity"] != regate["program_identity"]
                or declaration["runner_invocation"] != invocation
                or declaration["signed_input_sha256"] != signed
                or declaration["output_rtl_sha256"] != produced
                or declaration["author_record_sha256"] != author_hash
                or preimage["author_record_sha256"] != author_hash
                or preimage["signed_input_sha256"] != signed
                or preimage["validation"]["verdict"] != "PASS"
                or invocation["status"] != "COMPLETED"
                or invocation["material_before"] != preimage["input_material"]
                or invocation["material_before"]["output_rtl_sha256"] != signed
                or invocation["material_after"]["output_rtl_sha256"] != produced
                or _runner_material_snapshot(Path(task["project"])) != invocation["material_after"]
                or invocation["material_before"]["input"] != invocation["material_after"]["input"]
                or declaration["repair_contract"] != _program_output_repair_contract(
                    task["repair_provenance"]["repair_contract"],
                    regate["program_identity"], invocation["material_after"])):
            return None
        diagnostic = _stored_runner_diagnostics(invocation)
        if diagnostic and diagnostic.get("reason"):
            return None
        _runner_frozen_material(invocation, task["candidate_snapshot"])
        measured = _read_json_regular(archive / "runner_result.json")
        if (measured["runner_invocation"] != invocation
                or measured["collected"]["repair_contract"]["verdict"] != "PASS"
                or not measured["collected"]["ok"]):
            return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return regate


def _signed_candidate_hash(task: dict) -> str:
    """The hash an AI repair author's signature is required to cover.

    Normally the frozen candidate itself: the author signs the bytes that were
    reviewed. After a VERIFIED Program re-entry the author's bytes are the
    preserved signed INPUT instead -- the Program, not the author, produced the
    difference, so requiring the author's signature over the Program's output
    would attribute a Program mutation to the author. With no verified regate
    record this is `task["rtl_sha256"]`, exactly as before.
    """
    regate = _verified_program_regate(task)
    if regate is None:
        return str(task.get("rtl_sha256") or "")
    return str(regate.get("signed_input_sha256") or "")


def _validate_candidate_snapshot(candidate: dict, problem_id: str) -> list[str]:
    """Return tamper/missing reasons for one immutable candidate record."""
    reasons: list[str] = []
    if not isinstance(candidate, dict):
        return ["candidate snapshot is absent"]
    if candidate.get("schema") != _CANDIDATE_SCHEMA:
        reasons.append(f"candidate schema must be {_CANDIDATE_SCHEMA!r}")
    if str(candidate.get("id")) != str(problem_id):
        reasons.append("candidate id does not match the review task")
    paths = [Path(str(p)) for p in candidate.get("rtl_paths") or []]
    if not paths or not all(p.is_file() for p in paths):
        reasons.append("candidate snapshot RTL is absent")
    completion_path = Path(str(candidate.get("completion_path") or ""))
    payload_path = Path(str(candidate.get("response_payload_path") or ""))
    if not completion_path.is_file():
        reasons.append("candidate snapshot completion is absent")
        completion = ""
    else:
        completion = completion_path.read_text(errors="replace")
    expected_hash = candidate.get("rtl_sha256")
    if _sha256_text(completion) != expected_hash:
        reasons.append("candidate snapshot completion hash is stale or wrong")
    if paths:
        try:
            if _sha256_text(_candidate_text(paths)) != expected_hash:
                reasons.append("candidate snapshot RTL bytes do not match completion")
        except OSError as exc:
            reasons.append(f"candidate snapshot RTL is unreadable: {exc}")
    try:
        payload = _strict_json_loads(payload_path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        reasons.append(f"candidate snapshot response payload is unreadable: {exc}")
    else:
        if _sha256_text(str(payload.get("completion") or "")) != expected_hash:
            reasons.append("candidate snapshot response payload does not match RTL")
    manifest_path = Path(str(candidate.get("manifest_path") or ""))
    try:
        manifest = _strict_json_loads(manifest_path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        reasons.append(f"candidate snapshot manifest is unreadable: {exc}")
    else:
        if manifest != candidate:
            reasons.append("candidate snapshot manifest differs from its task record")
    return reasons


def _archive_repair_input(problem_id: str, project: Path, run_p: Path,
                          provenance: dict) -> dict:
    """BLOCKING: preserve and revalidate signed input before Program can edit it."""
    candidate = _archive_candidate(problem_id, project, {
        "id": problem_id, "ok": True,
        "completion": _candidate_text(_rtl_files(project))}, run_p, "AI_REPAIR_INPUT")
    if (candidate["rtl_sha256"] != provenance.get("repaired_rtl_sha256")
            or _validate_candidate_snapshot(candidate, problem_id)):
        raise ValueError("AI_REPAIR_INPUT_REFUSED: signed input changed before Program gates")
    return candidate


def _required_scorer_top(entry: dict, fmt: str | None = None) -> str | None:
    """The one module name this benchmark's scorer will instantiate, if it
    fixes one. Driven by the registry's `module_name_strategy`; no per-benchmark
    branch and no problem-specific knowledge.

    Takes the REGISTRY ENTRY, and says so loudly if handed anything else. The
    name `entry` is overloaded in this module: inside the solve/resume workers a
    local `entry` is the runner's ENTRY STEP (a str/int), not the registry
    entry. Passing that here used to raise a bare AttributeError inside the
    per-problem worker, which caught it, reported NOT_MEASURED for that problem,
    and carried on -- so a miswiring produced a full run of 156 NOT_MEASURED
    rows and "0/156 produced a gated candidate" with no single message naming
    the cause. A named TypeError makes the same mistake self-identifying.
    Call it as `_required_scorer_top(_entry(bench))`."""
    if entry is not None and not isinstance(entry, dict):
        raise TypeError(
            "_required_scorer_top expects the REGISTRY ENTRY dict, got "
            f"{type(entry).__name__} {entry!r}. Inside the solve/resume workers "
            "the local `entry` is the runner's entry STEP; pass "
            "_entry(bench) instead.")
    # Explicit Shape D replaces the default I/O protocol, including any
    # nonagentic scorer's fixed top-name constraint. Its scorer is external.
    if fmt == "agentic":
        return None
    strategy = ((entry or {}).get("layout") or {}).get("module_name_strategy")
    return "TopModule" if strategy == "always_TopModule" else None


def _make_ai_review_task(problem_id: str, project: Path, got: dict,
                         routing: dict, runner_rc: int, run_p: Path,
                         candidate_origin: str, *,
                         program_phases: dict | None = None,
                         verification_challenges: list[dict] | None = None,
                         program_candidate: dict | None = None,
                         repair_parent_candidate: dict | None = None,
                         repair_provenance: dict | None = None,
                         repair_input_candidate: dict | None = None,
                         review_key: str | None = None,
                         archive_key: str | None = None,
                         runner_invocation: dict | None = None,
                         expected_public_input: dict | None = None) -> dict:
    """Build the hash-bound, oracle-free handoff for one AI review."""
    project, run_p = Path(project).resolve(), Path(run_p).resolve()
    if runner_invocation is not None:
        diagnostic = _stored_runner_diagnostics(runner_invocation)
        if diagnostic and diagnostic.get("reason"):
            raise ValueError(diagnostic["reason"])
        material = _runner_material_snapshot(project)
        if (material != runner_invocation["material_after"]
                or runner_rc != runner_invocation["rc"]
                or _sha256_text(str(got.get("completion") or "")) != material["output_rtl_sha256"]):
            raise ValueError("RUNNER_MATERIAL_UNBOUND: task freeze differs from invocation/collected output")
    prompt = project / "input" / "phase1_prompt.md"
    paths = _rtl_files(project)
    completion = str(got.get("completion") or "")
    if not prompt.is_file() or not paths or not got.get("ok") or not completion:
        raise ValueError("cannot request AI review without prompt + gated RTL")
    safe = _safe_problem_id(problem_id)
    if runner_invocation is not None:
        # The response includes transient diagnostics. Archive each actual
        # generation separately; never rewrite a content-addressed old payload.
        generation = _safe_problem_id(runner_invocation["invocation_id"])
        archive_key = f"{archive_key or candidate_origin}-inv-{generation}"
    candidate = _archive_candidate(
        problem_id, project, got, run_p, candidate_origin, archive_key=archive_key)
    if runner_invocation is not None:
        diagnostic = _stored_runner_diagnostics(runner_invocation)
        if diagnostic and diagnostic.get("reason"):
            raise ValueError(diagnostic["reason"])
        _runner_frozen_material(runner_invocation, candidate)
    if candidate_origin == "PROGRAM":
        program_candidate = candidate
    import emit_attestation as emit_attestation          # noqa: PLC0415
    phase1_provenance = emit_attestation.phase1_provenance(project)
    challenges = verification_challenges or []
    review_key = review_key or (f"{_safe_problem_id(candidate_origin).lower()}-"
                               f"r{len(challenges)}-{candidate['rtl_sha256']}")
    if runner_invocation is not None:
        review_key = f"{review_key}-inv-{generation}"
    challenge_dir = (run_p / "ai_verification_challenges" / safe /
                     review_key)
    challenge_file = str((challenge_dir / "challenge_tb.sv").resolve())
    prompt_sha = _sha256_text(prompt.read_text(errors="replace"))
    import benchmark_io_adapter as bio                  # noqa: PLC0415
    public_input = bio.public_original_input(
        project, problem_id, prompt_sha, expected=expected_public_input)
    public_paths = [str(project / "input" / "public_original" / "files" /
                        row["relative_path"]) for row in public_input["files"]]
    program_review_obligations = _program_review_obligation_contract(
        prompt.read_text(errors="replace"), candidate, project)
    evidence_item_shape = {
        "excerpt": ("<exact prompt excerpt; at least 8 characters and a "
                    "whitespace-normalized substring of prompt_path>"),
        "supports": "<the claim it supports; at least 12 characters>",
    }
    phase3 = ((program_phases or {}).get("phase3_verifying") or {})
    ran = phase3.get("ran") if isinstance(phase3.get("ran"), dict) else {}
    not_attempted = (phase3.get("not_attempted")
                     if isinstance(phase3.get("not_attempted"), dict) else {})
    functional_evidence = ran.get("step4_functional_evidence")
    functional_source = "phase3_verifying.ran.step4_functional_evidence"
    if functional_evidence is None:
        functional_evidence = not_attempted.get("step4_functional_evidence")
        functional_source = (
            "phase3_verifying.not_attempted.step4_functional_evidence")
    if functional_evidence is None:
        functional_evidence = "NOT_RECORDED"
        functional_source = "no step4_functional_evidence record"
    confirmation_required = functional_evidence != "PASS"

    return {
        "schema": _REVIEW_TASK_SCHEMA,
        "id": str(problem_id),
        "project": str(project),
        "candidate_origin": candidate_origin,
        "verification_execution": _challenge_execution_declaration(run_p),
        "public_original_input": public_input,
        "public_original_input_paths": public_paths,
        "candidate_snapshot": candidate,
        "program_candidate_snapshot": program_candidate,
        "repair_parent_candidate_snapshot": repair_parent_candidate,
        "verification_challenges": challenges,
        "repair_provenance": repair_provenance,
        **({"repair_input_candidate_snapshot": repair_input_candidate}
           if repair_input_candidate is not None else {}),
        "prompt_path": str(prompt),
        "rtl_paths": candidate["rtl_paths"],
        "working_rtl_paths": [str(p.resolve()) for p in paths],
        "prompt_sha256": prompt_sha,
        "phase1_provenance": phase1_provenance,
        "rtl_sha256": candidate["rtl_sha256"],
        "program_routing": {
            "nature": routing.get("nature"),
            "route": routing.get("route"),
            "source": routing.get("source"),
            "needs_ai_parse": routing.get("needs_ai_parse"),
        },
        "program_verification": {
            "actor": "vibe_ic_one_shot_runner",
            "rtl_gen": got.get("rtl_gen"),
            "runner_rc": int(runner_rc),
            **({"runner_invocation": runner_invocation} if runner_invocation is not None else {}),
            **({"runner_argv": list(runner_invocation["argv"])} if runner_invocation is not None else {}),
            "functional_evidence": functional_evidence,
            "functional_evidence_source": functional_source,
            "functional_confirmation_required": confirmation_required,
        },
        "program_review_obligations": program_review_obligations,
        "review_path": str((run_p / "ai_reviews" / safe /
                            f"{review_key}.json").resolve()),
        "challenge_path": challenge_file,
        "response_path": str((run_p / "responses" / f"{safe}.json").resolve()),
        "review_requirements": {
            "schema": _AI_REVIEW_SCHEMA,
            "required_envelope": {
                "_contract": (
                    "the review JSON written to review_path is REJECTED "
                    "unless it carries every field below with this exact "
                    "shape; concrete values are the required values (copy "
                    "them verbatim), <angle-bracket> values are authored by "
                    "the reviewer under the stated rule"),
                "schema": _AI_REVIEW_SCHEMA,
                **({"source_sha256": public_input["source_sha256"]}
                   if public_input.get("status") == "PRESENT" else {}),
                "id": str(problem_id),
                "prompt_sha256": prompt_sha,
                "rtl_sha256": candidate["rtl_sha256"],
                "reviewer": {
                    "kind": "AI",
                    "model": ("<the reviewing AI model name; empty, "
                              "unknown, unspecified and n/a are rejected>"),
                },
                "blind": {"oracle_accessed": False},
                "routing": {
                    "verdict": "<AGREE or OVERRIDE_PROGRAM>",
                    "ai_nature": ("<the AI-judged nature; AGREE requires it "
                                  "to equal program_routing.nature>"),
                },
                "semantic_review": {
                    "verdict": "<PASS, FAIL, or NEEDS_CLARIFICATION>",
                    "findings": ["<list; must be non-empty when the verdict "
                                 "is FAIL>"],
                    "rationale": ("<the review basis; at least 16 "
                                  "characters>"),
                    "prompt_evidence": [dict(evidence_item_shape)],
                },
                "gate_escalation_dispositions": {
                    "_required_when": (
                        "semantic_review.verdict is PASS and "
                        "program_review_obligations contains an obligation "
                        "of kind gate_escalation; omit otherwise"),
                    "_shape": ("a LIST of the item below, one per such "
                               "obligation"),
                    "_item": {
                        "obligation_id": "<the obligation's id, verbatim>",
                        "disposition": (
                            f"<{_ESCALATION_DISCRIMINATED} or "
                            f"{_ESCALATION_SANCTIONED}>"),
                        "how": (f"<required for {_ESCALATION_DISCRIMINATED}: "
                                "what your active test drives that would "
                                "DIFFER if the gate's finding is real; at "
                                "least 24 characters>"),
                        "prompt_evidence": [dict(evidence_item_shape)],
                    },
                    "_effect": (
                        "a PROGRAM gate named a suspected defect in the "
                        "exact candidate you are reviewing, and nothing "
                        "repaired it. Both dispositions are always "
                        "available: either your test discriminates the "
                        "finding, or the prompt asks for that shape and "
                        "you quote the line. An undisposed escalation "
                        "blocks a semantic PASS."),
                },
                "spec_clarification": {
                    "_required_when": "semantic_review.verdict is NEEDS_CLARIFICATION; omit otherwise",
                    "schema": "vibeic.spec_clarification.v1",
                    "source_sha256": [prompt_sha],
                    "requests": [{
                        "source_sha256": prompt_sha,
                        "excerpt": "<verbatim prompt obligation needing a missing definition>",
                        "missing_information": "<concrete missing definition; at least 16 characters>",
                        "question": "<specific question for the spec owner; at least 16 characters>",
                    }],
                    "_effect": (
                        "hold acceptance and scoring; no RTL repair is authorized. "
                        "Do not infer a predicate from a standard or hidden oracle. "
                        "A clarified prompt requires a fresh canonical run/review; "
                        "never rewrite the frozen prompt or waive inherited tests."),
                },
                "override": {
                    "_required_when": "routing.verdict is OVERRIDE_PROGRAM",
                    "prompt_evidence": [dict(evidence_item_shape)],
                    "explanation": ("<at least 160 characters when no "
                                    "prompt_evidence item verifies against "
                                    "the prompt>"),
                    "program_limitation": ("<the deterministic limitation "
                                           "being overridden; at least 16 "
                                           "characters>"),
                },
                "verification_test": {
                    "_required_when": (
                        "semantic_review.verdict is FAIL, OR semantic_review."
                        "verdict is PASS while program_verification."
                        "functional_confirmation_required is true; write the "
                        "test file to the task challenge_path"),
                    "schema": _CHALLENGE_SCHEMA,
                    "path": challenge_file,
                    "sha256": "<sha256 of the exact challenge file text>",
                    "top_module": "vibeic_ai_challenge_tb",
                    "rationale": ("<what the test proves and how; at least "
                                  "80 characters>"),
                    "expected_behavior": ("<the checked behavior; at least "
                                          "24 characters>"),
                    "prompt_evidence": [dict(evidence_item_shape)],
                    "interface_proof": {
                        "_optional_when": (
                            "the joint compile fails ONLY at the test's "
                            "named-port instantiation because the candidate "
                            "omits a port the public input explicitly "
                            "requires. Without this the diagnostic is "
                            "indistinguishable from a test that invented a "
                            "port name, and both stay INVALID. Every field is "
                            "validated: the excerpt must be verbatim public "
                            "input that NAMES the port and states its "
                            "DIRECTION, the hashes must be the reviewed ones, "
                            "the candidate must declare the module and NOT "
                            "the port, the test must connect it, and the "
                            "compiler must itself report that port is not a "
                            "port. A proof that fails any of these REJECTS "
                            "the review; it never falls back to INVALID. The "
                            "result stays an interface defect: it authorizes "
                            "repair, never a runtime FAIL or a PASS"),
                        "schema": _INTERFACE_PROOF_SCHEMA,
                        "module": "<module the public input names>",
                        "port": "<required port identifier>",
                        "direction": "<input|output|inout>",
                        "width": "<positive integer bit width>",
                        "excerpt": ("<exact public-input excerpt naming the "
                                    "port and its direction>"),
                        "supports": ("<the interface requirement it "
                                     "establishes; at least 12 characters>"),
                        "prompt_sha256": prompt_sha,
                        **({"public_source_sha256": public_input["source_sha256"]}
                           if public_input.get("status") == "PRESENT" else {}),
                        "candidate_rtl_sha256": candidate["rtl_sha256"],
                        "challenge_sha256": ("<sha256 of the exact challenge "
                                             "file text>"),
                    },
                },
                "challenge_supersessions": [{
                    "_optional_when": (
                        "a fresh semantic PASS proves that an inherited "
                        "challenge contradicts the prompt; verification_test "
                        "must be a replacement test that PASSES this candidate. "
                        "The named challenge must ALSO validly FAIL, or be "
                        "structurally INVALID on, THIS candidate: a challenge "
                        "that still PASSES is not blocking acceptance, so it "
                        "must not be named here, and naming one rejects the "
                        "whole review. Name each inherited challenge at most "
                        "once, and the replacement must be a DIFFERENT test "
                        "from the one it replaces"),
                    "schema": _CHALLENGE_SUPERSESSION_SCHEMA,
                    "challenge_sha256": "<exact inherited challenge sha256>",
                    "rationale": (
                        "<why the old assertion is defective; at least 80 "
                        "characters>"),
                    "prompt_evidence": [dict(evidence_item_shape)],
                }],
            },
            "blind_inputs_only": [
                "prompt_path",
                "rtl_paths",
                "public_original_input_paths (verified public_original_input only)",
                ("verification_challenges only when correcting a defective "
                 "inherited test; never scorer/golden/oracle bytes"),
            ],
            "routing_verdicts": ["AGREE", "OVERRIDE_PROGRAM"],
            "override_rule": (
                "OVERRIDE_PROGRAM is allowed when the AI supplies prompt-bound "
                "evidence or a detailed interpretation and names the program "
                "limitation; AI semantic judgment is authoritative"),
            "semantic_verdicts": ["PASS", "FAIL"],
            "semantic_fail_action": (
                "write a self-contained prompt-derived executable test to "
                "challenge_path and describe it in verification_test; the "
                "reviewed PROGRAM candidate must fail that test before repair "
                "is authorized. Corrected RTL must pass the SAME immutable "
                "test, return through PROGRAM gates, then receive a fresh "
                "hash-bound AI review"),
            "semantic_pass_action": (
                "When PROGRAM has no PASS functional evidence, a semantic PASS "
                "must include a self-contained prompt-derived executable test "
                "at challenge_path. The frozen candidate must PASS that test, "
                "and the current plus inherited active tests must cover every "
                "block-eligible item in program_review_obligations; one passing "
                "example is not whole-spec confirmation. An unrunnable test is "
                "NOT_MEASURED and a failing or coverage-incomplete test cannot "
                "authorize acceptance."),
            "semantic_pass_verification_test": {
                "required": confirmation_required,
                "required_result_on_reviewed_candidate": "PASS",
                "required_program_coverage": "ALL_BLOCKING_OBLIGATIONS",
                "program_review_obligations_sha256": (
                    program_review_obligations["sha256"]),
                "reason": ("PROGRAM step4_functional_evidence is "
                           f"{functional_evidence!r}"),
                "blind_source": "prompt_path only",
            },
            "semantic_fail_verification_test": {
                "schema": _CHALLENGE_SCHEMA,
                "path": challenge_file,
                "top_module": "vibeic_ai_challenge_tb",
                "required_result_on_reviewed_candidate": "FAIL",
                "required_result_on_repair": "PASS",
                "pass_marker": "VIBEIC_AI_CHALLENGE=PASS",
                "fail_marker": "VIBEIC_AI_CHALLENGE=FAIL",
                "marker_form": (
                    "both markers are checked against the challenge SOURCE "
                    "TEXT: each must appear in the file as a LITERAL string. "
                    "A format string such as $display(\"VIBEIC_AI_CHALLENGE"
                    "=%s\", ok ? \"PASS\" : \"FAIL\") prints the marker "
                    "correctly at run time and still contains neither "
                    "literal, so it is rejected; write one $display per "
                    "marker with the marker spelled out"),
                "constraints": [
                    "derive assertions only from prompt_path",
                    "self-contained: no include/readmem/file/system/DPI access",
                    "compile with the candidate RTL using iverilog -g2012",
                    "exit zero and print the pass marker only when assertions pass",
                ],
            },
            "reviewer_kind": "AI",
            "reviewer_model_required": True,
            "oracle_accessed": False,
        },
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not Path(path).is_file():
        return []
    rows = []
    for lineno, raw in enumerate(Path(path).read_text(errors="replace").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = _strict_json_loads(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{lineno}: row is not an object")
        rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                   for r in rows)
    _atomic_write_text(path, text)


def _current_task_material(task: dict) -> tuple[str | None, str | None,
                                                 list[str], list[str]]:
    """Current prompt/frozen-RTL hashes plus frozen/stated RTL path sets."""
    prompt = Path(str(task.get("prompt_path") or ""))
    stated = sorted(str(Path(p).resolve()) for p in task.get("rtl_paths") or [])
    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        candidate = {}
    current_paths = sorted(
        str(Path(p).resolve()) for p in candidate.get("rtl_paths") or [])
    prompt_hash = (_sha256_text(prompt.read_text(errors="replace"))
                   if prompt.is_file() else None)
    try:
        rtl_hash = _sha256_text(_candidate_text([Path(p) for p in current_paths])) \
            if current_paths else None
    except OSError:
        rtl_hash = None
    return prompt_hash, rtl_hash, stated, current_paths


def _refresh_program_review_obligations(task: dict) -> bool:
    """Refresh only the deterministic contract of an unchanged review task.

    ``program_review_obligations`` is derived by Program from the prompt and
    frozen candidate. A Program upgrade may correct that derivation while a
    long benchmark run is awaiting AI review. The validator intentionally
    compares against the current derivation, so leaving the old value in the
    task creates an impossible state: the task is rejected, but ``--resume``
    previously had no way to replace the stale Program-owned field.

    Refresh is allowed only when every authority-bearing input is still bound
    to its original hash and the candidate snapshot is intact. The prior
    contract is retained in the task for audit. AI verdicts, prompt evidence,
    tests, and RTL are never changed here; newly added obligations therefore
    still require coverage and cannot be silently accepted.
    """
    if task.get("schema") != _REVIEW_TASK_SCHEMA:
        return False
    prompt_hash, rtl_hash, stated, current = _current_task_material(task)
    if (stated != current
            or prompt_hash != task.get("prompt_sha256")
            or rtl_hash != task.get("rtl_sha256")
            or _validate_candidate_snapshot(
                task.get("candidate_snapshot") or {},
                str(task.get("id")))):
        return False
    prompt_path = Path(str(task.get("prompt_path") or ""))
    try:
        prompt_text = prompt_path.read_text(errors="replace")
        expected = _program_review_obligation_contract(
            prompt_text, task.get("candidate_snapshot") or {},
            _task_project(task))
    except (ImportError, OSError, ValueError):
        return False
    prior = task.get("program_review_obligations")
    if prior == expected:
        return False
    refreshes = task.setdefault("program_review_obligation_refreshes", [])
    if not isinstance(refreshes, list):
        return False
    refreshes.append({
        "schema": "vibeic.benchmark.program_review_obligations_refresh.v1",
        "basis": "UNCHANGED_HASH_BOUND_PROMPT_AND_CANDIDATE",
        "prior_contract": prior,
        "replacement_sha256": expected.get("sha256"),
    })
    task["program_review_obligations"] = expected
    return True


def _repair_record_path(run_p: Path, task: dict) -> Path:
    """Stable handoff path for the AI that authors a proven repair."""
    safe = _safe_problem_id(str(task.get("id")))
    parent_hash = str(task.get("rtl_sha256") or "missing")
    return (Path(run_p).resolve() / "ai_repairs" / safe /
            f"repair-of-{parent_hash}.json")


def _validate_repair_record(path: Path, task: dict, repaired_hash: str,
                            challenge: dict) -> tuple[dict | None, list[str]]:
    """Bind an AI repair's author and rationale to parent/new/test hashes."""
    path = Path(path).resolve()
    reasons: list[str] = _public_input_reasons(task)
    try:
        raw = path.read_text(errors="replace")
        record = _strict_json_loads(raw)
    except (OSError, ValueError) as exc:
        return None, [f"AI repair record is absent or unreadable: {exc}"]
    if not isinstance(record, dict):
        return None, ["AI repair record is not a JSON object"]
    expected = {
        "schema": _AI_REPAIR_RECORD_SCHEMA,
        "id": str(task.get("id")),
        "prompt_sha256": task.get("prompt_sha256"),
        "parent_rtl_sha256": task.get("rtl_sha256"),
        "repaired_rtl_sha256": repaired_hash,
        "challenge_sha256": challenge.get("sha256"),
    }
    for key, value in expected.items():
        if record.get(key) != value:
            reasons.append(f"AI repair record {key} is stale or wrong")
    author = record.get("author") or {}
    if author.get("kind") != "AI":
        reasons.append("AI repair record author.kind must be AI")
    model = str(author.get("model") or "").strip()
    if not model or model.lower() in {"unknown", "unspecified", "n/a"}:
        reasons.append("AI repair record author.model must name the AI model")
    if record.get("oracle_accessed") is not False:
        reasons.append("AI repair record oracle_accessed must be false")
    if len(str(record.get("rationale") or "").strip()) < 40:
        reasons.append("AI repair record rationale must explain the repair")
    contract = record.get("repair_contract")
    public = task.get("public_original_input") or {}
    if public.get("status") != "PRESENT" or not public.get("source_sha256"):
        reasons.append("source-bounded repair requires immutable public original input")
    if not isinstance(contract, dict):
        reasons.append("AI repair record lacks repair_contract")
    else:
        if contract.get("schema") != "vibeic.source_bounded_completion.v1":
            reasons.append("repair_contract schema is invalid")
        bindings = {
            "prompt_sha256": task.get("prompt_sha256"),
            "source_sha256": public.get("source_sha256"),
            "parent_rtl_sha256": task.get("rtl_sha256"),
            "candidate_sha256": repaired_hash,
            "challenge_sha256": challenge.get("sha256"),
        }
        for key, value in bindings.items():
            if contract.get(key) != value:
                reasons.append(f"repair_contract {key} is stale or wrong")
        if not isinstance(contract.get("preservation"), dict):
            reasons.append("repair_contract lacks preservation declaration")
        if not isinstance(contract.get("elaboration_matrix"), dict):
            reasons.append("repair_contract lacks elaboration matrix")
        if contract.get("author") != record.get("author"):
            reasons.append("repair_contract author differs from repair record")
        if contract.get("oracle_accessed") is not False:
            reasons.append("repair_contract oracle_accessed must be false")
    if reasons:
        return None, reasons
    return {**record, "path": str(path), "sha256": _sha256_text(raw)}, []


def _refresh_final_repair_provenance(task: dict) -> tuple[dict | None,
                                                          list[str]]:
    """Rebind an AI signature to the exact candidate emitted by PROGRAM gates.

    A supplied AI repair re-enters at validation, but deterministic gate logic
    can still normalize that RTL before freezing the candidate.  The original
    pre-gate signature must not silently authorize different bytes. Let the AI
    explicitly re-sign the final hash at the same evidence path, even when a
    review already exists. This only refreshes provenance; the unchanged review
    must still pass its normal hash, snapshot, and challenge validation.
    Missing or invalid final provenance remains BLOCKING.
    """
    if task.get("candidate_origin") != "AI_REPAIR":
        return None, ["candidate is not an AI_REPAIR"]
    provenance = task.get("repair_provenance") or {}
    path_raw = str(provenance.get("path") or "").strip()
    path = Path(path_raw)
    parent = (task.get("repair_parent_candidate_snapshot")
              or task.get("program_candidate_snapshot") or {})
    parent_hash = str(parent.get("rtl_sha256") or "")
    challenges = task.get("verification_challenges") or []
    challenge_hash = str(provenance.get("challenge_sha256") or "")
    challenge = next(
        (item for item in challenges
         if str(item.get("sha256") or "") == challenge_hash), None)
    reasons: list[str] = []
    if not parent_hash:
        reasons.append("final AI repair task lacks its PROGRAM parent hash")
    if challenge is None:
        reasons.append("final AI repair task lacks its inherited challenge")
    if not path_raw:
        reasons.append("final AI repair task lacks its evidence path")
    if reasons:
        return None, reasons
    parent_task = {**task, "rtl_sha256": parent_hash}
    return _validate_repair_record(
        path, parent_task, _signed_candidate_hash(task), challenge)


def _validate_embedded_repair_provenance(task: dict) -> list[str]:
    """Ensure a final AI_REPAIR review still names its actual repair author."""
    if task.get("candidate_origin") != "AI_REPAIR":
        return []
    provenance = task.get("repair_provenance")
    if not isinstance(provenance, dict):
        return ["AI_REPAIR candidate lacks repair_provenance"]
    parent = (task.get("repair_parent_candidate_snapshot")
              or task.get("program_candidate_snapshot") or {})
    challenges = task.get("verification_challenges") or []
    expected_challenge_hashes = {str(c.get("sha256")) for c in challenges}
    reasons = []
    reasons.extend(
        "repair parent " + reason
        for reason in _validate_candidate_snapshot(
            parent, str(task.get("id"))))
    if provenance.get("schema") != _AI_REPAIR_RECORD_SCHEMA:
        reasons.append("repair_provenance schema is invalid")
    if str(provenance.get("id")) != str(task.get("id")):
        reasons.append("repair_provenance id does not match task")
    if provenance.get("prompt_sha256") != task.get("prompt_sha256"):
        reasons.append("repair_provenance prompt hash is stale")
    if provenance.get("parent_rtl_sha256") != parent.get("rtl_sha256"):
        reasons.append("repair_provenance parent hash is stale")
    if provenance.get("repaired_rtl_sha256") != _signed_candidate_hash(task):
        reasons.append("repair_provenance repaired hash is stale")
    if str(provenance.get("challenge_sha256")) not in expected_challenge_hashes:
        reasons.append("repair_provenance challenge hash is not inherited")
    author = provenance.get("author") or {}
    if author.get("kind") != "AI" or not str(author.get("model") or "").strip():
        reasons.append("repair_provenance must name the AI author model")
    if provenance.get("oracle_accessed") is not False:
        reasons.append("repair_provenance oracle_accessed must be false")
    path = Path(str(provenance.get("path") or ""))
    try:
        raw = path.read_text(errors="replace")
        disk = _strict_json_loads(raw)
    except (OSError, ValueError) as exc:
        reasons.append(f"repair_provenance file is absent or unreadable: {exc}")
    else:
        embedded = {k: v for k, v in provenance.items()
                    if k not in {"path", "sha256"}}
        if disk != embedded:
            reasons.append("repair_provenance differs from its evidence file")
        if _sha256_text(raw) != provenance.get("sha256"):
            reasons.append("repair_provenance file hash is stale")
    return reasons


_CHALLENGE_FORBIDDEN = re.compile(
    r"`\s*include|\$(?:readmem[hb]|fopen|fread|fscanf|sscanf|system)|"
    r"\b(?:DPI|VPI|PLI)\b",
    re.I,
)

#: `//` to end of line, and `/* ... */` including newlines. Applied before the
#: forbidden-construct scan so a COMMENT cannot decide the verdict.
_CHALLENGE_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


_TIMESCALE = re.compile(
    r"`timescale\s*(\d+)\s*([munpf]?s)\s*/\s*(\d+)\s*([munpf]?s)")


def _challenge_forbidden_hit(source: str):
    """The forbidden-construct scan, run on CODE rather than on raw text.

    MEASURED 2026-09-06, RTLLM clean-room run. Ten reviews were rejected with
    `verification test is not self-contained` while every one of the ten
    challenge files was clean. The reviewer had written the header comment the
    contract asks for --

        // Self-contained: no `include, no $readmem, no file/system/DPI access.

    -- and that COMMENT contains the literal tokens the pattern looks for, so a
    test was rejected for DECLARING its compliance. Stripping comments made all
    ten clean, and the pattern still catches the real constructs.

    A guard that a comment can flip is not a guard: editing prose must never
    change a verdict about code. Comments are removed first; string literals are
    deliberately NOT removed, because `$readmemh("f.hex", m)` is a real call and
    a path inside a string is exactly what makes it one.
    """
    return _CHALLENGE_FORBIDDEN.search(_CHALLENGE_COMMENT.sub(" ", source or ""))


def _verified_prompt_evidence(items, prompt_text: str) -> list[dict]:
    """Keep only exact normalized excerpts tied to a non-trivial claim."""
    verified = []
    if not isinstance(items, list):
        return verified
    normalized_prompt = re.sub(r"\s+", " ", prompt_text).strip()
    for item in items:
        if not isinstance(item, dict):
            continue
        if (not isinstance(item.get("excerpt"), str)
                or not isinstance(item.get("supports"), str)):
            continue
        excerpt = re.sub(r"\s+", " ", item.get("excerpt")).strip()
        supports = item.get("supports").strip()
        if (len(excerpt) >= 8 and excerpt in normalized_prompt
                and len(supports) >= 12):
            verified.append({"excerpt": excerpt, "supports": supports})
    return verified


#: Dispositions a reviewer may return for a routed gate escalation. Both are
#: always available, which is the point: this obligation can never become a
#: blocking condition a correct candidate is unable to clear.
_ESCALATION_DISCRIMINATED = "DISCRIMINATED"
_ESCALATION_SANCTIONED = "SANCTIONED_BY_PROMPT"


def _gate_escalation_obligations(task: dict) -> list:
    """The routed-escalation rows of this task's Program contract."""
    contract = task.get("program_review_obligations")
    if not isinstance(contract, dict):
        return []
    return [row for row in (contract.get("obligations") or [])
            if isinstance(row, dict) and row.get("kind") == "gate_escalation"]


def _gate_escalation_disposition_reasons(task: dict, review: dict,
                                         prompt_text: str) -> list:
    """A semantic PASS must dispose of every routed gate escalation.

    WHY THIS IS ENFORCED AND NOT MERELY ANNOUNCED. Putting the escalation into
    the task contract tells the reviewer it exists; nothing about that obliges
    the reviewer to look. An advisory that only reaches a second reader who may
    also ignore it has moved, not landed — and the run that motivated this had
    already demonstrated exactly that: the finding was recorded in writing, in
    the project, and a semantic PASS was issued anyway.

    WHY IT CANNOT BECOME AN UNCLEARABLE GATE — the property that decided the
    design. Coverage here is NOT measured by matching the gate's signal names
    against the challenge text. `wptr` and `rptr` are INTERNAL to the design
    under review, and a challenge that correctly drives only the module's ports
    would never name them, so a token match would refuse good reviews forever.
    What is required instead is a DISPOSITION, and both dispositions are
    reachable from any candidate:

      DISCRIMINATED         the active test reaches the behaviour that would
                            DIFFER if the finding is real — say what it drives.
      SANCTIONED_BY_PROMPT  the prompt asks for exactly the shape the gate
                            named — quote the line, verified against the frozen
                            prompt by the same `_verified_prompt_evidence` that
                            checks every other prompt claim in a review.

    A reviewer who genuinely looked can always answer one of the two. A
    reviewer who did not, cannot.
    """
    obligations = _gate_escalation_obligations(task)
    if not obligations:
        return []
    raw = review.get("gate_escalation_dispositions")
    by_id = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) \
                    and isinstance(item.get("obligation_id"), str):
                by_id[item["obligation_id"]] = item
    reasons = []
    for row in obligations:
        oid = str(row.get("id"))
        item = by_id.get(oid)
        if item is None:
            reasons.append(
                "semantic PASS does not dispose of PROGRAM gate escalation "
                f"{oid}: add a gate_escalation_dispositions entry stating "
                f"{_ESCALATION_DISCRIMINATED} or {_ESCALATION_SANCTIONED}")
            continue
        disposition = str(item.get("disposition") or "")
        if disposition == _ESCALATION_DISCRIMINATED:
            how = str(item.get("how") or "").strip()
            if len(how) < 24:
                reasons.append(
                    f"gate escalation {oid} is claimed "
                    f"{_ESCALATION_DISCRIMINATED} without saying what the test "
                    "drives that would differ if the finding is real "
                    "(how: at least 24 characters)")
        elif disposition == _ESCALATION_SANCTIONED:
            if not _verified_prompt_evidence(item.get("prompt_evidence"),
                                             prompt_text):
                reasons.append(
                    f"gate escalation {oid} is claimed "
                    f"{_ESCALATION_SANCTIONED} without a prompt excerpt that "
                    "verifies against the frozen prompt")
        else:
            reasons.append(
                f"gate escalation {oid} carries an unknown disposition "
                f"{disposition!r}; expected {_ESCALATION_DISCRIMINATED} or "
                f"{_ESCALATION_SANCTIONED}")
    return reasons

_INTERFACE_PROOF_SCHEMA = "vibeic.benchmark.interface_proof.v1"
_DIRECTIONS = ("input", "output", "inout")
def _declared_ports(source: str, module: str) -> set[str] | None:
    """Identifiers in `module <name> ( ... );`, or None if it is not declared.

    A port is a port because it appears in the module HEADER -- true for both
    the ANSI form (`module m(input wire a, ...)`) and the non-ANSI form
    (`module m(a, b); input a;`), which is what makes one scan answer the
    question for both. Comments and strings are stripped first, for the same
    reason `_challenge_forbidden_hit` strips them: text that the compiler does
    not read must not decide a verdict about code.

    None is NOT the empty set. "This file does not declare that module" and
    "that module declares no ports" are different answers, and the caller
    refuses on the first rather than treating it as an omission it can blame
    on the candidate.
    """
    import _hdl_code_text                                 # noqa: PLC0415
    scanned = _hdl_code_text.strip_hdl_comments_and_strings(source or "")
    match = re.search(rf"\bmodule\s+{re.escape(module)}\b", scanned)
    if match is None:
        return None
    rest = scanned[match.end():]
    stop = rest.find(";")
    header = rest[:stop] if stop != -1 else rest
    if "(" not in header:
        return set()
    body = header[header.index("(") + 1:]
    if body.rstrip().endswith(")"):
        body = body.rstrip()[:-1]
    return set(re.findall(r"[A-Za-z_]\w*", body)) - {
        *_DIRECTIONS, "wire", "reg", "logic", "signed", "unsigned", "parameter",
        "localparam", "bit", "integer", "real", "genvar", "tri", "wand", "wor"}


def _interface_proof_internal_reasons(proof) -> list:
    """The proof's own bindings that hold WITHOUT reading the public input.

    ONE implementation, called from both halves. The freeze-time validator has
    the prompt and can ask "is this excerpt really the public input"; the
    compile-time half does not and cannot. But three of the freeze's four
    excerpt rules never needed the prompt at all -- whether the excerpt NAMES
    the port, whether it STATES the claimed direction, and whether it states a
    width the proof claims to be wider than 1 are properties of the excerpt
    text and the claim, and they are exactly what makes a claim self-consistent.

    Re-asking them at the compile is the difference between reporting a
    direction the public input supports and reporting whatever the proof said.
    Factored rather than copied so a rule cannot be tightened in one half and
    left loose in the other (vibe-ic#2210).
    """
    reasons = []
    port = str(proof.get("port") or "")
    direction = str(proof.get("direction") or "").lower()
    width = proof.get("width")
    excerpt = " ".join(str(proof.get("excerpt") or "").split())
    if not re.fullmatch(r"[A-Za-z_]\w*", port):
        reasons.append(f"interface_proof.port is not an identifier: {port!r}")
    if direction not in _DIRECTIONS:
        reasons.append("interface_proof.direction must be one of "
                       + ", ".join(_DIRECTIONS))
    if not isinstance(width, int) or isinstance(width, bool) or width < 1:
        reasons.append("interface_proof.width must be a positive integer")
    if len(excerpt) < 8:
        reasons.append("interface_proof.excerpt is too short to be evidence")
        return reasons
    if port and not re.search(rf"\b{re.escape(port)}\b", excerpt):
        reasons.append("interface_proof.excerpt does not name the port it "
                       "claims the public input requires")
    if direction in _DIRECTIONS and direction not in excerpt.lower():
        reasons.append("interface_proof.excerpt states no direction for the "
                       "port, so the requirement is ambiguous")
    # A width the excerpt never states is a number the proof invented. Width 1
    # is exempt because a bare `inout wire io_line` states it by saying nothing,
    # which is how the public input in vibe-ic#2210 expresses it.
    if (isinstance(width, int) and not isinstance(width, bool) and width > 1
            and not re.search(rf"\b{width}\b", excerpt)):
        reasons.append(f"interface_proof.width {width} is not stated by the "
                       f"excerpt that supports the port")
    return reasons


def _interface_proof_from_review(raw, task: dict, prompt_text: str,
                                 challenge_source: str,
                                 ) -> tuple[dict | None, list[str]]:
    """Validate a typed, prompt-bound proof that a REQUIRED port was omitted.

    THE PROBLEM THIS EXISTS FOR (#2210). A candidate that omits a required
    public port and a test that invents a port name produce the SAME compiler
    diagnostic, at the SAME location -- the test's named-port instantiation --
    so `_joint_compile_attribution`, which reads WHICH FILE the errors cite,
    cannot separate them and both become INVALID. MEASURED on the pinned image
    (iverilog 14.0 s20260301-462-ga5d8d1781), synthetic fixtures, both
    standalone compiles clean:

        candidate omits required `io_line`   joint rc 2   INVALID
        conforming candidate, test typo      joint rc 2   INVALID
        conforming candidate, correct test   joint rc 0   PASS

    Compiler source location is the wrong instrument for the question, and no
    stronger one can be built from the compile alone: which interface was
    REQUIRED is a fact about the public input, which the joint compile never
    reads. So the semantic authority supplies the claim and the PROGRAM
    validates every binding it rests on -- the same shape `_validate_ai_review`
    already uses for override authority: authority is not an unexplained token.

    EVERY BINDING IS CHECKED, AND ANY FAILURE LEAVES THE RESULT INVALID:

      * the excerpt is a whitespace-normalized VERBATIM substring of the public
        input, so a port name the input never contains cannot be proven -- this
        is what keeps the invented-port control INVALID;
      * the excerpt must NAME the port and state a DIRECTION word, so a passing
        mention ("do not add io_line") is not an interface requirement and an
        ambiguous one is refused rather than guessed;
      * the prompt hash, and the public-source hash when a public manifest is
        PRESENT, must still be the ones the task was written against;
      * the candidate and challenge hashes must be the reviewed ones;
      * the candidate must DECLARE the module and NOT declare the port -- if it
        declares the port there is no omission to attribute, and if it declares
        no such module this is a wrong-top binding, which stays invalid;
      * the challenge must actually CONNECT that port by name.

    The compiler evidence itself is checked later, at the compile, against the
    real diagnostics -- a proof cannot assert what the compiler said.
    """
    reasons: list[str] = []
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["verification_test.interface_proof must be an object"]
    if raw.get("schema") != _INTERFACE_PROOF_SCHEMA:
        reasons.append(f"interface_proof.schema must be "
                       f"{_INTERFACE_PROOF_SCHEMA!r}")
    module = str(raw.get("module") or "")
    port = str(raw.get("port") or "")
    direction = str(raw.get("direction") or "").lower()
    if not re.fullmatch(r"[A-Za-z_]\w*", module):
        reasons.append("interface_proof.module must be an identifier")
    if not re.fullmatch(r"[A-Za-z_]\w*", port):
        reasons.append("interface_proof.port must be an identifier")
    if direction not in _DIRECTIONS:
        reasons.append("interface_proof.direction must be one of "
                       + ", ".join(_DIRECTIONS))
    width = raw.get("width")
    if not isinstance(width, int) or isinstance(width, bool) or width < 1:
        reasons.append("interface_proof.width must be a positive integer")
    if raw.get("prompt_sha256") != task.get("prompt_sha256"):
        reasons.append("interface_proof.prompt_sha256 is not the reviewed prompt")
    if raw.get("candidate_rtl_sha256") != task.get("rtl_sha256"):
        reasons.append("interface_proof.candidate_rtl_sha256 is not the "
                       "reviewed candidate")
    if raw.get("challenge_sha256") != _sha256_text(challenge_source):
        reasons.append("interface_proof.challenge_sha256 is not this challenge")
    public = task.get("public_original_input")
    if isinstance(public, dict) and public.get("status") == "PRESENT":
        if raw.get("public_source_sha256") != public.get("source_sha256"):
            reasons.append("interface_proof.public_source_sha256 is not the "
                           "staged public source")
    verified = _verified_prompt_evidence(
        [{"excerpt": raw.get("excerpt"),
          "supports": raw.get("supports") or ""}], prompt_text)
    if not verified:
        reasons.append("interface_proof.excerpt must be an exact prompt "
                       "excerpt of at least 8 characters with a stated claim "
                       "of at least 12")
    else:
        # The prompt-free rules come from the SHARED helper, so the compile-time
        # half cannot end up asking a weaker question than this one does.
        reasons.extend(_interface_proof_internal_reasons(raw))
    candidate_text = "\n".join(
        Path(p).read_text(errors="replace")
        for p in (task.get("rtl_paths") or []) if Path(p).is_file())
    ports = _declared_ports(candidate_text, module) if module else None
    if ports is None:
        reasons.append(f"the candidate declares no module {module!r}, so this "
                       "is a wrong-top binding, not a port omission")
    elif port and port in ports:
        reasons.append(f"the candidate already declares port {port!r}; there "
                       "is no omission to attribute")
    if port and not re.search(rf"\.\s*{re.escape(port)}\s*\(",
                              challenge_source or ""):
        reasons.append("the challenge does not connect the port this proof is "
                       "about")
    if reasons:
        return None, reasons
    return {
        "schema": _INTERFACE_PROOF_SCHEMA,
        "module": module,
        "port": port,
        "direction": direction,
        "width": width,
        "excerpt": verified[0]["excerpt"],
        "supports": verified[0]["supports"],
        "prompt_sha256": task.get("prompt_sha256"),
        "public_source_sha256": raw.get("public_source_sha256"),
        "candidate_rtl_sha256": task.get("rtl_sha256"),
        "challenge_sha256": _sha256_text(challenge_source),
    }, []


def _challenge_from_review(task: dict, review: dict,
                           prompt_text: str, *,
                           required_for: str = "semantic FAIL"
                           ) -> tuple[dict | None, list[str]]:
    """Validate and freeze an AI-authored prompt-only executable challenge."""
    raw = review.get("verification_test")
    reasons: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"{required_for} requires verification_test"]
    if raw.get("schema") != _CHALLENGE_SCHEMA:
        reasons.append(f"verification_test.schema must be {_CHALLENGE_SCHEMA!r}")
    expected_path = Path(str(task.get("challenge_path") or "")).resolve()
    actual_path = Path(str(raw.get("path") or "")).resolve()
    if actual_path != expected_path:
        reasons.append("verification_test.path must equal the task challenge_path")
    if str(raw.get("top_module") or "") != "vibeic_ai_challenge_tb":
        reasons.append("verification_test.top_module must be vibeic_ai_challenge_tb")
    if not actual_path.is_file():
        reasons.append("verification test file is absent")
        source = ""
    else:
        if actual_path.is_symlink():
            reasons.append("verification test must be a real file, not a symlink")
        source = actual_path.read_text(errors="replace")
    source_hash = _sha256_text(source)
    if raw.get("sha256") != source_hash:
        reasons.append("verification_test.sha256 is stale or wrong")
    if _challenge_forbidden_hit(source):
        reasons.append("verification test is not self-contained")
    if "module vibeic_ai_challenge_tb" not in source:
        reasons.append("verification test must define vibeic_ai_challenge_tb")
    # These are SOURCE-TEXT checks, and the reason has to say so. A challenge
    # written as `$display("VIBEIC_AI_CHALLENGE=%s", bad ? "FAIL" : "PASS")`
    # prints the marker perfectly at run time and is still rejected here,
    # because neither literal appears in the file. Telling its author the test
    # "must print" a marker it demonstrably does print sends them to debug the
    # wrong thing; naming the literal-vs-format-string distinction is the whole
    # remedy.
    _MARKER_FIX = (" as a LITERAL in the source (a $display format string such "
                   "as \"VIBEIC_AI_CHALLENGE=%s\" prints correctly at run time "
                   "but contains neither literal; use one $display per marker)")
    if "VIBEIC_AI_CHALLENGE=PASS" not in source:
        reasons.append("verification test must contain VIBEIC_AI_CHALLENGE=PASS"
                       + _MARKER_FIX)
    if "VIBEIC_AI_CHALLENGE=FAIL" not in source:
        reasons.append("verification test must contain VIBEIC_AI_CHALLENGE=FAIL"
                       + _MARKER_FIX)
    rationale = str(raw.get("rationale") or "").strip()
    expected_behavior = str(raw.get("expected_behavior") or "").strip()
    if len(rationale) < 80:
        reasons.append("verification_test.rationale must explain the test in "
                       "at least 80 characters")
    if len(expected_behavior) < 24:
        reasons.append("verification_test.expected_behavior must state the "
                       "checked behavior")
    verified_evidence = _verified_prompt_evidence(
        raw.get("prompt_evidence") or [], prompt_text)
    if not verified_evidence:
        reasons.append("verification_test needs prompt-bound evidence")
    # OPTIONAL, and absent is the default. A challenge without one behaves
    # exactly as before; supplying an invalid one is a refusal, not a
    # downgrade to the old behaviour, so a malformed proof can never buy a
    # weaker result than no proof at all.
    interface_proof, proof_reasons = _interface_proof_from_review(
        raw.get("interface_proof"), task, prompt_text, source)
    reasons.extend(proof_reasons)
    if reasons:
        return None, reasons
    challenge = {
        "schema": _CHALLENGE_SCHEMA,
        "id": str(task.get("id")),
        "path": str(actual_path),
        "sha256": source_hash,
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_sha256": task.get("prompt_sha256"),
        "reviewed_rtl_sha256": task.get("rtl_sha256"),
        "prompt_evidence": verified_evidence,
        "expected_behavior": expected_behavior,
        "rationale": rationale,
    }
    if interface_proof is not None:
        challenge["interface_proof"] = interface_proof
    return challenge, []


def _challenge_supersessions_from_review(
        task: dict, review: dict, prompt_text: str,
        replacement: dict | None) -> tuple[list[dict], list[str]]:
    """Validate explicit corrections to defective inherited challenges.

    BLOCKING: an inherited proof remains immutable and active unless a fresh
    blind AI semantic PASS names its exact hash, cites the prompt, and supplies
    a different executable replacement test that passes the current candidate.
    The old proof stays in the audit result as SUPERSEDED; malformed, missing,
    passing, or unrunnable targets never disappear silently.
    """
    raw = review.get("challenge_supersessions")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["challenge_supersessions must be a list"]
    inherited = {
        str(item.get("sha256") or ""): item
        for item in task.get("verification_challenges") or []
        if isinstance(item, dict)
    }
    reasons: list[str] = []
    records: list[dict] = []
    seen: set[str] = set()
    replacement_hash = str((replacement or {}).get("sha256") or "")
    for index, item in enumerate(raw):
        prefix = f"challenge_supersessions[{index}]"
        if not isinstance(item, dict):
            reasons.append(f"{prefix} must be an object")
            continue
        if item.get("schema") != _CHALLENGE_SUPERSESSION_SCHEMA:
            reasons.append(
                f"{prefix}.schema must be {_CHALLENGE_SUPERSESSION_SCHEMA!r}")
        target = str(item.get("challenge_sha256") or "")
        if target not in inherited:
            reasons.append(f"{prefix} must name an inherited challenge sha256")
        if target in seen:
            reasons.append(f"{prefix} repeats a challenge sha256")
        seen.add(target)
        rationale = str(item.get("rationale") or "").strip()
        if len(rationale) < 80:
            reasons.append(f"{prefix}.rationale must be at least 80 characters")
        evidence = _verified_prompt_evidence(
            item.get("prompt_evidence") or [], prompt_text)
        if not evidence:
            reasons.append(f"{prefix} needs prompt-bound evidence")
        if not replacement_hash:
            reasons.append(f"{prefix} needs an executable replacement test")
        elif replacement_hash == target:
            reasons.append(f"{prefix} replacement test must differ from target")
        if (target in inherited and target not in {
                r.get("challenge_sha256") for r in records}
                and len(rationale) >= 80 and evidence and replacement_hash
                and replacement_hash != target):
            records.append({
                "schema": _CHALLENGE_SUPERSESSION_SCHEMA,
                "challenge_sha256": target,
                "replacement_challenge_sha256": replacement_hash,
                "rationale": rationale,
                "prompt_evidence": evidence,
            })
    return records, reasons


def _joint_compile_attribution(errors: str, rtl_paths: list[str],
                               test_path: str) -> tuple[bool, bool]:
    """Which side of a joint compile do the error lines cite?

    iverilog reports diagnostics as ``<path>:<line>: ...`` using the paths
    exactly as given on the command line, so ``path + ":"`` is the citation
    token. A line can cite either side; unclassifiable lines cite neither.
    """
    cites_candidate = False
    cites_challenge = False
    for line in errors.splitlines():
        if any(p and (p + ":") in line for p in rtl_paths):
            cites_candidate = True
        if test_path and (test_path + ":") in line:
            cites_challenge = True
    return cites_candidate, cites_challenge


def _declared_timescale(source: str) -> str | None:
    """The `timescale a source DECLARES, normalized, or None.

    Read from the source text, never guessed. Comments are stripped first, for
    the same reason `_challenge_forbidden_hit` strips them: a directive that is
    commented out is prose, and prose must not decide a verdict about code.
    The FIRST declaration is the one in force at the top of the file, which is
    what "the declared unit" means for the modules that follow it.
    """
    match = _TIMESCALE.search(_CHALLENGE_COMMENT.sub(" ", source or ""))
    if match is None:
        return None
    return f"{match.group(1)}{match.group(2)}/{match.group(3)}{match.group(4)}"


def _timescale_disagreement(rtl_paths: list[str], declared: str | None) -> str | None:
    """A candidate/challenge pair whose declared timescales DISAGREE.

    With one declared unit the prelude makes every module share it. With two
    different ones there is no single answer to impose, and which one wins
    would go back to depending on compile order -- so this is refused by name
    rather than decided silently.
    """
    for path in rtl_paths:
        try:
            found = _declared_timescale(Path(path).read_text(errors="replace"))
        except OSError:
            continue
        if found is not None and declared is not None and found != declared:
            return (f"candidate and challenge declare different timescales: "
                    f"{Path(path).name} declares {found}, the challenge "
                    f"declares {declared}")
    return None


def _ports_absent_from_dut(errors: str) -> list:
    """Port names iverilog says are not ports of the instantiated unit.

    The diagnostic is `port ``NAME'' is not a port of dut.` — the quoting is
    iverilog's own (two backticks, two apostrophes), so match it literally
    rather than guessing a shape. Returns names in first-seen order with
    duplicates removed: one missing port is usually reported once per
    instantiation site and a count is not the finding, the membership is.
    """
    seen = []
    for m in re.finditer(r"port ``([^']+)'' is not a port of", errors or ""):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def _interface_omission_reason(candidate: dict, challenge: dict,
                               errors: str) -> str | None:
    """The attributable interface defect this compile proves, or None.

    v1.20.9 established WHICH ports the compiler says are absent and stated,
    out loud, that attribution between "the candidate omitted a required port"
    and "the test invented one" is UNDETERMINED without the prompt-bound
    interface. This is the consumer that supplies it. It reads
    `_ports_absent_from_dut` rather than re-deriving the same list: one
    extractor, so the disclosure and the attribution can never disagree about
    which ports the compiler named.

    The freeze-time half (`_interface_proof_from_review`) established that the
    public input REQUIRES this port. This half re-establishes everything that
    is a fact about THIS RUN, and takes none of it on trust from the proof:

      * the proof is bound to the candidate being compiled RIGHT NOW. A
        challenge is INHERITED across repair rounds -- `_validate_ai_review`
        re-runs every one of them against the new candidate -- so a proof
        frozen against the parent must not be spent on its child. It is
        re-earned or it is not used.
      * this candidate really does declare the module and NOT the port. The
        freeze-time check answered that about a different set of bytes.
      * the compiler itself named this port as absent.

    None whenever any of that is missing, and the caller then falls through to
    v1.20.9's disclosure unchanged -- so the undecidable case keeps saying it
    is undecidable, and only a validated proof turns it into a decision. An
    interface result stays an interface result: this returns a
    CANDIDATE_BROKEN reason, never a runtime FAIL and never a PASS.
    """
    proof = challenge.get("interface_proof")
    if not isinstance(proof, dict) or proof.get("schema") != _INTERFACE_PROOF_SCHEMA:
        return None
    port = str(proof.get("port") or "")
    module = str(proof.get("module") or "")
    if not port or not module:
        return None
    if proof.get("candidate_rtl_sha256") != candidate.get("rtl_sha256"):
        return None
    # THE CHALLENGE IS RE-EARNED TOO. The candidate binding above stops a proof
    # frozen against a parent from being spent on its child, but nothing stopped
    # a proof frozen for one CHALLENGE from riding on another: this function is
    # reached once per challenge, and a challenge is inherited across repair
    # rounds. `_run_verification_challenge` binds the challenge to its own hash,
    # so the comparison that was missing is the proof's claim against it.
    if proof.get("challenge_sha256") != challenge.get("sha256"):
        return None
    # AND THE REASON MUST NOT STATE WHAT THIS RUN DID NOT ESTABLISH. The
    # direction, width and excerpt below are interpolated into the attributed
    # reason verbatim. Whether the excerpt is really the public input is a
    # question only the freeze can ask, but whether the excerpt NAMES the port,
    # STATES that direction, and states that width are properties of the proof
    # itself -- so they are re-asked here, through the same helper the freeze
    # uses. Without this, a proof reaching this boundary directly could have the
    # attributed record assert an interface the excerpt does not support.
    if _interface_proof_internal_reasons(proof):
        return None
    if port not in _ports_absent_from_dut(errors):
        return None
    try:
        source = "\n".join(
            Path(p).read_text(errors="replace")
            for p in (candidate.get("rtl_paths") or []) if Path(p).is_file())
    except OSError:
        return None
    declared = _declared_ports(source, module)
    if declared is None or port in declared:
        return None
    return (f"joint compile failed on a REQUIRED public interface the "
            f"candidate omits: module {module!r} must declare "
            f"{proof.get('direction')} port {port!r} of width "
            f"{proof.get('width')}, evidenced by the public input excerpt "
            f"{proof.get('excerpt')!r} (excerpt provenance established when "
            f"the proof was frozen against the reviewed prompt; every other "
            f"binding re-earned on this run); the compiler reports it is not a "
            f"port of the instantiated candidate")


def _native_challenge_identity_path(run_p: Path) -> Path:
    return Path(run_p) / "ai_verification_challenges" / "native_execution.json"


_NATIVE_CHALLENGE_IDENTITY_FIELDS = (
    "container", "container_id", "image_id", "image_digest")


def _frozen_native_challenge_identity(run_p: Path) -> dict | None:
    path = _native_challenge_identity_path(run_p)
    if not path.exists() and not path.is_symlink():
        return None
    declaration = _read_json_regular(path)
    if (not isinstance(declaration, dict) or declaration.get("backend") != "native"
            or declaration.get("error") or any(
                not isinstance(declaration.get(k), str) or not declaration[k]
                for k in _NATIVE_CHALLENGE_IDENTITY_FIELDS)):
        raise ValueError("frozen native challenge identity is incomplete")
    return declaration


def _known_unbound_native_mismatch(declaration) -> bool:
    """Only this pre-proof refusal is retryable; bound identities never refresh."""
    return (isinstance(declaration, dict)
            and declaration.get("backend") == "native"
            and declaration.get("error") == "runtime pair is incomplete or mismatched"
            and not any(declaration.get(k) for k in _NATIVE_CHALLENGE_IDENTITY_FIELDS)
            and isinstance(declaration.get("runtime_pair"), dict)
            and declaration["runtime_pair"].get("verdict") == _runtime_pair.RUNTIME_PAIR_MISMATCH)


def _challenge_execution_declaration(run_p: Path, *, native: bool = False) -> dict:
    """Bind the challenge to the run's selected runtime, before execution.

    Old standalone callers without a runtime declaration retain their named
    legacy host mode. A present but unreadable/incomplete pair NEVER selects it.
    An operator can explicitly select host challenges with
    VIBEIC_CHALLENGE_BACKEND=host; this does not change the runner's backend.
    """
    # A process default cannot override the run's first native proof identity.
    try:
        frozen = _frozen_native_challenge_identity(run_p)
    except (OSError, ValueError) as exc:
        return {"backend": "native", "error": str(exc)}
    if frozen is not None:
        return frozen
    selected = "native" if native else os.environ.get("VIBEIC_CHALLENGE_BACKEND")
    if selected == "host":
        return {"backend": "host", "selection": "VIBEIC_CHALLENGE_BACKEND=host"}
    if selected not in (None, "native"):
        return {"backend": selected, "error": "unknown challenge backend"}
    path = Path(run_p) / _RUNTIME_PAIR_RECORD
    if (not path.exists() and selected is None
            and not (Path(run_p) / ".bench_config.json").exists()):
        return {"backend": "host", "selection": "legacy caller without runtime pair"}
    try:
        pair = _strict_json_loads(path.read_text())
    except (OSError, ValueError) as exc:
        return {"backend": "native", "error": f"runtime pair unreadable: {exc}"}
    if (not isinstance(pair, dict)
            or pair.get("verdict") != _runtime_pair.RUNTIME_PAIR_MATCH
            or not pair.get("container")
            or not pair.get("required_digest")
            or pair.get("required_digest") != pair.get("found_digest")):
        return {"backend": "native", "error": "runtime pair is incomplete or mismatched",
                "runtime_pair": pair}
    container = str(pair["container"])
    image_id, why = _runtime_pair._pin.container_image_id(container)
    return {"backend": "native", "selection": str(path.resolve()),
            "container": container,
            "container_id": _challenge_exec.container_id(container),
            "image_id": image_id, "image_digest": pair["required_digest"],
            **({"error": why} if why else {})}


def _challenge_execution_for_task(task: dict) -> dict:
    project = Path(str(task.get("project") or ""))
    run_p = project.parent.parent
    declaration = task.get("verification_execution")
    try:
        frozen = _frozen_native_challenge_identity(run_p)
    except (OSError, ValueError) as exc:
        return {"backend": "native", "error": str(exc)}
    if "verification_execution" in task:
        declaration = task["verification_execution"]
        if frozen is not None:
            issued_host = frozen.get("issued_host_task_sha256", [])
            if (isinstance(declaration, dict) and declaration.get("backend") == "host"
                    and not str(declaration.get("selection", "")).startswith("legacy")
                    and isinstance(issued_host, list)
                    and _review_task_digest(task) in issued_host):
                return declaration
            if _known_unbound_native_mismatch(declaration):
                return frozen
            if (not isinstance(declaration, dict)
                    or declaration.get("backend") != "native"
                    or declaration.get("error")
                    or any(declaration.get(k) != frozen[k]
                           for k in _NATIVE_CHALLENGE_IDENTITY_FIELDS)):
                return {**frozen, "error": "task declaration differs from frozen native identity"}
            return frozen
        if _known_unbound_native_mismatch(declaration):
            # The original refusal stays in the task/worklist. Only a persisted
            # MATCH may bind its first proof; arbitrary native errors stay owed.
            return _challenge_execution_declaration(run_p, native=True)
        if (isinstance(declaration, dict) and declaration.get("backend") == "host"
                and str(declaration.get("selection", "")).startswith("legacy")
                and ((run_p / _RUNTIME_PAIR_RECORD).exists()
                     or (run_p / ".bench_config.json").exists())):
            return {"backend": "native", "error": "canonical task has only a legacy host declaration"}
        return declaration
    # Historical tasks are resumed against their original run declaration,
    # including malformed declarations; absence is the named legacy case only.
    return _challenge_execution_declaration(run_p)


def _challenge_native_identity(declaration: dict) -> tuple[dict, str]:
    """Read back the exact selected container; no host or alternate CID fallback."""
    container = str(declaration.get("container") or "")
    cid = _challenge_exec.container_id(container)
    image_id, why_id = _runtime_pair._pin.container_image_id(container)
    digest, why_digest = _runtime_pair._pin.container_image_digest(container)
    actual = {"container_id": cid, "image_id": image_id, "image_digest": digest}
    if declaration.get("error"):
        return actual, str(declaration["error"])
    for field, value in actual.items():
        if not declaration.get(field) or not value:
            return actual, f"native {field} unavailable: {why_id or why_digest}"
        if value != declaration[field]:
            return actual, (f"native {field} drift: declared {declaration[field]}, "
                            f"found {value}")
    return actual, ""


def _run_verification_challenge(candidate: dict, challenge: dict) -> dict:
    """BLOCKING: execute the immutable proof on its declared backend.

    Missing native identity/capability is UNAVAILABLE (acceptance NOT_MEASURED),
    never a candidate verdict. Legacy direct calls are explicitly labelled host.
    Raw command/returncode/stdout/stderr records accompany every execution.
    """
    reasons = _validate_candidate_snapshot(candidate, str(candidate.get("id")))
    if reasons:
        return {"status": "INVALID", "reasons": reasons}
    test_path = Path(str(challenge.get("path") or ""))
    try:
        source = test_path.read_text(errors="replace")
    except OSError as exc:
        return {"status": "INVALID", "reasons": [f"challenge unreadable: {exc}"]}
    if _sha256_text(source) != challenge.get("sha256"):
        return {"status": "INVALID", "reasons": ["challenge hash changed"]}
    if _challenge_forbidden_hit(source):
        return {"status": "INVALID",
                "reasons": ["challenge is not self-contained"]}
    declaration = challenge.get("execution_backend", {
        "backend": "host", "selection": "legacy standalone caller"})
    receipt = {"declaration": declaration, "commands": [], "tools": {}}

    def finish(result):
        return {**result, "execution": receipt}

    if not isinstance(declaration, dict) or declaration.get("backend") not in ("host", "native"):
        return finish({"status": "UNAVAILABLE", "reasons": ["challenge backend is undeclared or invalid"]})
    native = declaration["backend"] == "native"
    mounts = []
    if native:
        actual, why = _challenge_native_identity(declaration)
        receipt["identity_before"] = actual
        if why:
            return finish({"status": "UNAVAILABLE", "reasons": [why]})
        execution_run = challenge.get("execution_run")
        if execution_run is not None:
            # Freeze after readback, before the first tool. Repeated proofs use
            # the same identity, even after a fresh process or pair overwrite.
            run_p = Path(execution_run)
            path = _native_challenge_identity_path(run_p)
            frozen = {"backend": "native", "selection": str(path.resolve()),
                      **{k: declaration[k] for k in _NATIVE_CHALLENGE_IDENTITY_FIELDS}}
            try:
                existing = _frozen_native_challenge_identity(run_p)
                if existing is None:
                    frozen["issued_host_task_sha256"] = sorted({
                        _review_task_digest(task)
                        for task in _read_jsonl(run_p / _REVIEW_WORKLIST)
                        if isinstance(task.get("verification_execution"), dict)
                        and task["verification_execution"].get("backend") == "host"
                        and not str(task["verification_execution"].get(
                            "selection", "")).startswith("legacy")})
                elif "issued_host_task_sha256" in existing:
                    # Never backfill an old freeze from the mutable worklist.
                    frozen["issued_host_task_sha256"] = existing["issued_host_task_sha256"]
                _write_immutable_json(path, frozen)
                if _frozen_native_challenge_identity(run_p) != frozen:
                    raise ValueError("frozen native identity readback differs")
            except (OSError, ValueError) as exc:
                return finish({"status": "UNAVAILABLE", "reasons": [str(exc)]})
            declaration = frozen
            receipt["declaration"] = frozen
        try:
            inspect_argv = ["docker", "inspect", "--format", "{{json .Mounts}}", declaration["container_id"]]
            cp = subprocess.run(inspect_argv, capture_output=True, text=True, timeout=30)
            receipt["commands"].append({"stage": "mounts", "argv": inspect_argv,
                "returncode": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr})
            mounts = _strict_json_loads(cp.stdout) if cp.returncode == 0 else []
            if not isinstance(mounts, list):
                raise ValueError("container mounts are not a list")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return finish({"status": "UNAVAILABLE", "reasons": [f"native mounts unavailable: {exc}"]})

    def mapped(path):
        absolute = Path(path).resolve()
        if not native:
            return str(absolute)
        choices = []
        for mount in mounts:
            if mount.get("Type") != "bind":
                continue
            root = Path(mount["Source"]).resolve()
            if absolute.is_relative_to(root):
                choices.append((len(root.parts), str(Path(mount["Destination"]) / absolute.relative_to(root))))
        if not choices:
            raise ValueError(f"native backend has no bind mount for {absolute}")
        return max(choices)[1]

    def execute(stage, argv, cwd=None):
        actual_argv = argv
        if native:
            actual, why = _challenge_native_identity(declaration)
            receipt["identity_before_" + stage] = actual
            if why:
                raise ValueError(why)
            command = shlex.join(argv)
            if cwd is not None:
                command = "cd " + shlex.quote(mapped(cwd)) + " && exec " + command
            actual_argv = _challenge_exec.container_deadline_argv(
                declaration["container_id"], command, 30,
                shell=("env", "IIC_OSIC_TOOLS_QUIET=1", "bash", "-lc"))
        record = {"stage": stage, "tool_argv": argv, "argv": actual_argv, "cwd": cwd}
        receipt["commands"].append(record)
        try:
            cp = subprocess.run(actual_argv, cwd=None if native else cwd,
                capture_output=True, text=True, timeout=45 if native else 30)
        except subprocess.TimeoutExpired as exc:
            record.update(returncode=None,
                stdout=exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout,
                stderr=exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr,
                timed_out=True)
            raise
        record.update(returncode=cp.returncode, stdout=cp.stdout, stderr=cp.stderr)
        if native:
            actual, why = _challenge_native_identity(declaration)
            receipt["identity_after_" + stage] = actual
            if why:
                raise ValueError(why)
            if _challenge_exec.image_refusal(cp) or cp.returncode in {124, 126, 127}:
                raise ValueError(f"native {stage} unavailable: rc={cp.returncode}: {cp.stderr}")
            if (cp.returncode != 0
                    and (cp.stderr or "").startswith("Error response from daemon:")):
                raise ValueError(f"native {stage} transport unavailable: {cp.stderr}")
        return cp

    try:
        tools = {}
        for tool in ("iverilog", "vvp"):
            if native:
                probe = execute("locate_" + tool, ["bash", "-c", "command -v " + tool])
                path = probe.stdout.strip() if probe.returncode == 0 else ""
            else:
                path = shutil.which(tool)
            if not path:
                return finish({"status": "UNAVAILABLE", "reasons": [f"{tool} unavailable on declared {declaration['backend']} backend"]})
            tools[tool] = path
            version = execute("version_" + tool, [path, "-V"])
            if version.returncode != 0:
                return finish({"status": "UNAVAILABLE", "reasons": [f"{tool} version probe failed"]})
            receipt["tools"][tool] = {"path": path, "version_stdout": version.stdout, "version_stderr": version.stderr}
        iverilog, vvp = tools["iverilog"], tools["vvp"]
    except subprocess.TimeoutExpired:
        return finish({"status": "UNAVAILABLE",
                       "reasons": ["challenge tool version probe timed out"]})
    except (OSError, ValueError, subprocess.SubprocessError, _challenge_exec.ContainerImageMismatch) as exc:
        return finish({"status": "UNAVAILABLE", "reasons": [f"challenge backend unavailable: {exc}"]})
    rtl_paths = [str(Path(p)) for p in candidate.get("rtl_paths") or []]
    # ARGUMENT ORDER IS NOT A VERDICT INPUT. `timescale is a compiler
    # directive that applies from its point of appearance FORWARD, across
    # files, in compile order. A candidate with no `timescale of its own
    # therefore inherits the challenge's unit when the challenge is compiled
    # first, and iverilog's default when it is compiled first -- MEASURED
    # 2026-09-06 on a correct clkgenerator candidate: RTL-first FAIL,
    # TB-first PASS, and the runner reported "the frozen candidate must pass
    # its required test" about a candidate that was right. A verdict that
    # argument order can flip is not a verdict.
    #
    # The fix states the DECLARED unit once, ahead of every source, so all of
    # them share it whatever order they are given in. It is never guessed:
    # with no declaration anywhere there is no prelude and every file keeps
    # the same default, which is already order-independent.
    declared = _declared_timescale(source)
    disagreement = _timescale_disagreement(rtl_paths, declared)
    if disagreement is not None:
        return finish({"status": "INVALID", "reasons": [disagreement]})
    # Native scratch must be in the candidate's measured bind mount, not the
    # host's unrelated /tmp. Longest-prefix mapping also supports unlike roots.
    scratch_root = str(Path(candidate["manifest_path"]).parent) if native else None
    try:
        scratch = tempfile.TemporaryDirectory(prefix="vibeic-ai-challenge-", dir=scratch_root)
    except OSError as exc:
        return finish({"status": "UNAVAILABLE", "reasons": [f"challenge scratch unavailable: {exc}"]})
    with scratch as td:
        out = Path(td) / "simv"
        prelude = []
        if declared is not None:
            prelude_path = Path(td) / "_vibeic_timescale.v"
            try:
                prelude_path.write_text(f"`timescale {declared}\n")
            except OSError as exc:
                return finish({"status": "UNAVAILABLE", "reasons": [f"challenge scratch unavailable: {exc}"]})
            prelude = [str(prelude_path)]
        try:
            comp = execute("compile",
                [iverilog, "-g2012", "-s", "vibeic_ai_challenge_tb",
                 "-o", mapped(out), *[mapped(p) for p in prelude],
                 *[mapped(p) for p in rtl_paths], mapped(test_path)], cwd=td)
        except subprocess.TimeoutExpired:
            return finish({"status": "UNAVAILABLE" if native else "INVALID", "reasons": ["challenge compile timed out"]})
        except (OSError, ValueError, _challenge_exec.ContainerImageMismatch) as exc:
            return finish({"status": "UNAVAILABLE", "reasons": [f"challenge backend unavailable: {exc}"]})
        if comp.returncode != 0:
            errors = comp.stderr or comp.stdout or ""
            cites_candidate, cites_challenge = _joint_compile_attribution(
                errors, [mapped(p) for p in rtl_paths], mapped(test_path))
            if cites_candidate and not cites_challenge:
                return finish({"status": _CHALLENGE_CANDIDATE_BROKEN, "reasons": [
                    "joint compile failed; every cited file is candidate RTL",
                    errors[-1200:],
                ]})
            if cites_challenge and not cites_candidate:
                # The one case where the CITED FILE is not the broken one: a
                # required public port the candidate never declared is
                # reported at the test's named-port instantiation, exactly
                # where an invented port name is. The interface proof was
                # validated against the public input at freeze time; what is
                # still open is whether the COMPILER actually says this port
                # is missing, which only the real diagnostics can answer.
                proven = _interface_omission_reason(
                    candidate, challenge, errors)
                if proven is not None:
                    return finish({"status": _CHALLENGE_CANDIDATE_BROKEN,
                            "interface_proof": challenge["interface_proof"],
                            "reasons": [proven, errors[-1200:]]})
                cited = "only the challenge file"
            elif cites_candidate:
                cited = "both candidate RTL and the challenge file"
            else:
                cited = "no classifiable file"
            # AN OMITTED REQUIRED PORT AND AN INVENTED ONE PRODUCE THE SAME
            # DIAGNOSTIC, IN THE SAME FILE (vibe-ic#2210). iverilog reports
            # both at the challenge's named-port instantiation, so attribution
            # by CITED FILE cannot separate "the candidate failed to expose a
            # port it was required to expose" from "the test asked for a port
            # nobody required". Those are opposite verdicts: the first is a
            # real interface defect held without a candidate-side proof, the
            # second is correctly INVALID.
            #
            # Deciding it needs the PROMPT-BOUND interface, and this function
            # receives only a candidate and a challenge. So it does not decide.
            # It NAMES the ports and says which question is unanswered — a gate
            # that cannot decide has to say so rather than pick, or the next
            # reader inherits a verdict with no evidence under it.
            absent = _ports_absent_from_dut(errors)
            extra = []
            if absent:
                extra = [
                    "ports named by the compiler as absent from the "
                    f"instantiated unit: {', '.join(absent)}",
                    "ATTRIBUTION UNDETERMINED: this diagnostic is identical "
                    "whether the candidate OMITTED a required port or the "
                    "challenge INVENTED one. Deciding it requires the "
                    "prompt-bound required interface, which this comparison "
                    "does not carry. Supply it to attribute; do not read this "
                    "INVALID as evidence that the candidate is conforming.",
                ]
            return finish({"status": "INVALID",
                    "ports_absent_from_candidate": absent,
                    "reasons": [
                        f"joint compile failed; errors cite {cited}",
                        *extra,
                        errors[-1200:],
                    ]})
        try:
            sim = execute("runtime", [vvp, mapped(out)], cwd=td)
        except subprocess.TimeoutExpired:
            return finish({"status": "UNAVAILABLE" if native else "INVALID", "returncode": None,
                    "reasons": ["challenge simulation timed out"]})
        except (OSError, ValueError, _challenge_exec.ContainerImageMismatch) as exc:
            return finish({"status": "UNAVAILABLE", "reasons": [f"challenge backend unavailable: {exc}"]})
    output = (sim.stdout or "") + (sim.stderr or "")
    # The challenge contract requires printing the FAIL marker, not exiting
    # non-zero: a test that collects its verdict in $finish still fails.
    failed = "VIBEIC_AI_CHALLENGE=FAIL" in output
    passed = (not failed and sim.returncode == 0
              and "VIBEIC_AI_CHALLENGE=PASS" in output)
    return finish({
        "status": ("FAIL" if failed else ("PASS" if passed else "INVALID")),
        "returncode": sim.returncode,
        "output": output[-2000:],
        "candidate_rtl_sha256": candidate.get("rtl_sha256"),
        "challenge_sha256": challenge.get("sha256"),
    })


def _validate_ai_review(task: dict, *,
                        allow_repaired_output: bool = False,
                        repaired_output_sha256: str | None = None) -> dict:
    """Validate a hash-bound review, including evidence-backed AI override.

    AI is the semantic authority, but authority is not an unexplained token.
    It may override the program route when it cites prompt text or provides a
    detailed interpretation and identifies the deterministic limitation.  A
    valid semantic FAIL is a real ``REPAIR_REQUIRED`` decision, not a malformed
    review and not a permanent convergence failure.
    """
    task_reasons: list[str] = _public_input_reasons(task)
    invocation_reason = _runner_reentry_reason(
        task, {}, allow_repaired_output=allow_repaired_output,
        repaired_output_sha256=repaired_output_sha256)
    if invocation_reason:
        task_reasons.append(invocation_reason)
    if task.get("schema") != _REVIEW_TASK_SCHEMA:
        task_reasons.append(f"review task schema must be {_REVIEW_TASK_SCHEMA!r}")
    review_path = Path(str(task.get("review_path") or ""))
    if not review_path.is_file():
        return {"status": "PENDING", "review_path": str(review_path),
                "reasons": task_reasons + ["AI review file is absent"]}
    try:
        review = _strict_json_loads(review_path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return {"status": "REJECTED", "review_path": str(review_path),
                "reasons": [f"AI review is unreadable: {type(exc).__name__}: {exc}"]}
    reasons: list[str] = task_reasons
    if not isinstance(review, dict):
        reasons.append("AI review is not a JSON object")
        review = {}
    if review.get("schema") != _AI_REVIEW_SCHEMA:
        reasons.append(f"schema must be {_AI_REVIEW_SCHEMA!r}")
    if str(review.get("id")) != str(task.get("id")):
        reasons.append("review id does not match the task")

    prompt_hash, rtl_hash, stated, current = _current_task_material(task)
    if stated != current:
        reasons.append("current RTL file set differs from the reviewed task")
    if prompt_hash != task.get("prompt_sha256"):
        reasons.append("prompt changed after the review task was issued")
    if rtl_hash != task.get("rtl_sha256"):
        reasons.append("RTL changed after the review task was issued")
    if review.get("prompt_sha256") != task.get("prompt_sha256"):
        reasons.append("review prompt_sha256 is stale or wrong")
    if review.get("rtl_sha256") != task.get("rtl_sha256"):
        reasons.append("review rtl_sha256 is stale or wrong")
    original = task.get("public_original_input") or {}
    if original.get("status") == "PRESENT" and review.get(
            "source_sha256") != original.get("source_sha256"):
        reasons.append("review source_sha256 is stale or wrong")
    if task.get("candidate_origin") == "AI_BACKUP":
        provenance = task.get("backup_provenance") or {}
        try:
            record = provenance["author_record"]
            if (record["id"] != task["id"]
                    or record["prompt_sha256"] != task["prompt_sha256"]
                    or provenance["public_original_input"] != original
                    or provenance["gated_rtl_sha256"] != task["rtl_sha256"]):
                raise ValueError("backup input/output lineage differs")
            root = Path(provenance["input_root"])
            if _strict_json_loads((root.parent / "author_record.json").read_text()) != record:
                raise ValueError("archived author record differs")
            import benchmark_io_adapter as bio          # noqa: PLC0415
            for row in record["output_manifest"]:
                data = (root / bio._public_relative(row["relative_path"])).read_bytes()
                if hashlib.sha256(data).hexdigest() != row["sha256"]:
                    raise ValueError("archived author input differs")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            reasons.append(f"AI_BACKUP_PROVENANCE_INVALID: {exc}")

    reviewer = review.get("reviewer") or {}
    if reviewer.get("kind") != "AI":
        reasons.append("reviewer.kind must be AI")
    model = str(reviewer.get("model") or "").strip()
    if not model or model.lower() in {"unknown", "unspecified", "n/a"}:
        reasons.append("reviewer.model must name the AI model")

    blind = review.get("blind") or {}
    if blind.get("oracle_accessed") is not False:
        reasons.append("blind.oracle_accessed must be false")

    prompt_path = Path(str(task.get("prompt_path") or ""))
    prompt_text = (prompt_path.read_text(errors="replace")
                   if prompt_path.is_file() else "")
    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        reasons.append("candidate snapshot record is malformed")
        candidate = {}
    reasons.extend(_validate_candidate_snapshot(
        candidate, str(task.get("id"))))
    reasons.extend(_validate_embedded_repair_provenance(task))
    try:
        expected_obligations = _program_review_obligation_contract(
            prompt_text, candidate, _task_project(task))
    except (ImportError, OSError, ValueError) as exc:
        expected_obligations = None
        reasons.append(
            "Program review obligations could not be derived: "
            f"{type(exc).__name__}: {exc}")
    if expected_obligations is not None \
            and task.get("program_review_obligations") != expected_obligations:
        reasons.append(
            "program_review_obligations are missing, stale, or differ from "
            "the current prompt and frozen candidate")

    routing = review.get("routing") or {}
    expected_nature = (task.get("program_routing") or {}).get("nature")
    routing_verdict = routing.get("verdict")
    override = review.get("override") or {}
    evidence = override.get("prompt_evidence") or []
    verified_evidence = []
    if routing_verdict == "AGREE":
        if routing.get("ai_nature") != expected_nature:
            reasons.append("AI route marked AGREE but does not match program route")
    elif routing_verdict == "OVERRIDE_PROGRAM":
        if not isinstance(evidence, list):
            reasons.append("override.prompt_evidence must be a list")
            evidence = []
        verified_evidence = _verified_prompt_evidence(evidence, prompt_text)
        explanation = str(override.get("explanation") or "").strip()
        if not verified_evidence and len(explanation) < 160:
            reasons.append("OVERRIDE_PROGRAM needs prompt-bound evidence or a "
                           "detailed explanation of at least 160 characters")
        if len(str(override.get("program_limitation") or "").strip()) < 16:
            reasons.append("OVERRIDE_PROGRAM must identify the program limitation")
        proposed = override.get("proposed_program_enhancement")
        if proposed is not None:
            if not isinstance(proposed, dict):
                reasons.append("proposed_program_enhancement must be an object")
            elif (len(str(proposed.get("component") or "").strip()) < 3
                  or len(str(proposed.get("proposal") or "").strip()) < 16
                  or len(str(proposed.get("regression_fixture") or "").strip()) < 8):
                reasons.append("proposed_program_enhancement must name a component, "
                               "concrete proposal, and regression fixture")
    else:
        reasons.append("AI routing verdict must be AGREE or OVERRIDE_PROGRAM")

    semantic = review.get("semantic_review") or {}
    semantic_verdict = semantic.get("verdict")
    findings = semantic.get("findings")
    semantic_evidence = semantic.get("prompt_evidence") or []
    verified_semantic_evidence = _verified_prompt_evidence(
        semantic_evidence, prompt_text)
    if semantic_verdict not in {"PASS", "FAIL", "NEEDS_CLARIFICATION"}:
        reasons.append("AI semantic_review verdict must be PASS or FAIL, or NEEDS_CLARIFICATION")
    if semantic_verdict != "NEEDS_CLARIFICATION" and "spec_clarification" in review:
        reasons.append("unresolved spec_clarification is only valid with NEEDS_CLARIFICATION")
    if not isinstance(findings, list):
        reasons.append("semantic_review.findings must be a list")
        findings = []
    if semantic_verdict == "FAIL" and not findings:
        reasons.append("semantic FAIL must name at least one actionable finding")
    rationale = str(semantic.get("rationale") or "").strip()
    if len(rationale) < 16:
        reasons.append("semantic_review.rationale must state the review basis")
    challenge = None
    challenge_result = None
    # ``or {}`` only launders a FALSY non-dict: a truthy ``"not-an-object"``
    # or ``7`` survived it and reached ``.get()`` as an AttributeError, which
    # is the one outcome a fail-closed guard must never produce -- a BLOCKED
    # exit is legible, a traceback out of the acceptance predicate is not.
    program_verification = task.get("program_verification")
    if not isinstance(program_verification, dict):
        if program_verification is not None:
            reasons.append("Program verification record is malformed")
        program_verification = {}
    functional_evidence = program_verification.get("functional_evidence")
    confirmation_required = program_verification.get(
        "functional_confirmation_required")
    if not isinstance(confirmation_required, bool):
        reasons.append(
            "program_verification.functional_confirmation_required must be boolean")
        confirmation_required = True
    if confirmation_required != (functional_evidence != "PASS"):
        reasons.append(
            "functional confirmation requirement contradicts Program evidence")
    if semantic_verdict == "NEEDS_CLARIFICATION":
        from spec_review_lint import validate_spec_clarification

        clarification = validate_spec_clarification(
            review.get("spec_clarification"), {str(prompt_path): prompt_text})
        reasons.extend(clarification["errors"])
        if clarification["status"] != "SPEC_CLARIFICATION_REQUIRED":
            reasons.append("NEEDS_CLARIFICATION requires a valid source-bound question")
        if review.get("challenge_supersessions"):
            reasons.append("spec clarification cannot supersede verification challenges")
        inherited = task.get("verification_challenges") or []
        if not isinstance(inherited, list) or any(not isinstance(item, dict) for item in inherited):
            reasons.append("inherited verification challenges must be a list of objects")
            inherited = []
        # No simulation can supply a missing requirement. Preserve all existing
        # tests for the next review; do not execute, waive, or reclassify them.
        status = "REJECTED" if reasons else "SPEC_CLARIFICATION_REQUIRED"
        return {
            "status": status, "review_path": str(review_path), "reasons": reasons,
            "decision_reasons": reasons or [
                "The AI requests a missing spec definition; this is not a proven "
                "RTL defect. Obtain an owner clarification before a fresh review."],
            "reviewer_model": model or None, "routing_verdict": routing_verdict,
            "ai_nature": routing.get("ai_nature"), "semantic_verdict": semantic_verdict,
            "semantic_findings": len(findings), "semantic_findings_detail": findings,
            "semantic_rationale": rationale,
            "verified_semantic_prompt_evidence": verified_semantic_evidence,
            "spec_clarification": clarification,
            "verified_challenge": None, "challenge_result": None,
            "inherited_challenge_results": [
                {"status": "NOT_RUN", "reason": "awaiting spec clarification",
                 "challenge_sha256": item.get("sha256")}
                for item in inherited],
            "challenge_supersessions": [], "program_review_coverage": None,
            "unmeasurable": [], "override": None,
        }
    #: Reasons this host could not ADJUDICATE, kept apart from `reasons`, which
    #: are findings against the review or the candidate. The two must never be
    #: mixed: one says "this is wrong", the other says "we did not look".
    unmeasurable: list[str] = []
    execution_backend = _challenge_execution_for_task(task)
    raw_supersessions = review.get("challenge_supersessions")
    supersession_requested = (
        isinstance(raw_supersessions, list) and bool(raw_supersessions))
    if semantic_verdict == "FAIL":
        challenge, challenge_reasons = _challenge_from_review(
            task, review, prompt_text)
        reasons.extend(challenge_reasons)
        if challenge is not None:
            challenge_result = _run_verification_challenge(
                candidate, {**challenge, "execution_backend": execution_backend,
                            "execution_run": str(Path(task["project"]).parent.parent)})
            if challenge_result.get("status") == _CHALLENGE_UNAVAILABLE:
                unmeasurable.append(
                    "the prompt-derived verification test could not be RUN on "
                    "this host, so the AI finding is neither proven nor "
                    "disproven: "
                    + "; ".join(str(r) for r in
                                challenge_result.get("reasons") or []))
            elif (challenge_result.get("status")
                  == _CHALLENGE_CANDIDATE_BROKEN):
                # A candidate that cannot even compile can never produce the
                # FAIL a proof demands; demanding one here would make worse
                # candidates harder to reject than better ones. The compile
                # errors travel with challenge_result into the repair task.
                pass
            elif challenge_result.get("status") != "FAIL":
                reasons.append("AI finding is not proven: the reviewed candidate "
                               "must fail the prompt-derived verification test")
    elif (semantic_verdict == "PASS"
          and (confirmation_required or supersession_requested)):
        challenge, challenge_reasons = _challenge_from_review(
            task, review, prompt_text,
            required_for=(
                "challenge supersession replacement"
                if supersession_requested
                else "semantic PASS without Program functional evidence"))
        reasons.extend(challenge_reasons)
        if challenge is not None:
            challenge_result = _run_verification_challenge(
                candidate, {**challenge, "execution_backend": execution_backend,
                            "execution_run": str(Path(task["project"]).parent.parent)})
            if challenge_result.get("status") == _CHALLENGE_UNAVAILABLE:
                unmeasurable.append(
                    "the prompt-derived PASS confirmation could not be RUN on "
                    "this host, so the candidate is not functionally measured: "
                    + "; ".join(str(r) for r in
                                challenge_result.get("reasons") or []))
            elif challenge_result.get("status") != "PASS":
                reasons.append(
                    "AI semantic PASS is not confirmed: the frozen candidate "
                    "must pass its required prompt-derived verification test")
    challenge_supersessions, supersession_reasons = \
        _challenge_supersessions_from_review(
            task, review, prompt_text, challenge)
    reasons.extend(supersession_reasons)
    if challenge_supersessions and semantic_verdict != "PASS":
        reasons.append(
            "challenge supersession requires a fresh AI semantic PASS")
    supersession_authorized = (
        semantic_verdict == "PASS"
        and (challenge_result or {}).get("status") == "PASS"
        and not supersession_reasons)
    supersession_by_hash = ({
        item["challenge_sha256"]: item
        for item in challenge_supersessions
    } if supersession_authorized else {})
    inherited_challenge_results = []
    for inherited in task.get("verification_challenges") or []:
        inherited_reasons = []
        if inherited.get("schema") != _CHALLENGE_SCHEMA:
            inherited_reasons.append("inherited challenge schema is invalid")
        if str(inherited.get("id")) != str(task.get("id")):
            inherited_reasons.append("inherited challenge id does not match task")
        if inherited.get("prompt_sha256") != task.get("prompt_sha256"):
            inherited_reasons.append("inherited challenge prompt hash is stale")
        if inherited_reasons:
            reasons.extend(inherited_reasons)
            inherited_challenge_results.append({
                "status": "INVALID", "reasons": inherited_reasons})
            continue
        result = _run_verification_challenge(
            candidate, {**inherited, "execution_backend": execution_backend,
                        "execution_run": str(Path(task["project"]).parent.parent)})
        supersession = supersession_by_hash.get(
            str(inherited.get("sha256") or ""))
        if supersession is not None:
            if result.get("status") == _CHALLENGE_UNAVAILABLE:
                unmeasurable.append(
                    "a challenge named for supersession could not be RUN on "
                    "this host, so its alleged defect was not measured: "
                    + "; ".join(str(r) for r in
                                result.get("reasons") or []))
            elif result.get("status") in {"FAIL", "INVALID"}:
                result = {
                    **result,
                    "status": "SUPERSEDED",
                    "original_status": result.get("status"),
                    "supersession": supersession,
                }
            else:
                reasons.append(
                    "a challenge named for supersession must validly FAIL or "
                    "be structurally INVALID on the current candidate before "
                    "it can be corrected; this one still PASSES, which means "
                    "it is not blocking acceptance and does not need to be "
                    "named -- drop it from challenge_supersessions")
            inherited_challenge_results.append(result)
            continue
        inherited_challenge_results.append(result)
        if result.get("status") == _CHALLENGE_UNAVAILABLE:
            unmeasurable.append(
                "an inherited immutable verification test could not be RUN on "
                "this host, so the repair is neither proven nor disproven: "
                + "; ".join(str(r) for r in result.get("reasons") or []))
        elif (result.get("status") == "FAIL"
              and semantic_verdict == "FAIL"):
            # A fresh AI rejection and an inherited prompt-derived failure
            # agree that this intermediate repair is still wrong.  That is
            # additional repair evidence, not a malformed review.  A claimed
            # PASS over the same failure remains rejected below.
            pass
        elif (result.get("status") == "INVALID"
              and semantic_verdict == "FAIL"
              and (challenge_result or {}).get("status") == "FAIL"):
            # A broken older test must not deadlock an independently proven
            # repair.  This does NOT waive, supersede, or accept the invalid
            # challenge: it remains visible and is carried to the next fresh
            # review, where semantic PASS is still blocked until the AI
            # supplies a prompt-bound passing replacement.  The only action
            # authorised here is another repair of a candidate that already
            # failed a different, fresh, executable prompt-derived test.
            result["nonblocking_during_proven_repair"] = True
            result["required_on_fresh_review"] = True
        elif result.get("status") != "PASS":
            reasons.append("repair does not pass every immutable verification "
                           "test that proved its parent candidate wrong")
    program_review_coverage = None
    if (semantic_verdict == "PASS" and confirmation_required
            and (challenge_result or {}).get("status") == "PASS"):
        active_challenges = [challenge] if challenge is not None else []
        for inherited, result in zip(
                task.get("verification_challenges") or [],
                inherited_challenge_results):
            if result.get("status") == "PASS":
                active_challenges.append(inherited)
        try:
            program_review_coverage = _program_review_coverage_result(
                prompt_text, candidate, active_challenges)
        except (ImportError, OSError, ValueError) as exc:
            unmeasurable.append(
                "Program could not measure AI verification-test coverage: "
                f"{type(exc).__name__}: {exc}")
        else:
            if program_review_coverage.get("status") != "PASS":
                gap_ids = [str(item.get("id")) for item in
                           program_review_coverage.get(
                               "blocking_gap_items") or []]
                reasons.append(
                    "AI semantic PASS leaves structural prompt obligation(s) "
                    "uncovered by its active executable tests: "
                    + ", ".join(gap_ids))
    if semantic_verdict == "PASS":
        # Disposed of separately from coverage: the gate names signals INTERNAL
        # to the design, which a correct port-driving challenge would never
        # mention, so this asks the reviewer for a verdict, not a token match.
        reasons.extend(_gate_escalation_disposition_reasons(
            task, review, prompt_text))
    if reasons:
        # A finding against the review outranks an unrunnable proof: a
        # malformed review is wrong on every host, simulator or not.
        status = "REJECTED"
        decision_reasons = reasons
    elif unmeasurable:
        status = _NOT_MEASURED
        decision_reasons = unmeasurable + [
            "NOT_MEASURED is not a verdict about this candidate or this "
            "review. This host lacks the capability the proof needs; install "
            "it and re-run --resume. Nothing is accepted on the strength of a "
            "test that did not run."]
    elif semantic_verdict == "FAIL":
        status = "REPAIR_REQUIRED"
        decision_reasons = ["AI semantic authority rejected the current RTL; "
                            "repair, re-run PROGRAM gates, and review the new hash"]
    else:
        status = "ACCEPTED"
        decision_reasons = []
    return {"status": status,
            "review_path": str(review_path), "reasons": reasons,
            "decision_reasons": decision_reasons,
            "reviewer_model": model or None,
            "routing_verdict": routing_verdict,
            "ai_nature": routing.get("ai_nature"),
            "semantic_verdict": semantic_verdict,
            "semantic_findings": len(findings),
            "semantic_findings_detail": findings,
            "semantic_rationale": rationale,
            "verified_semantic_prompt_evidence": verified_semantic_evidence,
            "verified_challenge": challenge,
            "challenge_result": challenge_result,
            "inherited_challenge_results": inherited_challenge_results,
            "challenge_supersessions": challenge_supersessions,
            "program_review_coverage": program_review_coverage,
            "unmeasurable": unmeasurable,
            "override": ({**override, "verified_prompt_evidence": verified_evidence}
                         if routing_verdict == "OVERRIDE_PROGRAM" else None)}


def _attach_ai_review_attribution(result: dict, verdict: dict,
                                  task: dict) -> None:
    """Put Program First's AI review WHO/HOW into the four-phase record."""
    phases = result.get("phases") or {}
    result["phases"] = phases
    status = verdict.get("status")
    model = verdict.get("reviewer_model")
    phases.setdefault("phase1_routing", {}).update({
        "ai_decided_routing_review": {
            "actor": model or "AI_PENDING",
            "mechanism": "AI",
            "authority": "FINAL_SEMANTIC_AUTHORITY",
            "status": status,
            "verdict": verdict.get("routing_verdict"),
            "nature": verdict.get("ai_nature"),
            "how": "blind prompt parse, hash-bound to prompt_sha256",
            "override_basis": verdict.get("override"),
        },
    })
    phases.setdefault("phase3_verifying", {}).update({
        "ai_semantic_review": {
            "actor": model or "AI_PENDING",
            "mechanism": "AI",
            "status": status,
            "verdict": verdict.get("semantic_verdict"),
            "findings": verdict.get("semantic_findings"),
            "how": "blind prompt-versus-RTL review, hash-bound to rtl_sha256",
            "program_functional_evidence": (
                task.get("program_verification") or {}).get(
                    "functional_evidence"),
            "functional_confirmation_required": (
                task.get("program_verification") or {}).get(
                    "functional_confirmation_required"),
            "functional_confirmation_result": (
                verdict.get("challenge_result") or {}).get("status"),
            "functional_confirmation_challenge_sha256": (
                verdict.get("verified_challenge") or {}).get("sha256"),
            "program_review_coverage": verdict.get(
                "program_review_coverage"),
        },
    })
    program_candidate = task.get("program_candidate_snapshot") or {}
    initial_origin = (program_candidate.get("candidate_origin")
                      or task.get("candidate_origin") or "NONE")
    result["initial_candidate_origin"] = initial_origin
    phases.setdefault("phase2_solving", {}).update({
        "program_first_candidate": {
            "origin": initial_origin,
            "rtl_sha256": program_candidate.get("rtl_sha256"),
            "how": "Program emitted and gated the immutable first candidate",
        },
        "accepted_candidate": {
            "origin": task.get("candidate_origin"),
            "rtl_sha256": task.get("rtl_sha256"),
        },
    })
    if status == "REPAIR_REQUIRED":
        phases.setdefault("phase4_debugging", {})[
            "ai_semantic_repair_handoff"] = {
                "actor": model, "mechanism": "AI",
                "status": status,
                "findings": verdict.get("semantic_findings_detail"),
                "how": ("AI explains the spec mismatch; corrected RTL must "
                        "return through PROGRAM gates and a fresh AI review"),
                "physical_eco": False,
            }
    if status == "SPEC_CLARIFICATION_REQUIRED":
        debugging = phases.setdefault("phase4_debugging", {})
        previous = debugging.get("ai_semantic_repair_handoff")
        if isinstance(previous, dict):
            # Preserve earlier evidence without advertising it as a current
            # repair instruction after the new review asks for missing input.
            previous.setdefault("prior_status", previous.get("status"))
            previous.update({"active": False, "status": "ON_HOLD_FOR_SPEC_CLARIFICATION"})
    phases["phase3_verifying"]["ai_semantic_review"]["spec_clarification"] = verdict.get(
        "spec_clarification")
    repair = task.get("repair_provenance") or {}
    if task.get("candidate_origin") == "AI_REPAIR" and repair:
        phases.setdefault("phase4_debugging", {})[
            "ai_semantic_repair"] = {
                "actor": (repair.get("author") or {}).get("model"),
                "mechanism": "AI",
                "status": "VERIFIED_AND_ACCEPTED" if status == "ACCEPTED"
                          else status,
                "rationale": repair.get("rationale"),
                "parent_rtl_sha256": repair.get("parent_rtl_sha256"),
                "repaired_rtl_sha256": repair.get("repaired_rtl_sha256"),
                "challenge_sha256": repair.get("challenge_sha256"),
                "program_reentry": "step 2 gates",
                "fresh_ai_review_actor": model,
                "physical_eco": False,
            }
    result["program_first_ai_review"] = {
        k: verdict.get(k) for k in (
            "status", "reviewer_model", "routing_verdict", "ai_nature",
            "semantic_verdict", "semantic_findings", "override")
    }
    result["program_first_ai_review"]["repair_provenance"] = repair or None


def _program_enhancement_candidate(task: dict, result: dict,
                                   verdict: dict) -> dict:
    """A durable, non-blocking follow-up when AI exposes program rigidity."""
    override = verdict.get("override") or {}
    if verdict.get("verified_challenge"):
        why_non_blocking = (
            "AI supplied prompt-bound executable evidence; convert the same "
            "test into a reusable Program regression without rewriting this "
            "already-frozen benchmark attempt")
    else:
        why_non_blocking = (
            "AI supplied an auditable route interpretation; improve the "
            "reusable Program router without rewriting this frozen attempt")
    return {
        "schema": "vibeic.benchmark.program_enhancement_candidate.v1",
        "id": str(task.get("id")),
        "project": task.get("project"),
        "prompt_sha256": task.get("prompt_sha256"),
        "rtl_sha256": task.get("rtl_sha256"),
        "review_path": task.get("review_path"),
        "program_candidate_snapshot": task.get("program_candidate_snapshot"),
        "reviewed_candidate_snapshot": task.get("candidate_snapshot"),
        "verified_challenge": verdict.get("verified_challenge"),
        "challenge_result": verdict.get("challenge_result"),
        "program_routing": task.get("program_routing"),
        "ai_routing": {
            "verdict": verdict.get("routing_verdict"),
            "nature": verdict.get("ai_nature"),
        },
        "semantic_verdict": verdict.get("semantic_verdict"),
        "semantic_findings": verdict.get("semantic_findings_detail"),
        "semantic_rationale": verdict.get("semantic_rationale"),
        "verified_semantic_prompt_evidence":
            verdict.get("verified_semantic_prompt_evidence") or [],
        "verified_prompt_evidence": override.get("verified_prompt_evidence") or [],
        "ai_explanation": override.get("explanation"),
        "program_limitation": override.get("program_limitation"),
        "proposed_program_enhancement":
            override.get("proposed_program_enhancement"),
        "candidate_origin": result.get("candidate_origin"),
        "status": "OPEN_PROGRAM_ENHANCEMENT",
        "blocking_acceptance": False,
        "why_non_blocking": why_non_blocking,
    }


def _verified_program_recovery(task: dict, result: dict,
                               verdict: dict) -> dict:
    """Capture a repair only after it passes the tests that proved Program wrong."""
    return {
        "schema": "vibeic.benchmark.program_enhancement_candidate.v2",
        "id": str(task.get("id")),
        "project": task.get("project"),
        "prompt_sha256": task.get("prompt_sha256"),
        "rtl_sha256": task.get("rtl_sha256"),
        "semantic_verdict": "VERIFIED_RECOVERY",
        "program_candidate_snapshot": task.get("program_candidate_snapshot"),
        "repaired_candidate_snapshot": task.get("candidate_snapshot"),
        "verification_challenges": task.get("verification_challenges") or [],
        "repair_challenge_results":
            verdict.get("inherited_challenge_results") or [],
        "repair_provenance": task.get("repair_provenance"),
        "fresh_ai_review_path": task.get("review_path"),
        "fresh_ai_reviewer_model": verdict.get("reviewer_model"),
        "candidate_origin": result.get("candidate_origin"),
        "status": "VERIFIED_AI_RECOVERY_READY_FOR_PROGRAM_CAPTURE",
        "required_capture": {
            "action": (
                "add the immutable prompt-derived challenge as a Program "
                "regression and enhance the reusable Program implementation"),
            "acceptance": (
                "the enhanced Program candidate passes the captured challenge "
                "on its first attempt without AI repair"),
        },
        "blocking_acceptance": False,
        "why_non_blocking": (
            "the current repair is independently proven and accepted; capture "
            "improves the next Program First attempt without rewriting this run"),
    }


def _four_phase_rollup(fpa, results: list[dict]) -> dict:
    """General attribution plus Program First / AI Review counts and actors."""
    out = fpa.summarize(results)

    def counts(values) -> dict:
        result: dict[str, int] = {}
        for value in values:
            key = str(value)
            result[key] = result.get(key, 0) + 1
        return result

    reviews = [r.get("program_first_ai_review") or {} for r in results]
    out["phase1_ai_review_status"] = counts(
        v.get("status") or "PENDING" for v in reviews)
    out["phase1_ai_review_models"] = counts(
        v.get("reviewer_model") or "PENDING" for v in reviews)
    out["phase2_candidate_origin"] = counts(
        r.get("candidate_origin", "NONE") for r in results)
    out["phase2_initial_candidate_origin"] = counts(
        r.get("initial_candidate_origin", r.get("candidate_origin", "NONE"))
        for r in results)
    out["phase3_ai_semantic_verdict"] = counts(
        v.get("semantic_verdict") or "PENDING" for v in reviews)
    out["phase4_ai_repair_required"] = counts(
        bool(r.get("ai_repair_required")) for r in results)
    out["phase4_ai_repairs_completed"] = counts(
        r.get("candidate_origin") == "AI_REPAIR" for r in results)
    return out


def _require_program_first_ai_acceptance(run_p: Path) -> None:
    """Block scoring until Program gates and blind AI review accept every id."""
    run_p = Path(run_p).resolve()
    solve_p = run_p / "solve_report.json"
    if not solve_p.is_file():
        return                         # historical/manual runs keep old policy
    try:
        solve = _strict_json_loads(solve_p.read_text(errors="replace"))
    except (OSError, ValueError):
        return                         # the clean-room gate reports this later
    policy = solve.get("acceptance_policy") or {}
    if policy.get("required") is not True:
        return
    if (policy.get("review_task_schema") != _REVIEW_TASK_SCHEMA
            or policy.get("review_schema") != _AI_REVIEW_SCHEMA):
        raise SystemExit("Program First + AI Review acceptance BLOCKED: solve "
                         "uses an obsolete proof schema; start a fresh run")
    acc_p = run_p / _ACCEPTANCE_REPORT
    if not acc_p.is_file():
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         "no acceptance report; "
                         "run --resume after completing needs_ai_review.jsonl")
    try:
        acceptance = _strict_json_loads(acc_p.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         f"unreadable {acc_p}: {exc}")
    if (acceptance.get("schema") != _ACCEPTANCE_SCHEMA
            or acceptance.get("status") != "COMPLETE"):
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         "acceptance status is "
                         f"{acceptance.get('status', 'INVALID')}, not COMPLETE")

    tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
    expected = [str(r.get("id")) for r in solve.get("results") or []]
    by_id = {str(t.get("id")): t for t in tasks}
    if len(by_id) != len(tasks) or sorted(by_id) != sorted(expected):
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         "review worklist ids do "
                         "not exactly match solve_report results")
    accepted_ids = [str(pid) for pid in acceptance.get("accepted_ids") or []]
    if (sorted(accepted_ids) != sorted(expected)
            or acceptance.get("accepted") != len(expected)
            or acceptance.get("total") != len(expected)):
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         "COMPLETE report does "
                         "not account for every solve_report result")
    failures = []
    for pid in expected:
        task = by_id[pid]
        verdict = _validate_ai_review(task)
        if verdict["status"] != "ACCEPTED":
            failures.append(f"{pid}: " + "; ".join(verdict["reasons"]))
            continue
        response = Path(str(task.get("response_path") or ""))
        try:
            payload = _strict_json_loads(response.read_text(errors="replace"))
        except (OSError, ValueError) as exc:
            failures.append(f"{pid}: accepted response unreadable: {exc}")
            continue
        if _sha256_text(str(payload.get("completion") or "")) != task.get("rtl_sha256"):
            failures.append(f"{pid}: response bytes do not match reviewed RTL")
    if failures:
        raise SystemExit("Program First + AI Review acceptance BLOCKED:\n  "
                         + "\n  ".join(failures))


def _shape_c_task_binding_reasons(task: dict, run_p: Path,
                                  solve_result: dict | None) -> list[str]:
    """Bind a Shape-C review task back to its runner-owned run evidence.

    This is BLOCKING: any returned reason prevents scorer export.
    """
    import emit_attestation as emit_attestation          # noqa: PLC0415

    run_p = Path(run_p).resolve()
    pid = str(task.get("id") or "")
    safe = _safe_problem_id(pid)
    reasons: list[str] = []
    expected_project = (run_p / "projects" / safe).resolve()
    project = Path(str(task.get("project") or "")).resolve()
    if project != expected_project:
        reasons.append("project is not the runner-owned project for this id")
    expected_prompt = expected_project / "input" / "phase1_prompt.md"
    if Path(str(task.get("prompt_path") or "")).resolve() != expected_prompt:
        reasons.append("prompt path is not inside the runner-owned project")
    expected_response = (run_p / "responses" / f"{safe}.json").resolve()
    if Path(str(task.get("response_path") or "")).resolve() != expected_response:
        reasons.append("response path is not the runner-owned response path")
    review_root = (run_p / "ai_reviews" / safe).resolve()
    try:
        Path(str(task.get("review_path") or "")).resolve().relative_to(review_root)
    except ValueError:
        reasons.append("review path escapes the runner-owned review directory")

    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        reasons.append("candidate snapshot record is malformed")
        candidate = {}
    candidate_root = (run_p / "candidate_snapshots" / safe).resolve()
    candidate_paths = [Path(str(p)).resolve() for p in
                       candidate.get("rtl_paths") or []]
    for path in candidate_paths + [
            Path(str(candidate.get("completion_path") or "")).resolve(),
            Path(str(candidate.get("response_payload_path") or "")).resolve(),
            Path(str(candidate.get("manifest_path") or "")).resolve()]:
        try:
            path.relative_to(candidate_root)
        except ValueError:
            reasons.append("candidate evidence escapes its runner-owned snapshot")
            break

    expected_phase1 = task.get("phase1_provenance")
    current_phase1 = emit_attestation.phase1_provenance(expected_project)
    if (not isinstance(expected_phase1, dict)
            or expected_phase1.get("ran") is not True):
        reasons.append("task lacks hash-bound Phase-1 provenance")
    elif current_phase1 != expected_phase1:
        reasons.append("Phase-1 L-doc provenance changed after task creation")

    if not isinstance(solve_result, dict):
        reasons.append("problem is absent from solve_report")
        return reasons
    invocation_reason = _runner_reentry_reason(task, solve_result)
    if invocation_reason:
        reasons.append(invocation_reason)
    if (solve_result.get("ok") is not True
            or solve_result.get("candidate_ready") is not True):
        reasons.append("solve_report did not mark a runner-owned candidate ready")
    if solve_result.get("accepted") is not True:
        reasons.append("solve_report did not mark this candidate accepted")
    if str(solve_result.get("candidate_origin")) != str(
            task.get("candidate_origin")):
        reasons.append("candidate origin differs from solve_report")
    if Path(str(solve_result.get("review_task") or "")).resolve() != Path(
            str(task.get("review_path") or "")).resolve():
        reasons.append("review task path differs from solve_report")

    verification = task.get("program_verification")
    if not isinstance(verification, dict):
        reasons.append("Program verification record is malformed")
        verification = {}
    if verification.get("actor") != "vibe_ic_one_shot_runner":
        reasons.append("Program verification actor is not the canonical runner")
    task_rc = verification.get("runner_rc")
    result_rc = solve_result.get("rc")
    if type(task_rc) is not int or type(result_rc) is not int:
        reasons.append(
            "runner rc is absent or not an integer in task or solve_report")
    elif task_rc != result_rc:
        reasons.append("runner rc differs from solve_report")
    phases = solve_result.get("phases")
    if not isinstance(phases, dict):
        reasons.append("solve_report phases record is malformed")
        phases = {}
    phase3 = phases.get("phase3_verifying")
    if not isinstance(phase3, dict):
        reasons.append("solve_report verifying phase is malformed")
        phase3 = {}
    ran = phase3.get("ran")
    if not isinstance(ran, dict):
        reasons.append("solve_report Program gate record is malformed")
        ran = {}
    recorded_rtl_gen = ran.get("rtl_gen")
    # A supplied-RTL re-entry does not *run* the upstream owner; attribution
    # correctly records it under not_attempted as NOT_APPLICABLE. Looking
    # only in ``ran`` made every repaired/backup candidate fail export even
    # though the task and solve report carried the same honest gate status.
    if recorded_rtl_gen is None:
        not_attempted = phase3.get("not_attempted")
        if not isinstance(not_attempted, dict):
            reasons.append("solve_report skipped Program gate record is malformed")
            not_attempted = {}
        recorded_rtl_gen = not_attempted.get("rtl_gen")
    if verification.get("rtl_gen") != recorded_rtl_gen:
        reasons.append("RTL-owning Program gate differs from solve_report")
    # R-0915-85 — `SKIPPED-BY-ENTRY` is `NOT_APPLICABLE`. Dead as the old
    # word, this set refused every supplied-RTL export at the second door.
    if recorded_rtl_gen not in {_V.Verdict.PASS.value,
                                _V.Verdict.NOT_APPLICABLE.value}:
        reasons.append("RTL-owning Program gate did not pass its allowed status")
    # #2216 — the RTL-OWNING gate is one gate, not the ledger. Export is the
    # second door onto the same claim as the resume accept path, so it asks the
    # same question: did any REQUIRED IN-SCOPE gate report a failure on these
    # bytes. Out-of-exit and unplaceable gates are recorded and never block.
    ledger = _required_gate_ledger(solve_result)
    reasons.extend(_gate_evidence_freshness_reasons(
        expected_project, solve_result))
    for name in ledger.get("failed_required") or []:
        reasons.append(
            f"required in-scope PROGRAM gate {name} reported "
            f"{(ledger.get('in_scope') or {}).get(name)}")
    return reasons


def _record_export_guard_notes(run_p: Path, solve: dict,
                               notes_by_id: dict[str, list[str]]) -> None:
    """Persist non-blocking export uncertainty beside each accepted result."""
    results = solve.get("results")
    if (not isinstance(results, list)
            or any(not isinstance(row, dict) for row in results)):
        raise SystemExit("accepted sample export BLOCKED: solve_report results "
                         "are malformed")
    result_ids = [str(row.get("id")) for row in results]
    if (len(set(result_ids)) != len(result_ids)
            or sorted(result_ids) != sorted(notes_by_id)):
        raise SystemExit("accepted sample export BLOCKED: export guard notes "
                         "do not exactly account for solve_report results")
    for row in results:
        row["export_guard_notes"] = list(notes_by_id[str(row.get("id"))])
    _atomic_write_json(Path(run_p) / "solve_report.json", solve)


def _export_accepted_shape_c_task(task: dict, samples: Path,
                                  top_module: str, *, run_p: Path,
                                  solve_result: dict | None) -> dict:
    """BLOCKING Shape-C sole emit for one accepted, frozen runner candidate.

    This is deliberately downstream of ``_require_program_first_ai_acceptance``:
    it never authors RTL.  It re-validates the hash-bound AI review, immutable
    candidate snapshot, Phase-1 provenance, RTL-owning Program gate,
    scorer-facing top, standalone compile, and prompt-derived export guards
    before atomically publishing the exact reviewed bytes.  The broader runner
    rc remains type-checked, cross-record bound, and disclosed in solve_report;
    it is not a functional VerilogEval score gate because unrelated SDC,
    physical, or full-design audit failures do not invalidate reviewed RTL.
    Any unavailable required proof is a named BLOCKED result; it is never an
    advisory and never a silent skip.
    """
    import emit_attestation as emit_attestation          # noqa: PLC0415
    import shape_b_sample_export as guarded_export       # noqa: PLC0415

    pid = str(task.get("id") or "")
    safe = _safe_problem_id(pid)
    reasons: list[str] = _shape_c_task_binding_reasons(
        task, run_p, solve_result)
    if not pid or safe != pid or "/" in pid or "\\" in pid:
        reasons.append("problem id is absent or unsafe for a sample filename")
    verdict = _validate_ai_review(task)
    if verdict.get("status") != "ACCEPTED":
        reasons.append("hash-bound blind AI review is not ACCEPTED")
        reasons.extend(str(v) for v in verdict.get("reasons") or [])

    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        candidate = {}
    reasons.extend(_validate_candidate_snapshot(candidate, pid))
    paths = [Path(str(p)) for p in candidate.get("rtl_paths") or []]
    try:
        rtl_text = _candidate_text(paths) if paths else ""
    except OSError as exc:
        rtl_text = ""
        reasons.append(f"candidate RTL is unreadable: {exc}")
    if _sha256_text(rtl_text) != task.get("rtl_sha256"):
        reasons.append("candidate RTL bytes do not match the reviewed hash")
    if top_module not in guarded_export._module_names(rtl_text):
        reasons.append(f"scorer-facing top module {top_module!r} is absent")

    prompt = Path(str(task.get("prompt_path") or ""))
    try:
        prompt_text = prompt.read_text(errors="replace")
    except OSError as exc:
        prompt_text = ""
        reasons.append(f"staged prompt is unreadable: {exc}")
    if _sha256_text(prompt_text) != task.get("prompt_sha256"):
        reasons.append("staged prompt bytes do not match the reviewed hash")

    project = Path(str(task.get("project") or ""))
    provenance = emit_attestation.phase1_provenance(project)
    if provenance.get("ran") is not True:
        reasons.append("Phase-1 L-doc provenance is absent")
    if shutil.which("iverilog") is None:
        reasons.append("standalone compile capability is unavailable")
    if reasons:
        return {"verdict": "BLOCKED", "id": pid, "reasons": reasons,
                "exported": None}

    samples.mkdir(parents=True, exist_ok=True)
    destination = samples / f"{pid}_sample01.sv"
    temporary = samples / f".{pid}_sample01.sv.pending"
    try:
        temporary.write_text(rtl_text)
        guard_ok, guard_detail = guarded_export.guard_export(
            temporary, prompt_text)
        if not guard_ok:
            return {"verdict": "BLOCKED", "id": pid,
                    "reasons": [str(v) for v in guard_detail],
                    "exported": None}
        temporary.replace(destination)
        try:
            emit_attestation.record(
                samples, destination,
                gates=["vibe_ic_one_shot_runner", "program_first_ai_review",
                       "shape_c_guard_export"],
                shape="C", phase1=provenance)
            records = emit_attestation._load(samples)
            record = records.get(destination.name) or {}
            attestation_matches = (
                record.get("sha256")
                == emit_attestation.sha256_file(destination)
                and record.get("shape") == "C"
                and (record.get("phase1") or {}).get("ran") is True
            )
        except (OSError, ValueError, TypeError) as exc:
            destination.unlink(missing_ok=True)
            return {"verdict": "BLOCKED", "id": pid,
                    "reasons": [f"Shape-C emit attestation failed: {exc}"],
                    "exported": None}
        if not attestation_matches:
            destination.unlink(missing_ok=True)
            return {"verdict": "BLOCKED", "id": pid,
                    "reasons": ["Shape-C emit attestation was not recorded"],
                    "exported": None}
    finally:
        temporary.unlink(missing_ok=True)
    guard_notes = [str(value) for value in guard_detail
                   if str(value).startswith("NOTE:")]
    return {"verdict": "PASS", "id": pid,
            "rtl_sha256": task.get("rtl_sha256"),
            "exported": str(destination),
            "guard_notes": guard_notes,
            "gates": ["vibe_ic_one_shot_runner",
                      "program_first_ai_review", "shape_c_guard_export"]}


def _export_accepted_shape_c_samples(bench: str, run_p: Path) -> None:
    """Export accepted frozen Shape-C candidates through their sole emit.

    Program First deliberately publishes hash-bound response payloads only
    after AI acceptance.  The scorer, however, consumes ``samples/`` carrying
    emit attestations.  Bridge those two contracts here, after blindness and
    acceptance gates but before the scorer. Shape C publishes the exact reviewed
        bytes only after the blocking RTL-gate/review/provenance/top/compile/export
        guard above. Broader runner failures stay visible in solve_report without
        being relabelled PASS. Shape B remains in its byte-identical historical
        function below.
    """
    entry = _entry(bench)
    shape = entry.get("shape")
    if shape != "C":
        return
    if shape == "C":
        import emit_attestation as emit_attestation      # noqa: PLC0415

        run_p = Path(run_p).resolve()
        strategy = (entry.get("layout") or {}).get("module_name_strategy")
        if strategy != "always_TopModule":
            raise SystemExit("accepted Shape-C sample export BLOCKED: module "
                             f"name strategy {strategy!r} is unsupported")
        try:
            tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
            solve = _strict_json_loads(
                (run_p / "solve_report.json").read_text(errors="replace"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(
                f"accepted Shape-C sample export setup failed: {exc}") from exc
        if not tasks:
            raise SystemExit("accepted Shape-C sample export BLOCKED: review "
                             "worklist is empty")
        if not isinstance(solve, dict):
            raise SystemExit("accepted Shape-C sample export BLOCKED: "
                             "solve_report root is not an object")
        solve_results = solve.get("results") or []
        if (not isinstance(solve_results, list)
                or any(not isinstance(row, dict) for row in solve_results)):
            raise SystemExit("accepted Shape-C sample export BLOCKED: "
                             "solve_report results are malformed")
        solve_by_id = {str(row.get("id")): row for row in solve_results}
        task_ids = [str(task.get("id")) for task in tasks]
        if (len(solve_by_id) != len(solve_results)
                or len(set(task_ids)) != len(task_ids)
                or sorted(task_ids) != sorted(solve_by_id)):
            raise SystemExit("accepted Shape-C sample export BLOCKED: review "
                             "worklist does not exactly match solve_report")

        failures = []
        guard_notes_by_id: dict[str, list[str]] = {}
        # Validate and emit every task into a private transaction first. A
        # failure in task N must not leave task 1..N-1 visible to the scorer.
        with tempfile.TemporaryDirectory(
                prefix=".shape-c-export-", dir=run_p) as transaction:
            staged_samples = Path(transaction) / "samples"
            for task in tasks:
                pid = str(task.get("id"))
                result = _export_accepted_shape_c_task(
                    task, staged_samples, "TopModule", run_p=run_p,
                    solve_result=solve_by_id.get(pid))
                if result.get("verdict") != "PASS":
                    failures.append(
                        f"{pid}: " + "; ".join(
                            str(v) for v in result.get("reasons") or []))
                else:
                    guard_notes_by_id[pid] = [
                        str(value) for value in result.get("guard_notes") or []]
            if failures:
                raise SystemExit("accepted Shape-C sample export BLOCKED:\n  "
                                 + "\n  ".join(failures))

            samples = run_p / "samples"
            expected_names = {f"{pid}_sample01.sv" for pid in task_ids}
            existing_names = ({p.name for p in samples.iterdir()
                               if p.is_file() and p.suffix in {".sv", ".v"}
                               and not p.name.startswith(".")}
                              if samples.is_dir() else set())
            if existing_names:
                records = emit_attestation._load(samples)
                existing_ok = existing_names == expected_names
                for task in tasks:
                    pid = str(task.get("id"))
                    destination = samples / f"{pid}_sample01.sv"
                    record = records.get(destination.name) or {}
                    if (not destination.is_file()
                            or emit_attestation.sha256_file(destination)
                            != task.get("rtl_sha256")
                            or record.get("sha256") != task.get("rtl_sha256")
                            or record.get("shape") != "C"
                            or record.get("phase1")
                            != task.get("phase1_provenance")):
                        existing_ok = False
                if not existing_ok:
                    raise SystemExit(
                        "accepted Shape-C sample export BLOCKED: samples/ "
                        "contains stale, partial, or foreign scoring artifacts")
                print(f"Program First Shape-C export: {len(tasks)}/{len(tasks)} "
                      "already carries exact accepted, attested samples")
                _record_export_guard_notes(
                    run_p, solve, guard_notes_by_id)
                return

            samples.mkdir(parents=True, exist_ok=True)
            published: list[Path] = []
            try:
                for task in tasks:
                    pid = str(task.get("id"))
                    staged = staged_samples / f"{pid}_sample01.sv"
                    destination = samples / staged.name
                    staged.replace(destination)
                    published.append(destination)
                    emit_attestation.record(
                        samples, destination,
                        gates=["vibe_ic_one_shot_runner",
                               "program_first_ai_review",
                               "shape_c_guard_export"],
                        shape="C", phase1=task.get("phase1_provenance"))
                records = emit_attestation._load(samples)
                for task, destination in zip(tasks, published):
                    record = records.get(destination.name) or {}
                    if (record.get("sha256") != task.get("rtl_sha256")
                            or record.get("shape") != "C"
                            or record.get("phase1")
                            != task.get("phase1_provenance")):
                        raise ValueError(
                            f"attestation read-back mismatch for {task.get('id')}")
            except (OSError, ValueError, TypeError) as exc:
                for destination in published:
                    destination.unlink(missing_ok=True)
                raise SystemExit(
                    "accepted Shape-C sample export BLOCKED: transactional "
                    f"publish failed: {exc}") from exc
        _record_export_guard_notes(run_p, solve, guard_notes_by_id)
        print(f"Program First Shape-C export: {len(tasks)}/{len(tasks)} "
              f"accepted frozen candidate(s) passed blocking sole emit -> "
              f"{run_p / 'samples'}")
        return


def _export_accepted_shape_b_samples(bench: str, dataset: Path,
                                     run_p: Path) -> None:
    """Export accepted frozen candidates through Shape B's sole emit path.

    Program First deliberately publishes hash-bound response payloads only
    after AI acceptance.  The scorer, however, consumes ``samples/`` carrying
    emit attestations.  Bridge those two contracts here, after blindness and
    acceptance gates but before the scorer: export the immutable reviewed RTL,
    never a mutable working copy, through ``shape_b_sample_export``.
    """
    if _entry(bench).get("shape") != "B":
        return
    import benchmark_io_adapter as bio                    # noqa: PLC0415
    import shape_b_sample_export as sample_export          # noqa: PLC0415

    fmt = _BENCH_FORMAT.get(bench)
    if fmt is None:
        raise SystemExit(f"no IO adapter bound for {bench!r}")
    dataset = Path(dataset).resolve()
    try:
        problems = {str(row["id"]): row
                    for row in bio.problems(fmt, dataset)}
        tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
        solve_p = run_p / "solve_report.json"
        solve = (_strict_json_loads(solve_p.read_text(errors="replace"))
                 if solve_p.is_file() else None)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"accepted sample export setup failed: {exc}") from exc

    if solve is not None and not isinstance(solve, dict):
        raise SystemExit("accepted Shape-B sample export BLOCKED: solve_report "
                         "root is not an object")
    if solve is not None:
        solve_results = solve.get("results")
        if (not isinstance(solve_results, list)
                or any(not isinstance(row, dict) for row in solve_results)):
            raise SystemExit("accepted Shape-B sample export BLOCKED: "
                             "solve_report results are malformed")
        task_ids = [str(task.get("id")) for task in tasks]
        solve_ids = [str(row.get("id")) for row in solve_results]
        if (len(set(task_ids)) != len(task_ids)
                or len(set(solve_ids)) != len(solve_ids)
                or sorted(task_ids) != sorted(solve_ids)):
            raise SystemExit("accepted Shape-B sample export BLOCKED: review "
                             "worklist does not exactly match solve_report")

    failures = []
    guard_notes_by_id: dict[str, list[str]] = {}
    samples = run_p / "samples"
    for task in tasks:
        pid = str(task.get("id"))
        candidate = task.get("candidate_snapshot") or {}
        paths = [Path(str(p)) for p in candidate.get("rtl_paths") or []]
        if not paths or len({p.parent.resolve() for p in paths}) != 1:
            failures.append(f"{pid}: frozen RTL is absent or spans directories")
            continue
        problem = problems.get(pid)
        if problem is None:
            failures.append(f"{pid}: no dataset input record")
            continue
        problem_root = Path(str(problem.get("root") or "")).resolve()
        try:
            design = str(problem_root.relative_to(dataset))
        except ValueError:
            failures.append(f"{pid}: dataset problem root escapes dataset")
            continue
        result = sample_export.export(
            paths[0].parent, pid, samples,
            dataset=dataset, design=design,
            prompt=Path(str(task.get("prompt_path") or "")),
            project=Path(str(task.get("project") or "")))
        if result.get("verdict") != "PASS":
            failures.append(
                f"{pid}: {result.get('reason') or 'emit rejected'}: "
                f"{result.get('note') or result.get('block_reason') or ''}")
        else:
            guard_notes_by_id[pid] = [
                str(value) for value in result.get("guard_notes") or []]
    if failures:
        raise SystemExit("accepted Shape-B sample export BLOCKED:\n  "
                         + "\n  ".join(failures))
    if solve is not None:
        _record_export_guard_notes(run_p, solve, guard_notes_by_id)
    elif any(guard_notes_by_id.values()):
        print("Program First export guard notes (solve_report unavailable): "
              + json.dumps(guard_notes_by_id, sort_keys=True))
    print(f"Program First export: {len(tasks)}/{len(tasks)} accepted frozen "
          f"candidate(s) passed Shape-B emit -> {samples}")


def _export_accepted_cvdp_responses(bench: str, dataset: Path,
                                    run_p: Path) -> Path:
    """Publish exact accepted candidates in CVDP's scorer envelope.

    This is a post-acceptance I/O translation, not an authoring gate. Routing,
    RTL generation, review, repair, and verification have already happened in
    the general flow. The adapter may read scorer-visible output path KEYS at
    this host-only boundary, but never reference values.
    """
    if _BENCH_FORMAT.get(bench) != "cvdp":
        raise SystemExit(f"{bench!r} is not bound to the CVDP I/O adapter")
    import benchmark_io_adapter as bio                    # noqa: PLC0415
    import rtl_final_bundle_integrity as bundle_integrity  # noqa: PLC0415

    run_p = Path(run_p).resolve()
    dataset = Path(dataset).resolve()
    try:
        tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
        solve = _strict_json_loads(
            (run_p / "solve_report.json").read_text(errors="replace"))
        contracts = bio.cvdp_scorer_contracts(dataset)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"accepted CVDP response export setup failed: {exc}") from exc
    results = solve.get("results") if isinstance(solve, dict) else None
    if (not isinstance(results, list)
            or any(not isinstance(row, dict) for row in results)):
        raise SystemExit(
            "accepted CVDP response export BLOCKED: solve_report is malformed")
    solve_by_id = {str(row.get("id")): row for row in results}
    task_by_id = {str(task.get("id")): task for task in tasks}
    ordered_ids = [str(row.get("id")) for row in results]
    if (len(solve_by_id) != len(results)
            or len(task_by_id) != len(tasks)
            or sorted(task_by_id) != sorted(solve_by_id)):
        raise SystemExit(
            "accepted CVDP response export BLOCKED: review worklist does not "
            "exactly match solve_report")

    rows, evidence, failures = [], [], []
    for pid in ordered_ids:
        task = task_by_id[pid]
        result = solve_by_id[pid]
        reasons = _shape_c_task_binding_reasons(task, run_p, result)
        verdict = _validate_ai_review(task)
        if verdict.get("status") != "ACCEPTED":
            reasons.append("hash-bound blind AI review is not ACCEPTED")
            reasons.extend(str(v) for v in verdict.get("reasons") or [])
        candidate = task.get("candidate_snapshot")
        if not isinstance(candidate, dict):
            candidate = {}
        reasons.extend(_validate_candidate_snapshot(candidate, pid))
        response_paths = contracts.get(pid) or []
        if not response_paths:
            reasons.append("official scorer response-path contract is absent")
        completion = ""
        bundle_gate = None
        if not reasons:
            try:
                completion = bio.cvdp_package_response(
                    [Path(str(p)) for p in candidate.get("rtl_paths") or []],
                    [Path(str(p)) for p in
                     candidate.get("source_rtl_paths") or []],
                    response_paths)
            except (OSError, ValueError, TypeError) as exc:
                reasons.append(str(exc))
        if not reasons:
            final_files = bio.cvdp_response_file_map(
                completion, response_paths)
            bundle_gate = bundle_integrity.check_final_bundle(
                [Path(str(p)) for p in candidate.get("rtl_paths") or []],
                final_files)
            bundle_report_path = (run_p / "reports" /
                                  "final_bundle_integrity" /
                                  f"{_safe_problem_id(pid)}.json")
            _atomic_write_json(bundle_report_path, bundle_gate)
            if bundle_gate.get("status") != "PASS":
                detail = "; ".join(
                    str(value) for value in bundle_gate.get("reasons") or [])
                if not detail:
                    detail = str(
                        (bundle_gate.get("compile") or {}).get("reason")
                        or "no compile evidence")
                reasons.append(
                    "general final RTL bundle integrity is "
                    f"{bundle_gate.get('status')}: "
                    f"{detail}")
        if reasons:
            failures.append(f"{pid}: " + "; ".join(reasons))
            continue
        rows.append({"id": pid, "completion": completion})
        evidence.append({
            "id": pid,
            "candidate_rtl_sha256": task.get("rtl_sha256"),
            "scorer_completion_sha256": _sha256_text(completion),
            "response_paths": response_paths,
            "final_bundle_integrity": {
                "status": bundle_gate.get("status"),
                "report": str(bundle_report_path),
                "report_sha256": _sha256_text(
                    bundle_report_path.read_text(errors="replace")),
            },
            "gates": ["vibe_ic_one_shot_runner",
                      "program_first_ai_review",
                      "cvdp_thin_io_package",
                      "rtl_final_bundle_integrity"],
        })
    if failures:
        raise SystemExit("accepted CVDP response export BLOCKED:\n  "
                         + "\n  ".join(failures))

    response_path = run_p / "responses" / "accepted_cvdp.jsonl"
    temp_path = response_path.with_name(
        f".{response_path.name}.{os.getpid()}.pending")
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_jsonl(temp_path, rows)
        temp_path.replace(response_path)
    finally:
        temp_path.unlink(missing_ok=True)
    report = {
        "schema": "vibeic.benchmark.cvdp_response_export.v1",
        "verdict": "PASS",
        "bench": bench,
        "dataset": str(dataset),
        "count": len(rows),
        "response_jsonl": str(response_path),
        "records": evidence,
    }
    _atomic_write_json(run_p / "reports" / "cvdp_response_export.json", report)
    print(f"Program First CVDP export: {len(rows)}/{len(rows)} accepted "
          f"candidate(s) packaged by the thin I/O adapter -> {response_path}")
    return response_path


def cmd_score(bench: str, run: str, dataset: str | None,
              allow_ungated: bool = False, allow_direct_agent: bool = False,
              capture_golden: bool = False, ai_model: str | None = None,
              golden_db: str | None = None,
              scorer_root: str | None = None, threads: int = 4):
    e = _entry(bench)
    if _dispatch_format(bench, Path(run).resolve()) == "agentic":
        raise SystemExit("SHAPED_SCORE_REFUSED: Shape D requires its official "
                         "coordinator-side scorer after general AI acceptance; "
                         "the nonagentic scorer cannot consume this protocol")
    if bench not in _BENCH_FORMAT:
        raise SystemExit(
            f"--score has no general I/O binding for {bench!r}. "
            f"Shape {e['shape']} uses benchmark-verify or its documented "
            "external scorer.")
    run_p = Path(run).resolve()
    config_path = run_p / ".bench_config.json"
    try:
        config = _strict_json_loads(config_path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        raise SystemExit(
            "canonical scoring requires the clean-room metadata written by "
            f"--solve: {config_path}: {exc}") from exc
    if (config.get("schema") != "vibeic.benchmark.general_run.v1"
            or config.get("bench") != bench
            or config.get("full_dataset") is not True):
        raise SystemExit(
            "canonical scoring requires a full-dataset general --solve run; "
            "partial, separate-scaffold, or benchmark-local runs are not eligible")
    _require_program_first_ai_acceptance(run_p)
    # Front-door Vibe-IC entry gate (owner directive 2026-06-28): refuse to
    # score a run that did not enter through the Vibe-IC plugin.  Direct-agent
    # authoring / patching followed by a host-scorer invocation measures
    # "Opus + MCP-EDA", not Vibe-IC.
    entry_guard = Path(__file__).resolve().parent / "vibe_ic_entry_guard.py"
    if entry_guard.is_file() and not allow_direct_agent:
        rc = subprocess.call([sys.executable, str(entry_guard), str(run_p),
                              "--strict"])
        if rc != 0:
            raise SystemExit(
                "Vibe-IC entry guard FAILed — this run lacks evidence of "
                "passing through vibe_ic_one_shot_runner.py / phase1. "
                "Run the benchmark through the Vibe-IC plugin; direct-agent "
                "authoring/patching cannot be scored as canonical. "
                "Pass --allow-direct-agent only for a disclosed NON-CANONICAL "
                "exploratory run.")
    # Front-door clean-room gate (ORGANIC-20260604): refuse to score a run that
    # inherited prior samples / scores / memory. The published pass@1 must come
    # from a clean-room run ('一定是重跑', user directive 2026-06-04).
    guard = Path(__file__).resolve().parent / "benchmark_clean_room_check.py"
    if guard.is_file():
        rc = subprocess.call([sys.executable, str(guard), str(run_p)])
        if rc != 0:
            raise SystemExit("clean-room guard FAILed — this run inherited prior "
                             "samples/scores and CANNOT be scored as canonical. "
                             "Re-run clean-room into a fresh dir.")
    if dataset:
        ds_p = Path(dataset).resolve()
    else:
        ds_p = Path(str(config.get("dataset") or "")).resolve()
    if ds_p != Path(str(config.get("dataset") or "")).resolve():
        raise SystemExit(
            f"dataset mismatch: --solve pinned {config.get('dataset')}, "
            f"but --score received {ds_p}")
    # Front-door blindness audit (ORGANIC-20260605-blindness-deterministic-
    # audit-guard): when the orchestrator exported batch-agent transcripts to
    # <RUNDIR>/transcripts/, audit them deterministically — any non-prompt
    # dataset access (sibling refs/tests, build files) or agent-side scorer
    # self-run REFUSES scoring. No transcripts exported -> explicit NOTICE
    # (the audit cannot vouch for a run it never saw).
    audit = Path(__file__).resolve().parent / "blindness_audit.py"
    tdir = run_p / "transcripts"
    has_transcripts = tdir.is_dir() and any(tdir.iterdir())
    if audit.is_file() and has_transcripts:
        rc = subprocess.call([sys.executable, str(audit), "--dataset",
                              str(ds_p), "--bench", bench, str(tdir)])
        if rc == 1:
            raise SystemExit(
                "blindness audit FAILed — an agent accessed non-prompt "
                "dataset files or self-ran the host scorer (offending "
                "transcript + path named above). The run is not blind and "
                "CANNOT be scored as canonical; fix the orchestration and "
                "re-run clean-room.")
        # rc == 3 is AUDIT_ERROR (blindness_audit.EXIT_AUDIT_ERROR): the
        # auditor itself crashed (e.g. a malformed transcript line). This is a
        # TOOL failure, NOT a blindness violation — it must NEVER be folded
        # into the FAIL message above (ORGANIC-20260607, #480). Refuse to
        # score (the audit could not vouch for the run) but say so honestly so
        # the host fixes the transcript/auditor rather than the orchestration.
        if rc == 3:
            raise SystemExit(
                "blindness audit could NOT complete (AUDIT_ERROR) — the "
                "auditor hit an internal error while scanning the transcripts "
                "(see message above); this is a tool failure, NOT a blindness "
                "violation. The run is NOT blindness-verified, so it cannot be "
                "scored as canonical yet; fix the transcript/auditor and re-run "
                "the audit. (Do not treat this as 'agent accessed dataset "
                "files'.)")
    elif audit.is_file():
        print("NOTICE: <RUNDIR>/transcripts/ not present or empty — blindness "
              "audit skipped. Export is the orchestration DEFAULT (--solve "
              "pre-creates the dir; copy every agent transcript there). A run "
              "scored on this branch MUST disclose 'blindness audit "
              "unavailable' in its RESULT.md (ORGANIC-20260605-transcripts-"
              "export-default).")
    if _BENCH_FORMAT[bench] == "cvdp":
        if capture_golden:
            raise SystemExit(
                "--capture-golden is not implemented for CVDP's official "
                "cocotb result schema; refusing to imply that it was captured")
        responses = _export_accepted_cvdp_responses(
            bench, ds_p, run_p)
        scorer = HARNESS / "score_cvdp_open.py"
        cmd = [sys.executable, str(scorer),
               "--dataset", str(ds_p),
               "--responses", str(responses),
               "--run", str(run_p),
               "--threads", str(max(1, int(threads)))]
        if scorer_root:
            cmd += ["--scorer-root", str(Path(scorer_root).resolve())]
        print("$ " + " ".join(cmd))
        sys.exit(subprocess.call(cmd))
    if e["shape"] == "C":
        _export_accepted_shape_c_samples(bench, run_p)
    else:
        _export_accepted_shape_b_samples(bench, ds_p, run_p)
    # Front-door GATE-AS-SOLE-EMIT-PATH guard: every scoreable sample MUST carry a
    # valid emit-path attestation (gates_atomic / shape_b_sample_export wrote it on a
    # clean emit). A sample authored directly into samples/ — bypassing the emit gates
    # + port-reorder — has none, so the number would measure the raw author, not the
    # runner (and silently undercount emit-gate-recoverable designs). HARD-BLOCK by
    # default, exactly like the clean-room + blindness guards; --allow-ungated opts an
    # exploratory direct-author run out (its RESULT.md MUST then disclose NON-CANONICAL).
    emit_chk = Path(__file__).resolve().parent / "emit_attestation_check.py"
    if emit_chk.is_file():
        rc = subprocess.call([sys.executable, str(emit_chk), "--samples",
                              str(run_p / "samples")] + ([] if allow_ungated else ["--strict"]))
        if rc != 0 and not allow_ungated:
            raise SystemExit(
                "emit-attestation guard FAILed — one or more samples were NOT produced "
                "by the general runner's accepted emit path "
                "(shape_c_guard_export / shape_b_sample_export), "
                "so the emit gates + port-reorder never fired and this run is NON-CANONICAL. "
                "Author into a work dir and emit through the gate (the runner does this "
                "automatically), or pass --allow-ungated for a disclosed exploratory run.")
    if allow_direct_agent:
        print("NOTICE: --allow-direct-agent passed — this run is NON-CANONICAL and "
              "its RESULT.md MUST disclose that it did not enter through the "
              "Vibe-IC runner.")
    scorer = HARNESS / e.get("scorer", "score_iverilog_tb.py")
    cmd = [sys.executable, str(scorer), "--bench", bench, "--dataset", str(ds_p), "--run", str(run_p)]
    print("$ " + " ".join(cmd))
    rc = subprocess.call(cmd)
    if capture_golden:
        if not ai_model:
            raise SystemExit(
                "--capture-golden needs --ai-model: nothing on this host knows "
                "which model authored the samples, and a defaulted tag would "
                "make two incomparable rows look comparable.")
        rep = capture_goldens(run_p, bench, ai_model, db=golden_db)
        if rep.get("why"):
            print(f"golden capture: NOT DONE — {rep['why']}")
        else:
            print(f"golden capture: {rep['captured']} of {rep['passing']} "
                  f"PASSing problem(s) recorded (of {rep['total_scored']} scored) "
                  f"as plugin v{rep['plugin_version']} / {rep['ai_model']} -> "
                  f"{rep['db']}")
            if rep["sample_not_found"]:
                print(f"  NOT captured (no sample on disk): {rep['sample_not_found']}")
    sys.exit(rc)


# ── FORMAT BINDING ───────────────────────────────────────────────────────────
# Which IO adapter reads which benchmark's files. This is the ONLY benchmark
# knowledge the dispatcher holds, and it is a mapping, not a code path.
_BENCH_FORMAT = {
    "verilogeval-v2": "verilogeval",
    "verilogeval-human": "verilogeval",
    "rtllm": "rtllm",
    "cvdp-open": "cvdp",
}


def _dispatch_format(bench: str, run_p: Path | None = None,
                     shape: str | None = None) -> str | None:
    """Select only an I/O protocol; task nature always uses the shared router."""
    selected = "agentic" if shape == "D" else _BENCH_FORMAT.get(bench)
    if shape not in {None, "D"}:
        raise ValueError("unsupported explicit I/O shape")
    if run_p is not None:
        try:
            config = _strict_json_loads((run_p / ".bench_config.json").read_text())
            solve = _strict_json_loads((run_p / "solve_report.json").read_text())
            tasks = _read_jsonl(run_p / _ROUTE_WORKLIST)
            formats = {_issued_route_task_format(task, run_p) for task in tasks}
            if len(formats) != 1:
                raise ValueError("missing or inconsistent issued I/O format")
            bound = formats.pop()
            if (config.get("bench") != bench or solve.get("bench") != bench
                    or config.get("format") != bound
                    or solve.get("format") != bound
                    or bound not in {"agentic", _BENCH_FORMAT.get(bench)}
                    or (shape == "D" and bound != "agentic")):
                raise ValueError("continuation differs from issued I/O format")
            selected = bound
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"IO_FORMAT_BINDING_REFUSED: {exc}") from exc
    return selected


def _shape_d_problems(dataset: Path, run_p: Path) -> list[dict]:
    """BLOCKING blind staging via agentic_jsonl_to_shape_d.py, the sole parser.

    The extraction tree is coordinator/scorer-owned and is outside the run
    and every solver project. Only the extractor's visible work/input files
    cross benchmark_io_adapter.stage; hidden score/ and metadata never do.
    """
    import agentic_jsonl_to_shape_d as shaped             # noqa: PLC0415
    root = run_p.parent / (run_p.name + ".shape_d_scorer")
    if root.exists() or root.is_symlink():
        raise ValueError("SHAPED_INPUT_REFUSED: occupied coordinator extraction root")
    if not dataset.is_dir():
        raise ValueError("SHAPED_INPUT_REFUSED: expected a JSONL dataset directory")
    root.mkdir(mode=0o700)
    stats = shaped.extract_dataset(dataset, root, "*.jsonl")
    if not stats["ids"]:
        raise ValueError("SHAPED_INPUT_REFUSED: no agentic rows recognized")
    _atomic_write_json(root / "manifest.json", {
        "schema": "vibeic.benchmark.shape_d_scorer.v1",
        "extractor": "agentic_jsonl_to_shape_d.py", **stats})
    return [{"id": pid, "root": root / pid} for pid in stats["ids"]]

# ── THE SAME COMPLETENESS ENGINE, PER FORMAT ─────────────────────────────────
# `benchmark_completeness` is the THIN-ADAPTER layer over the ONE general
# engine (`spec_complete_extract.assess_spec`): each benchmark differs only in
# how it states its interface, and the COMPLETE / EXTRACTION_GAP / SPEC_ABSENT
# verdict comes from the same place for all of them and for a plain Phase-1
# doc. It had no caller, so `--solve` recorded rc/ok per problem and NOTHING
# about whether the prompt it was handed could be solved at all — which is the
# FLOOR half of the triage rubric (benchmark-defect / under-spec) that
# open-benchmark-methodology § 4 requires a run to separate out.
#
# A MAPPING, not a code path: a format added to `_BENCH_FORMAT` above and to
# this table is assessed with no further change here. `cvdp` is deliberately
# absent — its interface arrives as a cocotb harness + `.env` TOPLEVEL, which
# `cvdp_complete_extract.extract(record)` reads from the RECORD, not from the
# staged prompt text this loop has in hand.
def _completeness_adapters() -> dict:
    """`{format: assess(prompt) -> spec}`. Imported lazily and never fatally.

    A completeness verdict is DISCLOSURE on the solve report; an import error
    here must not stop a run from solving. It is recorded by name instead of
    swallowed, so `completeness: "UNAVAILABLE: ..."` is distinguishable from a
    real SPEC_ABSENT.
    """
    import benchmark_completeness as _bc                # noqa: PLC0415
    return {"rtllm": _bc.assess_rtllm,
            "verilogeval": _bc.assess_verilogeval}


def _rtl_gen_waive(project: Path) -> dict | None:
    """The runner's rtl_gen WAIVE record, or None.

    Detected from the report the runner writes, not from stdout text: the
    deterministic dispatch declares `extras.fallback_skill` when it hands over,
    and that field is the handover contract.
    """
    rep = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    if not rep.is_file():
        return None
    try:
        d = _strict_json_loads(rep.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    for st in d.get("steps") or []:
        if st.get("name") == "rtl_gen" and st.get("status") == "WAIVED":
            ex = st.get("extras") or {}
            if ex.get("fallback_skill"):
                return {"fallback_skill": ex["fallback_skill"],
                        "detail": st.get("detail", "")}
    return None


def _solver_argv(runner: Path, proj: Path, entry, exit_step,
                 delivery_route: str = "ip") -> list:
    """One problem's runner argv, assembled from the routing verdict.

    Open RTL evaluations deliver IP/module evidence, so explicitly choose the
    IP delivery path at the normal front door. This is independent of task
    nature and leaves conflicting owner declarations for the runner to refuse.

    The exit decides what must NOT run. An RTL-evidence task never needs
    physical design because no RTL consumer reads a netlist or GDS; a run
    whose exit lies before step 15 therefore skips Phase 3 outright.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import task_nature_route as tnr                       # noqa: PLC0415
    if delivery_route not in {"ic", "ip"}:
        raise ValueError(f"invalid delivery runner route: {delivery_route!r}")
    argv = [sys.executable, str(runner), str(proj),
            "--route", delivery_route, "--skip-analog", "--skip-hardware"]
    if exit_step and exit_step in tnr.flow_step_ids():
        order = {s: i for i, s in enumerate(tnr.flow_step_ids())}
        if order.get(exit_step, 99) < order.get("15", 99):
            argv.append("--skip-phase3")
        # --skip-phase3 was the only bit the exit contract used to reach
        # execution, so a lint-evidence exit still dispatched phase-2 synthesis
        # and DFT/LEC. Forward the exit itself; the phase2 runner prunes every
        # dispatch site wholly past it as SKIPPED-BY-EXIT.
        argv += ["--exit-step", str(exit_step)]
    if entry and entry != "D1":
        argv += ["--entry-step", str(entry)]
    return argv


def _resume_solver_argv(runner: Path, proj: Path, supplied_rtl: bool,
                        entry, exit_step, delivery_route: str = "ip") -> list:
    """Re-enter one routed problem without losing its declared exit.

    AI backup/repair supplies RTL, so it resumes at the first RTL-validation
    step.  The routing exit is unchanged: re-entry must not expand a lint or
    behavioural task into synthesis/DFT/LEC work.
    """
    effective_entry = "2" if supplied_rtl else entry
    return _solver_argv(runner, proj, effective_entry, exit_step, delivery_route)


def _ensure_phase1_frontdoor(runner: Path, project: Path, runner_budget,
                             *, force_current: bool = False,
                             route_receipt: dict | None = None,
                             task_sha256: str | None = None,
                             source_sha256: str | None = None,
                             ldoc_root_handle: str | None = None,
                             delivery_route: str = "ip") -> dict:
    """Materialize canonical Phase-1 provenance before a mid-flow entry.

    This prerequisite is BLOCKING: missing or mutable provenance must stop the
    owning loop instead of silently producing a non-canonical benchmark sample.

    Routing still decides the task's owning loop first. A debug/optimization
    task may therefore *solve* from a later step, but it must not bypass the
    one Phase-1 front door that binds its prompt to L-doc provenance. The
    D1-only pass is accepted by its produced provenance rather than the broad
    runner rc: Phase 1 may honestly return nonzero for an outstanding expert
    handoff after it has emitted all hash-bound L-docs.
    """
    import emit_attestation as emit_attestation          # noqa: PLC0415
    import route_decision as rd                          # noqa: PLC0415

    project = Path(project).resolve()
    existing = emit_attestation.phase1_provenance(project)
    if existing.get("ran") is True and not force_current:
        return {"status": "REUSED", "runner_rc": None,
                "provenance": existing}

    prompt = project / "input" / "phase1_prompt.md"
    try:
        prompt_before = _sha256_text(prompt.read_text(errors="replace"))
        rtl_before = _sha256_text(_candidate_text(_rtl_files(project)))
    except OSError as exc:
        return {"status": "BLOCKED", "runner_rc": None,
                "reason": f"front-door input is unreadable: {exc}"}

    argv = _solver_argv(runner, project, "D1", "D1", delivery_route)
    argv.append("--no-dashboard")
    process = runner_budget.run(argv)
    diagnostic = _runner_diagnostics(process, argv, project, require_phase2=False)
    diagnostics = {"runner_diagnostics": diagnostic} if diagnostic else {}
    diagnostics["runner_invocation"] = getattr(process, "invocation", None)
    if diagnostic and diagnostic.get("reason"):
        return {"status": "BLOCKED", "runner_rc": process.rc,
                "reason": diagnostic["reason"], **diagnostics}
    if process.error is not None:
        return {"status": "BLOCKED", "runner_rc": process.rc,
                "reason": process.error, **diagnostics}
    try:
        prompt_after = _sha256_text(prompt.read_text(errors="replace"))
        rtl_after = _sha256_text(_candidate_text(_rtl_files(project)))
    except OSError as exc:
        return {"status": "BLOCKED", "runner_rc": process.rc,
                "reason": f"front-door output is unreadable: {exc}", **diagnostics}
    if prompt_before != prompt_after or rtl_before != rtl_after:
        return {"status": "BLOCKED", "runner_rc": process.rc,
                "reason": "D1-only front door changed the prompt or supplied RTL", **diagnostics}
    provenance = emit_attestation.phase1_provenance(project)
    if provenance.get("ran") is not True:
        return {"status": "BLOCKED", "runner_rc": process.rc,
                "reason": "D1-only front door emitted no hash-bound L-doc provenance", **diagnostics}
    result = {"status": "GENERATED", "runner_rc": process.rc,
              "provenance": provenance, **diagnostics}
    if force_current:
        # The report producer is the authority for D1's typed verdict.  A
        # digest and ``ran: true`` alone describe provenance, not gate success.
        import _path_layout as _pl                    # noqa: PLC0415
        report_path = _pl.report_path(project, "phase1_one_shot.json")
        try:
            report_bytes = report_path.read_bytes()
            report = _strict_json_loads(report_bytes.decode("utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            return {**result, "d1_gate_error": f"D1_GATE_REPORT_UNREADABLE: {exc}"}
        if not isinstance(report, dict) or not isinstance(report.get("verdict"), str):
            return {**result, "d1_gate_error": "D1_GATE_REPORT_SCHEMA_INVALID"}
        binding = report.get("runner_binding")
        invocation_id = str(process.invocation_id or "")
        if (not invocation_id or not isinstance(binding, dict)
                or binding.get("schema") != "vibeic.runner_report_binding.v1"
                or binding.get("invocation_id") != invocation_id
                or binding.get("project") != str(project)
                or binding.get("report_name") != "phase1_one_shot.json"
                or not isinstance(binding.get("argv"), list)
                or any(not isinstance(arg, str) for arg in binding.get("argv"))
                or not isinstance(binding.get("source"), dict)
                or not isinstance(binding.get("producer"), dict)
                or not isinstance(binding.get("material"), dict)):
            return {**result, "d1_gate_error": "D1_GATE_REPORT_NOT_CURRENT_CALL"}
        if source_sha256 is None or task_sha256 is None or ldoc_root_handle is None:
            return {**result, "d1_gate_error": "D1_GATE_BINDING_INPUT_MISSING"}
        result["d1_gate"] = rd.make_d1_gate(
            verdict=str(report.get("verdict") or ""),
            route_receipt=route_receipt or {},
            provenance=provenance,
            source_sha256=source_sha256,
            task_sha256=task_sha256,
            ldoc_root_handle=ldoc_root_handle,
            invocation_id=invocation_id,
            report_sha256=hashlib.sha256(report_bytes).hexdigest(),
            waiver_receipt=(report.get("waiver_receipt")
                            if isinstance(report.get("waiver_receipt"), dict)
                            else None))
    return result


def _receipt_store_path(project: Path, kind: str, digest: str) -> Path:
    """Immutable per-run receipt location; the digest is part of the path."""
    if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
        raise ValueError(f"receipt digest is not canonical: {digest!r}")
    return (Path(project) / "reports" / "orchestrator" / "receipts" /
            str(kind) / f"{digest}.json")


def _receipt_current_pointer(project: Path, kind: str) -> Path:
    """Mutable atomic pointer to the latest immutable receipt of ``kind``."""
    return (Path(project) / "reports" / "orchestrator" / "receipts" /
            f"{kind}.current.json")


_RECEIPT_ENVELOPE_SCHEMA = "vibeic.run_receipt_envelope.v1"
_RECEIPT_POINTER_SCHEMA = "vibeic.current_receipt_pointer.v2"
_RECEIPT_HISTORY_SCHEMA = "vibeic.receipt_history_entry.v1"
_RECEIPT_HISTORY_HEAD_SCHEMA = "vibeic.receipt_history_head.v1"
_RECEIPT_UNSET = object()


def _receipt_sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _write_bound_route_record(path: Path, value: dict) -> None:
    """Publish a route/activation record once; changed bytes are a refusal."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"route record path is linked: {path}")
    if path.is_file():
        current = _strict_json_loads(path.read_text(errors="replace"))
        if current != value:
            raise ValueError(f"route record changed after issue: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, value)


def _receipt_lock_path(project: Path, kind: str) -> Path:
    return (Path(project) / "reports" / "orchestrator" / "receipts" /
            f"{kind}.current.lock")


def _receipt_history_dir(project: Path, kind: str) -> Path:
    return (Path(project) / "reports" / "orchestrator" / "receipts" /
            str(kind) / "history")


def _receipt_history_path(project: Path, kind: str, sequence: int) -> Path:
    if int(sequence) < 1:
        raise ValueError("RECEIPT_HISTORY_SEQUENCE_INVALID")
    return _receipt_history_dir(project, kind) / f"{int(sequence)}.json"


def _receipt_history_head(project: Path, kind: str) -> Path:
    return (Path(project) / "reports" / "orchestrator" / "receipts" /
            f"{kind}.history.head.json")


def _read_json_regular(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"receipt is not a regular file: {path}")
    try:
        value = _strict_json_loads(path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"receipt is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"receipt is not an object: {path}")
    return value


def _read_receipt_history(project: Path, kind: str) -> tuple[dict, list[dict]]:
    """Verify the append-only sequence and every immutable run envelope."""
    head_path = _receipt_history_head(project, kind)
    head = _read_json_regular(head_path)
    if set(head) != {
            "schema", "kind", "sequence", "receipt_digest", "run_id",
            "head_sha256"}:
        raise ValueError("RECEIPT_HISTORY_HEAD_SCHEMA_INVALID")
    if head.get("schema") != _RECEIPT_HISTORY_HEAD_SCHEMA or head.get("kind") != kind:
        raise ValueError("RECEIPT_HISTORY_HEAD_INVALID")
    head_body = {key: head.get(key) for key in (
        "schema", "kind", "sequence", "receipt_digest", "run_id")}
    if head.get("head_sha256") != _receipt_sha256_json(head_body):
        raise ValueError("RECEIPT_HISTORY_HEAD_DIGEST_MISMATCH")
    head_sequence = head.get("sequence")
    if (isinstance(head_sequence, bool) or not isinstance(head_sequence, int)
            or head_sequence < 1):
        raise ValueError("RECEIPT_HISTORY_HEAD_SEQUENCE_INVALID")
    history_dir = _receipt_history_dir(project, kind)
    if history_dir.is_symlink() or not history_dir.is_dir():
        raise ValueError("RECEIPT_HISTORY_MISSING")
    indexed = []
    for path in history_dir.glob("*.json"):
        if path.is_symlink():
            raise ValueError("RECEIPT_HISTORY_LINKED")
        try:
            indexed.append(int(path.stem))
        except ValueError:
            raise ValueError("RECEIPT_HISTORY_FILENAME_INVALID") from None
    if sorted(indexed) != list(range(1, head_sequence + 1)):
        raise ValueError("RECEIPT_HISTORY_SEQUENCE_GAP")
    entries = []
    previous_digest = None
    for sequence in range(1, head_sequence + 1):
        entry_path = _receipt_history_path(project, kind, sequence)
        entry = _read_json_regular(entry_path)
        required = {
            "schema", "kind", "sequence", "run_id", "predecessor_digest",
            "payload_digest_field", "payload_digest", "receipt_digest",
            "history_sha256",
        }
        if set(entry) != required:
            raise ValueError("RECEIPT_HISTORY_ENTRY_SCHEMA_INVALID")
        body = {key: entry.get(key) for key in (
            "schema", "kind", "sequence", "run_id", "predecessor_digest",
            "payload_digest_field", "payload_digest", "receipt_digest")}
        if entry.get("history_sha256") != _receipt_sha256_json(body):
            raise ValueError("RECEIPT_HISTORY_ENTRY_DIGEST_MISMATCH")
        entry_sequence = entry.get("sequence")
        if (entry.get("kind") != kind or isinstance(entry_sequence, bool)
                or not isinstance(entry_sequence, int)
                or entry_sequence != sequence):
            raise ValueError("RECEIPT_HISTORY_ENTRY_SEQUENCE_INVALID")
        if entry.get("predecessor_digest") != previous_digest:
            raise ValueError("RECEIPT_HISTORY_PREDECESSOR_INVALID")
        envelope_path = _receipt_store_path(project, kind, str(entry["receipt_digest"]))
        envelope = _read_json_regular(envelope_path)
        if set(envelope) != {
                "schema", "kind", "run_id", "sequence", "predecessor_digest",
                "payload_digest_field", "payload_digest", "payload"}:
            raise ValueError("RECEIPT_HISTORY_ENVELOPE_SCHEMA_INVALID")
        envelope_body = {key: envelope.get(key) for key in (
            "schema", "kind", "run_id", "sequence", "predecessor_digest",
            "payload_digest_field", "payload_digest", "payload")}
        if _receipt_sha256_json(envelope_body) != entry["receipt_digest"]:
            raise ValueError("RECEIPT_HISTORY_ENVELOPE_DIGEST_MISMATCH")
        for key in ("kind", "run_id", "sequence", "predecessor_digest",
                    "payload_digest_field", "payload_digest"):
            if envelope.get(key) != entry.get(key):
                raise ValueError("RECEIPT_HISTORY_ENVELOPE_BINDING_MISMATCH")
        payload = envelope.get("payload")
        field = envelope.get("payload_digest_field")
        if (not isinstance(payload, dict) or not isinstance(field, str)
                or payload.get(field) != envelope.get("payload_digest")):
            raise ValueError("RECEIPT_HISTORY_PAYLOAD_DIGEST_MISMATCH")
        previous_digest = entry["receipt_digest"]
        entries.append(entry)
    if not entries:
        raise ValueError("RECEIPT_HISTORY_EMPTY")
    if (head.get("sequence") != entries[-1]["sequence"]
            or head.get("receipt_digest") != entries[-1]["receipt_digest"]
            or head.get("run_id") != entries[-1]["run_id"]):
        raise ValueError("RECEIPT_HISTORY_HEAD_CURRENT_MISMATCH")
    return head, entries


def _read_current_receipt(project: Path, kind: str) -> dict:
    """Read and verify the current pointer and its immutable predecessor chain."""
    project = Path(project).resolve()
    pointer_path = _receipt_current_pointer(project, kind)
    pointer = _read_json_regular(pointer_path)
    if set(pointer) != {
            "schema", "kind", "run_id", "sequence", "predecessor_digest",
            "payload_digest_field", "payload_digest", "receipt_digest",
            "receipt_path"}:
        raise ValueError("RECEIPT_CURRENT_POINTER_SCHEMA_INVALID")
    if pointer.get("schema") != _RECEIPT_POINTER_SCHEMA or pointer.get("kind") != kind:
        raise ValueError("RECEIPT_CURRENT_POINTER_INVALID")
    sequence = pointer.get("sequence")
    if (isinstance(sequence, bool) or not isinstance(sequence, int)
            or sequence < 1):
        raise ValueError("RECEIPT_CURRENT_SEQUENCE_INVALID")
    history_head, history_entries = _read_receipt_history(project, kind)
    if (pointer.get("sequence") != history_head.get("sequence")
            or pointer.get("receipt_digest") != history_head.get("receipt_digest")
            or pointer.get("run_id") != history_head.get("run_id")):
        raise ValueError("RECEIPT_CURRENT_HISTORY_MISMATCH")
    receipt_digest = str(pointer.get("receipt_digest") or "")
    immutable = _receipt_store_path(project, kind, receipt_digest)
    if Path(str(pointer.get("receipt_path") or "")).resolve() != immutable.resolve():
        raise ValueError("RECEIPT_CURRENT_PATH_MISMATCH")
    envelope = _read_json_regular(immutable)
    if set(envelope) != {
            "schema", "kind", "run_id", "sequence", "predecessor_digest",
            "payload_digest_field", "payload_digest", "payload"}:
        raise ValueError("RECEIPT_ENVELOPE_SCHEMA_INVALID")
    if envelope.get("schema") != _RECEIPT_ENVELOPE_SCHEMA:
        raise ValueError("RECEIPT_ENVELOPE_INVALID")
    body = {key: envelope.get(key) for key in (
        "schema", "kind", "run_id", "sequence", "predecessor_digest",
        "payload_digest_field", "payload_digest", "payload")}
    if _receipt_sha256_json(body) != receipt_digest:
        raise ValueError("RECEIPT_ENVELOPE_DIGEST_MISMATCH")
    for key in ("kind", "run_id", "sequence", "predecessor_digest",
                "payload_digest_field", "payload_digest"):
        if pointer.get(key) != envelope.get(key):
            raise ValueError(f"RECEIPT_CURRENT_{key.upper()}_MISMATCH")
    if not isinstance(envelope.get("payload"), dict):
        raise ValueError("RECEIPT_PAYLOAD_INVALID")
    payload_field = envelope.get("payload_digest_field")
    if (not isinstance(payload_field, str)
            or envelope["payload"].get(payload_field) != envelope.get("payload_digest")):
        raise ValueError("RECEIPT_PAYLOAD_DIGEST_MISMATCH")

    # A pointer may never be moved back to an older immutable receipt.  The
    # append-only history above is the authority for the maximum sequence; the
    # top-level scan also rejects unindexed newer envelopes.
    store = immutable.parent
    sequences = []
    for candidate in store.glob("*.json"):
        if candidate.is_symlink() or candidate == pointer_path:
            continue
        try:
            item = _read_json_regular(candidate)
        except ValueError:
            continue
        if (item.get("schema") == _RECEIPT_ENVELOPE_SCHEMA
                and item.get("kind") == kind):
            try:
                sequences.append(int(item.get("sequence")))
            except (TypeError, ValueError):
                raise ValueError("RECEIPT_SEQUENCE_INVALID") from None
    if (not sequences or sequence != max(sequences)
            or len(history_entries) != sequence):
        raise ValueError("RECEIPT_CURRENT_POINTER_ROLLBACK")
    predecessor = envelope.get("predecessor_digest")
    if sequence == 1:
        if predecessor is not None:
            raise ValueError("RECEIPT_FIRST_PREDECESSOR_INVALID")
    else:
        if (not isinstance(predecessor, str)
                or not re.fullmatch(r"[0-9a-f]{64}", predecessor)):
            raise ValueError("RECEIPT_PREDECESSOR_INVALID")
        previous = _receipt_store_path(project, kind, predecessor)
        prior = _read_json_regular(previous)
        if prior.get("kind") != kind or int(prior.get("sequence", -1)) != sequence - 1:
            raise ValueError("RECEIPT_PREDECESSOR_CHAIN_INVALID")
    return {"pointer": pointer, "envelope": envelope,
            "receipt": envelope["payload"], "path": immutable}


def _publish_current_receipt(project: Path, kind: str, value: dict,
                             *, digest_field: str, run_id: str | None = None,
                             expected_predecessor_digest: str | None | object = _RECEIPT_UNSET,
                             expected_sequence: int | object = _RECEIPT_UNSET) -> Path:
    """Append one run receipt and CAS-advance its current pointer.

    The semantic payload may repeat across runs, but every immutable envelope
    has a fresh run id, sequence, and predecessor.  A replayed run id or an
    A→B→A pointer update is refused while the pointer remains atomically
    replaceable for a legitimate next invocation.
    """
    project = Path(project).resolve()
    digest = str(value.get(digest_field) or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"receipt digest is not canonical: {digest!r}")
    run_id = str(run_id or uuid.uuid4().hex)
    if not run_id or "/" in run_id or "\\" in run_id:
        raise ValueError("RECEIPT_RUN_ID_INVALID")
    root = _receipt_current_pointer(project, kind).parent
    root.mkdir(parents=True, exist_ok=True)
    lock = _receipt_lock_path(project, kind)
    with lock.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            pointer = _receipt_current_pointer(project, kind)
            current = None
            if pointer.exists():
                current = _read_current_receipt(project, kind)["pointer"]
            current_digest = current.get("receipt_digest") if current else None
            current_sequence = int(current.get("sequence", 0)) if current else 0
            if (expected_predecessor_digest is not _RECEIPT_UNSET
                    and expected_predecessor_digest != current_digest):
                raise ValueError("RECEIPT_PREDECESSOR_COMPARE_FAILED")
            if (expected_sequence is not _RECEIPT_UNSET
                    and int(expected_sequence) != current_sequence):
                raise ValueError("RECEIPT_SEQUENCE_COMPARE_FAILED")
            store = _receipt_store_path(project, kind, digest).parent
            store.mkdir(parents=True, exist_ok=True)
            for candidate in store.glob("*.json"):
                if candidate.is_symlink() or candidate == pointer:
                    continue
                try:
                    prior = _read_json_regular(candidate)
                except ValueError:
                    continue
                if (prior.get("schema") == _RECEIPT_ENVELOPE_SCHEMA
                        and prior.get("kind") == str(kind)
                        and prior.get("run_id") == run_id):
                    raise ValueError("RECEIPT_RUN_ID_REPLAY")
            predecessor = current_digest
            sequence = current_sequence + 1
            envelope_body = {
                "schema": _RECEIPT_ENVELOPE_SCHEMA,
                "kind": str(kind), "run_id": run_id,
                "sequence": sequence, "predecessor_digest": predecessor,
                "payload_digest_field": str(digest_field),
                "payload_digest": digest, "payload": value,
            }
            envelope_digest = _receipt_sha256_json(envelope_body)
            immutable = _receipt_store_path(project, kind, envelope_digest)
            _write_bound_route_record(immutable, envelope_body)
            history_body = {
                "schema": _RECEIPT_HISTORY_SCHEMA, "kind": str(kind),
                "sequence": sequence, "run_id": run_id,
                "predecessor_digest": predecessor,
                "payload_digest_field": str(digest_field),
                "payload_digest": digest, "receipt_digest": envelope_digest,
            }
            history_entry = {**history_body,
                             "history_sha256": _receipt_sha256_json(history_body)}
            _write_bound_route_record(
                _receipt_history_path(project, kind, sequence), history_entry)
            head_body = {
                "schema": _RECEIPT_HISTORY_HEAD_SCHEMA, "kind": str(kind),
                "sequence": sequence, "receipt_digest": envelope_digest,
                "run_id": run_id,
            }
            _atomic_write_json(
                _receipt_history_head(project, kind),
                {**head_body, "head_sha256": _receipt_sha256_json(head_body)})
            # Re-read the compare point immediately before replacing the
            # pointer.  Cooperative publishers therefore cannot overwrite a
            # concurrent advancement with a stale predecessor.
            if pointer.exists():
                latest = _read_json_regular(pointer)
                if (latest.get("receipt_digest") != current_digest
                        or int(latest.get("sequence", -1)) != current_sequence):
                    raise ValueError("RECEIPT_CURRENT_COMPARE_FAILED")
            if pointer.is_symlink():
                raise ValueError(f"receipt current pointer is linked: {pointer}")
            pointer_body = {
                "schema": _RECEIPT_POINTER_SCHEMA, "kind": str(kind),
                "run_id": run_id, "sequence": sequence,
                "predecessor_digest": predecessor,
                "payload_digest_field": str(digest_field),
                "payload_digest": digest,
                "receipt_digest": envelope_digest,
                "receipt_path": str(immutable),
            }
            _atomic_write_json(pointer, pointer_body)
            return immutable
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _activate_route_d1(project: Path, task: dict, route_receipt: dict,
                       runner: Path, runner_budget,
                       *, run_scope: str | None = None,
                       delivery_route: str = "ip") -> tuple[dict, dict, dict]:
    """Run/consume D1 and return (frontdoor, pending, activation).

    D1 is a two-stage admission: the pending record is visible before the
    canonical D1-only runner, and activation is published only after the
    runner emitted current L-doc provenance. A runner refusal or missing
    provenance therefore cannot unlock any later step.
    """
    import emit_attestation as emit_attestation          # noqa: PLC0415
    import route_decision as rd                            # noqa: PLC0415

    project = Path(project).resolve()
    run_scope = str(run_scope or uuid.uuid4().hex)
    if not run_scope or "/" in run_scope or "\\" in run_scope:
        raise ValueError("D1_RUN_SCOPE_INVALID")
    run_p = project.parent.parent
    decision, reasons = _validate_ai_route(task, run_p)
    if decision is None or decision.get("route_receipt") != route_receipt:
        raise ValueError("ROUTE_ADMISSION_AI_INVALID: " + ", ".join(reasons))
    _seal_route_admission(run_p, task, decision)
    source_sha = str(route_receipt.get("source_sha256") or "")
    if not source_sha:
        raise ValueError("D1_ACTIVATION_SOURCE_MISSING")
    task_sha = str(task.get("task_sha256") or "")
    pending = rd.write_d1_pending(
        _receipt_current_pointer(project, "d1_pending"), route_receipt=route_receipt,
        source_sha256=source_sha, task_sha256=task_sha)
    _publish_current_receipt(project, "d1_pending", pending,
                             digest_field="activation_sha256",
                             run_id=f"{task_sha}:d1-pending:{run_scope}")
    pending_current = _read_current_receipt(project, "d1_pending")
    if pending_current["receipt"].get("activation_sha256") != pending.get("activation_sha256"):
        raise ValueError("D1_PENDING_CURRENT_POINTER_MISMATCH")
    rd.admit_canonical_step(
        step="D1", pending=pending, activation=None,
        route_receipt=route_receipt, task_sha256=task_sha,
        source_sha256=source_sha)
    ldoc_root = project / "phase1" / "generated_docs"
    ldoc_handle = _sha256_text(str(ldoc_root.resolve()))
    frontdoor = _ensure_phase1_frontdoor(
        runner, project, runner_budget, force_current=True,
        route_receipt=route_receipt, task_sha256=task_sha,
        source_sha256=source_sha, ldoc_root_handle=ldoc_handle,
        delivery_route=delivery_route)
    if frontdoor.get("status") == "BLOCKED":
        # Keep the named pending state. Never manufacture activation on a
        # refusal, even if stale L-docs happen to be on disk.
        raise RuntimeError(
            "D1_ENTRY_PENDING: canonical D1 did not activate: "
            f"{frontdoor.get('reason')}")
    provenance = frontdoor.get("provenance") or emit_attestation.phase1_provenance(project)
    d1_gate = frontdoor.get("d1_gate")
    if not isinstance(d1_gate, dict):
        raise RuntimeError(frontdoor.get("d1_gate_error") or
                           "D1_ENTRY_PENDING: current D1 gate receipt missing")
    activation = rd.activate_d1(
        pending=pending, route_receipt=route_receipt,
        provenance=provenance, source_sha256=source_sha,
        task_sha256=task_sha, ldoc_root_handle=ldoc_handle,
        d1_gate=d1_gate)
    _publish_current_receipt(project, "d1_activation", activation,
                             digest_field="activation_sha256",
                             run_id=(f"{task_sha}:d1-activation:{run_scope}:"
                                     f"{d1_gate.get('invocation_id')}"))
    activation_current = _read_current_receipt(project, "d1_activation")
    if (activation_current["receipt"].get("activation_sha256")
            != activation.get("activation_sha256")):
        raise ValueError("D1_ACTIVATION_CURRENT_POINTER_MISMATCH")
    _seal_owned_d1_admission(run_p, task, activation)
    return frontdoor, pending, activation


@dataclass(frozen=True)
class _D1EvidenceSnapshot:
    project: Path
    report: tuple
    prompt: tuple
    ldocs: tuple
    directories: tuple
    activation_sha256: str | None
    digest: str


_D1_LAUNCH_CONTEXT = threading.local()


def _d1_file_generation(path: Path) -> tuple:
    st = path.lstat()
    if path.is_symlink() or not path.is_file():
        raise ValueError("D1_SNAPSHOT_FILE_NOT_REGULAR")
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _capture_d1_evidence(project: Path) -> _D1EvidenceSnapshot:
    """Read each evidence file once; bytes and file generations are immutable."""
    import _path_layout as _pl                     # noqa: PLC0415
    project = Path(project).resolve()
    docs = project / "phase1" / "generated_docs"
    report_path = _pl.report_path(project, "phase1_one_shot.json")
    directories = []
    for root in (docs, report_path.parent, project / "input"):
        for directory in (root, *root.parents):
            if directory == project.parent:
                break
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError("D1_SNAPSHOT_DIRECTORY_INVALID")
            st = directory.stat()
            generation = (st.st_dev, st.st_ino)
            if (directory, generation) not in directories:
                directories.append((directory, generation))
    def capture(path):
        generation = _d1_file_generation(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino) != generation[:2]:
                raise ValueError("D1_SNAPSHOT_PATH_REPLACED")
            data = handle.read()
        if generation != _d1_file_generation(path):
            raise ValueError("D1_SNAPSHOT_GENERATION_CHANGED")
        return (path, data, generation)
    prompt = capture(project / "input" / "phase1_prompt.md")
    report = capture(report_path)
    ldocs = tuple(capture(p) for p in sorted(docs.glob("L*.json")))
    if not ldocs:
        raise ValueError("D1_SNAPSHOT_LDOCS_MISSING")
    try:
        activation_sha = _read_current_receipt(project, "d1_activation")["receipt"]["activation_sha256"]
    except (OSError, ValueError, KeyError):
        activation_sha = None
    digest = _receipt_sha256_json({
        "project": str(project),
        "files": [{"path": str(p), "sha256": hashlib.sha256(b).hexdigest(),
                   "generation": g} for p, b, g in (prompt, report, *ldocs)],
    })
    snapshot = _D1EvidenceSnapshot(project, report, prompt, ldocs,
                                   tuple(directories), activation_sha, digest)
    _assert_d1_snapshot_current(snapshot)
    return snapshot


def _assert_d1_snapshot_current(snapshot: _D1EvidenceSnapshot) -> None:
    """Refuse generation replacement, including identical bytes at a new path."""
    for path, generation in snapshot.directories:
        if path.is_symlink() or not path.is_dir():
            raise ValueError("D1_SNAPSHOT_DIRECTORY_REPLACED")
        st = path.stat()
        if (st.st_dev, st.st_ino) != generation:
            raise ValueError("D1_SNAPSHOT_DIRECTORY_REPLACED")
    docs = snapshot.project / "phase1" / "generated_docs"
    if tuple(sorted(docs.glob("L*.json"))) != tuple(p for p, _, _ in snapshot.ldocs):
        raise ValueError("D1_SNAPSHOT_LDOC_SET_CHANGED")
    for path, _, generation in (snapshot.prompt, snapshot.report, *snapshot.ldocs):
        if _d1_file_generation(path) != generation:
            raise ValueError("D1_SNAPSHOT_GENERATION_CHANGED")


def _d1_invalidation_path(project: Path, activation_sha: str) -> Path:
    return (_route_anchor_dir(project.parent.parent) / "d1_invalidations" /
            project.name / f"{activation_sha}.json")


def _validate_d1_snapshot(snapshot: _D1EvidenceSnapshot, route_receipt: dict,
                          activation: dict, task_sha256: str,
                          *, authority_project: Path | None = None) -> None:
    """Validate exactly the captured bytes; never re-read the report for a PASS."""
    import route_decision as _rd                   # noqa: PLC0415
    project = Path(authority_project or snapshot.project).resolve()
    _rd.require_d1_activation(
        activation, route_receipt, task_sha256=str(task_sha256),
        ldoc_root_handle=_sha256_text(str((project / "phase1" / "generated_docs").resolve())))
    if _d1_invalidation_path(project, activation["activation_sha256"]).exists():
        raise ValueError("D1_CURRENT_ACTIVATION_INVALIDATED")
    gate = activation.get("d1_gate")
    if not isinstance(gate, dict) or gate.get("verdict") != "PASS":
        raise ValueError("D1_CURRENT_GATE_NOT_PLAIN_PASS")
    if _sha256_text(snapshot.prompt[1].decode("utf-8")) != route_receipt.get("source_sha256"):
        raise ValueError("D1_CURRENT_PROMPT_PROVENANCE_MISMATCH")
    provenance = hashlib.sha256()
    for p, data, _ in snapshot.ldocs:
        # L-docs are authority too: ambiguous JSON is never a valid generation.
        _strict_json_loads(data.decode("utf-8"))
        provenance.update(p.name.encode("utf-8") + b"\0" +
                          hashlib.sha256(data).hexdigest().encode("utf-8") + b"\n")
    if provenance.hexdigest() != activation.get("d1_provenance_sha256"):
        raise ValueError("D1_CURRENT_LDOC_PROVENANCE_MISMATCH")
    report_bytes = snapshot.report[1]
    report = _strict_json_loads(report_bytes.decode("utf-8"))
    if not isinstance(report, dict) or report.get("verdict") != "PASS":
        raise ValueError("D1_CURRENT_REPORT_NOT_PASS")
    if hashlib.sha256(report_bytes).hexdigest() != gate.get("report_sha256"):
        raise ValueError("D1_CURRENT_REPORT_DIGEST_MISMATCH")
    binding = report.get("runner_binding")
    if (not isinstance(binding, dict)
            or binding.get("schema") != "vibeic.runner_report_binding.v1"
            or binding.get("invocation_id") != gate.get("invocation_id")
            or binding.get("project") != str(project)
            or binding.get("report_name") != "phase1_one_shot.json"):
        raise ValueError("D1_CURRENT_REPORT_INVOCATION_MISMATCH")
    _assert_d1_snapshot_current(snapshot)


def _validate_live_d1_for_launch(project: Path, route_receipt: dict,
                                 activation: dict, task_sha256: str) -> _D1EvidenceSnapshot:
    """BLOCKING: a historical or invalidated D1 is never a live launch permit."""
    snapshot = _capture_d1_evidence(project)
    _validate_d1_snapshot(snapshot, route_receipt, activation, task_sha256)
    return snapshot


def _run_from_d1_snapshot(budget, argv: list, snapshot: _D1EvidenceSnapshot,
                          receipt: dict, activation: dict, task_sha: str,
                          *, authority_project: Path | None = None,
                          expected_repaired_output_sha256: str | None = None):
    """Validate one captured generation and bind that generation to submission."""
    try:
        owner_project = Path(authority_project or snapshot.project).resolve()
        run_p = owner_project.parent.parent
        task = _read_json_regular(run_p / "ai_route_tasks" / f"{task_sha}.json")
        _require_route_admission(run_p, task, receipt)
        if (_read_current_receipt(owner_project, "route_decision")["receipt"] != receipt
                or _read_current_receipt(owner_project, "d1_activation")["receipt"] != activation):
            raise ValueError("D1_SNAPSHOT_CURRENT_AUTHORITY_REPLACED")
        _validate_d1_snapshot(snapshot, receipt, activation, task_sha,
                              authority_project=authority_project)
        _D1_LAUNCH_CONTEXT.snapshot = snapshot
        _D1_LAUNCH_CONTEXT.authority = (owner_project, task, receipt, activation)
        _assert_d1_snapshot_current(snapshot)
        if expected_repaired_output_sha256 is not None:
            current_output_sha256 = _runner_material_snapshot(owner_project).get(
                "output_rtl_sha256")
            if current_output_sha256 != expected_repaired_output_sha256:
                raise ValueError(
                    "RUNNER_MATERIAL_UNBOUND: repaired RTL changed before runner launch")
        return budget.run(
            argv,
            **({"expected_repaired_output_sha256":
                expected_repaired_output_sha256}
               if expected_repaired_output_sha256 is not None else {}))
    except (OSError, ValueError, TypeError) as exc:
        return _ProcessOutcome(rc=None, error=f"D1_SNAPSHOT_LAUNCH_REFUSED: {exc}")
    finally:
        _D1_LAUNCH_CONTEXT.snapshot = None
        _D1_LAUNCH_CONTEXT.authority = None
        _restore_d1_evidence(snapshot)


def _restore_d1_evidence(snapshot: _D1EvidenceSnapshot) -> None:
    """Record invalidation instead of writing historical bytes to live paths.

    The name is retained for the existing span-finalization call sites. Any
    changed evidence, even an identical-byte path replacement, invalidates this
    activation permanently. Only a new typed D1 invocation can create a permit.
    """
    try:
        _assert_d1_snapshot_current(snapshot)
        return
    except (OSError, ValueError) as exc:
        reason = str(exc)
    archive = (snapshot.project / "reports" / "orchestrator" / "d1_history" /
               snapshot.digest)
    history = {
        "schema": "vibeic.invalidated_d1_snapshot.v1",
        "snapshot_sha256": snapshot.digest, "reason": reason,
        "activation_sha256": snapshot.activation_sha256,
        "files": [{"path": str(p), "bytes_hex": b.hex(), "generation": g}
                  for p, b, g in (snapshot.prompt, snapshot.report, *snapshot.ldocs)],
    }
    # Invalidation is outside the downstream-writable root. The archive is
    # historical evidence and cannot be consumed as a current pointer.
    if snapshot.activation_sha256:
        _write_immutable_json(
            _d1_invalidation_path(snapshot.project, snapshot.activation_sha256),
            {"schema": history["schema"], "reason": reason,
             "activation_sha256": snapshot.activation_sha256,
             "snapshot_sha256": snapshot.digest})
    _write_immutable_json(archive / "snapshot.json", history)


def _validated_route_reentry_state(*, bench: str, dataset: str | Path | None,
                                   fmt: str | None, run_p: Path, pid: str,
                                   result: dict, route_worklist: list[dict],
                                   allow_d1_only: bool,
                                   supplied_rtl: bool = False,
                                   snapshot_sink: dict | None = None,
                                   d1_snapshot: _D1EvidenceSnapshot | None = None) -> dict:
    """Single route/D1 admission used by resume and explicit Program re-entry."""
    import route_decision as _rd                   # noqa: PLC0415
    import task_nature_route as _tnr                # noqa: PLC0415

    task = next((row for row in route_worklist
                 if isinstance(row, dict) and str(row.get("id")) == str(pid)), None)
    if not isinstance(task, dict):
        return {"status": "REFUSED", "reason": "ROUTE_REENTRY_TASK_MISSING"}
    if dataset is not None and fmt is not None:
        try:
            _validate_route_input_anchor(
                bench, fmt, Path(dataset).resolve(), run_p, list(route_worklist))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return {"status": "REFUSED", "reason": f"ROUTE_REENTRY_ANCHOR_INVALID: {exc}"}
    project = Path(str(task.get("project") or "")).resolve()
    expected_project = run_p / "projects" / _safe_problem_id(str(pid))
    if project != expected_project:
        return {"status": "REFUSED", "reason": "ROUTE_REENTRY_PROJECT_INVALID"}
    stored_receipt = result.get("route_receipt")
    if not isinstance(stored_receipt, dict):
        stored_receipt = (result.get("routing_verdict") or {}).get("route_receipt")
    try:
        current_route = _read_current_receipt(project, "route_decision")
        receipt = current_route["receipt"]
        if not isinstance(stored_receipt, dict):
            raise ValueError("ROUTE_REENTRY_ROUTE_RECEIPT_MISSING")
        if stored_receipt.get("receipt_sha256") != receipt.get("receipt_sha256"):
            raise ValueError("ROUTE_REENTRY_ROUTE_RECEIPT_STALE")
        errors = _rd.validate_route_receipt(receipt)
        if errors:
            raise ValueError("ROUTE_REENTRY_ROUTE_INVALID: " + ", ".join(errors))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"status": "REFUSED", "reason": str(exc)}

    expected_exit = str(receipt["verify_through"])
    expected_route = _tnr.delivery_route_for_target(
        str(receipt["delivery_target"]),
        "DIE" if str(receipt["delivery_target"]) in
        {"gds", "shippable_gds", "foundry_handoff"} else None)
    if result.get("exit") is not None and str(result.get("exit")) != expected_exit:
        return {"status": "REFUSED", "reason": "ROUTE_REENTRY_EXIT_MUTATION"}
    if (result.get("delivery_route") is not None
            and str(result.get("delivery_route")) != expected_route):
        return {"status": "REFUSED", "reason": "ROUTE_REENTRY_ROUTE_MUTATION"}
    if result.get("entry") is not None and str(result.get("entry")) != str(receipt["entry_step"]):
        return {"status": "REFUSED", "reason": "ROUTE_REENTRY_ENTRY_MUTATION"}

    current_activation = None
    try:
        current_activation = _read_current_receipt(project, "d1_activation")
        activation = current_activation["receipt"]
        if activation.get("route_receipt_sha256") != receipt.get("receipt_sha256"):
            raise ValueError("ROUTE_REENTRY_D1_ROUTE_MISMATCH")
        if d1_snapshot is None:
            launch_snapshot = _validate_live_d1_for_launch(
                project, receipt, activation, str(task.get("task_sha256") or ""))
        else:
            launch_snapshot = d1_snapshot
            _validate_d1_snapshot(launch_snapshot, receipt, activation,
                                  str(task.get("task_sha256") or ""))
        if snapshot_sink is not None:
            prior = snapshot_sink.get(str(pid))
            if prior is not None and prior.digest != launch_snapshot.digest:
                raise ValueError("D1_SNAPSHOT_PLANNED_GENERATION_CHANGED")
            snapshot_sink[str(pid)] = launch_snapshot
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Only a genuinely absent activation may be retried at D1.  Existing
        # but stale/foreign evidence is a hard refusal and may not be used to
        # authorize even a later D1 span.
        if allow_d1_only and current_activation is None:
            try:
                _require_route_admission(run_p, task, receipt, require_d1=False)
            except (OSError, ValueError, TypeError, KeyError) as authority_error:
                return {"status": "REFUSED", "reason": str(authority_error)}
            return {"status": "D1_ONLY", "reason": str(exc),
                    "route_receipt": receipt, "task": task, "project": project}
        return {"status": "REFUSED", "reason": f"ROUTE_REENTRY_D1_INVALID: {exc}"}
    try:
        _require_route_admission(run_p, task, receipt)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"status": "REFUSED", "reason": str(exc)}
    return {"status": "ACTIVE", "route_receipt": receipt, "task": task,
            "project": project, "activation": activation,
            "entry_step": str(receipt["entry_step"]),
            "exit_step": expected_exit, "delivery_route": expected_route,
            "effective_entry": "2" if supplied_rtl else str(receipt["entry_step"])}


def _declared_route_ai_backup(routing: dict) -> dict:
    """Validate the route-level AI-backup declaration, without defaulting it.

    An absent declaration is different from a malformed declaration for
    diagnostics, but neither authorises AI work.  In particular, strings are
    not accepted as a convenient one-item list: silently normalising a broken
    route would turn a Program failure into an undeclared AI task.
    """
    plugin_entry = routing.get("plugin_entry")
    if plugin_entry is None:
        return {"status": "UNDECLARED", "skills": []}
    if not isinstance(plugin_entry, dict):
        return {"status": "INVALID", "skills": [],
                "reason": "plugin_entry must be an object"}
    if "ai_backup" not in plugin_entry:
        return {"status": "UNDECLARED", "skills": []}
    declared = plugin_entry.get("ai_backup")
    if not isinstance(declared, list) or not declared:
        return {"status": "INVALID", "skills": [],
                "reason": "plugin_entry.ai_backup must be a non-empty list"}
    if any(not isinstance(skill, str) or not skill.strip()
           for skill in declared):
        return {"status": "INVALID", "skills": [],
                "reason": "every declared AI-backup skill must be non-empty text"}
    skills = [skill.strip() for skill in declared]
    if len(set(skills)) != len(skills):
        return {"status": "INVALID", "skills": [],
                "reason": "declared AI-backup skills must be unique"}
    return {"status": "DECLARED", "skills": skills}


def _public_input_reasons(task: dict) -> list[str]:
    """Keep original-input identity fixed across review and repair lineage."""
    import benchmark_io_adapter as bio                  # noqa: PLC0415
    try:
        actual = bio.public_original_input(
            Path(str(task.get("project") or "")), str(task.get("id")),
            str(task.get("prompt_sha256") or ""),
            expected=task.get("public_original_input"))
        if actual.get("status") != "NOT_MEASURED" \
                and task.get("public_original_input") != actual:
            return ["PUBLIC_INPUT_HANDOFF_INVALID: task dropped original input"]
        if "public_original_input_paths" in task:
            paths = [str(Path(task["project"]).resolve() / "input" /
                         "public_original" / "files" / row["relative_path"])
                     for row in actual["files"]]
            if task["public_original_input_paths"] != paths:
                return ["PUBLIC_INPUT_HANDOFF_INVALID: reviewer allowlist differs"]
    except ValueError as exc:
        return [str(exc)]
    return []


def _route_contract_sha256() -> str:
    """Bind an AI decision to the general nature-to-flow mapping it selects."""
    import task_nature_route as tnr                       # noqa: PLC0415
    import route_decision as rd                            # noqa: PLC0415
    return _sha256_text(json.dumps(
        {"nature_entry": tnr.NATURE_ENTRY,
         "evidence_exit": tnr.EVIDENCE_EXIT,
         "delivery_targets": tnr.DELIVERY_TARGETS,
         "prompt_delivery_requirements_schema": tnr.PROMPT_DELIVERY_REQUIREMENTS_SCHEMA,
         "prompt_delivery_rules_version": tnr.PROMPT_DELIVERY_RULES_VERSION,
         "canonical_dag_sha256": rd.canonical_dag()["sha256"]},
        sort_keys=True))


def _make_ai_route_task(problem_id: str, project: Path, staged: dict,
                        proposal: dict, run_p: Path, fmt: str,
                        benchmark: str | None = None,
                        dataset_path: Path | None = None) -> dict:
    """Issue an input-only route question before any design runner executes."""
    import task_nature_route as tnr                       # noqa: PLC0415
    import route_decision as rd                            # noqa: PLC0415
    project, run_p = Path(project).resolve(), Path(run_p).resolve()
    prompt = project / "input" / "phase1_prompt.md"
    prompt_sha = _sha256_text(prompt.read_text(errors="replace"))
    safe = _safe_problem_id(str(problem_id))
    prompt_text = prompt.read_text(errors="replace")
    prompt_delivery = tnr.prompt_delivery_requirements(prompt_text)
    semantic_payload = tnr.semantic_routing_payload(
        prompt_text,
        context={"program_proposal": {
            "nature": proposal.get("nature"),
            "entry_nature": proposal.get("entry_nature"),
            "source": proposal.get("source"),
            "needs_ai_parse": proposal.get("needs_ai_parse"),
        }})
    response_path = str((run_p / "ai_routes" / safe /
                         f"{prompt_sha}.json").resolve())
    coordinator_binding = rd.build_coordinator_binding(
        benchmark=benchmark, problem_id=str(problem_id),
        project_path=str(project), prompt_path=str(prompt),
        response_path=response_path,
        semantic_payload_sha256=semantic_payload["semantic_payload_sha256"],
        dataset_path=str(Path(dataset_path).resolve()) if dataset_path is not None else None,
        harness_digest=None, golden_digest=None, expected_digest=None)
    task = {
        "schema": _ROUTE_TASK_SCHEMA,
        "id": str(problem_id),
        "io_format": fmt,
        "project": str(project),
        "prompt_path": str(prompt),
        "prompt_sha256": prompt_sha,
        "prompt_chars": int(staged.get("prompt_chars") or 0),
        "public_original_input": staged["public_original_input"],
        "program_proposal": proposal,
        # This is the semantic handoff.  It contains no benchmark label,
        # problem id, coordinator path, harness/golden/expected answer, or
        # other opaque identity.  Those values live in the separate binding.
        "semantic_payload": semantic_payload,
        "semantic_payload_sha256": semantic_payload["semantic_payload_sha256"],
        "prompt_delivery_requirements": prompt_delivery,
        "coordinator_binding": coordinator_binding,
        "routing_contract_sha256": _route_contract_sha256(),
        "allowed_natures": sorted(tnr.NATURE_ENTRY),
        "response_path": response_path,
        "response_contract": {
            "schema": _AI_ROUTE_SCHEMA,
            "bindings": ["id", "task_sha256", "prompt_sha256",
                         "source_sha256", "routing_contract_sha256"],
            "disposition": "CONFIRM, OVERRIDE, or NEEDS_CLARIFICATION",
            "ai_nature": "one allowed_natures member for CONFIRM or OVERRIDE",
            "author": {"kind": "AI", "model": "<named model>"},
            "blind": {"oracle_accessed": False},
            "prompt_evidence": ("excerpt/supports records from visible input "
                                "only; OVERRIDE needs >=1 exact excerpt whose "
                                "supports claim names ai_nature"),
            "rationale": "<at least 24 characters>",
            "semantic_decision": {
                "nature": "one allowed_natures member",
                "requested_evidence": "optional evidence class; the Program maps it to a step",
                "delivery_target": "optional delivery target; the Program maps it to a step",
                "semantic_payload_sha256": semantic_payload["semantic_payload_sha256"],
                "step_fields_forbidden": ["entry_step", "answer_step", "verify_through"],
            },
        },
    }
    task["task_sha256"] = _sha256_text(json.dumps(task, sort_keys=True))
    _write_immutable_json(run_p / "ai_route_tasks" /
                          f"{task['task_sha256']}.json", task)
    return task


def _route_input_anchor(bench: str, fmt: str, dataset: Path,
                        route_tasks: list[dict]) -> dict:
    """Create the owner-visible input/task anchor body used by resume."""
    body = {
        "schema": "vibeic.route_input_anchor.v1",
        "benchmark": str(bench),
        "format": str(fmt),
        "dataset_handle": hashlib.sha256(
            str(Path(dataset).resolve()).encode("utf-8")).hexdigest(),
        "tasks": [{
            "id": str(task["id"]),
            "task_sha256": str(task["task_sha256"]),
            "project": str(task["project"]),
            "prompt_path": str(task["prompt_path"]),
            "prompt_sha256": str(task["prompt_sha256"]),
            "response_path": str(task["response_path"]),
            "source_sha256": str(task["public_original_input"].get("source_sha256")),
            "semantic_payload_sha256": str(task["semantic_payload_sha256"]),
        } for task in route_tasks],
    }
    body["anchor_sha256"] = _sha256_text(json.dumps(body, sort_keys=True))
    return body


def _route_anchor_dir(run_p: Path) -> Path:
    """Return the owner-controlled anchor directory outside the run root.

    Worker projects and generated artefacts live below ``run_p``.  The anchor
    and its process capability deliberately live in a sibling namespace so a
    worker that can rewrite every run-root file cannot rewrite the authority it
    is being checked against.
    """
    run_p = Path(run_p).resolve()
    run_key = hashlib.sha256(str(run_p).encode("utf-8")).hexdigest()
    return run_p.parent / ".vibeic_route_anchors" / run_key


def _route_anchor_paths(run_p: Path) -> tuple[Path, Path]:
    root = _route_anchor_dir(run_p)
    return root / "anchor.json", root / "capability.bin"


def _publish_route_input_anchor(run_p: Path, anchor: dict) -> None:
    """Publish an immutable, HMAC-bound anchor outside the worker root."""
    anchor_path, capability_path = _route_anchor_paths(run_p)
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    if capability_path.is_symlink() or anchor_path.is_symlink():
        raise ValueError("ROUTE_INPUT_ANCHOR_INVALID: linked authority")
    if capability_path.is_file():
        capability = capability_path.read_bytes()
    else:
        capability = secrets.token_bytes(32)
        fd = os.open(str(capability_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, capability)
        finally:
            os.close(fd)
    if len(capability) != 32:
        raise ValueError("ROUTE_INPUT_ANCHOR_INVALID: capability")
    body = {k: v for k, v in anchor.items()
            if k not in {"anchor_mac", "capability_sha256"}}
    body["capability_sha256"] = hashlib.sha256(capability).hexdigest()
    body_bytes = json.dumps(body, sort_keys=True).encode("utf-8")
    body["anchor_mac"] = hmac.new(capability, body_bytes, hashlib.sha256).hexdigest()
    _write_immutable_json(anchor_path, body)


def _read_route_input_anchor(run_p: Path) -> dict:
    """Read the immutable coordinator anchor and verify its capability MAC."""
    path, capability_path = _route_anchor_paths(run_p)
    if (path.is_symlink() or capability_path.is_symlink()
            or not path.is_file() or not capability_path.is_file()):
        raise ValueError("ROUTE_INPUT_ANCHOR_INVALID: authority missing")
    capability = capability_path.read_bytes()
    if len(capability) != 32:
        raise ValueError("ROUTE_INPUT_ANCHOR_INVALID: capability")
    anchor = _strict_json_loads(path.read_text(errors="replace"))
    if not isinstance(anchor, dict) or anchor.get("schema") != "vibeic.route_input_anchor.v1":
        raise ValueError("ROUTE_INPUT_ANCHOR_INVALID: schema")
    digest = anchor.get("anchor_sha256")
    mac = anchor.get("anchor_mac")
    cap_digest = anchor.get("capability_sha256")
    body = {k: v for k, v in anchor.items()
            if k not in {"anchor_sha256", "anchor_mac", "capability_sha256"}}
    if not isinstance(digest, str) or _sha256_text(json.dumps(body, sort_keys=True)) != digest:
        raise ValueError("ROUTE_INPUT_ANCHOR_INVALID: digest")
    signed = {k: v for k, v in anchor.items() if k != "anchor_mac"}
    if (cap_digest != hashlib.sha256(capability).hexdigest()
            or not isinstance(mac, str)
            or not hmac.compare_digest(
                mac, hmac.new(capability,
                              json.dumps(signed, sort_keys=True).encode("utf-8"),
                              hashlib.sha256).hexdigest())):
        raise ValueError("ROUTE_INPUT_ANCHOR_INVALID: capability binding")
    return anchor


def _validate_route_input_anchor(bench: str, fmt: str, dataset: Path,
                                 run_p: Path, route_tasks: list[dict]) -> None:
    """Reject co-mutated inputs against the external capability-bound anchor."""
    anchor = _read_route_input_anchor(run_p)
    if (anchor.get("benchmark") != str(bench)
            or anchor.get("format") != str(fmt)
            or anchor.get("dataset_handle") != hashlib.sha256(
                str(Path(dataset).resolve()).encode("utf-8")).hexdigest()):
        raise ValueError("ROUTE_INPUT_ANCHOR_INVALID: current run identity")
    expected = anchor.get("tasks")
    actual = [{
        "id": str(task.get("id")),
        "task_sha256": str(task.get("task_sha256")),
        "project": str(task.get("project")),
        "prompt_path": str(task.get("prompt_path")),
        "prompt_sha256": str(task.get("prompt_sha256")),
        "response_path": str(task.get("response_path")),
        "source_sha256": str((task.get("public_original_input") or {}).get("source_sha256")),
        "semantic_payload_sha256": str(task.get("semantic_payload_sha256")),
    } for task in route_tasks]
    if expected != actual:
        raise ValueError("ROUTE_INPUT_ANCHOR_INVALID: issued task/input identity changed")


def _route_admission_path(run_p: Path, task: dict) -> Path:
    digest = str(task.get("task_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("ROUTE_ADMISSION_TASK_DIGEST_INVALID")
    return _route_anchor_dir(run_p) / "admissions" / f"{digest}.json"


def _seal_route_admission(run_p: Path, task: dict, decision: dict) -> None:
    """Seal validated AI authority outside the worker-writable run root.

    A changed response requires a new issued task/anchor and a fresh typed D1
    call. Publishing a replacement route, mode or activation is insufficient.
    """
    anchor = _read_route_input_anchor(run_p)
    _, capability_path = _route_anchor_paths(run_p)
    body = {
        "schema": "vibeic.coordinator_route_admission.v1",
        "anchor_sha256": anchor["anchor_sha256"],
        "task_sha256": task["task_sha256"],
        "prompt_sha256": task["prompt_sha256"],
        "source_sha256": task["public_original_input"].get("source_sha256"),
        "ai_response_sha256": decision["ai_route_response_sha256"],
        "route_receipt": decision["route_receipt"],
    }
    body["admission_mac"] = hmac.new(
        capability_path.read_bytes(),
        json.dumps(body, sort_keys=True, allow_nan=False).encode("utf-8"),
        hashlib.sha256).hexdigest()
    path = _route_admission_path(run_p, task)
    if path.parent.is_symlink():
        raise ValueError("ROUTE_ADMISSION_AUTHORITY_LINKED")
    _write_bound_route_record(path, body)


def _require_route_admission(run_p: Path, task: dict, receipt: dict,
                              *, require_d1: bool = True) -> None:
    """BLOCKING: writable receipts never create AI or user mode authority."""
    anchor = _read_route_input_anchor(run_p)
    task_hash = task.get("task_sha256")
    task_body = {k: v for k, v in task.items() if k != "task_sha256"}
    if _sha256_text(json.dumps(task_body, sort_keys=True)) != task_hash:
        raise ValueError("ROUTE_ADMISSION_TASK_CHANGED")
    anchored = next((row for row in anchor["tasks"] if row["id"] == str(task["id"])), None)
    expected = _route_input_anchor(
        anchor["benchmark"], anchor["format"], Path("/unused"), [task])["tasks"][0]
    if anchored != expected:
        raise ValueError("ROUTE_ADMISSION_ORIGINAL_ANCHOR_MISMATCH")
    issued = run_p / "ai_route_tasks" / f"{task_hash}.json"
    if _read_json_regular(issued) != task:
        raise ValueError("ROUTE_ADMISSION_ISSUED_TASK_CHANGED")
    reasons = _public_input_reasons(task)
    if reasons:
        raise ValueError("ROUTE_ADMISSION_ORIGINAL_INPUT_CHANGED: " + ", ".join(reasons))
    path = _route_admission_path(run_p, task)
    if path.parent.is_symlink():
        raise ValueError("ROUTE_ADMISSION_AUTHORITY_LINKED")
    sealed = _read_json_regular(path)
    body = {k: v for k, v in sealed.items() if k != "admission_mac"}
    _, capability_path = _route_anchor_paths(run_p)
    expected_mac = hmac.new(
        capability_path.read_bytes(),
        json.dumps(body, sort_keys=True, allow_nan=False).encode("utf-8"),
        hashlib.sha256).hexdigest()
    if (sealed.get("schema") != "vibeic.coordinator_route_admission.v1"
            or not isinstance(sealed.get("admission_mac"), str)
            or not hmac.compare_digest(sealed["admission_mac"], expected_mac)
            or sealed.get("anchor_sha256") != anchor["anchor_sha256"]
            or sealed.get("task_sha256") != task_hash
            or sealed.get("prompt_sha256") != task["prompt_sha256"]
            or sealed.get("source_sha256") != task["public_original_input"].get("source_sha256")):
        raise ValueError("ROUTE_ADMISSION_OWNER_BINDING_INVALID")
    response = Path(task["response_path"])
    if response.is_symlink() or hashlib.sha256(response.read_bytes()).hexdigest() != sealed.get("ai_response_sha256"):
        raise ValueError("ROUTE_ADMISSION_AI_RESPONSE_CHANGED")
    if receipt != sealed.get("route_receipt"):
        raise ValueError("ROUTE_ADMISSION_ROUTE_OR_MODE_REPLACED")
    import route_decision as _rd                   # noqa: PLC0415
    pending = _read_current_receipt(Path(task["project"]), "d1_pending")["receipt"]
    expected_pending = _rd.write_d1_pending(
        _receipt_current_pointer(Path(task["project"]), "d1_pending"),
        route_receipt=receipt, source_sha256=receipt["source_sha256"],
        task_sha256=task_hash)
    if pending != expected_pending:
        raise ValueError("ROUTE_ADMISSION_PENDING_REPLACED")
    if require_d1:
        activation = _read_current_receipt(Path(task["project"]), "d1_activation")["receipt"]
        d1_path = _owned_d1_admission_path(run_p, task, activation)
        if d1_path.parent.is_symlink() or d1_path.parent.parent.is_symlink():
            raise ValueError("D1_OWNER_ADMISSION_LINKED")
        owned = _read_json_regular(d1_path)
        owned_body = {k: v for k, v in owned.items() if k != "admission_mac"}
        owned_mac = hmac.new(
            capability_path.read_bytes(),
            json.dumps(owned_body, sort_keys=True, allow_nan=False).encode("utf-8"),
            hashlib.sha256).hexdigest()
        if (not isinstance(owned.get("admission_mac"), str)
                or not hmac.compare_digest(owned["admission_mac"], owned_mac)
                or owned.get("schema") != "vibeic.coordinator_d1_admission.v1"
                or owned.get("anchor_sha256") != anchor["anchor_sha256"]
                or owned.get("task_sha256") != task_hash
                or owned.get("activation") != activation):
            raise ValueError("D1_OWNER_ADMISSION_REPLACED")



def _owned_d1_admission_path(run_p: Path, task: dict, activation: dict) -> Path:
    digest = str(activation.get("activation_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("D1_OWNER_ADMISSION_DIGEST_INVALID")
    return _route_admission_path(run_p, task).parent / "d1" / task["task_sha256"] / f"{digest}.json"


def _seal_owned_d1_admission(run_p: Path, task: dict, activation: dict) -> None:
    """Seal only D1 gates measured by the coordinator's fresh typed call.

    A worker can replace all its JSON, but cannot issue a new D1 generation
    just by rewriting the invocation id, report digest and activation together.
    """
    anchor = _read_route_input_anchor(run_p)
    _, capability = _route_anchor_paths(run_p)
    body = {
        "schema": "vibeic.coordinator_d1_admission.v1",
        "anchor_sha256": anchor["anchor_sha256"],
        "task_sha256": task["task_sha256"], "activation": activation,
    }
    body["admission_mac"] = hmac.new(
        capability.read_bytes(), json.dumps(body, sort_keys=True, allow_nan=False).encode("utf-8"),
        hashlib.sha256).hexdigest()
    path = _owned_d1_admission_path(run_p, task, activation)
    if path.parent.is_symlink() or path.parent.parent.is_symlink():
        raise ValueError("D1_OWNER_ADMISSION_LINKED")
    _write_bound_route_record(path, body)


def _claim_names_nature(claim: str, nature: str) -> bool:
    """True when an evidence claim cites `nature` (``_`` and space alike)."""
    def norm(text: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())
    return f" {norm(nature)} " in f" {norm(claim)} "


def _issued_route_task_format(task: dict, run_p: Path) -> str:
    """Read the I/O protocol from the existing hash-bound coordinator issue."""
    task_hash = task["task_sha256"]
    body = {k: v for k, v in task.items() if k != "task_sha256"}
    if _sha256_text(json.dumps(body, sort_keys=True)) != task_hash:
        raise ValueError("issued route task identity changed")
    issued = run_p / "ai_route_tasks" / f"{task_hash}.json"
    if _strict_json_loads(issued.read_text()) != task:
        raise ValueError("route task differs from coordinator issue")
    fmt = task.get("io_format")
    if not isinstance(fmt, str) or fmt not in {"agentic", *_BENCH_FORMAT.values()}:
        raise ValueError("missing or invalid issued I/O format")
    return fmt


def _validate_ai_route(task: dict, run_p: Path, *,
                       benchmark: str | None = None,
                       dataset: Path | None = None) -> tuple[dict | None, list[str]]:
    """Fail closed on an unsigned, stale, non-blind, or ungrounded route."""
    import task_nature_route as tnr                       # noqa: PLC0415
    import route_decision as rd                            # noqa: PLC0415
    run_p = Path(run_p).resolve()
    reasons = _public_input_reasons(task)
    try:
        task_hash = task["task_sha256"]
        _issued_route_task_format(task, run_p)
        binding = task.get("coordinator_binding")
        if not isinstance(binding, dict):
            raise ValueError("coordinator binding is missing")
        binding_digest = binding.get("binding_sha256")
        binding_body = {k: v for k, v in binding.items()
                        if k != "binding_sha256"}
        if (not isinstance(binding_digest, str)
                or rd.sha256_json(binding_body) != binding_digest):
            raise ValueError("coordinator binding digest mismatch")
        project = Path(str(task["project"])).resolve()
        if project != run_p / "projects" / _safe_problem_id(str(task["id"])):
            raise ValueError("route project is not owned by this run/task")
        prompt = project / "input" / "phase1_prompt.md"
        prompt_text = prompt.read_text(errors="replace")
        if _sha256_text(prompt_text) != task["prompt_sha256"]:
            raise ValueError("route prompt changed after issue")
        prompt_delivery = tnr.prompt_delivery_requirements(prompt_text)
        if task.get("prompt_delivery_requirements") != prompt_delivery:
            raise ValueError("prompt delivery requirements changed after issue")
        if benchmark is not None and dataset is not None:
            expected_binding = rd.build_coordinator_binding(
                benchmark=benchmark, problem_id=str(task["id"]),
                project_path=str(project), prompt_path=str(prompt),
                response_path=str(task["response_path"]),
                semantic_payload_sha256=str(task["semantic_payload_sha256"]),
                dataset_path=str(Path(dataset).resolve()),
                harness_digest=None, golden_digest=None, expected_digest=None)
            if binding != expected_binding:
                raise ValueError("coordinator binding differs from current run identity")
        if task.get("routing_contract_sha256") != _route_contract_sha256():
            raise ValueError("general route table changed after issue")
        semantic_payload = task.get("semantic_payload")
        if not isinstance(semantic_payload, dict) or task.get(
                "semantic_payload_sha256") != semantic_payload.get("semantic_payload_sha256"):
            raise ValueError("semantic route payload is missing or stale")
        if rd.sha256_json({k: v for k, v in semantic_payload.items()
                           if k != "semantic_payload_sha256"}) != semantic_payload.get(
                               "semantic_payload_sha256"):
            raise ValueError("semantic route payload digest mismatch")
        response_path = Path(str(task["response_path"]))
        expected_path = (run_p / "ai_routes" / _safe_problem_id(str(task["id"])) /
                         f"{task['prompt_sha256']}.json")
        response_ancestors = [response_path]
        parent = response_path.parent
        while parent != run_p and parent != parent.parent:
            response_ancestors.append(parent)
            parent = parent.parent
        if (response_path != expected_path or parent != run_p
                or any(path.is_symlink() for path in response_ancestors)):
            raise ValueError("route response path is not coordinator-owned regular path")
        if not response_path.is_file():
            return None, reasons + ["AI_ROUTE_PENDING: no response"]
        response_bytes = response_path.read_bytes()
        response = _strict_json_loads(response_bytes.decode("utf-8"))
        if not isinstance(response, dict):
            raise ValueError("route response must be an object")
        required = {
            "schema": _AI_ROUTE_SCHEMA,
            "id": task["id"],
            "task_sha256": task_hash,
            "prompt_sha256": task["prompt_sha256"],
            "source_sha256": task["public_original_input"].get("source_sha256"),
            "routing_contract_sha256": task["routing_contract_sha256"],
        }
        for key, value in required.items():
            if key not in response or response.get(key) != value:
                reasons.append(f"AI_ROUTE_INVALID: {key} is stale or wrong")
        author = response.get("author")
        if (not isinstance(author, dict)
                or not isinstance(author.get("kind"), str)
                or author.get("kind") != "AI"
                or not isinstance(author.get("model"), str)
                or not author.get("model").strip()
                or author.get("model").lower() in
                {"unknown", "unspecified", "n/a"}):
            reasons.append("AI_ROUTE_INVALID: named AI author required")
        blind = response.get("blind")
        if not isinstance(blind, dict) or blind.get("oracle_accessed") is not False:
            reasons.append("AI_ROUTE_INVALID: blind.oracle_accessed must be false")
        if (not isinstance(response.get("rationale"), str)
                or len(response.get("rationale").strip()) < 24):
            reasons.append("AI_ROUTE_INVALID: route rationale too short")
        disposition = response.get("disposition")
        if (not isinstance(disposition, str)
                or disposition not in {"CONFIRM", "OVERRIDE", "NEEDS_CLARIFICATION"}):
            reasons.append("AI_ROUTE_INVALID: unknown disposition")
        semantic = response.get("semantic_decision")
        typed_route = isinstance(semantic, dict)
        if "semantic_decision" in response and not isinstance(semantic, dict):
            reasons.append("AI_ROUTE_INVALID: semantic_decision must be an object")
            semantic = {}
        semantic = semantic or {}
        if any(key in semantic for key in ("entry_step", "answer_step", "verify_through")):
            reasons.append("AI_ROUTE_INVALID: semantic decision may not choose flow steps")
        if ("semantic_payload_sha256" in semantic
                and (not isinstance(semantic.get("semantic_payload_sha256"), str)
                     or semantic.get("semantic_payload_sha256") != task.get("semantic_payload_sha256"))):
            reasons.append("AI_ROUTE_INVALID: semantic payload binding is stale")
        nature = semantic.get("nature", response.get("ai_nature"))
        requested_evidence = semantic.get("requested_evidence")
        delivery_target = semantic.get("delivery_target")
        if nature is not None and not isinstance(nature, str):
            reasons.append("AI_ROUTE_INVALID: ai_nature must be a string")
        if ("requested_evidence" in semantic
                and not isinstance(requested_evidence, str)):
            reasons.append("AI_ROUTE_INVALID: requested_evidence must be a string")
        if ("delivery_target" in semantic
                and not isinstance(delivery_target, str)):
            reasons.append("AI_ROUTE_INVALID: delivery_target must be a string")
        prompt_evidence = response.get("prompt_evidence")
        if prompt_evidence is not None:
            if not isinstance(prompt_evidence, list):
                reasons.append("AI_ROUTE_INVALID: prompt_evidence must be an array")
            elif any(not isinstance(item, dict)
                     or not isinstance(item.get("excerpt"), str)
                     or not isinstance(item.get("supports"), str)
                     for item in prompt_evidence):
                reasons.append("AI_ROUTE_INVALID: prompt evidence fields must be strings")
        if disposition != "NEEDS_CLARIFICATION":
            if nature not in tnr.NATURE_ENTRY:
                reasons.append("AI_ROUTE_INVALID: ai_nature is not a product nature")
            if requested_evidence is not None and requested_evidence not in tnr.EVIDENCE_EXIT:
                reasons.append("AI_ROUTE_INVALID: requested_evidence is not a product evidence class")
            resolved_delivery = tnr.resolve_prompt_delivery_target(
                prompt_delivery, delivery_target)
            if not resolved_delivery.get("ok"):
                reasons.append("AI_ROUTE_INVALID: " + str(
                    resolved_delivery.get("reason") or "delivery target refused"))
            if (disposition == "CONFIRM"
                    and nature != task["program_proposal"].get("entry_nature")):
                reasons.append("AI_ROUTE_INVALID: CONFIRM differs from proposal")
            evidence = _verified_prompt_evidence(
                response.get("prompt_evidence"), prompt_text)
            if disposition == "OVERRIDE":
                # A route CHANGE departs from the Program's input-derived
                # proposal, so it must be grounded in the visible input
                # itself: at least one exact excerpt whose claim is cited for
                # the nature selected.  Rationale length is never a
                # substitute (review wave 52: 160 characters of filler routed
                # a generation prompt to debug with zero excerpts).
                if not evidence:
                    reasons.append(
                        "AI_ROUTE_INVALID: OVERRIDE requires verified prompt "
                        "evidence (exact visible-input excerpt + claim); "
                        "rationale length is not evidence")
                elif (nature in tnr.NATURE_ENTRY
                        and not any(_claim_names_nature(item["supports"], nature)
                                    for item in evidence)):
                    reasons.append(
                        "AI_ROUTE_INVALID: no verified evidence claim names "
                        f"the selected ai_nature {nature!r}")
            elif not evidence and len(str(response.get("rationale") or "").strip()) < 160:
                reasons.append("AI_ROUTE_INVALID: prompt evidence or detailed rationale required")
        if reasons:
            return None, reasons
        if disposition == "NEEDS_CLARIFICATION":
            return None, ["AI_ROUTE_NEEDS_CLARIFICATION: AI could not select a route"]
        entry = tnr.NATURE_ENTRY[nature]
        requested_evidence = requested_evidence or entry["default_evidence"]
        resolved_delivery = tnr.resolve_prompt_delivery_target(
            prompt_delivery, delivery_target)
        if not resolved_delivery.get("ok"):
            return None, reasons + ["AI_ROUTE_INVALID: " + str(
                resolved_delivery.get("reason") or "delivery target refused")]
        delivery_target = str(resolved_delivery["target"])
        delivery_route = tnr.delivery_route_for_target(
            delivery_target, resolved_delivery.get("route_family"))
        # The prompt itself is the only user-owned source available at this
        # boundary. Reviewer prose and benchmark metadata are never Ultra
        # evidence. The Program derives all flow steps from this receipt.
        explicit_ultra = rd.explicit_ultra_evidence(prompt_text, source="user")
        route_receipt = tnr.route_decision_receipt(
            prompt_text, nature=nature,
            requested_evidence=requested_evidence,
            delivery_target=delivery_target,
            # The route receipt is semantic evidence.  Bind it to the visible
            # prompt bytes so opaque benchmark IDs and staging paths cannot
            # alter the route decision; public-input identity remains sealed
            # separately by the task/coordinator binding and its digest.
            source_sha256=str(task["prompt_sha256"]),
            explicit_user_evidence=explicit_ultra,
            context=semantic_payload.get("context"))
        return {
            "nature": nature, "entry_nature": nature,
            "route": entry["route"], "plugin_entry": entry["plugin_entry"],
            "source": "ai_confirmed" if disposition == "CONFIRM" else "ai_override",
            "needs_ai_parse": False,
            "ai_route_response_sha256": hashlib.sha256(response_bytes).hexdigest(),
            "program_proposal": task["program_proposal"],
            "requested_evidence": requested_evidence,
            "delivery_target": delivery_target,
            "delivery_route": delivery_route,
            "prompt_delivery_requirements": prompt_delivery,
            "route_receipt": route_receipt,
            "semantic_payload_sha256": task["semantic_payload_sha256"],
            "coordinator_binding": task.get("coordinator_binding"),
            # The Program has normalized both the new semantic object and the
            # legacy top-level nature into the same typed receipt.  This is
            # deliberately always true at the execution boundary: callers
            # cannot choose a weaker barrier by changing response shape.
            "typed_route": True,
            "normalized_legacy_semantic": not typed_route,
        }, []
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return None, reasons + [f"AI_ROUTE_INVALID: {exc}"]


def _backup_output_manifest(project: Path) -> list[dict]:
    """Exact author deliverable set, including public include dependencies."""
    root = Path(project) / "phase2" / "stage1" / "rtl"
    if root.is_symlink():
        raise ValueError("AI_BACKUP_OUTPUT_INVALID: linked output root")
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("AI_BACKUP_OUTPUT_INVALID: linked output")
        if path.is_file():
            data = path.read_bytes()
            files.append({"relative_path": str(path.relative_to(root)),
                          "sha256": hashlib.sha256(data).hexdigest(),
                          "bytes": len(data)})
    return files


def _validate_backup_completion(item: dict, run_p: Path) -> tuple[dict | None, list[str]]:
    """BLOCKING: file presence is not an author's completed handoff.

    Reuse the repair record's named AI author, blind declaration and rationale
    protocol. These cooperative records bind attribution, not OS identities.
    """
    reasons = _public_input_reasons(item)
    project = Path(str(item.get("project") or "")).resolve()
    try:
        if project != (Path(run_p).resolve() / "projects" /
                       _safe_problem_id(str(item.get("id")))):
            raise ValueError("backup project is not owned by this run/task")
        task_hash = item["task_sha256"]
        body = {k: v for k, v in item.items() if k != "task_sha256"}
        if _sha256_text(json.dumps(body, sort_keys=True)) != task_hash:
            raise ValueError("issued backup task identity changed")
        issued = Path(run_p) / "ai_backup_tasks" / f"{task_hash}.json"
        if _strict_json_loads(issued.read_text()) != item:
            raise ValueError("backup does not match the coordinator-issued handoff")
        prompt_text = (project / "input" / "phase1_prompt.md").read_text()
        if _sha256_text(prompt_text) != item["prompt_sha256"]:
            raise ValueError("prompt changed before backup worker entry")
        path = project / "phase2" / "stage1" / "ai_backup_author.json"
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError("author completion record path is linked")
        raw_record = path.read_bytes()
        record = _strict_json_loads(raw_record)
        outputs = _backup_output_manifest(project)
        rtl = _rtl_files(project)
        if not rtl or any(not p.read_bytes().strip() for p in rtl):
            raise ValueError("author RTL output is empty or incomplete")
        expected = {"schema": "vibeic.benchmark.ai_backup_record.v1",
                    "id": item["id"], "task_sha256": task_hash,
                    "prompt_sha256": item["prompt_sha256"],
                    "source_sha256": item["public_original_input"].get("source_sha256"),
                    "output_manifest": outputs,
                    "rtl_sha256": _sha256_text(_candidate_text(rtl))}
        if not isinstance(record, dict):
            raise ValueError("author completion record must be an object")
        for key, value in expected.items():
            if record.get(key) != value:
                reasons.append(f"AI_BACKUP_COMPLETION_INVALID: {key} is stale or wrong")
        author = record.get("author")
        if (not isinstance(author, dict) or author.get("kind") != "AI"
                or not str(author.get("model") or "").strip()
                or str(author.get("model")).lower() in {"unknown", "unspecified", "n/a"}):
            reasons.append("AI_BACKUP_COMPLETION_INVALID: named AI author required")
        if (record.get("oracle_accessed") is not False
                or len(str(record.get("rationale") or "").strip()) < 40):
            reasons.append("AI_BACKUP_COMPLETION_INVALID: blind author rationale required")
        unchanged = outputs == item.get("initial_output_manifest")
        if record.get("disposition") != ("NO_CHANGE" if unchanged else "CHANGED"):
            reasons.append("AI_BACKUP_COMPLETION_INVALID: disposition differs from output")
        if unchanged and not _verified_prompt_evidence(
                record.get("prompt_evidence"), prompt_text):
            reasons.append("AI_BACKUP_COMPLETION_INVALID: no-change needs prompt-bound evidence")
        if reasons:
            return None, reasons
        return {**record, "path": str(path),
                "record_sha256": hashlib.sha256(raw_record).hexdigest()}, []
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, reasons + [f"AI_BACKUP_COMPLETION_PENDING: {exc}"]


def _archive_backup_completion(item: dict, record: dict, run_p: Path) -> dict:
    """Preserve the exact signed input before Program normalizes any bytes."""
    root = (Path(run_p) / "ai_backup_completions" / item["task_sha256"] /
            record["record_sha256"])
    project = Path(item["project"])
    import benchmark_io_adapter as bio                  # noqa: PLC0415
    for row in record["output_manifest"]:
        relative = bio._public_relative(row["relative_path"])
        data = (project / "phase2" / "stage1" / "rtl" / relative).read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("AI_BACKUP_COMPLETION_PENDING: output changed before regating")
        bio._public_write_once(root / "files" / relative, data)
    _write_immutable_json(root / "author_record.json", record)
    return {"author_record": record, "input_root": str(root / "files"),
            "public_original_input": item["public_original_input"]}


def _make_ai_backup_task(problem_id: str, project: Path, skills: list[str],
                         source: str, detail: str, bench: str,
                         dataset: Path, run_p: Path,
                         required_top: str | None = None,
                         expected_public_input: dict | None = None) -> dict:
    """Build one prompt-bound handoff into the runner-owned RTL directory.

    `required_top` carries the module name the benchmark's SCORER will
    instantiate, when the benchmark fixes one. This is a LAYOUT fact from the
    registry, not design knowledge and not oracle content, and the author cannot
    always derive it: measured on VerilogEval-v2, 155 of 156 prompts state the
    name themselves and exactly ONE never mentions it, which is precisely the
    problem whose candidate came back named `chip_top` and was unscoreable.
    Refusing such an artefact without telling the author the required name would
    make the re-authoring loop unresolvable, so the requirement travels WITH the
    task."""
    project = Path(project).resolve()
    dataset = Path(dataset).resolve()
    run_p = Path(run_p).resolve()
    prompt = project / "input" / "phase1_prompt.md"
    prompt_text = prompt.read_text(errors="replace")
    import benchmark_io_adapter as bio                  # noqa: PLC0415
    task = {
        "schema": "vibeic.benchmark.ai_backup_task.v1",
        "id": str(problem_id),
        "project": str(project),
        # `skill` keeps the existing single-skill consumer compatible.  The
        # route declaration is ordered, so its first member is the primary;
        # `declared_skills` keeps every authorised alternative visible.
        "skill": skills[0],
        "declared_skills": list(skills),
        "handoff_source": source,
        "prompt_sha256": _sha256_text(prompt_text),
        "handoff_instance": uuid.uuid4().hex,
        "public_original_input": bio.public_original_input(
            project, problem_id, _sha256_text(prompt_text),
            expected=expected_public_input),
        "initial_output_manifest": _backup_output_manifest(project),
        "write_rtl_to": str(project / "phase2" / "stage1" / "rtl"),
        "read_docs_from": str(project / "phase1" / "generated_docs"),
        "read_prompt_from": str(prompt),
        "runner_said": str(detail or "")[:600],
        "regate_entry_step": "2",
        "review_required_after_regating": True,
        "completion_record_path": str(project / "phase2" / "stage1" /
                                      "ai_backup_author.json"),
        "completion_record_contract": {
            "schema": "vibeic.benchmark.ai_backup_record.v1",
            "required_bindings": ["id", "task_sha256", "prompt_sha256",
                                  "source_sha256", "output_manifest", "rtl_sha256"],
            "output_manifest": "sorted complete relative_path/sha256/bytes list under write_rtl_to",
            "rtl_sha256": "SHA256 of newline-joined sorted .sv/.v contents, as _candidate_text",
            "author": {"kind": "AI", "model": "<actual named author model>"},
            "oracle_accessed": False,
            "rationale": "<at least 40 characters explaining completed work>",
            "disposition": "CHANGED or explicit NO_CHANGE relative to initial_output_manifest",
            "prompt_evidence": "NO_CHANGE requires excerpt/supports as in AI repair/review evidence",
            "completion": "write this record only after all output files are complete; presence alone is pending",
        },
        # The scorer-facing top module name, when the benchmark fixes one.
        # Absent (None) for benchmarks that take the name from the description.
        "required_top_module": required_top,
        "required_top_module_note": (
            None if not required_top else
            f"This benchmark's scorer instantiates {required_top!r}. Declare the "
            f"top-level module with exactly that name. This is a benchmark "
            f"LAYOUT requirement, not design content — the prompt may not state "
            f"it, and an artefact that declares any other top name cannot be "
            f"elaborated by the grading testbench and will be refused."),
        "resume_with": (f"benchmark_dispatch.py {bench} --resume "
                        f"--dataset {dataset} --run {run_p}"),
    }
    task["public_original_input_paths"] = [
        str(project / "input" / "public_original" / "files" / row["relative_path"])
        for row in task["public_original_input"]["files"]]
    task["task_sha256"] = _sha256_text(json.dumps(task, sort_keys=True))
    _write_immutable_json(run_p / "ai_backup_tasks" /
                          f"{task['task_sha256']}.json", task)
    return task


def _prepare_general_solve_run(bench: str, dataset: Path, run_p: Path,
                               fmt: str, limit: int) -> None:
    """Create the clean-room envelope owned by the one general solve entry.

    The retired scaffold entry used to create this state separately and thereby
    left an authoring gap before score. Keeping creation inside ``--solve``
    makes it impossible to substitute a benchmark-local author between verbs.
    """
    dataset = Path(dataset).resolve()
    run_p = Path(run_p).resolve()
    if not dataset.exists():
        raise SystemExit(f"dataset path not found: {dataset}")
    existing = ([child for child in run_p.iterdir()
                 if child.name != _COORDINATOR_LOCK]
                if run_p.exists() else [])
    if existing:
        raise SystemExit(
            f"clean-room solve requires an empty fresh run directory: {run_p}")
    run_p.mkdir(parents=True, exist_ok=True)
    for child in ("projects", "responses", "reports", "transcripts"):
        (run_p / child).mkdir(parents=True, exist_ok=True)
    _atomic_write_json(run_p / ".bench_config.json", {
        "schema": "vibeic.benchmark.general_run.v1",
        "bench": bench,
        "format": fmt,
        "dataset": str(dataset),
        "clean_room": True,
        "full_dataset": limit == 0,
        "diagnostic_limit": int(limit or 0),
        "inherited_from": None,
        "seed_run": None,
        "reused_samples_from": None,
    })
    _render_lesson_digest(run_p)
    guard = Path(__file__).resolve().parent / "benchmark_clean_room_check.py"
    if guard.is_file() and limit == 0:
        rc = subprocess.call([sys.executable, str(guard), str(run_p)])
        if rc != 0:
            raise SystemExit(
                "clean-room guard failed while creating the general solve run")
    elif limit:
        print("NOTICE: --limit creates a diagnostic partial run; it cannot be "
              "scored or published as a benchmark result")


#: Where a coordinator records what it reconciled before it launched anything.
#: A run directory, never a committed artefact -- which is why the VERBATIM
#: refusal, repository and all, may live in it.
_RUNTIME_PAIR_RECORD = "runtime_pair_preflight.json"


def _write_runtime_pair_record(run_p: Path, record: dict) -> None:
    """Record the reconciliation where the run that used it can be read with it."""
    run_p.mkdir(parents=True, exist_ok=True)
    path = run_p / _RUNTIME_PAIR_RECORD
    if record.get("verdict") == _runtime_pair.RUNTIME_PAIR_MATCH and path.is_file():
        prior_text = path.read_text()
        try:
            prior = _strict_json_loads(prior_text)
        except ValueError:
            prior = None
        if isinstance(prior, dict) and prior.get("verdict") == _runtime_pair.RUNTIME_PAIR_MISMATCH:
            _write_immutable_text(run_p / "runtime_pair_refusals" /
                                  f"{_sha256_text(prior_text)}.json", prior_text)
    _atomic_write_json(path, record)
    if _read_json_regular(path) != record:
        raise ValueError("runtime pair persistence readback differs")


def _runtime_pair_before_fan_out(rows, run_p: Path, operation: str) -> int | None:
    """`None` to fan out over `rows`; `2` to launch ZERO workers.

    THE FAN-OUT SITE, for the coordinator whose fan-outs are CONDITIONAL.
    `--solve` always launches workers and asks the pair at its front door;
    `--resume` does not. Most of what resume does — accepting a review,
    refusing a re-entry under a stale source identity, writing a worklist — is
    bookkeeping that needs no container at all, and refusing all of it on the
    state of the machine would answer a routing question with a deployment one.

    An empty `rows` is NOT a fan-out: `_ordered_parallel_map` never enters the
    worker for it. Asking the pair there would make a resume with nothing to run
    depend on a container it was never going to use.
    """
    if not rows:
        return None
    rc, _record = _runtime_pair_gate(run_p, operation)
    return rc


def _runtime_pair_gate(run_p: Path, operation: str,
                       pristine: bool = False) -> tuple[int | None, dict]:
    """`(None, record)` to fan out; `(2, record)` to launch ZERO workers.

    THE PAIR IS ASKED BEFORE THE FIRST WORKER, and that placement is the whole
    fix. #2120: the pin required one digest, the shared container ran another
    build carrying the SAME version label, a freshly started MCP answered
    "16/16 checks passed" about it, and this dispatcher fanned out anyway. Every
    worker then recorded provenance about a container that was not the one the
    pin demands; the batch had to be stopped and excluded from results.

    Asking per worker would be worse, not better: N identical refusals, N
    partially-built projects, and a run root that has to be reasoned about
    before it can be thrown away. One question, before anything exists.

    A MISMATCH IS AN INFRASTRUCTURE VERDICT (`RUNTIME_INFRASTRUCTURE_NOT_READY`)
    and is recorded as one. No problem was attempted, so there is no design to
    FAIL and nothing for an AI repair task to repair -- charging a deployment's
    state to a design is how a machine problem becomes a score.

    `pristine` says the run root is still a clean room that has not been built
    yet. A refusal must not be the thing that stops the CORRECTED re-run: the
    record then goes to a SIBLING path, because dropping a file into the run
    root would make the next `--solve` refuse it as non-empty and the operator
    would read the clean-room message instead of the mismatch.
    """
    record = _runtime_pair.preflight()
    record["operation"] = operation
    if record["verdict"] == _runtime_pair.RUNTIME_PAIR_MATCH:
        if not pristine:
            try:
                _write_runtime_pair_record(run_p, record)
            except (OSError, ValueError) as exc:
                record.update(failure_class=_runtime_pair.RUNTIME_INFRASTRUCTURE_NOT_READY,
                              workers_launched=0, persistence_error=str(exc))
                print(f"RUNTIME_PAIR_PERSISTENCE_REFUSED: {exc}", file=sys.stderr)
                return 2, record
        print(_runtime_pair.pair_line(record))
        return None, record
    record["failure_class"] = _runtime_pair.RUNTIME_INFRASTRUCTURE_NOT_READY
    record["workers_launched"] = 0
    if pristine:
        with contextlib.suppress(OSError):
            _atomic_write_json(
                run_p.parent / f"{run_p.name}.{_RUNTIME_PAIR_RECORD}", record)
    else:
        with contextlib.suppress(OSError, ValueError):
            _write_runtime_pair_record(run_p, record)
    print(f"{_runtime_pair.RUNTIME_INFRASTRUCTURE_NOT_READY}: "
          f"{_runtime_pair.pair_line(record)}", file=sys.stderr)
    # VERBATIM. `_eda_pin` composed these; re-wording one would hand the reader
    # a summary of a mismatch instead of the mismatch itself.
    for line in record["evidence"]:
        print(line, file=sys.stderr)
    print(f"0 worker(s) launched; the runtime pair was reconciled before "
          f"fan-out and {record['disagreed']} disagreed. This is NOT a design "
          f"result: no problem was attempted.", file=sys.stderr)
    return 2, record


def _cmd_solve_locked(bench: str, dataset: str, run: str, limit: int = 0,
                      jobs: int = 1, heavy_jobs: int | None = None,
                      worker_threads: int = 0,
                      routed_tasks: list[dict] | None = None,
                      route_decisions: dict[str, dict] | None = None,
                      shape: str | None = None) -> int:
    """Solve every problem through the GENERAL flow.

    This verb did not exist. A separate scaffold prepared the run and
    `--score` scored, leaving a hole an agent filled by hand — how a 302-problem
    CVDP run came to be authored by a prompt->drafts->gate loop that RULE 0
    forbids, and scored 192/302 with no deterministic emit and no
    program-extracted spec.

    What happens per problem, and note that none of it is benchmark-specific:

        benchmark_io_adapter.stage   record/files -> a project (INPUT only;
                                     reading an oracle path RAISES)
        task_nature_route            input-only advisory proposal
        AI route handoff             hash-bound nature confirmation/override
        task_nature_route            confirmed nature -> general entry + exit
        vibe_ic_one_shot_runner      --entry-step <entry>, the one real runner
        benchmark_io_adapter.collect the artefact -> the scorer's shape

    The adapter is the thin IO shell § 0 permits; everything between IN and OUT
    is the flow a normal design task takes.
    """
    import subprocess                                    # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(HARNESS))
    import benchmark_io_adapter as bio                    # noqa: PLC0415
    import benchmark_entry_surface_check as bes           # noqa: PLC0415
    import flow_phase_attribution as fpa                  # noqa: PLC0415
    import task_nature_route as tnr                       # noqa: PLC0415
    import route_decision as rd                            # noqa: PLC0415

    entry_audit = bes.audit(Path(__file__).resolve().parents[1])
    if entry_audit.get("verdict") != "PASS":
        detail = "; ".join(
            f"{row.get('rule')}: {row.get('path')}"
            for row in entry_audit.get("findings") or [])
        print("ERROR: benchmark general-entry policy failed: " + detail,
              file=sys.stderr)
        return 2

    try:
        _assessors = _completeness_adapters()
        _assess_why = ""
    except Exception as exc:                              # noqa: BLE001
        _assessors, _assess_why = {}, f"UNAVAILABLE: {type(exc).__name__}: {exc}"

    fmt = _dispatch_format(bench, Path(run).resolve() if routed_tasks is not None
                           else None, shape)
    if fmt is None:
        print(f"ERROR: no IO adapter bound for {bench!r}. Known: "
              f"{sorted(_BENCH_FORMAT)}", file=sys.stderr)
        return 2

    ds, run_p = Path(dataset).resolve(), Path(run).resolve()
    fresh = routed_tasks is None
    gate_rc, pair_record = _runtime_pair_gate(
        run_p, "solve" if fresh else "resume:ai-route", pristine=fresh)
    if gate_rc is not None:
        return gate_rc
    if fresh:
        _prepare_general_solve_run(bench, ds, run_p, fmt, limit)
    else:
        config = _strict_json_loads((run_p / ".bench_config.json").read_text())
        if (config.get("bench") != bench or config.get("format") != fmt
                or config.get("dataset") != str(ds)
                or config.get("diagnostic_limit") != int(limit or 0)):
            print("ERROR: route continuation differs from original run", file=sys.stderr)
            return 2
    _write_runtime_pair_record(run_p, pair_record)
    runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"
    runner_budget = _RunnerBudget(jobs, heavy_jobs, worker_threads)
    if fresh:
        problem_rows = []
        problems = (_shape_d_problems(ds, run_p) if fmt == "agentic"
                    else bio.problems(fmt, ds))
        for index, prob in enumerate(problems):
            if limit and index >= limit:
                break
            problem_rows.append((index, prob))
    else:
        problem_rows = [(index, {"id": task["id"]})
                        for index, task in enumerate(routed_tasks)]
    problem_ids = [str(prob.get("id", f"problem-{index}"))
                   for index, prob in problem_rows]
    project_keys = [re.sub(r"[^\w.-]", "_", pid) for pid in problem_ids]
    if (len(set(problem_ids)) != len(problem_ids)
            or len(set(project_keys)) != len(project_keys)):
        print("ERROR: duplicate problem id or project-path collision in "
              "benchmark dataset", file=sys.stderr)
        return 2

    if fresh:
        route_tasks = []
        for index, prob in problem_rows:
            pid = problem_ids[index]
            proj = run_p / "projects" / _safe_problem_id(pid)
            proj.mkdir(parents=True, exist_ok=True)
            staged = bio.stage(fmt, prob, proj)
            prompt_text = (proj / "input" / "phase1_prompt.md").read_text(
                errors="replace")
            try:
                proposal = tnr.classify_task_nature(
                    prompt_text, fpa.rtl_present_at_input(proj), None)
            except Exception as exc:                       # noqa: BLE001
                # The Program router is advisory at this boundary. Its own
                # failure must not preclude an input-bound AI decision.
                proposal = {
                    "nature": None, "entry_nature": None,
                    "route": None, "plugin_entry": None,
                    "source": "router_error", "needs_ai_parse": True,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            route_tasks.append(_make_ai_route_task(
                pid, proj, staged, proposal, run_p, fmt, benchmark=bench,
                dataset_path=ds))
        _publish_route_input_anchor(
            run_p, _route_input_anchor(bench, fmt, ds, route_tasks))
        _write_jsonl(run_p / _ROUTE_WORKLIST, route_tasks)
        for name in (_BACKUP_WORKLIST, _REVIEW_WORKLIST, _REPAIR_WORKLIST):
            _write_jsonl(run_p / name, [])
        _atomic_write_json(run_p / "solve_report.json", {
            "bench": bench, "format": fmt, "dataset": str(ds),
            "solved": 0, "accepted": 0, "total": len(route_tasks),
            "routing_phase": "PENDING", "route_confirmed": 0,
            "acceptance_policy": {
                "required": True, "review_task_schema": _REVIEW_TASK_SCHEMA,
                "review_schema": _AI_REVIEW_SCHEMA,
                "score_gate": _ACCEPTANCE_REPORT,
            },
            "results": [{"id": task["id"], "accepted": False,
                         "candidate_ready": False,
                         "worker_status": "ROUTE_PENDING"}
                        for task in route_tasks],
        })
        _atomic_write_json(run_p / _ACCEPTANCE_REPORT, {
            "schema": _ACCEPTANCE_SCHEMA, "status": "PENDING",
            "accepted": 0, "total": len(route_tasks), "accepted_ids": [],
            "pending_routing": len(route_tasks),
        })
        print(f"{len(route_tasks)} input-only AI route task(s) -> "
              f"{run_p / _ROUTE_WORKLIST}; no design runner launched")
        return 2

    task_by_route_id = {str(task["id"]): task for task in routed_tasks}
    if (route_decisions is None
            or set(route_decisions) != set(problem_ids)
            or len(task_by_route_id) != len(routed_tasks)):
        print("ERROR: AI routes do not cover the issued input set", file=sys.stderr)
        return 2

    def _solve_one(row) -> _SolveWorkerOutcome:
        index, prob = row
        pid = str(prob.get("id", f"problem-{index}"))
        proj = run_p / "projects" / re.sub(r"[^\w.-]", "_", pid)
        staged_chars = 0
        nature = "NOT_MEASURED"
        entry = None
        ev = None
        exit_step = None
        verdict: dict = {}
        route_receipt = None
        activation = None
        effective_entry = None
        # Two facts a failing row must still report. The route-level
        # AI-backup declaration is a pure function of the routing verdict, so
        # it is known the moment routing returns; the Phase-1 front door's
        # verdict is known the moment it returns. Both live outside the try so
        # that a later failure -- a BLOCKED front door, a runner error --
        # reports the declaration it actually classified (UNDECLARED, INVALID
        # or DECLARED) and the front door that stopped it, instead of stamping
        # NOT_MEASURED over a determinate answer. NOT_MEASURED survives only
        # when the worker died before routing: the one case nobody looked.
        route_backup: dict = {"status": "NOT_MEASURED", "skills": []}
        phase1_frontdoor = None
        process = None
        argv: list[str] = []
        try:
            route_task = task_by_route_id[pid]
            if proj.resolve() != Path(route_task["project"]):
                raise ValueError("AI route project identity changed")
            staged = {"prompt_chars": route_task["prompt_chars"],
                      "public_original_input": route_task["public_original_input"]}
            staged_chars = int(staged.get("prompt_chars") or 0)

            # One detector, not a second inline copy: `input/rtl/` is only ONE
            # of the canonical places a design's input RTL arrives in.
            rtl_present = fpa.rtl_present_at_input(proj)
            prompt_text = (proj / "input" / "phase1_prompt.md").read_text(
                errors="replace")

            # Completeness is disclosure only; it never selects a solver.
            completeness = _assess_why or "NOT_ADAPTED"
            assess = _assessors.get(fmt)
            if assess is not None:
                try:
                    completeness = assess(prompt_text).get("completeness", "?")
                except Exception as exc:                  # noqa: BLE001
                    completeness = (
                        f"UNAVAILABLE: {type(exc).__name__}: {exc}")

            verdict = route_decisions[pid]
            nature = verdict["nature"]
            route_receipt = verdict.get("route_receipt")
            if not isinstance(route_receipt, dict):
                raise ValueError("ROUTE_RECEIPT_MISSING")
            receipt_errors = rd.validate_route_receipt(route_receipt)
            if receipt_errors:
                raise ValueError("ROUTE_RECEIPT_INVALID: " + ", ".join(receipt_errors))
            run_scope = uuid.uuid4().hex
            _publish_current_receipt(
                proj, "route_decision", route_receipt,
                digest_field="receipt_sha256",
                run_id=f"{route_task['task_sha256']}:route:{run_scope}")
            current_route = _read_current_receipt(proj, "route_decision")
            if (current_route["receipt"].get("receipt_sha256")
                    != route_receipt.get("receipt_sha256")):
                raise ValueError("ROUTE_RECEIPT_CURRENT_POINTER_MISMATCH")
            # `entry_step` and `verify_through` are derived by the Program
            # receipt. The semantic reviewer never supplies or overrides them.
            entry = str(route_receipt["entry_step"])
            ev = str(route_receipt["requested_evidence"])
            exit_step = str(route_receipt["verify_through"])
            route_backup = _declared_route_ai_backup(verdict)
            # Every accepted response is normalized into the Program receipt,
            # and every newly executed route crosses the same two-stage D1
            # barrier.  Response shape cannot opt into a legacy bypass.
            phase1_frontdoor, pending, activation = _activate_route_d1(
                proj, route_task, route_receipt, runner, runner_budget,
                run_scope=run_scope,
                delivery_route=str(verdict.get("delivery_route") or "ip"))
            if entry == "D1":
                nature_row = tnr.NATURE_ENTRY[verdict["entry_nature"]]
                candidates = [str(x) for x in nature_row.get("then") or []]
                order = {sid: i for i, sid in enumerate(rd.canonical_dag()["steps"])}
                effective_entry = next(
                    (sid for sid in candidates
                     if sid in order and order[sid] <= order[exit_step]), None)
            else:
                effective_entry = entry
            rd.require_d1_activation(
                activation, route_receipt, task_sha256=route_task["task_sha256"],
                ldoc_root_handle=_sha256_text(str((proj / "phase1" / "generated_docs").resolve())))
            planned_snapshot = _validate_live_d1_for_launch(
                proj, route_receipt, activation, route_task["task_sha256"])
            admitted_steps = rd.admit_route_closure(
                pending=pending, activation=activation,
                route_receipt=route_receipt,
                task_sha256=route_task["task_sha256"],
                source_sha256=route_receipt["source_sha256"],
                ldoc_root_handle=_sha256_text(
                    str((proj / "phase1" / "generated_docs").resolve())))
            if effective_entry is None:
                # A D1-only proof still has a receipt and activation but no
                # downstream runner span to launch.
                process = _ProcessOutcome(rc=0, stdout="", stderr="")
                got = {"ok": True, "completion": "", "rtl_gen": None}
                rc = 0
            else:
                argv = _solver_argv(
                    runner, proj, effective_entry, exit_step,
                    str(verdict.get("delivery_route") or "ip"))
                d1_snapshot = _capture_d1_evidence(proj)
                if d1_snapshot.digest != planned_snapshot.digest:
                    raise ValueError("D1_SNAPSHOT_PLANNED_GENERATION_CHANGED")
                process = _run_from_d1_snapshot(
                    runner_budget, argv, d1_snapshot, route_receipt, activation,
                    route_task["task_sha256"])
                if process.error is not None:
                    raise RuntimeError(process.error)
                rc = int(process.rc)
                got = _collect_runner_result(
                    process, argv, fmt, pid, proj,
                    required_top=_required_scorer_top(_entry(bench), fmt))
            diagnostic = got.get("runner_diagnostics")
            pre_gate_blocked = bool(diagnostic and diagnostic.get("reason"))
            waive = None if pre_gate_blocked else _rtl_gen_waive(proj)
            backup_source = None
            backup_skills: list[str] = []
            backup_detail = ""
            if not got.get("ok") and not pre_gate_blocked:
                if waive:
                    backup_source = "rtl_gen_waive"
                    backup_skills = [str(waive.get("fallback_skill"))]
                    backup_detail = str(waive.get("detail") or "")
                elif route_backup["status"] == "DECLARED":
                    backup_source = "route_declaration"
                    backup_skills = list(route_backup["skills"])
                    backup_detail = str(got.get("reason") or "")
            awaiting_backup = bool(backup_source)
            phases = fpa.attribute(
                proj, routing=verdict, entry=entry, evidence=ev,
                exit_step=exit_step, rtl_present=rtl_present,
                artefact_collected=bool(got.get("ok")))
            if pre_gate_blocked:
                phases = _phase_error_attribution()
                for phase in phases.values():
                    phase["reason"] = diagnostic["reason_class"]
            result = {
                "id": pid, "nature": nature,
                "entry": entry, "evidence": ev, "exit": exit_step,
                "rc": rc,
                "runner_invocation": getattr(process, "invocation", None),
                "ok": bool(got.get("ok")),
                "candidate_ready": bool(got.get("ok")),
                "accepted": False, "staged": staged_chars,
                "completeness": completeness,
                "routing_verdict": verdict, "phases": phases,
                "public_original_input": staged["public_original_input"],
                "phase1_frontdoor": phase1_frontdoor,
                "route_receipt": route_receipt,
                "delivery_route": verdict.get("delivery_route") or "ip",
                "d1_activation": activation,
                "effective_entry": effective_entry,
                "admitted_steps": admitted_steps,
                "candidate_origin": (
                    "PROGRAM" if got.get("ok") else
                    ("AI_BACKUP_PENDING" if awaiting_backup else "NONE")),
                "route_ai_backup": route_backup,
                "program_first_ai_review": {"status": "PENDING"},
                "ai_repair_required": False,
                "awaiting_ai_review": bool(got.get("ok")),
                "awaiting_ai_backup": awaiting_backup,
                "awaiting_ai": bool(got.get("ok") or awaiting_backup),
            }
            if diagnostic:
                result["runner_diagnostics"] = diagnostic
            review_task = None
            backup_task = None
            if got.get("ok"):
                review_task = _make_ai_review_task(
                    pid, proj, got, verdict, rc, run_p, "PROGRAM",
                    program_phases=phases,
                    runner_invocation=getattr(process, "invocation", None),
                    expected_public_input=staged["public_original_input"])
                result["review_task"] = review_task["review_path"]
                p1 = (phases.get("phase1_routing") or {})
                p1["needs_ai_parse_consumed_by"] = (
                    "blind Program First AI review at "
                    f"{review_task['review_path']}")
            elif awaiting_backup:
                backup_task = _make_ai_backup_task(
                    pid, proj, backup_skills, str(backup_source),
                    backup_detail, bench, ds, run_p,
                    required_top=_required_scorer_top(_entry(bench), fmt),
                    expected_public_input=staged["public_original_input"])
            state = ("candidate->AI-review" if got.get("ok")
                     else ("WAIVE->AI" if backup_source == "rtl_gen_waive"
                           else ("route-declared->AI" if awaiting_backup
                                 else "no-rtl")))
            log_line = (f"  {pid:44s} {nature:22s} entry={str(entry):3s} "
                        f"exit={str(exit_step):4s} rc={rc} {state}")
            if pre_gate_blocked:
                log_line += f" {diagnostic['reason']}"
            return _SolveWorkerOutcome(
                index=index, problem_id=pid,
                result_json=json.dumps(result),
                review_task_json=(json.dumps(review_task)
                                  if review_task else None),
                backup_task_json=(json.dumps(backup_task)
                                  if backup_task else None),
                log_line=log_line)
        except Exception as exc:                          # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            result = {
                "id": pid,
                "nature": nature, "entry": entry,
                "evidence": ev, "exit": exit_step,
                "rc": process.rc if process and process.error else None,
                "runner_invocation": (getattr(process, "invocation", None)
                                      or (phase1_frontdoor or {}).get("runner_invocation")),
                "worker_status": "ERROR", "worker_error": error,
                "worker_retryable": (
                    proj / "input" / "phase1_prompt.md").is_file(),
                "ok": False, "candidate_ready": False, "accepted": False,
                "staged": staged_chars,
                "completeness": "NOT_MEASURED: WORKER_ERROR",
                "routing_verdict": verdict,
                "phases": _phase_error_attribution(),
                "phase1_frontdoor": phase1_frontdoor,
                "route_receipt": route_receipt,
                "delivery_route": verdict.get("delivery_route") or "ip",
                "d1_activation": activation,
                "effective_entry": effective_entry,
                "candidate_origin": "NONE",
                "route_ai_backup": route_backup,
                "program_first_ai_review": {"status": "NOT_MEASURED"},
                "ai_repair_required": False,
                "awaiting_ai_review": False,
                "awaiting_ai_backup": False, "awaiting_ai": False,
            }
            if process is not None:
                diagnostic = _runner_diagnostics(process, argv, proj)
                if diagnostic:
                    result["runner_diagnostics"] = diagnostic
            return _SolveWorkerOutcome(
                index=index, problem_id=pid,
                result_json=json.dumps(result),
                review_task_json=None, backup_task_json=None,
                log_line=(f"  {pid:44s} NOT_MEASURED worker ERROR: {error}"))

    outcomes = _ordered_parallel_map(problem_rows, _solve_one, jobs)
    results: list[dict] = []
    backlog: list[dict] = []
    review_tasks: list[dict] = []
    for outcome in outcomes:
        result = _strict_json_loads(outcome.result_json)
        results.append(result)
        if outcome.review_task_json:
            review_tasks.append(_strict_json_loads(outcome.review_task_json))
        if outcome.backup_task_json:
            backlog.append(_strict_json_loads(outcome.backup_task_json))
        print(outcome.log_line)

    if backlog:
        # THE HAND-OFF. A program cannot call a language model, so the honest
        # shape is not "the solver silently did nothing" but a WORK-LIST plus a
        # resume command. The runner has already emitted L1-L27 for each of
        # these and named the skill it waived to; the AI authors into the
        # runner's OWN tree (phase2/stage1/rtl/) and `--resume` re-invokes the
        # runner so ITS gates fire on that RTL. That is the runner's designed
        # AI-backup, not a bypass of it: nothing here writes a scoring artefact.
        bl = run_p / _BACKUP_WORKLIST
        _write_jsonl(bl, backlog)
        print(f"\n{len(backlog)} problem(s) handed to a declared AI skill -> {bl}")
        print(f"  author RTL into each project's phase2/stage1/rtl/, then:")
        print(f"    python3 {Path(__file__).name} {bench} --resume "
              f"--dataset {ds} --run {run_p}")
    else:
        _write_jsonl(run_p / _BACKUP_WORKLIST, [])

    _write_jsonl(run_p / _REVIEW_WORKLIST, review_tasks)
    if review_tasks:
        print(f"\n{len(review_tasks)} program candidate(s) require blind AI "
              f"semantic review -> {run_p / _REVIEW_WORKLIST}")
        print("  write each schema-bound review to its review_path, then run --resume")
    # The completeness roll-up carries its own denominator: "3 SPEC_ABSENT" out
    # of an unstated population is the shape this repo refuses everywhere else.
    comp_counts: dict = {}
    for r in results:
        comp_counts[r.get("completeness", "?")] = comp_counts.get(r.get("completeness", "?"), 0) + 1
    solve_report = {
        "bench": bench, "format": fmt, "dataset": str(ds),
        "solved": sum(1 for r in results if r["ok"]),
        "accepted": 0, "total": len(results),
        "routing_phase": "COMPLETE", "route_confirmed": len(results),
        "acceptance_policy": {
            "required": True,
            "rule": ("runner-owned RTL gate PASS (or supplied-RTL re-entry), "
                     "exact overall runner rc preserved, blocking sole-emit "
                     "compile/guards PASS, AND blind AI semantic PASS; AI route "
                     "may AGREE or evidence-backed OVERRIDE_PROGRAM"),
            "semantic_authority": "AI",
            "program_disagreement": (
                "AI must prove the issue with a prompt-derived executable test "
                "that the frozen Program candidate fails; repair must pass the "
                "same immutable test, runner-owned RTL gate, blocking sole-emit "
                "compile/guards, and a fresh AI review"),
            "review_task_schema": _REVIEW_TASK_SCHEMA,
            "review_schema": _AI_REVIEW_SCHEMA,
            "score_gate": _ACCEPTANCE_REPORT,
        },
        "completeness_counts": comp_counts,
        "completeness_assessed_of":
            f"{sum(comp_counts.get(k, 0) for k in comp_counts if not k.startswith(('UNAVAILABLE', 'NOT_ADAPTED')))} of {len(results)}",
        "four_phase_summary": _four_phase_rollup(fpa, results),
        "results": results,
    }
    _atomic_write_json(run_p / "solve_report.json", solve_report)
    _atomic_write_json(run_p / _ACCEPTANCE_REPORT, {
        "schema": _ACCEPTANCE_SCHEMA, "status": "PENDING",
        "accepted": 0, "total": len(results), "accepted_ids": [],
    })
    ok = sum(1 for r in results if r["ok"])
    waiting = sum(1 for r in results if r.get("awaiting_ai"))
    unmeasured = any(
        r.get("worker_status") == "ERROR"
        or any(isinstance(row, Mapping) and row.get("status") == "NOT_MEASURED"
               for row in (r.get("phases") or {}).values())
        for r in results)
    print(f"\n{ok}/{len(results)} produced a gated candidate; 0 accepted"
          + (f", {waiting} awaiting AI review/backup" if waiting else "")
          + f" -> {run_p}/solve_report.json")
    # 2 = handed off, not failed. Even when every PROGRAM candidate exists, no
    # response is accepted until the blind AI review agrees.
    return 2 if results and (waiting == len(results) or unmeasured) else 1


def cmd_solve(bench: str, dataset: str, run: str, limit: int = 0,
              jobs: int = 1, heavy_jobs: int | None = None,
              worker_threads: int = 0, shape: str | None = None) -> int:
    """Run the sole solve coordinator under an exclusive run-root lock."""
    try:
        with _run_root_coordinator_lock(Path(run), "solve"):
            return _cmd_solve_locked(
                bench, dataset, run, limit=limit, jobs=jobs,
                heavy_jobs=heavy_jobs, worker_threads=worker_threads,
                shape=shape)
    except _CoordinatorBusy as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _cmd_resume_locked(bench: str, dataset: str, run: str,
                       jobs: int = 1, heavy_jobs: int | None = None,
                       worker_threads: int = 0) -> int:
    """Advance Program First / AI Review work and publish only acceptances.

    PROGRAM emits first. A runner WAIVE or a valid route-level declaration may
    authorise AI backup for a missing initial candidate. Every gated candidate
    then receives a blind AI route + semantic review. AI may reject only with a
    prompt-derived test that the frozen candidate actually fails; a repair must
    pass that same immutable test plus PROGRAM gates and a fresh review. A
    changed prompt is never legitimised by refresh.
    """
    import subprocess                                    # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import benchmark_io_adapter as bio                    # noqa: PLC0415
    import flow_phase_attribution as fpa                  # noqa: PLC0415

    run_p = Path(run).resolve()
    solve_p = run_p / "solve_report.json"
    if not solve_p.is_file():
        print(f"ERROR: no solve report at {solve_p} — run --solve first",
              file=sys.stderr)
        return 2
    try:
        solve = _strict_json_loads(solve_p.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: unreadable solve report {solve_p}: {exc}",
              file=sys.stderr)
        return 2
    policy = solve.get("acceptance_policy") or {}
    if (policy.get("required") is not True
            or policy.get("review_task_schema") != _REVIEW_TASK_SCHEMA
            or policy.get("review_schema") != _AI_REVIEW_SCHEMA):
        print("ERROR: this solve predates the current Program First + AI Review "
              "proof schemas; start a fresh --solve run", file=sys.stderr)
        return 2
    fmt = _dispatch_format(bench, run_p)
    if fmt is None:
        print(f"ERROR: no IO adapter bound for {bench!r}", file=sys.stderr)
        return 2
    if solve.get("routing_phase") == "PENDING":
        try:
            route_tasks = _read_jsonl(run_p / _ROUTE_WORKLIST)
            config = _strict_json_loads((run_p / ".bench_config.json").read_text())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR: AI route worklist unreadable: {exc}", file=sys.stderr)
            return 2
        if (len(route_tasks) != solve.get("total")
                or [task.get("id") for task in route_tasks] !=
                [row.get("id") for row in solve.get("results") or []]):
            print("ERROR: AI route worklist differs from issued solve population",
                  file=sys.stderr)
            return 2
        try:
            _validate_route_input_anchor(bench, fmt, Path(dataset).resolve(),
                                         run_p, route_tasks)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            print(f"ERROR: AI route input anchor refused: {exc}", file=sys.stderr)
            return 2
        decisions = {}
        pending = []
        for task in route_tasks:
            decision, reasons = _validate_ai_route(
                task, run_p, benchmark=bench, dataset=Path(dataset).resolve())
            if decision is None:
                pending.append((task.get("id"), reasons))
            else:
                decisions[str(task["id"])] = decision
        if pending:
            for pid, reasons in pending:
                print(f"  {pid}: {'; '.join(reasons)}")
            print(f"{len(pending)}/{len(route_tasks)} AI route(s) pending; "
                  "zero design runners launched")
            return 2
        return _cmd_solve_locked(
            bench, dataset, run, limit=int(config.get("diagnostic_limit") or 0),
            jobs=jobs, heavy_jobs=heavy_jobs, worker_threads=worker_threads,
            routed_tasks=route_tasks, route_decisions=decisions)
    runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"
    runner_budget = _RunnerBudget(jobs, heavy_jobs, worker_threads)

    try:
        backup = _read_jsonl(run_p / _BACKUP_WORKLIST)
        review_tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
        prior_enhancements = _read_jsonl(run_p / _ENHANCEMENT_WORKLIST)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    results = solve.get("results") or []
    result_by_id = {str(r.get("id")): r for r in results}
    task_by_id = {str(t.get("id")): t for t in review_tasks}
    if len(result_by_id) != len(results) or len(task_by_id) != len(review_tasks):
        print("ERROR: duplicate problem id in solve report or review worklist",
              file=sys.stderr)
        return 2
    # Review-only resume can execute proofs without a worker fan-out. Refresh
    # before repair planning, which itself adjudicates inherited challenges.
    # Questions and absent reviews remain no-execution bookkeeping.
    for task in review_tasks:
        try:
            review = _read_json_regular(Path(str(task.get("review_path") or "")))
        except (OSError, ValueError):
            continue
        semantic = review.get("semantic_review") if isinstance(review, dict) else None
        if (not isinstance(semantic, dict)
                or semantic.get("verdict") == "NEEDS_CLARIFICATION"
                or not (review.get("verification_test") or task.get("verification_challenges"))):
            continue
        declaration = _challenge_execution_for_task(task)
        if not isinstance(declaration, dict) or declaration.get("backend") != "native":
            continue
        try:
            frozen = _frozen_native_challenge_identity(run_p)
        except (OSError, ValueError):
            continue  # The consumer records UNAVAILABLE; never recover corruption.
        if frozen is None:
            gate_rc, _ = _runtime_pair_gate(run_p, "resume:review")
            if gate_rc is not None:
                return gate_rc
        break
    try:
        route_worklist = _read_jsonl(run_p / _ROUTE_WORKLIST)
    except ValueError:
        route_worklist = []
    route_task_by_id = {str(t.get("id")): t for t in route_worklist}

    planned_d1_snapshots: dict[str, _D1EvidenceSnapshot] = {}

    def _route_reentry_state(pid: str, result: dict, *, allow_d1_only: bool,
                             d1_snapshot=None) -> dict:
        return _validated_route_reentry_state(
            bench=bench, dataset=dataset, fmt=fmt, run_p=run_p, pid=str(pid),
            result=result, route_worklist=list(route_worklist),
            allow_d1_only=allow_d1_only, supplied_rtl=False,
            snapshot_sink=planned_d1_snapshots, d1_snapshot=d1_snapshot)

    refreshed_obligation_ids = [
        pid for pid, task in task_by_id.items()
        if _refresh_program_review_obligations(task)
    ]
    if refreshed_obligation_ids:
        print("  refreshed deterministic review obligations for "
              f"{len(refreshed_obligation_ids)} unchanged candidate(s): "
              + ", ".join(refreshed_obligation_ids))

    # Old mid-flow runs could route debug/optimization correctly yet skip the
    # canonical Phase-1 provenance pass altogether. Repair that missing
    # program evidence before any candidate is (re-)accepted. A provenance
    # record that once existed and later changed is never regenerated here;
    # that is tampering/staleness and remains blocking.
    #
    # THE REFUSAL IS SCOPED TO ACCEPTANCE, WHICH IS WHAT #2012 SAID.
    # This pass used to `return 2` for the WHOLE run the moment any candidate
    # came up short, before a single repair or backup task had been written.
    # "A candidate must not be ACCEPTED without canonical Phase-1 provenance"
    # and "no candidate in this run may be routed" are different statements,
    # and only the first one is the invariant. Measured consequences of the
    # second, all three on origin/main sources:
    #   * a --resume whose results are all still awaiting AI backup returned 2
    #     with an EMPTY needs_ai_repair.jsonl and needs_ai_backup.jsonl -- the
    #     worklists the AI half of the loop reads;
    #   * one worker crashing took the HEALTHY sibling's routing down with it,
    #     because that sibling's own provenance was equally absent;
    #   * a candidate whose review had already come back REPAIR_REQUIRED was
    #     never routed for repair, so the loop had no way forward at all.
    # The blocked candidates are recorded here and refused AT THE ACCEPT SITE
    # below, which is the single place `accepted` is ever set True.
    import emit_attestation as emit_attestation          # noqa: PLC0415
    phase1_blocked: dict[str, str] = {}
    for result in results:
        pid = str(result.get("id"))
        if (result.get("worker_status") == "ERROR"
                and result.get("worker_retryable") is True):
            # There is no Program outcome to guard yet: this result is owed
            # the retry below, which re-enters at its routed entry and emits
            # the provenance the next --resume binds and checks. Refusing it
            # here made a D1 worker crash unrecoverable except by a fresh
            # --solve that discards every other committed result -- the very
            # loss the retry exists to prevent.
            continue
        proj = run_p / "projects" / re.sub(r"[^\w.-]", "_", pid)
        task = task_by_id.get(pid)
        expected = (task.get("phase1_provenance")
                    if isinstance(task, dict) else None)
        current = emit_attestation.phase1_provenance(proj)
        if isinstance(expected, dict) and expected.get("ran") is True:
            if current != expected:
                phase1_blocked[pid] = (
                    "Phase-1 provenance changed after task creation")
            continue
        if result.get("entry") == "D1" and current.get("ran") is not True:
            # Judged by what the run EMITTED, not by what the task recorded.
            # A task written before provenance was carried, or not written
            # at all yet (awaiting AI backup), says nothing about the L-docs
            # on disk; when they are there the front door below REUSES them
            # without a runner call and binds them into the task. Only a D1
            # run that truly left none is refused, and the message is then
            # a measured fact rather than a missing field.
            phase1_blocked[pid] = (
                "canonical D1-entry run emitted no Phase-1 provenance")
            continue
        admission = _route_reentry_state(pid, result, allow_d1_only=False)
        if admission.get("status") != "ACTIVE":
            phase1_blocked[pid] = str(admission.get("reason") or "ROUTE_REENTRY_REFUSED")
            continue
        frontdoor = _ensure_phase1_frontdoor(runner, proj, runner_budget)
        if frontdoor.get("status") == "BLOCKED":
            phase1_blocked[pid] = str(
                frontdoor.get("reason") or "Phase-1 front door blocked")
            continue
        current = frontdoor["provenance"]
        result["phase1_frontdoor"] = frontdoor
        if isinstance(task, dict):
            task["phase1_provenance"] = current
    def _run_and_collect(job) -> _ResumeRunnerOutcome:
        pid, proj, supplied_rtl, entry, exit_step, *extra = job
        collect_kwargs = extra.pop() if extra and isinstance(extra[-1], dict) else {}
        expected_repaired_output_sha256 = collect_kwargs.pop(
            "expected_repaired_output_sha256", None)
        delivery_route = extra[0] if extra else "ip"
        d1_only = extra[1] if len(extra) > 1 else False
        if d1_only:
            state = _route_reentry_state(str(pid), result_by_id.get(str(pid)) or {},
                                         allow_d1_only=True)
            if state.get("status") != "D1_ONLY":
                return _ResumeRunnerOutcome(
                    problem_id=pid, rc=None, collected_json=None,
                    error=str(state.get("reason") or "D1_ONLY_REENTRY_REFUSED"))
            latest = proj / "reports" / "orchestrator" / "runner_invocations" / "latest.json"
            prior_latest = latest.read_bytes() if latest.is_file() else None
            try:
                frontdoor, _, _ = _activate_route_d1(
                    proj, state["task"], state["route_receipt"], runner, runner_budget,
                    delivery_route=delivery_route)
            except Exception as exc:                     # noqa: BLE001
                invocation = None
                if latest.is_file() and latest.read_bytes() != prior_latest:
                    pointer = _read_json_regular(latest)
                    record = latest.parent / f"{pointer['invocation_id']}.json"
                    if record.is_file():
                        invocation = _read_json_regular(record)
                return _ResumeRunnerOutcome(
                    problem_id=pid, rc=(invocation or {}).get("rc"), collected_json=None,
                    error=f"D1_ONLY_REENTRY_REFUSED: {exc}", invocation=invocation)
            return _ResumeRunnerOutcome(
                problem_id=pid, rc=frontdoor.get("runner_rc"), collected_json=None,
                error="D1_ONLY_REENTRY_COMPLETED_WITHOUT_DOWNSTREAM_SPAN",
                invocation=frontdoor.get("runner_invocation"))
        # The caller performs a state check before constructing a job. Repeat
        # it here at the actual fan-out seam so a pointer/anchor mutation after
        # planning cannot turn a valid plan into a later-span bypass.
        d1_snapshot = _capture_d1_evidence(proj)
        state = _route_reentry_state(str(pid), result_by_id.get(str(pid)) or {},
                                     allow_d1_only=False, d1_snapshot=d1_snapshot)
        if state.get("status") != "ACTIVE":
            return _ResumeRunnerOutcome(
                problem_id=pid, rc=None, collected_json=None,
                error=str(state.get("reason") or "ROUTE_REENTRY_REFUSED"))
        if expected_repaired_output_sha256 is not None:
            try:
                current_output_sha256 = _runner_material_snapshot(proj).get(
                    "output_rtl_sha256")
            except (OSError, ValueError, TypeError) as exc:
                return _ResumeRunnerOutcome(
                    problem_id=pid, rc=None, collected_json=None,
                    error=f"RUNNER_MATERIAL_UNBOUND: unable to recheck repaired RTL: {exc}")
            if current_output_sha256 != expected_repaired_output_sha256:
                return _ResumeRunnerOutcome(
                    problem_id=pid, rc=None, collected_json=None,
                    error=("RUNNER_MATERIAL_UNBOUND: repaired RTL changed "
                           "after repair admission"))
        # AI backup/repair has already authored the candidate. Re-enter at the
        # first RTL-validation step so program-first does not author again and
        # overwrite the hash whose semantics the AI just repaired. The routed
        # exit still applies; otherwise resume expands a step-2/4 task into LEC.
        argv = _resume_solver_argv(
            runner, proj, supplied_rtl, state["entry_step"],
            state["exit_step"], state["delivery_route"])
        process = _run_from_d1_snapshot(
            runner_budget, argv, d1_snapshot, state["route_receipt"],
            state["activation"], state["task"]["task_sha256"],
            expected_repaired_output_sha256=expected_repaired_output_sha256)
        diagnostic = _runner_diagnostics(process, argv, proj)
        diagnostics_json = json.dumps(diagnostic) if diagnostic else None
        if process.error is not None:
            return _ResumeRunnerOutcome(
                problem_id=pid, rc=process.rc, collected_json=None,
                error=process.error, diagnostics_json=diagnostics_json,
                invocation=getattr(process, "invocation", None))
        try:
            got = _collect_runner_result(
                process, argv, fmt, pid, proj, supplied_rtl=supplied_rtl,
                **collect_kwargs,
                required_top=_required_scorer_top(_entry(bench), fmt))
            payload = json.dumps(got)
        except Exception as exc:                          # noqa: BLE001
            return _ResumeRunnerOutcome(
                problem_id=pid, rc=process.rc, collected_json=None,
                error=f"{type(exc).__name__}: {exc}", diagnostics_json=diagnostics_json,
                invocation=getattr(process, "invocation", None))
        return _ResumeRunnerOutcome(
            problem_id=pid, rc=process.rc, collected_json=payload, error=None,
            invocation=getattr(process, "invocation", None))

    def _refresh_result(result: dict, proj: Path, rc: int, got: dict) -> None:
        routing = result.get("routing_verdict") or {}
        phases = fpa.attribute(
            proj, routing=routing, entry=result.get("entry"),
            evidence=result.get("evidence"), exit_step=result.get("exit"),
            rtl_present=fpa.rtl_present_at_input(proj),
            artefact_collected=bool(got.get("ok")))
        diagnostic = got.get("runner_diagnostics")
        result.pop("runner_diagnostics", None)
        if diagnostic:
            result["runner_diagnostics"] = diagnostic
            if diagnostic.get("reason"):
                phases = _phase_error_attribution()
                for phase in phases.values():
                    phase["reason"] = diagnostic["reason_class"]
        result.update({
            "rc": rc,
            "ok": bool(got.get("ok")),
            "candidate_ready": bool(got.get("ok")),
            "accepted": False,
            "phases": phases,
            "awaiting_ai_backup": False,
            "awaiting_ai_review": bool(got.get("ok")),
            "awaiting_ai": bool(got.get("ok")),
        })
        result.pop("worker_status", None)
        result.pop("worker_error", None)
        result.pop("worker_retryable", None)

    repairs: list[dict] = []
    remaining_backup: list[dict] = []
    refreshed: set[str] = set()
    enhancement_by_key = {
        (str(row.get("id")), str(row.get("prompt_sha256")),
         str(row.get("rtl_sha256")), str(row.get("semantic_verdict"))): row
        for row in prior_enhancements
    }

    # A process-level worker error is not converted into a design verdict.
    # The staged project stays in the run root and --resume retries exactly
    # that Program invocation; successful projects already committed in the
    # solve report are never discarded or re-authored.
    retry_plans = []
    retry_blocked = []
    for result in results:
        if (result.get("worker_status") == "ERROR"
                and result.get("worker_retryable") is True):
            pid = str(result.get("id"))
            reentry_state = _route_reentry_state(pid, result, allow_d1_only=True)
            if reentry_state.get("status") == "REFUSED":
                retry_blocked.append((pid, str(reentry_state.get("reason"))))
                result.update({"accepted": False, "candidate_ready": False,
                               "worker_error": str(reentry_state.get("reason")),
                               "worker_retryable": False})
                continue
            retry_plans.append({
                "id": pid, "result": result,
                "project": (run_p / "projects" /
                            re.sub(r"[^\w.-]", "_", pid)),
                "reentry_state": reentry_state,
            })
    for pid, reason in retry_blocked:
        repairs.append({"id": pid, "status": "ROUTE_REENTRY_BLOCKED",
                        "reasons": [reason]})
    gate_rc = _runtime_pair_before_fan_out(retry_plans, run_p, "resume:retry")
    if gate_rc is not None:
        return gate_rc
    retry_outcomes = _ordered_parallel_map(
        [(p["id"], p["project"], False, p["result"].get("entry"),
          p["result"].get("exit"), p["result"].get("delivery_route", "ip"),
          p["reentry_state"].get("status") == "D1_ONLY")
         for p in retry_plans], _run_and_collect, jobs)
    existing_backup_ids = {str(item.get("id")) for item in backup}
    for plan, outcome in zip(retry_plans, retry_outcomes):
        pid = plan["id"]
        result = plan["result"]
        proj = plan["project"]
        if outcome.error is not None:
            result.pop("runner_diagnostics", None)
            if outcome.diagnostics_json:
                result["runner_diagnostics"] = _strict_json_loads(outcome.diagnostics_json)
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj),
                "status": "PROJECT_WORKER_ERROR",
                "reasons": [outcome.error],
                "required_next": (
                    "fix the named worker failure and run --resume again; "
                    "other coordinator-committed project results are retained"),
            })
            result.update({"rc": outcome.rc, "worker_status": "ERROR",
                           "worker_error": outcome.error, "runner_invocation": outcome.invocation,
                           "ok": False, "candidate_ready": False, "accepted": False})
            print(f"  {pid:44s} Program worker retry ERROR: {outcome.error}")
            continue
        rc = int(outcome.rc)
        got = _strict_json_loads(str(outcome.collected_json))
        _refresh_result(result, proj, rc, got)
        result["runner_invocation"] = outcome.invocation
        if got.get("ok"):
            task = _make_ai_review_task(
                pid, proj, got, result.get("routing_verdict") or {}, rc,
                run_p, "PROGRAM", program_phases=result.get("phases"),
                runner_invocation=outcome.invocation,
                expected_public_input=result.get("public_original_input"))
            task_by_id[pid] = task
            result.update({
                "review_task": task["review_path"],
                "candidate_origin": "PROGRAM",
                "awaiting_ai_review": True, "awaiting_ai": True,
            })
            refreshed.add(pid)
            print(f"  {pid:44s} Program worker retry completed; "
                  "fresh AI review required")
            continue
        waive = _rtl_gen_waive(proj)
        route_backup = _declared_route_ai_backup(
            result.get("routing_verdict") or {})
        backup_source = None
        backup_skills: list[str] = []
        backup_detail = ""
        if waive:
            backup_source = "rtl_gen_waive"
            backup_skills = [str(waive.get("fallback_skill"))]
            backup_detail = str(waive.get("detail") or "")
        elif route_backup["status"] == "DECLARED":
            backup_source = "route_declaration"
            backup_skills = list(route_backup["skills"])
            backup_detail = str(got.get("reason") or "")
        result.update({
            "route_ai_backup": route_backup,
            "candidate_origin": (
                "AI_BACKUP_PENDING" if backup_source else "NONE"),
            "awaiting_ai_backup": bool(backup_source),
            "awaiting_ai_review": False,
            "awaiting_ai": bool(backup_source),
        })
        if backup_source and pid not in existing_backup_ids:
            backup.append(_make_ai_backup_task(
                pid, proj, backup_skills, str(backup_source), backup_detail,
                bench, Path(dataset).resolve(), run_p,
                required_top=_required_scorer_top(_entry(bench), fmt)))
            existing_backup_ids.add(pid)
        print(f"  {pid:44s} Program worker retry completed (rc={rc})")

    # AI backup is authorised only by its recorded WAIVE/route declaration.
    # The coordinator validates every handoff first, workers run only unique
    # projects, and the coordinator applies their immutable outcomes in the
    # original worklist order.
    backup_plans: list[dict] = []
    for item in backup:
        pid = str(item.get("id"))
        result = result_by_id.get(pid)
        proj = Path(str(item.get("project") or ""))
        if result is None:
            backup_plans.append({
                "kind": "invalid", "item": item, "id": pid,
                "repair": {"id": pid, "status": "INVALID_HANDOFF",
                           "reasons": [
                               "backup id is absent from solve_report"]},
            })
            continue
        prompt = proj / "input" / "phase1_prompt.md"
        expected_prompt_hash = item.get("prompt_sha256")
        try:
            current_prompt_hash = _sha256_text(
                prompt.read_text(errors="replace"))
        except OSError as exc:
            current_prompt_hash = None
            prompt_reason = f"staged prompt is unreadable: {exc}"
        else:
            prompt_reason = "staged prompt differs from the handoff-bound hash"
        if (not isinstance(expected_prompt_hash, str)
                or len(expected_prompt_hash) != 64
                or current_prompt_hash != expected_prompt_hash):
            status = ("PROMPT_CHANGED" if expected_prompt_hash
                      and current_prompt_hash is not None
                      else "INVALID_BACKUP_HANDOFF")
            backup_plans.append({
                "kind": "prompt_error", "item": item, "id": pid,
                "result": result, "status": status,
                "repair": {
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj), "status": status,
                "reasons": [prompt_reason],
                "required_next": (
                    "restore the exact staged prompt and start a fresh "
                    "--solve handoff; do not re-gate this backup"),
                },
            })
            continue
        rtl_dir = proj / "phase2" / "stage1" / "rtl"
        completion, completion_reasons = _validate_backup_completion(item, run_p)
        if completion is None:
            backup_plans.append({
                "kind": "no_rtl", "item": item, "id": pid,
                "result": result, "reasons": completion_reasons,
            })
            continue
        try:
            provenance = _archive_backup_completion(item, completion, run_p)
        except (OSError, ValueError) as exc:
            backup_plans.append({"kind": "no_rtl", "item": item, "id": pid,
                                 "result": result, "reasons": [str(exc)]})
            continue
        reentry_state = _route_reentry_state(pid, result, allow_d1_only=False)
        if reentry_state.get("status") != "ACTIVE":
            backup_plans.append({
                "kind": "route_blocked", "item": item, "id": pid,
                "result": result,
                "reasons": [str(reentry_state.get("reason") or
                                 "ROUTE_REENTRY_D1_INVALID")],
            })
            continue
        backup_plans.append({
            "kind": "run", "item": item, "id": pid, "result": result,
            "project": proj, "rtl_dir": rtl_dir, "provenance": provenance,
            "reentry_state": reentry_state,
        })

    backup_run_plans = [p for p in backup_plans if p["kind"] == "run"]
    gate_rc = _runtime_pair_before_fan_out(backup_run_plans, run_p,
                                           "resume:ai-backup")
    if gate_rc is not None:
        return gate_rc
    def _run_completed_backup(job):
        pid = job[0]
        plan = next(p for p in backup_run_plans if p["id"] == pid)
        completion, reasons = _validate_backup_completion(plan["item"], run_p)
        if completion != plan["provenance"]["author_record"]:
            return _ResumeRunnerOutcome(problem_id=pid, rc=None,
                collected_json=None, error="; ".join(reasons) or
                "AI_BACKUP_COMPLETION_PENDING: author input changed before worker entry")
        return _run_and_collect(job)

    backup_outcomes = iter(_ordered_parallel_map(
        [(p["id"], p["project"], True, None, p["result"].get("exit"),
          p["result"].get("delivery_route", "ip"))
         for p in backup_run_plans],
        _run_completed_backup, jobs))
    for plan in backup_plans:
        kind = plan["kind"]
        pid = plan["id"]
        item = plan["item"]
        if kind == "invalid":
            repairs.append(plan["repair"])
            continue
        result = plan["result"]
        if kind == "prompt_error":
            repairs.append(plan["repair"])
            result.update({"accepted": False, "candidate_origin": "NONE",
                           "awaiting_ai_backup": False,
                           "awaiting_ai_review": False,
                           "awaiting_ai": False})
            print(f"  {pid:44s} AI backup blocked: {plan['status']}")
            continue
        if kind == "no_rtl":
            remaining_backup.append(item)
            result.update({"accepted": False, "awaiting_ai_backup": True,
                           "awaiting_ai_review": False, "awaiting_ai": True,
                           "ai_backup_completion": {"status": "PENDING",
                                                    "reasons": plan["reasons"]}})
            print(f"  {pid:44s} AI backup completion PENDING: "
                  + "; ".join(plan["reasons"]))
            continue
        if kind == "route_blocked":
            remaining_backup.append(item)
            result.update({"accepted": False, "awaiting_ai_backup": True,
                           "awaiting_ai_review": False, "awaiting_ai": True,
                           "route_reentry_blocked": plan["reasons"]})
            repairs.append({"id": pid, "status": "ROUTE_REENTRY_BLOCKED",
                            "reasons": plan["reasons"]})
            print(f"  {pid:44s} AI backup blocked by route/D1 boundary")
            continue
        outcome = next(backup_outcomes)
        if outcome.error is not None:
            result.pop("runner_diagnostics", None)
            if outcome.diagnostics_json:
                result["runner_diagnostics"] = _strict_json_loads(outcome.diagnostics_json)
            remaining_backup.append(item)
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(plan["project"]),
                "status": "PROJECT_WORKER_ERROR",
                "reasons": [outcome.error],
                "required_next": (
                    "fix the named worker failure and run --resume again; "
                    "other coordinator-committed project results are retained"),
            })
            result.update({
                "rc": outcome.rc, "worker_status": "ERROR",
                "runner_invocation": outcome.invocation, "ok": False,
                "worker_error": outcome.error, "accepted": False,
                "candidate_ready": False, "awaiting_ai_backup": True,
                "awaiting_ai_review": False, "awaiting_ai": True,
                "ai_repair_required": False,
            })
            print(f"  {pid:44s} AI backup worker ERROR: {outcome.error}")
            continue
        rc = int(outcome.rc)
        got = _strict_json_loads(str(outcome.collected_json))
        proj = plan["project"]
        _refresh_result(result, proj, rc, got)
        result["runner_invocation"] = outcome.invocation
        if got.get("ok"):
            task = _make_ai_review_task(
                pid, proj, got, result.get("routing_verdict") or {}, rc,
                run_p, "AI_BACKUP", program_phases=result.get("phases"),
                runner_invocation=outcome.invocation,
                expected_public_input=item["public_original_input"])
            task["backup_provenance"] = {
                **plan["provenance"], "gated_rtl_sha256": task["rtl_sha256"]}
            result["ai_backup_completion"] = {
                "status": "CONSUMED", "task_sha256": item["task_sha256"],
                "record_sha256": plan["provenance"]["author_record"]["record_sha256"]}
            task_by_id[pid] = task
            result["review_task"] = task["review_path"]
            result["candidate_origin"] = "AI_BACKUP"
            result["ai_repair_required"] = False
            refreshed.add(pid)
            print(f"  {pid:44s} AI backup re-gated; fresh AI review required")
        else:
            # Keep the original backup handoff live: after the AI repairs the
            # rejected files, the next --resume must know to re-run the gates.
            remaining_backup.append(item)
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj),
                "status": "PROGRAM_GATES_REJECTED_AI_BACKUP",
                "reasons": [str(got.get("reason") or "runner rejected RTL")],
                "write_rtl_to": str(plan["rtl_dir"]),
                "resume_with": (f"benchmark_dispatch.py {bench} --resume "
                                f"--dataset {dataset} --run {run_p}"),
            })
            result.update({"awaiting_ai_backup": True,
                           "awaiting_ai_review": False,
                           "awaiting_ai": True,
                           "ai_repair_required": True})
            print(f"  {pid:44s} AI backup rejected by PROGRAM gates (rc={rc})")

    # AI repair is authorised only after the frozen candidate demonstrably
    # failed a prompt-derived test.  Validation remains coordinator-owned;
    # only the independent project runner calls fan out.
    repair_plans: list[dict] = []
    for pid, task in list(task_by_id.items()):
        if pid in refreshed:
            repair_plans.append({"kind": "noop", "id": pid})
            continue
        result = result_by_id.get(pid)
        if result is None:
            repair_plans.append({
                "kind": "report", "id": pid,
                "repair": {"id": pid, "status": "INVALID_REVIEW_TASK",
                           "reasons": [
                               "review id is absent from solve_report"]},
            })
            continue
        # A dispatched receipt freezes the PROGRAM candidate's output RTL.
        # Before ordinary re-entry checks, prove that a changed working RTL is
        # an authorized AI repair. Only that exact state may tolerate the
        # expected output-material delta; every other state stays strict.
        repair_verdict = None
        repair_provenance = None
        repair_challenge = None
        repair_output_sha256 = None
        repair_state = False
        proj = Path(str(task.get("project") or ""))
        working_paths = _rtl_files(proj)
        try:
            working_hash = (_sha256_text(_candidate_text(working_paths))
                            if working_paths else None)
        except OSError:
            working_hash = None
        if working_hash != task.get("rtl_sha256"):
            # Establish the semantic proof without laundering the stale
            # invocation receipt. The receipt exception is considered only
            # after this detached review is a real REPAIR_REQUIRED finding.
            proof_task = dict(task)
            verification = task.get("program_verification")
            if isinstance(verification, dict) and "runner_invocation" in verification:
                proof_verification = dict(verification)
                proof_verification.pop("runner_invocation", None)
                proof_task["program_verification"] = proof_verification
            proof_verdict = _validate_ai_review(proof_task)
            challenge = proof_verdict.get("verified_challenge")
            if (proof_verdict.get("status") == "REPAIR_REQUIRED"
                    and isinstance(challenge, dict)):
                candidate_provenance, provenance_reasons = \
                    _validate_repair_record(
                        _repair_record_path(run_p, task), task,
                        str(working_hash), challenge)
                if not provenance_reasons:
                    # Now revalidate the complete task, allowing only the
                    # proven output-material delta in the runner receipt.
                    candidate_verdict = _validate_ai_review(
                        task, allow_repaired_output=True,
                        repaired_output_sha256=str(working_hash))
                    candidate_challenge = candidate_verdict.get(
                        "verified_challenge")
                    if (candidate_verdict.get("status") == "REPAIR_REQUIRED"
                            and isinstance(candidate_challenge, dict)
                            and candidate_challenge.get("sha256")
                            == challenge.get("sha256")):
                        repair_state = True
                        repair_verdict = candidate_verdict
                        repair_provenance = candidate_provenance
                        repair_challenge = challenge
                        repair_output_sha256 = str(working_hash)
        invocation_reason = _runner_reentry_reason(
            task, result, allow_repaired_output=repair_state,
            repaired_output_sha256=repair_output_sha256)
        if invocation_reason:
            reentry_state = _route_reentry_state(pid, result, allow_d1_only=False)
            if reentry_state.get("status") != "ACTIVE":
                reason = str(reentry_state.get("reason") or
                             "ROUTE_REENTRY_D1_INVALID")
                repair_plans.append({"kind": "report", "id": pid,
                                     "repair": {
                                         "id": pid,
                                         "status": "ROUTE_REENTRY_BLOCKED",
                                         "reasons": [reason],
                                     }})
                result.update({"accepted": False, "candidate_ready": False,
                               "awaiting_ai_review": False,
                               "route_reentry_blocked": [reason]})
                continue
            # A legacy pre-run refusal is not a completed gate invocation.
            # Re-enter the SAME frozen bytes; no edit or author signature is
            # authorised here. Keep old review/test/task records for audit.
            prompt_hash, frozen_hash, stated, frozen_paths = _current_task_material(task)
            reasons = _validate_candidate_snapshot(task.get("candidate_snapshot"), pid)
            reasons += _public_input_reasons(task)
            old_invocation = (task.get("program_verification") or {}).get("runner_invocation")
            if isinstance(old_invocation, dict) and old_invocation.get("material_after") is not None:
                try:
                    if _runner_material_snapshot(proj) != old_invocation["material_after"]:
                        reasons.append("unchanged invocation-bound input/output population required for runner re-entry")
                except (OSError, ValueError) as exc:
                    reasons.append(f"runner re-entry material is unreadable: {exc}")
            if (prompt_hash != task.get("prompt_sha256") or frozen_hash != task.get("rtl_sha256")
                    or stated != frozen_paths
                    or _sha256_text(_candidate_text(_rtl_files(proj))) != task.get("rtl_sha256")):
                reasons.append("unchanged bound prompt and working/frozen RTL required for runner re-entry")
            if proj.resolve() != (run_p / "projects" / _safe_problem_id(pid)).resolve():
                reasons.append("runner re-entry project is not coordinator-owned")
            if pid in phase1_blocked:
                reasons.append(phase1_blocked[pid])
            if result.get("accepted") or Path(str(task.get("response_path"))).is_file():
                reasons.append("runner re-entry cannot replace an accepted/published candidate")
            if task.get("candidate_origin") == "AI_REPAIR":
                reasons += _validate_embedded_repair_provenance(task)
            if reasons:
                repair_plans.append({"kind": "report", "id": pid, "repair": {
                    "id": pid, "status": "RUNNER_REGATE_BLOCKED", "reasons": [invocation_reason, *reasons]}})
                result.update({"accepted": False, "candidate_ready": False, "awaiting_ai_review": False})
                continue
            key = "runner-regate-" + uuid.uuid4().hex
            archive = run_p / "runner_regates" / _safe_problem_id(pid) / key
            _write_immutable_json(archive / "prior_task.json", task)
            _write_immutable_json(archive / "prior_result.json", result)
            repair_plans.append({
                "kind": "regate", "id": pid, "task": task, "result": result,
                "project": proj, "challenge": None, "review_key": key,
                "reentry_state": reentry_state,
                "archive": archive, "repair_parent_candidate": task.get("repair_parent_candidate_snapshot"),
                "repair_provenance": task.get("repair_provenance"),
                "repair_input_candidate": task.get("repair_input_candidate_snapshot"),
                "program_first_phases": result.get("program_first_phases") or result.get("phases") or {},
            })
            continue
        pre_logs: list[str] = []
        review_path = Path(str(task.get("review_path") or ""))
        if (task.get("candidate_origin") == "AI_REPAIR"
                and (not review_path.is_file()
                     or _validate_embedded_repair_provenance(task))):
            final_provenance, final_provenance_reasons = \
                _refresh_final_repair_provenance(task)
            if final_provenance_reasons:
                result.update({"accepted": False, "awaiting_ai": True,
                               "awaiting_ai_review": False,
                               "ai_repair_required": True})
                repair_plans.append({
                    "kind": "report", "id": pid,
                    "log": f"  {pid:44s} final gated RTL needs AI provenance",
                    "repair": {
                        "schema": "vibeic.benchmark.ai_repair_task.v2",
                        "id": pid, "project": task.get("project"),
                        "status": "AI_REPAIR_FINAL_PROVENANCE_REQUIRED",
                        "reasons": final_provenance_reasons,
                        "repair_record_path": (task.get("repair_provenance")
                                               or {}).get("path"),
                        "program_parent_rtl_sha256":
                            (task.get("program_candidate_snapshot")
                             or {}).get("rtl_sha256"),
                        "final_repaired_rtl_sha256": task.get("rtl_sha256"),
                    },
                })
                continue
            task["repair_provenance"] = final_provenance
            result.update({"awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": False})
            pre_logs.append(f"  {pid:44s} final AI repair provenance rebound")
        prompt_hash, _, _, _ = _current_task_material(task)
        if prompt_hash != task.get("prompt_sha256"):
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False})
            repair_plans.append({
                "kind": "report", "id": pid, "pre_logs": pre_logs,
                "repair": {
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": task.get("project"),
                    "status": "PROMPT_CHANGED",
                    "reasons": [
                        "restore the original prompt; it cannot be refreshed"],
                },
            })
            continue
        proj = Path(str(task.get("project") or ""))
        working_paths = _rtl_files(proj)
        try:
            working_hash = (_sha256_text(_candidate_text(working_paths))
                            if working_paths else None)
        except OSError:
            working_hash = None
        if working_hash == task.get("rtl_sha256"):
            repair_plans.append({
                "kind": "noop", "id": pid, "pre_logs": pre_logs})
            continue
        prior_verdict = repair_verdict or _validate_ai_review(task)
        challenge = repair_challenge or prior_verdict.get("verified_challenge")
        if prior_verdict.get("status") != "REPAIR_REQUIRED" or not challenge:
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": False})
            repair_plans.append({
                "kind": "report", "id": pid, "pre_logs": pre_logs,
                "log": (f"  {pid:44s} changed RTL rejected: "
                        "AI issue is unproven"),
                "repair": {
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": str(proj),
                    "status": "UNPROVEN_AI_EDIT_REJECTED",
                    "reasons": [
                        "working RTL changed before an AI finding was proven "
                        "by a prompt-derived executable verification test",
                        *[str(v) for v in prior_verdict.get("reasons") or []],
                    ],
                    "restore_from": (task.get("candidate_snapshot") or {}).get(
                        "manifest_path"),
                },
            })
            continue
        repair_record_path = _repair_record_path(run_p, task)
        if repair_state:
            provenance_reasons = []
        else:
            repair_provenance, provenance_reasons = _validate_repair_record(
                repair_record_path, task, str(working_hash), challenge)
        if provenance_reasons:
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False,
                           "ai_repair_required": True})
            repair_plans.append({
                "kind": "report", "id": pid, "pre_logs": pre_logs,
                "log": f"  {pid:44s} changed RTL needs AI repair provenance",
                "repair": {
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": str(proj),
                    "status": "AI_REPAIR_PROVENANCE_REQUIRED",
                    "reasons": provenance_reasons,
                    "repair_record_path": str(repair_record_path),
                    "reviewed_rtl_sha256": task.get("rtl_sha256"),
                    "repaired_rtl_sha256": working_hash,
                    "challenge_sha256": challenge.get("sha256"),
                },
            })
            continue
        reentry_state = _route_reentry_state(pid, result, allow_d1_only=False)
        if reentry_state.get("status") != "ACTIVE":
            reason = str(reentry_state.get("reason") or
                         "ROUTE_REENTRY_D1_INVALID")
            repair_plans.append({"kind": "report", "id": pid,
                                 "pre_logs": pre_logs,
                                 "repair": {
                                     "id": pid,
                                     "status": "ROUTE_REENTRY_BLOCKED",
                                     "reasons": [reason],
                                 }})
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False,
                           "ai_repair_required": True,
                           "route_reentry_blocked": [reason]})
            continue
        # Freeze the signed bytes BEFORE the gates can normalize them in
        # place.  Without this the only copy of what the author signed is
        # destroyed, and a later Program fix has nothing to re-enter from.
        try:
            preserved = _archive_pre_gate_input(
                run_p, pid, working_paths, str(working_hash))
        except (OSError, ValueError) as exc:
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False,
                           "ai_repair_required": True})
            repair_plans.append({
                "kind": "report", "id": pid, "pre_logs": pre_logs,
                "log": f"  {pid:44s} signed pre-gate input not preserved",
                "repair": {
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": str(proj),
                    "status": "PRE_GATE_INPUT_NOT_PRESERVED",
                    "reasons": [f"{type(exc).__name__}: {exc}"],
                    "signed_rtl_sha256": working_hash,
                },
            })
            continue
        repair_plans.append({
            "kind": "run", "id": pid, "pre_logs": pre_logs,
            "task": task, "result": result, "project": proj,
            "reentry_state": reentry_state,
            "challenge": challenge, "repair_provenance": repair_provenance,
            "repair_parent_candidate": task.get("candidate_snapshot"),
            "pre_gate_input": preserved,
            "repair_input_candidate": _archive_repair_input(
                pid, proj, run_p, repair_provenance),
            "repaired_output_sha256": repair_output_sha256,
            "program_first_phases": (
                result.get("program_first_phases")
                or result.get("phases") or {}),
        })

    repair_run_plans = [p for p in repair_plans if p["kind"] in {"run", "regate"}]
    gate_rc = _runtime_pair_before_fan_out(repair_run_plans, run_p,
                                           "resume:repair")
    if gate_rc is not None:
        return gate_rc
    repair_outcomes = iter(_ordered_parallel_map(
        [(p["id"], p["project"], True, None, p["result"].get("exit"),
          ({"repair_contract": ((p.get("repair_provenance") or {}).get("repair_contract")),
            "require_repair_contract": True,
            **({"expected_repaired_output_sha256": p["repaired_output_sha256"]}
               if p.get("repaired_output_sha256") is not None else {})}
           if p["task"].get("candidate_origin") == "AI_REPAIR" or p["kind"] == "run"
           else {}))
         for p in repair_run_plans],
        _run_and_collect, jobs))
    for plan in repair_plans:
        for line in plan.get("pre_logs") or []:
            print(line)
        if plan["kind"] == "noop":
            continue
        if plan["kind"] == "report":
            repairs.append(plan["repair"])
            if plan.get("log"):
                print(plan["log"])
            continue
        pid = plan["id"]
        task = plan["task"]
        result = plan["result"]
        proj = plan["project"]
        outcome = next(repair_outcomes)
        if outcome.error is not None:
            result.pop("runner_diagnostics", None)
            if outcome.diagnostics_json:
                result["runner_diagnostics"] = _strict_json_loads(outcome.diagnostics_json)
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj),
                "status": "PROJECT_WORKER_ERROR",
                "reasons": [outcome.error],
                "required_next": (
                    "fix the named worker failure and run --resume again; "
                    "other coordinator-committed project results are retained"),
            })
            result.update({
                "rc": outcome.rc, "worker_status": "ERROR",
                "runner_invocation": outcome.invocation,
                "ok": False, "candidate_ready": False,
                "worker_error": outcome.error, "accepted": False,
                "awaiting_ai": True, "awaiting_ai_review": False,
                "ai_repair_required": True,
            })
            print(f"  {pid:44s} AI repair worker ERROR: {outcome.error}")
            continue
        rc = int(outcome.rc)
        got = _strict_json_loads(str(outcome.collected_json))
        _refresh_result(result, proj, rc, got)
        result["runner_invocation"] = outcome.invocation
        program_first_phases = plan["program_first_phases"]
        if program_first_phases:
            result["program_first_phases"] = program_first_phases
            result.setdefault("phases", {})["phase2_solving"] = \
                program_first_phases.get("phase2_solving", {})
            result["phases"]["phase4_debugging"] = \
                program_first_phases.get("phase4_debugging", {})
        if got.get("ok"):
            inherited = list(task.get("verification_challenges") or [])
            if plan.get("challenge") is not None:
                inherited.append(plan["challenge"])
            new_task = _make_ai_review_task(
                pid, proj, got, result.get("routing_verdict") or {}, rc,
                run_p, task.get("candidate_origin") if plan["kind"] == "regate" else "AI_REPAIR",
                expected_public_input=task.get("public_original_input"),
                runner_invocation=outcome.invocation,
                program_phases=result.get("phases"),
                verification_challenges=inherited,
                program_candidate=(task.get("program_candidate_snapshot")
                                   or task.get("candidate_snapshot")),
                repair_parent_candidate=plan.get("repair_parent_candidate"),
                repair_provenance=plan["repair_provenance"],
                repair_input_candidate=plan.get("repair_input_candidate"),
                review_key=plan.get("review_key"), archive_key=plan.get("review_key"))
            if plan["kind"] == "regate":
                for key in ("backup_provenance", "pre_gate_input", "program_regate"):
                    if key in task:
                        new_task[key] = task[key]
                _write_immutable_json(plan["archive"] / "new_task.json", new_task)
            preserved = plan.get("pre_gate_input")
            if isinstance(preserved, dict):
                new_task["pre_gate_input"] = _bind_pre_gate_output(
                    preserved, new_task["rtl_sha256"])
            task_by_id[pid] = new_task
            result["review_task"] = new_task["review_path"]
            result["candidate_origin"] = new_task["candidate_origin"]
            result["ai_repair_required"] = False
            refreshed.add(pid)
            print(f"  {pid:44s} RTL re-gated; fresh AI review required")
        else:
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj),
                "status": "PROGRAM_GATES_REJECTED_AI_REPAIR",
                "reasons": [str(got.get("reason") or "runner rejected RTL")],
                "write_rtl_to": str(proj / "phase2" / "stage1" / "rtl"),
            })
            result["ai_repair_required"] = True
            print(f"  {pid:44s} changed RTL rejected by PROGRAM gates (rc={rc})")

    accepted_ids: list[str] = []
    review_outcomes: list[dict] = []
    not_measured: list[dict] = []
    clarifications: list[dict] = []
    for pid, result in result_by_id.items():
        result["awaiting_spec_clarification"] = False
        task = task_by_id.get(pid)
        if task is None:
            result["accepted"] = False
            continue
        invocation_reason = _runner_reentry_reason(task, result)
        if result.get("worker_status") == "ERROR" or invocation_reason:
            result.update({"accepted": False, "candidate_ready": False,
                           "awaiting_ai_review": False})
            review_outcomes.append({"id": pid, "status": "PENDING", "reasons": [
                result.get("worker_error") or invocation_reason]})
            continue
        verdict = _validate_ai_review(task)
        _attach_ai_review_attribution(result, verdict, task)
        review_outcomes.append({"id": pid, **verdict})
        if (verdict["status"] == "REPAIR_REQUIRED"
                or (verdict["status"] == "ACCEPTED"
                    and verdict.get("routing_verdict") == "OVERRIDE_PROGRAM")):
            enhancement = _program_enhancement_candidate(task, result, verdict)
            enhancement_by_key[(
                pid, str(task.get("prompt_sha256")),
                str(task.get("rtl_sha256")),
                str(verdict.get("semantic_verdict")),
            )] = enhancement
        if verdict["status"] == "SPEC_CLARIFICATION_REQUIRED":
            clarifications.append({
                "schema": "vibeic.benchmark.spec_clarification_task.v1",
                "id": pid, "project": task.get("project"),
                "status": verdict["status"], "review_path": task.get("review_path"),
                "prompt_sha256": task.get("prompt_sha256"),
                "reviewed_rtl_sha256": task.get("rtl_sha256"),
                "spec_clarification": verdict["spec_clarification"],
                "required_next": (
                    "obtain the spec owner's missing definition; keep this frozen "
                    "run intact. A changed prompt must enter a fresh canonical "
                    "run and review. No repair, test waiver, or scoring is authorized."),
            })
            result.update({"accepted": False, "awaiting_ai": False,
                           "awaiting_ai_review": False, "ai_repair_required": False,
                           "not_measured": False, "awaiting_spec_clarification": True})
            print(f"  {pid:44s} SPEC_CLARIFICATION_REQUIRED -- obtain the missing definition")
            continue
        if verdict["status"] == _NOT_MEASURED:
            # Not accepted -- nothing was established, so nothing is scored --
            # but this is NOT a repair task and NOT an AI failure. It waits on
            # the HOST, and it says so in its own row rather than borrowing
            # the vocabulary of a defect.
            not_measured.append({
                "schema": "vibeic.benchmark.ai_review_not_measured.v1",
                "id": pid, "project": task.get("project"),
                "status": _NOT_MEASURED,
                "reasons": verdict.get("unmeasurable") or [],
                "decision_reasons": verdict.get("decision_reasons") or [],
                "review_path": task.get("review_path"),
                "reviewed_rtl_sha256": task.get("rtl_sha256"),
                "required_next": (
                    "install the missing capability on this host and re-run "
                    "--resume; do not re-author RTL on the strength of a test "
                    "that did not run"),
            })
            result.update({"accepted": False, "awaiting_ai": False,
                           "awaiting_ai_review": False,
                           "ai_repair_required": False,
                           "not_measured": True})
            print(f"  {pid:44s} NOT_MEASURED -- this host cannot run the "
                  f"verification challenge")
            continue
        if verdict["status"] != "ACCEPTED":
            needs_repair = verdict["status"] == "REPAIR_REQUIRED"
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": not needs_repair,
                           "ai_repair_required": needs_repair})
            if needs_repair:
                result["ai_repair_required"] = True
                repairs.append({
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": task.get("project"),
                    "status": "AI_SEMANTIC_REPAIR_REQUIRED",
                    "reasons": (verdict.get("decision_reasons") or [])
                               + [str(v) for v in
                                  verdict.get("semantic_findings_detail") or []],
                    "review_path": task.get("review_path"),
                    "reviewed_rtl_sha256": task.get("rtl_sha256"),
                    "verified_challenge": verdict.get("verified_challenge"),
                    "challenge_result": verdict.get("challenge_result"),
                    "repair_record_path": str(
                        _repair_record_path(run_p, task)),
                    "repair_record_requirements": {
                        "schema": _AI_REPAIR_RECORD_SCHEMA,
                        "id": pid,
                        "prompt_sha256": task.get("prompt_sha256"),
                        "parent_rtl_sha256": task.get("rtl_sha256"),
                        "repaired_rtl_sha256":
                            "sha256 of the corrected working RTL",
                        "challenge_sha256":
                            (verdict.get("verified_challenge") or {}).get(
                                "sha256"),
                        "author": {"kind": "AI", "model": "required"},
                        "oracle_accessed": False,
                        "rationale": "required",
                        "repair_contract": {
                            "schema": "vibeic.source_bounded_completion.v1",
                            "prompt_sha256": task.get("prompt_sha256"),
                            "source_sha256": (task.get("public_original_input") or {}).get(
                                "source_sha256"),
                            "parent_rtl_sha256": task.get("rtl_sha256"),
                            "candidate_sha256": "sha256 of corrected working RTL",
                            "challenge_sha256": (verdict.get("verified_challenge") or {}).get(
                                "sha256"),
                            "author": {"kind": "AI", "model": "same as outer author"},
                            "oracle_accessed": False,
                            "preservation": "complete exact-path declaration required",
                            "elaboration_matrix": "complete exact-path declaration required",
                        },
                    },
                    "verified_prompt_evidence":
                        (verdict.get("override") or {}).get(
                            "verified_prompt_evidence") or [],
                    "verified_semantic_prompt_evidence":
                        verdict.get("verified_semantic_prompt_evidence") or [],
                    "write_rtl_to": str(
                        Path(str(task.get("project"))) /
                        "phase2" / "stage1" / "rtl"),
                    "required_next": (
                        "author corrected RTL that passes verified_challenge, "
                        "write the hash-bound AI repair record, run --resume "
                        "for PROGRAM gates and the SAME challenge, then submit "
                        "a fresh AI review for the new hash"),
                })
            continue
        supplied_rtl = result.get("candidate_origin") in {
            "AI_BACKUP", "AI_REPAIR"}
        # Only an authenticated explicit reentry may supply a PROGRAM-owned
        # postimage declaration. Ordinary author repairs retain their exact
        # signed candidate contract, including every immutable hash check.
        regate = _verified_program_regate(task)
        repair_contract = (task.get("repair_provenance") or {}).get("repair_contract")
        if regate is not None:
            repair_contract = _read_json_regular(Path(regate["output_contract_path"]))["repair_contract"]
        got = bio.collect(
            fmt, pid, Path(str(task.get("project") or "")),
            supplied_rtl=supplied_rtl,
            repair_contract=(repair_contract
                             if task.get("candidate_origin") == "AI_REPAIR" else None),
            require_repair_contract=(task.get("candidate_origin") == "AI_REPAIR"),
            required_top=_required_scorer_top(_entry(bench), fmt))
        if (not got.get("ok")
                or _sha256_text(str(got.get("completion") or ""))
                != task.get("rtl_sha256")):
            reasons = ["current PROGRAM-gated completion does not match the "
                       "AI-reviewed RTL hash"]
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": task.get("project"),
                "status": "ACCEPTED_REVIEW_MATERIAL_MISMATCH",
                "reasons": reasons,
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": True})
            continue
        if task.get("candidate_origin") == "AI_REPAIR":
            recovery = _verified_program_recovery(task, result, verdict)
            enhancement_by_key[(
                pid, str(task.get("prompt_sha256")),
                str(task.get("rtl_sha256")), "VERIFIED_RECOVERY",
            )] = recovery
        # #2012's invariant, at the only site that can violate it: a
        # candidate whose canonical Phase-1 provenance is missing, or was
        # changed after its review task was written, is NOT accepted and NOT
        # published. Asked before the frozen response payload is written, so
        # nothing reaches responses/ for a refused candidate.
        blocked_reason = phase1_blocked.get(pid)
        if blocked_reason is not None:
            print("ERROR: canonical Phase-1 front door BLOCKED:\n  "
                  f"{pid}: {blocked_reason}", file=sys.stderr)
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": task.get("project"),
                "status": "PHASE1_PROVENANCE_BLOCKED",
                "reasons": [blocked_reason],
                "required_next": (
                    "re-enter this project through the canonical Phase-1 "
                    "front door so it emits hash-bound L-doc provenance, then "
                    "run --resume again; a candidate with no canonical "
                    "Phase-1 provenance is never accepted"),
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": False})
            continue
        payload_path = Path(str((task.get("candidate_snapshot") or {}).get(
            "response_payload_path") or ""))
        try:
            frozen_payload = _strict_json_loads(payload_path.read_text(errors="replace"))
        except (OSError, ValueError) as exc:
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": task.get("project"),
                "status": "FROZEN_RESPONSE_PAYLOAD_INVALID",
                "reasons": [str(exc)],
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False,
                           "ai_repair_required": False})
            continue
        # #2216 — REQUIRED IN-SCOPE PROGRAM GATE ELIGIBILITY, asked here and
        # nowhere earlier. Every check above is about the ARTEFACT: is it
        # runner-owned, does its hash still match, is its Phase-1 provenance
        # intact, did its OWNING gate pass. None of them can see a second
        # in-scope gate that FAILED on these same bytes, and the message below
        # nevertheless claimed every Program gate had passed. Collection stays
        # exactly as permissive as it was — a failed candidate must remain
        # reviewable and repairable — but a required in-scope FAILURE now holds
        # the DELIVERABLE instead of being overwritten by a semantic PASS.
        freshness_reasons = _gate_evidence_freshness_reasons(
            Path(str(task.get("project") or "")), result)
        if freshness_reasons:
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": task.get("project"),
                "status": "PROGRAM_GATE_EVIDENCE_STALE",
                "reasons": freshness_reasons,
                "required_next": (
                    "refresh the solve attribution and review handoff from "
                    "the current Program step report, then obtain a fresh "
                    "review before acceptance; repeating --resume alone "
                    "cannot refresh reviewed gate evidence"),
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": False})
            print(f"  {pid:44s} NOT ACCEPTED -- {freshness_reasons[0]}")
            continue
        gate_ledger = _required_gate_ledger(result)
        result["required_gate_ledger"] = gate_ledger
        if gate_ledger.get("failed_required"):
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": task.get("project"),
                "status": "PROGRAM_GATE_INELIGIBLE",
                "reasons": [
                    f"required in-scope PROGRAM gate {name} reported "
                    f"{gate_ledger['in_scope'].get(name)} on this candidate"
                    for name in gate_ledger["failed_required"]],
                "required_gate_ledger": gate_ledger,
                "review_path": task.get("review_path"),
                "reviewed_rtl_sha256": task.get("rtl_sha256"),
                "required_next": (
                    "repair the RTL so the named in-scope gate passes, then "
                    "run --resume for PROGRAM gates and submit a fresh AI "
                    "review for the new hash; an independent semantic PASS "
                    "does not discharge a required in-scope gate failure"),
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False,
                           "ai_repair_required": True})
            print(f"  {pid:44s} NOT ACCEPTED -- "
                  f"{_gate_status_note(gate_ledger)}")
            continue
        _atomic_write_json(Path(task["response_path"]), frozen_payload)
        accepted_ids.append(pid)
        result.update({"accepted": True, "awaiting_ai": False,
                       "awaiting_ai_backup": False,
                       "awaiting_ai_review": False,
                       "ai_repair_required": False,
                       "reviewer_model": verdict.get("reviewer_model")})
        route_note = ("AI OVERRIDE_PROGRAM" if
                      verdict.get("routing_verdict") == "OVERRIDE_PROGRAM"
                      else "AI AGREE")
        # The message states what was MEASURED. "ACCEPTED by PROGRAM gates"
        # asserted that every required gate passed even when a required
        # in-scope gate never reported at all -- MEASURED: `rtl_validate` is
        # BLOCKED on 44 of 61 published accepted rows and absent on the other
        # 17. That hole is now said out loud as NOT_MEASURED, never as a pass.
        print(f"  {pid:44s} ACCEPTED -- {_gate_status_note(gate_ledger)} "
              f"+ {route_note}")

    ordered_tasks = [task_by_id[pid] for pid in result_by_id
                     if pid in task_by_id]
    _write_jsonl(run_p / _BACKUP_WORKLIST, remaining_backup)
    _write_jsonl(run_p / _REVIEW_WORKLIST, ordered_tasks)
    _write_jsonl(run_p / _REPAIR_WORKLIST, repairs)
    _write_jsonl(run_p / _CLARIFICATION_WORKLIST, clarifications)
    enhancements = sorted(enhancement_by_key.values(),
                          key=lambda row: (str(row.get("id")),
                                           str(row.get("rtl_sha256"))))
    _write_jsonl(run_p / _ENHANCEMENT_WORKLIST, enhancements)

    total = len(results)
    unmeasured_pending = any(
        r.get("worker_status") == "ERROR"
        or any(isinstance(row, Mapping) and row.get("status") == "NOT_MEASURED"
               for row in (r.get("phases") or {}).values())
        for r in results)
    complete = (total > 0 and len(accepted_ids) == total
                and len(ordered_tasks) == total and not remaining_backup
                and not repairs and not unmeasured_pending)
    solve.update({
        "solved": sum(1 for r in results if r.get("candidate_ready")),
        "accepted": len(accepted_ids),
        "four_phase_summary": _four_phase_rollup(fpa, results),
        "results": results,
    })
    _atomic_write_json(solve_p, solve)
    acceptance = {
        "schema": _ACCEPTANCE_SCHEMA,
        "status": "COMPLETE" if complete else "PENDING",
        "accepted": len(accepted_ids), "total": total,
        "accepted_ids": accepted_ids,
        "review_outcomes": review_outcomes,
        "pending_backup": len(remaining_backup),
        "pending_repair": len(repairs),
        "pending_spec_clarification": len(clarifications),
        "not_measured": len(not_measured),
        "not_measured_detail": not_measured,
        "pending_review": sum(1 for o in review_outcomes
                              if o.get("status") in {"PENDING", "REJECTED"}),
        "program_enhancement_candidates": len(enhancements),
    }
    _atomic_write_json(run_p / _ACCEPTANCE_REPORT, acceptance)
    if not_measured:
        print(f"\n{len(not_measured)}/{total} NOT_MEASURED: this host could not "
              f"run the verification challenge, so those reviews were neither "
              f"proven nor disproven. This is a host capability gap, not a "
              f"finding about the candidates.")
    print(f"\n{len(accepted_ids)}/{total} Program First + AI Review accepted; status "
          f"{acceptance['status']} -> {run_p / _ACCEPTANCE_REPORT}")
    if complete:
        return 0
    return 2 if (remaining_backup or repairs or ordered_tasks
                 or unmeasured_pending) else 1


_CORRECTION_REFUSED = "REVIEW_CORRECTION_REFUSED"
_REGATE_REFUSED = "PROGRAM_REGATE_REFUSED"
def _program_retry_removal_clause() -> str:
    """"removed one version after <the version the MANIFEST reports>".

    One clause, used by both the deprecation line and the `--help` text, so
    the two can never name different versions -- and neither carries a typed
    literal that the landing version can contradict.
    """
    running = _program_version()
    since = f"v{running}" if running else (
        "this plugin's current version (UNREADABLE from the manifest)")
    return f"removed one version after {since}"


def _program_retry_deprecation() -> str:
    """The alias's deprecation line, naming the version from the MANIFEST.

    A typed version literal here is a claim that goes stale the moment the
    merge lands under a different number than whoever wrote it guessed -- and
    the landing version is assigned at landing, not by the author. The running
    version is read from `.claude-plugin/plugin.json` instead, so the line
    cannot disagree with the plugin printing it.

    An unreadable manifest degrades LOUDLY: the sentence says the version could
    not be read rather than quoting a number nobody measured.
    """
    return ("DEPRECATED: --program-retry is now an alias of --program-regate "
            f"and will be {_program_retry_removal_clause()} (issue #2047 "
            "merged the two Program re-entry operations into one). Re-run "
            "with --program-regate.")


def _correction_path(path: str | Path, run_p: Path | None = None,
                     *, exists: bool = True,
                     token: str = _CORRECTION_REFUSED) -> Path:
    """BLOCKING: correction evidence may not traverse a symlink or escape run.

    `token` names the refusing operation. It changes only the message prefix:
    the two operations enforce one identical path contract, so a divergence
    here could not be a divergence in what is allowed.
    """
    if not isinstance(path, (str, Path)) or not str(path):
        raise ValueError(f"{token}: malformed path")
    path = Path(path).absolute()
    if any(part.is_symlink() for part in [path, *path.parents]):
        raise ValueError(f"{token}: symlink path: {path}")
    path = path.resolve()
    if run_p is not None and not path.is_relative_to(run_p):
        raise ValueError(f"{token}: path outside run: {path}")
    if exists and not path.is_file():
        raise ValueError(f"{token}: missing file: {path}")
    return path


def _correction_object(path: Path,
                       token: str = _CORRECTION_REFUSED) -> tuple[dict, str]:
    raw = path.read_bytes().decode("utf-8")
    obj = _strict_json_loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"{token}: not a JSON object: {path}")
    return obj, raw


def _review_task_digest(task: dict) -> str:
    return _sha256_text(json.dumps(task, ensure_ascii=False, sort_keys=True))


def _apply_review_correction(run_p: Path, request_path: Path) -> None:
    """Advance ONE unaccepted review, not its candidate or acceptance verdict.

    BLOCKING: explicit AI attribution, prompt evidence and exact source hashes
    are required. The old current challenge becomes an ordinary inherited
    obligation; ONLY the existing validation/supersession/coverage predicates
    can subsequently retire it. This operation neither proves a defect nor
    authorizes repair, and it never reopens an accepted/published candidate.

    Called only under the solve/resume coordinator lock. Immutable archives are
    prepared first; the sole state-transition commit is the atomic worklist
    replacement. Interruption before that commit leaves the old task active;
    repeating the same request reuses identical archives. Interruption after it
    leaves the new, unreviewed task active. Ordinary resume derives all other
    worklists and the pending acceptance ledger from that authoritative task.
    """
    run_p = run_p.resolve()
    request, request_raw = _correction_object(_correction_path(request_path))
    request_sha = _sha256_text(request_raw)
    task_path = _correction_path(run_p / _REVIEW_WORKLIST, run_p)
    task_raw = task_path.read_text(encoding="utf-8")
    tasks = _read_jsonl(task_path)
    ids = [str(t.get("id")) for t in tasks]
    pid = str(request.get("id") or "")
    if not pid or len(set(ids)) != len(ids) or ids.count(pid) != 1:
        raise ValueError("REVIEW_CORRECTION_REFUSED: missing or duplicate task id")
    current = tasks[ids.index(pid)]
    archive = run_p / "review_corrections" / _safe_problem_id(pid) / request_sha
    transition_path = _correction_path(archive / "transition.json", run_p,
                                       exists=False)
    transition = None
    if transition_path.exists():
        transition, _ = _correction_object(transition_path)
        task = transition.get("prior_task")
        if not isinstance(task, dict):
            raise ValueError("REVIEW_CORRECTION_REFUSED: invalid transition archive")
    else:
        task = current
    if request.get("schema") != _REVIEW_CORRECTION_SCHEMA:
        raise ValueError("REVIEW_CORRECTION_REFUSED: wrong request schema")
    if task.get("schema") != _REVIEW_TASK_SCHEMA:
        raise ValueError("REVIEW_CORRECTION_REFUSED: wrong task schema")
    for field, expected in (
            ("task_sha256", _review_task_digest(task)),
            ("prompt_sha256", task.get("prompt_sha256")),
            ("rtl_sha256", task.get("rtl_sha256"))):
        if not re.fullmatch(r"[0-9a-f]{64}", str(request.get(field) or "")) \
                or request[field] != expected:
            raise ValueError(f"REVIEW_CORRECTION_REFUSED: stale {field}")
    author = request.get("author")
    blind = request.get("blind")
    if (not isinstance(author, dict) or author.get("kind") != "AI"
            or not isinstance(author.get("model"), str)
            or author["model"].strip().lower() in {"", "unknown", "unspecified", "n/a"}
            or not isinstance(blind, dict) or blind.get("oracle_accessed") is not False):
        raise ValueError("REVIEW_CORRECTION_REFUSED: attributed blind AI required")
    if not isinstance(request.get("rationale"), str) \
            or len(request["rationale"].strip()) < 80:
        raise ValueError("REVIEW_CORRECTION_REFUSED: rationale needs 80 characters")
    prompt_path = _correction_path(task.get("prompt_path") or "", run_p)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if not _verified_prompt_evidence(request.get("prompt_evidence"), prompt_text):
        raise ValueError("REVIEW_CORRECTION_REFUSED: prompt-bound evidence required")
    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        raise ValueError("REVIEW_CORRECTION_REFUSED: candidate snapshot missing")
    material_paths = [prompt_path]
    project = _correction_path(task.get("project") or "", run_p, exists=False)
    if not project.is_dir():
        raise ValueError("REVIEW_CORRECTION_REFUSED: missing project directory")
    working_paths = [_correction_path(p, run_p) for p in _rtl_files(project)]
    for field in ("rtl_paths", "working_rtl_paths"):
        paths = task.get(field)
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"REVIEW_CORRECTION_REFUSED: missing {field}")
        material_paths.extend(_correction_path(p, run_p) for p in paths)
    for field in ("completion_path", "response_payload_path", "manifest_path"):
        material_paths.append(_correction_path(candidate.get(field) or "", run_p))
    material_paths.extend(_correction_path(p, run_p)
                          for p in candidate.get("rtl_paths") or [])
    if (_validate_candidate_snapshot(candidate, pid)
            or _current_task_material(task)[:2] != (
                task.get("prompt_sha256"), task.get("rtl_sha256"))
            or sorted(task["rtl_paths"]) != sorted(candidate["rtl_paths"])
            or sorted(str(p) for p in working_paths)
                != sorted(task["working_rtl_paths"])
            or _sha256_text(_candidate_text(working_paths))
                != task.get("rtl_sha256")):
        raise ValueError("REVIEW_CORRECTION_REFUSED: prompt/candidate/working RTL drift")
    review_path = _correction_path(task.get("review_path") or "", run_p)
    review, review_raw = _correction_object(review_path)
    for field in ("id", "prompt_sha256", "rtl_sha256"):
        if review.get(field) != task.get(field):
            raise ValueError(f"REVIEW_CORRECTION_REFUSED: prior review {field} drift")
    if (review.get("schema") != _AI_REVIEW_SCHEMA
            or not isinstance(review.get("reviewer"), dict)
            or review["reviewer"].get("kind") != "AI"
            or not isinstance(review.get("blind"), dict)
            or review["blind"].get("oracle_accessed") is not False):
        raise ValueError("REVIEW_CORRECTION_REFUSED: malformed prior AI review")
    if request.get("review_sha256") != _sha256_text(review_raw):
        raise ValueError("REVIEW_CORRECTION_REFUSED: prior review hash drift")
    challenge_path = _correction_path(task.get("challenge_path") or "", run_p,
                                      exists=False)
    raw_test = review.get("verification_test")
    challenge = None
    prior_challenge_status = None
    if (raw_test is None and (review.get("semantic_review") or {}).get(
            "verdict") == "NEEDS_CLARIFICATION"):
        # A valid source question need not make a functional claim or author
        # a test. Verify that boundary through its owning validator; malformed
        # questions must not gain a correction path by omitting proof fields.
        outcome = _validate_ai_review(task)
        if outcome.get("status") != "SPEC_CLARIFICATION_REQUIRED":
            raise ValueError("REVIEW_CORRECTION_REFUSED: invalid prior spec "
                             "clarification: " + "; ".join(outcome.get("reasons") or []))
        if "challenge_sha256" not in request:
            raise ValueError("REVIEW_CORRECTION_REFUSED: explicit prior "
                             "challenge hash or null required")
        if challenge_path.exists():
            _correction_path(challenge_path, run_p)
            prior_challenge_status = "PRESERVED_UNCONTRACTED_SUPPLEMENTAL_NOT_PROMOTED"
        else:
            prior_challenge_status = "ABSENT_NO_VERIFICATION_OBLIGATION"
    else:
        if not isinstance(raw_test, dict):
            raise ValueError("REVIEW_CORRECTION_REFUSED: prior challenge missing")
        _correction_path(raw_test.get("path") or "", run_p)
        challenge, reasons = _challenge_from_review(task, review, prompt_text)
        if reasons or not challenge:
            raise ValueError("REVIEW_CORRECTION_REFUSED: " + "; ".join(reasons))
    prior_challenge_bytes = (challenge_path.read_bytes()
                             if challenge_path.is_file() else None)
    prior_challenge_sha256 = (
        challenge["sha256"] if challenge is not None else
        hashlib.sha256(prior_challenge_bytes).hexdigest()
        if prior_challenge_bytes is not None else None)
    if request.get("challenge_sha256") != prior_challenge_sha256:
        raise ValueError("REVIEW_CORRECTION_REFUSED: current challenge hash drift")
    material_paths.append(review_path)
    if prior_challenge_bytes is not None:
        material_paths.append(challenge_path)
    inherited = task.get("verification_challenges")
    if not isinstance(inherited, list) or not all(isinstance(c, dict) for c in inherited):
        raise ValueError("REVIEW_CORRECTION_REFUSED: malformed inherited challenges")
    for item in inherited:
        path = _correction_path(item.get("path") or "", run_p)
        if _sha256_text(path.read_text(encoding="utf-8")) != item.get("sha256"):
            raise ValueError("REVIEW_CORRECTION_REFUSED: inherited challenge drift")
        material_paths.append(path)
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in material_paths}
    if (prior_challenge_bytes is not None and hashes[str(challenge_path)] !=
            hashlib.sha256(prior_challenge_bytes).hexdigest()):
        raise ValueError("REVIEW_CORRECTION_REFUSED: prior challenge changed "
                         "during preparation")
    key = f"review-correction-{request_sha}"
    new_review = _correction_path(
        run_p / "ai_reviews" / _safe_problem_id(pid) / f"{key}.json",
        run_p, exists=False)
    new_challenge = _correction_path(
        run_p / "ai_verification_challenges" / _safe_problem_id(pid)
        / key / "challenge_tb.sv", run_p, exists=False)

    def replace_paths(value):
        if isinstance(value, dict):
            return {k: replace_paths(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace_paths(v) for v in value]
        if value == task["challenge_path"]:
            return str(new_challenge)
        if value == task["review_path"]:
            return str(new_review)
        return value

    new_task = replace_paths(task)
    new_task["verification_challenges"] = list(inherited)
    if challenge is not None and not any(
            c.get("sha256") == challenge["sha256"] for c in inherited):
        new_task["verification_challenges"].append(challenge)
    new_task["review_correction"] = {
        "schema": _REVIEW_CORRECTION_SCHEMA,
        "request_sha256": request_sha,
        "archive_path": str(archive),
        "prior_review_path": str(review_path),
        "prior_review_sha256": request["review_sha256"],
        "prior_challenge_sha256": prior_challenge_sha256,
        "status": "FRESH_REVIEW_REQUIRED",
        "repair_authorized": False,
    }
    if prior_challenge_status is not None:
        new_task["review_correction"]["prior_challenge_status"] = prior_challenge_status
    expected_transition = {"schema": _REVIEW_CORRECTION_SCHEMA,
                           "prior_task": task, "new_task": new_task,
                           "material_sha256": hashes,
                           "request_sha256": request_sha}
    if transition is not None and transition != expected_transition:
        raise ValueError("REVIEW_CORRECTION_REFUSED: transition evidence drift")
    if current not in (task, new_task):
        raise ValueError("REVIEW_CORRECTION_REFUSED: current task drift")
    already_applied = current == new_task
    if not already_applied:
        solve, _ = _correction_object(_correction_path(run_p / "solve_report.json", run_p))
        results = solve.get("results")
        matches = ([r for r in results if isinstance(r, dict) and r.get("id") == pid]
                   if isinstance(results, list) else [])
        if len(matches) != 1 or matches[0].get("accepted") is not False:
            raise ValueError("REVIEW_CORRECTION_REFUSED: task must be unaccepted")
        acceptance_path = _correction_path(run_p / _ACCEPTANCE_REPORT, run_p,
                                          exists=False)
        if acceptance_path.exists():
            acceptance, _ = _correction_object(acceptance_path)
            if pid in (acceptance.get("accepted_ids") or []):
                raise ValueError("REVIEW_CORRECTION_REFUSED: candidate already accepted")
        response = _correction_path(task.get("response_path") or "", run_p, exists=False)
        if response.exists() or new_review.exists() or new_challenge.exists():
            raise ValueError("REVIEW_CORRECTION_REFUSED: published response or occupied new path")
    archives = {"prior_task.json": json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n",
                "prior_review.json": review_raw}
    if prior_challenge_bytes is not None:
        archives["prior_challenge_tb.sv"] = prior_challenge_bytes.decode("utf-8")
    if prior_challenge_status is not None:
        archives["prior_challenge_status.json"] = json.dumps({
            "status": prior_challenge_status, "sha256": prior_challenge_sha256,
            "path": str(challenge_path), "verification_obligation_promoted": False,
        }, sort_keys=True) + "\n"
    # The transition is the prepared-archive marker; keep it last so an
    # interrupted archive write can be completed by the ordinary replay path.
    archives["request.json"] = request_raw
    archives["transition.json"] = json.dumps(expected_transition, ensure_ascii=False,
                                              sort_keys=True) + "\n"
    for name, raw in archives.items():
        path = _correction_path(archive / name, run_p, exists=False)
        if path.exists():
            if path.read_bytes().decode("utf-8") != raw:
                raise ValueError("REVIEW_CORRECTION_REFUSED: immutable archive drift")
        else:
            if transition is not None:
                raise ValueError("REVIEW_CORRECTION_REFUSED: immutable archive missing")
            _atomic_write_text(path, raw)
    # Recheck all source material before the one authoritative commit.
    if challenge_path.exists() != (prior_challenge_bytes is not None):
        raise ValueError("REVIEW_CORRECTION_REFUSED: prior challenge presence "
                         "changed during preparation")
    for path, digest in hashes.items():
        source = _correction_path(path, run_p)
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("REVIEW_CORRECTION_REFUSED: source changed during preparation")
    if task_path.read_text(encoding="utf-8") != task_raw:
        raise ValueError("REVIEW_CORRECTION_REFUSED: worklist changed during preparation")
    if not already_applied:
        tasks[ids.index(pid)] = new_task
        _write_jsonl(task_path, tasks)
    print(f"  {pid}: REVIEW_CORRECTION_" +
          ("ALREADY_APPLIED" if already_applied else "APPLIED") +
          "; same candidate; FRESH_REVIEW_REQUIRED; no repair permit")


_PROGRAM_RETRY_SCHEMA = "vibeic.benchmark.program_retry.v1"


def _program_source_identity() -> dict:
    """Fingerprint the installed executable Program sources, including dirty edits.

    The SECOND half of the merged operation's identity. A Program can be fixed
    without a version bump -- the fix is real, the version pair is unchanged --
    and a Program version can move with the executable sources untouched. The
    two identities are neither necessary nor sufficient for each other in
    either direction, so `_apply_program_regate` requires BOTH to have moved.
    """
    root = Path(__file__).resolve().parent.parent
    paths = [root / ".claude-plugin" / "plugin.json"]
    for directory in ("programs", "_shared", "flow", "config", "tools",
                      "schemas", "data", "ip-catalog", "mcp-eda"):
        paths.extend(p for p in (root / directory).rglob("*") if p.is_file()
                     and not {"tests", "__pycache__", ".pytest_cache"}.intersection(p.relative_to(root).parts)
                     and p.suffix not in {".pyc", ".md"})
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(paths)}
    return {"schema": "vibeic.program.source_identity.v1",
            "source_sha256": _review_task_digest(hashes)}


def _regate_path(path, run_p, *, exists=True):
    """`_correction_path` under this operation's own refusal token."""
    return _correction_path(path, run_p, exists=exists, token=_REGATE_REFUSED)


def _regate_project_tree(project: Path) -> dict:
    """Bind all source files and internal relative links without following links."""
    hashes = {}
    for path in sorted(project.rglob("*")):
        key = str(path.relative_to(project))
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute() or not path.resolve().is_relative_to(project):
                raise ValueError(f"{_REGATE_REFUSED}: escaping project symlink")
            hashes[key] = {"symlink": target}
        elif path.is_file():
            hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():
            raise ValueError(f"{_REGATE_REFUSED}: unsupported project file")
    return hashes


def _guard_program_regate_journals(run_p: Path) -> None:
    """BLOCKING: an interrupted promotion needs explicit reconciliation."""
    root = _regate_path(run_p / "program_regates", run_p, exists=False)
    for archive in sorted(root.glob("*/*")):
        _regate_path(archive, run_p, exists=False)
        intent = _regate_path(archive / "intent.json", run_p, exists=False)
        completed = _regate_path(archive / "complete.json", run_p, exists=False)
        failed = _regate_path(archive / "failed.json", run_p, exists=False)
        if not intent.exists():
            continue
        reason = None
        try:
            plan = _strict_json_loads(intent.read_text())
            request_path = _regate_path(archive / "request.json", run_p)
            request = _strict_json_loads(request_path.read_text())
            if (plan.get("schema") != _PROGRAM_REGATE_SCHEMA or plan.get("request") != request
                    or _sha256_text(request_path.read_text()) != archive.name
                    or plan.get("program_identity") != request.get("program_identity")
                    or _review_task_digest(plan["prior_task"]) != request.get("task_sha256")):
                raise ValueError("intent/request binding differs")
            if completed.exists() and not failed.exists():
                marker = _strict_json_loads(completed.read_text())
                transition_path = _regate_path(archive / "transition.json", run_p)
                transition = _strict_json_loads(transition_path.read_text())
                if (marker.get("schema") != _PROGRAM_REGATE_SCHEMA
                        or marker.get("request_sha256") != archive.name
                        or marker.get("archive_path") != str(archive)
                        or marker.get("program_identity") != plan["program_identity"]
                        or transition.get("prior_task") != plan["prior_task"]
                        or transition["new_task"].get("program_regate") != marker):
                    raise ValueError("completion/transition binding differs")
            elif failed.exists() and not completed.exists():
                marker = _strict_json_loads(failed.read_text())
                if (marker.get("schema") != _PROGRAM_REGATE_SCHEMA
                        or marker.get("request_sha256") != archive.name
                        or marker.get("intent_sha256") != _review_task_digest(plan)
                        or marker.get("promotion_started") is not False
                        or (archive / "prior_project").exists()
                        or (archive / "promotion.json").exists()):
                    raise ValueError("failure marker cannot establish an untouched original")
            else:
                reason = "missing or conflicting terminal markers"
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            reason = str(exc)
        if reason is not None:
            raise ValueError(f"{_REGATE_REFUSED}: interrupted journal requires "
                             f"reconciliation before resume: {archive}: {reason}")


def _regate_request_field(request: dict, primary: str, legacy: str):
    """One request field under BOTH operations' names.

    `--program-regate` (v1.17.63) and `--program-retry` (v1.17.71) named the
    same two hashes differently. The merged operation accepts either spelling
    so a caller written against either front door still binds, and refuses a
    request that supplies both under conflicting values -- an ambiguous
    identity is not an identity.
    """
    have_primary = request.get(primary) is not None
    have_legacy = request.get(legacy) is not None
    if have_primary and have_legacy and request[primary] != request[legacy]:
        raise ValueError(f"{_REGATE_REFUSED}: {primary} and {legacy} disagree")
    if have_primary:
        return request[primary]
    return request.get(legacy)


def _apply_program_regate(bench: str, dataset: str | Path, run_p: Path,
                          request_path: Path, worker_threads: int) -> int:
    """The ONE Program re-entry operation: re-run the FIXED Program on ONE
    preserved, signed pre-gate input, under BOTH Program identities.

    BLOCKING. A deterministic gate can normalize a signed author candidate into
    different bytes before freezing it, which correctly makes the author's
    final signature stale. When that transform is later FIXED, the pending task
    is stuck: its unchanged working output is not re-gated, restoring the signed
    input reads as a new AI edit needing a counterexample against the unwanted
    candidate, and re-signing the unwanted output would attribute a PROGRAM
    mutation to the AI author. This operation is the missing third option.

    IDENTITY -- both halves, always. The Program must have moved in BOTH the
    declared version pair (`program_version_before`/`_after`) and the executable
    SOURCE TREE (`_program_source_identity`). Neither implies the other: a fix
    can land with no version bump, and a version can move with no executable
    change. Requiring one alone lets the other kind of no-op retry loop.

    EXECUTION. The re-run happens in a STAGED copy of the project under the
    resume coordinator lock, with an immutable intent journalled before staging
    and a terminal marker after, so an interrupted promotion blocks the next
    resume instead of resuming over unknown state. Failure leaves the original
    project and task untouched.

    ATTRIBUTION. The regenerated bytes are recorded as PROGRAM-authored with the
    author's signature unchanged (`_verified_program_regate` then binds the
    author's signature to the preserved signed INPUT, not to the Program's
    output). It never accepts, never publishes, never supersedes a challenge and
    never grants a repair permit: the regenerated output carries the SAME
    downstream obligations as a first-time output, including a fresh independent
    review.

    The stale-signature refusal is NOT weakened. Every task without a verified
    `program_regate` record is compared exactly as before; see
    `_signed_candidate_hash`.

    Merged from `--program-regate` (v1.17.63) and `--program-retry` (v1.17.71)
    under issue #2047. `--program-retry` remains as a deprecated alias for one
    version; see `cmd_resume`.
    """
    import benchmark_io_adapter as bio                  # noqa: PLC0415
    import emit_attestation as ea                       # noqa: PLC0415
    import flow_phase_attribution as fpa                # noqa: PLC0415
    import task_nature_route as tnr                     # noqa: PLC0415

    def refuse(reason):
        raise ValueError(f"{_REGATE_REFUSED}: {reason}")

    material = {}

    def bound(path):
        path = _regate_path(path, run_p)
        material[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def obj(path):
        value = _strict_json_loads(bound(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            refuse("expected a JSON object")
        return value

    request_path = bound(request_path)
    request_raw = request_path.read_text(encoding="utf-8")
    request = obj(request_path)
    request_sha = _sha256_text(request_raw)
    if request.get("schema") not in (_PROGRAM_REGATE_SCHEMA,
                                     _PROGRAM_RETRY_SCHEMA):
        refuse("unsupported request schema")

    # --- identity half 1: the executable Program sources ------------------
    identity = _program_source_identity()
    if request.get("program_identity") is None:
        refuse("request names no Program source identity; the merged "
               "operation requires the source tree AND the version pair")
    if request.get("program_identity") != identity:
        refuse("stale Program identity")

    rationale = _regate_request_field(request, "rationale", "reason")
    if not isinstance(rationale, str) or len(rationale.strip()) < 80:
        refuse("rationale needs 80 characters")
    author = request.get("author")
    blind = request.get("blind")
    if (not isinstance(author, dict) or author.get("kind") != "AI"
            or not isinstance(author.get("model"), str)
            or author["model"].strip().lower() in {"", "unknown", "unspecified", "n/a"}
            or not isinstance(blind, dict) or blind.get("oracle_accessed") is not False):
        refuse("attributed blind AI required")

    task_path = bound(run_p / _REVIEW_WORKLIST)
    tasks = _read_jsonl(task_path)
    pid = request.get("id")
    ids = [t.get("id") for t in tasks]
    if not isinstance(pid, str) or not pid or len(set(ids)) != len(ids) or ids.count(pid) != 1:
        refuse("missing or duplicate review task")
    task = tasks[ids.index(pid)]
    if task.get("schema") != _REVIEW_TASK_SCHEMA:
        refuse("wrong task schema")
    if task.get("candidate_origin") != "AI_REPAIR":
        refuse("only an AI_REPAIR candidate can be re-gated")

    stale_output = _regate_request_field(request, "stale_output_sha256",
                                         "rtl_sha256")
    signed = _regate_request_field(request, "signed_input_sha256",
                                   "input_rtl_sha256")
    for field, value, expected in (
            ("task_sha256", request.get("task_sha256"), _review_task_digest(task)),
            ("prompt_sha256", request.get("prompt_sha256"), task.get("prompt_sha256")),
            ("stale_output_sha256", stale_output, task.get("rtl_sha256"))):
        if value != expected or not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            refuse("stale " + field)
    if not re.fullmatch(r"[0-9a-f]{64}", str(signed or "")):
        refuse("malformed signed_input_sha256")
    if signed == str(task.get("rtl_sha256") or ""):
        refuse("the gates did not change the signed input; nothing to re-gate")

    # --- identity half 2: the declared Program version pair ---------------
    before = str(request.get("program_version_before") or "")
    after = str(request.get("program_version_after") or "")
    running = _program_version()
    if not before or not after:
        refuse("both Program versions must be named")
    if before == after:
        refuse("Program version unchanged; a retry with the same Program "
               "is a loop, not a fix")
    if not running:
        refuse("the running Program version is not readable")
    if after != running:
        refuse(f"program_version_after {after!r} is not the running "
               f"Program {running!r}")
    if (task.get("program_regate") or {}).get("program_identity") == identity:
        refuse("Program identity has not changed since the prior re-entry")

    solve_path = bound(run_p / "solve_report.json")
    solve = obj(solve_path)
    policy = solve.get("acceptance_policy") or {}
    if (policy.get("required") is not True
            or policy.get("review_task_schema") != _REVIEW_TASK_SCHEMA
            or policy.get("review_schema") != _AI_REVIEW_SCHEMA):
        refuse("unsupported solve acceptance policy")
    results = solve.get("results")
    matches = [r for r in results if r.get("id") == pid]
    if len(matches) != 1 or matches[0].get("accepted") is not False:
        refuse("task must be unaccepted")
    result = matches[0]
    if result.get("exit") not in tnr.flow_step_ids():
        refuse("missing or unsupported declared exit")
    fmt = _dispatch_format(bench, run_p)
    if fmt is None:
        refuse("no bound IO adapter")
    acceptance_path = _regate_path(run_p / _ACCEPTANCE_REPORT, run_p, exists=False)
    acceptance = obj(acceptance_path) if acceptance_path.exists() else {}
    if pid in (acceptance.get("accepted_ids") or []):
        refuse("candidate already accepted")
    response = _regate_path(task.get("response_path"), run_p, exists=False)
    if response != run_p / "responses" / f"{_safe_problem_id(pid)}.json":
        refuse("response path is not the canonical publication path")
    if response.exists():
        refuse("candidate already published")
    project = _regate_path(task.get("project"), run_p, exists=False)
    if project != run_p / "projects" / _safe_problem_id(pid) or not project.is_dir():
        refuse("project is not the runner-owned project")
    try:
        route_worklist = _read_jsonl(run_p / _ROUTE_WORKLIST)
    except (OSError, ValueError, TypeError) as exc:
        refuse("route worklist is unreadable: " + str(exc))
    admission = _validated_route_reentry_state(
        bench=bench, dataset=dataset, fmt=fmt, run_p=run_p, pid=pid,
        result=result, route_worklist=route_worklist,
        allow_d1_only=False, supplied_rtl=True)
    if admission.get("status") != "ACTIVE":
        refuse(str(admission.get("reason") or "ROUTE_REENTRY_REFUSED"))
    tree = _regate_project_tree(project)
    prompt = bound(task.get("prompt_path"))
    if prompt != project / "input" / "phase1_prompt.md" or _sha256_text(prompt.read_text()) != task["prompt_sha256"]:
        refuse("prompt drift")
    if task.get("phase1_provenance") != ea.phase1_provenance(project):
        refuse("Phase-1 provenance drift")

    def snapshot(candidate):
        if not isinstance(candidate, dict):
            refuse("missing candidate snapshot")
        for field in ("manifest_path", "completion_path", "response_payload_path"):
            bound(candidate.get(field))
        for path in candidate.get("rtl_paths") or []:
            bound(path)
        reasons = _validate_candidate_snapshot(candidate, pid)
        if reasons:
            refuse("; ".join(reasons))

    for field in ("candidate_snapshot", "program_candidate_snapshot", "repair_parent_candidate_snapshot"):
        snapshot(task.get(field))
    working = [bound(p) for p in _rtl_files(project)]
    if ([str(p) for p in working] != task.get("working_rtl_paths")
            or _sha256_text(_candidate_text(working)) != task["rtl_sha256"]
            or task["candidate_snapshot"].get("rtl_sha256") != task["rtl_sha256"]
            or task.get("rtl_paths") != task["candidate_snapshot"]["rtl_paths"]):
        refuse("working or frozen RTL drift")
    provenance = task.get("repair_provenance")
    if not isinstance(provenance, dict):
        refuse("task lacks its AI repair provenance")
    record_path = bound(provenance.get("path"))
    if request.get("repair_record_sha256") != material[str(record_path)]:
        refuse("stale repair record hash")
    if str(provenance.get("repaired_rtl_sha256") or "") != signed:
        refuse("signed_input_sha256 is not the hash the author signed")

    # --- the preserved input, named by BOTH the request and the task ------
    pre_gate = task.get("pre_gate_input")
    if not isinstance(pre_gate, dict):
        refuse("task has no preserved pre-gate input record")
    if str(pre_gate.get("signed_input_sha256") or "") != signed \
            or str(pre_gate.get("gate_output_sha256") or "") \
            != str(task.get("rtl_sha256") or ""):
        refuse("preserved pre-gate binding does not name this task's pair")
    # The signed input is preserved TWICE, by the two merged operations'
    # different records, and the merged operation binds BOTH: the request's
    # immutable CANDIDATE snapshot (--program-retry) and the task's PRE-GATE
    # input manifest (--program-regate). They must describe the same bytes.
    input_manifest = bound(request.get("input_manifest_path"))
    if request.get("input_manifest_sha256") is not None \
            and request["input_manifest_sha256"] != material[str(input_manifest)]:
        refuse("stale input manifest hash")
    input_candidate = obj(input_manifest)
    snapshot(input_candidate)
    if (input_candidate.get("manifest_path") != str(input_manifest)
            or input_candidate.get("rtl_sha256") != signed
            or len(input_candidate.get("rtl_paths") or []) != len(working)
            or input_candidate.get("source_rtl_paths") != task["working_rtl_paths"]):
        refuse("preserved input binding or source paths differ")

    manifest_path = _regate_path(pre_gate.get("input_manifest_path") or "", run_p)
    preserved = obj(manifest_path)
    if preserved.get("schema") != _PRE_GATE_INPUT_SCHEMA \
            or str(preserved.get("id")) != pid \
            or str(preserved.get("rtl_sha256") or "") != signed:
        refuse("preserved input manifest does not match the request")
    if before != str(preserved.get("program_version") or ""):
        refuse(f"program_version_before {before!r} is not the Program that "
               "produced the preserved input")
    preserved_paths = [bound(q) for q in preserved.get("rtl_paths") or []]
    if not preserved_paths:
        refuse("preserved input has no RTL")
    if len(preserved_paths) != len(preserved.get("source_rtl_paths") or []):
        refuse("preserved input manifest is internally inconsistent")
    if len(preserved_paths) != len(working):
        refuse("preserved input does not cover the working RTL file set")
    if _sha256_text(_candidate_text(preserved_paths)) != signed:
        refuse("preserved signed input hash drift")
    automatic_input = task.get("repair_input_candidate_snapshot")
    if automatic_input is not None and automatic_input != input_candidate:
        refuse("request differs from automatically preserved input")
    inherited = task.get("verification_challenges")
    if not isinstance(inherited, list) or not inherited:
        refuse("missing inherited challenges")
    inherited = list(inherited)
    for challenge in inherited:
        path = bound(challenge.get("path"))
        if _sha256_text(path.read_text()) != challenge.get("sha256"):
            refuse("inherited challenge drift")
    signed_challenge = next((c for c in inherited if c.get("sha256") == provenance.get("challenge_sha256")), None)
    if signed_challenge is None:
        refuse("signed challenge is not inherited")
    validated, reasons = _validate_repair_record(
        record_path, {**task, "rtl_sha256": task["repair_parent_candidate_snapshot"]["rtl_sha256"]},
        input_candidate["rtl_sha256"], signed_challenge)
    if reasons or validated != provenance:
        refuse("signed input provenance drift: " + "; ".join(reasons))

    # A bound current proof is preserved and remains an inherited obligation.
    review_path = _regate_path(task.get("review_path"), run_p, exists=False)
    challenge_path = _regate_path(task.get("challenge_path"), run_p, exists=False)
    prior_review = None
    if review_path.exists() or challenge_path.exists():
        prior_review = obj(review_path)
        bound(challenge_path)
        bound((prior_review.get("verification_test") or {}).get("path"))
        if (request.get("review_sha256") != material[str(review_path)]
                or request.get("challenge_sha256") != material[str(challenge_path)]
                or any(prior_review.get(k) != task.get(k) for k in ("id", "prompt_sha256", "rtl_sha256"))
                or prior_review.get("schema") != _AI_REVIEW_SCHEMA
                or (prior_review.get("reviewer") or {}).get("kind") != "AI"
                or (prior_review.get("blind") or {}).get("oracle_accessed") is not False):
            refuse("current review/test is not exactly bound")
        current_challenge, reasons = _challenge_from_review(task, prior_review, prompt.read_text())
        if reasons or not current_challenge:
            refuse("invalid current challenge: " + "; ".join(reasons))
        if not any(c.get("sha256") == current_challenge["sha256"] for c in inherited):
            inherited.append(current_challenge)
    elif request.get("review_sha256") is not None or request.get("challenge_sha256") is not None:
        refuse("bound current review/test is missing")
    key = "program-regate-" + request_sha
    new_review = _regate_path(run_p / "ai_reviews" / _safe_problem_id(pid) / (key + ".json"), run_p, exists=False)
    new_challenge = _regate_path(run_p / "ai_verification_challenges" / _safe_problem_id(pid) / key / "challenge_tb.sv", run_p, exists=False)
    archive = _regate_path(run_p / "program_regates" / _safe_problem_id(pid) / request_sha, run_p, exists=False)
    if archive.exists() or new_review.exists() or new_challenge.exists():
        refuse("occupied re-entry archive or fresh review/test path")
    for name in (_BACKUP_WORKLIST, _REPAIR_WORKLIST):
        path = _regate_path(run_p / name, run_p, exists=False)
        if path.exists():
            bound(path)
    if any(t.get("id") == pid for t in _read_jsonl(run_p / _BACKUP_WORKLIST)):
        refuse("task also has a pending AI backup")

    def recheck():
        for path, digest in material.items():
            if hashlib.sha256(_regate_path(path, run_p).read_bytes()).hexdigest() != digest:
                refuse("source changed during preparation: " + path)
        if _regate_project_tree(project) != tree or _program_source_identity() != identity:
            refuse("project or Program source changed during preparation")
        if response.exists() or new_review.exists() or new_challenge.exists():
            refuse("publication or fresh review/test path occupied during preparation")

    recheck()
    intent = {
        "schema": _PROGRAM_REGATE_SCHEMA, "request": request, "prior_task": task,
        "material_sha256": material, "project_tree": tree,
        "program_identity": identity, "status": "PREPARED"}
    _write_immutable_json(archive / "intent.json", intent)
    _write_immutable_text(archive / "request.json", request_raw)
    for source in (task_path, solve_path, acceptance_path,
                   run_p / _BACKUP_WORKLIST, run_p / _REPAIR_WORKLIST):
        if source.exists():
            _write_immutable_text(archive / "prior_state" / source.name,
                                  source.read_bytes().decode("utf-8"))
    if prior_review is not None:
        _write_immutable_text(archive / "prior_review.json", review_path.read_text())
        _write_immutable_text(archive / "prior_challenge_tb.sv", challenge_path.read_text())
    staged = archive / "staged_project"
    promoted = False
    try:
        shutil.copytree(project, staged, symlinks=True)
        for source, destination in zip(input_candidate["rtl_paths"], working, strict=True):
            _atomic_write_bytes(staged / destination.relative_to(project), Path(source).read_bytes())
        if _sha256_text(_candidate_text(_rtl_files(staged))) != signed:
            refuse("staged work tree does not hash to the signed input")
        bio.public_original_input(
            staged, pid, task["prompt_sha256"], expected=task["public_original_input"])
        input_material = _runner_material_snapshot(staged)
        preservation = provenance["repair_contract"]["preservation"]
        for row in preservation["sources"]:
            source_relative = row["path"][4:] if row["path"].startswith("rtl/") else row["path"]
            expected = row.get("candidate_sha256", preservation.get("candidate_sha256"))
            if input_material["output_rtl"].get(source_relative, {}).get("sha256") != expected:
                refuse("signed preimage byte binding mismatch: " + row["path"])
        # Validate the unchanged author declaration on ONLY the exact signed
        # preimage. The historical gate report is not a new runner verdict.
        preimage = bio.collect(
            fmt, pid, staged, supplied_rtl=True,
            repair_contract=provenance["repair_contract"], require_repair_contract=True,
            required_top=_required_scorer_top(_entry(bench), fmt))
        if not preimage.get("ok") or (preimage.get("repair_contract") or {}).get("verdict") != "PASS":
            refuse("author preimage contract failed: " + str(preimage.get("reason")))
        if _runner_material_snapshot(staged) != input_material:
            refuse("signed preimage changed during contract validation")
        preimage_path = archive / "preimage_contract.json"
        _write_immutable_json(preimage_path, {
            "schema": _PROGRAM_REGATE_SCHEMA, "signed_input_sha256": signed,
            "author_record_sha256": material[str(record_path)],
            "input_material": input_material, "validation": preimage["repair_contract"]})
        recheck()
        phase2_report = staged / "reports" / "orchestrator" / "phase2_one_shot.json"
        if phase2_report.exists():
            phase2_report.unlink()  # staged copy only; require fresh gate evidence
        runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"
        argv = _resume_solver_argv(
            runner, staged, True, admission["entry_step"],
            admission["exit_step"], admission["delivery_route"])
        d1_snapshot = _capture_d1_evidence(staged)
        process = _run_from_d1_snapshot(
            _RunnerBudget(1, 1, worker_threads), argv, d1_snapshot,
            admission["route_receipt"], admission["activation"],
            admission["task"]["task_sha256"], authority_project=project)
        if (ea.phase1_provenance(staged) != task["phase1_provenance"]
                or _sha256_text((staged / "input" / "phase1_prompt.md").read_text())
                != task["prompt_sha256"]):
            refuse("Program changed bound prompt or Phase-1 inputs")
        diagnostic = _runner_diagnostics(process, argv, staged)
        output_contract = provenance["repair_contract"]
        declaration_path = archive / "output_contract.json"
        if not process.error and not (diagnostic and diagnostic.get("reason")):
            invocation = process.invocation
            if (not isinstance(invocation, dict) or invocation.get("status") != "COMPLETED"
                    or invocation.get("material_before") != input_material
                    or invocation["material_after"]["input"] != input_material["input"]):
                refuse("Program transformation lacks completed current input/output provenance")
            bio.public_original_input(
                staged, pid, task["prompt_sha256"], expected=task["public_original_input"])
            output_contract = _program_output_repair_contract(
                provenance["repair_contract"], identity, invocation["material_after"])
            _write_immutable_json(declaration_path, {
                "schema": _PROGRAM_REGATE_SCHEMA, "actor": "PROGRAM",
                "program_identity": identity, "runner_invocation": invocation,
                "signed_input_sha256": signed,
                "output_rtl_sha256": invocation["material_after"]["output_rtl_sha256"],
                "author_record_sha256": material[str(record_path)],
                "preimage_contract_sha256": hashlib.sha256(preimage_path.read_bytes()).hexdigest(),
                "repair_contract": output_contract})
        got = _collect_runner_result(
            process, argv, fmt, pid, staged, supplied_rtl=True,
            repair_contract=output_contract,
            require_repair_contract=True)
        _write_immutable_json(archive / "runner_result.json", {
            "argv": argv, "rc": process.rc, "error": process.error,
            "runner_diagnostics": got.get("runner_diagnostics"),
            "runner_invocation": getattr(process, "invocation", None), "collected": got})
        if process.error or not got.get("ok"):
            refuse("Program runner failed; original task/project retained: "
                   + str(process.error or got.get("reason")))
        _regate_project_tree(staged)
        if (ea.phase1_provenance(staged) != task["phase1_provenance"]
                or _sha256_text((staged / "input" / "phase1_prompt.md").read_text()) != task["prompt_sha256"]):
            refuse("Program changed bound prompt or Phase-1 inputs")
        candidate_root = _regate_path(
            run_p / "candidate_snapshots" / _safe_problem_id(pid)
            / f"{key}-{_sha256_text(str(got.get('completion') or ''))}", run_p, exists=False)
        if candidate_root.exists():
            refuse("occupied fresh candidate snapshot")
        for source in _rtl_files(staged):
            _regate_path(source, run_p)
        # Keep absolute gate-report paths valid in the retained staged tree.
        # The promotable copy is separate; no archived report is rewritten.
        promotion_project = archive / "promotion_project"
        shutil.copytree(staged, promotion_project, symlinks=True)
        if _regate_project_tree(promotion_project) != _regate_project_tree(staged):
            refuse("staged output changed while preparing promotion")
        recheck()
        if candidate_root.exists():
            refuse("fresh candidate snapshot occupied during preparation")
        _write_immutable_json(archive / "promotion.json", {"output": got, "staged_tree": _regate_project_tree(staged)})
        # Any interruption after this point is unknown state and blocks resume.
        promoted = True
        project.rename(archive / "prior_project")
        promotion_project.rename(project)
        phases = fpa.attribute(project, routing=result.get("routing_verdict") or {},
                               entry="2", evidence=result.get("evidence"),
                               exit_step=admission["exit_step"],
                               rtl_present=True, artefact_collected=True)
        new_task = _make_ai_review_task(
            pid, project, got, result.get("routing_verdict") or {}, int(process.rc), run_p, "AI_REPAIR",
            program_phases=phases, verification_challenges=inherited,
            runner_invocation=getattr(process, "invocation", None),
            expected_public_input=task.get("public_original_input"),
            program_candidate=task["program_candidate_snapshot"],
            repair_parent_candidate=task["repair_parent_candidate_snapshot"],
            repair_provenance=provenance, repair_input_candidate=input_candidate,
            review_key=key, archive_key=key)
        new_task["pre_gate_input"] = _bind_pre_gate_output(
            preserved, new_task["rtl_sha256"])
        action = {"schema": _PROGRAM_REGATE_SCHEMA, "actor": "PROGRAM",
                  "program_identity": identity, "archive_path": str(archive),
                  "request_sha256": request_sha,
                  "signed_input_sha256": signed,
                  "input_rtl_sha256": signed,
                  "input_manifest_path": str(manifest_path),
                  "stale_output_sha256": task["rtl_sha256"],
                  "prior_output_rtl_sha256": task["rtl_sha256"],
                  "new_output_sha256": new_task["rtl_sha256"],
                  "output_rtl_sha256": new_task["rtl_sha256"],
                  "program_version_before": before,
                  "program_version_after": after,
                  "output_contract_path": str(declaration_path),
                  "output_contract_sha256": hashlib.sha256(declaration_path.read_bytes()).hexdigest(),
                  "attributed_to": "PROGRAM",
                  "author_signature_unchanged": True,
                  "repair_authorized": False,
                  "status": "FRESH_REVIEW_REQUIRED",
                  "entry": "2", "exit": admission["exit_step"], "runner_rc": process.rc,
                  "accepted": False}
        new_task["program_regate"] = action
        tasks[ids.index(pid)] = new_task
        _write_immutable_json(archive / "transition.json", {"prior_task": task, "new_task": new_task})
        _write_jsonl(task_path, tasks)
        program_first_phases = result.get("program_first_phases") or result.get("phases") or {}
        if program_first_phases:
            result["program_first_phases"] = program_first_phases
            phases["phase2_solving"] = program_first_phases.get("phase2_solving", {})
            phases["phase4_debugging"] = program_first_phases.get("phase4_debugging", {})
        result.update({"accepted": False, "rc": process.rc, "candidate_ready": True,
                       "candidate_origin": "AI_REPAIR", "awaiting_ai": True,
                       "awaiting_ai_review": True, "ai_repair_required": False,
                       "review_task": new_task["review_path"], "program_regate": action,
                       "phases": phases})
        result.pop("runner_diagnostics", None)
        if got.get("runner_diagnostics"):
            result["runner_diagnostics"] = got["runner_diagnostics"]
        solve["four_phase_summary"] = _four_phase_rollup(fpa, results)
        _atomic_write_json(solve_path, solve)
        repairs = [t for t in _read_jsonl(run_p / _REPAIR_WORKLIST) if t.get("id") != pid]
        _write_jsonl(run_p / _REPAIR_WORKLIST, repairs)
        outcomes = [t for t in acceptance.get("review_outcomes") or [] if t.get("id") != pid]
        outcomes.append({"id": pid, "status": "PENDING", "reasons": ["fresh independent review required"]})
        acceptance.update({"schema": _ACCEPTANCE_SCHEMA, "status": "PENDING",
                           "review_outcomes": outcomes, "total": len(results),
                           "accepted_ids": [r["id"] for r in results if r.get("accepted")],
                           "accepted": sum(r.get("accepted") is True for r in results),
                           "pending_review": sum(o.get("status") in {"PENDING", "REJECTED"} for o in outcomes),
                           "pending_repair": len(repairs)})
        _atomic_write_json(acceptance_path, acceptance)
        _write_immutable_json(archive / "complete.json", action)
    except Exception as exc:
        if not promoted:
            _write_immutable_json(archive / "failed.json", {
                "schema": _PROGRAM_REGATE_SCHEMA, "request_sha256": request_sha,
                "intent_sha256": _review_task_digest(intent), "promotion_started": False,
                "status": "REFUSED", "reason": str(exc)})
        raise
    print(f"  {pid}: PROGRAM_REGATE_APPLIED; program {before} -> {after}; "
          f"signed input {signed[:12]} re-entered; PROGRAM-attributed; "
          "FRESH_REVIEW_REQUIRED; signature unchanged; no repair permit")
    return 2


def cmd_resume(bench: str, dataset: str, run: str, jobs: int = 1,
               heavy_jobs: int | None = None,
               worker_threads: int = 0,
               review_correction: str | None = None,
               program_regate: str | None = None,
               program_retry: str | None = None) -> int:
    """Run the sole resume coordinator under an exclusive run-root lock.

    TWO explicit operations remain, separate and mutually exclusive: a review
    correction and the ONE Program re-entry. Each keeps its own refusal token
    so the caller is told WHICH operation refused, and no combination is
    silently ordered for them.

    `program_retry` is the DEPRECATED alias of `program_regate` (issue #2047,
    which merged `--program-retry` into `--program-regate`). It maps onto the
    same operation, under the same refusal token, and prints a deprecation
    line, so a caller written against the old front door does not break
    silently. Giving both names at once is refused rather than ordered.
    """
    try:
        if program_regate is not None and program_retry is not None:
            raise ValueError(f"{_REGATE_REFUSED}: --program-retry is the "
                             "deprecated alias of --program-regate; give one")
        if program_retry is not None:
            print(_program_retry_deprecation(), file=sys.stderr)
            program_regate, program_retry = program_retry, None
        if review_correction is not None and program_regate is not None:
            raise ValueError(f"{_REGATE_REFUSED}: cannot combine with review correction")
        if review_correction is not None or program_regate is not None:
            # Check BEFORE resolve/open of the persistent coordinator lock.
            _correction_path(Path(run) / _COORDINATOR_LOCK,
                             Path(run).absolute().resolve(), exists=False,
                             token=(_CORRECTION_REFUSED
                                    if review_correction is not None
                                    else _REGATE_REFUSED))
        with _run_root_coordinator_lock(Path(run), "resume"):
            _guard_program_regate_journals(Path(run).resolve())
            if review_correction is not None:
                try:
                    _apply_review_correction(Path(run).resolve(), Path(review_correction))
                except (KeyError, TypeError, AttributeError) as exc:
                    raise ValueError("REVIEW_CORRECTION_REFUSED: malformed evidence: "
                                     f"{type(exc).__name__}: {exc}") from exc
            if program_regate is not None:
                try:
                    return _apply_program_regate(
                        bench, dataset, Path(run).resolve(),
                        Path(program_regate), worker_threads)
                except (KeyError, TypeError, AttributeError, IndexError) as exc:
                    raise ValueError(f"{_REGATE_REFUSED}: malformed evidence: "
                                     f"{type(exc).__name__}: {exc}") from exc
            return _cmd_resume_locked(
                bench, dataset, run, jobs=jobs, heavy_jobs=heavy_jobs,
                worker_threads=worker_threads)
    except _CoordinatorBusy as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bench", nargs="?", help="benchmark name (see --list)")
    ap.add_argument("--list", action="store_true", help="list known benchmarks")
    ap.add_argument("--show", action="store_true",
                    help="print the full registry entry for <bench> (#532)")
    ap.add_argument("--score", action="store_true", help="invoke the scorer on an existing run dir")
    ap.add_argument("--solve", action="store_true",
                    help="Start the benchmark through the general flow. This is "
                         "the verb that closes the old scaffold-to-score gap: "
                         "there was no program that solved, and that hole is "
                         "where an agent hand-rolls a benchmark-only harness — "
                         "the thing RULE 0 forbids. Each problem is staged by "
                         "the thin IO adapter, then receives an input-only "
                         "AI route task. --resume validates all hash-bound "
                         "AI routes before running vibe_ic_one_shot_runner. "
                         "Every PROGRAM candidate is "
                         "hash-bound to a mandatory blind AI route + semantic "
                         "review before it can be scored. AI may issue an "
                         "evidence-backed OVERRIDE_PROGRAM and is the final "
                         "semantic authority. No benchmark-specific solver is "
                         "involved.")
    ap.add_argument("--resume", action="store_true",
                    help="Advance needs_ai_routing.jsonl before any runner, "
                         "then needs_ai_backup.jsonl, needs_ai_review.jsonl, "
                         "and needs_ai_repair.jsonl. AI-authored/modified RTL is "
                         "allowed only after a prompt-derived executable test "
                         "proves the frozen candidate wrong, then is re-gated "
                         "and must pass the same test plus fresh AI review; "
                         f"repeat until {_ACCEPTANCE_REPORT} is COMPLETE.")
    ap.add_argument("--review-correction", metavar="REQUEST.json",
                    help="with --resume: explicitly archive and advance one "
                         "unaccepted review on unchanged RTL; requires "
                         "hash-bound blind AI correction evidence; never "
                         "accepts, supersedes a challenge, or permits repair")
    ap.add_argument("--program-regate", metavar="REQUEST.json",
                    help="with --resume: the ONE Program re-entry operation. "
                         "Re-run the FIXED Program on one preserved, signed "
                         "pre-gate input in a staged project under the resume "
                         "coordinator lock. Requires BOTH Program identities "
                         "to have moved -- the declared version pair AND the "
                         "executable source tree -- plus the preserved input "
                         "and an unaccepted task. Binds the new output to the "
                         "SAME author signature, attributes the regenerated "
                         "bytes to the PROGRAM, preserves history, and never "
                         "accepts, publishes or permits repair: a fresh "
                         "independent review is still required.")
    ap.add_argument("--program-retry", metavar="REQUEST.json",
                    help="DEPRECATED alias of --program-regate (issue #2047 "
                         "merged the two Program re-entry operations into "
                         "one). Runs the merged operation and prints a "
                         "deprecation line; "
                         + _program_retry_removal_clause() + ".")
    ap.add_argument("--limit", type=int, default=0,
                    help="with --solve: stop after N problems (0 = all)")
    ap.add_argument("--shape", choices=["D"],
                    help="with --solve: select the general agentic JSONL I/O "
                         "protocol only; --resume retains this protocol. "
                         "Task nature still requires the shared named-AI handoff")
    ap.add_argument("--dataset", help="dataset path on disk")
    ap.add_argument("--run", help="run dir")
    ap.add_argument("--jobs", type=int, default=1,
                    help="with --solve/--resume: bounded project workers "
                         "(default 1 preserves serial behaviour)")
    ap.add_argument("--heavy-jobs", type=int, default=None,
                    help="with --solve/--resume: maximum concurrent runner "
                         "heavy slots (default: --jobs)")
    ap.add_argument("--worker-threads", type=int, default=0,
                    help="with --solve/--resume: EDA threads per worker; 0 "
                         "auto-budgets host CPUs (serial default is unchanged)")
    ap.add_argument("--scorer-root",
                    help="with CVDP --score: directory containing the official "
                         "run_benchmark.py (or set CVDP_BENCHMARK_ROOT)")
    ap.add_argument("--threads", type=int, default=4,
                    help="with CVDP --score: official scorer worker count "
                         "(default 4)")
    ap.add_argument("--allow-ungated", action="store_true",
                    help="OPT-IN: score even if some samples lack an emit-path attestation "
                         "(a disclosed exploratory direct-author run, NON-CANONICAL). Default "
                         "HARD-BLOCKs ungated samples so the published number reflects the runner.")
    ap.add_argument("--capture-golden", action="store_true",
                    help="after --score, record every HOST-VERIFIED PASS into "
                         "OUR OWN golden corpus (benchmark_golden_capture), "
                         "tagged with the plugin version + --ai-model")
    ap.add_argument("--ai-model", default=None,
                    help="the model that authored the samples; REQUIRED by "
                         "--capture-golden (never defaulted)")
    ap.add_argument("--golden-db", default=None,
                    help=f"sqlite for --capture-golden (default {_GOLDEN_DEFAULT_DB})")
    ap.add_argument("--allow-direct-agent", action="store_true",
                    help="OPT-IN: score even if the run lacks Vibe-IC runner entry evidence "
                         "(NON-CANONICAL). Default HARD-BLOCKs direct-agent authoring/patching.")
    a = ap.parse_args()
    if a.shape and not a.solve:
        ap.error("--shape selects I/O at --solve; --resume retains that selection")
    if a.review_correction and (not a.resume or a.solve or a.score or a.show or a.list):
        ap.error("--review-correction requires --resume alone")
    if a.program_regate and (not a.resume or a.solve or a.score or a.show or a.list):
        ap.error("--program-regate requires --resume alone")
    if a.program_regate and a.review_correction:
        ap.error("--program-regate and --review-correction are separate "
                 "operations; run one per resume")
    if a.program_retry and (not a.resume or a.solve or a.score or a.show or a.list or a.review_correction):
        ap.error("--program-retry requires --resume alone, without --review-correction")
    if a.program_retry and a.program_regate:
        ap.error("--program-retry is the DEPRECATED alias of --program-regate "
                 "(issue #2047 merged them into one operation); give one")

    if a.list:
        cmd_list()
        return
    if not a.bench:
        ap.print_help()
        sys.exit(2)
    # Resolve every operational spelling through the one alias table, even
    # when an old registry row still uses that spelling.  In particular,
    # ``cvdp`` is a historical Shape-D row while the alias table deliberately
    # routes current work to ``cvdp-open``.  ``--show`` keeps an exact registry
    # key so the historical row remains inspectable.
    _reg_keys = _strict_json_loads(REGISTRY.read_text())["benchmarks"]
    if a.bench and not (a.show and a.bench in _reg_keys):
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import benchmark_io_adapter as _bio          # noqa: PLC0415
            _resolved = _bio.resolve_name(a.bench)
        except ImportError:
            _resolved = None
        if _resolved and _resolved in _reg_keys:
            if _resolved != a.bench:
                print(f"[name] {a.bench!r} -> {_resolved!r}")
            a.bench = _resolved

    if a.show:
        reg = _strict_json_loads(REGISTRY.read_text())["benchmarks"]
        if a.bench not in reg:
            raise SystemExit(f"unknown benchmark: {a.bench} (see --list)")
        print(json.dumps({a.bench: reg[a.bench]}, ensure_ascii=False,
                         indent=2))
        return
    if a.score:
        if not a.run:
            raise SystemExit("--score requires --run")
        cmd_score(a.bench, a.run, a.dataset,
                  allow_ungated=a.allow_ungated,
                  allow_direct_agent=a.allow_direct_agent,
                  capture_golden=a.capture_golden,
                  ai_model=a.ai_model,
                  golden_db=a.golden_db,
                  scorer_root=a.scorer_root,
                  threads=a.threads)
        return
    if a.resume or a.solve:
        # Main thread, before any worker exists: see `_install_orphan_guard`.
        _install_orphan_guard()
    if a.resume:
        if not (a.dataset and a.run):
            raise SystemExit("--resume requires --dataset and --run")
        sys.exit(cmd_resume(
            a.bench, a.dataset, a.run, jobs=a.jobs,
            heavy_jobs=a.heavy_jobs, worker_threads=a.worker_threads,
            review_correction=a.review_correction,
            program_regate=a.program_regate,
            program_retry=a.program_retry))
    if a.solve:
        if not (a.dataset and a.run):
            raise SystemExit("--solve requires --dataset and --run")
        sys.exit(cmd_solve(
            a.bench, a.dataset, a.run, limit=a.limit, jobs=a.jobs,
            heavy_jobs=a.heavy_jobs, worker_threads=a.worker_threads,
            shape=a.shape))
    # default: show plan + env status
    env = _env_check()
    print(f"# Environment: iverilog={'OK' if env['iverilog'] else 'MISSING'}, "
          f"vibeic-eda container={'RUNNING' if env['iic_eda_running'] else 'NOT RUNNING'}")
    # The per-SHAPE requirement check, from `benchmark_setup.needs()`. Printed
    # before the plan because a plan whose step 3 cannot run is worse than no
    # plan: the reader follows it and finds out inside the runner.
    try:
        _entry_for_env = _entry(a.bench)
    except SystemExit:
        _entry_for_env = None
    if _entry_for_env is not None:
        needed, missing = _requirement_report(_entry_for_env, env)
        print(f"# Requirements for shape {_entry_for_env.get('shape','?')}: "
              + ", ".join(f"{k}={'OK' if env.get(k) else 'MISSING'}" for k in needed))
        if missing:
            print(f"# MISSING: {', '.join(missing)} — this host cannot run "
                  f"{a.bench} as scoped. Detail + install pointers:")
            print(f"#   python3 {Path(__file__).resolve().parent / 'benchmark_setup.py'} {a.bench}")
    print()
    cmd_show(a.bench)


if __name__ == "__main__":
    main()
