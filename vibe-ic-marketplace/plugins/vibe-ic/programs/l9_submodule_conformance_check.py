#!/usr/bin/env python3
"""
l9_submodule_conformance_check.py — cross-check the SUBMODULE half of the
L9 Integration Spec against the actual RTL emitted under <project>/rtl/.

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
AGNOSTIC (no aid_class / chip-specific assumptions). Conforms to the
v1.6.16 / Wave 93 VACUOUS_PASS contract: when L9 is missing or carries
no submodules, the gate emits VACUOUS_PASS rather than FAIL — the wider
flow_compliance_check catches an absent L9 separately via L1-L23
presence checks.

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


def check_submodule_presence(l9: dict,
                             rtl_ports: Dict[str, List[Tuple[str, str]]]
                             ) -> List[Finding]:
    findings: List[Finding] = []
    for s in l9.get("submodules", []) or []:
        if not isinstance(s, dict):
            continue
        # v0.1.85 — skip naming-delegated functional submodules. A submodule
        # documented in a "Plugin chooses naming/hierarchy" spec (tagged
        # low_confidence) is a FUNCTIONAL contract, not a literal RTL module-
        # name assertion; do not require `module <prose name>` in rtl/.
        if s.get("low_confidence") is True:
            continue
        name = s.get("name")
        if not name:
            continue
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
    for s in l9.get("submodules", []) or []:
        if not isinstance(s, dict):
            continue
        # v0.1.85 — skip naming-delegated functional submodules. A submodule
        # documented in a "Plugin chooses naming/hierarchy" spec (tagged
        # low_confidence) is a FUNCTIONAL contract, not a literal RTL module-
        # name assertion; do not require `module <prose name>` in rtl/.
        if s.get("low_confidence") is True:
            continue
        name = s.get("name")
        if not name:
            continue
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
    for s in l9.get("submodules", []) or []:
        if not isinstance(s, dict):
            continue
        # v0.1.85 — skip naming-delegated functional submodules. A submodule
        # documented in a "Plugin chooses naming/hierarchy" spec (tagged
        # low_confidence) is a FUNCTIONAL contract, not a literal RTL module-
        # name assertion; do not require `module <prose name>` in rtl/.
        if s.get("low_confidence") is True:
            continue
        name = s.get("name")
        decl_ports = s.get("ports")
        if not name or not isinstance(decl_ports, list) or not decl_ports:
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

def audit(project: Path) -> Tuple[str, List[Finding]]:
    """Return (verdict, findings). Verdict: PASS / FAIL / VACUOUS_PASS."""
    l9 = load_l9(project)
    if l9 is None or not l9.get("submodules"):
        return "VACUOUS_PASS", []

    rtl_ports = collect_module_ports(project)
    if not rtl_ports:
        # L9 lists submodules but rtl/ is empty / absent. This is an
        # incomplete project — flow_compliance_check catches absent
        # rtl/ at the L9-presence step. Vacuous here keeps signals
        # non-redundant.
        return "VACUOUS_PASS", []

    rtl_text = collect_rtl_text(project)
    findings: List[Finding] = []
    findings.extend(check_submodule_presence(l9, rtl_ports))
    findings.extend(check_submodule_instantiation(l9, rtl_text, rtl_ports))
    if l9.get("schema_version") in (1, "1", 1.0):
        findings.extend(check_submodule_ports_v1(l9, rtl_ports))
    verdict = "PASS" if not findings else "FAIL"
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

    verdict, findings = audit(project)

    report = {
        "verdict": verdict,
        "project": str(project),
        "findings": [asdict(f) for f in findings],
    }
    if verdict == "VACUOUS_PASS":
        report["reason"] = ("L9 missing or carries no top_module/submodules "
                            "to cross-check; gate inapplicable")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    if verdict == "PASS":
        print(f"PASS: L9 conformance OK ({len(findings)} findings)")
        return 0
    print(f"FAIL: {len(findings)} L9-conformance finding(s):", file=sys.stderr)
    for f in findings:
        print(f"  [{f.rule}] {f.module}: {f.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
