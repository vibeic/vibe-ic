#!/usr/bin/env python3
"""staged_rtl_closure_preflight.py — ORGANIC #586.

Security-hardened IPs ship multiple implementation variants behind a
compile-time parameter, and a staging convention may deliberately
exclude one variant. When the parameter's DECLARED DEFAULT still points
at the excluded variant, yosys elaborates the uninstantiated generate
branch of EVERY module that declares the default and aborts with
``Module `X' referenced ... is not part of the design`` — even though
the actual instantiation tree overrides the parameter everywhere. The
failure surfaces as a raw yosys abort with no hint that a
default-vs-closure mismatch is the cause.

This preflight scans a staged RTL set and reports every module
reference that resolves to no staged module, classifying each:

  * ``generate_branch_default`` — the dangling reference sits inside a
    generate case/if branch; the diagnosis names the guarding label,
    the selector parameter(s) whose declared default matches that
    label, and the sibling-branch modules that ARE in closure (the
    rewrite target).
  * ``unconditional`` — referenced outside any generate conditional
    (a genuine closure hole).

Exit codes: 0 = closure complete, 1 = dangling references found,
2 = input error. Chip-AGNOSTIC: pure Verilog/SV structure.

WHERE AN INSTANTIATION CAN BE (vibe-ic#2093)
--------------------------------------------
``_INST_FULL_RE`` matches ``<id> <id> (`` ANYWHERE in the file. Two
constructs have that exact shape and are not instantiations:

    `define MACRO(a, b)            a compiler directive
    function automatic ret_t f(x)  a function/task header

MEASURED on a staged OpenTitan-AES set (131 files): 36 FAIL rows, of which
35 were one of those two -- 32 SV package-function headers returning a
typedef (``mubi4_t``, ``secded_39_32_t``, ``tl_h2d_cmd_intg_t``, ...), a
function header inside a module generate block (``matrix_col_t``), and 3
``define``. Every one printed "instantiated outside any generate
conditional ... genuine hole", which is a confident instruction to stage a
type. The one true finding was buried under them.

The fix is positional, not a name blacklist: a module instantiation is a
module ITEM, so a candidate counts only when the innermost enclosing
``module``/``endmodule``-style region is a MODULE -- never a package, a
function, a task, a class or an interface -- and never inside a compiler
directive line (or its backslash continuations). A name blacklist would
have to enumerate every typedef in every vendor package and would still
miss the next one; the position is decidable from the grammar.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_ID = r"[A-Za-z_]\w*"

_MODULE_DEF_RE = re.compile(rf"^\s*module\s+({_ID})", re.M)
# Instantiation: ModName [#(...)] inst_name ( ... — at statement start.
_INST_RE = re.compile(
    rf"^\s*({_ID})\s*(?:#\s*\()?",
    re.M,
)
_INST_FULL_RE = re.compile(
    rf"\b({_ID})\s+(?:#\s*\([^;]*?\)\s*)?({_ID})\s*\(",
)
_NON_MODULE_KEYWORDS = frozenset({
    "module", "endmodule", "input", "output", "inout", "wire", "reg",
    "logic", "assign", "always", "always_ff", "always_comb", "always_latch",
    "parameter", "localparam", "generate", "endgenerate", "begin", "end",
    "if", "else", "for", "while", "case", "casez", "casex", "endcase",
    "function", "endfunction", "task", "endtask", "initial", "final",
    "typedef", "enum", "struct", "union", "package", "endpackage",
    "import", "export", "genvar", "integer", "int", "bit", "byte",
    "return", "unique", "priority", "default", "posedge", "negedge",
    "signed", "unsigned", "automatic", "static", "const", "var",
    "interface", "endinterface", "modport", "clocking", "endclocking",
    "property", "endproperty", "assert", "assume", "cover", "sequence",
    "endsequence", "supply0", "supply1", "tri", "wand", "wor", "buf",
    "not", "and", "or", "xor", "nand", "nor", "xnor", "specify",
    "endspecify", "defparam", "event", "real", "time", "string",
})
# parameter ... Name = value  (type tokens between are tolerated)
_PARAM_RE = re.compile(
    rf"\bparameter\b[^;,=()]*?({_ID})\s*=\s*([^,;)\n]+)")
# case-generate label line: `value: begin` / `value :` (inside generate)
_CASE_LABEL_RE = re.compile(rf"^\s*([\w:\[\]']+)\s*:\s*(?:begin\b)?", re.M)
# v1.14.50 — if/else-generate block opener: `begin : label`.
# `_enclosing_case_label` below requires the literal keyword `case`, so before
# this the whole if/else-generate form was invisible: a dangling reference
# guarded by `if (P == V) begin : L` fell through to `unconditional_dangling_ref`
# and was reported as "instantiated outside any generate conditional — genuine
# hole", which is the OPPOSITE of the truth and sends the operator to stage a
# module that was excluded on purpose. Measured on OpenTitan aes_sbox.sv.
_GEN_BLOCK_RE = re.compile(rf"\bbegin\s*:\s*({_ID})")
_IF_GUARD_RE = re.compile(r"\bif\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*$")
_ELSE_GUARD_RE = re.compile(r"\belse\s*$")
_EQ_COND_RE = re.compile(rf"^\s*({_ID})\s*==\s*([\w:'\[\]]+)\s*$")
_BARE_COND_RE = re.compile(rf"^\s*({_ID})\s*$")
_FALSEY = {"0", "1'b0", "'0", "1'B0", "false"}

#: Region openers whose closer is unambiguous. `property`/`sequence`/
#: `covergroup` are deliberately ABSENT: `assert property (...)` uses the
#: keyword with no `endproperty`, so tracking it would corrupt the stack for
#: the rest of the file.
_REGION_PAIRS = {
    "module": "endmodule", "package": "endpackage",
    "function": "endfunction", "task": "endtask",
    "class": "endclass", "interface": "endinterface",
}
_REGION_TOKEN_RE = re.compile(
    r"\b(module|endmodule|package|endpackage|function|endfunction"
    r"|task|endtask|class|endclass|interface|endinterface)\b")


def _enclosing_if_generate(text: str, pos: int):
    """(label, condition_or_None) of the nearest preceding
    `if (...) begin : L` / `else begin : L`, else None.

    Conservative by construction: the block opener must be IMMEDIATELY
    preceded by an `if (...)` or a bare `else`, so `for (...) begin : L`,
    `always ... begin : L` and plain named blocks are all excluded and keep
    their existing classification.
    """
    window = text[max(0, pos - 4000):pos]
    last = None
    for m in _GEN_BLOCK_RE.finditer(window):
        last = m
    if last is None:
        return None
    before = window[:last.start()].rstrip()
    m_if = _IF_GUARD_RE.search(before)
    if m_if:
        return last.group(1), m_if.group(1).strip()
    if _ELSE_GUARD_RE.search(before):
        return last.group(1), None
    return None


def _guard_parameters(cond, label, params: Dict[str, str]) -> List[str]:
    """Parameter NAMES the branch's guard depends on — regardless of whether
    their DEFAULT selects it.

    `_params_selecting` answers "which defaults make this true"; this answers
    "which parameters decide this at all". The two differ exactly when the
    deciding parameter's default does NOT select the branch, which is the case
    where an operator most needs to be told the name: the branch is reached by
    an override from the instantiation tree, and nothing else in the report
    says which knob that is."""
    names: List[str] = []
    if cond:
        for n in re.findall(_ID, cond):
            if n in params and n not in names:
                names.append(n)
    if not names and label:
        # case-generate: the label is an enum VALUE, so the deciding parameter
        # is whichever declared parameter is typed by that value's family.
        tail = label.split("::")[-1]
        for pn, pv in params.items():
            if pv.split("::")[-1] == tail and pn not in names:
                names.append(pn)
    return sorted(names)


def _params_selecting(cond, params: Dict[str, str]) -> List[str]:
    """Parameter DEFAULTS that make `cond` true. Empty is a legitimate,
    meaningful answer: the branch is then reached only via an override from
    the instantiation tree, and the caller's message already says exactly
    that instead of inventing a selector."""
    if not cond:
        return []
    m = _EQ_COND_RE.match(cond)
    if m:
        name, val = m.group(1), m.group(2)
        v = params.get(name)
        if v is not None and v.split("::")[-1] == val.split("::")[-1]:
            return [f"{name} = {v}"]
        return []
    m = _BARE_COND_RE.match(cond)
    if m:
        name = m.group(1)
        v = params.get(name)
        if v is not None and v.strip() not in _FALSEY:
            return [f"{name} = {v}"]
    return []


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _gather(targets: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for t in targets:
        p = Path(t)
        if p.is_dir():
            for f in sorted(list(p.rglob("*.sv")) + list(p.rglob("*.v"))):
                try:
                    out[str(f)] = _strip_comments(
                        f.read_text(errors="replace"))
                except OSError:
                    continue
        elif p.is_file():
            try:
                out[str(p)] = _strip_comments(p.read_text(errors="replace"))
            except OSError:
                continue
    return out


def _directive_spans(text: str) -> List[Tuple[int, int]]:
    """(start, end) of every compiler-directive line and its continuations.

    A backtick-define of a macro with arguments is ``<id> <id> (`` and matched the
    instantiation pattern; three macro names were reported as missing
    modules on the measured set. A macro BODY continued with a trailing
    backslash is part of the directive too, so the continuation lines are
    included rather than re-scanned as module items.
    """
    spans: List[Tuple[int, int]] = []
    off = 0
    continuing = False
    for line in text.split("\n"):
        start = off
        off += len(line) + 1
        if line.lstrip().startswith("`"):
            continuing = True
        if continuing:
            spans.append((start, off))
            if not line.rstrip().endswith("\\"):
                continuing = False
    return spans


def _region_events(text: str) -> List[Tuple[int, Optional[str]]]:
    """[(offset, innermost_open_region_kind)] after each region token.

    The text is passed through the comment stripper first. `_gather` has
    already stripped it, so this is the identity on that path and costs
    nothing; it also makes the helper correct when called on raw HDL, which
    is where the phantom-declaration class of defect comes from.

    An unmatched ``end<x>`` is ignored rather than treated as a pop, so a
    file this scanner cannot follow degrades to "no module region" and its
    candidates are dropped -- never silently promoted to findings.
    """
    code = _strip_comments(text)
    stack: List[str] = []
    events: List[Tuple[int, Optional[str]]] = []
    for m in _REGION_TOKEN_RE.finditer(code):
        tok = m.group(1)
        if tok in _REGION_PAIRS:
            stack.append(tok)
        else:
            opener = tok[3:]
            if opener in stack:
                del stack[len(stack) - 1 - stack[::-1].index(opener):]
        events.append((m.end(), stack[-1] if stack else None))
    return events


def _innermost_region(events, offsets, pos: int) -> Optional[str]:
    """Region kind in force at `pos`: the state left by the last region
    token at or before it. `offsets` is bisected rather than `events`
    because an event's second element may be None and tuple comparison
    against None raises."""
    idx = bisect.bisect_right(offsets, pos) - 1
    return events[idx][1] if idx >= 0 else None


def _instantiations(text: str) -> List[Tuple[str, int]]:
    """[(module_ref, offset)] of plausible instantiations.

    A module instantiation is a MODULE ITEM (vibe-ic#2093): the innermost
    enclosing region must be a module, so a function/task header inside a
    package or inside a module, and anything at package scope, is not one.
    """
    events = _region_events(text)
    offsets = [e[0] for e in events]
    directives = _directive_spans(text)
    out: List[Tuple[str, int]] = []
    for m in _INST_FULL_RE.finditer(text):
        ref, inst = m.group(1), m.group(2)
        if ref in _NON_MODULE_KEYWORDS or inst in _NON_MODULE_KEYWORDS:
            continue
        if _innermost_region(events, offsets, m.start()) != "module":
            continue
        if any(a <= m.start() < b for a, b in directives):
            continue
        # skip function-style calls `name (` with the "instance" being
        # actually the open paren of a task/if/for — inst must not be a
        # keyword (checked) and ref must not start a declaration.
        out.append((ref, m.start()))
    return out


def _enclosing_case_label(text: str, pos: int) -> Optional[str]:
    """Best-effort: nearest preceding case-generate label (`X: begin`)
    between the instantiation and the start of its generate region."""
    window = text[max(0, pos - 4000):pos]
    labels = _CASE_LABEL_RE.findall(window)
    # drop port-connection false positives (`.name (`) — the regex
    # can't see the dot, so filter labels that appear after the last
    # `case` keyword only.
    case_idx = window.rfind("case")
    if case_idx < 0:
        return None
    labels_after_case = _CASE_LABEL_RE.findall(window[case_idx:])
    if not labels_after_case:
        return None
    return labels_after_case[-1].strip()


def _param_defaults(text: str) -> Dict[str, str]:
    return {m.group(1): m.group(2).strip()
            for m in _PARAM_RE.finditer(text)}


def audit(targets: List[str]) -> Dict:
    files = _gather(targets)
    if not files:
        return {"verdict": "ERROR", "error": "no .sv/.v files found",
                "findings": []}
    defined: Set[str] = set()
    for text in files.values():
        defined |= set(_MODULE_DEF_RE.findall(text))

    findings: List[Dict] = []
    seen: Set[Tuple[str, str]] = set()
    for path, text in files.items():
        params = _param_defaults(text)
        for ref, pos in _instantiations(text):
            if ref in defined or ref in _NON_MODULE_KEYWORDS:
                continue
            key = (path, ref)
            if key in seen:
                continue
            seen.add(key)
            label = _enclosing_case_label(text, pos)
            if_cond = None
            label_is_if_generate = False
            if not label:
                _ifg = _enclosing_if_generate(text, pos)
                if _ifg:
                    label, if_cond = _ifg
                    label_is_if_generate = True
            if label:
                # selector parameters whose declared default's tail
                # matches the guarding label's tail (enum-token match,
                # scope-prefix tolerant: pkg::Val vs Val).
                if label_is_if_generate:
                    # if/else-generate: the guard is the CONDITION, not the
                    # label, so read the selecting defaults off the condition.
                    matching = _params_selecting(if_cond, params)
                else:
                    label_tail = label.split("::")[-1]
                    matching = sorted(
                        f"{p} = {v}" for p, v in params.items()
                        if v.split("::")[-1] == label_tail)
                # sibling alternatives: labels in the same case whose
                # branch instantiates an in-closure module.
                siblings = sorted({
                    r for r, _ in _instantiations(text)
                    if r in defined})
                findings.append({
                    "severity": "FAIL",
                    "rule": "generate_branch_default",
                    "file": path,
                    "module_ref": ref,
                    "guard_label": label,
                    "selecting_param_defaults": matching,
                    "guard_parameters": _guard_parameters(
                        if_cond, label, params),
                    "in_closure_alternatives": siblings[:8],
                    "message": (
                        f"module {ref!r} is referenced inside generate "
                        f"branch {label!r} but is NOT in the staged "
                        f"closure. "
                        + (f"The branch is selected by parameter "
                           f"DEFAULT(s) {matching} — yosys elaborates "
                           f"uninstantiated default branches and will "
                           f"abort. Rewrite the default to an in-closure "
                           f"variant"
                           + (f" (e.g. one that instantiates "
                              f"{siblings[0]!r})" if siblings else "")
                           + ", or stage the missing module."
                           if matching else
                           ("This is the ELSE branch of a generate "
                            "conditional; which parameter default selects "
                            "it was NOT derived (it is the negation of the "
                            "guard, which this check does not evaluate). "
                            "Read the guard above the branch before acting."
                            if if_cond is None and label_is_if_generate else
                            "No parameter default selects this branch — "
                            "an instantiation-tree override may avoid "
                            "elaboration, but yosys still elaborates "
                            "declared defaults; verify."))
                    ),
                })
            else:
                findings.append({
                    "severity": "FAIL",
                    "rule": "unconditional_dangling_ref",
                    "file": path,
                    "module_ref": ref,
                    "message": (f"module {ref!r} is instantiated outside "
                                f"any generate conditional and is NOT in "
                                f"the staged closure — genuine hole."),
                })
    return {
        "verdict": "PASS" if not findings else "FAIL",
        "files_scanned": len(files),
        "modules_defined": sorted(defined),
        "findings": findings,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("targets", nargs="+", help="staged RTL file(s)/dir(s)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    report = audit(args.targets)
    if report["verdict"] == "ERROR":
        print(f"error: {report['error']}", file=sys.stderr)
        return 2
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    print(f"=== staged_rtl_closure_preflight "
          f"({report['files_scanned']} file(s)) ===")
    print(f"  verdict: {report['verdict']}")
    for f in report["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
