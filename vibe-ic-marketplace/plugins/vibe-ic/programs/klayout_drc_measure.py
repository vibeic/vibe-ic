#!/usr/bin/env python3
"""Produce one digest-bound KLayout DRC invocation receipt with ``docker run``.

This is intentionally a small measurement producer, not a DRC checker.  The
KLayout RDB remains the source of the violation count; this program records
which exact GDS and deck invocation made that RDB, including the raw terminal
transcript.  It never writes a derived "zero violations" sentence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
import _docker_memory as _dmem  # noqa: E402 — every `docker run` carries the ceiling
import sys
from pathlib import Path

# This module is also loaded by path by repository hygiene.  Unlike execution
# as ``__main__``, that loader does not add ``programs/`` to ``sys.path``.
_PROGRAMS_DIR = str(Path(__file__).resolve().parent)
if _PROGRAMS_DIR not in sys.path:
    sys.path.insert(0, _PROGRAMS_DIR)

from _atomic_artefact import write_text


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _inside(project: Path, value: str, *, label: str) -> tuple[Path, str]:
    """Return an existing-or-output project-relative path, refusing escapes."""
    raw = Path(value)
    path = (project / raw).resolve() if not raw.is_absolute() else raw.resolve()
    try:
        rel = path.relative_to(project.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must remain under project: {value}") from exc
    return path, rel


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
        f.flush()


def measure(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    if not project.is_dir():
        raise ValueError(f"project is not a directory: {project}")
    gds, gds_rel = _inside(project, args.gds, label="GDS")
    report, report_rel = _inside(project, args.report, label="report")
    if not gds.is_file():
        raise ValueError(f"GDS does not exist: {gds}")
    if not args.deck.startswith("/"):
        raise ValueError("--deck must be an absolute path inside the pinned image")
    before = _sha(gds)
    assert before is not None
    transcript = report.with_suffix(".log")
    _, transcript_rel = _inside(project, str(transcript), label="transcript")
    report.parent.mkdir(parents=True, exist_ok=True)

    cgds = "/project/" + gds_rel
    creport = "/project/" + report_rel
    # The ceiling comes from `_docker_memory` so this call site cannot drift from
    # the shell and the other `docker run` callers; `--memory` stays as an
    # explicit operator override for a deck that genuinely needs more. It is
    # spliced in right after the run verb, where `test_no_docker_run_escapes_
    # the_ceiling` looks for it — that guard reads a 400-character window, so a
    # comment placed between the verb and the flags puts them out of its reach.
    _mem = (["--memory", args.memory, "--memory-swap", args.memory]
            if args.memory else None)
    command = [
        "docker", "run", "--rm",
        *(_mem if _mem is not None else _dmem.docker_memory_flags()),
        "--init", "--network", "none",
        "--cpus", str(args.cpus),
        "-v", f"{project}:/project", "-w", "/project", args.image,
        "--skip", "klayout", "-b", "-r", args.deck,
        "-rd", f"input={cgds}", "-rd", f"report={creport}",
        "-rd", f"in_gds={cgds}", "-rd", f"report_file={creport}",
        "-rd", f"top_cell={args.top}",
    ]
    try:
        cp = subprocess.run(command, capture_output=True, text=True, check=False)
        rc = cp.returncode
        write_text(transcript, cp.stdout + cp.stderr, encoding="utf-8")
    except OSError as exc:
        rc = 127
        write_text(transcript, f"MEASUREMENT_LAUNCH_ERROR: {exc}\n", encoding="utf-8")

    outputs = {}
    for path, rel in ((report, report_rel), (transcript, transcript_rel)):
        digest = _sha(path)
        if digest is not None:
            outputs[rel] = digest
    record = {
        "record": "invocation",
        "measured": True,
        "tool": "klayout",
        "exit_code": rc,
        "inputs": {gds_rel: before},
        "outputs": outputs,
        "command": command,
        "deck": args.deck,
        "top_cell": args.top,
    }
    _append(project / "provenance.jsonl", record)
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project")
    p.add_argument("--gds", required=True, help="project-relative GDS input")
    p.add_argument("--report", required=True, help="project-relative RDB output")
    p.add_argument("--deck", required=True, help="absolute deck path inside image")
    p.add_argument("--top", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--cpus", type=int, default=2)
    p.add_argument("--memory", default=None,
                   help="explicit container ceiling; default is the shared "
                        "one from _docker_memory (VIBEIC_DOCKER_MEMORY / "
                        "VIBEIC_DOCKER_MEMORY_FRACTION)")
    args = p.parse_args(argv)
    try:
        return measure(args)
    except (OSError, ValueError) as exc:
        print(f"klayout_drc_measure: REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
