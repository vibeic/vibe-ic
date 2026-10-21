#!/usr/bin/env python3
"""Extract explicit negative reliability facts into L25.

This module deliberately does not infer a qualification envelope from PVT
analysis points.  It preserves only two closed statements that input prose can
make without a measurement: qualification is not established, and a named
reliability check remains unmeasured.  Every emitted statement cites the exact
input line so the L25 consumer can re-read evidence independently.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DOC_SUFFIXES = (".md", ".markdown", ".txt", ".rst", ".adoc", ".asciidoc")

_QUALIFICATION = re.compile(r"(?<![a-z0-9])qualif(?:y|ied|ication)(?![a-z0-9])", re.I)
_NEGATED_QUALIFICATION = (
    re.compile(r"(?<![a-z0-9])not\b.{0,160}\bqualif(?:y|ied|ication)(?![a-z0-9])", re.I),
    re.compile(r"(?<![a-z0-9])no\b.{0,160}\bqualif(?:y|ied|ication)(?![a-z0-9])", re.I),
    re.compile(r"\bwithout\b.{0,160}\bqualif(?:y|ied|ication)(?![a-z0-9])", re.I),
)
_RELIABILITY_QUAL_CONTEXT = re.compile(
    r"(?<![a-z0-9])(?:reliability|mission(?:[- ]profile)?|lifetime|"
    r"temperature|voltage|aging|NBTI|HCI|EM|electro[- ]?migration|"
    r"AEC[- ]?Q(?:100|200)|JESD47)(?![a-z0-9])", re.I)
_UNMEASURED = re.compile(
    r"(?<![a-z0-9])(?:unmeasured|not\s+(?:yet\s+)?measured|not_measured)"
    r"(?![a-z0-9])", re.I)

# Closed L25 vocabulary. DRC/LVS/ERC/IR belong to the L24 sign-off contract;
# seeing them beside a reliability term does not move them into L25.
_OBLIGATIONS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("EM", re.compile(r"(?<![a-z0-9])(?:EM|electro[- ]?migration)(?![a-z0-9])", re.I)),
    ("ESD", re.compile(r"(?<![a-z0-9])ESD(?![a-z0-9])", re.I)),
    ("current_capacity", re.compile(r"(?<![a-z0-9])current[- ]capacity(?![a-z0-9])", re.I)),
    ("aging", re.compile(r"(?<![a-z0-9])(?:aging|NBTI|HCI)(?![a-z0-9])", re.I)),
)


def _documents(project: Path) -> List[Path]:
    root = project / "input" / "docs"
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and p.suffix.lower() in _DOC_SUFFIXES)


def _citation(project: Path, path: Path, line: int, literal: str) -> Dict[str, Any]:
    return {
        "document": path.relative_to(project).as_posix(),
        "line": line,
        "literal": literal.strip()[:1000],
    }


def extract_negative_reliability(project: Path) -> Optional[Dict[str, Any]]:
    """Return typed L25 negative facts, or ``None`` when none are explicit."""
    project = Path(project)
    qualification = None
    obligations: List[Dict[str, Any]] = []
    evidence: Dict[str, List[Dict[str, str]]] = {}
    scanned: List[str] = []
    seen_obligations = set()

    for path in _documents(project):
        rel = path.relative_to(project).as_posix()
        scanned.append(rel)
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        for lineno, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line:
                continue
            if (qualification is None and _QUALIFICATION.search(line)
                    and _RELIABILITY_QUAL_CONTEXT.search(line)
                    and any(p.search(line) for p in _NEGATED_QUALIFICATION)):
                cite = _citation(project, path, lineno, line)
                qualification = {
                    "status": "NOT_ESTABLISHED",
                    "citation": cite,
                }
                evidence.setdefault(rel, []).append({
                    "literal": cite["literal"],
                    "label": "qualification_status",
                })

            if not _UNMEASURED.search(line):
                continue
            for subject, pattern in _OBLIGATIONS:
                if not pattern.search(line):
                    continue
                key = (subject, rel, lineno)
                if key in seen_obligations:
                    continue
                seen_obligations.add(key)
                cite = _citation(project, path, lineno, line)
                obligations.append({
                    "subject": subject,
                    "status": "NOT_MEASURED",
                    "citation": cite,
                })
                evidence.setdefault(rel, []).append({
                    "literal": cite["literal"],
                    "label": f"unmeasured_obligations {subject}",
                })

    fields: Dict[str, Any] = {}
    if qualification is not None:
        fields["qualification_status"] = qualification
    if obligations:
        fields["unmeasured_obligations"] = obligations
    if not fields:
        return None
    return {
        "fields": fields,
        "extraction_evidence": evidence,
        "source_documents": sorted(evidence),
        "scan": {
            "documents_scanned": scanned,
            "documents_scanned_count": len(scanned),
            "extracted_by": (
                "l25_reliability_negative_extract.extract_negative_reliability"),
        },
    }


__all__ = ["extract_negative_reliability"]

