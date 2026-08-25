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

A NAME IS NOT A CALL, AND THIS GATE LEARNED IT TWICE.

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

#: Where a reference means the gate can be REACHED without a human choosing to.
#: `skills/` is deliberately NOT here — see the module docstring.
_EXECUTABLE_GLOBS = (
    "flow/*.yaml", "flow/*.yml",
    "benchmark/*.json",
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
    """{gate: {"executable": [...], "skill": [...]}} — where each is named."""
    g = gates(plugin)
    execs = _texts(plugin, repo, _EXECUTABLE_GLOBS, _REPO_GLOBS)
    skills = _texts(plugin, repo, _SKILL_GLOBS)
    out = {name: {"executable": [], "skill": []} for name in g}
    for f, t in execs:
        # THIS program names its subjects — six of them, in the docstring above.
        # Counting that as wiring made all six read as consulted, which is the
        # exact defect this gate exists to find, committed by the gate itself.
        # An auditor naming what it audits is not a caller.
        if f.stem == Path(__file__).stem:
            continue
        for name in g:
            # A gate's OWN file does not wire it, and neither does its own test.
            if f.stem == name or f.stem == f"test_{name}":
                continue
            if name in t:
                out[name]["executable"].append(str(f))
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
        prev = _load_baseline(bpath) or []
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
        if prev and a.record_shrink and not left:
            print(f"nothing to record: {bpath} already holds the tightened set "
                  f"({len(prev)} unwired)")
            return 0
        doc = {
            "_comment": "Gates no automatic verdict consults (vibe-ic#693). "
                        "MAY ONLY SHRINK. A gate here produces no verdict, and "
                        "the tree looks the same either way. `skill_only` is "
                        "recorded because a skill mention runs the gate only "
                        "if an agent remembers to — which for a gate that "
                        "catches a vacuous pass is the same as absent at the "
                        "moment it matters.",
            "unwired": record,
            "skill_only": sorted(n for n in record if w.get(n, {}).get("skill")),
        }
        try:
            # The subset property is re-established on the DOCUMENT, so a
            # future edit that builds `unwired` from something other than the
            # two expressions above is refused here rather than trusted.
            _ratchet.write_shrunk(bpath, doc,
                                  previous_by_register={"unwired": prev}
                                  if prev else {})
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
    print(f"  gates: {len(gates(plugin))}   unwired: {len(now)} "
          f"(baseline {len(base)})   of those named in a skill: {len(skill_only)}")
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
              "looks the same\n  either way. Wire it into the flow yaml, "
              "CAPTURE_ROUTING, a runner, or\n  tools/ci — a skill mention runs "
              "it only if an agent remembers to.")
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
