#!/usr/bin/env python3
"""Run the cheap BASE-owned push gates before any expensive verifier arm.

`gatekeeper-verify-merge.sh` calls this first, over the actual push population,
so a forbidden collateral revert, an NDA leak or a prohibited git command in a
commit message is refused before hours of arms run.  The gate programs are
materialised from the exact BASE commit, never imported from the candidate
checkout, so a candidate cannot answer for itself by editing the checker.

This was the `push-preflight` subcommand of the protected-path transition
validator.  It never read that validator's byte register, and when the owner
removed the register and its two-step landing (PREPARE, then ACTIVATE) on
2026-09-27 this check moved here unchanged in what it runs and how
it decides: gate rc=1 is a measured REFUSE (exit 1), anything else non-zero is
NORECORD (exit 2).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

# `_progress_run` lives in the plugin's `programs/`, which is not a sibling of
# this file. Walk UP until the directory that actually holds it is found.
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "_vibeic_push_preflight_primitives",
    Path(__file__).resolve().with_name("landing_record_primitives.py"),
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("landing record primitives are unavailable")
primitives = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = primitives
_SPEC.loader.exec_module(primitives)
Refusal = primitives.Refusal

SCHEMA = 1
KIND = "vibeic.landing-push-preflight-receipt"
PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"
GATES = (
    "landing_collateral_revert_check.py",
    "commit_msg_nda_check.py",
    "nda_diff_scan_check.py",
    "git_prohibition_guard.py",
)
NDA_GUARDS = frozenset({"commit_msg_nda_check.py", "nda_diff_scan_check.py"})
BASE_FILES = GATES + ("_commercial_pdk.py",)


def _gate_record(name: str, proc: subprocess.CompletedProcess) -> dict[str, Any]:
    stdout = proc.stdout if isinstance(proc.stdout, bytes) else b""
    stderr = proc.stderr if isinstance(proc.stderr, bytes) else b""
    visible = stderr if proc.returncode else stdout
    lines = [line.strip() for line in
             visible.decode("utf-8", errors="replace").splitlines()
             if line.strip()]
    # The two NDA guards can be handed private detector literals on the host.
    # Their streams may be useful for local diagnosis, but a broken formatter
    # must not copy private text into a durable/public preflight receipt.
    if name in NDA_GUARDS:
        summary = ("NDA guard PASS" if proc.returncode == 0 else
                   "NDA guard REFUSE" if proc.returncode == 1 else
                   "NDA guard NORECORD")
    else:
        summary = (lines[-1] if lines else "NO OUTPUT")[:1000]
    stdout_sha256 = ("0" * 64 if name in NDA_GUARDS
                     else hashlib.sha256(stdout).hexdigest())
    stderr_sha256 = ("0" * 64 if name in NDA_GUARDS
                     else hashlib.sha256(stderr).hexdigest())
    return {
        "name": name,
        "rc": proc.returncode,
        "stdout_sha256": stdout_sha256,
        "stderr_sha256": stderr_sha256,
        "summary": summary,
    }


def build_receipt(*, object_repo: Path, base: str, candidate: str,
                  push_range: str) -> dict[str, Any]:
    """BLOCKING.  Every gate runs from BASE bytes over `push_range`."""
    git = primitives._git
    repo = object_repo.resolve(strict=True)
    _algorithm, oid_len = primitives._object_format(repo)
    base_commit, base_tree = primitives._commit_and_tree(
        repo, base, oid_len, "base")
    candidate_commit, candidate_tree = primitives._commit_and_tree(
        repo, candidate, oid_len, "candidate")
    if (not isinstance(push_range, str) or not push_range.strip()
            or "\n" in push_range or "\r" in push_range
            or len(push_range) > 4096):
        raise Refusal("push range is empty or not a safe one-line rev-list expression")
    parts = push_range.split()
    selected_raw = git(repo, ["rev-list", *parts])
    assert isinstance(selected_raw, str)
    selected = selected_raw.split()
    if not selected or candidate_commit not in selected:
        raise Refusal("push range is empty or does not include the candidate")

    gate_records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="landing-push-preflight.") as temp:
        authority = Path(temp)
        for name in BASE_FILES:
            raw = git(repo, ["show", f"{base_commit}:{PROGRAMS_REL}/{name}"],
                      binary=True)
            assert isinstance(raw, bytes)
            path = authority / name
            path.write_bytes(raw)
            path.chmod(0o500)
        env = primitives._git_env()
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(authority)})

        commands: list[tuple[str, list[str]]] = [
            ("landing_collateral_revert_check.py",
             ["--repo", str(repo), "--rev-range", push_range]),
            ("commit_msg_nda_check.py",
             ["--repo", str(repo), "--rev-range", push_range]),
            ("nda_diff_scan_check.py",
             ["--repo", str(repo), "--rev-range", push_range]),
        ]
        for name, argv in commands:
            proc = _pr.run(
                [sys.executable, "-B", str(authority / name), *argv],
                env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
            gate_records.append(_gate_record(name, proc))

        messages = git(repo, ["log", "--format=%B", *parts], binary=True)
        assert isinstance(messages, bytes)
        message_file = authority / "commit-messages.txt"
        message_file.write_bytes(messages)
        proc = _pr.run(
            [sys.executable, "-B", str(authority / "git_prohibition_guard.py"),
             str(message_file)],
            env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
        gate_records.append(_gate_record("git_prohibition_guard.py", proc))

    if any(row["rc"] not in {0, 1} for row in gate_records):
        verdict = "NORECORD"
    elif any(row["rc"] == 1 for row in gate_records):
        verdict = "REFUSE"
    else:
        verdict = "PASS"
    payload = {
        "base_commit": base_commit,
        "base_tree": base_tree,
        "candidate_commit": candidate_commit,
        "candidate_tree": candidate_tree,
        "push_range": push_range,
        "gates": gate_records,
    }
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "complete": verdict != "NORECORD",
        "verdict": verdict,
        "payload": payload,
        "payload_sha256": hashlib.sha256(
            primitives.canonical_bytes(payload)).hexdigest(),
    }


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short receipt write")
            view = view[written:]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            temp.unlink()
        except OSError:
            pass
        raise
    else:
        os.close(fd)
        os.replace(temp, path)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--object-repo", type=Path, required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--push-range", required=True)
    ap.add_argument("--receipt", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        receipt = build_receipt(
            object_repo=args.object_repo, base=args.base,
            candidate=args.candidate, push_range=args.push_range)
        _atomic_write(args.receipt, primitives.canonical_bytes(receipt))
    except (OSError, Refusal, subprocess.SubprocessError) as exc:
        print(f"[NORECORD] landing push preflight: {exc}", file=sys.stderr)
        return 2
    for gate in receipt["payload"]["gates"]:
        word = ("PASS" if gate["rc"] == 0 else
                "FAIL" if gate["rc"] == 1 else "NORECORD")
        stream = sys.stdout if gate["rc"] == 0 else sys.stderr
        print(f"[{word}] {gate['name']}: {gate['summary']}", file=stream)
    verdict = receipt["verdict"]
    stream = sys.stdout if verdict == "PASS" else sys.stderr
    print(f"PUSH PREFLIGHT: {verdict} — {receipt['payload_sha256'][:12]}",
          file=stream)
    return 0 if verdict == "PASS" else 1 if verdict == "REFUSE" else 2


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    raise SystemExit(_pr.exit_undetermined_on_stall(main))
