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
  R9  a chip-path artefact the documents describe is hollow
  R10 two sections of one document state different test-mode counts from the
      same source artefact

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

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import ast
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

import _ic_release_artefacts as _art
import yaml

import _flow_reason_taxonomy as _reason_taxonomy
import _ic_release_artefacts as _art
import tapeout_docs_gen as _tap
import _vacuous_exit as _vx
import digital_hardmacro_check as _hm
from _atomic_artefact import write_text as atomic_write_text
from _specrtl_common import strip_comments
from _release_docs_contract import (
    CONSTRAINT_BEARING,
    DERIVED_COLUMN,
    H2_RE,
    IP_DATASHEET,
    IP_DELIVERABLES_MANIFEST,
    MANDATORY_RE,
    MANIFEST_NAME,
    NOT_MEASURED,
    PIN_COUNT_LABEL,
    PLACEHOLDER_TOKENS,
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


def _cells(line: str) -> List[str]:
    parts = [c.strip() for c in line.split("|")]
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


TEST_MODE_LABEL = "Declared test modes"
TEST_MODE_CLAIM_RE = re.compile(
    r"\b(?P<count>\d+)\s+test mode\(s\)(?!\w)")
CONSTRAINT_SOURCE_RE = re.compile(
    r"\(derived from `(?P<source>[^`]+)`\)\s*$")
# ── independent Verilog interface reader ──────────────────────────────────
# This reader intentionally does NOT call digital_hardmacro_check.parse_verilog.
# That parser normalises every bit-select to a base name because its job is
# cross-VIEW name identity. This gate asks a different question: how many
# logical pin bits the Verilog declaration exposes. Sharing the normalised set
# is the historical defect issue #1989 measured.
_V_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_V_MODULE_START_RE = re.compile(
    r"\bmodule\s+(?:automatic\s+)?(?:\\\S+|[A-Za-z_][\w$]*)")
_V_DIRECTION_RE = re.compile(r"^\s*(input|output|inout)\b(?P<rest>.*)$", re.S)
_V_IDENTIFIER_RE = re.compile(r"\\\S+|[A-Za-z_][\w$]*")
_V_RANGE_RE = re.compile(r"\[([^\]]+)\]")
_V_DECL_RE = re.compile(r"\b(input|output|inout)\b(?P<rest>[^;]*);", re.S)
_V_PARAM_RE = re.compile(
    r"\b(?:parameter|localparam)\b"
    r"(?:\s+(?:integer|int|longint|shortint|byte|logic|reg|signed|unsigned))*"
    r"\s+(?P<name>[A-Za-z_][\w$]*)\s*=\s*(?P<value>[^,;)]+)", re.S)
_V_ATTRIBUTE_RE = re.compile(r"\(\*.*?\*\)", re.S)
_V_KEYWORDS = {"wire", "reg", "logic", "signed", "unsigned", "var",
               "tri", "wand", "wor", "supply0", "supply1"}


def _balanced(text: str, start: int) -> Optional[Tuple[str, int]]:
    """Text inside the parenthesis at ``start`` and the index after it."""
    if start >= len(text) or text[start] != "(":
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
    return None


def _module_parts(v_text: str) -> Optional[Tuple[str, str, str]]:
    text = strip_comments(v_text)
    module = _V_MODULE_START_RE.search(text)
    if module is None:
        return None
    pos = module.end()
    while pos < len(text) and text[pos].isspace():
        pos += 1
    parameters = ""
    if pos < len(text) and text[pos] == "#":
        pos += 1
        while pos < len(text) and text[pos].isspace():
            pos += 1
        group = _balanced(text, pos)
        if group is None:
            return None
        parameters, pos = group
    open_header = text.find("(", pos)
    if open_header < 0:
        return None
    group = _balanced(text, open_header)
    if group is None:
        return None
    header, after_header = group
    semicolon = text.find(";", after_header)
    if semicolon < 0:
        return None
    endmodule = text.find("endmodule", semicolon + 1)
    body = text[semicolon + 1:endmodule if endmodule >= 0 else len(text)]
    return parameters, header, body


def _split_top_level_commas(text: str) -> List[str]:
    out: List[str] = []
    start = 0
    paren = bracket = brace = 0
    for index, char in enumerate(text):
        if char == "(":
            paren += 1
        elif char == ")" and paren:
            paren -= 1
        elif char == "[":
            bracket += 1
        elif char == "]" and bracket:
            bracket -= 1
        elif char == "{":
            brace += 1
        elif char == "}" and brace:
            brace -= 1
        elif char == "," and paren == bracket == brace == 0:
            out.append(text[start:index])
            start = index + 1
    out.append(text[start:])
    return out


def _sv_literal_to_decimal(match: re.Match) -> str:
    width, base, digits = match.group(1), match.group(2).lower(), match.group(3)
    del width
    if any(char in digits.lower() for char in "xz?"):
        raise ValueError("unknown digit in a width expression")
    return str(int(digits.replace("_", ""), {"b": 2, "o": 8,
                                               "d": 10, "h": 16}[base]))


_SV_LITERAL_RE = re.compile(r"(?:(\d+))?'[sS]?([bBoOdDhH])([0-9a-fA-F_xXzZ?]+)")


def _integer_expr(expr: str, parameters: Dict[str, int]) -> Optional[int]:
    try:
        expr = _SV_LITERAL_RE.sub(_sv_literal_to_decimal, expr.strip())
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError):
        return None

    def walk(node) -> int:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return int(node.value)
        if isinstance(node, ast.Name) and node.id in parameters:
            return parameters[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = walk(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, (ast.Div, ast.FloorDiv)):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.LShift):
                return left << right
            if isinstance(node.op, ast.RShift):
                return left >> right
        raise ValueError("unsupported width expression")

    try:
        return walk(tree)
    except (ValueError, ZeroDivisionError):
        return None


def _parameter_values(parameter_text: str, body: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for match in _V_PARAM_RE.finditer(parameter_text + ";" + body):
        value = _integer_expr(match.group("value"), out)
        if value is not None:
            out[match.group("name")] = value
    return out


def _packed_width(text: str, parameters: Dict[str, int]) -> Optional[int]:
    ranges = _V_RANGE_RE.findall(text)
    if not ranges:
        return 1
    width = 1
    for packed in ranges:
        if ":" not in packed:
            return None
        msb_text, lsb_text = packed.split(":", 1)
        msb = _integer_expr(msb_text, parameters)
        lsb = _integer_expr(lsb_text, parameters)
        if msb is None or lsb is None:
            return None
        width *= abs(msb - lsb) + 1
    return width


def _declared_name(text: str) -> Optional[str]:
    text = text.split("=", 1)[0]
    text = _V_RANGE_RE.sub(" ", text)
    names = [m.group(0) for m in _V_IDENTIFIER_RE.finditer(text)
             if m.group(0).lower() not in _V_KEYWORDS]
    return names[-1] if names else None


def verilog_port_widths(v_text: str) -> Optional[List[Tuple[str, str, int]]]:
    """ANSI/non-ANSI logical ports with packed widths expanded to bit counts.

    ``None`` means the representation could not be settled (including an
    unresolved symbolic range); an empty list means a readable zero-port
    module. The caller reports the former loudly instead of silently treating
    an unknown width as one bit.
    """
    parts = _module_parts(v_text)
    if parts is None:
        return None
    parameter_text, header, body = parts
    # Keep the safety dataflow explicit at each declaration scan. The helper
    # already strips, but the census intentionally does not infer safety across
    # function returns.
    parameter_text = strip_comments(parameter_text)
    header = strip_comments(header)
    body = strip_comments(body)
    parameters = _parameter_values(parameter_text, body)
    rows: List[Tuple[str, str, int]] = []
    if re.search(r"\b(?:input|output|inout)\b", header):
        direction = ""
        width: Optional[int] = 1
        for chunk in _split_top_level_commas(_V_ATTRIBUTE_RE.sub(" ", header)):
            match = _V_DIRECTION_RE.match(chunk)
            payload = chunk
            if match:
                direction = match.group(1).lower()
                payload = match.group("rest")
                width = _packed_width(payload, parameters)
            if not direction or width is None:
                return None
            name = _declared_name(payload)
            if name is not None:
                rows.append((name, direction, width))
    else:
        for match in _V_DECL_RE.finditer(body):
            direction = match.group(1).lower()
            payload = match.group("rest")
            width = _packed_width(payload, parameters)
            if width is None:
                return None
            for chunk in _split_top_level_commas(payload):
                name = _declared_name(chunk)
                if name is not None:
                    rows.append((name, direction, width))
    deduped: Dict[str, Tuple[str, str, int]] = {}
    for row in rows:
        deduped.setdefault(row[0], row)
    return list(deduped.values())


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


def _subsection_body(text: str, title: str) -> Optional[str]:
    marker = f"### {title}"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != marker:
            continue
        body: List[str] = []
        for following in lines[index + 1:]:
            if following.startswith("## ") or following.startswith("### "):
                break
            body.append(following)
        return "\n".join(body)
    return None


def _check_ip_interface_disclosures(texts: Dict[str, str], release: str,
                                    findings: List[Finding]) -> None:
    """The datasheet must show the interface, not only three summary counts."""
    text = texts.get(IP_DATASHEET)
    if text is None:
        return
    for title, rule, required_headers in (
        ("Pin Table", "PIN_TABLE_ABSENT", ("Pin", "Direction", "Width")),
        ("Hardened Parameter Set", "HARDENED_PARAMETER_SET_ABSENT",
         ("Field", "Value", DERIVED_COLUMN)),
    ):
        body = _subsection_body(text, title)
        header = next((line for line in (body or "").splitlines()
                       if line.strip().startswith("|")), "")
        cells = _cells(header.strip()) if header else []
        if body is not None and all(name in cells for name in required_headers):
            continue
        findings.append(Finding(
            rule, "ERROR", release,
            f"{IP_DATASHEET} does not carry a parseable '### {title}' table "
            f"with columns {list(required_headers)}. Summary counts alone do "
            "not tell an integrator which ports or frozen build choices the "
            "delivered macro exposes."))


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
        for token in PLACEHOLDER_TOKENS:
            if token in line:
                hits += 1
                findings.append(Finding(
                    "UNRESOLVED_PLACEHOLDER", "ERROR", release,
                    f"{document}:{lineno} still carries the placeholder "
                    f"{token!r}: {line.strip()!r}"))
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


def _check_source_count_consistency(
        texts: Dict[str, str], rows: Sequence[Row], release: str,
        findings: List[Finding]) -> int:
    """R10 — one document cannot give one source two test-mode counts.

    This is deliberately source-scoped and document-scoped.  Two unrelated
    artefacts can legitimately count different things, and two documents can
    present different subsets.  What cannot be true is the issue-#1990 shape:
    one section says six test modes and another says zero, both claiming the
    same ``L7_TEST_DEBUG.json`` as their authority.
    """
    stated: Dict[Tuple[str, str], Tuple[Row, int]] = {}
    for row in rows:
        if row.label != TEST_MODE_LABEL or row.value == NOT_MEASURED:
            continue
        source_match = SOURCE_PATH_RE.search(row.third)
        if source_match is None:
            continue
        try:
            count = int(row.value)
        except ValueError:
            continue
        stated[(row.document, source_match.group(1))] = (row, count)

    checked = 0
    for document, text in texts.items():
        for line in text.splitlines():
            mandatory = MANDATORY_RE.match(line)
            count_match = TEST_MODE_CLAIM_RE.search(line)
            source_match = CONSTRAINT_SOURCE_RE.search(line)
            if mandatory is None or count_match is None or source_match is None:
                continue
            source = source_match.group("source")
            peer = stated.get((document, source))
            if peer is None:
                continue
            checked += 1
            row, row_count = peer
            constraint_count = int(count_match.group("count"))
            if constraint_count == row_count:
                continue
            findings.append(Finding(
                "SOURCE_COUNT_INCONSISTENT", "ERROR", release,
                f"{document} states {constraint_count} test mode(s) in "
                f"mandatory constraint `{mandatory.group('id')}`, while its "
                f"'{row.label}' row states {row_count}; both claim "
                f"`{source}` as their derivation source. Sections of one "
                f"document cannot disagree about the same source artefact."))
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


#: Where the chip path's route leaves its gate-level netlist. A glob, because
#: the emitter names it after the design and a design name is exactly the
#: literal a chip-AGNOSTIC gate may not carry.
IC_NETLIST_GLOB = "phase3/stage3/pnr/*_pnr.v"


def _netlist_signal_ports(project: Path, arm: str, release: str,
                          ip_views: Optional[Mapping[str, Path]] = None
                          ) -> Optional[Tuple[int, Path, Set[str]]]:
    """The logical pin-bit count a SECOND view declares, re-derived here.

    IP arm: the delivered blackbox Verilog beside the LEF the document was
    written off. IC arm: the gate-level netlist the route produced beside the
    DEF the document was written off. Same shape in both — a different view,
    read by a different program from the one that wrote the number — because a
    count re-derived from the SAME artefact the document cited proves only that
    the generator can read its own output.

    Returns None when this arm has no second view, which is reported as
    NOT DETERMINED rather than accepted.
    """
    if arm == "ip":
        views = (dict(ip_views) if ip_views is not None else
                 _hm.discover_packages(_hm.hardmacro_dir(project)).get(release, {}))
        v_path = views.get(".v")
        if v_path is None:
            return None
    else:
        # NOT A GUESS BETWEEN CANDIDATES. Two gate-level netlists is two
        # answers, and picking one would make the cross-check depend on sort
        # order — a gate whose verdict moves with a filename is not a gate.
        hits = sorted(project.glob(IC_NETLIST_GLOB))
        if len(hits) != 1:
            return None
        v_path = hits[0]
    ports = verilog_port_widths(
        v_path.read_text(encoding="utf-8", errors="replace"))
    if ports is None:
        return None
    if arm == "ip" and ip_views is not None:
        pg = _explicit_ip_supplies(project, release, ip_views)
        present = {name for name, _direction, _width in ports} & set(pg)
        if present and present != set(pg):
            raise ValueError("Verilog declares only part of the independent PG interface")
        if any(direction != "inout" or width != 1
               for name, direction, width in ports if name in pg):
            raise ValueError("Verilog PG terminals must be scalar inout ports")
        ports = [row for row in ports if row[0] not in pg]
    # The NAMES come back too: whether this netlist declares the pins the DEF
    # marks as supplies is a question about names, and it is the only thing
    # that decides which of the two conventions it follows. Assuming either
    # one was the defect.
    return (sum(width for _name, _direction, width in ports), v_path,
            {str(n) for n, _d, _w in ports})


def _explicit_ip_supplies(project: Path, release: str,
                          views: Mapping[str, Path]) -> Dict[str, str]:
    import hardmacro_supply_intent as supply
    for suffix in (".lef", ".lib", ".v"):
        raw = views.get(suffix)
        if (raw is None or raw.is_symlink() or not raw.is_file()
                or not raw.resolve().is_relative_to(project.resolve())):
            raise ValueError("explicit IP views must be project-contained regular files")
    lef = {row["pin"]: row["use"] for row in supply.lef_pg_pins(
        views[".lef"].read_text()) if row["master"] == release}
    lib = {row["pin"]: row["use"] for row in supply.liberty_pg_pins(
        views[".lib"].read_text()) if row["cell"] == release}
    if lef != lib or any(value not in ("POWER", "GROUND") for value in lef.values()):
        raise ValueError("LEF and Liberty disagree on PG names or polarity")
    return lef



def _supplies_are_the_designs(project: Path, arm: str, release: str,
                              signal, supply, total,
                              netlist_count: int,
                              netlist_port_names: Set[str]
                              ) -> Tuple[bool, str]:
    """May the netlist's bit count be read as signal + supply for THIS design?

    Every clause here closes a hole the pre-landing review (2026-09-23) opened
    and reproduced. The first version asked only `netlist_count == signal +
    supply`, which anchors to nothing: the supply row was a free variable the
    document itself supplied, so a datasheet could move pins out of the signal
    row into the supply row and the arithmetic would follow it.

      * IC ARM ONLY. The IP arm's delivered blackbox omits supplies BY
        CONTRACT, so `netlist == signal + supply` there means the signal row is
        SHORT by exactly the supply count. The old code accepted it on both
        arms.
      * THE NETLIST MUST ACTUALLY DECLARE THEM. OpenROAD `write_verilog` omits
        power ports unless asked (`-include_pwr_gnd`), so a routed netlist of
        pure signal bits could still match signal + supply on a datasheet
        carried forward from a build with fewer signals. Whether this netlist
        follows the convention is decided by whether the pins the DEF MARKS as
        supplies appear among its ports -- measured, from two different files.
      * BOTH ROWS COME FROM THE DESIGN. `signal` and `supply` are checked
        against the DEF's own USE SIGNAL / USE POWER|GROUND split, so neither
        is a free variable and pins cannot be moved between them.
      * THE ARITHMETIC IS REQUIRED, NOT ASSUMED. The comment used to claim the
        parts check guarded this; it does not -- it runs only when the total
        row is present. A document whose total is absent or NOT_MEASURED
        reached the second reading with no arithmetic check at all.
    """
    if arm != "ic":
        return False, "the second reading is the IC arm's; this is the IP arm"
    if supply is None:
        return False, "the document states no supply row to read the netlist with"
    try:
        facts = _art.audit(project, release).by_id("def").facts
    except Exception:  # pragma: no cover - an unreadable audit is not an OK
        return False, "the routed DEF could not be read to settle the split"
    def_signal = facts.get("signal_pins")
    def_supply = facts.get("supply_pins")
    def_supply_names = set(facts.get("supply_pin_names") or ())
    if not isinstance(def_signal, int) or not isinstance(def_supply, int):
        return False, "the routed DEF states no signal/supply pin split"
    if not def_supply_names or not def_supply_names <= netlist_port_names:
        return False, ("the netlist does not declare the pin(s) the routed DEF "
                       "marks USE POWER/GROUND, so its bit count is the "
                       "logical interface alone")
    if signal[1] != def_signal or supply[1] != def_supply:
        return False, (f"the routed DEF marks {def_signal} signal and "
                       f"{def_supply} supply pin(s), not "
                       f"{signal[1]} and {supply[1]}")
    if total is None or total[1] != signal[1] + supply[1]:
        return False, ("the document states no total equal to its own signal "
                       "plus supply rows")
    return netlist_count == signal[1] + supply[1], ""


def _check_pin_count(project: Path, arm: str, release: str,
                     rows: Sequence[Row], findings: List[Finding],
                     ip_views: Optional[Mapping[str, Path]] = None) -> str:
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

    AND WHETHER A GIVEN NETLIST FOLLOWS THAT CONVENTION IS MEASURED. The IP
    arm's delivered blackbox omits the supplies; a routed `chip_top` declares
    them as ports (`inout VDD; inout VSS;`) and its bit count is therefore the
    TOTAL, not the signal count. Assuming the IP convention on the IC arm
    failed a correct datasheet — see the comment at the comparison below, which
    carries the measurement.

    EVERY DOCUMENT THAT STATES A COUNT IS CHECKED, not the first one found. Two
    documents in this set carry the interface table; taking the first match
    would let a correct datasheet mask an edited integration guide, which is
    precisely the drift a cross-check exists to catch. Both comparisons run for
    every document — an early return after one finding would leave the OTHER
    defect unreported in the same run.
    """
    try:
        netlist = _netlist_signal_ports(project, arm, release, ip_views)
        pg = (_explicit_ip_supplies(project, release, ip_views)
              if arm == "ip" and ip_views is not None else None)
    except (OSError, ValueError) as exc:
        findings.append(Finding("IP_SUPPLY_IDENTITY_MISMATCH", "ERROR", release, str(exc)))
        return "DISAGREES"
    states: List[str] = []
    for document in sorted({row.document for row in rows}):
        signal = _stated(rows, document, SIGNAL_PIN_LABEL)
        supply = _stated(rows, document, SUPPLY_PIN_LABEL)
        total = _stated(rows, document, PIN_COUNT_LABEL)
        if signal is None and supply is None and total is None:
            continue
        if pg is not None and (supply is None or supply[1] != len(pg)
                or signal is None or total is None
                or total[1] != signal[1] + len(pg)):
            findings.append(Finding("IP_SUPPLY_COUNT_MISMATCH", "ERROR", release,
                                    f"{document} counts disagree with independent PG views"))
            states.append("DISAGREES")

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
            where = (_hm.hardmacro_dir(project).as_posix() + "/*.v"
                     if arm == "ip" else IC_NETLIST_GLOB)
            findings.append(Finding(
                "PIN_COUNT_NOT_CROSS_CHECKED", "INFO", release,
                f"{document} states '{SIGNAL_PIN_LABEL}' = {signal[1]} and "
                f"this run carries no single netlist view at {where}, so the "
                f"count could not be re-derived from a second view. NOT "
                f"DETERMINED, not accepted."))
            states.append("NOT_DETERMINED")
            continue
        netlist_count, v_path, netlist_port_names = netlist
        if netlist_count == signal[1]:
            states.append("AGREES")
            continue
        # WHICH CONVENTION THIS NETLIST FOLLOWS IS MEASURED, NOT ASSUMED.
        #
        # MEASURED on a signed-off IC-arm run (lane icspm5, 2026-09-23). The
        # datasheet stated, all three from the same routed DEF and internally
        # consistent,
        #
        #     Pin count (total) 38 · Signal pins 36 · Supply pins 2
        #
        # and this check refused it: the gate-level netlist the route produced
        # declares 38 logical pin bits, so 36 "disagreed". It did not. The
        # netlist is
        #
        #     module chip_top (VDD, VSS, clk, p, rst, y, x);
        #       inout VDD; inout VSS; ...
        #
        # — the two supplies are ports of it, and 38 is the TOTAL, which is
        # exactly what the document says the total is. The premise written
        # into the docstring above and into the generated datasheet's own
        # prose — "a gate-level netlist conventionally carries the logical
        # interface only" — holds for the IP arm's delivered blackbox and does
        # not hold for a routed chip_top. A cross-check that fails a correct
        # datasheet is the kind that gets deleted rather than the document
        # fixed, and it would have been deleted for a reason that was not
        # true.
        #
        # So the count is compared against BOTH readings of what this netlist
        # could be counting, and the one it matches is reported. THIS IS NOT A
        # SECOND CHANCE TO PASS: `signal + supply` is only reachable when the
        # document's own three rows are arithmetically consistent (checked
        # above, in this same loop, before this point), so an edited signal
        # count cannot reach it — 30/2/32 is caught by the parts check, and
        # 30/2/32 against a 38-bit netlist matches neither reading and still
        # DISAGREES. The only case newly accepted is the one where the
        # netlist's bits ARE the document's stated total.
        with_supplies = (signal[1] + supply[1]) if supply is not None else None
        second_reading, second_refusal = _supplies_are_the_designs(
            project, arm, release, signal, supply, total,
            netlist_count, netlist_port_names)
        if second_reading:
            states.append("AGREES")
            continue
        findings.append(Finding(
            "PIN_COUNT_DISAGREES_WITH_NETLIST", "ERROR", release,
            f"{document} states '{SIGNAL_PIN_LABEL}' = {signal[1]}, derived "
            f"from {signal[0].third}; the netlist view "
            f"`{v_path.relative_to(project).as_posix()}` declares "
            f"{netlist_count} logical pin bit(s)"
            + (f", and the document's signal + supply rows sum to "
               f"{with_supplies}, so the netlist matches neither the logical "
               f"interface alone nor the interface with its supplies"
               if with_supplies is not None else "")
            + (f" ({second_refusal})" if second_refusal else "")
            + ". A datasheet with a pin count no view supports is stale on "
              "arrival."))
        states.append("DISAGREES")

    if not states:
        return "NOT_STATED"
    for tier in ("UNREADABLE", "DISAGREES", "INTERNALLY_INCONSISTENT",
                 "NOT_DETERMINED"):
        if tier in states:
            return tier
    return "AGREES"




#: `metrics.json`'s own name for the die bounding box, and the label the IC
#: datasheet states the same quantity under. Spelled here so the gate and the
#: producer cannot drift into cross-checking two different things.
IC_METRICS_REL = "phase3/final/metrics.json"
IC_DIE_BBOX_KEY = "design__die__bbox"
IC_WIDTH_LABEL = "Die width (um)"
IC_HEIGHT_LABEL = "Die height (um)"

#: How far the two derivations may differ before the gate calls it a
#: disagreement. NOT a tolerance on the design — a tolerance on the ROUNDING
#: the two writers apply: the document rounds to 3 decimal places and a metrics
#: writer commonly rounds to 1. Anything wider would let a real edit through,
#: and anything narrower would redden every correct run on the third decimal.
IC_DIE_TOLERANCE_UM = 0.11


def _check_die_area(project: Path, release: str, rows: Sequence[Row],
                    findings: List[Finding]) -> str:
    """R3ic — the stated die outline, against the metrics the sign-off read.

    THE DOCUMENT DERIVED IT FROM THE DEF and this re-derives it from
    `metrics.json` — a DIFFERENT artefact, written by a DIFFERENT producer —
    for the reason the pin cross-check exists: a number re-derived from the
    artefact the document cited proves only that the generator can read its own
    output. A die size edited after generation, or carried forward from an
    earlier build, disagrees with the tree instead of being believed.

    The finding names BOTH sides with BOTH paths, because "the die size is
    wrong" is not actionable and "240 x 160 here, 180 x 120 there" is.
    """
    metrics_path = project / IC_METRICS_REL
    doc = _load_json(metrics_path)
    bbox = doc.get(IC_DIE_BBOX_KEY) if isinstance(doc, dict) else None
    parts = str(bbox).split() if isinstance(bbox, str) else []
    coords = None
    if len(parts) == 4:
        try:
            coords = tuple(float(token) for token in parts)
        except ValueError:
            coords = None
    if coords is None:
        # DISCLOSED, NOT SILENT, and the same reading the pin cross-check emits
        # when it has no second view: a cross-check that could not run and a
        # cross-check that agreed must never print the same nothing.
        if any(row.label in (IC_WIDTH_LABEL, IC_HEIGHT_LABEL)
               and row.value != NOT_MEASURED for row in rows):
            findings.append(Finding(
                "DIE_SIZE_NOT_CROSS_CHECKED", "INFO", release,
                f"this release states a die size and `{IC_METRICS_REL}` "
                f"carries no readable `{IC_DIE_BBOX_KEY}`, so the outline "
                f"could not be re-derived from a second artefact. NOT "
                f"DETERMINED, not accepted."))
        return "NOT_DETERMINED"
    x0, y0, x1, y1 = coords
    expected = {IC_WIDTH_LABEL: abs(x1 - x0), IC_HEIGHT_LABEL: abs(y1 - y0)}

    states: List[str] = []
    for document in sorted({row.document for row in rows}):
        for label, want in expected.items():
            stated = _stated_float(rows, document, label)
            if stated is None:
                continue
            row, value = stated
            if value < 0:
                findings.append(Finding(
                    "DIE_SIZE_UNREADABLE", "ERROR", release,
                    f"{document} states '{label}' = {row.value!r}, which is "
                    f"not a length."))
                states.append("UNREADABLE")
                continue
            if abs(value - want) <= IC_DIE_TOLERANCE_UM:
                states.append("AGREES")
                continue
            findings.append(Finding(
                "DIE_SIZE_DISAGREES_WITH_METRICS", "ERROR", release,
                f"{document} states '{label}' = {value:g} um, derived from "
                f"{row.third}; `{IC_METRICS_REL}` states "
                f"{IC_DIE_BBOX_KEY} = {bbox!r}, which is {want:g} um on that "
                f"axis. A datasheet with a die size no artefact supports is "
                f"stale on arrival."))
            states.append("DISAGREES")
    if not states:
        return "NOT_STATED"
    for tier in ("UNREADABLE", "DISAGREES"):
        if tier in states:
            return tier
    return "AGREES"


def _stated_float(rows: Sequence[Row], document: str,
                  label: str) -> Optional[Tuple[Row, float]]:
    """The length ONE document states for `label`, or None when it states none.

    A NOT_MEASURED row is NOT a stated length and is deliberately not read as
    zero, for the reason `_stated` records: "we did not look" and "we looked
    and it is zero" must never reach the same comparison.
    """
    for row in rows:
        if row.document != document or row.label != label:
            continue
        if row.value == NOT_MEASURED:
            continue
        try:
            return row, float(row.value)
        except ValueError:
            return row, -1.0
    return None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None




def _check_artefact_substance(project: Path, release: str,
                              findings: List[Finding]) -> str:
    """R9 — the artefacts these documents describe must have something IN them.

    THE GATE ASKS THIS AGAIN, HAVING ALREADY BEEN ASKED BY THE PRODUCER, and
    the repetition is the point. `ic_release_docs_gen` refuses to WRITE a
    document set over a hollow artefact — but documents are FILES: they outlive
    the run, they get copied forward, and an artefact hollowed out AFTER
    generation leaves a beautiful document set describing a die with nothing on
    it. A producer-side refusal alone would mean the check only ever ran at the
    one moment the tree was known good.

    The predicate is `_ic_release_artefacts.audit` — the SAME one the producer
    used, imported rather than restated, so the two can never disagree about
    what "hollow" means.

    IC ARM ONLY. The IP arm's equivalent is `digital_hardmacro_check`, which
    step 37.5ip already declares in the same `gate.all_of` as this program;
    running a second substance audit over the same kit would give that step two
    verdicts over one population.
    """
    # SCOPED TO THIS RELEASE. The sign-off GDS is per-release, and auditing
    # every release's layout for every release would make one hollow stream
    # redden a second, untouched release — a refusal that is environmental
    # rather than content-earned, which is what the control release exists to
    # detect.
    audit = _art.audit(project, release)
    for finding in audit.errors:
        findings.append(Finding(
            finding.rule, "ERROR", release,
            f"{finding.artefact_class}: `{finding.path}` — {finding.message} "
            f"The document set in this release describes it as if it carried "
            f"the work."))
    if audit.errors:
        return "REFUSED"
    return "CLEAN" if audit.any_present else "NOTHING_PRESENT"






# ── one release ────────────────────────────────────────────────────────────
def check_release(project: Path, arm: str, release_dir: Path,
                  release: str, *,
                  ip_views: Optional[Mapping[str, Path]] = None,
                  expected_constraints=None) -> Tuple[List[Finding], dict]:
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
    observed_constraints = []
    if expected_constraints is not None:
        for constraint in expected_constraints:
            expected = constraint_ids(constraint.line())[constraint.cid]
            statements = [match.group("text") for name in CONSTRAINT_BEARING[arm]
                          for line in texts.get(name, "").splitlines()
                          if (match := MANDATORY_RE.match(line)) and match.group("id") == constraint.cid]
            if (statements and all(text == expected for text in statements)
                    and (project / constraint.source).is_file()):
                observed_constraints.append({"cid": constraint.cid, "text": constraint.text,
                                             "source": constraint.source})
            else:
                findings.append(Finding(
                    "MANDATORY_CONSTRAINT_ABSENT_OR_CHANGED", "ERROR", release,
                    f"{constraint.cid} must carry its current text and source "
                    f"in {list(CONSTRAINT_BEARING[arm])}."))
    source_counts_checked = _check_source_count_consistency(
        texts, rows, release, findings)
    if arm == "ip":
        _check_ip_interface_disclosures(texts, release, findings)
    # BOTH ARMS NOW, and the `arm == "ip"` guard that stood here is the defect
    # it removed: the IC arm carried the same three interface rows and NOTHING
    # re-derived any of them, so a hand-edited chip pin count was believed.
    pin_state = _check_pin_count(project, arm, release, rows, findings, ip_views)
    die_state = (_check_die_area(project, release, rows, findings)
                 if arm == "ic" else "NOT_APPLICABLE")
    substance = (_check_artefact_substance(project, release, findings)
                 if arm == "ic" else "NOT_APPLICABLE")
    detail = {
        "release": release,
        "directory": release_dir.as_posix(),
        "documents_present": sorted(texts),
        "derived_fields": derived,
        "not_measured_fields": holes,
        "rows_examined": len(rows),
        "mandatory_constraints_in_app_notes": constraints_checked,
        "observed_constraints": observed_constraints,
        "same_source_count_comparisons": source_counts_checked,
        "placeholders": placeholders,
        "pin_count_cross_check": pin_state,
        "die_size_cross_check": die_state,
        "artefact_substance": substance,
        "pass": not any(f.severity == "ERROR" for f in findings),
    }
    return findings, detail


# ── the run ────────────────────────────────────────────────────────────────
#: Spelled once, and only for the absence report: the search space this gate
#: looked in when it found nothing. An absence verdict that does not name where
#: it looked is a claim nobody can re-check.
KIT_DIR_GLOB = "phase3/stage4/hardmacro/*.{{lef,lib,gds,v}} (arm {arm})"
IC_RELEASE_GLOB = "phase3/stage4/gds/*.gds (arm {arm})"


def _searched_glob(arm: str) -> str:
    """Where THIS arm looked for a release it should have documented."""
    return (IC_RELEASE_GLOB if arm == "ic" else KIT_DIR_GLOB).format(arm=arm)


def expected_releases(project: Path, arm: str) -> List[str]:
    """The releases this arm SHOULD have documented, from the tree itself.

    For the IP arm the answer is the delivered hardmacro packages: one kit, one
    document set. For the IC arm it is the sign-off layouts — one die, one
    document set — derived by ``_ic_release_artefacts.releases`` from
    ``phase3/stage4/gds/*.gds``, which is step 37.5ic's own declared input.

    DERIVING IT RATHER THAN READING THE DOCUMENTATION DIRECTORY IS THE WHOLE
    POINT, and until this landed the IC arm did neither: it returned `[]`
    unconditionally, so a run that signed off a die and wrote NOT ONE document
    reached the `not expected and not present` branch below and was scored
    NOT_DETERMINED — a PASS tier. The arm was declared, wired to nothing, and
    could only ever answer "nothing to examine". That is the v1.13.42 shape
    this gate's own docstring was written about, reproduced inside the gate
    that was written to end it.

    Reading the tree makes "the die was signed off and nobody documented it" a
    refusal with a name instead of an empty sweep that passes.
    """
    if arm == "ip":
        return sorted(_hm.discover_packages(_hm.hardmacro_dir(project)))
    if arm == "ic":
        return _art.releases(project)
    return []


#: The producer's own refusal record. R-0915-144, and the IC arm only, because
#: `ic_release_docs_gen` is the producer that writes one.
PRODUCER_REFUSAL_REL = "reports/phase3/release_docs_producer_refusal.json"


#: Where the producer's metrics live, read through the SAME loader the producer and
#: `tapeout_docs_gen` use. A second metrics reader would be a second answer to
#: "what did this run measure".
PRODUCER_METRICS_REL = "phase3/final/metrics.json"


#: The metrics record the producer reads, and the flow step that DECLARES it.
PRODUCER_METRICS_REL = "phase3/final/metrics.json"

#: A step's own published verdict for THIS run lives here, keyed by the step id --
#: `reports/metrics/<sid>.json` carrying `<sid>__flow__step_status`. That is the
#: record `flow_compliance_check` writes for the step itself, which is why it is the
#: right authority: it is the step's verdict, not another program's opinion of the
#: step's files.
_STEP_STATUS_REL_FMT = "reports/metrics/{sid}.json"
_STEP_STATUS_KEY_FMT = "{sid}__flow__step_status"
#: NOT a step's verdict: this reader's statement that it could not read one for this run.
#: Deliberately outside `_BLOCKING_STEP_STATUSES` -- see `step_verdict_now`.
_VERDICT_UNREADABLE = "UNREADABLE"

#: A step's verdict counts as a BLOCKAGE only in these tiers. R-0915-140's shape.
_BLOCKING_STEP_STATUSES = frozenset({"FAIL", "NOT_MEASURED", "BLOCKED",
                                     "INCOMPLETE"})


def _declaring_step(rel: str) -> Optional[str]:
    """The flow step that DECLARES this path as a required_output, glob-aware.

    DERIVED FROM THE FLOW, not tabled: a table mapping a refusal class to a step
    goes stale the first time a step is renumbered, and this question already has an
    answer in the flow definition. `reports/phase3/sta/post_route_summary.json` is
    step 23's; `reports/phase3/power.json` is step 33's;
    `phase3/stage4/gds/*.gds` is step 37's; `phase3/final/metrics.json` is 37.4's.
    """
    import fnmatch
    try:
        doc = yaml.safe_load(
            (Path(__file__).resolve().parent.parent
             / "flow" / "phase1_phase2_phase3.yaml").read_text())
    except (OSError, ValueError):                          # pragma: no cover
        return None
    for step in (doc or {}).get("steps") or []:
        if not isinstance(step, dict):
            continue
        for declared in (step.get("required_outputs") or []):
            for alt in str(declared).split(" OR "):
                alt = alt.strip()
                if not alt:
                    continue
                if alt == rel or fnmatch.fnmatch(rel, alt):
                    return str(step.get("id"))
    return None


def _metrics_row(project: Path, sid: str) -> Tuple[Optional[dict], str, str]:
    """`(row, normalised_sid, why_not)` for the step's metrics record.

    THE NAME IS `step_metrics`' TO SPELL, not this reader's. R-0915-152.
    `_STEP_STATUS_REL_FMT.format(sid=sid)` builds `reports/metrics/37.4.json`, and the file
    `step_metrics.emit` actually writes is `reports/metrics/37_4.json` -- it normalises a
    step id before using it as a filename or a key component. MEASURED across the ids this
    flow uses:

        23     -> 23        37.4   -> 37_4      0.5ic -> 0_5ic
        33     -> 33        37.5ic -> 37_5ic    M1    -> m1

    So every dotted or suffixed step -- and `M1`, which also lowercases -- was looked for at
    a path nothing writes and under a key nothing emits: the verdict read ABSENT, which is
    not in `_BLOCKING_STEP_STATUSES`, so an upstream step that had genuinely FAILED was
    recorded as passing and 37.5ic took the blame for it. The normalisation is imported from
    the module that owns it rather than reproduced here, so the two cannot drift.
    """
    try:
        import step_metrics as _sm                          # noqa: PLC0415
        sid_n = _sm.normalize_step(sid)
        rel = f"{_sm.METRICS_REL}/{sid_n}.json"
    except Exception:                                       # pragma: no cover
        sid_n, rel = sid, _STEP_STATUS_REL_FMT.format(sid=sid)
    path = project / rel
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None, sid_n, f"no step record at {rel}"
    if not isinstance(doc, dict):
        return None, sid_n, f"{rel} is not an object"
    return doc, sid_n, ""


def _artefact_present(project: Path, rel: str) -> bool:
    """Did the run leave this declared artefact on disk?

    NOT USED TO DECIDE AN EXCUSE, and the reason is measured -- see the note on
    `upstream_blockage_now`. Kept because it is the correct spec-shape reader and the question
    "did the step produce it at all" is one a reader of this gate's record will want.

    Glob- and `A OR B`-aware, because that is the shape `required_outputs` uses, and
    permissive in the same direction as `flow_declared_producer_run._glob_exists`: a false NO
    grants an excuse that was not earned, so anything that matches counts as produced.
    """
    if not rel:
        return False
    for alt in (a.strip() for a in str(rel).split(" OR ")):
        if not alt:
            continue
        if any(ch in alt for ch in "*?["):
            try:
                if next(iter(Path(project).glob(alt)), None) is not None:
                    return True
            except (OSError, ValueError):
                continue
        elif (Path(project) / alt).exists():
            return True
    return False


def _entry_covers(entry: str, rel: str) -> bool:
    """Does a declared-output ENTRY cover the artefact path `rel`?

    Same matching `_declaring_step` uses to find the entry in the first place -- `A OR B` split
    then fnmatch -- because the record holds DECLARATION patterns
    (`phase3/stage4/gds/*.gds`) while the producer names the concrete file it read
    (`phase3/stage4/gds/zzdie.gds`). Two spellings of one match is how they come to disagree.
    """
    import fnmatch                                           # noqa: PLC0415
    for alt in (a.strip() for a in str(entry).split(" OR ")):
        if not alt:
            continue
        if alt == rel or fnmatch.fnmatch(rel, alt) or fnmatch.fnmatch(alt, rel):
            return True
    return False


def upstream_blockage_is_about(project: Path, sid: str, rel: str) -> Tuple[bool, str]:
    """`(is_about, why)` -- does the step's record name `rel` as missing, unusable or unresolved?

    R-0915-165, and it is the condition that was missing. The upstream step's VERDICT stays the
    authority (R-0915-149); this asks the separate question the verdict cannot answer, which is
    what that verdict is ABOUT.

    FAILS CLOSED, deliberately. No record, a record from another invocation, or a record naming
    none of the lists -> NOT about this artefact, so no excuse. That is the direction
    `test_a_step_with_no_published_verdict_is_not_an_excuse` already rules: "no evidence" must
    never read as "blocked".

    The step folders' `outputs.json` is NEVER consulted. It is a restatement of the declaration
    and it lies -- measured on a converged run, 7 of 90 entries, every folder marked
    `"status": "pass"`, name a `rel` that does not exist in the run directory.
    """
    try:
        import _path_layout as _pl_                          # noqa: PLC0415
        rec_path = _pl_.step_output_record_path(project, sid)
    except Exception:                                        # pragma: no cover
        return False, f"the per-step output record path for step {sid} is unresolvable"
    try:
        rec = json.loads(rec_path.read_text(errors="replace"))
    except (OSError, ValueError):
        return False, (
            f"step {sid} published no per-step output record in this run, so what its "
            f"blockage is about cannot be read; no record, no excuse")
    if not isinstance(rec, dict):
        return False, f"step {sid}'s output record is not an object"
    mine = os.environ.get("VIBEIC_FCC_INVOCATION", "").strip()
    wrote = str(rec.get("invocation") or "").strip()
    if mine and wrote and wrote != mine:
        return False, (
            f"step {sid}'s output record was written by invocation {wrote}, not this one "
            f"({mine}), so it describes an earlier run")
    for field_ in ("missing", "unusable", "unresolved"):
        if field_ == "unresolved" and mine and wrote != mine:
            continue
        for entry in (rec.get(field_) or []):
            if isinstance(entry, str) and _entry_covers(entry, rel):
                return True, (
                    f"step {sid}'s own gate reported {entry} as {field_}, which covers "
                    f"{rel}")
    return False, (
        f"step {sid} is blocked, but its own record names {rel} in neither `missing` nor "
        f"`unusable`, and not in `unresolved` -- so its blockage is not about the artefact this release needed")


def step_verdict_now(project: Path, sid: str) -> Tuple[str, str]:
    """The step's OWN published verdict IN THIS RUN, or why it cannot be read.

    "IN THIS RUN" is the part that was missing, and it is the difference between a
    measurement and a leftover. `reports/metrics/<sid>.json` persists across runs, so a row
    written by an EARLIER run reads exactly like this one's -- and a step that failed once
    then excused 37.5ic's missing documents on every later run, however well that step went
    afterwards. Two separate defects fed it:

      * `_emit_step_metrics` could not refresh its OWN `step_status`, because its
        no-clobber filter -- written to stop the wrapper overwriting a PROGRAM's
        measurement -- also stopped it overwriting the wrapper's previous value. Fixed at
        the source, with its own arm.
      * and nothing in the row said WHICH invocation measured it. It does now, and this
        reader requires it to be the invocation the audit spawned it from
        (`VIBEIC_FCC_INVOCATION`, inherited through the environment exactly as the gate
        child inherits its role).

    A row from another invocation, or one with no invocation at all, is NOT this run's
    verdict. It is reported as `UNREADABLE`, WITH the reason, and `UNREADABLE` IS ITS OWN
    TIER: deliberately not `NOT_MEASURED`, and deliberately not blocking.

    WHY NOT `NOT_MEASURED`, WHICH IS WHAT A READER WOULD EXPECT. `NOT_MEASURED` is one of
    `_BLOCKING_STEP_STATUSES` -- a tier a step publishes ABOUT ITSELF, having measured and
    refused, and that genuinely blocks. "I could not read this step's verdict" is a
    different statement, made by this reader about its own evidence, and folding the two
    together would make an unreadable record an EXCUSE: delete every
    `reports/metrics/*.json` and 37.5ic's missing documents are forgiven for ever. That
    inverts the ruling `test_a_step_with_no_published_verdict_is_not_an_excuse` already
    holds -- "a step that has published NOTHING in this run has no verdict, so there is no
    evidence of blockage and the documents are still owed; 'no evidence' must never read as
    'blocked'". So `UNREADABLE` does not excuse, and it is NAMED in
    `upstream_verdicts_unreadable` so that a reader can see the gap rather than infer it
    from silence. That is the whole change: absence was silently PASSING before, and now it
    is silently nothing but said out loud.

    THE THREADED PATH IS THE SAME ANSWER. When steps are evaluated concurrently an upstream
    step's row may legitimately not exist yet when this gate runs -- neither evidence that
    it failed nor that it passed. `UNREADABLE`, disclosed, absence named.
    """
    doc, sid_n, why = _metrics_row(project, sid)
    if doc is None:
        return _VERDICT_UNREADABLE, why
    mine = os.environ.get("VIBEIC_FCC_INVOCATION", "").strip()
    wrote = str(doc.get(f"{sid_n}__flow__invocation") or "").strip()
    if mine and wrote and wrote != mine:
        return _VERDICT_UNREADABLE, (
            f"reports/metrics/{sid_n}.json records step {sid}'s verdict from invocation "
            f"{wrote}, not this one ({mine}), so it describes an earlier run")
    if mine and not wrote:
        return _VERDICT_UNREADABLE, (
            f"reports/metrics/{sid_n}.json names no invocation, so it cannot be shown to "
            f"be this run's measurement of step {sid}")
    status = doc.get(f"{sid_n}__flow__step_status")
    if status:
        return str(status).strip().upper(), ""
    # Some steps publish measurements and a `passed` flag instead of a status word.
    passed = doc.get(f"{sid_n}__flow__passed")
    if isinstance(passed, bool):
        return ("PASS" if passed else "FAIL"), ""
    return _VERDICT_UNREADABLE, (
        f"reports/metrics/{sid_n}.json carries no status for step {sid}")


def upstream_blockage_now(project: Path, release: str) -> dict:
    """Is THIS release's upstream blocked — judged by the upstream STEP's own verdict?

    R-0915-146 established that the producer's RECORD is not evidence: a program's
    claim about a state is not the state. R-0915-149 fixes what I replaced it with.

    RE-DERIVING THE PRODUCER'S PREDICATES WAS THE WRONG AUTHORITY, and a review
    caught it with the one measurement that settles it: the flow's OWN healthy
    records do not satisfy those predicates. The runner's `reports/phase3/power.json`
    carries no number BY DESIGN (`eda_report_audit`: "It carries no number of its
    own"), and step 23's `post_route_summary.json` carries the BOOL `has_wns_tns`,
    which the producer's number scan skips. So on every real tree that reaches steps
    23 and 33 the predicates answered STA_NO_SLACK + POWER_NO_TOTAL, the producer
    refused, and my gate reported BLOCKED_BY_UPSTREAM -- blaming two steps whose OWN
    gates PASS on those same files. My "healthy" fixture passed only because it wrote
    no STA or power file at all: a fixture that avoided the defect instead of
    exercising it.

    "The release-docs reader cannot digest the declared format" is 37.5ic's OWN
    defect, and it is a FAIL. It is not upstream blockage.

    SO THE AUTHORITY IS THE UPSTREAM STEP. The producer's findings are used ONLY to
    NAME which artefacts are at issue; each artefact's DECLARING step comes from the
    flow; and that step's own published verdict for this run decides. A step that
    PASSES can never be the excuse for missing documents, however loudly another
    program complains about its files.
    """
    named: List[dict] = []
    try:
        audit = _art.audit(project, release)
        for f in (audit.errors or []):
            named.append({"rule": getattr(f, "rule", ""),
                          "path": str(getattr(f, "path", "") or ""),
                          "detail": f.line()})
    except Exception as exc:                               # pragma: no cover
        return {"release": release, "blocked": False, "named": [],
                "blocking_steps": {}, "unattributed": [],
                "note": f"the artefact reader raised: "
                        f"{exc.__class__.__name__}: {exc}"}
    try:
        metrics = _tap.load_metrics(project / PRODUCER_METRICS_REL)
        for b in (_tap.release_blockers(metrics) if metrics else []):
            named.append({"rule": "RELEASE_BLOCKER", "path": PRODUCER_METRICS_REL,
                          "detail": str(b)})
        if not metrics:
            named.append({"rule": "METRICS_ABSENT", "path": PRODUCER_METRICS_REL,
                          "detail": f"{PRODUCER_METRICS_REL}: absent or unreadable"})
    except Exception as exc:                               # pragma: no cover
        named.append({"rule": "METRICS_UNREADABLE", "path": PRODUCER_METRICS_REL,
                      "detail": f"{exc.__class__.__name__}: {exc}"})

    # WHY THE EXCUSE IS NOT SCOPED TO THE ARTEFACT, though it should be. R-0915-160, and
    # this is a MEASURED refusal rather than an omission.
    #
    # The ruling asks that an upstream step excuse this one only when its blockage is ABOUT
    # the artefact this step needed -- i.e. when the upstream verdict NAMES that artefact as
    # missing or not produced. There is nothing on disk at gate time that says which artefact
    # an upstream verdict is about: `reports/metrics/<sid>.json` carries SCALARS, and this
    # run's compliance report is not written until after every step.
    #
    # I tried "did the upstream step PRODUCE the artefact" as a proxy, and the tree refuted it.
    # Two shapes are indistinguishable by presence, and they need OPPOSITE answers:
    #
    #   step 37 FAIL, `phase3/stage4/gds/*.gds` PRESENT but carrying no geometry
    #       -> the step's failure IS about that artefact; it must excuse, and
    #          `test_a_step_that_published_not_measured_is_a_blockage` and three of its
    #          neighbours hold exactly that.
    #   step 33 NOT_MEASURED for "no power budget declared", `reports/phase3/power.json`
    #   PRESENT and carrying no number BY DESIGN (`eda_report_audit`: "it carries no number
    #   of its own")
    #       -> the complaint is about that file's CONTENT, which R-0915-149 already ruled is
    #          this step's own defect, so it must NOT excuse.
    #
    # Both are "blocking tier + artefact present". Only the upstream verdict's REASON
    # separates them, and no step publishes one per artefact. Scoping the excuse therefore
    # needs a producer change first -- each step recording which of its declared outputs its
    # own gate found missing or unusable -- and that is a separate ruling. Reported rather
    # than approximated: a proxy that reverses four accepted arms is not a narrower rule, it
    # is a different and wrong one.
    blocking: dict = {}
    passing: dict = {}
    unreadable: dict = {}
    not_about: dict = {}
    unattributed: List[str] = []
    for item in named:
        sid = _declaring_step(item["path"]) if item["path"] else None
        if sid is None:
            # Nothing in the flow declares this path, so no step owns it and no
            # step's verdict can excuse anything. Named, never absorbed.
            unattributed.append(item["detail"])
            continue
        status, why = step_verdict_now(project, sid)
        # WHETHER THE VERDICT WAS READ, beside the verdict. R-0915-152. `NOT_MEASURED` is a
        # blocking tier (R-0915-140), so an UNREADABLE upstream record excuses this step's
        # missing documents -- which is the right direction, since a step that cannot be
        # shown to have passed cannot be the thing that should have produced them. But an
        # excuse nobody can see the basis of is the defect this whole gate exists to
        # correct, so each entry says whether its verdict was measured or merely unreadable,
        # and the unreadable ones are collected under their own name below.
        entry = {"status": status, "why": why, "because": item["detail"],
                 "artefact": item["path"], "verdict_readable": not why}
        if status == _VERDICT_UNREADABLE:
            # Its own bucket: not a blockage, and not recorded as the step passing either.
            unreadable[sid] = dict(entry, reason=why)
            continue
        if status in _BLOCKING_STEP_STATUSES:
            _about, _about_why = upstream_blockage_is_about(project, sid, item["path"])
            entry["blockage_is_about_this_artefact"] = _about
            entry["about_why"] = _about_why
            if _about:
                blocking[sid] = entry
            else:
                not_about[sid] = entry
        else:
            passing[sid] = entry
    return {"release": release,
            "blocked": bool(blocking),
            "named": [i["detail"] for i in named],
            "blocking_steps": blocking,
            "upstream_steps_passing": passing,
            # EVERY STEP WHOSE VERDICT COULD NOT BE READ IN THIS RUN, by name and reason:
            # an absent row, one from another invocation, or one that names none. A reader
            # holding this record can tell an excuse founded on a measurement from one
            # founded on a gap.
            "upstream_verdicts_unreadable": unreadable,
            # BLOCKED, BUT NOT ABOUT WHAT THIS RELEASE NEEDED. R-0915-165. An excuse WITHHELD
            # has to be as visible as one granted, each with the reason read off the upstream
            # step's own output record.
            "upstream_blocked_but_not_about_the_artefact": not_about,
            "unattributed": unattributed}


def producer_refusal(project: Path) -> Optional[dict]:
    """The producer's stated refusal, or None.

    WHY THIS EXISTS. MEASURED on spm run22: `ic_release_docs_gen` RAN (2.26 s,
    rc 1) and declined to write any document, because
    `reports/phase3/sta/post_route_summary.json` carried no slack number anywhere
    and `reports/phase3/power.json` carried no power number -- and it said so, in
    those words, with the right reason ("a release document for a run that did not
    pass is worse than no document"). This gate could read NEITHER the producer's
    log nor the orchestrator report, so it published
    FAIL / RELEASE_DOCUMENTATION_ABSENT: true, and readable as "nobody wrote them".

    A producer's refusal is an UPSTREAM fact about this run, not a documentation
    defect. Read strictly: a document that is unreadable, is not this producer's,
    or does not say REFUSED is not a refusal, and the FAIL below stands.
    """
    try:
        doc = json.loads((project / PRODUCER_REFUSAL_REL).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    if str(doc.get("program") or "") != "ic_release_docs_gen":
        return None
    if str(doc.get("verdict") or "").strip().upper() != "REFUSED":
        return None
    reasons = [str(x) for x in (doc.get("substance_refusals") or [])]
    reasons += [str(x) for x in (doc.get("release_blockers") or [])]
    if not reasons:
        # A refusal that names no reason is not evidence of an upstream cause;
        # crediting it would be exactly the "trust the callee's word" this repo
        # refuses elsewhere.
        return None
    doc["_reasons"] = reasons
    return doc


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
                doc_dir(arm) + "/*/", _searched_glob(arm)],
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
            produced, consequence = (
                (f"delivers hardmacro package `{release}` under "
                 f"{_hm.hardmacro_dir(project)}",
                 "A delivered IP with no document set reaches its integrator "
                 "as four files and nothing that says what they are.")
                if arm == "ip" else
                (f"signs off layout `{release}` under "
                 f"{(project / 'phase3/stage4/gds').as_posix()}",
                 "A die signed off with no document set is a part nobody can "
                 "state the interface, the outline, the supplies or the known "
                 "issues of."))
            result.findings.append(Finding(
                "RELEASE_DOCUMENTATION_ABSENT", "ERROR", release,
                f"the run {produced} and {release_dir} carries no release "
                f"documentation. {consequence}"))
            details.append({"release": release, "directory": release_dir.as_posix(),
                            "documents_present": [], "derived_fields": 0,
                            "not_measured_fields": 0, "rows_examined": 0,
                            "mandatory_constraints_in_app_notes": 0,
                            "same_source_count_comparisons": 0,
                            "pin_count_cross_check": "NOT_STATED",
                            "die_size_cross_check": "NOT_STATED",
                            "artefact_substance": "NOT_EXAMINED",
                            "pass": False})
            continue
        findings, detail = check_release(project, arm, release_dir, release)
        result.findings.extend(findings)
        details.append(detail)

    failed = [d["release"] for d in details if not d["pass"]]

    # R-0915-144 — A PRODUCER'S STATED REFUSAL IS AN UPSTREAM FACT.
    #
    # Only when EVERY error this gate found is the absence of the document set,
    # and the producer recorded why it declined to write it. A release that HAS
    # documents and fails on their content is a documentation defect and stays a
    # FAIL; so does an absence with no refusal record, which is the case this
    # gate was written for. The refusal is not a waiver and nothing here becomes
    # a pass: the row is NOT_MEASURED with `reason_class BLOCKED_BY_UPSTREAM`,
    # which `_flow_reason_taxonomy` holds in `INCOMPLETE` -- not in
    # `SKIP_ELIGIBLE` -- so the step cannot be read as satisfied.
    # RE-DERIVED, PER RELEASE, ON THE CURRENT FILES. The record is a pointer only.
    only_absent = bool(result.findings) and all(
        f.rule == "RELEASE_DOCUMENTATION_ABSENT" for f in result.findings)
    blockage = {}
    if failed and arm == "ic":
        blockage = {rel: upstream_blockage_now(project, rel) for rel in failed}
    # THE PRODUCER'S OWN SCOPE, R-0915-149 / F2. `ic_release_docs_gen` audits the
    # WHOLE RUN and writes NOTHING when any artefact class refuses, so judging per
    # release asked a question the producer never answers: with release `b` hollow,
    # release `a`'s documents cannot be written either, and reporting `a` as "carries
    # no release documentation" blamed `a` for `b`'s breakage. My previous arm pinned
    # exactly that, and it was wrong.
    #
    # So one blocking upstream STEP anywhere blocks the run's documents -- and every
    # excused release NAMES the step and the artefact that blocked it, so nothing is
    # excused anonymously.
    _all_blocking: dict = {}
    for _rel, _b in blockage.items():
        for _sid, _entry in (_b.get("blocking_steps") or {}).items():
            _all_blocking.setdefault(_sid, dict(_entry, release=_rel))
    for _b in blockage.values():
        _b["blocked_by"] = {sid: e for sid, e in _all_blocking.items()}
    all_blocked = bool(_all_blocking)
    refusal = producer_refusal(project) if (failed and arm == "ic") else None
    if all_blocked and only_absent:
        result.passed = False
        result.verdict_tier = "NOT_MEASURED"
        result.summary = {
            "skipped": False,
            "reason": "release_docs_upstream_blocked",
            "reason_class": _reason_taxonomy.BLOCKED_BY_UPSTREAM,
            "arm": arm,
            "documentation_root": root.as_posix(),
            "documentation_root_exists": root.is_dir(),
            "expected_releases": expected,
            "releases_examined": len(details),
            "failed": failed,
            # WHAT WAS OBSERVED NOW, per release — the evidence.
            "upstream_blockage": blockage,
            # WHICH upstream steps blocked this run's documents, by their OWN
            # published verdict, and which artefact named each one.
            "blocking_steps": _all_blocking,
            "producer_refusals": sorted({
                str(e.get("because")) for e in _all_blocking.values()}),
            # THE RECORD, IF ANY — a POINTER for a reader, never the evidence. A
            # verdict that rested on it is the defect R-0915-146 closed.
            "producer": (str(refusal.get("program")) if refusal else None),
            "producer_refusal": (PRODUCER_REFUSAL_REL if refusal else None),
            "producer_refusal_is_evidence": False,
            "rows_examined": sum(d["rows_examined"] for d in details),
            "derived_fields": sum(d["derived_fields"] for d in details),
            "not_measured_fields": sum(
                d["not_measured_fields"] for d in details),
            "same_source_count_comparisons": sum(
                d["same_source_count_comparisons"] for d in details),
            "releases": details,
            "verdict_tier": "NOT_MEASURED",
            "pass": False,
        }
        return result

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
        "same_source_count_comparisons": sum(
            d["same_source_count_comparisons"] for d in details),
        "releases": details,
        "verdict_tier": result.verdict_tier,
        "pass": result.passed,
    }
    if arm == "ip":
        import _physical_current as _pc
        refusal = _pc.check_kit(project)
        if refusal:
            result.findings.append(Finding("IP_KIT_CURRENT_REFUSED", "ERROR", "", refusal))
            result.passed = False
            result.verdict_tier = "FAIL"
            result.summary.update(verdict_tier="FAIL")
            result.summary["pass"] = False
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

    # R-0915-144 — THE NON-VERDICT EXIT, and deliberately NOT the vacuous
    # announcement. `announce_vacuous` prints the VACUOUS_PASS sentinel, which the
    # audit promotes to a PASS tier; an upstream-blocked step is not a pass. rc 2
    # carries "this is not a verdict" and the report's own
    # `reason_class = BLOCKED_BY_UPSTREAM` decides which non-verdict it is --
    # `_flow_reason_taxonomy` holds that class in INCOMPLETE, never in
    # SKIP_ELIGIBLE, so the row lands as NOT_MEASURED and the step stays owed.
    if (str(result.summary.get("reason_class") or "")
            == _reason_taxonomy.BLOCKED_BY_UPSTREAM):
        print(f"  NOT MEASURED — this gate RE-DERIVED the upstream state of "
              f"{sorted(result.summary.get('upstream_blockage') or {})} from the "
              f"current files and every failing release is blocked now, so the "
              f"absence is not a documentation defect. The producer's own record "
              f"({result.summary.get('producer_refusal') or 'absent'}) is a "
              f"pointer, not the evidence:", file=sys.stderr)
        for why in result.summary.get("producer_refusals") or []:
            print(f"    - {why}", file=sys.stderr)
        return _vx.RC_VACUOUS

    if result.passed and skipped:
        _vx.announce_vacuous(GATE, reason)

    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
