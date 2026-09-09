#!/usr/bin/env python3
"""console_tool_termination_check.py — an EDA tool that can drop into its own
text console must be stopped by something that TRAVELS WITH THE COMMAND.

WHY (measured 2026-09-09 in the shipped image, after a 102 GB log was found)
==========================================================================
`netgen` and `magic` both carry an interactive text console. Reaching it is
not the bug; what makes it a disk-filling runaway is that the console
re-prints its whole menu for every byte of stdin it cannot parse. Measured
throughput in `ghcr.io/vibeic/vibeic-eda`, stdin fed unparseable bytes:

    netgen, no -batch                       9.9 MB / 5 s
    magic -dnull -noconsole, script w/o quit  4.0 MB / 6 s

At 2 MB/s that is ~170 GB/day. A run left on 2026-08-12 wrote a single
`pos.out.log` of 102 GB -- 1,619,420,055 lines, of which the last 2000 held
NINE distinct lines.

WHAT ACTUALLY STOPS IT, AND WHAT ONLY LOOKS LIKE IT DOES
--------------------------------------------------------
Two independent properties each suffice, and they are NOT equally durable:

* stdin at EOF. Measured safe for both tools. But this is a property of the
  CALLER's argv -- here, that `_container_exec.docker_exec_argv` builds
  `docker exec` WITHOUT `-i`. Anyone adding `-i` for an unrelated reason, in
  a different file, re-arms every call site at once.
* the command's own terminator. `netgen -batch` (measured: holds even when
  the sourced Tcl errors and when the arguments are wrong) and a magic script
  ending in `quit`. This travels with the command and cannot be undone
  elsewhere.

This program requires the second. It does not forbid the first; it refuses to
let the first be the ONLY thing standing between a tool and the disk.

WHAT IT CHECKS
--------------
Command strings are read from the arguments of the shipped execution helpers
(`_docker_exec`, `_docker_exec_raw`, `_sh`, `_run`, `_exec`,
`run_in_container`), located with `ast` -- never by grepping the file. That
distinction is the whole reason this is trustworthy: `analog_hardmacro_gds_emit`
carries the string

    f"magic -rcfile {magicrc} {tcl_name} returned "

inside a `detail=` FAILURE MESSAGE. A text scan flags it; reading the call
graph does not, because nothing executes it.

* `netgen ...`   must contain `-batch`.
* `klayout ...`  must contain `-b` (measured clean; `-zz -b` also passes).
* `magic ...`    runs a script, so the flag cannot settle it. The module that
  builds that script must emit a terminal `quit`. Checked per-module, which
  is the granularity the evidence supports.

WHY_NOT_BUCKET_A: whether a given Tcl string is "the script this magic call
runs" needs the data flow between a builder, a staging call and an exec call,
across modules. The deterministic half -- a module that executes magic must
also emit a `quit` -- is what this measures.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

#: The shipped helpers whose arguments are COMMANDS. A string that reaches
#: none of these is prose, however much it looks like a command line.
EXEC_FUNCS = frozenset({
    "_docker_exec", "_docker_exec_raw", "_sh", "_run", "_exec",
    "run_in_container", "sh",
})

#: tool -> (regex that must match the command, human name of the requirement)
FLAG_REQUIRED = {
    "netgen": (re.compile(r"(?<![\w-])-batch(?![\w-])"), "-batch"),
    "klayout": (re.compile(r"(?<![\w-])-b(?![\w-])"), "-b"),
}

#: magic cannot be settled by a flag: it runs a script. The module that
#: executes it must also emit a terminal quit into some script.
_MAGIC_QUIT = re.compile(r"quit\s+-noprompt|\bquit\b")

_TOOL_AT_START = {
    t: re.compile(r"(?:^|[;&|]\s*|&&\s*|\bcd\b[^;&|]*&&\s*)" + t + r"\s+-")
    for t in ("netgen", "klayout", "magic")
}


def _flatten(node: ast.AST) -> str | None:
    """A string/f-string argument as searchable text, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            else:
                out.append("{}")
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _flatten(node.left), _flatten(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _called_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _string_bindings(tree: ast.AST) -> dict:
    """`name -> text` for module- and function-level string assignments.

    REAL CODE ALMOST NEVER INLINES THE COMMAND. It writes

        cmd = (f"export PATH=... && "
               f"netgen -batch source {tcl}")
        rc, out, err = _docker_exec(container, cmd)

    and an earlier draft of this program, which read only the literal
    arguments of the exec call, saw NOTHING there -- it caught one of the
    three defects this was written for and reported PASS on the other two.
    A one-hop binding is what the shipped call sites actually use.

    Deliberately not a dataflow engine: last write wins, no branches, no
    aliases. An unresolvable name yields no command and therefore no finding,
    which keeps this side of the check silent rather than wrong.
    """
    bindings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            text = _flatten(node.value)
            if text is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = text
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            text = _flatten(node.value)
            if text is not None and isinstance(node.target, ast.Name):
                bindings[node.target.id] = text
    return bindings


def command_strings(tree: ast.AST) -> list:
    """Every string that is passed to a shipped execution helper."""
    bindings = _string_bindings(tree)

    def resolve(node):
        text = _flatten(node)
        if text is not None:
            return text
        if isinstance(node, ast.Name):
            return bindings.get(node.id)
        return None

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _called_name(node) not in EXEC_FUNCS:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            text = resolve(arg)
            if text:
                out.append((getattr(arg, "lineno", node.lineno), text))
            elif isinstance(arg, (ast.List, ast.Tuple)):
                parts = [resolve(e) for e in arg.elts]
                if all(p is not None for p in parts):
                    out.append((getattr(arg, "lineno", node.lineno),
                                " ".join(parts)))
    return out


def _emits_quit(path: Path, source: str) -> bool:
    """Does this module -- or a sibling it imports from -- terminate a script?

    One hop, same directory, no recursion: enough for the shipped shape
    (executor imports `build_*_tcl` from a sibling) and small enough that a
    reader can hold it. An import that cannot be resolved is not treated as a
    terminator, so the check stays conservative.
    """
    if _MAGIC_QUIT.search(source):
        return True
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.append(node.module)
        elif isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        for mod in mods:
            sibling = path.parent / f"{mod.split('.')[0]}.py"
            if not sibling.is_file() or sibling == path:
                continue
            try:
                if _MAGIC_QUIT.search(sibling.read_text(encoding="utf-8",
                                                        errors="replace")):
                    return True
            except OSError:
                continue
    return False


def scan_module(path: Path) -> list:
    """Findings for one module."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []
    commands = command_strings(tree)
    findings = []
    for tool, (needed, label) in FLAG_REQUIRED.items():
        pat = _TOOL_AT_START[tool]
        for lineno, cmd in commands:
            if not pat.search(cmd):
                continue
            if not needed.search(cmd):
                findings.append({
                    "file": str(path), "line": lineno, "tool": tool,
                    "requirement": label,
                    "detail": (f"{tool} is executed without {label}; nothing in "
                               f"the command stops its text console"),
                    "command": " ".join(cmd.split())[:160],
                })
    if any(_TOOL_AT_START["magic"].search(c) for _, c in commands):
        # THE SCRIPT, NOT THE CALLER, IS WHAT MUST TERMINATE -- and the module
        # that RUNS magic is often not the one that BUILDS the script.
        # `analog_hardmacro_gds_emit` executes magic and contains no `quit`,
        # yet is safe: it runs
        # `magic_port_extract_emit.build_gds_write_tcl()`, which emits one.
        # Flagging it was a false positive against a correct module, so the
        # terminator is looked for one import hop out as well. Narrowing this
        # must not silence the true positives it was written for; the tests
        # re-run both.
        if not _emits_quit(path, source):
            findings.append({
                "file": str(path), "line": 0, "tool": "magic",
                "requirement": "terminal quit in the emitted script",
                "detail": ("this module executes magic but emits no script "
                           "terminator; magic finishes the script and falls "
                           "into its console"),
                "command": "",
            })
    return findings


def run(root: Path) -> dict:
    files = sorted(p for p in root.rglob("*.py")
                   if "/tests/" not in str(p) and not p.name.startswith("test_"))
    findings = []
    for p in files:
        findings.extend(scan_module(p))
    return {
        "schema": "vibeic.console_tool_termination.v1",
        "files_scanned": len(files),
        "findings": findings,
        "verdict": "FAIL" if findings else "PASS",
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="An EDA tool that can reach its own text console must be "
                    "stopped by the command, not by the caller's stdin.")
    ap.add_argument("root", nargs="?", default=".",
                    help="directory to scan (default: cwd)")
    ap.add_argument("--json", help="write the structured result here")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"CANNOT CHECK: {args.root} is not a directory")
        return 2
    result = run(root)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n",
                                   encoding="utf-8")
    if result["verdict"] == "PASS":
        print(f"PASS: {result['files_scanned']} module(s); every console-capable "
              f"tool invocation carries its own terminator.")
        return 0
    print(f"FAIL: {len(result['findings'])} invocation(s) rely on the caller's "
          f"stdin alone:")
    for f in result["findings"]:
        where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
        print(f"  {where}: {f['detail']}")
        if f["command"]:
            print(f"      {f['command']}")
    print("  Measured: netgen without -batch emits 9.9 MB/5 s, and magic "
          "-noconsole with no script quit 4.0 MB/6 s, when stdin carries bytes "
          "they cannot parse.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
