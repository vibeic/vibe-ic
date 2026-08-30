#!/usr/bin/env python3
"""release_docs_check.py — the gate over a release document set.

ENFORCEMENT: advisory here — this gate is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; no one-shot runner invokes
it inline at all. It runs when ``flow_compliance_check`` evaluates step 37.5ip's
``gate.all_of`` clause ``release_docs_check . --arm ip --json
reports/phase3/release_docs.json``, so its rc IS that step's verdict — "advisory"
names the RUNNER channel it is absent from, not a verdict this gate cannot
reach. The same token, for the same reason, as its sibling clause
``digital_hardmacro_check`` on the same step: wiring either one into the runner
would change what a real run blocks on, which is the flow owner's call and is
recorded, not taken here. Kept in the first 4 kB: `declared_intent` reads only
`text[:4000]`.

WHY A GATE AND NOT A LINTER
===========================
Two proposals were written for the step-37.5 documentation package. Both
described DOCUMENTS. Neither said how the gate could REFUSE, and one of them got
as far as "document existence alone is insufficient for PASS" before listing
conditions without saying how any of them is decided.

Measured on this tree at v1.13.42, and the reason that omission is the whole
job: SIX on-pass gates could only ever answer rc 2. Every declared command
carried neither ``--compliance`` nor ``--stage-verdict``, so ``stage_passed()``
returned UNESTABLISHED and the program exited before consulting a single rule —
on every input, forever. The flow declared the review, the audit measured a
wiring, the tests passed, and no review had ever run.

So the acceptance for this gate is not "the documents are generated". It is:

    THE GATE REFUSES A REAL DEFECT, AND THE REFUSAL NAMES IT.

Its own test suite falsifies that in both directions over a project that carries
a SECOND, UNTOUCHED release as a control: a required section deleted, a pin
count edited away from the netlist, a mandatory constraint left only in an
Application Note, a shipped-view digest gone stale — each one rc 1 naming the
defect, each one repaired back to rc 0, and the control release green in every
arm.

WHAT IT DECIDES, AND FROM WHAT
==============================
Nothing here trusts the generator. Every quantity the documents state is
RE-DERIVED from the tree by this program, from a DIFFERENT view where one
exists:

  R1  a required document is absent
  R2  a required section is absent, or the declared sections are out of order
  R3  the stated pin count disagrees with the delivered netlist view — the
      document derived it from the LEF, this gate re-derives it from the
      Verilog, and the finding names BOTH sides with BOTH paths
  R4  a mandatory constraint appears ONLY in an Application Note
  R5  a quantitative field is neither derived from a resolvable artefact nor
      explicitly NOT_MEASURED with a reason
  R6  a shipped-view digest in the deliverables manifest disagrees with the file
  R7  the manifest's derived / NOT_MEASURED counts disagree with a recount
  R8  an unresolved placeholder survived into a shipped document

R3 AND R6 ARE THE TWO THAT CANNOT BE SATISFIED BY WRITING PROSE. A hand-typed
pin count and a stale digest are the two ways a document goes quietly wrong
while every section heading stays exactly where it was.

THE VERDICT TIERS
=================
rc 0 PASS, rc 1 FAIL, rc 2 VACUOUS — the convention ``_vacuous_exit`` routes and
``flow_compliance_check`` reads. rc 2 is reserved for ONE state and it is
disclosed on the rc-independent channel: this arm has no release to examine at
all. A kit that EXISTS with no documentation beside it is rc 1, not rc 2 — a
hard IP shipping its four views with no integration guide is the defect this
gate was written for, and crediting it to the vacuous tier would reinstate it.

ARMS. ``--arm ip`` is wired into step 37.5ip. ``--arm ic`` reads the chip-path
document set declared in ``_release_docs_contract``; the producer that writes it
extends ``tapeout_docs_gen`` and is a SEPARATE landing, so until that lands the
``ic`` arm has no producer in the flow and is invoked by this gate's tests only.
That is stated rather than hidden: an arm that is declared and never runs is
precisely the v1.13.42 shape above.

§4.05: reads ONLY the run's own generated evidence (the documents, the delivered
kit) and the design INPUT. Never the oracle, the harness, or the golden.

NDA: nothing here names a commercial foundry, process node, SKU, chip codename
or qualification programme, and the contract it enforces names none either.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import _vacuous_exit as _vx
import digital_hardmacro_check as _hm
from _atomic_artefact import write_text as atomic_write_text
from _release_docs_contract import (
    CONSTRAINT_BEARING,
    DERIVED_COLUMN,
    H2_RE,
    IP_DELIVERABLES_MANIFEST,
    MANDATORY_RE,
    MANIFEST_NAME,
    NOT_MEASURED,
    PIN_COUNT_LABEL,
    PLACEHOLDER_RE,
    SIGNAL_PIN_LABEL,
    SUPPLY_PIN_LABEL,
    REASON_PREFIX,
    SOURCE_PATH_RE,
    arm_docs,
    doc_dir,
)

try:
    import yaml
except ImportError:  # pragma: no cover - the flow's own evaluator needs it too
    print("release_docs_check: PyYAML required (pip install pyyaml)",
          file=sys.stderr)
    sys.exit(2)

GATE = "release_docs_check"
VERSION = "1.0.0"


@dataclass
class Finding:
    rule: str
    severity: str
    release: str
    message: str


@dataclass
class Result:
    program: str = GATE
    version: str = VERSION
    passed: bool = True
    verdict_tier: str = "PASS"
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ── reading a document ─────────────────────────────────────────────────────
@dataclass
class Row:
    """One row of a `Derived from` table, with where it came from."""
    document: str
    label: str
    value: str
    third: str


def sections_of(text: str) -> List[str]:
    return [m.group("title") for m in
            (H2_RE.match(line) for line in text.splitlines()) if m]


def derived_rows(document: str, text: str) -> List[Row]:
    """Every row of every table whose third column is the derivation column.

    Scoped to THAT column header on purpose. A document legitimately carries
    other tables — the deliverables file list, a register-group summary — and a
    reader that took every pipe-delimited line would demand a derivation for
    rows that are not measurements, which is how a rule this shape gets widened
    until it is switched off.
    """
    rows: List[Row] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = _cells(stripped)
        if len(cells) != 3:
            in_table = False
            continue
        if cells[2] == DERIVED_COLUMN:
            in_table = True
            continue
        if not in_table:
            continue
        if set(cells[0]) <= {"-", ":"} and cells[0]:
            continue
        rows.append(Row(document, cells[0], cells[1], cells[2]))
    return rows


#: A cell boundary: a `|` that is NOT backslash-escaped. Splitting on a bare
#: `|` was a MEASURED defect of this reader: the producer escapes a pipe inside
#: a prose cell (`\|`, the Markdown rule — an unescaped one would end the cell),
#: a naive split then saw FOUR cells instead of three, the row was read as
#: leaving the table, and every row BELOW it went unexamined. A recount over the
#: truncated table then disagreed with the manifest, so a correct release was
#: refused for a defect the reader had invented.
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


def _cells(line: str) -> List[str]:
    parts = [c.strip() for c in _CELL_SPLIT_RE.split(line)]
    if parts and not parts[0]:
        parts = parts[1:]
    if parts and not parts[-1]:
        parts = parts[:-1]
    return parts


def constraint_ids(text: str) -> Dict[str, str]:
    """`{constraint id: its text}` for every mandatory constraint in one file."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        m = MANDATORY_RE.match(line)
        if m:
            out[m.group("id")] = m.group("text")
    return out


# ── the checks ─────────────────────────────────────────────────────────────
def _check_sections(spec, document: str, text: str, release: str,
                    findings: List[Finding]) -> None:
    """R2 — every declared section present, in the declared order."""
    present = sections_of(text)
    missing = [s for s in spec.sections if s not in present]
    for title in missing:
        findings.append(Finding(
            "REQUIRED_SECTION_ABSENT", "ERROR", release,
            f"{document} does not carry the required section "
            f"'## {title}'. Declared sections for this document: "
            f"{list(spec.sections)}. Present: {present}."))
    if missing:
        return
    order = [s for s in present if s in spec.sections]
    if order != list(spec.sections):
        findings.append(Finding(
            "REQUIRED_SECTION_OUT_OF_ORDER", "ERROR", release,
            f"{document} carries every required section but in the order "
            f"{order}, and the declared order is {list(spec.sections)}. A "
            f"section that has drifted is a section a reader stops finding."))


def _check_rows(project: Path, rows: Sequence[Row], release: str,
                findings: List[Finding]) -> Tuple[int, int]:
    """R5 — derived from a resolvable artefact, or NOT_MEASURED with a reason.

    Returns (derived, not_measured) so the manifest's own counts can be checked
    against a recount rather than believed.
    """
    derived = holes = 0
    for row in rows:
        if row.value == NOT_MEASURED:
            holes += 1
            reason = row.third[len(REASON_PREFIX):].strip() \
                if row.third.startswith(REASON_PREFIX) else ""
            if not reason:
                findings.append(Finding(
                    "NOT_MEASURED_WITHOUT_A_REASON", "ERROR", release,
                    f"{row.document} states {NOT_MEASURED} for '{row.label}' "
                    f"and gives no '{REASON_PREFIX}' — 'we did not look' is "
                    f"only honest when it says why. Third column: "
                    f"{row.third!r}."))
            continue
        derived += 1
        m = SOURCE_PATH_RE.search(row.third)
        if not m:
            findings.append(Finding(
                "FIELD_NOT_DERIVED", "ERROR", release,
                f"{row.document} states '{row.label}' = {row.value!r} with no "
                f"artefact path behind it (third column: {row.third!r}). A "
                f"value nobody can walk back to an artefact of this run is a "
                f"hand-typed number, and a hand-typed copy of an "
                f"automatically-changing fact is stale by construction."))
            continue
        source = m.group(1)
        if not (project / source).exists():
            findings.append(Finding(
                "DERIVATION_SOURCE_ABSENT", "ERROR", release,
                f"{row.document} derives '{row.label}' = {row.value!r} from "
                f"`{source}`, and that path does not resolve under {project}. "
                f"A citation that resolves to nothing binds nothing."))
    return derived, holes


def _check_placeholders(document: str, text: str, release: str,
                        findings: List[Finding]) -> int:
    """R8 — no unresolved placeholder survives into a shipped document."""
    hits = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in PLACEHOLDER_RE.finditer(line):
            hits += 1
            findings.append(Finding(
                "UNRESOLVED_PLACEHOLDER", "ERROR", release,
                f"{document}:{lineno} still carries the placeholder "
                f"{match.group(0)!r}: {line.strip()!r}"))
    return hits


def _check_app_notes(arm: str, texts: Dict[str, str], release: str,
                     findings: List[Finding]) -> int:
    """R4 — a mandatory constraint may be RESTATED in an AN, never originate there.

    An Application Note is optional, is read by a subset of integrators, and is
    the first document dropped from a delivery. A constraint that lives only
    there is a constraint the release does not actually carry, so this is a gate
    FAILURE and not a style note.
    """
    bearing: Dict[str, str] = {}
    for name in CONSTRAINT_BEARING[arm]:
        bearing.update(constraint_ids(texts.get(name, "")))
    checked = 0
    for spec in arm_docs(arm):
        if not spec.is_application_note or spec.filename not in texts:
            continue
        for cid, text in constraint_ids(texts[spec.filename]).items():
            checked += 1
            if cid in bearing:
                continue
            findings.append(Finding(
                "MANDATORY_CONSTRAINT_ONLY_IN_APP_NOTE", "ERROR", release,
                f"{spec.filename} states mandatory constraint `{cid}` "
                f"({text[:120]}) and it appears in none of "
                f"{list(CONSTRAINT_BEARING[arm])}. An Application Note is "
                f"optional and is the first document dropped from a delivery; "
                f"a constraint that lives only there is one the release does "
                f"not carry."))
    return checked


def _stated(rows: Sequence[Row], document: str,
            label: str) -> Optional[Tuple[Row, int]]:
    """The count ONE document states for `label`, or None when it states none.

    A NOT_MEASURED row is NOT a stated count and is deliberately not read as
    zero: "we did not look" and "we looked and there are none" must never reach
    the same comparison.
    """
    for row in rows:
        if row.document != document or row.label != label:
            continue
        if row.value == NOT_MEASURED:
            continue
        try:
            return row, int(row.value)
        except ValueError:
            return row, -1
    return None


def _netlist_signal_ports(project: Path, release: str) -> Optional[Tuple[int, Path]]:
    """The logical port count the delivered Verilog view declares, re-derived."""
    views = _hm.discover_packages(_hm.hardmacro_dir(project)).get(release, {})
    v_path = views.get(".v")
    if v_path is None:
        return None
    bus = "[]<>"
    lef_path = views.get(".lef")
    if lef_path is not None:
        bus = _hm.lef_bus_chars(
            lef_path.read_text(encoding="utf-8", errors="replace"))
    parsed = _hm.parse_verilog(
        v_path.read_text(encoding="utf-8", errors="replace"), bus)
    ports = parsed.get("ports")
    return (len(ports) if isinstance(ports, set) else 0), v_path


def _check_pin_count(project: Path, release: str, rows: Sequence[Row],
                     findings: List[Finding]) -> str:
    """R3 — the stated pin counts, against the netlist and against themselves.

    THE SIGNAL COUNT IS SETTLED BY THE NETLIST. The document derived it from the
    LEF the placer reads; this re-derives it from the Verilog the simulator
    reads — a DIFFERENT view, by a DIFFERENT program — so a number edited after
    generation, or carried forward from an earlier release, disagrees with the
    tree instead of being believed. The finding names BOTH sides and BOTH paths,
    because "the pin count is wrong" is not actionable and "4 here, 3 there" is.

    THE TOTAL IS SETTLED BY ITS OWN PARTS. A Verilog view of a hard macro
    conventionally omits the supplies (`digital_hardmacro_check` states that
    exception and accepts it), so the netlist cannot settle a total that
    includes them. What a total CAN be held to is arithmetic: one that does not
    equal signal + supply was typed, not derived, and that is caught without
    pretending the netlist knew about the supplies.

    EVERY DOCUMENT THAT STATES A COUNT IS CHECKED, not the first one found. Two
    documents in this set carry the interface table; taking the first match
    would let a correct datasheet mask an edited integration guide, which is
    precisely the drift a cross-check exists to catch. Both comparisons run for
    every document — an early return after one finding would leave the OTHER
    defect unreported in the same run.
    """
    netlist = _netlist_signal_ports(project, release)
    states: List[str] = []
    for document in sorted({row.document for row in rows}):
        signal = _stated(rows, document, SIGNAL_PIN_LABEL)
        supply = _stated(rows, document, SUPPLY_PIN_LABEL)
        total = _stated(rows, document, PIN_COUNT_LABEL)
        if signal is None and supply is None and total is None:
            continue

        unreadable = [x for x in (signal, supply, total)
                      if x is not None and x[1] < 0]
        for row, _ in unreadable:
            findings.append(Finding(
                "PIN_COUNT_UNREADABLE", "ERROR", release,
                f"{row.document} states '{row.label}' = {row.value!r}, which "
                f"is not a count."))
        if unreadable:
            states.append("UNREADABLE")
            continue

        if signal is not None and supply is not None and total is not None \
                and total[1] != signal[1] + supply[1]:
            findings.append(Finding(
                "PIN_COUNT_INTERNALLY_INCONSISTENT", "ERROR", release,
                f"{document} states '{PIN_COUNT_LABEL}' = {total[1]}, and its "
                f"own component rows state '{SIGNAL_PIN_LABEL}' = {signal[1]} "
                f"and '{SUPPLY_PIN_LABEL}' = {supply[1]}, which sum to "
                f"{signal[1] + supply[1]}. A total that does not equal its "
                f"parts was typed, not derived."))
            states.append("INTERNALLY_INCONSISTENT")

        if signal is None:
            continue
        if netlist is None:
            findings.append(Finding(
                "PIN_COUNT_NOT_CROSS_CHECKED", "INFO", release,
                f"{document} states '{SIGNAL_PIN_LABEL}' = {signal[1]} and "
                f"this release ships no .v view under "
                f"{_hm.hardmacro_dir(project).as_posix()}, so the count could "
                f"not be re-derived from a second view. NOT DETERMINED, not "
                f"accepted."))
            states.append("NOT_DETERMINED")
            continue
        netlist_count, v_path = netlist
        if netlist_count == signal[1]:
            states.append("AGREES")
            continue
        findings.append(Finding(
            "PIN_COUNT_DISAGREES_WITH_NETLIST", "ERROR", release,
            f"{document} states '{SIGNAL_PIN_LABEL}' = {signal[1]}, derived "
            f"from {signal[0].third}; the delivered netlist view "
            f"`{v_path.relative_to(project).as_posix()}` declares "
            f"{netlist_count} logical port(s). A datasheet with a pin count no "
            f"view supports is stale on arrival."))
        states.append("DISAGREES")

    if not states:
        return "NOT_STATED"
    for tier in ("UNREADABLE", "DISAGREES", "INTERNALLY_INCONSISTENT",
                 "NOT_DETERMINED"):
        if tier in states:
            return tier
    return "AGREES"


def _check_deliverables_digests(project: Path, release: str, text: str,
                                findings: List[Finding]) -> int:
    """R6 — every shipped-view digest in the manifest, recomputed.

    A manifest whose digests are never re-derived binds nothing. This is the one
    check that catches a document set correctly describing a DIFFERENT build of
    the same kit — every heading in place, every section present, and the files
    it names are not the files that shipped.
    """
    checked = 0
    for line in text.splitlines():
        cells = _cells(line.strip()) if line.strip().startswith("|") else []
        if len(cells) != 3:
            continue
        path_m = re.fullmatch(r"`([^`]+)`", cells[0])
        digest_m = re.fullmatch(r"`([0-9a-f]{64})`", cells[2])
        if not (path_m and digest_m):
            continue
        checked += 1
        target = project / path_m.group(1)
        if not target.is_file():
            findings.append(Finding(
                "MANIFEST_FILE_ABSENT", "ERROR", release,
                f"{IP_DELIVERABLES_MANIFEST} lists `{path_m.group(1)}` and no "
                f"such file exists under {project}."))
            continue
        actual = _sha256(target)
        if actual != digest_m.group(1):
            findings.append(Finding(
                "MANIFEST_DIGEST_STALE", "ERROR", release,
                f"{IP_DELIVERABLES_MANIFEST} states sha256 "
                f"{digest_m.group(1)} for `{path_m.group(1)}`; the file on "
                f"disk digests to {actual}. The documents describe a build "
                f"that is not the one shipped."))
    return checked


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_manifest(release_dir: Path, release: str, derived: int, holes: int,
                    findings: List[Finding]) -> Optional[dict]:
    """R7 — the manifest's own counts, against a recount of the documents."""
    path = release_dir / MANIFEST_NAME
    if not path.is_file():
        findings.append(Finding(
            "MANIFEST_ABSENT", "ERROR", release,
            f"{release_dir} carries no {MANIFEST_NAME}. Without it nothing "
            f"binds this document set to the tree it describes, and a report "
            f"that does not name the tree it measured can describe the wrong "
            f"one in four ways with no error raised."))
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — an unreadable manifest is named
        findings.append(Finding(
            "MANIFEST_UNREADABLE", "ERROR", release,
            f"{MANIFEST_NAME} does not parse as YAML: {exc}"))
        return None
    if not isinstance(doc, dict):
        findings.append(Finding(
            "MANIFEST_UNREADABLE", "ERROR", release,
            f"{MANIFEST_NAME} is not a mapping."))
        return None
    for key, recount in (("derived_fields", derived),
                         ("not_measured_fields", holes)):
        stated = doc.get(key)
        if stated != recount:
            findings.append(Finding(
                "MANIFEST_COUNT_DISAGREES", "ERROR", release,
                f"{MANIFEST_NAME} states {key} = {stated!r}; a recount over "
                f"the documents in {release_dir.name} gives {recount}. A count "
                f"nobody re-derives is a count that drifts."))
    tree = doc.get("tree_sha")
    reason = str(doc.get("tree_sha_reason") or "").strip()
    if tree != NOT_MEASURED and not re.fullmatch(r"[0-9a-f]{40}", str(tree)):
        findings.append(Finding(
            "MANIFEST_TREE_SHA_INVALID", "ERROR", release,
            f"{MANIFEST_NAME} states tree_sha = {tree!r}, which is neither a "
            f"commit nor {NOT_MEASURED}."))
    if tree == NOT_MEASURED and not reason:
        findings.append(Finding(
            "MANIFEST_TREE_SHA_INVALID", "ERROR", release,
            f"{MANIFEST_NAME} states tree_sha = {NOT_MEASURED} with no "
            f"tree_sha_reason."))
    return doc


# ── one release ────────────────────────────────────────────────────────────
def check_release(project: Path, arm: str, release_dir: Path,
                  release: str) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    texts: Dict[str, str] = {}
    for spec in arm_docs(arm):
        path = release_dir / spec.filename
        if path.is_file():
            texts[spec.filename] = path.read_text(encoding="utf-8",
                                                  errors="replace")

    manifest_path = release_dir / MANIFEST_NAME
    manifest_doc = None
    if manifest_path.is_file():
        try:
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest_doc = loaded if isinstance(loaded, dict) else None
        except Exception:  # noqa: BLE001 — reported by _check_manifest
            manifest_doc = None

    # R1 — required, and conditionally required, documents.
    for spec in arm_docs(arm):
        if spec.filename in texts:
            continue
        if spec.requirement == "required":
            findings.append(Finding(
                "REQUIRED_DOCUMENT_ABSENT", "ERROR", release,
                f"{spec.filename} is required for the {arm} arm and is absent "
                f"from {release_dir}."))
        elif spec.requirement == "conditional":
            triggered = bool((manifest_doc or {}).get(spec.condition_field))
            if triggered:
                findings.append(Finding(
                    "REQUIRED_DOCUMENT_ABSENT", "ERROR", release,
                    f"{spec.filename} is required for this release because "
                    f"{MANIFEST_NAME} states {spec.condition_field} = true, "
                    f"and it is absent from {release_dir}."))

    rows: List[Row] = []
    placeholders = 0
    for spec in arm_docs(arm):
        text = texts.get(spec.filename)
        if text is None:
            continue
        _check_sections(spec, spec.filename, text, release, findings)
        placeholders += _check_placeholders(spec.filename, text, release,
                                            findings)
        rows.extend(derived_rows(spec.filename, text))

    derived, holes = _check_rows(project, rows, release, findings)
    constraints_checked = _check_app_notes(arm, texts, release, findings)
    pin_state = _check_pin_count(project, release, rows, findings) \
        if arm == "ip" else "NOT_APPLICABLE"
    digests = 0
    if IP_DELIVERABLES_MANIFEST in texts:
        digests = _check_deliverables_digests(
            project, release, texts[IP_DELIVERABLES_MANIFEST], findings)
    _check_manifest(release_dir, release, derived, holes, findings)

    detail = {
        "release": release,
        "directory": release_dir.as_posix(),
        "documents_present": sorted(texts),
        "derived_fields": derived,
        "not_measured_fields": holes,
        "rows_examined": len(rows),
        "mandatory_constraints_in_app_notes": constraints_checked,
        "shipped_digests_recomputed": digests,
        "placeholders": placeholders,
        "pin_count_cross_check": pin_state,
        "pass": not any(f.severity == "ERROR" for f in findings),
    }
    return findings, detail


# ── the run ────────────────────────────────────────────────────────────────
#: Spelled once, and only for the absence report: the search space this gate
#: looked in when it found nothing. An absence verdict that does not name where
#: it looked is a claim nobody can re-check.
KIT_DIR_GLOB = "phase3/stage4/hardmacro/*.{{lef,lib,gds,v}} (arm {arm})"


def expected_releases(project: Path, arm: str) -> List[str]:
    """The releases this arm SHOULD have documented, from the tree itself.

    For the IP arm the answer is the delivered hardmacro packages: one kit, one
    document set. Deriving it rather than reading the documentation directory is
    what makes "the kit shipped and nobody documented it" a FAIL instead of an
    empty sweep that passes.
    """
    if arm == "ip":
        return sorted(_hm.discover_packages(_hm.hardmacro_dir(project)))
    return []


def run_audit(project: Path, arm: str) -> Result:
    result = Result()
    root = project / doc_dir(arm)
    expected = expected_releases(project, arm)
    present = sorted(p.name for p in root.iterdir()
                     if p.is_dir()) if root.is_dir() else []

    if not expected and not present:
        # THE ONE VACUOUS STATE, and it is disclosed. Nothing to document and
        # nothing documented: this arm has no release in this run. It is NOT the
        # same as a kit shipping with no documents, which is rc 1 below.
        result.verdict_tier = "NOT_DETERMINED"
        result.summary = {
            "skipped": True,
            "reason": "no_release_to_examine",
            "arm": arm,
            "documentation_root": root.as_posix(),
            "documentation_root_exists": root.is_dir(),
            "searched_and_absent": [
                doc_dir(arm) + "/*/", KIT_DIR_GLOB.format(arm=arm)],
            "expected_releases": [],
            "releases_examined": 0,
            "releases": [],
            "verdict_tier": "NOT_DETERMINED",
            "pass": True,
        }
        return result

    details: List[dict] = []
    for release in sorted(set(expected) | set(present)):
        release_dir = root / release
        if not release_dir.is_dir():
            # THE DEFECT THIS GATE WAS WRITTEN FOR. A hard IP shipping its four
            # views with no integration guide is rc 1, never the vacuous tier.
            result.findings.append(Finding(
                "RELEASE_DOCUMENTATION_ABSENT", "ERROR", release,
                f"the run delivers hardmacro package `{release}` under "
                f"{_hm.hardmacro_dir(project)} and {release_dir} carries no "
                f"release documentation. A delivered IP with no document set "
                f"reaches its integrator as four files and nothing that says "
                f"what they are."))
            details.append({"release": release, "directory": release_dir.as_posix(),
                            "documents_present": [], "derived_fields": 0,
                            "not_measured_fields": 0, "rows_examined": 0,
                            "mandatory_constraints_in_app_notes": 0,
                            "shipped_digests_recomputed": 0, "placeholders": 0,
                            "pin_count_cross_check": "NOT_STATED",
                            "pass": False})
            continue
        findings, detail = check_release(project, arm, release_dir, release)
        result.findings.extend(findings)
        details.append(detail)

    failed = [d["release"] for d in details if not d["pass"]]
    result.passed = not failed
    result.verdict_tier = "PASS" if result.passed else "FAIL"
    result.summary = {
        "skipped": False,
        "reason": "",
        "arm": arm,
        "documentation_root": root.as_posix(),
        "documentation_root_exists": root.is_dir(),
        "expected_releases": expected,
        "releases_examined": len(details),
        "failed": failed,
        "rows_examined": sum(d["rows_examined"] for d in details),
        "derived_fields": sum(d["derived_fields"] for d in details),
        "not_measured_fields": sum(d["not_measured_fields"] for d in details),
        "releases": details,
        "verdict_tier": result.verdict_tier,
        "pass": result.passed,
    }
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=GATE, description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project_dir", type=Path,
                        help="project root (holds phase3/stage4/documentation/)")
    parser.add_argument("--arm", choices=sorted(("ip", "ic")), default="ip",
                        help="which document set to judge (default: %(default)s)")
    parser.add_argument("--json", default=None,
                        help="write the JSON report here")
    args = parser.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        _vx.announce_vacuous(GATE, "project_dir_absent")
        return _vx.RC_VACUOUS

    result = run_audit(args.project_dir, args.arm)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(asdict(result), indent=2,
                                          ensure_ascii=False) + "\n")

    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)
    print(_vx.verdict_line(GATE, result.passed, skipped, reason))
    # THE DENOMINATOR, ON EVERY PATH INCLUDING THE PASS. A scan of 12 releases
    # and a scan of none printed the same sentence is the exact class
    # `gate_discloses_denominator_check` exists for.
    print(f"  examined {result.summary.get('releases_examined', 0)} release(s) "
          f"in {result.summary.get('documentation_root')} · "
          f"{result.summary.get('rows_examined', 0)} derived row(s) · "
          f"{result.summary.get('derived_fields', 0)} derived field(s) · "
          f"{result.summary.get('not_measured_fields', 0)} {NOT_MEASURED} "
          f"field(s)")
    for finding in result.findings:
        if finding.severity in ("ERROR", "WARNING"):
            print(f"  [{finding.severity}] {finding.rule} "
                  f"({finding.release}): {finding.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(GATE, reason)

    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
