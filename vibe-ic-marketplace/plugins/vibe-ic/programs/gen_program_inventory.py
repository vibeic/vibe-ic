#!/usr/bin/env python3
"""gen_program_inventory.py — the single source of truth for every stated count
of this plugin's program corpus, and the gate that stops one drifting again.

WHY THIS EXISTS
===============
Two counts of the same tree lived side by side in this repo and only one of them
stayed true.

  * The MCP tool count is GENERATED (`mcp-eda/tools/gen_mcp_tool_inventory.py`)
    and its artefact says of itself *"Do NOT hand-edit; the website tool count
    must read `total` from here"*. It was still correct when this file was
    written, and its own drift test says so on every run.
  * The program count was HAND-TYPED. `917` was a TRUE measurement of
    `programs/*.py` at `73d1efb20` (2026-07-20) — verified: the tree held
    exactly 917 there, and that commit introduced the number into both
    READMEs. By the time anyone measured again the tree had passed 1,100, and
    `917` was still printed in two README files, eight occurrences.

The difference is not diligence. It is that one number had a generator and a
gate and the other had neither. This file supplies both.

AND A HAND-TYPED COUNT DOES NOT ONLY DRIFT — IT CAN BE BORN WRONG
=================================================================
Two of the other stale numbers never described this tree at all. `1608 test
files` and `888 catalogued` entered the plugin README at `cb8e4c2c0`
(2026-07-30) and appear at no earlier commit on any path. At that commit the
tree held 2,014 `test_*.py` and INDEX.md declared 1,004 — and no other
population of it equals 1608 or 888 either. They were wrong the day they were
typed, and stayed wrong for three weeks, because nothing ever compared a
stated number to the tree. That is the case for gating the STATEMENT and not
merely regenerating the artefact.

THE SECOND HALF OF THE BUG: WHICH TREE IS BEING COUNTED
=======================================================
`917` was wrong. Several OTHER numbers in the tree were right, of different
populations, and every one of them was quotable as "the number of programs":

    programs_py                  the programs themselves
    programs_catalogued          minus helpers and superseded stubs
    checkers_check_py            the narrow checker subset
    checkers_check_audit_lint    the wider checker subset (a "~600 checkers"
                                 claim is about THIS, and is not a correction
                                 of programs_py)
    programs_py_all              programs + tests + sub-packages, recursive
    program_tests                the tests

Any of those may be stated. None may be stated WITHOUT ITS POPULATION, because a
reader who cannot tell which population a number counts cannot tell a drifted
number from a different one — which is how 917 survived 261 additions
unchallenged. So every key below carries a `counts` sentence, that sentence is
emitted into the artefact, and `discover()` refuses a key that has none.

No CURRENT count is written as a literal anywhere in this file, its docstring
included: today's values live in PROGRAM_INVENTORY.json and are read from
there. The figures above are dated measurements of past commits, which is what
a provenance record is for and is the one shape that does not rot.

WHAT `--check` ENFORCES
=======================
1. The committed `PROGRAM_INVENTORY.json` still matches the filesystem.
2. Every REGISTERED STATED SITE — a specific line of a specific doc that quotes
   one of these numbers — still quotes the value the filesystem yields.
3. Every registered site's pattern still MATCHES SOMETHING. A guard whose
   pattern silently stops matching is a guard that has gone blind, and it would
   report PASS forever; a site that matches zero times is a FAILURE here, not a
   skip. Deleting the sentence to silence the gate does not work either — the
   site has to be removed from `STATED_SITES` deliberately.

Exit codes: 0 PASS, 1 FAIL (drift or blind site), 2 NOT CHECKED (the repo root
is not resolvable — e.g. the plugin installed standalone, where the marketplace
README is not on disk). 2 is never a pass; it says the question was not asked.

Usage:
  python3 programs/gen_program_inventory.py            # regenerate + print
  python3 programs/gen_program_inventory.py --check    # verify committed + docs
  python3 programs/gen_program_inventory.py --check --json report.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

PROGRAMS = Path(__file__).resolve().parent
PLUGIN = PROGRAMS.parent
MARKETPLACE = PLUGIN.parent.parent
REPO_ROOT = MARKETPLACE.parent
OUT = PROGRAMS / "PROGRAM_INVENTORY.json"

#: Every count this file is the source of truth for, and — load-bearing — what
#: each one counts. A number without its population is how the drift hid.
DEFINITIONS: Dict[str, str] = {
    "programs_py":
        "`.py` files directly in `plugins/vibe-ic/programs/` (non-recursive). "
        "The programs themselves: tests, sub-packages and helpers under "
        "`programs/tests/`, `programs/gds_antenna/`, `programs/metal_fill/` are "
        "NOT included.",
    "programs_catalogued":
        "Rows in `programs/INDEX.md` — `programs_py` minus private helpers "
        "(`_name.py`), `DEPRECATED_*` / `*_shim.py`, deprecation shims, and any "
        "file that does not parse. Always <= `programs_py`.",
    "programs_py_all":
        "Every `.py` anywhere under `plugins/vibe-ic/programs/`, recursively. "
        "This is `programs_py` + `program_tests_all` + the sub-package modules, "
        "and it is NOT a count of programs — quoting it as one is the ambiguity "
        "this file exists to remove.",
    "program_tests":
        "`test_*.py` under `plugins/vibe-ic/programs/tests/`, recursively. The "
        "pytest node files; helper modules under `tests/` are excluded.",
    "program_tests_all":
        "Every `.py` under `plugins/vibe-ic/programs/tests/`, recursively — "
        "`program_tests` plus the shared helpers and fixtures those tests import.",
    "checkers_check_py":
        "`programs/*_check.py` — the checker subset of `programs_py` under the "
        "narrow `_check.py` naming convention.",
    "checkers_check_audit_lint":
        "`programs/*_check.py` + `*_audit.py` + `*_lint.py` — the wider checker "
        "subset. This is the number a '~600 checkers' claim is about; it is NOT "
        "a correction of `programs_py`, it is a different population.",
    "mcp_eda_tests":
        "`test_*.py` under `plugins/vibe-ic/mcp-eda/test/`.",
    "skills": "`plugins/vibe-ic/skills/*/SKILL.md` — one per shipped skill.",
    "skill_compliance_tests":
        "`test_*.py` under `plugins/vibe-ic/skills/*/tests/` — the per-skill "
        "compliance regressions. Counted separately from `program_tests`; a "
        "bare `pytest` from the plugin root collects `programs/tests/` only.",
}


class Site(NamedTuple):
    """One place in the tree that STATES one of these counts in prose."""
    path: str      # repo-root-relative
    key: str       # which DEFINITIONS key the stated number must equal
    pattern: str   # exactly one capture group: the stated integer
    note: str


#: The registered stated sites. A number quoted anywhere outside this table is
#: ungated and will rot — add the site rather than trusting the prose.
_MKT = "vibe-ic-marketplace/README.md"
_PLG = "vibe-ic-marketplace/plugins/vibe-ic/README.md"

STATED_SITES: List[Site] = [
    Site(_MKT, "programs_py",
         r"\|\s*Deterministic programs\s*\|\s*\*\*([\d,]+)\*\*",
         "marketplace README summary table"),
    Site(_MKT, "program_tests",
         r"\|\s*Test files\s*\|\s*\*\*([\d,]+)\*\*",
         "marketplace README summary table"),
    Site(_MKT, "mcp_eda_tests",
         r"\|\s*Test files\s*\|.*?\+\s*\*\*([\d,]+)\*\*\s*under `plugins/vibe-ic/mcp-eda/test/`",
         "marketplace README summary table, second figure"),
    Site(_MKT, "skills",
         r"\|\s*Skills\s*\|\s*\*\*([\d,]+)\*\*",
         "marketplace README summary table"),
    Site(_MKT, "programs_py",
         r"`phase1/phase2/phase3` runners → ([\d,]+) programs",
         "marketplace README, program-first paragraph"),
    Site(_MKT, "programs_py",
         r"one install gets the skills, the agents, the\n([\d,]+) programs",
         "marketplace README, install section"),
    Site(_MKT, "programs_py",
         r"## Deterministic programs \(([\d,]+)\)",
         "marketplace README, section heading"),
    Site(_MKT, "programs_py",
         r"├── programs/\s+← ([\d,]+) programs",
         "marketplace README, repo tree"),
    Site(_MKT, "program_tests",
         r"│   └── tests/\s+← ([\d,]+) `test_\*\.py`",
         "marketplace README, repo tree"),
    Site(_PLG, "programs_py",
         r"It is \*\*([\d,]+) Python\n?programs\*\*",
         "plugin README, opening paragraph"),
    Site(_PLG, "programs_catalogued",
         r"\(([\d,]+) catalogued in \[`programs/INDEX\.md`\]",
         "plugin README, opening paragraph"),
    Site(_PLG, "skills",
         r"\*\*([\d,]+) skills\*\* that back the programs up",
         "plugin README, opening paragraph"),
    Site(_PLG, "program_tests",
         r"and\n\*\*([\d,]+) test files\*\*\. Programs decide",
         "plugin README, opening paragraph"),
    Site(_PLG, "programs_py",
         r"\*\*([\d,]+) deterministic programs\*\* verify actual artifacts on disk",
         "plugin README, three-layer architecture"),
    Site(_PLG, "programs_py",
         r"At ([\d,]+) programs, a hand-maintained per-bucket listing",
         "plugin README, Layout"),
    Site(_PLG, "programs_py",
         r"├── programs/\s+— ([\d,]+) \.py",
         "plugin README, layout tree"),
    Site(_PLG, "programs_catalogued",
         r"├── programs/\s+— [\d,]+ \.py \(([\d,]+) catalogued\)",
         "plugin README, layout tree"),
    Site(_PLG, "program_tests",
         r"│   └── tests/\s+— ([\d,]+) test files",
         "plugin README, layout tree"),
    Site(_PLG, "skills",
         r"├── skills/\s+— ([\d,]+) skills, each with SKILL\.md",
         "plugin README, layout tree"),
    Site(_PLG, "skill_compliance_tests",
         r"│   └── <skill>/tests/\s+— ([\d,]+) per-skill compliance regression files",
         "plugin README, layout tree"),
    Site(_PLG, "program_tests",
         r"\*\*([\d,]+) test files\*\* under `programs/tests/`",
         "plugin README, Test suite"),
    Site(_PLG, "skill_compliance_tests",
         r"plus \*\*([\d,]+)\*\* per-skill compliance regressions",
         "plugin README, Test suite"),
    Site(_PLG, "programs_py",
         r"program count moved from 41 to ([\d,]+)",
         "plugin README, history"),
    # The 3-layer coverage line: the DENOMINATORS are the skill count, so they
    # rot the same way. The numerators 35 and 6 are measurements of a different
    # kind and stay ungated — an ungated number is stated as such, not gated by
    # a rule that would have to guess at what it counts.
    Site(_PLG, "skills",
         r"Measured over the ([\d,]+) skills:",
         "plugin README, 3-layer coverage — denominator"),
    Site(_PLG, "skills",
         r"\*\*([\d,]+)/[\d,]+\*\* ship a `compliance\.yaml`",
         "plugin README, 3-layer coverage — every skill ships one"),
    Site(_PLG, "skills",
         r"\*\*[\d,]+/([\d,]+)\*\* ship a `compliance\.yaml`",
         "plugin README, 3-layer coverage — L1 denominator"),
    Site(_PLG, "skills",
         r"\*\*[\d,]+/([\d,]+)\*\* declare a\n?non-empty `cross_checks:`",
         "plugin README, 3-layer coverage — L2 denominator"),
    Site(_PLG, "skills",
         r"\*\*[\d,]+/([\d,]+)\*\* wire `mcp_execution_verify`",
         "plugin README, 3-layer coverage — L3 denominator"),
    # ── the "what each number counts" table — every key stated once, with its
    # population, so a reader can tell a drifted number from a different one.
    Site(_PLG, "programs_py",
         r"\| `programs_py` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
    Site(_PLG, "programs_catalogued",
         r"\| `programs_catalogued` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
    Site(_PLG, "programs_py_all",
         r"\| `programs_py_all` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
    Site(_PLG, "program_tests",
         r"\| `program_tests` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
    Site(_PLG, "program_tests_all",
         r"\| `program_tests_all` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
    Site(_PLG, "checkers_check_py",
         r"\| `checkers_check_py` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
    Site(_PLG, "checkers_check_audit_lint",
         r"\| `checkers_check_audit_lint` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
    Site(_PLG, "mcp_eda_tests",
         r"\| `mcp_eda_tests` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
    Site(_PLG, "skills",
         r"\| `skills` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
    Site(_PLG, "skill_compliance_tests",
         r"\| `skill_compliance_tests` \| \*\*([\d,]+)\*\* \|", "plugin README, counts table"),
]


# ─── discovery ──────────────────────────────────────────────────────
def _catalogued() -> Optional[int]:
    """Row count of INDEX.md, taken from ITS OWN generator, not re-derived.

    `tools/gen_programs_index.py` decides what is a helper and what does not
    parse; re-implementing that here would produce a second answer to the same
    question, which is the disease. When the generator is not on disk (a
    standalone plugin install) the answer is None — NOT DETERMINED, never 0.
    """
    gen = REPO_ROOT / "tools" / "gen_programs_index.py"
    if not gen.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_gpi_for_inventory", gen)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return len(mod.collect())


def discover() -> dict:
    counts: Dict[str, Optional[int]] = {
        "programs_py": len(list(PROGRAMS.glob("*.py"))),
        "programs_catalogued": _catalogued(),
        "programs_py_all": len(list(PROGRAMS.rglob("*.py"))),
        "program_tests": len(list((PROGRAMS / "tests").rglob("test_*.py"))),
        "program_tests_all": len(list((PROGRAMS / "tests").rglob("*.py"))),
        "checkers_check_py": len(list(PROGRAMS.glob("*_check.py"))),
        "checkers_check_audit_lint": len(
            set(PROGRAMS.glob("*_check.py"))
            | set(PROGRAMS.glob("*_audit.py"))
            | set(PROGRAMS.glob("*_lint.py"))),
        "mcp_eda_tests": len(list((PLUGIN / "mcp-eda" / "test").glob("test_*.py"))),
        "skills": len(list(PLUGIN.glob("skills/*/SKILL.md"))),
        "skill_compliance_tests": len(list(PLUGIN.glob("skills/*/tests/test_*.py"))),
    }
    missing = sorted(set(counts) - set(DEFINITIONS))
    if missing:  # a count with no stated population is the bug, not a nit
        raise AssertionError(
            f"counts without a `counts what` definition: {missing}")
    return {
        "schema_version": 1,
        "_comment": "AUTHORITATIVE program-corpus inventory — generated from the "
                    "filesystem by programs/gen_program_inventory.py. Do NOT "
                    "hand-edit. Every stated program count in this repo must be "
                    "read from `counts` here, never hand-typed; "
                    "`--check` fails when a doc quotes a different number.",
        "counts": counts,
        "definitions": DEFINITIONS,
    }


# ─── the doc-site gate ──────────────────────────────────────────────
def _stated(text: str, pattern: str) -> List[tuple]:
    """(value, 1-based line) for every match of a one-group site pattern."""
    out = []
    for m in re.finditer(pattern, text):
        out.append((int(m.group(1).replace(",", "")),
                    text.count("\n", 0, m.start(1)) + 1))
    return out


def check_sites(counts: Dict[str, Optional[int]]) -> Dict[str, list]:
    """Compare every registered stated site against the generated counts."""
    drift: List[dict] = []
    blind: List[dict] = []
    not_determined: List[dict] = []
    checked = 0
    for site in STATED_SITES:
        f = REPO_ROOT / site.path
        expected = counts.get(site.key)
        if not f.is_file() or expected is None:
            not_determined.append({"file": site.path, "key": site.key,
                                   "why": "file absent" if not f.is_file()
                                          else "count NOT DETERMINED"})
            continue
        found = _stated(f.read_text(errors="replace"), site.pattern)
        if not found:
            blind.append({"file": site.path, "key": site.key,
                          "note": site.note, "pattern": site.pattern})
            continue
        for value, line in found:
            checked += 1
            if value != expected:
                drift.append({"file": site.path, "line": line, "key": site.key,
                              "note": site.note, "stated": value,
                              "generated": expected})
    return {"checked": checked, "drift": drift, "blind": blind,
            "not_determined": not_determined}


def _report(inv: dict, committed_ok: Optional[bool], sites: dict) -> dict:
    return {
        "tool": "gen_program_inventory",
        "counts": inv["counts"],
        "committed_inventory_matches": committed_ok,
        "sites_checked": sites["checked"],
        "drift": sites["drift"],
        "blind_sites": sites["blind"],
        "not_determined": sites["not_determined"],
    }


def _write_json(path: str, payload: dict) -> None:
    sys.path.insert(0, str(PROGRAMS))
    from _atomic_artefact import write_json  # noqa: E402  (#1082 invariant)
    write_json(Path(path), payload)


def verdict(inv: dict, sites: dict,
            committed: Optional[dict]) -> tuple:
    """(rc, fail_lines) — the whole decision, in one testable place.

    rc 0 PASS / 1 FAIL / 2 NOT CHECKED. A definite failure OUTRANKS "could not
    look": rc=2 must never hide a measured contradiction, and rc=2 is never a
    pass. Kept out of `main` so the discriminating cases can be exercised
    directly instead of through a subprocess that only ever sees this tree.
    """
    fail: List[str] = []
    if committed is None:
        fail.append(f"{OUT.name} missing — run without --check to generate")
    else:
        for k, v in inv["counts"].items():
            if v is None:
                # NOT DETERMINED cannot contradict a recorded measurement. The
                # standalone-install case reaches here; reading it as a
                # mismatch would turn "I could not look" into "the number is
                # wrong", which is the confusion this whole file removes.
                continue
            c = committed.get("counts", {}).get(k)
            if c != v:
                fail.append(f"{OUT.name}: {k} committed={c} filesystem={v}")
        if committed.get("definitions") != inv["definitions"]:
            fail.append(f"{OUT.name}: `definitions` stale vs this file")

    for d in sites["drift"]:
        fail.append(f"{d['file']}:{d['line']} states {d['stated']} for "
                    f"`{d['key']}` ({d['note']}) — generated value is "
                    f"{d['generated']}")
    for b in sites["blind"]:
        fail.append(f"{b['file']}: registered site for `{b['key']}` "
                    f"({b['note']}) matched NOTHING — the guard has gone blind; "
                    f"restore the sentence or drop the site from STATED_SITES")

    if fail:
        return 1, fail
    if sites["not_determined"] and not sites["checked"]:
        return 2, []
    return 0, []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="verify the committed inventory AND every stated count "
                         "in the registered docs; exit 1 on drift")
    ap.add_argument("--json", help="write a machine-readable report here")
    a = ap.parse_args()

    inv = discover()

    if not a.check:
        _write_json(str(OUT), inv)
        print(f"wrote {OUT}")
        width = max(len(k) for k in inv["counts"])
        for k, v in inv["counts"].items():
            print(f"  {k:<{width}} = {'NOT DETERMINED' if v is None else v}")
            print(f"  {'':<{width}}   counts: {DEFINITIONS[k]}")
        if a.json:
            _write_json(a.json, _report(inv, None, {"checked": 0, "drift": [],
                                                    "blind": [],
                                                    "not_determined": []}))
        return

    committed = json.loads(OUT.read_text()) if OUT.exists() else None
    sites = check_sites(inv["counts"])
    rc, fail = verdict(inv, sites, committed)

    if a.json:
        _write_json(a.json, _report(inv, rc != 1 or not any(
            line.startswith(OUT.name) for line in fail), sites))

    if rc == 2:
        for n in sites["not_determined"]:
            print(f"[NOT CHECKED] {n['file']} ({n['key']}): {n['why']}",
                  file=sys.stderr)
        print("[NOT CHECKED] gen_program_inventory: no stated site was "
              "readable — this is not a PASS", file=sys.stderr)
        sys.exit(2)

    if rc == 1:
        print("[FAIL] gen_program_inventory: stated program counts have drifted",
              file=sys.stderr)
        for line in fail:
            print(f"  {line}", file=sys.stderr)
        print("  Remedy: `python3 programs/gen_program_inventory.py` to "
              "regenerate, then correct the doc line(s) named above.",
              file=sys.stderr)
        sys.exit(1)

    for n in sites["not_determined"]:
        print(f"[WARN] {n['file']} ({n['key']}): {n['why']}")
    print(f"[PASS] gen_program_inventory: {sites['checked']} stated count(s) "
          f"across {len({s.path for s in STATED_SITES})} file(s) match the "
          f"generated inventory (programs_py={inv['counts']['programs_py']}, "
          f"programs_catalogued={inv['counts']['programs_catalogued']}, "
          f"program_tests={inv['counts']['program_tests']})")
    sys.exit(0)


if __name__ == "__main__":
    main()
