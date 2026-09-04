#!/usr/bin/env python3
"""Contract for independently-produced, per-case L10 execution evidence.

The L10 conformance consumer must not infer execution from testbench source
text.  The executor writes this record after the simulator finishes; absence,
staleness, malformed data, or a missing case row is ``NOT_EXECUTED``.

This module is a reader/writer contract, not a verdict gate.  The consumer
declares enforcement: ``FAIL`` and ``NOT_EXECUTED`` both block Step 4, while
remaining distinct claims about the design and the run respectively.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from _atomic_artefact import write_text as _atomic_write_text

SCHEMA = "vibeic.l10_execution.v1"
PASS = "PASS"
FAIL = "FAIL"
NOT_EXECUTED = "NOT_EXECUTED"
SIM_EXECUTED_KEY = "sim_executed"
CASES_KEY = "cases"

_RECORD_CANDIDATES = (
    "reports/phase2/sim/l10_execution.json",
    "reports/phase2/l10_execution.json",
    "phase2/stage1/sim/l10_execution.json",
    "reports/sim/l10_execution.json",
)


def record_path(project: Path) -> Path:
    """Canonical producer target."""
    return Path(project) / _RECORD_CANDIDATES[0]


def resolve_record(project: Path) -> Optional[Path]:
    """Resolve the first supported record location, if any."""
    for rel in _RECORD_CANDIDATES:
        candidate = Path(project) / rel
        if candidate.is_file():
            return candidate
    return None


def file_sha256(path: Path) -> str:
    """Hash an input as bytes so evidence can bind to the exact declaration."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clear_record(project: Path) -> None:
    """Remove prior evidence before an execution attempt starts.

    A failed or unavailable rerun must not leave an earlier PASS in place.
    Only the contract's producer-owned generated artefact locations are
    removed.  Clearing every supported read location prevents a stale legacy
    fallback from reappearing when the canonical file is removed.
    """
    for rel in _RECORD_CANDIDATES:
        try:
            (Path(project) / rel).unlink()
        except FileNotFoundError:
            pass


def write_record(project: Path, l10_path: Path,
                 rows: Iterable[Dict[str, Any]], *, producer: str,
                 tb_dir: Optional[Path] = None,
                 source_junit: Optional[Path] = None) -> Path:
    """Atomically publish a completed execution record."""
    target = record_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc: Dict[str, Any] = {
        "schema": SCHEMA,
        "producer": producer,
        "l10_sha256": file_sha256(l10_path),
        CASES_KEY: list(rows),
    }
    if tb_dir is not None:
        doc["tb_dir"] = str(tb_dir)
    if source_junit is not None:
        doc["source_junit"] = str(source_junit)
    _atomic_write_text(target, json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return target


def _unavailable(reason: str, path: Optional[Path] = None,
                 malformed: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "path": str(path) if path else None,
        "producer": None,
        "schema_ok": False,
        "l10_binding_ok": False,
        "rows": {},
        "malformed": malformed or [],
    }


def _normalise_verdict(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    token = raw.strip().upper()
    aliases = {
        "PASS": PASS, "PASSED": PASS, "OK": PASS,
        "FAIL": FAIL, "FAILED": FAIL, "ERROR": FAIL,
        NOT_EXECUTED: NOT_EXECUTED,
    }
    return aliases.get(token)


def load_record(project: Path, l10_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load a record, failing closed on every unreviewable shape.

    When ``l10_path`` is supplied, a record must bind to that exact file hash;
    an old record beside a changed declaration credits no case.
    """
    path = resolve_record(project)
    if path is None:
        return _unavailable("no_execution_record")
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return _unavailable(
            f"execution_record_unreadable ({type(exc).__name__})", path)
    if not isinstance(doc, dict):
        return _unavailable("execution_record_not_an_object", path)
    if doc.get("schema") != SCHEMA:
        return _unavailable("execution_record_schema_mismatch", path)
    if l10_path is not None:
        try:
            expected = file_sha256(Path(l10_path))
        except OSError as exc:
            return _unavailable(
                f"l10_binding_unreadable ({type(exc).__name__})", path)
        if doc.get("l10_sha256") != expected:
            return _unavailable("execution_record_l10_hash_mismatch", path)
    rows = doc.get(CASES_KEY)
    if not isinstance(rows, list):
        return _unavailable(f"execution_record_has_no_{CASES_KEY}_list", path)

    parsed: Dict[str, Dict[str, Any]] = {}
    malformed: List[str] = []
    duplicates = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            malformed.append(f"row {index}: not an object")
            continue
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            malformed.append(f"row {index}: no usable id")
            continue
        case_id = case_id.strip()
        if case_id in parsed:
            duplicates.add(case_id)
            malformed.append(f"row {index}: duplicate id {case_id!r}")
            continue
        verdict = _normalise_verdict(row.get("verdict"))
        parsed[case_id] = {
            "verdict": verdict,
            "raw": row.get("verdict"),
            "detail": str(row.get("detail") or ""),
            "tb_file": str(row.get("tb_file") or ""),
            # Execution is an observed boolean, not something inferred back
            # from the verdict word.  Missing, string-valued, or false keeps
            # the row at NOT_EXECUTED in ``case_state``.
            SIM_EXECUTED_KEY: row.get(SIM_EXECUTED_KEY) is True,
        }
    for duplicate in duplicates:
        parsed.pop(duplicate, None)

    return {
        "available": True,
        "reason": None,
        "path": str(path),
        "producer": doc.get("producer"),
        "schema_ok": True,
        "l10_binding_ok": True,
        "rows": parsed,
        "malformed": malformed,
    }


def case_state(case_id: str, record: Dict[str, Any]) -> Tuple[str, str]:
    """Return PASS, FAIL, or NOT_EXECUTED for one declared case."""
    row = (record.get("rows") or {}).get(case_id)
    if row is None:
        if not record.get("available"):
            why = record.get("reason") or "no_execution_record"
            return NOT_EXECUTED, f"no per-case execution evidence ({why})"
        return NOT_EXECUTED, "case absent from completed execution record"
    verdict = row.get("verdict")
    if verdict in (PASS, FAIL):
        if not row.get(SIM_EXECUTED_KEY):
            return NOT_EXECUTED, "row verdict is not backed by sim_executed=true"
        return verdict, f"execution record row (verdict={verdict})"
    if verdict == NOT_EXECUTED:
        return NOT_EXECUTED, row.get("detail") or "executor reported case not executed"
    return NOT_EXECUTED, f"unrecognised execution verdict {row.get('raw')!r}"


def unclaimed_rows(case_ids: Iterable[str], record: Dict[str, Any]) -> List[str]:
    """Rows naming no currently-declared L10 case."""
    declared = set(case_ids)
    return sorted(key for key in (record.get("rows") or {}) if key not in declared)
