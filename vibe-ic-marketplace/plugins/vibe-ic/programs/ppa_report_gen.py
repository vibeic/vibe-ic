#!/usr/bin/env python3
"""The human report, and the claims file that makes every sentence in it checkable.

Spec §18 (Human Report Specification), §18.1 (claim language rules).
Interface contract: `docs/PPA_INTERFACES.md` §1 (exit codes), §2 (the canonical
metric record), §3 (identity), §5 (schema conventions).

WHY A REPORT GENERATOR IS A GATE AND NOT A FORMATTER
====================================================
A PPA report is the last place a number is touched before a human believes it.
Everything upstream — extraction, feasibility, Pareto — can be perfectly honest
and still be published as a lie, because the report is where a measurement
becomes a SENTENCE, and a sentence carries implications an artefact does not.

So this program does two things that a formatter would not:

  * it REFUSES (rc=1) a metric record that cannot support the sentence it would
    become, rather than printing it prettily. A record carrying `status:
    NOT_MEASURED` and a `value` is not a formatting problem;

  * it emits `claims.json`, in which every sentence a reader will believe is
    bound by id to the artefact path and hash that supports it. Prose is
    unrunnable; `claims.json` is what `ppa_page_claim_check.py` runs.

THE ROW THAT MUST NEVER BE OMITTED
==================================
`NOT_MEASURED`. A report that drops what it could not measure reads as complete
coverage, and it reads that way to the author too. Every metric this program was
given appears in the output — measured, not measured, not applicable or invalid
— and the not-measured rows carry a REASON where a value would have been.

There are no numeric sentinels. `0`, `-1` and `""` never mean "not measured"
here (PPA_INTERFACES.md §2), because a sentinel is a number and numbers get
compared. A record that uses one is refused for using one.

"I COULD NOT READ IT" AND "I READ IT AND IT WAS EMPTY" ARE DIFFERENT ANSWERS
===========================================================================
Both would print zero rows and both would exit non-zero if this collapsed them,
and the collapse is what makes a report of nothing look like a report. They are
separate codes here, both rc=2 and both marked:

    [CANNOT CHECK] NO_INPUT       the path is not there / cannot be read
    [CANNOT CHECK] EMPTY_CORPUS   the path is there and carries no record;
                                  the zero is STATED, with the path it counted

NO COLLAPSED SCALAR REACHES THE PAGE
====================================
Area, timing and power trade against each other, so any single weighted figure
is a proxy for the property and not the property — and it is the figure that
gets quoted. A record carrying one is refused for carrying it. This program has
no weights and cannot acquire any: there is no code path that combines two axes.

chip-AGNOSTIC, PDK-AGNOSTIC, vendor-AGNOSTIC: no design, PDK, process, vendor or
part literal appears in the logic or can affect it. Metric names, scope values
and units are carried through as opaque strings and are never interpreted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports resolve however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082
from _ppa import cli_exit  # PPA_INTERFACES §1: argparse exits 2; a bad invocation is 3
from _ppa import canonical_json as cj  # the ONLY serializer for anything hashed

RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

METRIC_SCHEMA = "vibeic.ppa.metric.v1"
CLAIMS_SCHEMA = "vibeic.ppa.claims.v1"

#: PPA_INTERFACES.md §2. The right-hand column is the ONLY question this program
#: asks of a status, and it is asked in exactly one place (`_may_carry_value`).
STATUS_MAY_CARRY_VALUE: Dict[str, bool] = {
    "MEASURED": True,
    "DERIVED": True,
    "NOT_MEASURED": False,
    "NOT_APPLICABLE": False,
    "INVALID": False,
    "ESTIMATED": False,
}

#: `ESTIMATED` is never in final PPA (§2). It is a legal status on a record and
#: an illegal one in a published report, which are two different statements —
#: so it is refused HERE, at publication, and not upstream where an estimate is
#: a perfectly reasonable intermediate.
STATUS_FORBIDDEN_IN_REPORT = ("ESTIMATED",)

#: A status that must carry a reason instead of a value. The absence of a
#: measurement is a fact about the run and it is reportable; the absence of a
#: REASON is just a hole.
STATUS_REQUIRES_REASON = ("NOT_MEASURED", "NOT_APPLICABLE", "INVALID")

#: Fields whose mere presence is the defect (§11.3, and the same list this
#: repository already refuses in `ppa_head_to_head_check.py`). A collapsed
#: scalar is the number that gets quoted.
COLLAPSED_SCALAR_FIELDS = ("score", "ppa_score", "overall", "figure_of_merit",
                           "fom", "composite", "weighted_score", "qor_score")

#: Which axis a metric belongs to, decided by its FIRST dotted segment only.
#: Deliberately not a keyword search over the whole name: a metric called
#: `timing.setup.power_domain_clock` is a timing metric, and a substring rule
#: would file it under power. Anything else is reported under `other`, which is
#: a stated bucket and not a silent drop.
AXIS_OF_PREFIX: Dict[str, str] = {
    "timing": "Timing",
    "power": "Power",
    "area": "Area",
}
AXIS_ORDER = ("Timing", "Power", "Area", "Other")


#: `sha256:<64 lowercase hex>` — the form `_ppa.canonical_json.digest_of`
#: produces and the only form this program will carry into a claims document.
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: Claim ids this program mints for its OWN derived counts. A metric record that
#: produced one of these ids would make a coverage citation resolve to a metric,
#: so the collision is refused by name rather than resolved by write order.
RESERVED_CLAIM_PREFIX = "report."


class Refusal(Exception):
    """A finding about the record, carrying the machine code that names it."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def _iter_metric_files(root: Path) -> List[Path]:
    """Every `*.json` under `root`, or `root` itself when it is a file.

    Sorted, so two runs over the same corpus produce the same document and the
    same digest. Directory iteration order is not a fact about the evidence.
    """
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*.json") if p.is_file())


def _records_in(payload: Any) -> List[Any]:
    """The three shapes a producer may hand us, and nothing else.

    A bare record, a list of records, or `{"metrics": [...]}`. Anything else is
    returned as a single item so that `_validate_record` refuses it BY NAME
    rather than this function silently skipping it — a skipped record is a row
    that never appears, which is the omission this program exists to prevent.
    """
    if isinstance(payload, dict) and isinstance(payload.get("metrics"), list):
        return list(payload["metrics"])
    if isinstance(payload, list):
        return list(payload)
    return [payload]


def load_metrics(root: Path) -> Tuple[List[Dict[str, Any]], List[Tuple[Path, str]]]:
    """Returns (records, unreadable) — never conflated.

    `unreadable` is a real answer and it is carried out of here rather than
    logged and dropped: a corpus in which half the files failed to parse must
    not report the other half as the whole.
    """
    records: List[Dict[str, Any]] = []
    unreadable: List[Tuple[Path, str]] = []
    for path in _iter_metric_files(root):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            unreadable.append((path, f"{type(exc).__name__}: {exc}"))
            continue
        for rec in _records_in(payload):
            if isinstance(rec, dict) and rec.get("schema") != METRIC_SCHEMA:
                # Not ours. A corpus directory legitimately holds other JSON,
                # and refusing a neighbour's file would make this gate depend on
                # what else happens to live beside it.
                continue
            records.append(rec if isinstance(rec, dict) else {"__not_an_object__": rec})
    return records, unreadable


# --------------------------------------------------------------------------
# refusals — each one a sentence the record could not have supported
# --------------------------------------------------------------------------

def _may_carry_value(status: str) -> bool:
    return STATUS_MAY_CARRY_VALUE.get(status, False)


def validate_record(rec: Dict[str, Any], where: str) -> None:
    """Raise `Refusal` when the record cannot support the sentence it becomes."""
    if "__not_an_object__" in rec:
        raise Refusal("RECORD_NOT_AN_OBJECT",
                      f"{where}: a metric record must be a JSON object")

    for field in COLLAPSED_SCALAR_FIELDS:
        if field in rec:
            raise Refusal(
                "COLLAPSED_SCALAR",
                f"{where}: record carries `{field}`. Area, timing and power "
                f"trade against each other, so a single figure is a proxy for "
                f"the property and not the property — and it is the figure a "
                f"reader quotes. Publish the triple.")

    metric = rec.get("metric")
    if not isinstance(metric, str) or not metric:
        raise Refusal("METRIC_UNNAMED",
                      f"{where}: record has no `metric` name, so no sentence "
                      f"can say what it is a measurement OF")

    status = rec.get("status")
    if status not in STATUS_MAY_CARRY_VALUE:
        raise Refusal(
            "STATUS_UNKNOWN",
            f"{where}: `{metric}` has status {status!r}, which is not one of "
            f"{sorted(STATUS_MAY_CARRY_VALUE)}. An unknown status is not a "
            f"weaker claim, it is an unreadable one.")

    if status in STATUS_FORBIDDEN_IN_REPORT:
        raise Refusal(
            "ESTIMATED_IN_FINAL",
            f"{where}: `{metric}` is {status}. PPA_INTERFACES.md §2: ESTIMATED "
            f"is never in final PPA. An estimate is a fine intermediate and a "
            f"published estimate is a number a reader will treat as measured.")

    has_value = "value" in rec and rec["value"] is not None
    if has_value and not _may_carry_value(status):
        raise Refusal(
            "VALUE_WITHOUT_MEASUREMENT",
            f"{where}: `{metric}` is {status} and still carries "
            f"value={rec['value']!r}. A status that cannot enter a numeric "
            f"comparison must not ship a number that can.")
    if not has_value and _may_carry_value(status):
        raise Refusal(
            "MEASURED_WITHOUT_VALUE",
            f"{where}: `{metric}` is {status} with no value. That is a "
            f"NOT_MEASURED row with a reason, not a measurement.")

    if status in STATUS_REQUIRES_REASON:
        reason = rec.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise Refusal(
                "REASON_MISSING",
                f"{where}: `{metric}` is {status} and carries no `reason`. "
                f"NOT_MEASURED is a reportable fact; NOT_MEASURED with no "
                f"reason is a hole with a label on it.")

    if status == "DERIVED" and not str(rec.get("formula", "")).strip():
        raise Refusal(
            "DERIVED_WITHOUT_FORMULA",
            f"{where}: `{metric}` is DERIVED with no `formula`. A number this "
            f"run computed is only checkable if a reader can recompute it.")

    if status == "MEASURED":
        source = rec.get("source")
        if not isinstance(source, dict) or not str(source.get("path", "")).strip():
            raise Refusal(
                "MEASURED_WITHOUT_SOURCE",
                f"{where}: `{metric}` is MEASURED with no `source.path`. A "
                f"measurement whose artefact is not named cannot be checked by "
                f"anyone but the process that produced it.")
        digest = source.get("sha256")
        if digest is not None and not SHA256_RE.match(str(digest)):
            raise Refusal(
                "SOURCE_DIGEST_MALFORMED",
                f"{where}: `{metric}` carries source.sha256={digest!r}, which "
                f"is not `sha256:<64 hex>`. A digest that cannot be compared "
                f"is decoration, and decoration in the identity field is worse "
                f"than an absent digest because it reads as one that was "
                f"checked (PPA_INTERFACES.md §3).")


# --------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------

def claim_id_for(metric: str, scope: Dict[str, Any]) -> str:
    """A stable id: the metric name plus a short digest of its SCOPE.

    Scope is in the id because two records of the same metric at different
    corners are different facts (§2), and a citation that resolved to whichever
    one happened to be written last would bind a sentence to the wrong number.
    The digest comes from the canonical serializer so the id does not depend on
    the order the scope dict was built in.
    """
    safe = "".join(c if (c.isalnum() or c in "._-") else "-" for c in metric)
    return f"{safe}.{cj.sha256(scope)[:8]}"


def _evidence_of(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The artefact behind the row.

    A NOT_MEASURED row legitimately has no evidence — the absence IS the fact —
    and that is the one case where an empty list is not a missing citation.
    """
    source = rec.get("source")
    if not isinstance(source, dict):
        return []
    ev: Dict[str, Any] = {"path": str(source.get("path", "")).strip(),
                          "status": rec["status"]}
    if not ev["path"]:
        return []
    for key in ("sha256", "tool", "parser"):
        val = source.get(key)
        if isinstance(val, str) and val:
            ev[key] = val
    return [ev]


def claim_of(rec: Dict[str, Any]) -> Dict[str, Any]:
    """One metric record -> one citable claim.

    The claim's status is COPIED from the record and never strengthened. That is
    the whole discipline: `ppa_page_claim_check.py` later refuses a claim whose
    status outruns its evidence, and it can only do that because nothing between
    the artefact and the sentence was allowed to upgrade it.
    """
    metric = rec["metric"]
    status = rec["status"]
    scope = rec.get("scope") if isinstance(rec.get("scope"), dict) else {}
    claim: Dict[str, Any] = {
        "id": claim_id_for(metric, scope),
        "text": _sentence(rec),
        "status": status,
        "metric": metric,
    }
    if _may_carry_value(status):
        claim["value"] = rec["value"]
        unit = rec.get("unit")
        if isinstance(unit, str) and unit:
            claim["unit"] = unit
    else:
        claim["reason"] = str(rec.get("reason", "")).strip() or "no reason recorded"
    if status == "DERIVED":
        claim["formula"] = str(rec.get("formula", ""))
    if scope:
        claim["scope"] = scope
    evidence = _evidence_of(rec)
    if evidence:
        claim["evidence"] = evidence
    return claim


def _scope_phrase(scope: Dict[str, Any]) -> str:
    """Scope rendered into the sentence, because a number without its scope is
    not comparable to anything (§2) and a reader will compare it anyway."""
    if not scope:
        return ""
    parts = [f"{k}={scope[k]}" for k in sorted(scope)]
    return " at " + ", ".join(parts)


def _sentence(rec: Dict[str, Any]) -> str:
    metric, status = rec["metric"], rec["status"]
    where = _scope_phrase(rec.get("scope") if isinstance(rec.get("scope"), dict) else {})
    if _may_carry_value(status):
        unit = rec.get("unit")
        unit = f" {unit}" if isinstance(unit, str) and unit else ""
        verb = "is" if status == "MEASURED" else "is DERIVED as"
        return f"{metric} {verb} {rec['value']}{unit}{where}."
    return f"{metric} is {status}{where}: {str(rec.get('reason', '')).strip()}"


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------

def _axis_of(metric: str) -> str:
    return AXIS_OF_PREFIX.get(metric.split(".", 1)[0], "Other")


def _cite(claim_id: str) -> str:
    return f"`[claim:{claim_id}]`"


def bookkeeping_claims(coverage: Dict[str, Any], source_root: str,
                       unreadable_count: int) -> List[Dict[str, Any]]:
    """Claims for the report's OWN counts, so its prose survives its own gate.

    Every number this report prints is quotable, and that includes the numbers
    the report computed about itself: "2 records read" is exactly as citable a
    statement as a WNS value, and it is the one a reader uses to decide whether
    the coverage was complete. So the counts are DERIVED claims with a stated
    formula and the corpus as their evidence, and the prose cites them — which
    means `ppa_page_claim_check.py --cite-numbers` passes over this report
    rather than being a mode nobody can run on the artefact it was written for.

    The evidence status is MEASURED because the fact being evidenced is "this
    corpus was read", which was measured. It says nothing about the status of
    the records inside it — those carry their own.
    """
    ev = [{"path": source_root, "status": "MEASURED"}]
    out: List[Dict[str, Any]] = [{
        "id": f"{RESERVED_CLAIM_PREFIX}coverage.total",
        "text": (f"{coverage['total']} {METRIC_SCHEMA} record(s) were read "
                 f"from {source_root}."),
        "status": "DERIVED",
        "value": coverage["total"],
        "formula": (f"count of `{METRIC_SCHEMA}` records parsed from "
                    f"`{source_root}`, after de-duplication by (metric, scope)"),
        "evidence": list(ev),
    }]
    for status in sorted(STATUS_MAY_CARRY_VALUE):
        count = coverage["by_status"].get(status, 0)
        out.append({
            "id": f"{RESERVED_CLAIM_PREFIX}coverage.{status}",
            "text": (f"{count} of the record(s) read from {source_root} "
                     f"carry status {status}."),
            "status": "DERIVED",
            "value": count,
            "formula": (f"count of parsed records whose `status` is exactly "
                        f"`{status}`"),
            "evidence": list(ev),
        })
    out.append({
        "id": f"{RESERVED_CLAIM_PREFIX}unreadable_files",
        "text": (f"{unreadable_count} file(s) under {source_root} could not be "
                 f"parsed and are not counted in coverage."),
        "status": "DERIVED",
        "value": unreadable_count,
        "formula": (f"count of `*.json` files under `{source_root}` that raised "
                    f"OSError or ValueError on read/parse"),
        "evidence": list(ev),
    })
    return out


def _row(claim: Dict[str, Any]) -> str:
    """One table row. A non-measured row prints the literal status and the
    reason IN THE VALUE COLUMN — not a blank, not a dash, and never a zero."""
    if claim["status"] in ("MEASURED", "DERIVED"):
        unit = claim.get("unit", "")
        shown = f"{claim['value']}{(' ' + unit) if unit else ''}"
    else:
        shown = f"**{claim['status']}** — {claim['reason']}"
    scope = claim.get("scope") or {}
    scope_txt = ", ".join(f"{k}={scope[k]}" for k in sorted(scope)) or "—"
    ev = claim.get("evidence") or []
    ev_txt = ", ".join(f"`{e['path']}`" for e in ev) or "none"
    return (f"| `{claim['metric']}` | {claim['status']} | {shown} | {scope_txt} "
            f"| {ev_txt} | {_cite(claim['id'])} |")


_TABLE_HEAD = ("| metric | status | value | scope | evidence | claim |\n"
               "|---|---|---|---|---|---|")


def render_report(claims: List[Dict[str, Any]], coverage: Dict[str, Any],
                  source_root: str, unreadable: List[Tuple[Path, str]]) -> str:
    """The human report. EVERY number in it carries a `[claim:<id>]`.

    The citation is not decoration: `ppa_page_claim_check.py` reads it, so a
    sentence that acquires a number without acquiring a citation is caught by a
    program instead of by a reviewer who happens to look.
    """
    by_status = coverage["by_status"]
    cov = f"{RESERVED_CLAIM_PREFIX}coverage"
    out: List[str] = []
    out.append("# PPA report")
    out.append("")
    out.append("## What this report is")
    out.append("")
    out.append(
        f"Every row below came from a `{METRIC_SCHEMA}` record under "
        f"`{source_root}`. Nothing here was computed by the report except the "
        f"counts, which say so and carry their formula: a metric status is "
        f"copied from the record that carried it, so no sentence in this "
        f"document is stronger than the artefact behind it.")
    out.append("")
    out.append(
        "This report contains no single combined PPA figure, and the generator "
        "has no code path that could produce one. Area, timing and power trade "
        "against each other; one number would be a proxy for the property and "
        "not the property.")
    out.append("")

    out.append("## Measurement coverage")
    out.append("")
    out.append(f"Records read from `{source_root}`: **{coverage['total']}** "
               f"{_cite(cov + '.total')}")
    out.append("")
    out.append("| status | count | claim |")
    out.append("|---|---|---|")
    # Every status is listed, including the ones whose count is zero: a status
    # that is absent from the table is indistinguishable from a status nobody
    # thought to look for.
    for status in sorted(STATUS_MAY_CARRY_VALUE):
        out.append(f"| {status} | {by_status.get(status, 0)} "
                   f"| {_cite(f'{cov}.{status}')} |")
    out.append("")
    out.append(
        f"The counts above are over `{METRIC_SCHEMA}` records only. This "
        f"report's own bookkeeping claims are not counted in them, so the "
        f"denominator a reader quotes is the evidence set and not the "
        f"paperwork.")
    out.append("")
    unreadable_cite = _cite(f"{RESERVED_CLAIM_PREFIX}unreadable_files")
    if unreadable:
        out.append(
            f"**{len(unreadable)} file(s) under `{source_root}` could not be "
            f"read and are NOT counted above** {unreadable_cite}. They are "
            f"listed here rather than dropped, because a corpus that "
            f"half-parsed must not be read as a corpus that measured half:")
        out.append("")
        for path, why in unreadable:
            out.append(f"  * `{path}` — {why} {unreadable_cite}")
        out.append("")
    else:
        out.append(f"No file under `{source_root}` failed to parse "
                   f"{unreadable_cite}.")
        out.append("")

    for axis in AXIS_ORDER:
        rows = [c for c in claims if _axis_of(c["metric"]) == axis]
        out.append(f"## {axis}")
        out.append("")
        if not rows:
            out.append(
                f"**NOT_MEASURED** — no `{METRIC_SCHEMA}` record under "
                f"`{source_root}` named a metric on this axis. This heading is "
                f"printed rather than omitted: an axis missing from a report "
                f"reads as an axis with nothing to report.")
            out.append("")
            continue
        out.append(_TABLE_HEAD)
        for claim in sorted(rows, key=lambda c: (c["metric"], c["id"])):
            out.append(_row(claim))
        out.append("")

    not_measured = [c for c in claims if c["status"] in STATUS_REQUIRES_REASON]
    out.append("## Not measured")
    out.append("")
    if not not_measured:
        out.append(
            f"No record read from `{source_root}` was NOT_MEASURED, "
            f"NOT_APPLICABLE or INVALID {_cite(cov + '.NOT_MEASURED')} "
            f"{_cite(cov + '.NOT_APPLICABLE')} {_cite(cov + '.INVALID')}. "
            f"That is a statement about the records that were PRESENT; it is "
            f"not a statement that every metric this design has was recorded.")
    else:
        out.append(
            f"Each row here carries a reason where a value would have been "
            f"{_cite(cov + '.NOT_MEASURED')} {_cite(cov + '.total')}.")
        out.append("")
        out.append("| metric | status | reason | claim |")
        out.append("|---|---|---|---|")
        for c in sorted(not_measured, key=lambda c: (c["metric"], c["id"])):
            out.append(f"| `{c['metric']}` | {c['status']} | {c['reason']} "
                       f"| {_cite(c['id'])} |")
    out.append("")

    out.append("## How to check this report")
    out.append("")
    out.append("```")
    out.append("ppa_page_claim_check.py <this report> --claims claims.json "
               "--cite-numbers")
    out.append("```")
    out.append("")
    out.append(
        "Every `[claim:<id>]` above resolves to an entry in `claims.json` that "
        "names the artefact path, its `sha256:` digest and the status of the "
        "record it was parsed from. The checker goes red when a sentence "
        "claims more than the artefact behind it supports, and `--cite-numbers` "
        "additionally goes red on any sentence here that states a number "
        "without naming the claim it came from.")
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def generate(metrics_root: Path) -> Tuple[int, Dict[str, Any]]:
    """Returns (rc, result). `result["report_md"]` / `["claims"]` on rc=0."""
    if not metrics_root.exists():
        return RC_UNDETERMINED, {
            "code": "NO_INPUT",
            "marker": "[CANNOT CHECK]",
            "detail": (f"{metrics_root} does not exist. This is not a report "
                       f"of zero metrics — nothing was looked at."),
        }

    records, unreadable = load_metrics(metrics_root)
    if not records:
        return RC_UNDETERMINED, {
            "code": "EMPTY_CORPUS",
            "marker": "[CANNOT CHECK]",
            "detail": (f"{metrics_root} exists and carries 0 "
                       f"`{METRIC_SCHEMA}` record(s) "
                       f"({len(unreadable)} file(s) unreadable). The zero is "
                       f"stated, and it is a different answer from NO_INPUT."),
            "unreadable": [[str(p), why] for p, why in unreadable],
        }

    claims: List[Dict[str, Any]] = []
    seen: Dict[str, Dict[str, Any]] = {}
    for index, rec in enumerate(records):
        where = f"record #{index}"
        try:
            validate_record(rec, where)
        except Refusal as refusal:
            return RC_REFUSED, {"code": refusal.code, "marker": "[REFUSE]",
                                "detail": refusal.detail}
        claim = claim_of(rec)
        if claim["id"].startswith(RESERVED_CLAIM_PREFIX):
            return RC_REFUSED, {
                "code": "RESERVED_CLAIM_ID",
                "marker": "[REFUSE]",
                "detail": (f"{where}: `{rec['metric']}` mints claim id "
                           f"`{claim['id']}`, which is inside the "
                           f"`{RESERVED_CLAIM_PREFIX}` namespace this report "
                           f"uses for its own counts. A coverage citation "
                           f"would resolve to a metric."),
            }
        prior = seen.get(claim["id"])
        if prior is not None and cj.sha256(prior) != cj.sha256(claim):
            return RC_REFUSED, {
                "code": "CLAIM_ID_COLLISION",
                "marker": "[REFUSE]",
                "detail": (f"{where}: two different records produce claim id "
                           f"`{claim['id']}` — same metric, same scope, "
                           f"different fact. A citation that resolves to two "
                           f"numbers binds a sentence to neither."),
            }
        if prior is None:
            seen[claim["id"]] = claim
            claims.append(claim)

    by_status: Dict[str, int] = {}
    for claim in claims:
        by_status[claim["status"]] = by_status.get(claim["status"], 0) + 1
    # The denominator is over METRIC records. The report's own bookkeeping
    # claims are appended after this line and deliberately do not inflate it:
    # a coverage figure that counted the paperwork would grow when the report
    # got wordier.
    coverage = {"total": len(claims), "by_status": by_status}

    report_md = render_report(claims, coverage, str(metrics_root), unreadable)
    all_claims = claims + bookkeeping_claims(coverage, str(metrics_root),
                                             len(unreadable))
    doc = {
        "schema": CLAIMS_SCHEMA,
        "generated_by": "ppa_report_gen.py",
        "coverage": coverage,
        "claims": all_claims,
    }
    return RC_OK, {
        "code": "OK",
        "coverage": coverage,
        "claims_doc": doc,
        "report_md": report_md,
        "unreadable": [[str(p), why] for p, why in unreadable],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate the human PPA report and the claims file that "
                    "binds every sentence in it to its evidence (spec §18).")
    ap.add_argument("metrics", nargs="?",
                    help="file or directory holding `%s` records" % METRIC_SCHEMA)
    ap.add_argument("--out", default=None, metavar="PATH",
                    help="write report.md here")
    ap.add_argument("--claims", default=None, metavar="PATH",
                    help="write claims.json here")
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="write the machine-readable run record here")
    args, _rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return _rc

    if not args.metrics:
        return cli_exit.refuse(ap.prog, "give a metrics file or directory")

    rc, result = generate(Path(args.metrics))

    if rc == RC_OK:
        if args.out:
            atomic_write_text(Path(args.out), result["report_md"])
        if args.claims:
            atomic_write_text(Path(args.claims),
                              json.dumps(result["claims_doc"], indent=2,
                                         sort_keys=True, ensure_ascii=False)
                              + "\n")
        cov = result["coverage"]
        detail = ", ".join(f"{k}={v}" for k, v in sorted(cov["by_status"].items()))
        print(f"PPA report: {cov['total']} record(s) — {detail or 'none'}")
        if not args.out and not args.claims:
            print(result["report_md"])
    else:
        print(f"{result['marker']} {result['code']}: {result['detail']}",
              file=sys.stderr)
        # stdout carries a line too, so a caller that only reads stdout cannot
        # mistake a refusal for a silent success.
        print(f"{result['marker']} {result['code']} -> rc={rc}")

    if args.json:
        record = {k: v for k, v in result.items() if k != "report_md"}
        record["rc"] = rc
        atomic_write_text(Path(args.json),
                          json.dumps(record, indent=2, sort_keys=True,
                                     ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
