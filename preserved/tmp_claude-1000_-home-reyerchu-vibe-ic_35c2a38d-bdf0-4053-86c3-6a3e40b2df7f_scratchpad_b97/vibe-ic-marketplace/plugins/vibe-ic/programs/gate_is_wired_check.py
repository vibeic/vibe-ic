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

BASELINE, AND WHY IT MAY ONLY SHRINK
------------------------------------
73 gates are unwired today. Failing the tree on all of them would make this gate
un-landable and it would be turned off, which is how a gate ends up reporting
FAIL while blocking nothing. The known set is a baseline that may only shrink;
anything NEW fails from the first run.

chip-AGNOSTIC: pure filesystem and reference structure.

USAGE
-----
    gate_is_wired_check.py [--root .] [--json OUT] [--write-baseline]

    exit 0 = no NEW unwired gate, and the baseline has not grown
    exit 1 = a new one, or the baseline grew / went stale (BLOCKING)
    exit 2 = could not be determined — never a vacuous pass
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
    "hooks/*",
    "programs/*.py",
    "mcp-eda/*.py",
)
#: Same, relative to the REPO root rather than the plugin root.
_REPO_GLOBS = ("tools/ci/*", "tools/*.py", "tools/*.sh", ".github/workflows/*")

#: Recorded, never counted as wired.
_SKILL_GLOBS = ("skills/**/*.md", "agents/**/*.md", "commands/**/*.md")


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
    for base, pats in ((plugin, globs), (repo, repo_globs)):
        for pat in pats:
            for f in base.glob(pat):
                if not f.is_file():
                    continue
                try:
                    out.append((f, executable_text(f, f.read_text(errors="replace"))))
                except OSError:
                    continue
    return out


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
                    help="record the CURRENT set; it may only shrink, and the "
                         "next run re-checks that")
    a = ap.parse_args(argv)

    plugin = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[1]
    repo = plugin
    for _ in range(6):
        if (repo / ".git").exists() or (repo / "tools" / "ci").is_dir():
            break
        repo = repo.parent

    if not (plugin / "programs").is_dir():
        print(f"[CANNOT DETERMINE] gate_is_wired: no programs/ under {plugin}. "
              f"NOT a pass.", file=sys.stderr)
        return 2

    now, w = unwired(plugin, repo)
    if not gates(plugin):
        print("[CANNOT DETERMINE] gate_is_wired: no gate found at all. NOT a "
              "pass.", file=sys.stderr)
        return 2

    bpath = Path(a.baseline) if a.baseline else plugin / "programs" / _BASELINE_NAME
    if a.write_baseline:
        prev = _load_baseline(bpath) or []
        if prev and len(now) > len(prev):
            print(f"[FAIL] refusing to write a baseline that GREW "
                  f"({len(prev)} -> {len(now)}). It is a debt register, not a "
                  f"waiver list.", file=sys.stderr)
            return 1
        bpath.write_text(json.dumps(
            {"_comment": "Gates no automatic verdict consults (vibe-ic#693). "
                         "MAY ONLY SHRINK. A gate here produces no verdict, and "
                         "the tree looks the same either way. `skill_only` is "
                         "recorded because a skill mention runs the gate only "
                         "if an agent remembers to — which for a gate that "
                         "catches a vacuous pass is the same as absent at the "
                         "moment it matters.",
             "unwired": now,
             "skill_only": sorted(n for n in now if w[n]["skill"])},
            indent=2) + "\n")
        print(f"wrote {bpath} ({len(now)} unwired)")
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
        print(f"  [NOTE] baseline shrank — now wired: {', '.join(gone)}. "
              f"Re-run with --write-baseline.")
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
