#!/usr/bin/env python3
"""Run one trusted operational command under the owned-process protocol.

The command has no total elapsed-time cutoff.  Output growth may renew only the
operational stall lease; natural exit, the exact child return code and a final
zero PID/starttime census remain the terminal evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def _programs(repo: Path) -> Path:
    return (repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" /
            "programs")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, required=True,
                    help="trusted repository providing the ownership protocol")
    ap.add_argument("--cwd", type=Path, required=True)
    ap.add_argument("--stall-grace", type=float, default=300.0,
                    help="operational output-starvation lease; not a total limit")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command.pop(0)
    if not command or args.stall_grace <= 0:
        ap.error("a command and positive --stall-grace are required")

    repo = args.repo.resolve()
    programs = _programs(repo)
    if not programs.is_dir():
        print("[NORECORD] trusted owned-process programs are absent",
              file=sys.stderr)
        return 2
    supervisor = programs / "_owned_process_supervisor.py"
    if not supervisor.is_file():
        print("[NORECORD] trusted owned-process supervisor is absent",
              file=sys.stderr)
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="owned-command-"))
    result = scratch / "result.json"
    status = scratch / "status.json"
    proc: subprocess.Popen[bytes] | None = None
    pending_signal: list[int] = []

    def relay(signum: int, _frame: object) -> None:
        # The supervisor is the subreaper that owns the command's complete
        # descendant tree.  Let its synchronous signal handler finish the zero
        # census; killing this thin wrapper first would orphan that cleanup.
        if not pending_signal:
            pending_signal.append(signum)
        if proc is not None and proc.poll() is None:
            proc.send_signal(signum)

    old_term = signal.signal(signal.SIGTERM, relay)
    old_int = signal.signal(signal.SIGINT, relay)
    try:
        proc = subprocess.Popen([
            sys.executable, str(supervisor),
            "--result", str(result),
            "--status", str(status),
            "--cwd", str(args.cwd.resolve()),
            "--stall-grace", str(args.stall_grace),
            "--poll", "1",
            "--", *command,
        ], env=dict(os.environ))
        if pending_signal:
            proc.send_signal(pending_signal[0])
        helper_rc = proc.wait()
        if pending_signal:
            return 128 + pending_signal[0]
        if helper_rc != 0 or not result.is_file():
            print("[NORECORD] owned supervisor did not publish a terminal "
                  f"record (rc={helper_rc})", file=sys.stderr)
            return 2
        try:
            record = json.loads(
                result.read_text(encoding="utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON constant {value}")),
                object_pairs_hook=lambda pairs: _strict_object(pairs),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            print(f"[NORECORD] invalid owned terminal record: {exc}",
                  file=sys.stderr)
            return 2
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
        shutil.rmtree(scratch, ignore_errors=True)

    required = {
        "protocol", "rc", "body", "problem", "outcome", "launched",
        "census_ok", "final_descendants", "observed", "capability_error",
    }
    if (not isinstance(record, dict) or set(record) != required
            or record.get("protocol") != 1
            or type(record.get("rc")) is not int
            or not isinstance(record.get("body"), str)
            or (record.get("problem") is not None
                and not isinstance(record.get("problem"), str))
            or not isinstance(record.get("outcome"), str)
            or type(record.get("launched")) is not bool
            or type(record.get("census_ok")) is not bool
            or not _valid_identity_rows(record.get("observed"))
            or not isinstance(record.get("capability_error"), str)
            or record.get("final_descendants") != []):
        print("[NORECORD] malformed owned terminal schema", file=sys.stderr)
        return 2
    body = record["body"]
    problem = record["problem"]
    rc = record["rc"]
    if body:
        sys.stdout.write(body)
        if not body.endswith("\n"):
            sys.stdout.write("\n")
    terminal_problems = []
    if problem:
        terminal_problems.append(problem)
    if record["outcome"] != "natural":
        terminal_problems.append(f"non-natural outcome {record['outcome']!r}")
    if record["launched"] is not True:
        terminal_problems.append("command was not launched")
    if record["census_ok"] is not True:
        terminal_problems.append("owned PID/starttime census is incomplete")
    if record["capability_error"]:
        terminal_problems.append(record["capability_error"])
    if terminal_problems:
        print(f"[NORECORD] {'; '.join(terminal_problems)}", file=sys.stderr)
        return 2
    return rc


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _valid_identity_rows(value: object) -> bool:
    return (isinstance(value, list)
            and all(isinstance(row, dict)
                    and set(row) == {"pid", "starttime"}
                    and type(row["pid"]) is int and row["pid"] > 0
                    and type(row["starttime"]) is int
                    and row["starttime"] >= 0
                    for row in value))


if __name__ == "__main__":
    raise SystemExit(main())
