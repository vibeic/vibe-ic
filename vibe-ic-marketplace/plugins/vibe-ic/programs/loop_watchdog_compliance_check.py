#!/usr/bin/env python3
"""loop_watchdog_compliance_check.py — FORCE the watchdog primitive.

Owner directive (v1.3.48): "let watchdog be the common process for loop in the
vibe-ic plugin; force AI to use such watchdog for any loop." A fixed-timeout
estimate murders a healthy, still-progressing EDA sub-process (proven on ibex),
and an unbounded poll/retry/convergence loop can spin forever. The shared
`_watchdog.py` primitive removes both failure modes — `run_supervised` (progress-
stall supervision of a sub-process) and `loop_guard` (bounded, no-progress-aware
in-process loop). This gate is the MECHANICAL enforcement that no future change
(AI- or human-authored) re-introduces an UNGUARDED long sub-process or an
unbounded risky loop.

It statically scans ``programs/*.py`` (NOT ``tests/``; NOT ``_watchdog.py``
itself; NOT this gate) and FAILs (exit 1) listing every offender ``file:line``.

OFFENSE CLASSES
===============
(a) An external sub-process launch of a LONG EDA tool that is NOT supervised:
      * ``subprocess.{run,Popen,call,check_output,check_call}`` whose argv[0]
        basename is a long tool (openroad, yosys, klayout, magic, netgen,
        ngspice, iverilog, sta) — a direct host launch under no watchdog.
      * a ``_docker_exec(...)`` call whose command invokes a long tool but which
        carries NO ``marker=`` kwarg (the marker is what routes _docker_exec
        through ``_watchdog.run_supervised``).
    Compliant forms: launch via ``_watchdog.run_supervised(...)`` (or a
    ``*.run_supervised``), or ``_docker_exec(..., marker=...)``.

(b) An unbounded / poll / retry loop that is NOT guarded:
      * a ``while`` loop whose body launches a sub-process (subprocess.* /
        _docker_exec / run_supervised) or sleeps (a poll) — a while loop cannot
        be driven by ``loop_guard`` (that is a ``for`` iterable), so it must be
        refactored or annotated.
      * a ``for`` loop over an INFINITE iterator (itertools.count/cycle/repeat,
        or the two-arg ``iter(callable, sentinel)``) whose body sleeps or
        launches a sub-process, unless it is a ``loop_guard(...)`` iterable.
    A ``for`` over a finite range / literal / collection is trivially bounded
    and is NEVER flagged (the spec: "a bounded for over a fixed list stays a
    plain loop"); any long sub-process inside it is judged by class (a).

(c) An OPAQUE SHELL-RUNNER that the gate cannot AST-inspect (v1.3.53 — SURFACES
    the v1.3.48 documented boundary instead of missing it silently):
      * a ``subprocess.{run,Popen,call,check_output,check_call}`` (or a
        ``_docker_exec``) whose argv is ``bash``/``sh <script>.{sh,bash}`` — a
        shell script the gate cannot read. The script may launch a long EDA
        tool that then escapes supervision, so the shell-runner is FLAGGED
        (the author must supervise it OR justify it).
      * a ``bash -c "<inline>"`` one-liner is judged by CONTENT, not shape: it
        is flagged ONLY when the inline command names a long tool (a
        ``bash -c "openroad …"`` launches long work unsupervised); a plain
        ``bash -c "echo …"`` with no long-tool token stays EXEMPT.
    Compliant forms: route through ``_watchdog.run_supervised`` /
    ``_docker_exec(..., marker=...)``, or add ``# watchdog-exempt: <reason>``
    (used to justify a genuinely bounded existing shell-runner — the boundary
    is now surfaced, not unbounded).

    KNOWN RESIDUAL BOUNDARY (stated, not silent): an argv whose FIRST element is
    built by a runtime string-concat under ``shell=True``
    (``cmd = "bash " + script; subprocess.run(cmd, shell=True)``) cannot have its
    argv[0] statically resolved, so neither class (a) (long tool) nor class (c)
    (shell-runner) can inspect it — the same inherent limit for any dynamically
    assembled command. This is an acknowledged edge, not a covered case; the
    common shapes (a ``bash``/``sh`` LIST argv, or a single-literal string) ARE
    covered.

EXEMPTIONS (precise — the gate errs toward an allowlist, never toward flagging
every loop):
  * ``argv[0]`` that is a benign short host command (docker, which, git, cat,
    ls, ps, pkill, rm, mkdir, python, …) — never a long generator.
  * a ``for`` loop over a finite iterable (bounded by construction).
  * an inline ``# watchdog-exempt: <reason>`` annotation on the offending
    statement (anywhere in its source span, or the line immediately above).
    The reason after the colon must be non-empty — a bare tag does not exempt.

CLI
===
    loop_watchdog_compliance_check.py [ROOT] [--programs-dir DIR] [--json OUT]
ROOT defaults to this program's plugin root; the scan target is ``ROOT/programs``
if present, else ROOT, else the explicit ``--programs-dir``.

Exit codes: 0 = clean, 1 = >=1 offender, 2 = usage/parse error.

chip-AGNOSTIC + tool-AGNOSTIC: reasons over Python AST shapes and a fixed list
of tool BINARY names + benign host commands only — no IC / vendor / SKU logic.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── the fixed lexicons ────────────────────────────────────────────────────
LONG_TOOLS = frozenset({
    "openroad", "yosys", "klayout", "magic", "netgen", "ngspice", "iverilog",
    "sta",
})
SUBPROC_LAUNCHERS = frozenset({"run", "Popen", "call", "check_output",
                               "check_call"})
# argv[0] values that are always short/benign host utilities, never a long
# open-ended generator — safe under a plain fixed timeout / no supervision.
BENIGN_ARGV0 = frozenset({
    "which", "command", "docker", "git", "cat", "ls", "ps", "pkill", "kill",
    "echo", "printf", "mkdir", "rm", "cp", "mv", "test", "true", "false",
    "sh", "bash", "env", "python", "python3", "grep", "sed", "awk", "head",
    "tail", "sync", "touch", "chmod", "sleep", "tee", "wc", "find", "sort",
    "uniq", "diff", "gzip", "gunzip", "tar", "cd", "export",
})
# itertools iterators with no natural bound.
INFINITE_ITERS = frozenset({"count", "cycle", "repeat"})
EXEMPT_TAG = "# watchdog-exempt:"

# v1.3.53 — OFFENSE CLASS (c): opaque shell-runners. `bash`/`sh` as argv[0]
# is a BENIGN short launcher, but `bash <script>.sh` runs an OPAQUE script the
# gate cannot AST-inspect; a long EDA tool launched from inside the script
# escapes classes (a)/(b) silently. We SURFACE that boundary.
SHELL_RUNNERS = frozenset({"bash", "sh"})

# In a shell STRING (a _docker_exec blob or a bare-string argv): a `bash|sh`
# invocation, then any run of START-UP flags — LONG (`--norc`, `--noprofile`,
# `--rcfile`, `--login`) or SHORT non-command (`-x`, `-l`) but NEVER a short
# `-c` command bundle — then a `.sh`/`.bash` SCRIPT FILE token. Precise: a
# `bash -c "echo …"` one-liner has no script-file token, so it does NOT match;
# and a common CI wrapper like `bash --norc run.sh` IS caught (the long
# start-up flag no longer masks the trailing script). NOTE: an option that
# takes a SEPARATE argument in a shell string (`--rcfile r run.sh`) can still
# leave a residual in the string form — the argv-LIST form (the common shape)
# handles it robustly by scanning every token for a `.sh`/`.bash` literal.
_SHELL_SCRIPT_RUNNER_RE = re.compile(
    r'(?:^|[\s;&|/(=])(?:bash|sh)\s+'
    r'(?:(?:--[A-Za-z][\w-]*|-(?![A-Za-z]*c\b)[A-Za-z]+)\s+)*'   # long OR short-non-c flags
    r'(?P<script>[^\s;&|"\'`]+\.(?:sh|bash))(?=[\s;&|"\'`]|$)')

# A SHORT `-c` command bundle in a shell string (single dash, letters include
# c: `-c`/`-lc`/`-ic`). A LONG flag like `--norc`/`--rcfile` is NOT this (the
# anchored `bash\s+-…c` requires the c-bundle to be the FIRST short flag). The
# token after it is an inline command, which then gets the ordinary long-tool
# scan — so `bash -c "openroad …"` is caught while `bash -c "echo …"` is not.
_SHELL_DASHC_RE = re.compile(r'(?:^|[\s;&|/(=])(?:bash|sh)\s+-[A-Za-z]*c\b')

# A long tool invoked as a COMMAND inside a shell string: the tool name
# preceded by a start/separator and followed by whitespace / a flag / quote /
# end. Precise enough that "install"/"status"/"sta_report"/"/magic/foo" do not
# match, while "sta -exit", "&& magic -dnull", "yosys -s" do.
_CMD_TOOL_RE = re.compile(
    r'(?:^|[\s;&|/=("\'`])(' + "|".join(sorted(LONG_TOOLS)) + r')(?=[\s"\'`-]|$)')

# A tool PRESENCE probe (`command -v sta`, `which magic`, `type yosys`) names a
# long tool as an ARGUMENT, not an invocation — strip these before the tool
# search so a literal presence probe is never mistaken for a long tool run.
_PRESENCE_PROBE_RE = re.compile(r'\b(?:command\s+-v|which|type|hash)\s+\S+')

# Files never scanned.
_SKIP_FILES = frozenset({"_watchdog.py", "loop_watchdog_compliance_check.py"})


@dataclass
class Offense:
    file: str
    line: int
    kind: str      # 'subprocess'|'docker_exec'|'while'|'for'|'shell_runner'
    detail: str


# ── literal / name helpers ────────────────────────────────────────────────
def _str_literal_parts(node: ast.AST) -> List[str]:
    """Constant-string parts of a Constant / f-string / str concatenation."""
    out: List[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.append(node.value)
    elif isinstance(node, ast.JoinedStr):
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append(v.value)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        out += _str_literal_parts(node.left) + _str_literal_parts(node.right)
    return out


def _const_str(node: ast.AST, names: Dict[str, str]) -> Optional[str]:
    """A single string value if the node is a Constant str or a Name bound to a
    string constant in `names` (module/function scope)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    parts = _str_literal_parts(node)
    return " ".join(parts) if parts else None


def _argv0_basename(call: ast.Call, names: Dict[str, str],
                    list_vars: Optional[Dict[str, List[Tuple[int, ast.AST]]]] = None
                    ) -> Optional[str]:
    """Best-effort argv[0] basename of a subprocess launcher call. Resolves an
    argv that is a list literal, a bare/f-string command, OR a Name bound to a
    list literal (`cmd = ['openroad', ...]; subprocess.run(cmd)`) — closing the
    argv-indirection evasion."""
    if not call.args:
        return None
    a0 = call.args[0]
    # Name bound to a list literal → resolve to the nearest preceding list.
    if isinstance(a0, ast.Name) and list_vars and a0.id in list_vars:
        before = [node for (ln, node) in list_vars[a0.id] if ln <= call.lineno]
        lst = before[-1] if before else list_vars[a0.id][0][1]
        if isinstance(lst, (ast.List, ast.Tuple)) and lst.elts:
            s = _const_str(lst.elts[0], names)
            return os.path.basename(s.strip()) if s else None
    # list/tuple argv literal → first element
    if isinstance(a0, (ast.List, ast.Tuple)) and a0.elts:
        s = _const_str(a0.elts[0], names)
        return os.path.basename(s.strip()) if s else None
    # bare string / f-string command → leading token
    s = _const_str(a0, names)
    if s:
        toks = s.strip().split()
        if toks:
            return os.path.basename(toks[0])
    return None


def _collect_list_vars(fn: ast.AST) -> Dict[str, List[Tuple[int, ast.AST]]]:
    """var → list of (lineno, List/Tuple node) assigned to it in `fn`."""
    out: Dict[str, List[Tuple[int, ast.AST]]] = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name) \
                and isinstance(n.value, (ast.List, ast.Tuple)) and n.value.elts:
            out.setdefault(n.targets[0].id, []).append((n.lineno, n.value))
    return out


# ── per-function local literal maps (for _docker_exec cmd tracing) ─────────
def _collect_str_consts(scope_nodes) -> Dict[str, str]:
    """`NAME = "literal"` bindings in a scope (best-effort, last write wins)."""
    out: Dict[str, str] = {}
    for n in scope_nodes:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name) \
                and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            out[n.targets[0].id] = n.value.value
    return out


def _collect_cmd_text(fn: ast.AST) -> Dict[str, List[Tuple[int, str]]]:
    """var → list of (lineno, string-literal text) for each assignment to it in
    `fn`. A `_docker_exec(container, cmd, ...)` call resolves `cmd` to the
    NEAREST PRECEDING assignment only (see `_cmd_text_before`) so a var name
    reused for both a long tool and a short probe never cross-contaminates —
    that would be a false positive."""
    text: Dict[str, List[Tuple[int, str]]] = {}
    for n in ast.walk(fn):
        if isinstance(n, (ast.Assign, ast.AugAssign)):
            tgt = (n.targets[0] if isinstance(n, ast.Assign) and n.targets
                   else getattr(n, "target", None))
            if isinstance(tgt, ast.Name):
                parts = _str_literal_parts(n.value)
                if parts:
                    text.setdefault(tgt.id, []).append(
                        (n.lineno, " ".join(parts)))
    return text


def _cmd_text_before(cmap: Dict[str, List[Tuple[int, str]]],
                     var: str, call_line: int) -> str:
    """Literal text of the nearest assignment to `var` at or before
    `call_line`; falls back to the last assignment if none precedes (handles
    augmented builds whose final append is on the call line)."""
    entries = cmap.get(var)
    if not entries:
        return ""
    before = [t for (ln, t) in entries if ln <= call_line]
    if before:
        return before[-1]
    return entries[0][1]


def _collect_loopguard_vars(fn: ast.AST) -> set:
    """Names bound to a loop_guard(...) call — a `for i in g:` over such a var
    is a guarded loop."""
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name) \
                and _is_loop_guard_call(n.value):
            out.add(n.targets[0].id)
    return out


def _is_loop_guard_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Name):
        return f.id == "loop_guard"
    if isinstance(f, ast.Attribute):
        return f.attr == "loop_guard"
    return False


# ── call classifiers ───────────────────────────────────────────────────────
def _is_subprocess_launcher(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr in SUBPROC_LAUNCHERS
            and isinstance(f.value, ast.Name) and f.value.id == "subprocess")


def _is_docker_exec(call: ast.Call) -> bool:
    f = call.func
    return ((isinstance(f, ast.Name) and f.id == "_docker_exec")
            or (isinstance(f, ast.Attribute) and f.attr == "_docker_exec"))


def _is_sleep(call: ast.Call) -> bool:
    f = call.func
    return isinstance(f, ast.Attribute) and f.attr == "sleep"


def _is_run_supervised(call: ast.Call) -> bool:
    f = call.func
    return ((isinstance(f, ast.Name) and f.id == "run_supervised")
            or (isinstance(f, ast.Attribute) and f.attr == "run_supervised"))


def _launches_subprocess(call: ast.Call) -> bool:
    return (_is_subprocess_launcher(call) or _is_docker_exec(call)
            or _is_run_supervised(call))


def _has_marker(call: ast.Call) -> bool:
    return any(k.arg == "marker" for k in call.keywords)


# ── class (c): opaque shell-runner detection (v1.3.53) ─────────────────────
def _inline_longtool(cmd: Optional[str]) -> Optional[str]:
    """If an inline `-c` command string names a long tool, return the tool
    name; else None. (`bash -c "openroad …"` launches long work; `bash -c
    "echo …"` does not.)"""
    if not cmd:
        return None
    m = _CMD_TOOL_RE.search(_PRESENCE_PROBE_RE.sub(" ", cmd))
    return m.group(1) if m else None


def _shell_runner_offense(call: ast.Call, names: Dict[str, str],
                          list_vars: Dict[str, List[Tuple[int, ast.AST]]],
                          ) -> Optional[str]:
    """Return an offense-detail string if a `bash`/`sh` launcher is an OPAQUE
    script-runner (`bash <script>.sh|.bash`, literal OR a dynamic script path)
    OR a `bash -c` inline that names a long tool; else None.

    argv[0] must already be a bash/sh basename (checked by the caller). PRECISE:
    a `bash -c "echo …"` one-liner with no long-tool token returns None."""
    if not call.args:
        return None
    a0 = call.args[0]

    # Resolve a LIST/TUPLE argv (literal, or a Name bound to one) → walk tokens.
    elts: Optional[List[ast.AST]] = None
    if isinstance(a0, (ast.List, ast.Tuple)) and a0.elts:
        elts = list(a0.elts)
    elif isinstance(a0, ast.Name) and a0.id in list_vars:
        before = [n for (ln, n) in list_vars[a0.id] if ln <= call.lineno]
        lst = before[-1] if before else list_vars[a0.id][0][1]
        if isinstance(lst, (ast.List, ast.Tuple)) and lst.elts:
            elts = list(lst.elts)

    if elts is not None:
        rest = elts[1:]                      # everything after argv[0] (bash/sh)
        # step 1 — a SHORT `-c` command bundle (single dash, letters include c:
        # `-c`/`-lc`/`-ic`) means the NEXT token is an INLINE command, not a
        # script. A LONG flag (`--norc`/`--rcfile`/`--noprofile`) is NEVER the
        # command flag (that is the FN-1 fix: `"c" in flag` used to mis-treat
        # `--norc` as `-c`). Judge the inline by long-tool CONTENT.
        for idx, e in enumerate(rest):
            s = _const_str(e, names)
            if (s is not None and s.startswith("-") and not s.startswith("--")
                    and "c" in s[1:]):
                nxt = rest[idx + 1] if idx + 1 < len(rest) else None
                tool = _inline_longtool(
                    _const_str(nxt, names) if nxt is not None else None)
                if tool:
                    return (f"bash -c inline launches long tool '{tool}' "
                            f"unsupervised (route via run_supervised / "
                            f"_docker_exec marker= or annotate)")
                return None                  # benign inline one-liner → exempt
        # step 2a — no `-c` inline: ANY literal `.sh`/`.bash` token is the
        # opaque script (works past start-up flags AND option-args like
        # `--rcfile r run.sh` that the string-regex form cannot skip).
        for e in rest:
            s = _const_str(e, names)
            if s is not None and (s.endswith(".sh") or s.endswith(".bash")):
                return (f"opaque shell-runner 'bash {s}' — the script the "
                        f"gate cannot AST-inspect may launch a long tool "
                        f"that escapes supervision")
        # step 2b — a DYNAMIC positional token (non-const, e.g. str(runner)
        # where runner=…/run.sh) is a script path the gate cannot read → flag.
        for e in rest:
            if _const_str(e, names) is None:
                return ("opaque shell-runner 'bash <script>' (dynamic script "
                        "path) — the script the gate cannot AST-inspect may "
                        "launch a long tool that escapes supervision")
        return None

    # Bare-string / f-string command form.
    full = _const_str(a0, names)
    if full:
        if _SHELL_DASHC_RE.search(full):
            tool = _inline_longtool(full)
            if tool:
                return (f"bash -c inline launches long tool '{tool}' "
                        f"unsupervised")
            return None
        m = _SHELL_SCRIPT_RUNNER_RE.search(full)
        if m:
            return (f"opaque shell-runner 'bash {m.group('script')}' — the "
                    f"script the gate cannot AST-inspect may launch a long "
                    f"tool that escapes supervision")
    return None


def _blob_shell_runner_offense(blob: str) -> Optional[str]:
    """Return an offense-detail if a _docker_exec shell blob invokes a
    `bash|sh <script>.sh|.bash` runner (the long tool hidden inside the script
    escapes the ordinary blob long-tool scan). A `bash -c "<inline>"` is NOT
    handled here — the blob's inline text is already covered by the caller's
    direct long-tool scan of the same blob."""
    m = _SHELL_SCRIPT_RUNNER_RE.search(blob)
    if m:
        return (f"opaque shell-runner 'bash {m.group('script')}' inside "
                f"_docker_exec — the script's contents escape the long-tool "
                f"scan; supervise it (marker=) or annotate")
    return None


# ── annotation lookup ──────────────────────────────────────────────────────
def _has_tag(line: str) -> bool:
    if EXEMPT_TAG not in line:
        return False
    return bool(line.split(EXEMPT_TAG, 1)[1].strip())   # non-empty reason


def _annotated(lines: List[str], node: ast.AST) -> bool:
    """A non-empty `# watchdog-exempt: <reason>` anywhere on the statement's
    own source span OR in the contiguous comment/blank block immediately above
    it (so a multi-line rationale block counts)."""
    hi = getattr(node, "end_lineno", node.lineno) or node.lineno
    # own span
    for i in range(node.lineno, hi + 1):
        if 1 <= i <= len(lines) and _has_tag(lines[i - 1]):
            return True
    # contiguous preceding comment/blank block
    i = node.lineno - 1
    while i >= 1:
        stripped = lines[i - 1].strip()
        if stripped == "" or stripped.startswith("#"):
            if _has_tag(lines[i - 1]):
                return True
            i -= 1
            continue
        break
    return False


# ── loop-body risk probes ──────────────────────────────────────────────────
def _iter_direct_calls(loop: ast.AST):
    """Yield Call nodes in the loop body, NOT descending into nested loops'
    deeper functions (walk is fine here — nested funcs are rare in these loops
    and a launch anywhere in the body is still a launch in the loop)."""
    for stmt in loop.body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call):
                yield n


def _loop_body_signals(loop: ast.AST) -> Tuple[bool, bool]:
    """(launches_subprocess, sleeps) for a loop body."""
    subp = sleep = False
    for c in _iter_direct_calls(loop):
        if _launches_subprocess(c):
            subp = True
        elif _is_sleep(c):
            sleep = True
    return subp, sleep


def _for_iter_is_infinite(node: ast.For) -> bool:
    it = node.iter
    if isinstance(it, ast.Call):
        f = it.func
        name = f.id if isinstance(f, ast.Name) else (
            f.attr if isinstance(f, ast.Attribute) else None)
        if name in INFINITE_ITERS:
            return True
        # two-arg iter(callable, sentinel) is unbounded in principle
        if name == "iter" and len(it.args) == 2:
            return True
    return False


# ── the file scanner ───────────────────────────────────────────────────────
def scan_file(path: Path) -> List[Offense]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [Offense(path.name, exc.lineno or 0, "parse",
                        f"SyntaxError: {exc.msg}")]

    module_consts = _collect_str_consts(tree.body)

    # Enclosing-function index for cmd tracing + loop_guard var maps.
    funcs: List[Tuple[int, int, ast.AST]] = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((n.lineno, n.end_lineno or n.lineno, n))

    def enclosing(lineno: int):
        best = None
        for s, e, fn in funcs:
            if s <= lineno <= e and (best is None or s > best[0]):
                best = (s, e, fn)
        return best[2] if best else None

    # memoize per-function maps
    _cmdtext_cache: Dict[int, Dict[str, List[Tuple[int, str]]]] = {}
    _lg_cache: Dict[int, set] = {}
    _consts_cache: Dict[int, Dict[str, str]] = {}
    _listvars_cache: Dict[int, Dict[str, List[Tuple[int, ast.AST]]]] = {}

    def cmd_text_for(fn) -> Dict[str, str]:
        if fn is None:
            return {}
        if id(fn) not in _cmdtext_cache:
            _cmdtext_cache[id(fn)] = _collect_cmd_text(fn)
        return _cmdtext_cache[id(fn)]

    def loopguard_vars_for(fn) -> set:
        if fn is None:
            return set()
        if id(fn) not in _lg_cache:
            _lg_cache[id(fn)] = _collect_loopguard_vars(fn)
        return _lg_cache[id(fn)]

    def consts_for(fn) -> Dict[str, str]:
        if fn is None:
            return module_consts
        if id(fn) not in _consts_cache:
            merged = dict(module_consts)
            merged.update(_collect_str_consts(list(ast.walk(fn))))
            _consts_cache[id(fn)] = merged
        return _consts_cache[id(fn)]

    def list_vars_for(fn):
        if fn is None:
            return {}
        if id(fn) not in _listvars_cache:
            _listvars_cache[id(fn)] = _collect_list_vars(fn)
        return _listvars_cache[id(fn)]

    offenses: List[Offense] = []

    for node in ast.walk(tree):
        # ── class (a): sub-process launches ──────────────────────────────
        if isinstance(node, ast.Call):
            if _is_subprocess_launcher(node):
                fn = enclosing(node.lineno)
                names = consts_for(fn)
                a0 = _argv0_basename(node, names, list_vars_for(fn))
                if a0 and a0 in LONG_TOOLS and a0 not in BENIGN_ARGV0:
                    if not _annotated(lines, node):
                        offenses.append(Offense(
                            path.name, node.lineno, "subprocess",
                            f"direct host launch of long tool '{a0}' not under "
                            f"run_supervised (subprocess.*)"))
                elif a0 in SHELL_RUNNERS:
                    # class (c): opaque `bash <script>` runner / long-tool -c.
                    detail = _shell_runner_offense(
                        node, names, list_vars_for(fn))
                    if detail and not _annotated(lines, node):
                        offenses.append(Offense(
                            path.name, node.lineno, "shell_runner", detail))
            elif _is_docker_exec(node):
                if not _has_marker(node):
                    fn = enclosing(node.lineno)
                    ctext = cmd_text_for(fn)
                    # cmd is arg[1] positional or cmd= kwarg
                    cmdarg = (node.args[1] if len(node.args) >= 2 else None)
                    if cmdarg is None:
                        for k in node.keywords:
                            if k.arg == "cmd":
                                cmdarg = k.value
                    blob = ""
                    if isinstance(cmdarg, ast.Name):
                        blob = _cmd_text_before(ctext, cmdarg.id, node.lineno)
                    elif cmdarg is not None:
                        blob = " ".join(_str_literal_parts(cmdarg))
                    blob = _PRESENCE_PROBE_RE.sub(" ", blob)
                    m = _CMD_TOOL_RE.search(blob)
                    if m and not _annotated(lines, node):
                        offenses.append(Offense(
                            path.name, node.lineno, "docker_exec",
                            f"_docker_exec of long tool '{m.group(1)}' without "
                            f"marker= (not routed through the watchdog)"))
                    elif not m:
                        # class (c): a `bash <script>.sh` runner whose long tool
                        # is HIDDEN inside the script escapes the blob scan.
                        sr = _blob_shell_runner_offense(blob)
                        if sr and not _annotated(lines, node):
                            offenses.append(Offense(
                                path.name, node.lineno, "shell_runner", sr))

        # ── class (b): loops ─────────────────────────────────────────────
        elif isinstance(node, ast.While):
            subp, sleep = _loop_body_signals(node)
            if (subp or sleep) and not _annotated(lines, node):
                why = ("launches a sub-process" if subp
                       else "sleeps (poll)")
                offenses.append(Offense(
                    path.name, node.lineno, "while",
                    f"while-loop {why} but is unbounded (not driven by "
                    f"loop_guard; refactor to a bounded loop_guard for-loop "
                    f"or annotate)"))
        elif isinstance(node, ast.For):
            # loop_guard(...) iterable, or a var bound to one → guarded.
            fn = enclosing(node.lineno)
            if _is_loop_guard_call(node.iter):
                continue
            if isinstance(node.iter, ast.Name) and \
                    node.iter.id in loopguard_vars_for(fn):
                continue
            if _for_iter_is_infinite(node):
                subp, sleep = _loop_body_signals(node)
                if (subp or sleep) and not _annotated(lines, node):
                    offenses.append(Offense(
                        path.name, node.lineno, "for",
                        "for-loop over an INFINITE iterator with a "
                        "sub-process/sleep body — drive it with loop_guard"))
            # finite for-loops are bounded by construction → not flagged.

    return offenses


def scan_programs(programs_dir: Path) -> List[Offense]:
    offenses: List[Offense] = []
    for py in sorted(programs_dir.glob("*.py")):
        if py.name in _SKIP_FILES:
            continue
        offenses.extend(scan_file(py))
    return offenses


def _resolve_programs_dir(root: Optional[str],
                          programs_dir: Optional[str]) -> Path:
    if programs_dir:
        return Path(programs_dir).resolve()
    if root:
        r = Path(root).resolve()
        if (r / "programs").is_dir():
            return r / "programs"
        return r
    # default: this program's own directory (the programs dir)
    return Path(__file__).resolve().parent


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Enforce the _watchdog primitive over programs/*.py: no "
                    "unguarded long sub-process, no unbounded risky loop.")
    ap.add_argument("root", nargs="?", default=None,
                    help="plugin root (scans ROOT/programs if present)")
    ap.add_argument("--programs-dir", default=None,
                    help="explicit programs directory to scan")
    ap.add_argument("--json", default=None, help="write the offender JSON here")
    args = ap.parse_args(argv)

    pdir = _resolve_programs_dir(args.root, args.programs_dir)
    if not pdir.is_dir():
        print(f"ERROR: programs dir not found: {pdir}", file=sys.stderr)
        return 2

    offenses = scan_programs(pdir)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(
            [o.__dict__ for o in offenses], indent=2) + "\n")

    if not offenses:
        n = len(list(pdir.glob("*.py")))
        # vibe-ic#564 — "0 file(s) scanned" and PASS is a verdict about a
        # population that was never read. rc 2 is the disclosed-skip
        # convention; the P0 umbrella reads the code, not the sentence.
        if n == 0:
            print(f"VACUOUS_PASS: loop_watchdog_compliance_check scanned 0 "
                  f"file(s) under {pdir} — nothing was examined, which is not "
                  f"a clean result", file=sys.stderr)
            return 2
        print(f"loop_watchdog_compliance_check: PASS — {n} file(s) scanned, "
              f"no unguarded long sub-process or unbounded risky loop.")
        return 0

    print(f"loop_watchdog_compliance_check: FAIL — {len(offenses)} offender(s):",
          file=sys.stderr)
    for o in offenses:
        print(f"  {o.file}:{o.line}  [{o.kind}]  {o.detail}", file=sys.stderr)
    print("\nFix each: route the sub-process through _watchdog.run_supervised "
          "(or _docker_exec(..., marker=...)); drive the loop with "
          "_watchdog.loop_guard(...); or add an inline "
          "'# watchdog-exempt: <reason>' if it is genuinely bounded/short.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
