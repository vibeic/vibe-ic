#!/usr/bin/env python3
"""A gate no automatic verdict consults. vibe-ic#693.

THIS GATE BLOCKS (rc=1) on a NEW unwired gate.

WHY IT EXISTS
-------------
A gate's entire purpose is to produce a verdict. One that nothing invokes
produces none, and the tree looks exactly the same either way.

MEASURED over `programs/`: 558 gates (`*_check`, `*_lint`, `*_audit`,
`*_guard`), of which 38 are referenced from NO executable location — not the
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

A NOTE ON THIS FILE'S OWN NAMES. The paragraph above is why `wiring()` skips
this program when it looks for callers. Counting an auditor's examples as
wiring made all of them read as consulted — 34 unwired instead of 38 — and the
gate committed the exact defect it exists to find. Pinned by
`test_the_auditor_does_not_wire_its_own_subjects`.

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
38 gates are unwired today. Failing the tree on all of them would make this gate
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
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_GATE_RE = re.compile(r"_(check|lint|audit|guard)$")
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


def _texts(plugin: Path, repo: Path, globs, repo_globs=()) -> List[Tuple[Path, str]]:
    out = []
    for base, pats in ((plugin, globs), (repo, repo_globs)):
        for pat in pats:
            for f in base.glob(pat):
                if not f.is_file():
                    continue
                try:
                    out.append((f, f.read_text(errors="replace")))
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
