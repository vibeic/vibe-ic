#!/usr/bin/env python3
"""
l9_submodule_conformance_check.py — cross-check the SUBMODULE half of the
L9 Integration Spec against the actual RTL emitted under <project>/rtl/.

ENFORCEMENT: advisory — and unlike this repo's other `advisory` declarations
this one is advisory on BOTH axes, which is why it needs no caveat. No runner
spawns the gate inline, so it cannot stop step 2 as step 2 runs; and step 2
wires it in `advisory_program_exit_zero`, the flow's non-blocking slot, so
`flow_compliance_check` records an rc 1 as a finding and passes the step.

THE REASON IS A MEASUREMENT, AND IT ALREADY EXISTED — in the flow definition,
where #1006 wrote it, and nowhere this audit could read it. Re-measured on
2ec8fc2f with `tools/d9_corpus_baseline.py --only l9_submodule_conformance_
check`: 8 of 107 published roots red, 3 CLEAN, 96 NO-INPUT. All 8 reds were
opened by hand. Six are the L9 EXTRACTOR turning a prose token into a declared
submodule (`signed` — a Verilog reserved keyword; `Checks`; `min_distance`;
two 8b/10b comma characters), so the finding is true and its label points at
the RTL for a defect in the producer. One (usb_pd) is a real design-side gap.
One (edge_llm_matmul_accel) is a WRONG RULER: the RTL implements the same
function under a different, valid decomposition against an L9 whose submodules
carry no evidence and no confidence. One demonstrable wrong ruler in 8 is on
its own enough to keep this out of the blocking slot.

PROMOTION CONDITION, so this is a re-measurement and not a standing opinion:
repair the L9 submodule extractor so a prose token cannot become a declared
submodule, decide whether the decomposition is a CONTRACT or a SUGGESTION (see
the `layer-contract-doctrine` skill), then re-run the command above. When the
red count is driven by designs rather than by the extractor, this declaration
becomes `blocking` and the flow row becomes `program_exit_zero`.

Catches the failure modes of CLAUDE.md rule #1 ("Single-agent RTL generation
— multi-agent fails on port naming") and rule #3 ("No stub modules — DTOP
must instantiate everything") at the artefact level. The rule itself is
process advice and unenforceable; this gate enforces the *consequences*
the rule was meant to prevent, regardless of how the RTL was authored.

Scope (deliberately narrow — top-level pin consistency is owned by the
sibling Wave 79 gate `l9_rtl_pin_consistency_check.py`; this gate stays
strictly below that line):

    1. SUBMODULE_FILE_MISSING — every L9.submodules[].name must exist as
                                a `module <name>` declaration in
                                rtl/*.sv|.v.
    2. SUBMODULE_NOT_INSTANTIATED — every L9.submodules[].name must be
                                instantiated by some other module in
                                rtl/*.sv|.v (else it is dead code, often
                                the symptom of a multi-agent run that
                                forgot to wire a piece up).
    3. (schema_version 1 only) SUBMODULE_PORTS_DRIFT — when L9 carries
                                per-submodule port declarations, they
                                must match the actual module port list.

Generality: works for ANY IC project with an L9_INTEGRATION_SPEC.json
plus an rtl/ directory. Pure Python, no EDA-tool dependency. Class-
AGNOSTIC (no aid_class / chip-specific assumptions).

VACUOUS_PASS IS DECIDED ON THE EXAMINED SET, NOT ON THE CONTAINER
-----------------------------------------------------------------
The v1.6.16 / Wave 93 contract said: when L9 is missing or carries no
submodules, emit VACUOUS_PASS rather than FAIL. That is right and stays.
It was written on the CONTAINER being empty, and the three checks below
each skip entries the gate cannot assert on — a bare-string entry (no
identifier to look for), a `low_confidence` entry (a naming-delegated
functional contract), an entry with no name. When those skips consumed
the WHOLE list the container was still non-empty, so control fell
through to `PASS` and the gate printed "L9 conformance OK (0 findings)"
having asserted on nothing.

Measured on the tracked corpus: 130 declared submodules across 36 L-doc
sets, 62 examinable; 16 of the 36 have an EMPTY examinable set, and 6 of
those reached the PASS arm (they declare 4 to 16 submodules each and
have an rtl/ directory). None of the individual skips is wrong — a bare
string really is prose and a delegated name really is not an RTL
assertion — so the remedy is not to examine more. It is that the verdict
and the report follow the EXAMINED set: an empty one is VACUOUS_PASS
with a reason that names the counts, and every arm (PASS included)
discloses `submodule_census` = declared / examined / skipped-by-reason.
A sibling gate's docstring states that this gate "proves each declared
submodule exists and is instantiated"; without the census a reader has
no way to see when it proved nothing of the kind.

Usage:
    python3 l9_submodule_conformance_check.py <project_dir> [--json <out>]

Exit codes:
    0  all checks pass (or VACUOUS_PASS)
    1  one or more conformance findings
    2  argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import _path_layout as _pl


# --- SystemVerilog / Verilog port-decl parsing ------------------------------
# Regex-based, intentionally NOT a full SV grammar. Handles ANSI-style port
# lists (the only style aid_class_rtl_gen.py and most modern Vibe-IC RTL
# emit). Limitations are listed in the docstring of `parse_module_ports`.

_RE_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_LINE_COMMENT = re.compile(r"//[^\n]*")
# Match `module <name>` only — anything between `<name>` and the port-list
# opening paren (parameter list `#(...)`, one or more `import pkg::*;`
# clauses) is skipped procedurally by `_seek_port_list_open` so we are not
# locked into one particular ordering.
_RE_MODULE_NAME = re.compile(r"\bmodule\s+(\w+)\b", re.MULTILINE)
_RE_DIRECTION_PORT = re.compile(
    r"\b(input|output|inout)\b"      # direction
    r"(?:\s+(?:wire|reg|logic|signed|tri|wand|wor|tri0|tri1)\b)*"  # opt. type kw
    r"(?:\s*\[[^\]]*\])?"            # optional packed dimension [N:0]
    r"\s+(\w+)"                      # port name
    r"(?:\s*\[[^\]]*\])?"            # optional unpacked dimension
    r"\s*(?=,|$)",                   # followed by , or end of segment
    re.MULTILINE,
)


def _strip_comments(text: str) -> str:
    text = _RE_BLOCK_COMMENT.sub("", text)
    text = _RE_LINE_COMMENT.sub("", text)
    return text


def _balanced_paren_slice(text: str, open_idx: int) -> Tuple[int, str]:
    """Given text and the index of an opening '(' character, return
    (close_idx, inner) where inner is the substring between the parens
    with comments stripped. Returns (-1, "") on unbalanced input."""
    depth = 0
    i = open_idx
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i, text[open_idx + 1 : i]
        i += 1
    return -1, ""


def _seek_port_list_open(text: str, start: int) -> int:
    """Scan forward from `start` past whitespace, optional `#(...)`
    parameter list, and zero or more `import <pkg>::<sym>;` clauses, and
    return the index of the port-list opening `(`. Returns -1 if the
    module declaration is malformed (e.g. no `(` found, or the next
    token is `;` indicating a port-list-less module — those exist but
    have no ports to compare so we treat them as no-ports).
    """
    i = start
    n = len(text)
    while i < n:
        # Skip whitespace
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            return -1
        c = text[i]
        # `;` terminates the module header without a port list — bare
        # `module foo;` is legal SV but carries nothing for us to check.
        if c == ";":
            return -1
        # `(` is the port-list opener we want.
        if c == "(":
            return i
        # `#(...)` parameter list — balanced-skip.
        if c == "#":
            i += 1
            while i < n and text[i].isspace():
                i += 1
            if i >= n or text[i] != "(":
                return -1
            close, _ = _balanced_paren_slice(text, i)
            if close < 0:
                return -1
            i = close + 1
            continue
        # SV `import pkg::sym;` (one or more, comma-separated). Skip
        # to the next `;`.
        if text.startswith("import", i) and (
                i + 6 >= n or not (text[i + 6].isalnum() or text[i + 6] == "_")):
            semi = text.find(";", i)
            if semi < 0:
                return -1
            i = semi + 1
            continue
        # Anything else between `module <name>` and `(` is unexpected;
        # bail rather than misparse.
        return -1
    return -1


def parse_module_ports(text: str) -> Dict[str, List[Tuple[str, str]]]:
    """Parse all `module <name> (...)` headers in `text` and return a dict
    mapping module name to a list of ``(port_name, direction)`` tuples in
    declaration order. Direction is one of: input, output, inout.

    Limitations (intentional):
      * Only ANSI-style port lists. Old K&R-style "module foo(a, b);
        input a; output b; endmodule" is not handled — the dict will
        record an empty port list for such modules. AS-IS deliberate:
        Vibe-IC plugin canonical RTL is ANSI-only.
      * Macro-substituted port lists (`SOMEPORTS) are not expanded.
      * Generated/parameterised port count is captured as written.
    """
    text = _strip_comments(text)
    out: Dict[str, List[Tuple[str, str]]] = {}
    for m in _RE_MODULE_NAME.finditer(text):
        name = m.group(1)
        open_idx = _seek_port_list_open(text, m.end())
        if open_idx < 0:
            # Bare `module foo;` or malformed header — record empty
            # port list so the module is still "known to exist".
            out.setdefault(name, [])
            continue
        close_idx, inner = _balanced_paren_slice(text, open_idx)
        if close_idx < 0:
            continue
        ports: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for pm in _RE_DIRECTION_PORT.finditer(inner):
            direction, pname = pm.group(1), pm.group(2)
            if pname in seen:
                continue
            seen.add(pname)
            ports.append((pname, direction))
        out[name] = ports
    return out


# --- L9 loading -------------------------------------------------------------

def load_l9(project: Path) -> Optional[dict]:
    """Locate and load <project>/generated_docs/L9_*.json. Return None if
    no L9 file exists."""
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return None
    for cand in sorted(gd.glob("L9_*.json")):
        try:
            return json.loads(cand.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return None


def collect_rtl(project: Path) -> Dict[str, Path]:
    """Walk rtl/ and asic_rtl/ for *.sv|.v, parse each, return a unified
    name → file-path mapping for module declarations.

    On duplicate module name across files, the lexically-first file wins
    and the duplicate is recorded as a finding by the caller (we keep the
    parser pure here)."""
    out: Dict[str, Path] = {}
    text_buf: List[Tuple[Path, str]] = []
    for sub in ("phase2/stage1/rtl", "rtl", "asic_rtl"):
        d = project / sub
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.sv")):
            text_buf.append((f, f.read_text(encoding="utf-8", errors="replace")))
        for f in sorted(d.rglob("*.v")):
            text_buf.append((f, f.read_text(encoding="utf-8", errors="replace")))
    for path, text in text_buf:
        for name in parse_module_ports(text).keys():
            out.setdefault(name, path)
    return out


def collect_module_ports(project: Path) -> Dict[str, List[Tuple[str, str]]]:
    """Parse every rtl/*.sv|.v under the project, return module → ports map."""
    merged: Dict[str, List[Tuple[str, str]]] = {}
    for sub in ("phase2/stage1/rtl", "rtl", "asic_rtl"):
        d = project / sub
        if not d.is_dir():
            continue
        for ext in ("*.sv", "*.v"):
            for f in sorted(d.rglob(ext)):
                text = f.read_text(encoding="utf-8", errors="replace")
                for mod, ports in parse_module_ports(text).items():
                    merged.setdefault(mod, ports)
    return merged


def collect_rtl_text(project: Path) -> str:
    """Concatenate all rtl/*.sv|.v with comments stripped. Used for
    instantiation detection — comment-stripped so commented-out
    instantiations don't count."""
    chunks: List[str] = []
    for sub in ("phase2/stage1/rtl", "rtl", "asic_rtl"):
        d = project / sub
        if not d.is_dir():
            continue
        for ext in ("*.sv", "*.v"):
            for f in sorted(d.rglob(ext)):
                chunks.append(_strip_comments(
                    f.read_text(encoding="utf-8", errors="replace")))
    return "\n".join(chunks)


# --- Finding model + checks -------------------------------------------------

@dataclass
class Finding:
    rule: str
    severity: str
    module: str
    message: str


# --- Which declared submodules can this gate actually assert on? ------------
# Every check below skips the same three shapes. Until this landing each one
# open-coded the skip, and NOTHING counted them: a document could declare N
# submodules, have all N skipped, and the gate still reported
# "PASS: L9 conformance OK (0 findings)". A PASS that examined nothing is
# indistinguishable from a PASS that examined everything, and a sibling gate
# states in its own docstring that this one "proves each declared submodule
# exists and is instantiated" — a premise the reader has no way to check.
#
# Measured on the tracked corpus at the time of this landing: 36 L-doc sets
# carry a non-empty `submodules` list, 130 entries between them, of which
# this gate can assert on 62. In 16 of the 36 the examinable set is EMPTY,
# and 6 of those reach the `PASS` arm rather than `VACUOUS_PASS` because the
# container is non-empty and rtl/ exists. So the fix is not to examine more —
# each skip is individually correct — it is to make the VERDICT and the
# report a function of the EXAMINED set rather than of the container, and to
# disclose the denominator on every arm.
SKIP_NOT_AN_OBJECT = "not_an_object"
SKIP_NAMING_DELEGATED = "naming_delegated_low_confidence"
SKIP_NO_NAME = "no_name"

_SKIP_REASON_TEXT = {
    SKIP_NOT_AN_OBJECT:
        "declared as a bare string rather than an object, so it carries no "
        "`name` field to assert on (the string is prose, not an identifier)",
    SKIP_NAMING_DELEGATED:
        "tagged low_confidence — a naming-delegated FUNCTIONAL contract, not "
        "a literal RTL module-name assertion (v0.1.85)",
    SKIP_NO_NAME:
        "an object with no `name` field",
}


def classify_submodules(l9: dict) -> Tuple[List[dict], Dict[str, object]]:
    """Split `L9.submodules` into what this gate can assert on and what it
    cannot, and count both.

    Returns ``(examinable, census)``. `census` carries ``declared``,
    ``examined`` and ``skipped`` (reason -> count); it is the denominator
    every verdict below discloses.

    The three skips are UNCHANGED in effect — a bare string has no
    identifier to look for in rtl/, a `low_confidence` entry is a functional
    contract whose RTL name the Plugin chooses, and an object with no name
    asserts nothing. What is new is that they are counted rather than
    silently dropped.
    """
    examinable: List[dict] = []
    skipped: Dict[str, int] = {}
    declared = 0

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for s in l9.get("submodules", []) or []:
        declared += 1
        if not isinstance(s, dict):
            _skip(SKIP_NOT_AN_OBJECT)
            continue
        if s.get("low_confidence") is True:
            _skip(SKIP_NAMING_DELEGATED)
            continue
        if not s.get("name"):
            _skip(SKIP_NO_NAME)
            continue
        examinable.append(s)
    return examinable, {"declared": declared,
                        "examined": len(examinable),
                        "skipped": skipped}


def describe_census(census: Dict[str, object]) -> str:
    """One human sentence naming the denominator and every skip."""
    parts = ["%s of %s declared submodule(s) examined"
             % (census.get("examined"), census.get("declared"))]
    skipped = census.get("skipped") or {}
    if isinstance(skipped, dict):
        for reason, n in sorted(skipped.items()):
            parts.append("%d skipped: %s"
                         % (n, _SKIP_REASON_TEXT.get(reason, reason)))
    return "; ".join(parts)


def check_submodule_presence(l9: dict,
                             rtl_ports: Dict[str, List[Tuple[str, str]]]
                             ) -> List[Finding]:
    findings: List[Finding] = []
    for s in classify_submodules(l9)[0]:
        name = s.get("name")
        if name not in rtl_ports:
            findings.append(Finding(
                rule="SUBMODULE_FILE_MISSING", severity="ERROR", module=name,
                message=f"L9 declares submodule '{name}' but no `module "
                        f"{name}` declaration found under rtl/."))
    return findings


_INSTANTIATION_TEMPLATE = (
    # `<module_name> [#(params)] <instance_name> (...)` — `\b` + word breaks.
    # We exclude cases where this matches a module-declaration header by also
    # requiring absence of the literal keyword `module ` immediately before.
    #
    # The optional parameter override `#(...)` is placed BEFORE the instance
    # name (correct Verilog ordering: `serv_alu #(.W(W)) alu (...)`), not
    # after it. The previous template put `#(...)` after `\w+` and used a
    # flat `[^)]*` body, so it (a) required the wrong token order and (b)
    # failed on nested parens inside the param list (e.g. `#(.W (W))`),
    # yielding false SUBMODULE_NOT_INSTANTIATED findings on standard,
    # synthesizable Verilog (whitespace/newlines between tokens are also
    # absorbed by `\s+`). The body now allows one level of nested parens.
    r"(?<!module\s)\b{name}\b\s+(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?\w+\s*\("
)


def check_submodule_instantiation(l9: dict,
                                  rtl_text: str,
                                  rtl_ports: Dict[str, List[Tuple[str, str]]]
                                  ) -> List[Finding]:
    findings: List[Finding] = []
    for s in classify_submodules(l9)[0]:
        name = s.get("name")
        if name not in rtl_ports:
            # Already flagged by SUBMODULE_FILE_MISSING; skip dead-code
            # check to keep findings non-redundant.
            continue
        pat = re.compile(_INSTANTIATION_TEMPLATE.format(name=re.escape(name)))
        # Filter out the module's own declaration: pattern matches that too
        # because it begins `<name> ( ... )`. Strip module headers first.
        scrubbed = re.sub(
            r"\bmodule\s+" + re.escape(name) + r"\s*(?:#\s*\([^)]*\))?\s*\([^)]*\)",
            "", rtl_text, flags=re.DOTALL)
        if not pat.search(scrubbed):
            findings.append(Finding(
                rule="SUBMODULE_NOT_INSTANTIATED", severity="ERROR",
                module=name,
                message=f"submodule '{name}' is declared by a module file "
                        f"but never instantiated by any other module in "
                        f"rtl/. Likely dead code from an incomplete RTL "
                        f"emission run (CLAUDE.md rule 3)."))
    return findings


def check_submodule_ports_v1(l9: dict,
                             rtl_ports: Dict[str, List[Tuple[str, str]]]
                             ) -> List[Finding]:
    """Schema v1 carries per-submodule .ports field. When present, cross-
    check it against the actual RTL module port list."""
    findings: List[Finding] = []
    for s in classify_submodules(l9)[0]:
        name = s.get("name")
        decl_ports = s.get("ports")
        if not isinstance(decl_ports, list) or not decl_ports:
            continue
        if name not in rtl_ports:
            continue  # already flagged by SUBMODULE_FILE_MISSING
        # Normalise L9 entries to (name, direction).
        expected: List[Tuple[str, str]] = []
        for p in decl_ports:
            if isinstance(p, dict):
                pn = p.get("name")
                pd = (p.get("mode") or p.get("direction") or "").lower()
                if pn and pd in ("input", "output", "inout"):
                    expected.append((pn, pd))
            elif isinstance(p, str):
                # Some L9 v1 files list ports as bare names; we cannot
                # check direction in that case but can still check presence.
                expected.append((p, ""))
        actual_map = dict(rtl_ports[name])
        expected_names = [pn for pn, _ in expected]
        for pn in expected_names:
            if pn not in actual_map:
                findings.append(Finding(
                    rule="SUBMODULE_PORTS_DRIFT", severity="ERROR",
                    module=name,
                    message=f"L9 declares port '{pn}' on submodule "
                            f"'{name}' but it is absent from the RTL."))
        for pn, pd in expected:
            if pd and pn in actual_map and actual_map[pn] != pd:
                findings.append(Finding(
                    rule="SUBMODULE_PORTS_DRIFT", severity="ERROR",
                    module=name,
                    message=f"Submodule '{name}' port '{pn}' direction "
                            f"disagrees: L9 says {pd}, RTL says "
                            f"{actual_map[pn]}."))
    return findings


# --- Main -------------------------------------------------------------------

_EMPTY_CENSUS: Dict[str, object] = {"declared": 0, "examined": 0, "skipped": {}}


def audit_report(project: Path) -> Tuple[str, List[Finding], Dict[str, object],
                                         str]:
    """Return (verdict, findings, census, reason).

    Verdict: PASS / FAIL / VACUOUS_PASS. `census` is the denominator — how
    many submodules the document DECLARES against how many this gate could
    assert on — and it is reported on every arm, PASS included. `reason` is
    non-empty only for VACUOUS_PASS and names which of the three vacuity
    causes fired, so "no L9" and "an L9 whose every entry this gate must
    skip" are not both reported as the same nothing.
    """
    l9 = load_l9(project)
    if l9 is None or not l9.get("submodules"):
        return ("VACUOUS_PASS", [], dict(_EMPTY_CENSUS),
                "L9 missing or carries no submodules to cross-check; gate "
                "inapplicable")

    examinable, census = classify_submodules(l9)

    rtl_ports = collect_module_ports(project)
    if not rtl_ports:
        # L9 lists submodules but rtl/ is empty / absent. This is an
        # incomplete project — flow_compliance_check catches absent
        # rtl/ at the L9-presence step. Vacuous here keeps signals
        # non-redundant.
        return ("VACUOUS_PASS", [], census,
                "L9 declares %d submodule(s) but no `module` declaration was "
                "found under rtl/; nothing to cross-check against"
                % census["declared"])

    if not examinable:
        # THE ARM THIS LANDING ADDS. The container is non-empty and rtl/
        # exists, so control used to fall straight through to the PASS at
        # the bottom with an empty finding list — a gate reporting success
        # after asserting on zero of the entries it was pointed at. Each
        # individual skip stays correct; what changes is that the verdict
        # now follows the EXAMINED set. Measured: 6 published cells reach
        # here, declaring 4 to 16 submodules each.
        return ("VACUOUS_PASS", [], census,
                "L9 declares %d submodule(s), none of which this gate can "
                "assert on — %s. Nothing was checked, so this is NOT a "
                "clean bill of health for the submodule half of L9."
                % (census["declared"], describe_census(census)))

    rtl_text = collect_rtl_text(project)
    findings: List[Finding] = []
    findings.extend(check_submodule_presence(l9, rtl_ports))
    findings.extend(check_submodule_instantiation(l9, rtl_text, rtl_ports))
    if l9.get("schema_version") in (1, "1", 1.0):
        findings.extend(check_submodule_ports_v1(l9, rtl_ports))
    verdict = "PASS" if not findings else "FAIL"
    return verdict, findings, census, ""


def audit(project: Path) -> Tuple[str, List[Finding]]:
    """Return (verdict, findings). Verdict: PASS / FAIL / VACUOUS_PASS.

    Thin wrapper over `audit_report` so there is ONE place that decides a
    verdict. Callers that need the denominator use `audit_report`.
    """
    verdict, findings, _census, _reason = audit_report(project)
    return verdict, findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Cross-check L9 Integration Spec against rtl/*.sv|.v.")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings, census, reason = audit_report(project)

    report = {
        "verdict": verdict,
        "project": str(project),
        "findings": [asdict(f) for f in findings],
        # Reported on EVERY arm, PASS included: without it a PASS over 0 of
        # 16 declared submodules reads exactly like a PASS over 16 of 16.
        "submodule_census": census,
    }
    if reason:
        report["reason"] = reason

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    if verdict == "PASS":
        print(f"PASS: L9 conformance OK ({len(findings)} findings) — "
              f"{describe_census(census)}")
        return 0
    print(f"FAIL: {len(findings)} L9-conformance finding(s) — "
          f"{describe_census(census)}:", file=sys.stderr)
    for f in findings:
        print(f"  [{f.rule}] {f.module}: {f.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
