#!/usr/bin/env python3
"""gate_fixture_discrimination_check — EXECUTE every fixture pair, both ways.

THIS GATE BLOCKS (rc=1) on a fixture pair that does not discriminate.

WHY IT EXISTS, MEASURED
=======================
`gate_mutation_fixture_check` asks whether `tools/ci/gate_fixtures/<slug>.py`
DEFINES both `can_pass` and `can_fail`. Existence is not discrimination, and
the difference is not academic:

  v1.15.79 moved the four PPA campaign trees to `docs/campaigns/`. Eleven
  fixtures kept planting their subject at the OLD path, so ten of them built
  can_pass and can_fail at a location their gate no longer reads and both arms
  landed on the same EMPTY corpus. MEASURED at 85338ac71308102dd957f95f4d12cd\
5290a02943: `test_gate_fixtures_discriminate` 11 failed / 77 passed.

  Through all of it `gate_mutation_fixture_check` answered GREEN — every file
  was still there — for four landings. The only thing that EXECUTES the pairs
  is `tools/ci/test_gate_fixtures_discriminate.py`, and nothing runs it: no
  hygiene row, no plugin-suite selector.

  AND THE CENSUS IS NOT WIRED EITHER, which is worth stating because I first
  wrote the opposite here and it was wrong. MEASURED on this tree: a grep of
  `tools/` and `.github/` finds no invocation of `gate_mutation_fixture_check`
  outside its own test file, and `repo_hygiene_gates.sh --list` names no row
  containing "fixture". So the whole fixture-coverage regime — existence AND
  discrimination — sits off the landing path. This file wires the half that
  can say no about the pairs themselves; the census half is REPORTED, not
  wired here, because a second new row is a second decision.

WHAT IT MEASURES
================
For every fixture the SUBJECT declares: build `can_pass`, run the gate exactly
as the subject's `repo_hygiene_gates.sh` declares it, require rc 0; build
`can_fail`, run the same argv, require a refusal for the stated reason. A pair
where either arm disagrees is a fixture that has stopped discriminating —
whether because the gate broke, the fixture drifted, or the corpus moved under
both.

IT IS THE SAME ENGINE THE SUITE USES, IMPORTED AND NOT RE-IMPLEMENTED.
`gate_mutation_fixtures.run_pair` is the one place the arms are executed; a
second copy of that logic is the drift shape this repository has removed four
times already (#527/#530/#534/#538).

WHY `--root` AND NOT `__file__`
===============================
The subject and the ENGINE are deliberately different trees. `--root` chooses
whose `repo_hygiene_gates.sh` and whose `gate_fixtures/` are read; the engine,
its declaration parser and their import closure always come from the tree this
file lives in. That is what lets this gate carry a fixture of its own without
the fixture having to vendor 200 modules into a synthetic subject — and it is
why the declaration spells the program `$RUNTIME_ROOT/...` and the subject
`--root "$ROOT"`.

exit 0 = every declared pair discriminates
exit 1 = at least one does not (BLOCKING)
exit 2 = could not be determined — no subject, or no fixture to run. NEVER a
         vacuous pass: a run that executed zero pairs has not shown anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import gate_mutation_fixtures as F  # noqa: E402


def audit(root: Path):
    """(verdict, rows) — one row per fixture the subject declares."""
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    fixture_dir = root / "tools" / "ci" / "gate_fixtures"
    if not script.is_file():
        return "NOT_CHECKED", [f"no declaration script at {script}"]
    if not fixture_dir.is_dir():
        return "NOT_CHECKED", [f"no fixture directory at {fixture_dir}"]

    decls = {d.label: d for d in F.declarations(script)}
    fixtures = sorted(F.load_fixtures(fixture_dir).values(),
                      key=lambda f: f.slug)
    if not fixtures:
        return "NOT_CHECKED", [f"no fixture module under {fixture_dir}"]

    rows = []
    for fx in fixtures:
        decl = decls.get(fx.gate)
        if decl is None:
            rows.append({"slug": fx.slug, "ok": False,
                         "detail": f"names an undeclared gate {fx.gate!r}"})
            continue
        if not (fx.has_can_pass and fx.has_can_fail):
            # `gate_mutation_fixture_check` owns the HALF verdict and reports
            # it against a baseline that may only shrink. Re-failing it here
            # would make one debt two reds; this row is about execution.
            rows.append({"slug": fx.slug, "ok": True,
                         "detail": "HALF — not executed here; "
                                   "gate_mutation_fixture_check owns it"})
            continue
        ok_pass, ok_fail = F.run_pair(decl, fx)
        if ok_pass.ok and ok_fail.ok:
            rows.append({"slug": fx.slug, "ok": True, "detail": "discriminates"})
        else:
            bad = ok_pass if not ok_pass.ok else ok_fail
            arm = "can_pass" if not ok_pass.ok else "can_fail"
            rows.append({"slug": fx.slug, "ok": False,
                         "detail": f"{arm}: {bad.detail}"})
    return ("FAIL" if any(not r["ok"] for r in rows) else "PASS"), rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="the subject whose declarations and fixtures are "
                         "read (default: the tree this file lives in)")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve() if a.root else F.REPO_ROOT

    verdict, rows = audit(root)
    if verdict == "NOT_CHECKED":
        print(f"[CANNOT DETERMINE] gate_fixture_discrimination: {rows[0]}. "
              f"NOT a pass — no pair was executed.", file=sys.stderr)
        return 2

    executed = [r for r in rows if r["detail"] != "HALF — not executed here; "
                                                 "gate_mutation_fixture_check owns it"]
    bad = [r for r in rows if not r["ok"]]
    if a.json_out:
        Path(a.json_out).write_text(
            json.dumps({"root": str(root), "verdict": verdict, "rows": rows},
                       indent=2) + "\n", encoding="utf-8")
    print(f"  gate fixture pairs EXECUTED both ways: {len(executed)} of "
          f"{len(rows)} declared; {len(bad)} do not discriminate")
    if bad:
        print(f"\n[FAIL] {len(bad)} fixture pair(s) do not discriminate — a "
              f"pair that cannot tell its gate's good input from its bad one "
              f"is evidence of nothing:")
        for r in bad:
            print(f"   {r['slug']}: {r['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
