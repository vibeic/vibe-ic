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
"""
from __future__ import annotations

import argparse
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


def _instantiations(text: str) -> List[Tuple[str, int]]:
    """[(module_ref, offset)] of plausible instantiations."""
    out: List[Tuple[str, int]] = []
    for m in _INST_FULL_RE.finditer(text):
        ref, inst = m.group(1), m.group(2)
        if ref in _NON_MODULE_KEYWORDS or inst in _NON_MODULE_KEYWORDS:
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
            if label:
                # selector parameters whose declared default's tail
                # matches the guarding label's tail (enum-token match,
                # scope-prefix tolerant: pkg::Val vs Val).
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
                           "No parameter default selects this branch — "
                           "an instantiation-tree override may avoid "
                           "elaboration, but yosys still elaborates "
                           "declared defaults; verify.")
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
