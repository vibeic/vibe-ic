#!/usr/bin/env python3
"""A gate no automatic verdict consults. vibe-ic#693.

THIS GATE BLOCKS (rc=1) on a NEW unwired gate.

WHY IT EXISTS
-------------
A gate's entire purpose is to produce a verdict. One that nothing invokes
produces none, and the tree looks exactly the same either way.

MEASURED over `programs/`: 559 gates (`*_check`, `*_lint`, `*_audit`,
`*_guard`), of which 73 are reachable from NO executable location — not the
flow yaml, not CAPTURE_ROUTING.json, not another program, not `hooks/`, not
`tools/ci/`. Among them:

    silent_decline_audit                  a step that declines without saying so
    step_internal_fail_bubble_up_check    an internal failure that never reaches
                                          the step verdict
    lvs_signoff_guard                     an LVS pass that should not have issued
    pnr_timing_repair_completeness_check  a repair recorded as applied but
                                          incomplete

Every one of those is the gate that would have caught a defect found by hand.
`drc_vacuous_pass_check` — a sign-off DRC certificate issued over an empty
layout, the strongest form of this defect — was a fifth, and is now run per
published cell from `tools/ci/repo_hygiene_gates.sh`.

A NAME IS NOT A CALL — AND THE THIRD TIME, THE RULE ITSELF WAS THE HOLE
-----------------------------------------------------------------------
vibe-ic#2065 shipped `counter_decode_lookahead_phase_check` with its own tests
and NO caller. This gate said so, once. Then the gate was WIRED — and the
measurement that followed is the reason this file now reads INVOCATIONS:

    delete BOTH invocations (the runner import, the router import), leave the
    flow Step-2 `programs:` entry and the CAPTURE_ROUTING row exactly as they
    are  ->  under the old rule:  unwired 26 (baseline 26)  [PASS]  rc 0

A register that credits a NAME cannot see an unwired gate, which is the one
thing it exists to see. Its own "A NAME IS NOT A CALL" argument below was true
and too narrow: it covered COMMENTS and DOCSTRINGS, and a `programs:` list
entry, a routing-table row and a sentence of advice inside a string are all
none of those.

RULED (owner, 2026-09-07): wired-ness is derived from an INVOCATION — a call
site reachable from a runner step — never from a declaration alone. That is
`_RULE_ID = "invocation.v1"`, and it is what `py_invocations`,
`flow_invocations` and `shell_invocations` each define for their own file kind:

    python   an import that is then REFERENCED, or the entry named as a whole
             string literal in a file that can spawn (a filename anywhere; a
             bare stem only inside a name table, an argument or a composed path)
    flow     a GATE CLAUSE whose command names it as the entry. NOT `programs:`.
    shell    an argv `"$PG/foo_check.py"`, or a bare stem in a dispatch array
    json/md  nothing. A routing table and a page execute nothing at all.

MEASURED over the shipped tree, 655 gates: 26 unwired under the name rule, 36
under this one, and the set is a strict SUPERSET — no gate the old rule accused
is credited by the new one. Every one of the ten made visible was credited
only by a declaration or by prose inside a string; each was read by hand, and
they are named in the register. Four shapes had to be got right before the
number was honest, and each was found by a false accusation the probe made
first: parsing the comment-stripped copy instead of the source (21 gates), the
flow's clause grammar carrying its command as the clause VALUE (47), a checker
handed to a driver rather than called (`cvdp_gate`), and a bash dispatch array
of bare stems (`run_plugin_self_audit.sh`).

A NAME IS NOT A CALL, AND THIS GATE LEARNED IT TWICE BEFORE THAT.

  1. Its own docstring names its subjects, and counting that as wiring made all
     of them read as consulted: 34 instead of 38.
  2. Patched for THIS FILE ONLY, which fixed the instance and left the rule.
     vibe-ic#702 then repaired `handoff_bundle_check` and deliberately left it
     off a rail, and this gate reported it newly WIRED — on one line of another
     program: `#: reproduced end-to-end through handoff_bundle_check, ...`,
     a comment. The baseline would have shrunk by one over a gate that still
     runs nowhere.

`executable_text()` is the rule: comments and docstrings are removed before
anything is searched, in `.py`, `.yaml` and shell alike. Applying it moved the
count from 29 to 73 — 44 gates had been held up by a comment somewhere. The
tree did not get worse; the measurement stopped being generous. Every gate the
tree really does invoke still reads as wired, verified by name.

WHY THE EXISTING RATCHET DID NOT SEE THEM. `gate_skip_routing_check` tracks
gates whose SKIP path does not reach a verdict, and reports `98 unrouted skip
path(s) in 53 gate(s); published inventory holds 98 in 53` — balanced. Its
population is 53 gates and NONE of the six above is in it. Its scope is its
coverage, and it reports balanced for what it never looked at. That is not a bug
in the ratchet: it answers a different question, correctly. Nothing was asking
THIS one.

WHAT "UNWIRED" MEANS HERE, PRECISELY
------------------------------------
Not "cannot execute". `drc_vacuous_pass_check` is named in
`skills/benchmark-verify/SKILL.md`, so it runs IF an agent reads that skill and
chooses to run it. By this repo's own program-first doctrine that is a
skill-prose lesson a fresh author might forget, and for a gate whose job is to
catch a vacuous pass, depending on an agent's memory is the same as absent at
the moment it matters. A skill mention is therefore recorded — and does NOT
count as wired.

Documentation mentions are excluded entirely: a gate named only in a `.md` is
not thereby run by anything.

THE CORPUS IS HALF THE ANSWER, AND IT USED TO BE UNSAID (vibe-ic#1467)
----------------------------------------------------------------------
Four of the wiring globs are anchored on the REPO root, not the plugin —
`tools/ci/*`, `tools/*.py`, `tools/*.sh`, `.github/workflows/*` — and for
several gates `tools/ci/repo_hygiene_gates.sh` is the ONLY caller there is.
So this gate's verdict is a function of a corpus it never named, and when that
corpus came back empty it did not say so: it printed the same confident
sentence it prints for a real finding, with names under it.

MEASURED, this repo's own bytes, `programs/` and `tools/` HARDLINKED so both
arms are the same files, one `.git` dropped at the `vibe-ic-marketplace/`
level as the only difference:

    without it   wiring sources: 1147 + 66   unwired 59 (baseline 60)  [PASS]
    with it      wiring sources: 1147 + 0    unwired 110   [FAIL] 50 gate(s)

Fifty accusations, every one of them false, over an unchanged tree — because
the old root walk tested `.git` BEFORE `tools/ci` and stopped at the first
ancestor holding either. `container_login_banner_parse_check` is in that list
of fifty, and it is one of the three names vibe-ic#1467 could not account for.

Two repairs, and the second is the one that matters:

  * `repo_root()` looks for `tools/ci/` and treats `.git` only as a fallback,
    so an intermediate checkout cannot capture the root;
  * an EMPTY repo-root corpus is `[CANNOT DETERMINE]` (rc 2), never a FAIL
    with names. An empty result is not a zero: a corpus that could not be read
    has not told this gate that nothing wires those gates, it has told it that
    it could not look. And every run now PRINTS both source counts, so two
    runs that disagree can be compared without access to each other's host —
    which vibe-ic#1467 needed and did not have, across three machines at one
    commit.

rc 2 still BLOCKS: `repo_hygiene_gates.sh` dispatches this gate with plain
`run`, where only `run_tolerating_uncheckable` forgives rc 2. Nothing here is
a way to make the gate quieter.

BASELINE, AND WHY IT MAY ONLY SHRINK
------------------------------------
73 gates are unwired today. Failing the tree on all of them would make this gate
un-landable and it would be turned off, which is how a gate ends up reporting
FAIL while blocking nothing. The known set is a baseline that may only shrink;
anything NEW fails from the first run.

A SHRINK IS A PASS, AND THE GATE SAYS SO WITHOUT NAMING A LAUNDERING FLAG
-------------------------------------------------------------------------
Wiring a recorded gate makes the baseline TOO BIG, which is the tightening
direction, and this gate used to answer it with

    [NOTE] baseline shrank — now wired: <name>. Re-run with --write-baseline.

That sentence is the defect. `--write-baseline` records whatever THIS run
measured — the departures and the arrivals together — so on a day when a gate
is wired and another is added unwired, the flag the operator was just told to
run removes the paid debt and records the new offender as accepted debt. And
the guard that was supposed to stop that was

    if prev and len(now) > len(prev): refuse

a COUNT, not a membership test, so a one-out-one-in swap wrote cleanly at
constant size. `flow_gate_enforcement_audit` removed this exact hole from
itself under vibe-ic#900 ("RATCHET ON MEMBERSHIP, NOT ON COUNT"); this gate
still carried it. It is a membership test now, and a shrink is recorded by
`--record-shrink`, which writes `previous & current` and CANNOT add — see
`_ratchet_baseline`.

The verdict path never writes: `tools/ci/repo_hygiene_gates.sh` runs inside the
whole-repo `suite_write_guard` bracket at `tools/gatekeeper-land.sh:690`, which
blocks on any tracked write, so a gate that rewrote its own register while
producing a verdict would refuse the landing that carried the fix.

chip-AGNOSTIC: pure filesystem and reference structure.

USAGE
-----
    gate_is_wired_check.py [--root .] [--json OUT]
                           [--record-shrink | --write-baseline]

    exit 0 = no NEW unwired gate, and the baseline has not grown
    exit 1 = a new one, or the baseline grew / went stale (BLOCKING)
    exit 2 = could not be determined — no programs/, no gate at all, no
             readable baseline, or an EMPTY repo-root wiring corpus. Never a
             vacuous pass, and never a confident FAIL over a failed look.

Every run prints the size of both corpora it read, plugin and repo root, so
that two runs which disagree can be compared from their output alone.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet_baseline as _ratchet  # noqa: E402

#: vibe-ic#1130 — `_gate` IS in this set, and its absence was the second
#: route to "a checker nothing runs". `checker_execution_wiring_audit`
#: added `*_gate.py` to its own population in #693, after
#: `gitignore_scratch_guard.py` proved a wired-to-nothing gate could hide
#: behind a filename; THIS regex never got the same widening, so the two
#: instruments that both audit wiring disagreed about what a gate is.
#: MEASURED on a38902d1: wiring-audit population 585, this one 581, and
#: the difference is exactly the four `*_gate.py` programs —
#: mpw_precheck_result_gate, plugin_change_pytest_gate, rtl_precheck_gate,
#: wake_gen_silence_gate. Strict subset in one direction (0 the other
#: way), so this is a pure widening with a bounded blast radius.
_GATE_RE = re.compile(r"_(check|lint|audit|guard|gate)$")
_BASELINE_NAME = "gate_is_wired_baseline.json"

#: THE RULE ID THIS REGISTER WAS MEASURED UNDER.
#:
#: It is written into the baseline document and compared on every run. It is
#: what makes a POPULATION CHANGE — the instrument starting to measure a
#: different question — distinguishable from a debt that grew, and it is the
#: only condition under which `--write-baseline` may ADD. See `main`.
_RULE_ID = "invocation.v1"

#: Where a reference means the gate can be REACHED without a human choosing to.
#: `skills/` is deliberately NOT here — see the module docstring.
_EXECUTABLE_GLOBS = (
    "flow/*.yaml", "flow/*.yml",
    # `benchmark/*.json` USED TO BE HERE AND IS NOT ANY MORE (vibe-ic#2065
    # ruling). A JSON file executes nothing. `CAPTURE_ROUTING.json` is a
    # routing TABLE an agent reads, and crediting an entry there as a call is
    # precisely the hole this file's INVOCATION section describes: the gate
    # #2065 shipped unwired was named there and read as consulted. MEASURED
    # before dropping it: the only other json in that directory,
    # `BENCHMARK_REGISTRY.json`, names no gate-shaped program at all, so
    # nothing loses its only caller. The `.py` beside them stays — see below.
    # `benchmark/*.py` as well as its json. That directory is not data and it is
    # not test scaffolding — `cvdp_gate.py`, `score_iverilog_tb.py` and
    # `gates_atomic.py` are the live scoring and emit paths, and they import
    # gates. Reading only the json made this gate report
    # `harness_verdict_forgery_gate` as reachable by nothing while
    # `benchmark/score_iverilog_tb.py:153` imports it — a confident accusation
    # from a corpus that could not contain the evidence. The sibling audit
    # `checker_execution_wiring_audit` had the identical hole in its own
    # haystack and is fixed in the same change.
    "benchmark/*.py",
    "hooks/*",
    "programs/*.py",
    "mcp-eda/*.py",
)
#: Same, relative to the REPO root rather than the plugin root.
_REPO_GLOBS = ("tools/ci/*", "tools/*.py", "tools/*.sh", ".github/workflows/*")

#: Recorded, never counted as wired.
_SKILL_GLOBS = ("skills/**/*.md", "agents/**/*.md", "commands/**/*.md")

#: A REGISTER OF RED GATES IS NOT A RUNNER (measured 2026-08-21).
#:
#: `executable_text` below already argues that a COMMENT naming a gate is not a
#: caller, and gives the measured case where believing one would have shrunk the
#: baseline and hidden a gate that runs nowhere. This is the same rule one level
#: out, and it was found the same way — by tripping it.
#:
#: `tools/ci/*` sweeps in `gate_red_since.json`, the acknowledgement ledger,
#: whose ENTIRE PURPOSE is to name gates that are red and say why. Writing the
#: row for this very gate — "closed_loop_edge_check, ppa_pr_scope_check and
#: slot_pad_budget_check are consulted by no automatic verdict" — made all three
#: read as wired: `unwired` fell 61 -> 58 and the gate turned PASS. Isolated to
#: that one file, on an otherwise clean tree at 6dfe15a32.
#:
#: The ledger's own `_doc` promises "there is nothing a row can silence and no
#: green a row can buy". It was exactly wrong, and in the worst direction: the
#: acknowledgement silenced the finding it acknowledged, so the more honestly a
#: row described its red the more certainly it hid it.
#:
#: Named by the constant its owner exports, so a move renames it here too.
_NOT_A_RUNNER = ("tools/ci/gate_red_since.json",)


#: Suffixes that DECLARE rather than execute. A `.json` routing table, a `.md`
#: page and a `.tsv` ledger all name programs; none of them runs one.
_DECLARATION_SUFFIXES = (".json", ".md", ".tsv", ".txt", ".csv")

#: Tokens whose presence means a file can START A PROCESS. A `.py` that names a
#: gate as a bare string constant is a DISPATCH TABLE only if it can also spawn;
#: without one of these the same literal is a data row.
_SPAWN_TOKENS = ("subprocess", "sys.executable", "os.exec", "os.spawn",
                 "runpy", "import_module", "_progress_run", "_pr.run",
                 "check_output", "Popen")


def _entry_stem(token: str) -> str:
    """The program a command token names: basename, `.py` optional."""
    base = token.rsplit("/", 1)[-1]
    return base[:-3] if base.endswith(".py") else base


def py_invocations(text: str, names: Set[str]) -> Dict[str, str]:
    """{gate: how} for the gates THIS python source invokes.

    Parsed from the ORIGINAL source, never from the comment-stripped copy:
    `executable_text` blanks a docstring to empty LINES, which can leave a
    function with an empty body, and the re-parse then raises IndentationError.
    MEASURED while this rule was being written — a probe that stripped first
    reported `phase3_one_shot_runner.py` as invoking NOTHING and would have
    accused 21 gates it demonstrably spawns. `ast` already excludes comments;
    docstrings are excluded by NODE below.

    Two forms, and only two:

    * IMPORTED **AND REFERENCED**. Not "and called": `benchmark/cvdp_gate.py`
      does `from valid_ready_independence_check import check_text as _f` and
      then `_structural_finding_gate(_f, ...)` — the checker is handed to a
      driver that calls it, an invocation with no Call node of its own.
      Requiring a direct call would have accused it. A DEAD import, bound and
      never referenced, is still not an invocation and is still refused.

    * NAMED AS A BARE ENTRY in a file that can spawn. `flow_compliance_check`
      holds 246 gate names as plain string constants and builds
      `PROGRAMS_DIR / f"{name}.py"` from them; that is a real dispatch and the
      literal is the only trace of it. The literal must be the WHOLE string
      (`"foo_check"` or `".../foo_check.py"`), which is what separates a
      dispatch row from advice prose — measured on six gates whose only credit
      under the old rule was a sentence like "matching ir_drop_budget_check".
    """
    out: Dict[str, str] = {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    doc_ids = set()
    for n in ast.walk(tree):
        body = getattr(n, "body", None)
        if isinstance(body, list) and isinstance(
                n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                    ast.ClassDef)):
            first = body[0] if body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                doc_ids.add(id(first.value))
        if (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)):
            doc_ids.add(id(n.value))
    bound: Dict[str, str] = {}
    import_lines = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            import_lines.add(n.lineno)
            for al in n.names:
                if al.name in names:
                    bound.setdefault(al.asname or al.name, al.name)
        elif isinstance(n, ast.ImportFrom):
            import_lines.add(n.lineno)
            if n.module in names:
                for al in n.names:
                    bound.setdefault(al.asname or al.name, n.module)
    for n in ast.walk(tree):
        if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                and n.lineno not in import_lines):
            g = bound.get(n.id)
            if g:
                out.setdefault(g, "imported+referenced")
    if any(tok in text for tok in _SPAWN_TOKENS):
        parent = {}
        for node in ast.walk(tree):
            for kid in ast.iter_child_nodes(node):
                parent[id(kid)] = node
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant)
                    and isinstance(n.value, str)) or id(n) in doc_ids:
                continue
            raw = n.value.strip()
            stem = _entry_stem(raw)
            if stem not in names:
                continue
            if raw.rsplit("/", 1)[-1].endswith(".py"):
                # A FILENAME literal has one use: it names a file to run.
                out.setdefault(stem, "spawned entry literal")
                continue
            # A BARE STEM is credited only where a dispatch puts one: an
            # element of a name TABLE, an argument, or a piece of a path being
            # composed. MEASURED — without this the arm credited
            #     lookahead_extra["gate"] = "counter_decode_lookahead_phase_check"
            # a LABEL in a report row, and a gate whose every invocation had
            # been deleted still read as wired on the strength of it. The
            # 246-entry `_STRUCTURAL_RTL_GATES` tuple in `flow_compliance_check`
            # is the shape this arm exists for and it is a Tuple of Constants,
            # so it is untouched.
            if isinstance(parent.get(id(n)),
                          (ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Call,
                           ast.BinOp, ast.JoinedStr)):
                out.setdefault(stem, "spawned entry literal")
    return out


def _gate_blocks(node):
    """Every `gate:` block in the flow, wherever it sits.

    ONLY `gate:`. The flow also carries `final_gate:` blocks, and its own prose
    records that NOTHING EXECUTES `final_gate` — crediting one would be this
    same defect one level along.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "gate":
                yield v
            else:
                yield from _gate_blocks(v)
    elif isinstance(node, list):
        for v in node:
            yield from _gate_blocks(v)


def _all_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _all_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_strings(v)


def flow_invocations(text: str, names: Set[str]) -> Dict[str, str]:
    """A gate is invoked by the flow when a GATE CLAUSE names it as the ENTRY
    of its command.

    A `programs:` / `mcp_tools:` / `skills:` list entry is a DECLARATION and is
    NOT credited. That is the whole of the vibe-ic#2065 ruling: the gate that
    shipped with no caller was named in a `programs:` list and in
    `CAPTURE_ROUTING.json`, and a register that credits a NAME cannot see an
    unwired gate.

    Schema-agnostic on purpose. Every string inside a `gate:` subtree is read
    and its FIRST token taken as the command entry, rather than hand-listing
    the clause kinds (`program_exit_zero`, `advisory_program_exit_zero`,
    `optional_program_exit_zero`, `program`, a nested `command:`) — a new
    clause kind must not silently stop counting. Prose inside the block
    (`advisory_reason:`) is harmless: its first token is an English word.
    """
    out: Dict[str, str] = {}
    try:
        import yaml                                   # noqa: PLC0415
        doc = yaml.safe_load(text)
    except Exception:                                 # noqa: BLE001
        return out
    for blk in _gate_blocks(doc):
        for sval in _all_strings(blk):
            toks = sval.split()
            if toks and _entry_stem(toks[0]) in names:
                out.setdefault(_entry_stem(toks[0]), "flow gate clause")
    return out


def shell_invocations(text: str, names: Set[str]) -> Dict[str, str]:
    """A shell / unit file in this corpus EXISTS to run things.

    It names its subjects two ways and both are real: `"$PG/foo_check.py"`, and
    a BARE STEM in a dispatch array — `tools/ci/run_plugin_self_audit.sh` holds
    `GATES=( "emitter_failure_mode_check" ... )` and loops it as
    `"$PROGRAMS/$g.py"`. Requiring the `.py` would have accused both of that
    file's gates. Comments are already stripped by `executable_text`.
    """
    out: Dict[str, str] = {}
    for m in re.finditer(r"([A-Za-z0-9_\-./$]*[a-z0-9_]+)\.py\b", text):
        stem = m.group(1).rsplit("/", 1)[-1]
        if stem in names:
            out[stem] = "shell argv"
    for m in re.finditer(r"[A-Za-z0-9_]+", text):
        if m.group(0) in names:
            out.setdefault(m.group(0), "shell dispatch")
    return out


def gates(plugin: Path) -> Set[str]:
    return {p.stem for p in (plugin / "programs").glob("*.py")
            if p.name != "__init__.py" and _GATE_RE.search(p.stem)}


def executable_text(path: Path, text: str) -> str:
    """`text` with everything that CANNOT invoke anything removed.

    A comment naming a gate is not a caller. MEASURED: vibe-ic#702 repaired
    `handoff_bundle_check` and deliberately left it OFF a rail, and this gate
    reported it newly wired — on the strength of one line in another program,

        #: reproduced end-to-end through `handoff_bundle_check`, where the …

    which is a comment. Believing it would have quietly shrunk the baseline by
    one and hidden a gate that still runs nowhere. Same shape as counting this
    program's own docstring; that was patched for this file alone, which fixed
    the instance and not the rule.

    A STRING is kept: `subprocess.run(["python3", "foo_check.py"])` is a real
    call and the name only ever appears there as a literal. A DOCSTRING is
    dropped — it is a string in expression position, executed for no effect.
    """
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return text
        drop: List[Tuple[int, int]] = []
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list) or not isinstance(
                    node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                           ast.ClassDef)):
                continue
            first = body[0] if body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                drop.append((first.lineno, first.end_lineno or first.lineno))
        lines = text.splitlines()
        for lo, hi in drop:
            for i in range(lo - 1, min(hi, len(lines))):
                lines[i] = ""
        try:                                     # then the comments
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    r, c = tok.start
                    if r - 1 < len(lines) and lines[r - 1]:
                        lines[r - 1] = lines[r - 1][:c]
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
        return "\n".join(lines)
    if path.suffix in (".yaml", ".yml", ".sh") or path.suffix == "":
        # `#` starts a comment at line start or after whitespace; a `#` inside
        # a quoted scalar does not. Conservative: keep the line whole when the
        # `#` sits inside a quote that opened earlier on the same line.
        out = []
        for ln in text.splitlines():
            m = re.search(r'(?:^|\s)#', ln)
            if m and ln[:m.start()].count('"') % 2 == 0 \
                  and ln[:m.start()].count("'") % 2 == 0:
                ln = ln[:m.start()]
            out.append(ln)
        return "\n".join(out)
    return text


def _texts(plugin: Path, repo: Path, globs, repo_globs=()) -> List[Tuple[Path, str]]:
    out = []
    excluded = {(repo / rel).resolve() for rel in _NOT_A_RUNNER}
    for base, pats in ((plugin, globs), (repo, repo_globs)):
        for pat in pats:
            for f in base.glob(pat):
                if not f.is_file():
                    continue
                if f.resolve() in excluded:
                    continue
                try:
                    out.append((f, executable_text(f, f.read_text(errors="replace"))))
                except OSError:
                    continue
    return out


def repo_root(plugin: Path) -> Optional[Path]:
    """The ancestor that carries the WIRING CORPUS, or None if there is none.

    `tools/ci/` is the marker, and `.git` is only a fallback — that ORDER is
    the fix for vibe-ic#1467 and it is not cosmetic. The walk used to read

        if (repo / ".git").exists() or (repo / "tools" / "ci").is_dir():

    which stops at the FIRST ancestor holding a `.git`, whether or not that
    ancestor carries any `tools/` at all. MEASURED, on this repo's own bytes
    with `programs/` and `tools/` hardlinked so the two arms are the same
    files: dropping a single `.git` at the `vibe-ic-marketplace/` level moves

        unwired: 59 (baseline 60)  [PASS]   ->   unwired: 110  [FAIL] 50 gates

    because the walk then anchors on the marketplace directory, `tools/ci/*`,
    `tools/*.py` and `.github/workflows/*` match nothing, and every gate wired
    only from the repo root reads as unwired. Fifty confident accusations from
    one marker file, over an unchanged tree.

    Returning None rather than "six levels up, whatever that is" is the other
    half: the caller must be able to tell an EMPTY corpus from a read one, and
    `plugin.parents[5]` is a directory that exists and globs to nothing, which
    is the shape that reads as an answer.
    """
    dot_git: Optional[Path] = None
    cur = plugin
    for _ in range(6):
        if (cur / "tools" / "ci").is_dir():
            return cur
        if dot_git is None and (cur / ".git").exists():
            dot_git = cur
        if cur == cur.parent:                    # reached the filesystem root
            break
        cur = cur.parent
    return dot_git


def wiring_sources(plugin: Path, repo: Path) -> Tuple[int, int]:
    """(wiring sources under the PLUGIN, wiring sources under the REPO root).

    The denominator this gate never disclosed. Its whole verdict is a function
    of these two numbers and nothing in the output said what they were, which
    is why vibe-ic#1467 collected contradictory red lists from three hosts at
    one commit and could not settle which corpus each run had read.
    """
    def _count(base: Path, pats) -> int:
        # Globbed and counted, NOT read: `_texts` parses and strips every file
        # it touches, and calling it a second time here doubled this gate's
        # wall clock (24.1s vs 13.8s, measured on the shipped tree). The
        # question this answers is how many files the corpus HAS, and that is
        # a directory walk.
        return sum(1 for pat in pats for f in base.glob(pat) if f.is_file())

    return (_count(plugin, _EXECUTABLE_GLOBS), _count(repo, _REPO_GLOBS))


def wiring(plugin: Path, repo: Path) -> Dict[str, Dict[str, List[str]]]:
    """{gate: {"executable": [...], "skill": [...]}} — where each is INVOKED.

    `executable` holds `<path>::<how>` for every INVOCATION found, and an
    invocation is what `py_invocations`, `flow_invocations` and
    `shell_invocations` each define for their own file kind. A DECLARATION —
    a `programs:` list entry, a routing-table row, a `.md` page — is not one,
    and files whose whole format is declaration are not read at all.
    """
    g = gates(plugin)
    execs = _texts(plugin, repo, _EXECUTABLE_GLOBS, _REPO_GLOBS)
    skills = _texts(plugin, repo, _SKILL_GLOBS)
    out: Dict[str, Dict[str, List[str]]] = {
        name: {"executable": [], "skill": []} for name in g}
    self_stem = Path(__file__).stem
    for f, t in execs:
        # THIS program names its subjects — six of them, in the docstring above.
        # Counting that as wiring made all six read as consulted, which is the
        # exact defect this gate exists to find, committed by the gate itself.
        # An auditor naming what it audits is not a caller.
        if f.stem == self_stem:
            continue
        if f.suffix in _DECLARATION_SUFFIXES:
            continue
        # A gate's OWN file does not wire it, and neither does its own test.
        names = {n for n in g if f.stem != n and f.stem != f"test_{n}"}
        if not names:
            continue
        if f.suffix == ".py":
            # The ORIGINAL bytes, not `t`: see `py_invocations`.
            try:
                found = py_invocations(f.read_text(errors="replace"), names)
            except OSError:
                continue
        elif f.suffix in (".yaml", ".yml"):
            found = flow_invocations(t, names)
        else:
            found = shell_invocations(t, names)
        for name, how in found.items():
            out[name]["executable"].append(f"{f}::{how}")
    for f, t in skills:
        for name in g:
            if name in t:
                out[name]["skill"].append(str(f))
    return out


def unwired(plugin: Path, repo: Path) -> Tuple[List[str], Dict[str, Dict]]:
    w = wiring(plugin, repo)
    return sorted(n for n, v in w.items() if not v["executable"]), w


def _load_baseline(p: Path) -> Optional[List[str]]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = d.get("unwired") if isinstance(d, dict) else d
    return sorted(v) if isinstance(v, list) else None


def _baseline_rule(p: Path) -> Optional[str]:
    """The rule id the register on disk was MEASURED under, or None.

    A register measured under a different rule is answering a different
    question, and comparing the two as debt is a category error — the set can
    legitimately grow without any gate having become unwired. This is the ONLY
    condition under which `--write-baseline` may add; see `main`.
    """
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d.get("measured_under") if isinstance(d, dict) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="plugin root (default: this program's parent's parent)")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the CURRENT set. Refused if that would ADD "
                         "any entry — a debt register is not a waiver list")
    ap.add_argument(_ratchet.RECORD_FLAG, dest="record_shrink",
                    action="store_true",
                    help="record a measured TIGHTENING: write `previous & "
                         "current`, which can only remove entries. This is "
                         "the path the gate names when it reports a shrink")
    a = ap.parse_args(argv)

    plugin = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[1]
    root = repo_root(plugin)
    repo = root if root is not None else plugin

    if not (plugin / "programs").is_dir():
        print(f"[CANNOT DETERMINE] gate_is_wired: no programs/ under {plugin}. "
              f"NOT a pass.", file=sys.stderr)
        return 2

    now, w = unwired(plugin, repo)
    if not gates(plugin):
        print("[CANNOT DETERMINE] gate_is_wired: no gate found at all. NOT a "
              "pass.", file=sys.stderr)
        return 2

    # THE DENOMINATOR, SAID OUT LOUD (vibe-ic#1467). Half of `_EXECUTABLE_GLOBS`
    # is anchored on the REPO root, and `tools/ci/repo_hygiene_gates.sh` alone
    # is the only wiring several gates have. Read zero files from there and the
    # verdict is not "these gates are unwired", it is "I could not look" — and
    # until now the two printed the same sentence, with names under it.
    n_plugin, n_repo = wiring_sources(plugin, repo)
    print(f"  wiring sources: {n_plugin} under {plugin}"
          + (f" + {n_repo} under {repo}" if root is not None
             else "  + NO REPO ROOT FOUND"))
    if n_repo == 0:
        # Flushed so the disclosure above cannot land AFTER the refusal when
        # the two streams are merged into one terminal.
        sys.stdout.flush()
        print(f"[CANNOT DETERMINE] gate_is_wired: the repo-root wiring corpus "
              f"is EMPTY — `{'`, `'.join(_REPO_GLOBS)}` matched no file "
              + (f"under {repo}." if root is not None else
                 f"because no ancestor of {plugin} within 6 levels carries "
                 f"`tools/ci/`.")
              + f" {len(now)} gate(s) read as unwired against that corpus, and "
                f"every gate whose only caller lives at the repo root is among "
                f"them by construction. A failed look is not a finding. NOT a "
                f"pass.", file=sys.stderr)
        return 2

    bpath = Path(a.baseline) if a.baseline else plugin / "programs" / _BASELINE_NAME
    if a.write_baseline or a.record_shrink:
        # `have_prev` is "a register EXISTS and parsed", not "it holds names".
        # An EMPTY register used to take the same branch as a missing one and
        # skipped the subset check entirely, so emptying the file was a second
        # door onto the write path. `None` — no readable register at all — is
        # the only bootstrap.
        _prev_read = _load_baseline(bpath)
        have_prev = _prev_read is not None
        prev = _prev_read or []
        # THE RECORDED SET, BY THE TWO PATHS THAT MAY PRODUCE IT.
        #
        # `--record-shrink` writes `previous & current`, which is a subset of
        # `previous` whatever this run measured, so a gate that became unwired
        # today cannot enter the register through it. `--write-baseline` writes
        # what this run measured and is refused below if that ADDS anything —
        # a membership test, not the count test this gate used to carry, which
        # a one-out-one-in swap passed at constant size.
        record = _ratchet.shrunk(prev, now) if a.record_shrink else now
        left = _ratchet.departed(prev, record)
        if have_prev and a.record_shrink and not left:
            print(f"nothing to record: {bpath} already holds the tightened set "
                  f"({len(prev)} unwired)")
            return 0
        doc = {
            "_comment": "Gates no automatic verdict INVOKES (vibe-ic#693, rule "
                        "re-derived under vibe-ic#2065). MAY ONLY SHRINK. A "
                        "gate here produces no verdict, and the tree looks the "
                        "same either way. `skill_only` is recorded because a "
                        "skill mention runs the gate only if an agent remembers "
                        "to — which for a gate that catches a vacuous pass is "
                        "the same as absent at the moment it matters.",
            "measured_under": _RULE_ID,
            "unwired": record,
            "skill_only": sorted(n for n in record if w.get(n, {}).get("skill")),
        }
        # A POPULATION CHANGE IS NOT A DEBT THAT GREW, AND IT IS THE ONE
        # CONDITION UNDER WHICH THIS MAY ADD.
        #
        # When the rule itself changes, the register on disk answers a
        # different question: gates it never counted become visible without any
        # gate having become unwired. Refusing the write would leave the
        # instrument permanently red and un-landable, which is how a gate ends
        # up turned off; allowing it unconditionally would restore the
        # laundering flag this file spent vibe-ic#900 removing.
        #
        # So the write is allowed to ADD exactly when the recorded
        # `measured_under` differs from the rule this build measures — and the
        # additions are PRINTED BY NAME, never summarised as a count. The
        # moment the stamp matches, the ratchet is back and adding is refused
        # again. Re-running this flag a second time therefore cannot launder
        # anything: the second run compares like with like.
        prev_rule = _baseline_rule(bpath)
        # PRESENT **AND DIFFERENT**, never merely absent. An absent stamp is
        # how a register would be laundered under this door: delete one line
        # and every new offender records itself as accepted debt. MEASURED —
        # the first version of this branch allowed it, and
        # `test_the_shipped_register_still_refuses_to_GROW` (whose synthetic
        # register carries no stamp, as any hand-written one would not) went
        # from refusing to writing. The shipped register carries the stamp from
        # this change onward, so a future rule change migrates by BUMPING
        # `_RULE_ID` — present and different — and nothing else opens the door.
        rederive = (have_prev and a.write_baseline
                    and prev_rule is not None and prev_rule != _RULE_ID)
        added = sorted(set(record) - set(prev))
        if rederive and added:
            print(f"[POPULATION CHANGE] the register on disk was measured under "
                  f"{prev_rule} and this build measures "
                  f"{_RULE_ID}. {len(added)} gate(s) become visible that the "
                  f"previous rule could not see — every one of them is a gate "
                  f"NOTHING INVOKES, not a gate that stopped being invoked:")
            for n in added:
                print(f"   + {n}")
        try:
            # The subset property is re-established on the DOCUMENT, so a
            # future edit that builds `unwired` from something other than the
            # two expressions above is refused here rather than trusted.
            _ratchet.write_shrunk(bpath, doc,
                                  previous_by_register={}
                                  if rederive else
                                  ({"unwired": prev} if have_prev else {}))
        except _ratchet.ShrinkRefused as exc:
            print(f"[FAIL] gate_is_wired baseline: {exc}", file=sys.stderr)
            return 1
        if left:
            print(_ratchet.report_line("unwired", left, len(prev), len(record)))
        print(f"wrote {bpath} ({len(record)} unwired)")
        return 0

    base = _load_baseline(bpath)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"unwired": now, "baseline": base,
             "skill_only": sorted(n for n in now if w[n]["skill"])},
            indent=2) + "\n")

    if base is None:
        print(f"[CANNOT DETERMINE] gate_is_wired: no readable baseline at "
              f"{bpath}. {len(now)} gate(s) are unwired and there is nothing to "
              f"compare against. NOT a pass.", file=sys.stderr)
        return 2

    new = sorted(set(now) - set(base))
    gone = sorted(set(base) - set(now))
    skill_only = sorted(n for n in now if w[n]["skill"])
    recorded_rule = _baseline_rule(bpath)
    print(f"  gates: {len(gates(plugin))}   unwired: {len(now)} "
          f"(baseline {len(base)})   of those named in a skill: {len(skill_only)}"
          f"   rule: {_RULE_ID}")
    if recorded_rule != _RULE_ID:
        # SAID OUT LOUD, ALWAYS. A register measured under another rule can be
        # compared to this run's set only as a category error; the reader has to
        # know that before reading the numbers above.
        print(f"  [RULE MISMATCH] the register records measured_under="
              f"{recorded_rule!r}; this build measures {_RULE_ID!r}. The two "
              f"sets answer different questions. Re-derive once with "
              f"--write-baseline, which prints every addition by name.")
    if gone:
        # A TIGHTENING IS NEVER A FAILURE AND NEVER AN ERRAND. It is reported
        # in full — which gates left, and by how much — and the register is
        # brought into line by `--record-shrink`, which can only remove. The
        # sentence that used to stand here named `--write-baseline`, whose
        # other effect on the same run is to record every NEW offender as
        # accepted debt.
        # The sizes are the REGISTER's, before and after this tightening —
        # `len(now)` would fold in any NEW offender and report a shrink of the
        # wrong size on exactly the run where the two land together.
        print(_ratchet.report_line("unwired", gone,
                                   len(base), len(base) - len(gone)))
        print(f"           now wired, so they no longer belong in the register."
              f" Record it with:  gate_is_wired_check.py "
              f"{_ratchet.RECORD_FLAG}")
    if new:
        print(f"\n[FAIL] {len(new)} gate(s) newly consulted by no automatic "
              f"verdict:")
        for n in new:
            where = w[n]["skill"]
            print(f"   {n}"
                  + (f"  (named only in {where[0]})" if where else ""))
        print("\n  A gate nothing invokes produces no verdict, and the tree "
              "looks the same either\n  way. INVOKE it: a flow GATE CLAUSE "
              "whose command names it as the entry, an\n  import that is then "
              "referenced, a spawned argv naming it, or a tools/ci\n  runner. "
              "A `programs:` list entry, a CAPTURE_ROUTING row and a skill\n"
              "  mention are DECLARATIONS — none of them runs anything.")
        return 1
    if len(now) > len(base):
        print(f"\n[FAIL] the unwired set grew {len(base)} -> {len(now)} with no "
              f"new name — the baseline is stale.")
        return 1

    print(f"[PASS] gate_is_wired: no gate newly unwired; the baseline has not "
          f"grown.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
