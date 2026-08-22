#!/usr/bin/env python3
"""Build the exact machine completion record for one hermetic landing arm."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


_SPEC = importlib.util.spec_from_file_location(
    "_vibeic_landing_completion_json",
    Path(__file__).resolve().with_name("protected_landing_transition.py"),
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("strict JSON authority is unavailable")
strict = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = strict
_SPEC.loader.exec_module(strict)

SCHEMA = 1
KIND = "vibeic.hermetic-landing-completion"
JOURNAL_KIND = "vibeic.hermetic-landing-gate-journal"
STATES = frozenset({"PASS", "FAIL", "SKIP", "REPORT"})
ARMS = frozenset({"A2", "B2"})
SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_GATES = 512
LANDING_PROGRESS_UNITS = (
    "cheap:nda-messages",
    "cheap:nda-content",
    "cheap:version",
    "cheap:agent-scope",
    "cheap:benchmark-structure",
    "cheap:benchmark-manifest",
    "cheap:git-prohibition",
    "cheap:collateral-revert",
    "cheap:base-ancestry",
    "cheap:version-sync",
    "cheap:landing-shape",
    "cheap:competing-claims-report",
    "cheap:worktree-clean",
    "cheap:scratch-report",
    "full:write-guard-baseline",
    "full:targeted-tests",
    "full:repo-tools-tests",
    "full:unselectable-tests",
    "full:unselectable-census",
    "full:repo-hygiene",
    "full:plugin-audit",
    "full:gatekeeper-review",
    "full:write-guard-final",
    "full:worktree-fingerprint-final",
    "full:completion-record",
)


class Refusal(RuntimeError):
    pass


def _digest_record(value: Any, what: str) -> dict[str, Any]:
    if (not isinstance(value, dict) or set(value) != {"sha256", "size"}
            or not isinstance(value.get("sha256"), str)
            or SHA256_RE.fullmatch(value["sha256"]) is None
            or type(value.get("size")) is not int or value["size"] < 0):
        raise Refusal(f"{what} is not one exact file digest")
    return {"sha256": value["sha256"], "size": value["size"]}


def _bounded(value: Any, what: str, limit: int = 240) -> str:
    if (not isinstance(value, str) or not value or len(value) > limit
            or "\x00" in value or "\n" in value or "\r" in value):
        raise Refusal(f"{what} is not one bounded string")
    return value


def _regular_digest(path: Path, what: str) -> dict[str, Any]:
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or path.is_symlink()
                or before.st_nlink != 1):
            raise Refusal(f"{what} is not a single-link regular file")
        fd = os.open(
            path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        try:
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            held = os.fstat(fd)
        finally:
            os.close(fd)
        after = path.lstat()
    except OSError as exc:
        raise Refusal(f"cannot read {what}: {exc}") from exc
    identity = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_nlink,
                            row.st_size, row.st_mtime_ns, row.st_ctime_ns)
    if identity(before) != identity(held) or identity(before) != identity(after):
        raise Refusal(f"{what} changed while read")
    return {"sha256": digest.hexdigest(), "size": size}


def _atomic_write(path: Path, raw: bytes, *, replace: bool) -> None:
    path.parent.resolve(strict=True)
    if not replace and (path.exists() or path.is_symlink()):
        raise Refusal(f"output already exists: {path}")
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short completion-record write")
            view = view[written:]
        os.fsync(fd)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    finally:
        os.close(fd)
    os.replace(temporary, path)
    observed = path.lstat()
    if (not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1
            or stat.S_IMODE(observed.st_mode) != 0o600):
        raise Refusal("published record is not a private regular file")


def _journal(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        observed = path.lstat()
        if (not stat.S_ISREG(observed.st_mode) or path.is_symlink()
                or observed.st_nlink != 1):
            raise Refusal("landing gate journal is not a single-link regular file")
        doc = strict.strict_loads(
            path.read_bytes(), what="landing gate journal")
    except (OSError, strict.Refusal) as exc:
        raise Refusal(f"landing gate journal is unreadable: {exc}") from exc
    if (not isinstance(doc, dict) or set(doc) != {
            "schema", "kind", "complete", "gates"}
            or type(doc.get("schema")) is not int or doc["schema"] != SCHEMA
            or doc.get("kind") != JOURNAL_KIND or doc.get("complete") is not False
            or not isinstance(doc.get("gates"), list)):
        raise Refusal("landing gate journal has the wrong schema")
    gates = []
    for index, row in enumerate(doc["gates"]):
        if (not isinstance(row, dict) or set(row) != {
                "index", "label", "output_sha256", "returncode", "state"}
                or type(row.get("index")) is not int or row["index"] != index
                or type(row.get("returncode")) is not int
                or row["state"] not in STATES
                or not isinstance(row.get("output_sha256"), str)
                or SHA256_RE.fullmatch(row["output_sha256"]) is None):
            raise Refusal("landing gate journal row is malformed")
        label = _bounded(row.get("label"), "gate label")
        if ((row["state"] == "PASS" and row["returncode"] != 0)
                or (row["state"] == "FAIL" and row["returncode"] == 0)
                or (row["state"] == "SKIP" and row["returncode"] != 0)
                or not 0 <= row["returncode"] <= 255):
            raise Refusal("landing gate state/returncode disagree")
        gates.append({**row, "label": label})
    labels = [row["label"] for row in gates]
    if labels != list(LANDING_PROGRESS_UNITS[:len(labels)]):
        raise Refusal("landing gate journal is not the exact ordered population")
    return gates


def append(path: Path, *, label: str, state: str, returncode: int,
           output_sha256: str) -> None:
    label = _bounded(label, "gate label")
    if state not in STATES or type(returncode) is not int:
        raise Refusal("gate state/returncode is malformed")
    if ((state == "PASS" and returncode != 0)
            or (state == "FAIL" and returncode == 0)
            or (state == "SKIP" and returncode != 0)
            or not 0 <= returncode <= 255):
        raise Refusal("gate state/returncode disagree")
    if SHA256_RE.fullmatch(output_sha256) is None:
        raise Refusal("gate output digest is malformed")
    gates = _journal(path)
    if (len(gates) >= len(LANDING_PROGRESS_UNITS)
            or label != LANDING_PROGRESS_UNITS[len(gates)]):
        raise Refusal("gate journal label is not the next parent-owned unit")
    gates.append({"index": len(gates), "label": label,
                  "output_sha256": output_sha256,
                  "returncode": returncode, "state": state})
    doc = {"schema": SCHEMA, "kind": JOURNAL_KIND,
           "complete": False, "gates": gates}
    _atomic_write(path, strict.canonical_bytes(doc), replace=path.exists())


def _resolved_cwd() -> Path:
    return Path.cwd().resolve(strict=True)


def _git(*args: str) -> str:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")}
    env.update({"GIT_NO_REPLACE_OBJECTS": "1", "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C"})
    if os.environ.get("VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY") == "1":
        try:
            cwd = _resolved_cwd()
        except OSError as exc:
            raise Refusal("hermetic subject cwd cannot be resolved") from exc
        if cwd != Path("/subject"):
            raise Refusal("hermetic completion must run at exact /subject")
        # `/subject` is materialized by the trusted host and mounted read-only
        # for uid 65534, so Git cannot infer trust from uid equality.  Restore
        # only this exact runner-owned exception after stripping every ambient
        # GIT_* variable above; wildcard/user/system configuration stays out.
        env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "/subject",
        })
    proc = subprocess.run(
        ["git", *args], env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise Refusal(f"git {' '.join(args[:2])} failed")
    value = proc.stdout.strip()
    if not value or "\n" in value or "\r" in value:
        raise Refusal("git identity is not one line")
    return value


def finish(
    journal: Path,
    *,
    failed: int,
    selection_path: Path = Path("/input/selection"),
    progress_plan_path: Path = Path("/input/progress-plan.json"),
    hygiene_path: Path | None = None,
) -> dict[str, Any]:
    if type(failed) is not int or failed not in {0, 1}:
        raise Refusal("FAILED is not exact 0 or 1")
    gates = _journal(journal)
    if not gates:
        raise Refusal("landing gate journal is empty")
    if [row["label"] for row in gates] != list(LANDING_PROGRESS_UNITS):
        raise Refusal("landing gate journal is not the complete population")
    observed_failure = any(row["state"] == "FAIL" for row in gates)
    if observed_failure != bool(failed):
        raise Refusal("shell FAILED flag disagrees with the gate journal")
    arm = os.environ.get("GATEKEEPER_VERIFY_ARM")
    base = os.environ.get("GATEKEEPER_BASE")
    benchmark = os.environ.get("GATEKEEPER_BENCHMARK_DATA_SHA")
    nonce = os.environ.get("VIBEIC_LANDING_PROGRESS_NONCE")
    if (arm not in ARMS or not isinstance(base, str)
            or SHA_RE.fullmatch(base) is None
            or not isinstance(benchmark, str) or SHA_RE.fullmatch(benchmark) is None
            or not isinstance(nonce, str) or SHA256_RE.fullmatch(nonce) is None):
        raise Refusal("verified landing identity environment is incomplete")
    head = _git("rev-parse", "HEAD^{commit}")
    tree = _git("rev-parse", "HEAD^{tree}")
    if SHA_RE.fullmatch(head) is None or SHA_RE.fullmatch(tree) is None:
        raise Refusal("subject Git identity is malformed")
    if not (len(base) == len(head) == len(tree)):
        raise Refusal("base, HEAD, and tree object formats disagree")
    selection = _regular_digest(selection_path, "selection")
    progress_plan = _regular_digest(
        progress_plan_path, "progress plan")
    if hygiene_path is None:
        configured_hygiene = os.environ.get("GATEKEEPER_HYGIENE_REPORT")
        if (not isinstance(configured_hygiene, str)
                or not configured_hygiene.startswith("/evidence/")
                or Path(configured_hygiene).as_posix() != configured_hygiene):
            raise Refusal("hygiene record path is outside the evidence volume")
        hygiene_path = Path(configured_hygiene)
    hygiene = _regular_digest(hygiene_path, "hygiene record")
    payload = {
        "arm": arm,
        "base": base,
        "benchmark_data_sha": benchmark,
        "failed": failed,
        "gates": gates,
        "head": head,
        "hygiene": hygiene,
        "progress_nonce": nonce,
        "progress_plan": progress_plan,
        "returncode": 1 if failed else 0,
        "selection": selection,
        "tree": tree,
    }
    return {"schema": SCHEMA, "kind": KIND, "complete": True,
            "payload": payload,
            "payload_sha256": hashlib.sha256(
                strict.canonical_bytes(payload)).hexdigest()}


def parse_record(value: Any) -> dict[str, Any]:
    if (not isinstance(value, dict) or set(value) != {
            "schema", "kind", "complete", "payload", "payload_sha256"}
            or type(value.get("schema")) is not int or value["schema"] != SCHEMA
            or value.get("kind") != KIND or value.get("complete") is not True):
        raise Refusal("landing completion record has the wrong envelope")
    payload = value.get("payload")
    expected = {
        "arm", "base", "benchmark_data_sha", "failed", "gates", "head",
        "hygiene", "progress_nonce", "progress_plan", "returncode",
        "selection", "tree",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise Refusal("landing completion payload has the wrong schema")
    if payload["arm"] not in ARMS:
        raise Refusal("landing completion arm is not A2/B2")
    for key in ("base", "head", "tree"):
        if (not isinstance(payload[key], str)
                or SHA_RE.fullmatch(payload[key]) is None):
            raise Refusal(f"landing completion {key} is not an object id")
    if not (len(payload["base"]) == len(payload["head"])
            == len(payload["tree"])):
        raise Refusal("landing completion object formats disagree")
    if (not isinstance(payload["benchmark_data_sha"], str)
            or SHA_RE.fullmatch(payload["benchmark_data_sha"]) is None):
        raise Refusal("landing completion benchmark SHA is malformed")
    if (not isinstance(payload["progress_nonce"], str)
            or SHA256_RE.fullmatch(payload["progress_nonce"]) is None):
        raise Refusal("landing completion nonce is malformed")
    if (type(payload["failed"]) is not int or payload["failed"] not in {0, 1}
            or type(payload["returncode"]) is not int
            or payload["returncode"] != payload["failed"]):
        raise Refusal("landing completion failure fields disagree")
    gates = payload["gates"]
    if (not isinstance(gates, list) or not gates or len(gates) > MAX_GATES):
        raise Refusal("landing completion has no finite gate population")
    parsed_gates: list[dict[str, Any]] = []
    labels: set[str] = set()
    for index, row in enumerate(gates):
        if (not isinstance(row, dict) or set(row) != {
                "index", "label", "output_sha256", "returncode", "state"}
                or type(row.get("index")) is not int or row["index"] != index
                or type(row.get("returncode")) is not int
                or row.get("state") not in STATES
                or not isinstance(row.get("output_sha256"), str)
                or SHA256_RE.fullmatch(row["output_sha256"]) is None):
            raise Refusal("landing completion gate row is malformed")
        label = _bounded(row.get("label"), "landing completion gate label")
        if label in labels:
            raise Refusal("landing completion repeats a gate label")
        labels.add(label)
        if ((row["state"] == "PASS" and row["returncode"] != 0)
                or (row["state"] == "FAIL" and row["returncode"] == 0)
                or (row["state"] == "SKIP" and row["returncode"] != 0)
                or not 0 <= row["returncode"] <= 255):
            raise Refusal("landing completion gate state/returncode disagree")
        parsed_gates.append(dict(row))
    if [row["label"] for row in parsed_gates] != list(LANDING_PROGRESS_UNITS):
        raise Refusal("landing completion gate population is not exact")
    observed_failure = any(row["state"] == "FAIL" for row in parsed_gates)
    if observed_failure != bool(payload["failed"]):
        raise Refusal("landing completion gates disagree with failed")
    for key in ("hygiene", "progress_plan", "selection"):
        _digest_record(payload[key], f"landing completion {key}")
    digest = value.get("payload_sha256")
    if (not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None
            or digest != hashlib.sha256(
                strict.canonical_bytes(payload)).hexdigest()):
        raise Refusal("landing completion payload digest disagrees")
    return {
        "schema": SCHEMA, "kind": KIND, "complete": True,
        "payload": {**payload, "gates": parsed_gates},
        "payload_sha256": digest,
    }


def strict_load_record(path: Path) -> dict[str, Any]:
    try:
        observed = path.lstat()
        if (not stat.S_ISREG(observed.st_mode) or path.is_symlink()
                or observed.st_nlink != 1):
            raise Refusal("landing completion record is not a regular file")
        raw = path.read_bytes()
    except OSError as exc:
        raise Refusal(f"cannot read landing completion record: {exc}") from exc
    try:
        return parse_record(strict.strict_loads(
            raw, what="landing completion record"))
    except strict.Refusal as exc:
        raise Refusal(str(exc)) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("append")
    add.add_argument("--journal", type=Path, required=True)
    add.add_argument("--label", required=True)
    add.add_argument("--state", choices=sorted(STATES), required=True)
    add.add_argument("--returncode", type=int, required=True)
    add.add_argument("--output-sha256", required=True)
    done = sub.add_parser("finish")
    done.add_argument("--journal", type=Path, required=True)
    done.add_argument("--record", type=Path, required=True)
    done.add_argument("--failed", type=int, required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--scope", required=True)
    plan.add_argument("--stall-grace-seconds", type=int, required=True)
    plan.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "append":
            append(args.journal, label=args.label, state=args.state,
                   returncode=args.returncode,
                   output_sha256=args.output_sha256)
        elif args.command == "finish":
            record = finish(args.journal, failed=args.failed)
            _atomic_write(
                args.record, strict.canonical_bytes(record), replace=False)
        else:
            scope = _bounded(args.scope, "landing progress scope")
            grace = args.stall_grace_seconds
            if type(grace) is not int or not 1 <= grace <= 86400:
                raise Refusal("landing progress grace is outside 1..86400")
            doc = {"schema": SCHEMA, "scope": scope,
                   "stall_grace_seconds": grace,
                   "units": list(LANDING_PROGRESS_UNITS)}
            _atomic_write(
                args.output, strict.canonical_bytes(doc), replace=False)
    except (OSError, Refusal) as exc:
        print(f"[NORECORD] landing completion record: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
