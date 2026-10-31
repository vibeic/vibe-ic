"""BLOCKING front-door delivery choice, shared by the whole and Phase-1 runners.

The owner answers IC or IP before Phase 1. Phase 3 retains its separate
admission check for stale generated declarations and router artefacts.
"""
from __future__ import annotations

import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from datetime import date
from pathlib import Path
import hashlib
import subprocess
from typing import Optional

import _atomic_artefact as _aa
import _submission_template as _st
import _tapeout_declaration as _td


ROUTES = {"ic": _td.DELIVERABLE_DIE, "ip": _td.DELIVERABLE_HARDMACRO}


def issue_typed_receipt(project, route, **_unused):
    """Consume the immutable route issued by the isolated canonical entry."""
    from execution_authority import consume
    from execution_modes import Refusal
    receipt = consume()['route']
    if receipt['project'] != str(Path(project).resolve()) or receipt['route'] != route:
        raise Refusal('ROUTE_AUTHORITY_UNAVAILABLE', 'project/route does not match live issuer')
    return receipt


def _disclose_undeclared(reason: str, doc: object) -> str:
    """Quote the staged route and its attestation in a front-door refusal."""
    staged = doc if isinstance(doc, dict) else {}
    answers = staged.get("answers")
    value = (_td.raw_answer(staged, "deliverable")
             if isinstance(answers, dict) else None)
    attestation = _td.attestation_of(staged, "deliverable")
    return (f"{reason}; staged answers.deliverable={value!r}; "
            "answer_provenance.deliverable "
            f"answered_by={attestation['answered_by']!r}, "
            f"citation={attestation['citation']!r}")


def admit(project: Path, route: Optional[str] = None, *, allow_rtl_scope: bool = True) -> Optional[str]:
    """Return a refusal, or write/accept the owner's route before Phase 1.

    The raw file is the source for new runs. A resumed run with only an
    owner-attested generated declaration is also accepted, as Phase 3 accepts
    it; a present but unanswered raw file cannot be rescued by that fallback.
    """
    if allow_rtl_scope:
        import flow109
        try:
            scope = flow109.active_rtl_scope(project)
        except flow109.Flow109Error as exc:
            return str(exc)
        if scope is not None:
            return ("FLOW109_RTL_SCOPE_CONFLICT: physical IC route requested"
                    if route == "ic" else None)
    raw_rel = _st.DESIGN_ANSWERS_REL
    raw_path = project / raw_rel
    declaration = project / _td.DECLARATION_REL
    requested = ROUTES.get(route) if route else None
    if route:
        same_raw_owner_answer = False
        for rel in (raw_rel, _td.DECLARATION_REL):
            if not (project / rel).exists():
                continue
            doc, err = _td.load(project / rel)
            if err or not isinstance(doc, dict) or not isinstance(doc.get("answers"), dict):
                return f"{rel}: {err or 'invalid answer mapping'}"
            try:
                _, existing = _td.read_owner_delivery(project, rel)
            except ValueError:
                continue  # a guess or silence does not bind the owner
            if existing != requested:
                return (f"operator --route {route} contradicts the existing "
                        f"owner-provenance answer {existing} in {rel}")
            if rel == raw_rel:
                same_raw_owner_answer = True
        if same_raw_owner_answer:
            return None  # preserve the original owner citation byte for byte

        if raw_path.exists():
            doc, err = _td.load(raw_path)
            if err or not isinstance(doc, dict) or not isinstance(doc.get("answers"), dict):
                return f"{raw_rel}: {err or 'invalid answer mapping'}"
        else:
            doc = {"schema": "vibe-ic/step_0_5ic_answers/1", "answers": {}}
        doc["answers"]["deliverable"] = requested
        prov = doc.get(_td.PROVENANCE_KEY)
        if not isinstance(prov, dict):
            prov = {}
            doc[_td.PROVENANCE_KEY] = prov
        prov["deliverable"] = {
            "answered_by": _td.ANSWERED_BY_OWNER_VALUE,
            "citation": f"operator --route {route} on {date.today().isoformat()}",
        }
        try:
            _aa.write_json(raw_path, doc)
        except OSError as exc:
            return f"{raw_rel}: could not record the operator's route: {exc}"
        return None

    rel = raw_rel if raw_path.exists() else _td.DECLARATION_REL
    if rel == _td.DECLARATION_REL and not declaration.exists():
        return _disclose_undeclared(
            f"{raw_rel}: no owner-attested DIE or HARDMACRO answer", {})
    staged, _ = _td.load(project / rel)
    try:
        _td.read_owner_delivery(project, rel)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return _disclose_undeclared(str(exc), staged)
    return None


def refusal_message(reason: str) -> str:
    if reason.startswith("FLOW109_"):
        return "REFUSED: " + reason
    return ("REFUSED: DELIVERY_ROUTE_UNDECLARED: IC path or IP path? "
            f"{reason}. Fill {_st.DESIGN_ANSWERS_REL} fields "
            "answers.deliverable (DIE or HARDMACRO) and "
            "answer_provenance.deliverable (answered_by: owner, citation: "
            "the prompt sentence or the person's reply), or pass --route ic|ip.")


def report_label(project: Path, *, allow_rtl_scope: bool = True) -> dict:
    """Label the current RTL invocation or the owner's physical deliverable."""
    if allow_rtl_scope:
        import flow109
        scope = flow109.active_rtl_scope(project)
        if scope is not None:
            return {"delivery_route": "RTL", "deliverable": "RTL",
                    "delivery_scope": scope}
    rel = (_st.DESIGN_ANSWERS_REL if (project / _st.DESIGN_ANSWERS_REL).exists()
           else _td.DECLARATION_REL)
    _, delivery = _td.read_owner_delivery(project, rel)
    return {"delivery_route": "IC" if delivery == _td.DELIVERABLE_DIE else "IP",
            "deliverable": delivery}
