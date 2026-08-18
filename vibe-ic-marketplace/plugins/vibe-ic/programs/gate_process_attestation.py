#!/usr/bin/env python3
"""Structured process evidence for repo hygiene gates.

This is not a gate and emits no verdict of its own.  It turns one completed
gate process into a machine record whose identity includes the raw return code,
the normalized verdict line, and the normalized set of named failures.  A
consumer must reject a missing or malformed record; prose is never a fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

SCHEMA = 1

_FINDING_RE = re.compile(
    r"^\s*(?:"
    r"\[(?:FAIL|FAILED|ERROR|UNDETERMINED|NOT[ _]CHECKED|NORECORD)\]"
    r"|FAILED\s+|ERROR\s+|FAIL(?:ED)?[\s:]"
    r"|AssertionError[\s:]|E\s{2,})",
    re.IGNORECASE)
_PYTEST_TIME_RE = re.compile(
    r"\bin\s+\d+(?:\.\d+)?s(?:\s+\(\d+:\d{2}:\d{2}\))?\s*$")


def _is_finding_line(line: str) -> bool:
    """Whether a line is a verdict token in the gate-output grammar."""
    return _FINDING_RE.match(line) is not None


def _replace_roots(text: str, roots: Iterable[Path]) -> str:
    vals = set()
    for root in roots:
        try:
            vals.add(str(Path(root).resolve()))
        except OSError:
            pass
        vals.add(str(root))
    for value in sorted((v for v in vals if v), key=len, reverse=True):
        text = text.replace(value, "<TREE>")
    return text


def normalise_line(line: str, roots: Iterable[Path]) -> str:
    line = _replace_roots(line.rstrip(), roots)
    return _PYTEST_TIME_RE.sub("in <TIME>s", line)


def semantic_record(output: str, returncode: int,
                    roots: Iterable[Path] = ()) -> Dict:
    """Return the verdict-bearing portion of one completed process."""
    lines = [normalise_line(line, roots) for line in output.splitlines()
             if line.strip()]
    verdict = lines[-1] if lines else "(no output)"
    findings = sorted(set(line for line in lines if _is_finding_line(line)))
    payload = {
        "returncode": int(returncode),
        "verdict_line": verdict,
        "finding_identities": findings,
    }
    payload["semantic_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")).hexdigest()
    return payload


def argv_sha256(argv: Sequence[str], roots: Iterable[Path] = ()) -> str:
    normalized = [_replace_roots(str(arg), roots) for arg in argv]
    return hashlib.sha256(json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def process_attestation(label: str, output: str, returncode: int,
                        argv: Sequence[str], roots: Iterable[Path] = (),
                        state: str = "") -> Dict:
    record = {
        "schema": SCHEMA,
        "complete": True,
        "label": label,
        "state": state,
        "argv_sha256": argv_sha256(argv, roots),
    }
    record.update(semantic_record(output, returncode, roots))
    return record


def append_private_jsonl(path: Path, record: Dict) -> None:
    """Append one complete record without inheriting a permissive umask."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.chmod(path, 0o600)
        data = (json.dumps(record, sort_keys=True, ensure_ascii=False)
                + "\n").encode("utf-8")
        while data:
            written = os.write(fd, data)
            if written <= 0:
                raise OSError("short write while appending process attestation")
            data = data[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _strict_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def strict_loads(payload: str) -> Any:
    """Decode one unambiguous RFC-JSON value."""
    return json.loads(payload, object_pairs_hook=_strict_object,
                      parse_constant=_reject_json_constant)


def validate_record(rec: object, lineno: int = 0) -> Dict:
    """Return one complete record or raise; shared by file/live consumers."""
    where = f" at line {lineno}" if lineno else ""
    required = {"schema", "complete", "label", "state", "argv_sha256",
                "returncode", "verdict_line", "finding_identities",
                "semantic_sha256"}
    if (not isinstance(rec, dict) or set(rec) != required
            or rec.get("schema") != SCHEMA or rec.get("complete") is not True):
        raise ValueError(f"invalid process attestation{where}")
    if (not isinstance(rec["label"], str)
            or not isinstance(rec["state"], str)
            or type(rec["returncode"]) is not int
            or not isinstance(rec["verdict_line"], str)
            or not isinstance(rec["finding_identities"], list) or not all(
            isinstance(item, str) for item in rec["finding_identities"])):
        raise ValueError(f"invalid process attestation field types{where}")
    for key in ("argv_sha256", "semantic_sha256"):
        value = rec[key]
        if (not isinstance(value, str) or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)):
            raise ValueError(f"invalid {key}{where}")
    semantic = {
        "returncode": rec["returncode"],
        "verdict_line": rec["verdict_line"],
        "finding_identities": rec["finding_identities"],
    }
    expected = hashlib.sha256(json.dumps(
        semantic, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    if rec["semantic_sha256"] != expected:
        raise ValueError(f"process attestation digest mismatch{where}")
    return rec


def load_jsonl(path: Path) -> List[Dict]:
    """Load only complete, current-schema records; malformed means refusal."""
    records: List[Dict] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(),
                                  start=1):
        if not line.strip():
            continue
        records.append(validate_record(strict_loads(line), lineno))
    return records


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--label", required=True)
    ap.add_argument("--returncode", required=True, type=int)
    ap.add_argument("--state", default="")
    ap.add_argument("--output-log", type=Path, required=True)
    ap.add_argument("--append-jsonl", type=Path, required=True)
    ap.add_argument("--root", type=Path, action="append", default=[])
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        ap.error("the attested command argv is required after --")
    output = args.output_log.read_text(encoding="utf-8", errors="replace")
    record = process_attestation(args.label, output, args.returncode,
                                 command, args.root, args.state)
    append_private_jsonl(args.append_jsonl, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
