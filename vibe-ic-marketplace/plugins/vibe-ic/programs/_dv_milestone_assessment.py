"""Current-run evidence contract for L10 DV checklist milestones.

L10 carries the imported checklist row and its historical status.  That status
is source material and is never rewritten here.  A later run may publish a
separate expert assessment at ``reports/phase2/dv_milestone_assessment.json``.
This reader accepts such an assessment only when it is bound to:

* the exact L10 bytes and exact source row;
* the complete current RTL file population and hashes;
* at least one current evidence file and its hash; and
* a named measurement producer, expert, acceptance condition, and review.

The expert still owns the heterogeneous semantic judgement (coverage, nightly,
formal, CDC, or another milestone-specific condition).  This program owns the
mechanical freshness and scope checks.  A missing, stale, malformed, unsigned,
or evidence-free row is unavailable; it never becomes PASS.

This is a reader/writer contract used by the existing
``l10_tb_conformance_check`` consumer.  It is not a new flow step or gate.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

_PROGRAMS = Path(__file__).resolve().parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from _atomic_artefact import write_text as _atomic_write_text

SCHEMA = "vibeic.dv-milestone-assessment.v1"
RECORD_REL = "reports/phase2/dv_milestone_assessment.json"
PASS = "PASS"
FAIL = "FAIL"
INCOMPLETE = "INCOMPLETE"
_VERDICTS = {PASS, FAIL, INCOMPLETE}


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def row_sha256(row: Dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rtl_files(project: Path) -> list[Path]:
    root = Path(project) / "phase2" / "stage1" / "rtl"
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*")
                  if p.is_file()
                  and p.suffix.lower() in (".v", ".sv", ".vh", ".svh"))


def rtl_context(project: Path) -> Dict[str, str]:
    project = Path(project).resolve()
    return {p.resolve().relative_to(project).as_posix(): sha256(p)
            for p in _rtl_files(project)}


def record_path(project: Path) -> Path:
    return Path(project) / RECORD_REL


def write_record(project: Path, l10_path: Path,
                 checklist_rows: Iterable[Dict[str, Any]],
                 assessments: Iterable[Dict[str, Any]]) -> Path:
    """Publish an expert-authored assessment with mechanical bindings filled.

    The caller authors ``verdict``, ``producer``, ``acceptance_condition``,
    ``signed_by`` and ``review``.  Each evidence entry supplies a
    project-relative ``path``; this writer hashes the live bytes rather than
    accepting a caller-provided hash.  ``load_record`` remains authoritative
    and rechecks every binding.
    """
    project = Path(project).resolve()
    declared = {
        str(row.get("id", row.get("name", ""))).strip(): row
        for row in checklist_rows if isinstance(row, dict)
        and str(row.get("id", row.get("name", ""))).strip()
    }
    rows = []
    for original in assessments:
        row = dict(original)
        milestone = str(row.get("id") or "").strip()
        if milestone not in declared:
            raise ValueError(f"assessment id {milestone!r} is not a checklist row")
        row["source_row_sha256"] = row_sha256(declared[milestone])
        evidence = []
        for raw in row.get("evidence") or []:
            if not isinstance(raw, dict):
                raise ValueError("evidence entries must be objects")
            target = _inside(project, raw.get("path"))
            if target is None or not target.is_file():
                raise ValueError(f"evidence path {raw.get('path')!r} is unavailable")
            rel = target.relative_to(project).as_posix()
            if not _is_current_run_evidence(rel):
                raise ValueError(
                    f"evidence path {raw.get('path')!r} is not a current-run output")
            evidence.append({"path": rel, "sha256": sha256(target)})
        row["evidence"] = evidence
        rows.append(row)
    context = rtl_context(project)
    if not context:
        raise ValueError("current RTL context is empty")
    doc = {
        "schema": SCHEMA,
        "l10_sha256": sha256(Path(l10_path)),
        "rtl_files_sha256": context,
        "rows": rows,
    }
    target = record_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(target, json.dumps(
        doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return target


def _unavailable(reason: str, path: Optional[Path] = None,
                 malformed: Optional[list[str]] = None) -> Dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "path": str(path) if path else None,
        "sha256": None,
        "rows": {},
        "malformed": malformed or [],
        "unclaimed_rows": [],
    }


def _inside(project: Path, rel: str) -> Optional[Path]:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        return None
    root = Path(project).resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _is_current_run_evidence(rel: str) -> bool:
    """A design input, L-doc, audit write or RTL source is not a measurement."""
    path = str(rel).replace("\\", "/").lstrip("./")
    forbidden = ("input/", "plugin_input/", "phase1/", "golden/", "oracle/",
                 "score/", "reports/audit/", "phase2/stage1/rtl/")
    return path != RECORD_REL and not path.startswith(forbidden)


def _normalise_verdict(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    token = raw.strip().upper()
    aliases = {"PASSED": PASS, "OK": PASS, "FAILED": FAIL,
               "ERROR": FAIL, "NOT_MEASURED": INCOMPLETE}
    return aliases.get(token, token if token in _VERDICTS else None)


def load_record(project: Path, l10_path: Path,
                checklist_rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Load the current assessment, refusing every stale or unreviewable row."""
    project = Path(project).resolve()
    path = record_path(project)
    if not path.is_file():
        return _unavailable("no_current_dv_milestone_assessment")
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return _unavailable(
            f"assessment_unreadable ({type(exc).__name__})", path)
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return _unavailable("assessment_schema_mismatch", path)
    try:
        current_l10 = sha256(Path(l10_path))
    except OSError as exc:
        return _unavailable(f"l10_unreadable ({type(exc).__name__})", path)
    if doc.get("l10_sha256") != current_l10:
        return _unavailable("assessment_l10_hash_mismatch", path)
    current_rtl = rtl_context(project)
    if not current_rtl:
        return _unavailable("assessment_has_no_current_rtl_context", path)
    if doc.get("rtl_files_sha256") != current_rtl:
        return _unavailable("assessment_rtl_context_mismatch", path)

    declared = {
        str(row.get("id", row.get("name", ""))).strip(): row
        for row in checklist_rows if isinstance(row, dict)
        and str(row.get("id", row.get("name", ""))).strip()
    }
    raw_rows = doc.get("rows")
    if not isinstance(raw_rows, list):
        return _unavailable("assessment_has_no_rows_list", path)
    parsed: Dict[str, Dict[str, Any]] = {}
    malformed: list[str] = []
    unclaimed: list[str] = []
    duplicates: set[str] = set()
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            malformed.append(f"row {index}: not an object")
            continue
        milestone = raw.get("id")
        if not isinstance(milestone, str) or not milestone.strip():
            malformed.append(f"row {index}: no usable id")
            continue
        milestone = milestone.strip()
        if milestone in parsed:
            duplicates.add(milestone)
            malformed.append(f"row {index}: duplicate id {milestone!r}")
            continue
        source = declared.get(milestone)
        if source is None:
            unclaimed.append(milestone)
            continue
        refusals: list[str] = []
        if raw.get("source_row_sha256") != row_sha256(source):
            refusals.append("source_row_hash_mismatch")
        verdict = _normalise_verdict(raw.get("verdict"))
        if verdict is None:
            refusals.append("invalid_verdict")
        for field in ("producer", "acceptance_condition", "signed_by", "review"):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                refusals.append(f"missing_{field}")
        evidence = raw.get("evidence")
        checked: list[dict[str, str]] = []
        if not isinstance(evidence, list) or not evidence:
            refusals.append("no_evidence")
        else:
            for ev_index, ev in enumerate(evidence):
                if not isinstance(ev, dict):
                    refusals.append(f"evidence_{ev_index}_not_an_object")
                    continue
                rel, expected = ev.get("path"), ev.get("sha256")
                target = _inside(project, rel)
                if target is None or not target.is_file():
                    refusals.append(f"evidence_{ev_index}_missing_or_outside_project")
                    continue
                canonical_rel = target.relative_to(project).as_posix()
                if not _is_current_run_evidence(canonical_rel):
                    refusals.append(f"evidence_{ev_index}_not_current_run_output")
                elif not isinstance(expected, str) or sha256(target) != expected:
                    refusals.append(f"evidence_{ev_index}_hash_mismatch")
                else:
                    checked.append({"path": canonical_rel, "sha256": expected})
        parsed[milestone] = {
            "valid": not refusals,
            "verdict": verdict,
            "producer": raw.get("producer"),
            "acceptance_condition": raw.get("acceptance_condition"),
            "signed_by": raw.get("signed_by"),
            "review": raw.get("review"),
            "evidence": checked,
            "refusals": refusals,
        }
    for duplicate in duplicates:
        parsed.pop(duplicate, None)
    return {
        "available": True,
        "reason": None,
        "path": str(path),
        "sha256": sha256(path),
        "rows": parsed,
        "malformed": malformed,
        "unclaimed_rows": sorted(unclaimed),
    }


def row_state(milestone_id: str, record: Optional[Dict[str, Any]]
              ) -> tuple[Optional[str], str, Optional[Dict[str, Any]]]:
    """Return a valid current verdict, or None with a named refusal."""
    if not record or not record.get("available"):
        why = (record or {}).get("reason") or "no_current_assessment"
        return None, why, None
    row = (record.get("rows") or {}).get(milestone_id)
    if row is None:
        return None, "milestone_absent_from_current_assessment", None
    if not row.get("valid"):
        return None, ",".join(row.get("refusals") or ["invalid_assessment"]), row
    return row.get("verdict"), "current_assessment_bound", row
