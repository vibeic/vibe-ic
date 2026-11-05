from __future__ import annotations


import argparse


import hashlib


import json


import re


import sys


from pathlib import Path


from typing import Callable, Dict, List, Optional, Sequence


RC_REFUSE = 1


def service_ready(repo: Path, manifest: Path, writer: str,
                  final_command: Sequence[str], base: str = "origin/main") -> dict:
    """Consume root-owned admission input; serialize only the final write.

    Receipt pins and check argv come from the maintainer's manifest, NEVER PR
    metadata. A receipt's self-checksum is integrity, not independent authority.
    This one-shot service neither polls nor assigns a version by itself.
    """
    import fcntl
    import os
    import subprocess

    def strict(raw):
        def pairs(rows):
            result = {}
            for key, value in rows:
                if key in result:
                    raise ValueError("duplicate JSON key: " + key)
                result[key] = value
            return result
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args],
                                       stderr=subprocess.PIPE).decode().strip()

    raw = manifest.read_bytes()
    plan = strict(raw)
    if (not writer or plan.get("writer") != writer or not final_command
            or not isinstance(plan.get("candidates"), list)):
        raise ValueError("missing admission input or wrong sole writer")
    refused = []
    verifier = repo / "tools/gatekeeper-verify-merge.sh"

    def inspect(entry):
        if any(entry.get(k) for k in ("holds", "shared_conflicts", "failed_gates")):
            raise ValueError("explicit hold, shared-source conflict or failed gate")
        now_base = git("rev-parse", base + "^{commit}")
        for dep in entry.get("dependencies", []):
            if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                               dep, now_base], capture_output=True).returncode:
                raise ValueError("unlanded dependency: " + dep)
        path = Path(entry["receipt"])
        receipt_bytes = path.read_bytes()
        if hashlib.sha256(receipt_bytes).hexdigest() != entry["receipt_sha256"]:
            raise ValueError("receipt differs from independently accepted pin")
        receipt = strict(receipt_bytes)
        head = git("rev-parse", entry["head"] + "^{commit}")
        checked = subprocess.run(
            ["bash", str(verifier), "--repo", str(repo), "--base", base,
             "--reassert", str(path), "--reassert-head", head, "--no-fetch"],
            capture_output=True, text=True, timeout=60)
        if checked.returncode and "REASSERT: REVALIDATE" not in checked.stderr:
            raise ValueError("receipt refused: " + checked.stdout + checked.stderr)
        affected = {line.strip().split("\t")[0] for line in checked.stderr.splitlines()
                    if line.startswith("    ")} if checked.returncode else set()
        checks = entry.get("checks", {})
        if not isinstance(checks, dict):
            raise ValueError("invalid named check mapping")
        # Additional consumed dependencies are explicitly named by the accepted
        # admission input. Git paths, not waiting time or PR identity, invalidate.
        changed = set(git("diff", "--name-only", receipt["base_sha"], now_base).splitlines())
        affected |= changed & set(checks)
        watch = set(checks) | affected
        bindings = {p: git("ls-tree", now_base, "--", p) for p in watch}
        return head, affected, bindings

    # Admit the complete queue before running any acceptance work. Stable
    # partitioning preserves input order only within the same readiness class.
    admitted = []
    for entry in plan["candidates"]:
        if not isinstance(entry, dict):
            raise ValueError("candidate admission is not an object")
        try:
            admitted.append((entry, *inspect(entry)))
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
            refused.append({"id": entry.get("id"), "reason": str(exc)})
    for entry, head, affected, bindings in sorted(admitted, key=lambda row: bool(row[2])):
        try:
            performed = []
            commands = {}
            for path in sorted(affected):
                rows = entry.get("checks", {}).get(path)
                if not rows:
                    raise ValueError("no impacted check for changed input: " + path)
                for check in rows:
                    args = check["argv"]
                    if not args or not all(isinstance(x, str) for x in args):
                        raise ValueError("invalid impacted argv")
                    key = check["id"]
                    if key in commands and commands[key] != args:
                        raise ValueError("ambiguous impacted check: " + key)
                    commands[key] = args
            for key, args in commands.items():
                run = subprocess.run(args, cwd=repo, capture_output=True, text=True, timeout=300)
                if run.returncode:
                    raise ValueError("impacted check failed: " + key + ": " + run.stderr)
                performed.append(key)
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
            refused.append({"id": entry.get("id"), "reason": str(exc)})
            continue  # An unrelated earlier refusal is never a FIFO barrier.

        common = Path(git("rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = repo / common
        with (common / "gatekeeper-final.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"status": "BLOCKED_SOLE_WRITER_LOCK", "refused": refused}
            # No test or acceptance arm runs while holding the short main lock.
            # Re-read input identities; unrelated main movement is not a lock.
            try:
                if manifest.read_bytes() != raw:
                    raise ValueError("admission manifest changed during checks")
                current_head, current_affected, current_bindings = inspect(entry)
                if (current_head != head or current_affected != affected
                        or current_bindings != bindings):
                    raise ValueError("named inputs changed during impacted checks")
            except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
                return {"status": "BLOCKED_CHANGED_INPUT", "reason": str(exc), "refused": refused}
            env = dict(os.environ, GATEKEEPER_READY_ID=str(entry["id"]),
                       GATEKEEPER_READY_HEAD=head,
                       GATEKEEPER_READY_BASE=git("rev-parse", base + "^{commit}"))
            done = subprocess.run(list(final_command), cwd=repo, env=env,
                                  capture_output=True, text=True, timeout=300)
            # Never advance to another candidate after a possibly partial write.
            return {"status": "DELIVERED" if done.returncode == 0 else "BLOCKED_FINAL_WRITE",
                    "id": entry["id"], "head": head, "receipt_reused": not affected,
                    "affected_paths": sorted(affected), "impacted_checks": performed,
                    "final_rc": done.returncode, "stdout": done.stdout,
                    "stderr": done.stderr, "refused": refused}
    return {"status": "BLOCKED_NO_ACCEPTED_CANDIDATE", "refused": refused}


def publish_service_manifest(manifest: Path, receipt_root: Path, writer: str,
                             candidates_json: str) -> dict:
    """Atomically publish root-owned accepted candidates for service_ready."""
    import os
    import tempfile

    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError("duplicate JSON key: " + key)
            value[key] = item
        return value

    candidates = json.loads(
        candidates_json, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    root = receipt_root.resolve()
    if (not writer or not isinstance(candidates, list)
            or manifest.resolve().parent != root):
        raise ValueError("invalid root-owned service manifest destination")
    for entry in candidates:
        if not isinstance(entry, dict):
            raise ValueError("candidate admission is not an object")
        receipt = Path(entry["receipt"]).resolve()
        try:
            receipt.relative_to(root)
        except ValueError as exc:
            raise ValueError("receipt escapes root-owned receipt directory") from exc
        pin = entry["receipt_sha256"]
        if (not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{64}", pin)
                or hashlib.sha256(receipt.read_bytes()).hexdigest() != pin):
            raise ValueError("receipt differs from independently accepted pin")
    body = json.dumps({"writer": writer, "receipt_root": str(root),
                       "candidates": candidates}, sort_keys=True,
                      separators=(",", ":")).encode() + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".root-admission.", dir=root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, manifest)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"manifest_sha256": hashlib.sha256(body).hexdigest(),
            "candidate_count": len(candidates)}


def service_final_write(repo: Path, base: str = "origin/main") -> dict:
    """Perform the existing squash merge for the candidate selected by service_ready.

    This is the sole-writer command run under ``gatekeeper-final.lock``.  It
    refuses unless the selected id, head and base exported by ``service_ready``
    still name the same open, non-draft PR.  It never discovers a candidate or
    accepts evidence; it only binds the already-admitted candidate to the
    existing ``gh pr merge`` writer.
    """
    import os
    import subprocess

    ready_id = os.environ.get("GATEKEEPER_READY_ID", "")
    ready_head = os.environ.get("GATEKEEPER_READY_HEAD", "")
    ready_base = os.environ.get("GATEKEEPER_READY_BASE", "")
    if not re.fullmatch(r"[1-9][0-9]*", ready_id):
        raise ValueError("missing or malformed GATEKEEPER_READY_ID")
    if not re.fullmatch(r"[0-9a-f]{40}", ready_head):
        raise ValueError("missing or malformed GATEKEEPER_READY_HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", ready_base):
        raise ValueError("missing or malformed GATEKEEPER_READY_BASE")
    if base != "origin/main":
        raise ValueError("the canonical final writer requires base origin/main")

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], stderr=subprocess.PIPE,
            text=True).strip()

    if git("rev-parse", base + "^{commit}") != ready_base:
        raise ValueError("GATEKEEPER_READY_BASE no longer names origin/main")
    if git("rev-parse", ready_head + "^{commit}") != ready_head:
        raise ValueError("GATEKEEPER_READY_HEAD is not the selected commit")

    def view():
        viewed = subprocess.run(
            ["gh", "pr", "view", ready_id, "--json",
             "number,headRefOid,baseRefName,baseRefOid,isDraft,state,mergeCommit"],
            cwd=repo, capture_output=True, text=True, timeout=60)
        if viewed.returncode:
            raise ValueError("cannot bind selected PR: " + viewed.stderr)
        try:
            value = json.loads(viewed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("selected PR metadata is not JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("selected PR metadata is not an object")
        return value

    pr = view()
    if (pr.get("number") != int(ready_id)
            or pr.get("headRefOid") != ready_head
            or pr.get("baseRefName") != "main"
            or pr.get("baseRefOid") != ready_base
            or pr.get("isDraft") is not False
            or pr.get("state") != "OPEN"):
        raise ValueError("selected PR id/head/base/state no longer match admission")

    merged = subprocess.run(
        ["gh", "pr", "merge", ready_id, "--squash", "--delete-branch",
         "--match-head-commit", ready_head],
        cwd=repo, capture_output=True, text=True, timeout=300)
    if merged.returncode:
        return {"status": "BLOCKED_FINAL_WRITE",
                "id": ready_id, "head": ready_head, "base": ready_base,
                "final_rc": merged.returncode, "stdout": merged.stdout,
                "stderr": merged.stderr}
    try:
        readback = view()
    except ValueError as exc:
        return {"status": "BLOCKED_FINAL_WRITE",
                "id": ready_id, "head": ready_head, "base": ready_base,
                "merge_commit": None, "final_rc": merged.returncode,
                "stdout": merged.stdout, "stderr": str(exc)}
    merge_commit = readback.get("mergeCommit")
    merge_oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    complete = (readback.get("number") == int(ready_id)
                and readback.get("headRefOid") == ready_head
                and readback.get("baseRefName") == "main"
                and readback.get("baseRefOid") == ready_base
                and readback.get("isDraft") is False
                and readback.get("state") == "MERGED"
                and isinstance(merge_oid, str)
                and re.fullmatch(r"[0-9a-f]{40}", merge_oid))
    return {"status": ("FINAL_WRITE_COMPLETE" if complete
                       else "BLOCKED_FINAL_WRITE"),
            "id": ready_id, "head": ready_head, "base": ready_base,
            "merge_commit": merge_oid,
            "final_rc": merged.returncode, "stdout": merged.stdout,
            "stderr": merged.stderr}


def _service_final_main(argv):
    import subprocess

    ap = argparse.ArgumentParser(
        description="Bind service-ready selection to the existing sole writer")
    ap.add_argument("--service-final-write", action="store_true", required=True)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args(argv)
    try:
        report = service_final_write(args.repo.resolve(), args.base)
    except (ValueError, KeyError, TypeError, OSError,
            subprocess.SubprocessError) as exc:
        report = {"status": "BLOCKED_FINAL_WRITE_BINDING", "reason": str(exc)}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "FINAL_WRITE_COMPLETE" else RC_REFUSE


def _service_main(argv):
    ap = argparse.ArgumentParser(description="Consume accepted ready work; root-only final write")
    ap.add_argument("--service-ready", type=Path, required=True)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--writer", required=True)
    ap.add_argument("--receipt-root", type=Path)
    ap.add_argument("--candidates-json")
    ap.add_argument("--final-command", nargs=argparse.REMAINDER, required=True)
    args = ap.parse_args(argv)
    try:
        if bool(args.receipt_root) != bool(args.candidates_json is not None):
            raise ValueError("receipt root and candidate authority must be supplied together")
        if args.receipt_root:
            publish_service_manifest(args.service_ready, args.receipt_root,
                                     args.writer, args.candidates_json)
        report = service_ready(args.repo.resolve(), args.service_ready, args.writer,
                               args.final_command, args.base)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        report = {"status": "BLOCKED_ADMISSION_INPUT", "reason": str(exc)}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "DELIVERED" else RC_REFUSE


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--service-ready" in argv:
        return _service_main(argv)
    if "--service-final-write" in argv:
        return _service_final_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
