#!/usr/bin/env python3
"""
l24_signoff_evidence_backed_check.py — batch-8 / layergate-8 (L24_SIGNOFF)

WHAT THIS GATE ENFORCES
=======================
L24_SIGNOFF models per-gate sign-off status (drc / lvs / sta / antenna /
ir_drop) plus a tapeout-gate checklist.

The consumer contract, stated honestly:

    L24 HAS NO CONSUMER TODAY. The statuses it models are produced by phase-3
    programs (signoff_ladder_run.py, tapeout_checklist, dft_signoff_check.py)
    which write their OWN reports and never read — or write back to — L24.
    In 24/24 sampled real Phase-1 runs the layer is 100% inert:
    extraction_status=NOT_YET_EXTRACTED, every status null, tapeout_gates [].

So this gate does NOT demand that L24 be filled in. Demanding content for a
layer nobody reads would be exactly the "token appears somewhere" mistake in
reverse: manufacturing work that no consumer needs.

What it enforces is the HAZARD that arrives the instant a consumer IS added:

    A Phase-1-asserted drc_status='PASS' with no evidence path is the
    false-certificate shape. It is the same failure family as the defect that
    motivated this batch — a completeness check that said CAPTURED because a
    token appeared in some layer, while the layer the backend actually
    consumed had it 0 times, and the whole detailed route aborted five steps
    downstream behind an opaque router error.

THE RULE
--------
    A sign-off status is complete when it is DERIVED from an evidence path —
    a report file that exists inside this project, plus the value that was
    read out of it — never when it is an asserted string.

Concretely, for every verdict L24 asserts:
  (1) it must be bound to an evidence record naming a PATH,
  (2) that path must resolve to a file INSIDE the project (evidence outside
      the run is not reproducible evidence),
  (3) the record must name the VALUE that was read back ("I looked at the
      report" is not evidence of WHAT was read), and
  (4) that value must still be findable in that file.

Claims are discovered from the layer's OWN key names (any ``*_status`` /
``status`` / ``verdict`` / ``result`` key, at any depth, including inside
``tapeout_gates[]``). Nothing about any design, PDK, vendor or signal is
hardcoded — this gate has never seen the design it is checking.

Only the ABSENCE of information is enumerated (null, TBD, PENDING,
NOT_YET_EXTRACTED, ...). Everything else counts as a CLAIM. That direction is
deliberate: a whitelist of positive verdicts would let a novel verdict word
through silently, which is the exact class of hole this gate exists to close.

BLOCKS OR ADVISES?
------------------
**BLOCKS** (exit 1 is a hard FAIL; it is NOT listed in
flow_compliance_check.INFORMATIONAL_GATES).

Why blocking is the right call even though L24 has no consumer:
  * The gate can only fire when the layer ASSERTS a sign-off verdict. On the
    inert layer every real run emits today, it exits 2 (SKIP) and costs
    nothing — 24/24 sampled runs SKIP, zero false positives.
  * The only way to make it fail is to publish an unevidenced certificate.
    There is no legitimate reason for Phase 1 — which runs before DRC, LVS
    and STA exist — to certify their outcome. A gate that merely *advised*
    here would repeat compounding failure (b) from the motivating defect: the
    verdict was FAIL and the flow continued anyway.
  * It forecloses the hazard the day a consumer is wired in, instead of
    discovering it five steps downstream like last time.

NO WAIVER (governance-hard). A waiver here would read "let me certify
sign-off without evidence", which is the thing being prevented.

Usage:
    python3 l24_signoff_evidence_backed_check.py <project_dir>

Exit codes:
    0 = PASS  — every asserted verdict traces to a verified evidence read-back
    1 = FAIL  — at least one verdict is asserted without verifiable evidence
    2 = SKIP  — no L24 present, L24 is an N/A stub, or the layer asserts
                nothing (today's real-run state)
"""
from __future__ import annotations

import sys
import json
import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _signoff_drc_format as _sdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from l_doc_evidence_util import (  # noqa: E402
    EvidenceVerdict,
    find_layer_files,
    is_no_information,
    is_populated,
    load_json,
    verify_evidence_binding,
)

_STEM = "L24_SIGNOFF"

# A key carries a sign-off VERDICT when its own name says so. Derived from the
# layer's key names — chip/PDK/vendor-agnostic.
_VERDICT_KEY_SUFFIXES = ("_status", "_verdict", "_result", "_signoff",
                         "_sign_off", "_state")
_VERDICT_KEY_EXACT = ("status", "verdict", "result", "signoff", "sign_off",
                      "outcome", "disposition")

# Keys that are metadata ABOUT the extraction, not sign-off verdicts. Without
# this, `extraction_status: "NOT_YET_EXTRACTED"` would be read as a claim.
_META_KEY_EXACT = ("extraction_status", "applicability", "doc_id", "doc_name",
                   "ic_class", "emitted_by", "schema_version")


def _is_verdict_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    k = key.strip().lower()
    if k in _META_KEY_EXACT:
        return False
    if k in _VERDICT_KEY_EXACT:
        return True
    return any(k.endswith(suf) for suf in _VERDICT_KEY_SUFFIXES)


def _subject_of(key: str, scope: Dict[str, Any]) -> str:
    """The claim's own base name, used to BIND evidence to THIS verdict.

    ``drc_status`` → ``drc``. A bare ``status`` inside a checklist entry takes
    its subject from the entry's own name/id/gate field, so per-gate rows in
    ``tapeout_gates[]`` each demand their own evidence rather than sharing one.
    """
    k = key.strip().lower()
    for suf in _VERDICT_KEY_SUFFIXES:
        if k.endswith(suf):
            base = k[: -len(suf)].strip("_")
            if base:
                return base
    if k in _VERDICT_KEY_EXACT and isinstance(scope, dict):
        for name_key in ("name", "id", "gate", "check", "gate_name", "label"):
            v = scope.get(name_key)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    return k


# Containers that HOLD evidence rather than assert verdicts. Walking into
# them would let an evidence record's own "status"-ish key be misread as a
# claim, and would make the gate fail on its own proof.
_EVIDENCE_CONTAINER_KEYS = frozenset({
    "extraction_evidence", "evidence", "evidence_paths", "extraction_hints",
    "extraction_strategy",
})


def _collect_claims(node: Any,
                    out: List[Tuple[str, str, Any, Dict[str, Any]]],
                    path: str = "") -> None:
    """Walk the layer and collect every asserted verdict.

    Appends ``(json_path, subject, value, enclosing_dict)``.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            child_path = f"{path}.{k}" if path else str(k)
            if isinstance(k, str) and k.strip().lower() in \
                    _EVIDENCE_CONTAINER_KEYS:
                continue
            if _is_verdict_key(k):
                if not isinstance(v, (dict, list)):
                    if is_populated(v):
                        out.append(
                            (child_path, _subject_of(str(k), node), v, node))
                    continue
                if isinstance(v, dict):
                    # Nested verdict map: {"status": {"drc": "PASS", ...}}.
                    # Each sub-key names its own subject.
                    for sub_k, sub_v in v.items():
                        sub_path = f"{child_path}.{sub_k}"
                        if isinstance(sub_v, (dict, list)):
                            _collect_claims(sub_v, out, sub_path)
                        elif is_populated(sub_v):
                            out.append(
                                (sub_path, str(sub_k).strip().lower(), sub_v, v))
                    continue
            _collect_claims(v, out, child_path)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _collect_claims(item, out, f"{path}[{i}]")


def _check_one(project: Path, layer_path: Path,
               rows_out: Optional[List[Dict[str, Any]]] = None
               ) -> Tuple[str, List[str]]:
    """Returns (verdict, messages) with verdict in {PASS, FAIL, SKIP}."""
    rel = layer_path.relative_to(project) if layer_path.is_relative_to(project) \
        else layer_path
    doc = load_json(layer_path)
    if not isinstance(doc, dict):
        return "SKIP", [f"{rel}: unreadable / non-object JSON"]

    applicability = str(doc.get("applicability", "") or "").strip().upper()
    if applicability in ("N/A", "NA", "NOT_APPLICABLE", "NOT APPLICABLE"):
        # An honest N/A stub must still say WHY — a silent-empty doc is
        # indistinguishable from a failed extraction.
        if is_no_information(doc.get("rationale")):
            return "FAIL", [
                f"{rel}: applicability=N/A with no `rationale` — a silent-empty "
                f"layer is indistinguishable from a failed extraction"]
        return "SKIP", [f"{rel}: N/A stub with rationale"]

    claims: List[Tuple[str, str, Any, Dict[str, Any]]] = []
    _collect_claims(doc, claims)

    # ── R-0915-38: the layer now carries what the INPUT REQUIRES ───────────
    # Phase 1 extracts L24's sign-off requirements from the design's own
    # documents (`l24_signoff_requirements_extract`), so this gate has a
    # second, earlier question to answer than the false-certificate one: for
    # every requirement the input STATES, did this run actually measure it?
    #
    # That question is about the RUN's reports, not about L24's own fields —
    # the requirement rows deliberately carry no `*_status` key, so they are
    # not claims and cannot be certificates. A requirement the run's reports
    # satisfy is BACKED; one they do not is named, and that is a real finding:
    # the design said DRC must be clean and the run has no clean DRC report.
    req_failures, req_msgs = _requirements_backed(project, doc, rel, rows_out)
    if req_failures:
        return "FAIL", req_failures

    if not claims:
        if req_msgs:
            return "PASS", req_msgs
        return "SKIP", [
            f"{rel}: layer asserts no sign-off verdict "
            f"(extraction_status={doc.get('extraction_status')!r}) — nothing "
            f"to certify, nothing to falsify"]

    msgs: List[str] = []
    failures: List[str] = []

    # Contradiction guard: a layer that says it extracted nothing cannot also
    # publish a certificate. This is the shape the motivating defect wore —
    # a verdict emitted by a track that contributed nothing.
    extraction_status = str(doc.get("extraction_status", "") or "").strip().upper()
    if extraction_status in ("NOT_YET_EXTRACTED", "NOT_EXTRACTED", "PENDING"):
        failures.append(
            f"{rel}: extraction_status={extraction_status} but the layer "
            f"asserts {len(claims)} sign-off verdict(s) "
            f"({', '.join(c[0] for c in claims[:4])}) — a layer that extracted "
            f"nothing cannot certify anything")

    for (json_path, subject, value, scope) in claims:
        v = verify_evidence_binding(project, doc, subject, scope)
        if v.ok:
            msgs.append(f"{rel}:{json_path}={value!r} — {v.detail}")
            continue
        if v.status == EvidenceVerdict.NO_EVIDENCE:
            why = (f"asserted verdict {value!r} with NO evidence path — this "
                   f"is the false-certificate shape")
        elif v.status == EvidenceVerdict.PATH_UNRESOLVED:
            why = v.detail
        elif v.status == EvidenceVerdict.NO_READBACK_VALUE:
            why = v.detail
        else:
            why = v.detail
        # Name the SUBJECT as well as the json path: on a checklist row the
        # path (`fields.tapeout_gates[3].status`) does not say which gate is
        # unevidenced, and an operator cannot act on an index.
        failures.append(f"{rel}:{json_path} (subject '{subject}') — {why}")

    if failures:
        return "FAIL", failures
    return "PASS", req_msgs + msgs


#: A verdict that is NOT a measurement of the design. `vacuous_pass` and
#: `inconclusive` are in here deliberately: a gate that examined nothing and
#: returned green has not measured DRC, and crediting it would back a required
#: check with an empty denominator — the exact shape this repo already refuses
#: elsewhere (`gate_zero_denominator_refuses_check`).
_ABSENT_VERDICTS = frozenset({
    "", "none", "null", "tbd", "pending", "not_yet_extracted", "unknown",
    "not_measured", "not_checked", "n/a", "na", "skip", "skipped",
    "vacuous", "vacuous_pass", "inconclusive", "advisory_screen_only",
    "not_applicable", "not_run", "deferred",
})
_FAILING_VERDICTS = frozenset({
    "fail", "failed", "failing", "error", "violation", "violations",
    "not_clean", "dirty", "not_met", "unmet", "false",
})


def _report_verdict_of(payload: Any) -> Optional[str]:
    """One report's verdict, however that report spells it.

    MEASURED across a real run tree: `drc_signoff.json` carries `passed: true`
    with no verdict string at all, `lvs_verdict.json` carries `status` AND
    `result` = "PASS", and `em.json` carries `verdict: "MEASURED"`. A reader
    that knew only one spelling would call two of the three unmeasured.
    """
    if not isinstance(payload, dict):
        return None
    for key in ("verdict", "status", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    passed = payload.get("passed")
    if isinstance(passed, bool):
        return "pass" if passed else "fail"
    return None


def _report_engine(path: str, payload: Any, project: Path) -> Optional[str]:
    """Identify a DRC engine from the audit's native producer provenance.

    A filename or free-form ``engine`` label is operator-controlled metadata.
    The only admissible identity is the producer classification emitted by
    ``eda_report_audit:drc`` plus a digest check over its subject files.
    """
    if not isinstance(payload, dict) or payload.get("program") != "eda_report_audit:drc":
        return None
    summary = payload.get("summary")
    producers = summary.get("producers") if isinstance(summary, dict) else None
    if not isinstance(producers, list) or len(producers) != 1:
        return None
    producer = producers[0]
    if not isinstance(producer, dict) or producer.get("is_signoff_deck") is not True:
        return None
    engine = producer.get("producer")
    if engine not in {"magic", "klayout"}:
        return None
    if not isinstance(producer.get("file"), str) or not producer["file"]:
        return None
    subject = payload.get("subject")
    if not isinstance(subject, dict) or subject.get("basis") != "content":
        return None
    items = subject.get("items")
    if not isinstance(items, list) or len(items) != 1:
        return None
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return None
        rel = Path(item["path"])
        if rel in seen:
            return None
        seen.add(rel)
        path_obj = (project / rel).resolve()
        if not path_obj.is_relative_to(project.resolve()) or not path_obj.is_file():
            return None
        expected = item.get("sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            return None
        digest = hashlib.sha256(path_obj.read_bytes()).hexdigest()
        if digest != expected:
            return None
        native = _sdf.classify_file(path_obj)
        if native.kind != engine or not native.is_signoff_deck:
            return None
        if engine == "klayout" and producer.get("deck") != native.deck:
            return None
    return engine


def _report_engine_for_path(project: Path, path: str) -> Optional[str]:
    """Read an already selected report to preserve a typed engine field."""
    try:
        payload = json.loads((project / path).read_text(errors="replace"))
    except (OSError, ValueError):
        payload = None
    return _report_engine(path, payload, project)


#: How a requirement's population was chosen. Carried into the gate's own
#: `--json` record so a reader can tell a flow-DECLARED sign-off reading from
#: the name scan that is still all some checks have.
_BASIS_DECLARED = "flow-declared-signoff-record"
_BASIS_SCAN = "report-name-scan"


def _declared_signoff_population(project: Path, check: str
                                 ) -> Optional[Tuple[Tuple[str, ...],
                                                     List[Tuple[str, Optional[str]]]]]:
    """(declared paths, [(path, verdict)]) when the FLOW declares a record.

    R-0915-52. A stated sign-off requirement is judged by the record the flow
    declares for that check — the step that publishes the sign-off verdict —
    and by nothing else. A pre-layout ESTIMATE published by an earlier step is
    not a sign-off reading of the same check, and neither is a different
    check's envelope that happens to carry the token in its filename.

    Returns None when the flow declares no sign-off record for this check, and
    the caller falls back to the name scan below. A declared record that is
    ABSENT from the run is reported as absent, NOT backfilled from the scan:
    the whole point is that the estimate does not stand in for the sign-off.
    """
    try:
        from l24_signoff_requirements_extract import signoff_record_paths_for
    except ImportError:
        return None
    declared = signoff_record_paths_for(check)
    if not declared:
        return None
    out: List[Tuple[str, Optional[str]]] = []
    for rel in declared:
        path = project / rel
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        out.append((rel, _report_verdict_of(payload)))
    return declared, out


def _reports_for_check(project: Path, check: str
                       ) -> List[Tuple[str, Optional[str]]]:
    """(project-relative path, verdict) for every report naming this check."""
    try:
        from l24_signoff_requirements_extract import report_tokens_for
    except ImportError:
        return []
    tokens = report_tokens_for(check)
    if not tokens:
        return []
    patterns = [re.compile(r"(?<![a-z0-9])" + re.escape(tok) + r"(?![a-z0-9])")
                for tok in tokens]
    reports = project / "reports"
    if not reports.is_dir():
        return []
    out: List[Tuple[str, Optional[str]]] = []
    for path in sorted(reports.rglob("*.json")):
        # `reports/audit/` is the audit's own bookkeeping, not a measurement
        # of the design; a requirement backed by the audit that is judging it
        # would be circular.
        try:
            relative = path.relative_to(project)
        except ValueError:
            continue
        if relative.parts[:2] == ("reports", "audit"):
            continue
        try:
            payload = json.loads(path.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        haystack = path.stem.lower()
        if isinstance(payload, dict):
            for key in ("program", "gate", "subject", "check"):
                value = payload.get(key)
                if isinstance(value, str):
                    haystack += " " + value.lower()
        if not any(p.search(haystack) for p in patterns):
            continue
        out.append((relative.as_posix(), _report_verdict_of(payload)))
    return out


def _phase3_has_run(project: Path) -> bool:
    """Has this run reached the phase that MEASURES sign-off?

    MEASURED, and this function exists because its absence deadlocked a run:
    the phase-2 strict-structural audit invokes this gate, so a requirements
    arm that failed on "no DRC report" failed at a point in the flow where DRC
    CANNOT have run. The run then halted in phase 2 and phase 3 never
    executed, so the evidence the gate demanded could never appear — the gate
    made its own premise unsatisfiable.

    A requirement is UNMET only if the run completed the phase that would have
    measured it. Before that it is simply not yet measurable, and saying so is
    not the same as saying it was missed.
    """
    if (project / "reports" / "orchestrator" / "phase3_one_shot.json").is_file():
        return True
    d = project / "reports" / "phase3"
    return d.is_dir() and any(d.rglob("*.json"))


def _required_sta_corners(project: Path, required: Any,
                          declared_paths: Tuple[str, ...]) -> Dict[str, Any]:
    """Bind explicit L24 process obligations to the declared audit's native bytes.

    Aggregate PASS/counts and unrelated discovered reports cannot supply a
    missing corner. This checks native setup/hold readings, not library or
    netlist correctness, which retain their separate owning gates.
    """
    import math
    import _audit_receipt as receipt
    import _sta_basis as basis
    import sta_corner_record_completeness_check as native
    out: Dict[str, Any] = {"required": required, "covered": [], "issues": [],
                           "native_records": []}
    issues = out["issues"]
    if (not isinstance(required, list) or not required
            or any(not isinstance(c, str) or c not in {"SS", "TT", "FF", "SF", "FS"}
                   for c in required)):
        issues.append("required process corners are malformed or unknown")
        return out
    roles: Dict[str, set] = {c: set() for c in required}
    # Other flow-declared STA gates publish their own schemas (corner record,
    # architectural residual, RC sweep). Only this audit owns subject.items.
    audit_rel = "reports/phase3/sta/post_route_summary.json"
    if audit_rel not in declared_paths:
        issues.append("no flow-declared canonical STA audit to bind corner evidence")
    for rel in (p for p in declared_paths if p == audit_rel):
        try:
            report_path = (project / rel).resolve()
            if not report_path.is_relative_to(project.resolve()):
                raise ValueError("audit path escapes project")
            payload = json.loads(report_path.read_text())
            if payload.get("program") != "eda_report_audit:sta" or payload.get("passed") is not True:
                raise ValueError("not the passing canonical STA audit producer")
            subject = payload.get("subject")
            if not isinstance(subject, dict) or subject.get("basis") != "content":
                raise ValueError("native content binding absent")
            items = subject.get("items")
            if not isinstance(items, list) or not items:
                raise ValueError("empty native subject")
            paths = []
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    raise ValueError("malformed native subject item")
                path = (project / item["path"]).resolve()
                if not path.is_relative_to(project.resolve()) or not path.is_file():
                    raise ValueError("native path missing or outside project")
                paths.append(path)
            actual = receipt.subject_of(paths, relative_to=project)
            if any(subject.get(k) != actual[k] for k in ("basis", "items", "sha256")):
                raise ValueError("native subject content or identity changed")
            for path in paths:
                text = path.read_text()
                sections = native._split_sections(text)
                if not sections:
                    labels = re.findall(r"(?m)^\s*STA_SIGNOFF_CORNER:\s*(\S+)", text)
                    sections = [("BOTH", labels[0] if len(set(labels)) == 1 else None, text)]
                for kind, corner, body in sections:
                    if corner not in roles:
                        continue
                    stamps = basis.STAMP_RE.findall(body)
                    if not stamps or any(basis.normalise_basis(v) != "POST_ROUTE" for v in stamps):
                        issues.append(f"{path.name}:{corner} lacks unambiguous POST_ROUTE basis")
                        continue
                    for marker in ("STA_BASIS_LIBERTY", "STA_BASIS_SPEF"):
                        values = re.findall(r"(?m)^\s*" + marker + r":\s*(\S+)", body)
                        if len(set(values)) != 1:
                            issues.append(f"{path.name}:{corner} lacks unambiguous {marker}")
                    if re.search(r"(?im)^\s*(?:worst slack|wns|tns).*\b(?:nan|[-+]?inf(?:inity)?)\b", body):
                        issues.append(f"{path.name}:{corner} contains a non-finite timing reading")
                    vals = native.extract_slacks(body)
                    if vals.get("tns_ns") is not None and (not math.isfinite(vals["tns_ns"]) or vals["tns_ns"] < 0):
                        issues.append(f"{path.name}:{corner} has failing total negative slack")
                    record = {"path": str(path.relative_to(project.resolve())),
                              "corner": corner, "role": kind, "slacks": vals}
                    out["native_records"].append(record)
                    for role, key in (("SETUP", "setup_wns_ns"), ("HOLD", "hold_wns_ns")):
                        if kind not in (role, "BOTH"):
                            continue
                        value = vals.get(key)
                        if value is None or not math.isfinite(value) or value < 0:
                            issues.append(f"{path.name}:{corner}:{role} has no finite met slack")
                        else:
                            roles[corner].add(role)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            issues.append(f"{rel}: {exc}")
    out["covered"] = sorted(c for c, found in roles.items() if found == {"SETUP", "HOLD"})
    out["missing"] = sorted(set(required) - set(out["covered"]))
    if out["missing"]:
        issues.append("required corners lack setup/hold evidence: " + ", ".join(out["missing"]))
    return out


def _requirements_backed(project: Path, doc: Any, rel: str,
                         rows_out: Optional[List[Dict[str, Any]]] = None
                         ) -> Tuple[List[str], List[str]]:
    """Judge each STATED sign-off requirement against the run's own reports.

    `rows_out`, when given, collects one typed record per stated requirement —
    the check, the BASIS its population was chosen on, every record read with
    the verdict read from it, and the outcome. That is what this gate's
    `--json` publishes, so a consumer can separate a MEASUREMENT from a
    failure to read an input without parsing the prose.
    """
    fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    rows = fields.get("signoff_requirements") if isinstance(fields, dict)         else None
    if rows_out is None:
        rows_out = []
    if not isinstance(rows, list) or not rows:
        return [], []
    failures: List[str] = []
    msgs: List[str] = []
    phase3 = _phase3_has_run(project)
    for row in rows:
        if not isinstance(row, dict) or not row.get("stated"):
            continue
        check = str(row.get("check") or "?")
        requirement = row.get("requirement")
        cite = row.get("citation") or {}
        where = (f"{cite.get('document')}:{cite.get('line')}"
                 if cite.get("document") else "the input")
        # R-0915-52: the flow's DECLARED sign-off record decides the
        # population where the flow declares one; the name scan answers for
        # every check it does not.
        declared_pair = _declared_signoff_population(project, check)
        if declared_pair is not None:
            declared_paths, found = declared_pair
            basis = _BASIS_DECLARED
            where_looked = (f"the flow's declared sign-off record for {check}"
                            f": {', '.join(declared_paths)}")
        else:
            declared_paths = ()
            found = _reports_for_check(project, check)
            basis = _BASIS_SCAN
            where_looked = (f"searched reports/ excluding reports/audit for "
                            f"{'/'.join(_signoff_tokens(check))}")
        measured = [(p, v) for p, v in found
                    if v is not None and v not in _ABSENT_VERDICTS]
        record: Dict[str, Any] = {
            "check": check,
            "requirement": requirement,
            "citation": where,
            "basis": basis,
            "declared_records": list(declared_paths),
            "records_read": [{"path": p, "verdict": v} for p, v in found],
        }
        rows_out.append(record)
        if not measured:
            looked = ", ".join(p for p, _ in found[:4]) or "no report"
            if not phase3:
                # NOT YET MEASURABLE, not missed. The requirement is recorded
                # and named so it is visible, but this run has not reached the
                # phase that measures it and the gate does not block on it.
                record["outcome"] = "NOT_YET_MEASURABLE"
                msgs.append(
                    f"{rel}: {check} "
                    f"{requirement or '(prose)'} required at {where} — "
                    f"recorded; this run has not reached phase 3, so it is "
                    f"not yet measurable")
                continue
            record["outcome"] = "UNMET_NO_READING"
            failures.append(
                f"{rel}: the input REQUIRES {check} "
                f"{requirement or '(requirement stated in prose)'} at {where}, "
                f"and this run has no report measuring it "
                f"({where_looked}; found: {looked})")
            continue
        failed = [(p, v) for p, v in measured if v in _FAILING_VERDICTS]
        if failed:
            record["outcome"] = "UNMET_MEASURED_FAILING"
            failures.append(
                f"{rel}: the input REQUIRES {check} "
                f"{requirement or '(requirement stated in prose)'} at {where}, "
                f"and this run measured it as "
                + ", ".join(f"{v!r} in {p}" for p, v in failed[:3]))
            continue
        required_engines = row.get("engines")
        if check == "DRC" and isinstance(required_engines, list) and required_engines:
            engine_records: Dict[str, List[Tuple[str, Optional[str]]]] = {
                str(engine).lower(): [] for engine in required_engines
            }
            for path, verdict in found:
                engine = _report_engine_for_path(project, path)
                if engine in engine_records:
                    engine_records[engine].append((path, verdict))
            missing_engines = sorted(engine for engine, records in engine_records.items()
                                     if not any(verdict not in _ABSENT_VERDICTS
                                                and verdict is not None
                                                for _path, verdict in records))
            failing_engines = sorted(engine for engine, records in engine_records.items()
                                     if any(verdict in _FAILING_VERDICTS
                                            for _path, verdict in records))
            if missing_engines or failing_engines:
                record["outcome"] = "UNMET_ENGINE_EVIDENCE"
                detail = []
                if missing_engines:
                    detail.append("missing " + ", ".join(missing_engines))
                if failing_engines:
                    detail.append("failing " + ", ".join(failing_engines))
                failures.append(
                    f"{rel}: the input REQUIRES DRC engines "
                    f"{sorted(engine_records)} at {where}, but "
                    + "; ".join(detail))
                continue
        required_corners = row.get("corners")
        if check == "STA" and required_corners not in (None, []):
            coverage = _required_sta_corners(project, required_corners, declared_paths)
            record["corner_coverage"] = coverage
            if coverage["issues"]:
                record["outcome"] = "UNMET_CORNER_EVIDENCE"
                failures.append(
                    f"{rel}: the input REQUIRES STA corners {required_corners!r} "
                    f"at {where}, but " + "; ".join(coverage["issues"]))
                continue
        record["outcome"] = "BACKED"
        msgs.append(
            f"{rel}: {check} {requirement or '(prose)'} required at {where} — "
            f"backed by " + ", ".join(f"{p} ({v})" for p, v in measured[:3]))
    return failures, msgs


def _signoff_tokens(check: str) -> Tuple[str, ...]:
    try:
        from l24_signoff_requirements_extract import report_tokens_for
    except ImportError:
        return ()
    return report_tokens_for(check) or ()


# ── R-0915-52: the gate STATES its own reason class ───────────────────────
#
# The completion audit's `classify_sub_gate` says of a FAIL record: "the
# record carries a FAIL verdict and no field that separates a measurement
# from a failure to read its input". That is true of this gate today, and it
# is the reason a real finding and an unreadable project look identical to a
# reader of the record.
#
# The field that separates them is `reason_class`, from the repo's own closed
# vocabulary in `_flow_reason_taxonomy`. It is written ONLY when this gate
# produced no measurement of the design, and is `null` on every verdict that
# IS one — including a FAIL, because a requirement measured and found unmet is
# a measurement, not a reason to excuse the step. A class on a measured verdict
# would be the false-disclosure shape in the other direction.
_GATE_NAME = "l24_signoff_evidence_backed_check"


def _emit_json(dest: Optional[str], payload: Dict[str, Any]) -> None:
    """Write the gate's own record, or do nothing when no `--json` is given."""
    if not dest:
        return
    out = Path(dest)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from _atomic_artefact import write_text as _atomic_write  # noqa: PLC0415
    except ImportError:
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False)
                       + "\n", encoding="utf-8")
        return
    _atomic_write(out, json.dumps(payload, indent=2, ensure_ascii=False)
                  + "\n")


def main(argv: List[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    json_dest: Optional[str] = None
    rest = argv[1:]
    for i, a in enumerate(rest):
        if a == "--json" and i + 1 < len(rest):
            json_dest = rest[i + 1]
        elif a.startswith("--json="):
            json_dest = a.partition("=")[2]
    # `--json <path>` consumes its value, which is not a positional.
    if json_dest is not None and json_dest in args:
        args.remove(json_dest)
    if not args:
        print("usage: l24_signoff_evidence_backed_check <project_dir> "
              "[--json <out>]", file=sys.stderr)
        return 2
    project = Path(args[0]).resolve()
    record: Dict[str, Any] = {"gate": _GATE_NAME, "project": str(project),
                              "requirements": []}
    if not project.is_dir():
        # The gate could not READ its input. This is the case the audit says
        # a FAIL record cannot be told apart from — so it is named.
        record.update(verdict="SKIP", reason_class="EXECUTION_ERROR",
                      reason=f"{project} is not a directory")
        _emit_json(json_dest, record)
        print(f"[SKIP] l24_signoff_evidence_backed_check: "
              f"{project} is not a directory")
        return 2

    layers = find_layer_files(project, _STEM)
    if not layers:
        # Phase 1's post-process is the sole writer of this layer, and it has
        # not run. ASKED_BEFORE_PRODUCER is exactly that shape.
        record.update(verdict="SKIP", reason_class="ASKED_BEFORE_PRODUCER",
                      reason=f"no {_STEM}.json under {project}; phase-1 "
                             f"post-process has not emitted the layer")
        _emit_json(json_dest, record)
        print(f"[SKIP] l24_signoff_evidence_backed_check: no {_STEM}.json "
              f"under {project}")
        return 2

    all_fail: List[str] = []
    all_pass: List[str] = []
    rows: List[Dict[str, Any]] = []
    n_skip = 0
    for layer in layers:
        verdict, msgs = _check_one(project, layer, rows)
        if verdict == "FAIL":
            all_fail.extend(msgs)
        elif verdict == "PASS":
            all_pass.extend(msgs)
        else:
            n_skip += 1
    record["requirements"] = rows

    if all_fail:
        # The two failure families read very differently to an operator, so
        # the headline says which one this is rather than calling an unmet
        # REQUIREMENT an unevidenced ASSERTION.
        unmet = [m for m in all_fail if "the input REQUIRES" in m]
        if unmet and len(unmet) == len(all_fail):
            print(f"[FAIL] l24_signoff_evidence_backed_check: "
                  f"{len(unmet)} sign-off requirement(s) the design's own "
                  f"input STATES are not measured by this run.")
        else:
            print(f"[FAIL] l24_signoff_evidence_backed_check: "
                  f"{len(all_fail)} unevidenced sign-off assertion(s). A "
                  f"Phase-1 sign-off verdict must be DERIVED from a report "
                  f"path + the value read from it, never asserted.")
        for m in all_fail[:12]:
            print(f"  - {m}")
        if len(all_fail) > 12:
            print(f"  ... {len(all_fail) - 12} more")
        # A FAIL here is a MEASUREMENT: the gate read the layer and the run's
        # own reports and found a stated requirement unmet, or a verdict
        # asserted with no evidence. `reason_class` stays null, which is what
        # makes it distinguishable from the two SKIPs above.
        record.update(verdict="FAIL", reason_class=None,
                      findings=list(all_fail))
        _emit_json(json_dest, record)
        return 1

    if all_pass:
        # Same distinction on the green side: R-0915-38 makes most PASSes a
        # statement about REQUIREMENTS met by the run's reports, not about
        # phase-1 verdicts tracing to evidence. Saying the latter when the
        # layer asserted no verdict at all would be a false description of
        # what was checked.
        requirement_rows = [m for m in all_pass if " required at " in m]
        pending = [m for m in requirement_rows
                   if "not yet measurable" in m]
        backed = [m for m in requirement_rows if m not in pending]
        if requirement_rows and len(requirement_rows) == len(all_pass):
            if not backed:
                print(f"[PASS] l24_signoff_evidence_backed_check: "
                      f"{len(pending)} sign-off requirement(s) extracted from "
                      f"the design's own input and recorded; this run has not "
                      f"reached phase 3, so none is measurable yet")
            elif pending:
                print(f"[PASS] l24_signoff_evidence_backed_check: "
                      f"{len(backed)} of {len(requirement_rows)} sign-off "
                      f"requirement(s) stated by the design's own input are "
                      f"measured by a report in this run; "
                      f"{len(pending)} not yet measurable")
            else:
                print(f"[PASS] l24_signoff_evidence_backed_check: "
                      f"{len(backed)} sign-off requirement(s) stated by the "
                      f"design's own input are each measured by a report in "
                      f"this run")
        else:
            print(f"[PASS] l24_signoff_evidence_backed_check: "
                  f"{len(all_pass)} sign-off verdict(s) each trace to a "
                  f"resolvable evidence path with a verified read-back value")
        for m in all_pass[:6]:
            print(f"  - {m}")
        # A PASS whose every requirement row is NOT_YET_MEASURABLE measured
        # nothing about the design — the question was asked before the phase
        # that answers it. That is the one green here that carries a class.
        stated = [r for r in rows if r.get("outcome")]
        pending_only = bool(stated) and all(
            r["outcome"] == "NOT_YET_MEASURABLE" for r in stated)
        record.update(
            verdict="PASS",
            reason_class="ASKED_BEFORE_PRODUCER" if pending_only else None,
            reason=("every stated sign-off requirement is recorded but this "
                    "run has not reached the phase that measures it")
                   if pending_only else None,
            findings=[])
        _emit_json(json_dest, record)
        return 0

    record.update(
        verdict="SKIP", reason_class="DESIGN_DECLARED_NA",
        reason=(f"{n_skip}/{len(layers)} {_STEM} layer(s) assert no sign-off "
                f"verdict and the input states no sign-off requirement — "
                f"nothing to certify"))
    _emit_json(json_dest, record)
    print(f"[SKIP] l24_signoff_evidence_backed_check: "
          f"{n_skip}/{len(layers)} {_STEM} layer(s) assert no sign-off verdict "
          f"(inert / N/A) — nothing to certify")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
