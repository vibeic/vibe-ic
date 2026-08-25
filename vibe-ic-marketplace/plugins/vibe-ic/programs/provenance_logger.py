#!/usr/bin/env python3
"""
provenance_logger.py — Wrap a tool invocation, record hashed provenance.

Root-cause fix for the "agent writes file, gate passes" failure class:
gates must be able to ask "was this file produced by a real tool run?",
not just "does this filename exist?".

How it works:
  1. Before running the tool, SHA-256 every declared input.
  2. Run the tool (any command; subprocess inherits env).
  3. After exit, SHA-256 every declared output.
  4. Append a JSONL record to <project>/provenance.jsonl:
       {
         "timestamp":  "2026-04-22T14:23:01Z",
         "tool":       "openroad",
         "version":    "2.0-17000-gabc123  (OpenROAD)",
         "cwd":        "/work",
         "argv":       ["openroad", "-no_init", "pnr.tcl"],
         "inputs":     {"path/to/input.v": "sha256:..."},
         "outputs":    {"phase3/stage3/pnr/routed.def": "sha256:..."},
         "exit_code":  0,
         "duration_s": 183.4,
         "stdout_sha": "sha256:...",
         "stderr_sha": "sha256:...",
         "stdout_tail": "last 400 chars",
         "stderr_tail": "last 400 chars"
       }

The JSONL is append-only from the logger's perspective — downstream gates
verify: (a) every required output has a matching entry, (b) the file on
disk still hashes to the value in the log, and (c) the tool name is in
an allow-list for that step.

A cheating agent CAN write a fake entry — but they'd have to:
  (i)  write a .jsonl entry AND
  (ii) make the file on disk hash to the value in the entry
That's no easier than writing a real tool output, so this raises the
floor from "echo text to file" to "hash collision required".

Usage
-----
Forward a tool:
    provenance_logger.py \
        --project /path/to/project \
        --tool openroad \
        --version-cmd "openroad -version" \
        --input   rtl/a3616_top.v \
        --input   constraints/a3616_top.sdc \
        --output  pnr/routed.def \
        --output  pnr/drc.rpt \
        -- openroad -no_init pnr.tcl

Tool stdout/stderr are streamed through to the caller's stdout/stderr
so that interactive/CI output is preserved, AND captured for the log.

Exit codes (of THIS wrapper):
    0   tool exited 0 and provenance record written
    1   tool exited non-zero (record still written — failures are logged)
    2   wrapper error (missing output, hash failed, JSON error)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artefact_digest_ledger as _ledger  # noqa: E402


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except OSError as exc:
        return f"error:{exc}"


def _sha256_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _utcnow_iso() -> str:
    # datetime.utcnow() is deprecated in Python 3.12+; use timezone-aware UTC.
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _capture_version(version_cmd: str) -> str:
    """Run a tool-version probe (e.g. ``yosys --version``) and return its first
    line.

    SECURITY: ``version_cmd`` is run through a shell (``shell=True``) by design
    so callers can pass a pipeline (``tool --version | head -1``). It is a
    tool-version command supplied by the caller's own configuration, NOT by
    untrusted input. Treat it as TRUSTED INPUT ONLY.
    """
    if not version_cmd:
        return ""
    try:
        r = subprocess.run(
            version_cmd, shell=True, capture_output=True, text=True, timeout=30,  # nosec B602 — trusted version probe
        )
        lines = (r.stdout or r.stderr or "").strip().splitlines()
        # #365 — the EDA container's entrypoint prints its own diagnostic
        # banners BEFORE the command's output ("[INFO] Final PATH variable:
        # ..."), so taking line 0 recorded the PATH banner as the tool
        # VERSION in every provenance entry written through a container.
        # Skip bracketed-level banner lines; they are the harness talking,
        # never the tool's version. Tool-AGNOSTIC: keyed on the banner
        # GRAMMAR, not on any tool or container name. If nothing else
        # remains, fall back to line 0 rather than returning empty — an
        # unexpected banner-only output should still be recorded verbatim
        # for a reader to see.
        real = [ln for ln in lines
                if not re.match(r"\s*\[[A-Z][A-Z ]*\]", ln) and ln.strip()]
        picked = (real or lines or [""])[0]
        return picked[:200]
    except Exception as exc:
        return f"version-capture-error: {exc!r}"[:200]


def run(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--project", required=True,
                   help="Project directory (provenance.jsonl written here)")
    p.add_argument("--tool", required=True,
                   help="Canonical tool name (openroad, yosys, klayout, ...)")
    p.add_argument("--version-cmd", default="",
                   help="Shell command to print tool version (optional)")
    p.add_argument("--input", action="append", default=[],
                   help="Declared input file path; may repeat")
    p.add_argument("--output", action="append", default=[],
                   help="Declared output file path; may repeat")
    p.add_argument("--step", default="",
                   help="Optional flow-step id (e.g. 'step-19-routing')")
    p.add_argument("--note", default="",
                   help="Optional free-form note recorded in the log")
    p.add_argument("--anchor-dir", default="",
                   help="Directory holding the artefact-digest chain anchor "
                        "(default: the project's PARENT). This is the trust "
                        "boundary of vibe-ic#1116: a directory the producing "
                        "step cannot write. Pointing it inside the project is "
                        "allowed and is reported, never silently accepted.")
    p.add_argument("cmd", nargs=argparse.REMAINDER,
                   help="-- tool-cmd arg1 arg2 ... (the command to run)")
    args = p.parse_args(argv)

    if not args.cmd or args.cmd[0] != "--":
        print("provenance_logger: must separate tool command with `--`",
              file=sys.stderr)
        return 2
    cmd = args.cmd[1:]
    if not cmd:
        print("provenance_logger: no command given after `--`", file=sys.stderr)
        return 2

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"provenance_logger: project not a dir: {project}",
              file=sys.stderr)
        return 2

    # Pre-run hashes
    inputs: Dict[str, str] = {}
    for rel in args.input:
        abs_p = (project / rel).resolve() if not Path(rel).is_absolute() \
            else Path(rel).resolve()
        inputs[rel] = _sha256_file(abs_p) if abs_p.exists() else "missing"

    version = _capture_version(args.version_cmd)

    # Run the tool, stream + capture
    t0 = time.time()
    stdout_buf = io.BytesIO()
    stderr_buf = io.BytesIO()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(project),
        )
    except FileNotFoundError:
        print(f"provenance_logger: command not found: {cmd[0]}",
              file=sys.stderr)
        return 127

    # Naive dual read — works for most tools; for extremely chatty tools
    # with select/poll we'd want a proper fan-out but this keeps deps to
    # stdlib only.
    import threading

    def _tee(src, dst_buf, dst_stream):
        for line in iter(lambda: src.readline(), b""):
            dst_buf.write(line)
            try:
                dst_stream.buffer.write(line)
                dst_stream.flush()
            except (BrokenPipeError, AttributeError):
                pass

    th_out = threading.Thread(target=_tee, args=(proc.stdout, stdout_buf, sys.stdout))
    th_err = threading.Thread(target=_tee, args=(proc.stderr, stderr_buf, sys.stderr))
    th_out.start()
    th_err.start()
    proc.wait()
    th_out.join()
    th_err.join()
    duration = time.time() - t0
    exit_code = proc.returncode

    stdout_bytes = stdout_buf.getvalue()
    stderr_bytes = stderr_buf.getvalue()

    # Post-run output hashes
    outputs: Dict[str, str] = {}
    for rel in args.output:
        abs_p = (project / rel).resolve() if not Path(rel).is_absolute() \
            else Path(rel).resolve()
        outputs[rel] = _sha256_file(abs_p) if abs_p.exists() else "missing"

    record = {
        "timestamp": _utcnow_iso(),
        "tool": args.tool,
        "version": version,
        "cwd": str(project),
        "argv": cmd,
        "inputs": inputs,
        "outputs": outputs,
        "exit_code": exit_code,
        "duration_s": round(duration, 3),
        "stdout_sha": _sha256_bytes(stdout_bytes),
        "stderr_sha": _sha256_bytes(stderr_bytes),
        "stdout_tail": stdout_bytes.decode("utf-8", errors="replace")[-400:],
        "stderr_tail": stderr_bytes.decode("utf-8", errors="replace")[-400:],
    }
    if args.step:
        record["step"] = args.step
    if args.note:
        record["note"] = args.note

    log_path = project / "provenance.jsonl"
    try:
        with log_path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"provenance_logger: cannot write {log_path}: {exc}",
              file=sys.stderr)
        return 2

    # ── THE HASH-CHAINED HALF (vibe-ic#1116) ────────────────────────────────
    # Everything above is a record the PRODUCING STEP WRITES, inside the run
    # directory the producing step writes. Measured against our own machinery:
    #
    #     honest artefact                  -> audit PASS
    #     edit the ARTEFACT only           -> audit FAIL   (caught)
    #     edit the artefact AND the record -> audit PASS   (NOT caught)
    #
    # The docstring above argues the second case needs a hash collision. It
    # does not: an adversary who writes the artefact FIRST and then records its
    # hash controls both sides, and both sides are in `project/`.
    #
    # `artefact_digest_ledger` is the repair, and until now nothing called it.
    # Each declared output that EXISTS extends a chain whose head is a function
    # of every entry ever appended, and the head is re-anchored in a single
    # small file that DEFAULTS OUTSIDE the run directory (`project.parent`).
    # The anchor is the trust boundary and it is stated rather than hidden: put
    # it inside the run dir and `artefact_digest_ledger verify` says so out loud
    # instead of reporting a guarantee it has not earned.
    #
    # It runs on the outputs that were PRODUCED, so `--anchor-dir` never turns a
    # missing declared output into a ledger failure — that is the `missing`
    # check below, unchanged, and it still owns that verdict. An OSError here is
    # treated exactly like one writing provenance.jsonl above (rc 2), because a
    # record the wrapper could not write is not a record.
    produced = [rel for rel, dig in outputs.items() if dig != "missing"]
    if produced:
        anchor_dir = Path(args.anchor_dir).resolve() if args.anchor_dir \
            else project.parent
        anchor = anchor_dir / _ledger.ANCHOR_NAME
        try:
            res = _ledger.append(project, anchor, args.step or args.tool, produced)
        except OSError as exc:
            print(f"provenance_logger: cannot extend the artefact digest "
                  f"ledger at {project / _ledger.LEDGER_NAME}: {exc}",
                  file=sys.stderr)
            return 2
        if anchor_dir == project or project in anchor_dir.parents:
            print(f"provenance_logger: NOTE — the digest anchor {anchor} is "
                  f"INSIDE the run directory this step writes, so the chain "
                  f"degrades to the pre-#1116 guarantee (a producer that "
                  f"rewrites both is undetectable). Pass --anchor-dir outside "
                  f"the project to restore it.", file=sys.stderr)
        print(f"provenance_logger: digest ledger +{res['added']} entr"
              f"{'y' if res['added'] == 1 else 'ies'}, chain head "
              f"{res['head'][:16]}... anchored at {anchor}", file=sys.stderr)

    # If any declared output is missing, the wrapper fails with 2 regardless of
    # the tool's own exit code — the step didn't produce what it promised.
    missing = [k for k, v in outputs.items() if v == "missing"]
    if missing:
        print(f"\nprovenance_logger: WARNING — declared outputs missing: {missing}",
              file=sys.stderr)
        if exit_code == 0:
            return 2

    return exit_code


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
