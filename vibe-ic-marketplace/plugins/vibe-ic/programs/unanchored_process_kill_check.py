#!/usr/bin/env python3
"""unanchored_process_kill_check.py — no shipped code may choose which process
to KILL by matching a command-line pattern.

THE RULE
    `pkill` and `killall` select victims by matching a name or a command line.
    A command line is not an identity. Two runs of the same tool on the same
    design carry the SAME argv, so a pattern cannot tell this job's process
    from a stranger's — and on this fleet every run on a host execs into ONE
    shared long-lived container, which means the two processes share a PID
    namespace and the stranger is the LIKELY match, not the unlikely one.

WHAT IT COST (measured 2026-08-27)
    `_docker_watchdog` and `phase3_one_shot_runner` each reaped a stalled tool
    with `pkill -TERM/-KILL -f <marker>` — no `-x`, no uid, no pid, no pgid.
    One run's stall watchdog SIGTERMed a DIFFERENT run's healthy tool. The
    signature is `rc=143 with ZERO test failures`; it was seen three times in
    one night at 85 s, 17 min and 46 min, with no cgroup OOM in dmesg. Because
    `lec_run` did not carry 143 in its container-timeout set, the stray SIGTERM
    fell through to a hard FAIL and a HEALTHY design was published as a PROVEN
    NON-EQUIVALENCE. A reaper that hits the wrong process does not merely waste
    a run; it manufactures a false verdict about silicon.

WHY `-x` IS NOT AN ESCAPE
    `-x` requires the WHOLE command line to match exactly — and the stranger's
    command line IS exactly the same. `-x` makes the pattern stricter without
    making the selection correct, so this gate rejects it too. There is no
    "careful enough" pattern; the fix is to stop selecting by name.

WHAT TO DO INSTEAD
    Select by IDENTITY, as `_owned_process_supervisor` already does:
    `(pid, /proc starttime)` for the root plus the descendants reached by
    walking ppid from it. For an in-container job, stamp that identity at spawn
    and read it back at reap time — `_docker_watchdog.new_job_pidfile`,
    `identity_stamp_prelude`, `reap_command`, `kill_supervised_job`.

SCOPE
    Executable code only. Comments and docstrings are blanked before scanning,
    so this file, and the incident write-ups that must keep naming `pkill` to
    explain themselves, do not trip the gate they document. That is deliberate:
    a gate that punishes its own explanation gets its explanation deleted.

chip-AGNOSTIC: pure source analysis, no vendor / SKU / IC literal.
"""
from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path
from typing import Dict, List, Tuple

BANNED = ("pkill", "killall")
_CMD_RE = re.compile(r"\b(%s)\b\s+\S" % "|".join(BANNED))
_LAUNCHERS = frozenset({"run", "Popen", "call", "check_output", "check_call",
                        "getoutput", "getstatusoutput", "system", "exec"})
# `tests` holds this gate's OWN fixtures (defect samples it must be able to
# recognise), so scanning it would make the gate fail on its own evidence.
# Note `mcp-eda/test` is NOT covered by this name and is scanned -- a real
# pattern kill lived there, and a directory-naming accident must not be what
# decides whether a site is examined.
_SKIP_DIR_PARTS = {".git", "__pycache__", ".pytest_cache", "node_modules",
                   "tests"}
_PLACEHOLDER = "\x00"


class Unscannable(Exception):
    """A file that could not be parsed. NEVER silently clean.

    An earlier draft of this gate blanked comments and docstrings out of the
    source text and re-parsed the result. Blanking a class whose body was only
    a docstring left `class X:` with no body, the re-parse raised SyntaxError,
    and the gate returned "no hits" — it reported `phase3_one_shot_runner.py`
    CLEAN while that file still contained both `pkill -f` reapers. A detector
    whose failure mode is a PASS is worse than no detector, because it is
    believed. The analysis now runs on the real AST (comments are not in it,
    and docstrings are identified by node, not by blanking text), and an
    unparseable file is an ERROR, not a pass."""


def _docstring_nodes(tree: ast.AST):
    """Every Constant node that is a docstring — the only string a module is
    allowed to say `pkill` in, because that is where the incident is explained
    and a gate that punishes its own explanation gets its explanation deleted."""
    out = set()
    holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


def _joined_text(node: ast.AST) -> str:
    """Flatten a str constant or an f-string into scannable text.

    An f-string's interpolations become a placeholder so `f"pkill -f {q}"`
    still reads as a command with arguments — the exact form both shipped
    reapers took."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append(_PLACEHOLDER)
        return "".join(parts)
    return ""


def _is_bare_banned(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in BANNED)


class _Finder(ast.NodeVisitor):
    """Three ways a pattern-based kill reaches a process, and only those.

    The gate flags an INVOCATION, never a MENTION. That distinction is
    load-bearing rather than lenient: a gate that fires on the word cannot be
    written without exempting itself, and a gate with an exemption list is a
    gate that grows exemptions. These rules carry no exemption list, and this
    file passes the gate on the same terms as every other file."""

    def __init__(self, docstrings):
        self.hits = []          # (lineno, rule, detail)
        self._docstrings = docstrings

    # (1) a string that reads as a command line: `pkill <arg>` / `killall <arg>`
    def _check_command_text(self, node):
        if id(node) in self._docstrings:
            return
        text = _joined_text(node)
        if not text:
            return
        m = _CMD_RE.search(text)
        if m:
            self.hits.append((node.lineno, "command-string",
                              text.replace(_PLACEHOLDER, "{...}")[:90]))

    def visit_Constant(self, node):
        self._check_command_text(node)

    def visit_JoinedStr(self, node):
        # do NOT recurse: the constant parts are fragments of THIS string
        self._check_command_text(node)

    # (2) an argv sequence handed to a process launcher.
    #
    # The primitive is looked for at ANY position, not just argv[0]. The form
    # that motivated widening this is real and was missed by a position-0 rule:
    #
    #     subprocess.run([_DOCKER, "exec", _CONTAINER, "pkill", "-f", marker])
    #
    # argv[0] there is `docker`; the pattern kill rides in as argv[3] and lands
    # inside the SHARED long-lived container -- the same blast radius as the
    # two reapers this gate was written for.
    def visit_Call(self, node):
        fn = node.func
        name = (fn.attr if isinstance(fn, ast.Attribute)
                else fn.id if isinstance(fn, ast.Name) else "")
        if name in _LAUNCHERS:
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if isinstance(arg, (ast.List, ast.Tuple)):
                    for elt in arg.elts:
                        if _is_bare_banned(elt):
                            self.hits.append(
                                (node.lineno, "argv-list",
                                 "%s([... %r ...])" % (name, elt.value)))
        self.generic_visit(node)

    # (3) a bare primitive being BUILT into a command by concatenation
    def visit_BinOp(self, node):
        if isinstance(node.op, ast.Add):
            for side in (node.left, node.right):
                if _is_bare_banned(side):
                    self.hits.append((node.lineno, "concatenated",
                                      "%r + ..." % side.value))
        self.generic_visit(node)


def scan_source(src: str):
    """[(lineno, rule, detail)] for each pattern-based kill INVOCATION.

    Raises `Unscannable` when the source does not parse — the caller must
    surface that, never treat it as clean."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise Unscannable(str(exc)) from exc
    f = _Finder(_docstring_nodes(tree))
    f.visit(tree)
    return sorted(set(f.hits))


def iter_python_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if _SKIP_DIR_PARTS & set(p.parts):
            continue
        yield p


def scan_tree(root: Path) -> Dict[Path, List[Tuple[int, str, str]]]:
    found: Dict[Path, List[Tuple[int, str, str]]] = {}
    for p in iter_python_files(root):
        try:
            src = p.read_text(errors="replace")
        except OSError:
            continue
        if not any(b in src for b in BANNED):
            continue                  # cheap reject before the AST work
        try:
            hits = scan_source(src)
        except Unscannable as exc:
            # Fail CLOSED. A file this gate cannot read is a file it cannot
            # clear, and the one thing it must never do is stay quiet.
            found[p] = [(0, "unscannable", str(exc))]
            continue
        if hits:
            found[p] = hits
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent),
                    help="directory to scan (default: this programs/ dir)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    found = scan_tree(root)
    if not found:
        print("PASS unanchored_process_kill_check: no pattern-based process "
              "kill in executable code under %s" % root)
        return 0

    print("FAIL unanchored_process_kill_check: a process is being selected "
          "for signalling by PATTERN, which cannot distinguish this job's "
          "process from a stranger's.")
    for path, hits in sorted(found.items()):
        for line_no, rule, detail in hits:
            print("  %s:%d: [%s] %s" % (path, line_no, rule, detail))
    print("\nSelect by IDENTITY instead — (pid, /proc starttime) plus ppid-"
          "walked descendants. For an in-container job use "
          "_docker_watchdog.kill_supervised_job(); see "
          "_owned_process_supervisor for the host-side original. `-x` is NOT "
          "a fix: the stranger's command line is identical.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
