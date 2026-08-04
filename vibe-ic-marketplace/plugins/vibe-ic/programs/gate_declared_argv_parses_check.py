#!/usr/bin/env python3
"""gate_declared_argv_parses_check.py — a gate the CI umbrella declares but
cannot validly invoke.

THIS GATE BLOCKS (rc=1) on a declaration whose argv the gate's own parser
rejects.

THE DEFECT, MEASURED
====================
`tools/ci/repo_hygiene_gates.sh` DECLARES each gate with the argv it will be
handed:

    run_tolerating_uncheckable "image-version pins resolve" "$ROOT" \\
        python3 "$ROOT/tools/vibeic-eda/sync_image_version.py" --check --require-remote

Nothing checks, at the declaration, that the program on the right still accepts
the flags on the left. The declaration and the program are edited independently
— a renamed flag, a removed positional, a `--strict` that became `--mode strict`
— and the drift surfaces only when CI executes the gate.

For a `run_tolerating_uncheckable` gate it does not surface even then. rc 2
carries two unrelated meanings and `_gate_dispatch.sh` reads only one of them:

    rc 2 -> NOT_CHECKED, "the gate REFUSED — it could not look", non-fatal

and rc 2 is ALSO what argparse exits with when it rejects a command line.
MEASURED against the real script by driving `_gate_dispatch.sh` with one flag
renamed on the `image-version pins resolve` declaration:

    usage: sync_image_version.py [-h] ...
    sync_image_version.py: error: unrecognized arguments: --require-remoteX
       ^^ NOT CHECKED (rc 2, non-fatal): image-version pins resolve [1s]
    repo_hygiene_gates: 0 of 1 gate(s) passed; 1 NOT CHECKED ...
    SUITE EXIT 0

The gate never ran, what it audits was never audited, and the suite is green.
This is vibe-ic#492's finding — "there was no input to check" and "you called me
wrongly" share one exit code — one level up, in the CI umbrella instead of the
P0 structural umbrella. Eight of the 63 declarations use that wrapper today, so
eight gates can go permanently silent without reddening anything.

The other 55 use plain `run`, where rc 2 is a FAIL and therefore loud. It is
still a defect worth failing at the declaration: the reader is shown the gate's
own `usage:` block, which reads as the gate's finding about the repo rather
than as a stale line in the CI script, and it is only reached by executing the
whole suite. Both halves are covered here, because a rule scoped to the silent
half would have to be re-scoped the first time a `run` gate becomes a
`run_tolerating_uncheckable` one.

WHY NOT AN EXISTING CHECKER — each was read before this file was written
========================================================================
* `p0_gate_invocability_drift_check` asserts exactly this property, and asserts
  it for a DIFFERENT umbrella: `flow_compliance_check._STRUCTURAL_RTL_GATES`,
  whose argv comes from `_structural_gate_argv`. Its population does not
  contain a single CI declaration. Widening it would put two umbrellas with two
  argv builders and two verdict policies (a 36-name allow-list here, none
  there) behind one predicate.
* `gate_discloses_denominator_check --population ci` parses THESE declarations
  and drives them — and acts only on `returncode == 0`. A declaration argparse
  rejects exits 2 and is dropped without a word. Verified by reading
  `audit_ci`, and by the control below: it exits 0 on the mutated script.
  Its question ("does a PASS say how much it looked at?") is answered from a
  gate's output text and is a different one.
* `checker_execution_wiring_audit` / `gate_is_wired_check` ask whether anything
  invokes a gate AT ALL. A stale declaration is an invocation — it is just not
  a valid one — so both read it as wired, correctly, for their question.
* `gate_host_independence_check` runs each declaration in two trees and
  compares. An argv the parser rejects is rejected identically in both, so it
  agrees with itself and passes.

WHAT IT ASSERTS, AND EXACTLY HOW FAR THAT REACHES
=================================================
One assertion, per declaration: THE PROGRAM'S ARGUMENT PARSER DOES NOT REJECT
THIS ARGV. Nothing about the verdict, the findings, or whether the gate has
anything to check. `_argv_parse_smoke` stops the process at the first completed
parse of the process argv, so no gate body runs — which is what keeps this
cheap enough to be a registration-time assertion, and what keeps it out of the
way of `_gate_dispatch.sh`'s corpus-write guard.

TWO THINGS IT DELIBERATELY DOES NOT SEE, stated because an audit that hides its
own blind spots is the defect it is about:

  (1) A gate that PARSES the argv and then hand-rolls its own required-argument
      check exits 2 after the smoke has already stopped it. That is
      `_gate_invocation`'s RULE B, and reading it needs the gate to really run.
      This rule is the parser half, as narrow as its name.
  (2) A declaration this smoke cannot drive — argv[0] is not `python3` — is
      counted as NOT PROBED and NAMED on every run. It is never folded into the
      accepted count. Both counts are printed whether the check passes or fails.

A THIRD BLIND SPOT WAS FOUND WHILE MEASURING AND IS CLOSED, NOT DISCLOSED.
35 of the 63 declarations pass NO arguments at all, and for those the smoke's
stop condition — "the parsed list is the process argv" — is satisfied by a
throwaway `argparse.ArgumentParser().parse_args([])` anywhere earlier in the
program. More than half the population could have reported ACCEPTED for an
argv nothing looked at, which is the vacuous pass this file is about committed
by this file. `probe` re-drives every argument-less declaration with an option
no parser knows, which makes the lists differ and forces the real parse. Cost,
measured over the shipped script: 0.76s for all 63 including the 35 second
probes.

THE PREDICATE IS BORROWED, NOT RE-TYPED
=======================================
The declaration parser is `gate_discloses_denominator_check.parse_declarations`
and the argv expander is its `_expand`. Both were got wrong twice in this repo
by re-typing (a label regex that stopped at the first inner quote; a `\\`
continuation that fed a gate a bare backslash as its last argument), and the
rejection classifier was got wrong a third time the same way — the drift check
re-typed `_gate_invocation`'s Rule A, never had Rule B, and was blind to four
gates for as long as it existed. So the rejection verdict comes from
`_gate_invocation.classify_not_invocable`, the repo's single reader of
argparse's rejection protocol.

THE ONE PLACEHOLDER, AND THE SECOND PROBE THAT KEEPS IT HONEST
==============================================================
Three declarations sit inside a `for` loop and carry a shell variable only bash
can bind. `_expand` substitutes a real directory for it. A path VALUE cannot
change whether a parser accepts an argv's SHAPE — except for a `type=`
converter or `argparse.FileType`, which open the value and make argparse reject
it. So a declaration that carries a runtime-expanded token and is rejected is
probed a SECOND time with a real FILE in place of the directory, and a
declaration accepted under either binding is not a finding. The fallback can
only ever CLEAR a rejection, and a rejection that survives both bindings is
about the argv's shape rather than about the probe's placeholder.

chip-AGNOSTIC: it reasons about shell declarations, Python argument parsers and
process exit codes. No design, PDK, vendor or IC literal appears in any
predicate.

USAGE
-----
    python3 gate_declared_argv_parses_check.py [--repo-root DIR]
                                               [--script PATH]
                                               [--json OUT] [--jobs N]
                                               [--timeout S]

EXIT CODES
----------
    0 = PASS  every probed declaration's parser accepted its argv
    1 = FAIL  at least one declaration cannot be validly invoked
    2 = NOT MEASURED (no script, no declarations, parser unavailable)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _argv_parse_smoke                                       # noqa: E402
import _gate_invocation                                        # noqa: E402

RC_OK, RC_FAIL, RC_NOT_MEASURED = 0, 1, 2

_SMOKE = _HERE / "_argv_parse_smoke.py"
_SCRIPT_REL = Path("tools") / "ci" / "repo_hygiene_gates.sh"

#: Per-declaration wall clock. Only reached by a program that never parses the
#: process argv at all, so it is a measurement floor and not a verdict: a
#: timeout is reported as NOT PARSER DRIVEN, never as a rejection.
DEFAULT_TIMEOUT_S = 30

# Outcome vocabulary. Four states and not two, for the reason `_gate_dispatch`
# gives for its own four: "I could not look" must never render as "I looked and
# it was fine".
ACCEPTED = "ACCEPTED"                    # the parser took the argv
REJECTED = "REJECTED"                    # the finding
NOT_PARSER_DRIVEN = "NOT_PARSER_DRIVEN"  # never reached a parse of this argv
NOT_PROBED = "NOT_PROBED"                # this smoke cannot drive it

#: A long option no parser in this tree defines, used to force the real parse
#: of an argument-less declaration. See "THE ARGUMENT-LESS DECLARATION".
_UNKNOWN_OPTION = "--vibeic-argv-parse-smoke-unknown-option"

#: argparse's own wording for "everything you asked for is here; this extra
#: token is not mine". Read, not invented: it is the ONE message that separates
#: "the parser objected to my probe token" from "the parser objected to the
#: declaration". Any other complaint is about the declaration.
_ONLY_THE_PROBE_TOKEN = "unrecognized arguments"


def _declaration_parser():
    """`gate_discloses_denominator_check`, or None when it cannot be imported.

    Returning None rather than raising keeps the failure in the rc-2
    NOT MEASURED lane: a check that cannot enumerate its population must say so,
    not answer PASS over an empty one.
    """
    try:
        import gate_discloses_denominator_check as G   # noqa: PLC0415
    except Exception:                                  # noqa: BLE001
        return None
    return G


def probe(argv: List[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT_S) -> Dict:
    """Drive one declaration as far as the program's parser, and classify it.

    `argv` is the FULL command as the CI script writes it, `python3` first.

    THE ARGUMENT-LESS DECLARATION
    -----------------------------
    `_argv_parse_smoke` stops at the first parse of a list equal to the process
    argv. When the declaration passes NO arguments that list is `[]`, and a
    throwaway `argparse.ArgumentParser().parse_args([])` earlier in the program
    is byte-identical to the real one — so the smoke could report ACCEPTED for
    an argv nothing examined, which is the vacuous pass this program exists to
    find, committed by this program.

    Closed by a SECOND probe rather than by a guess: the same declaration is
    driven again with `_UNKNOWN_OPTION` appended. The process argv is then
    non-empty, no throwaway `parse_args([])` can match it, and the real parse is
    forced. Its answer is read as:

        parser tolerated the extra token        -> ACCEPTED (`parse_known_args`)
        rejected, and ONLY for that token       -> ACCEPTED
        rejected for anything else              -> REJECTED, with that reason
        never reached a parser                  -> keep the first probe's answer

    The second probe can only be reached from a first probe that said ACCEPTED,
    so it can only ever make the verdict stricter.
    """
    first = _run_smoke(argv, cwd, timeout)
    if first["state"] != ACCEPTED or argv[2:]:
        return first
    second = _run_smoke([*argv, _UNKNOWN_OPTION], cwd, timeout)
    if second["state"] == ACCEPTED:
        return first
    if second["state"] == REJECTED:
        if _ONLY_THE_PROBE_TOKEN in second["detail"]:
            return first
        return {"state": REJECTED,
                "detail": f"{second['detail']} (the declaration passes no "
                          f"arguments; measured by re-probing it with an "
                          f"unknown option so a throwaway parse of an empty "
                          f"list could not stand in for the real one)"}
    return first


def _run_smoke(argv: List[str], cwd: Path,
               timeout: int = DEFAULT_TIMEOUT_S) -> Dict:
    """One parse-only invocation, classified. See `probe` for the policy."""
    if not argv:
        return {"state": NOT_PROBED, "detail": "empty command"}
    if Path(argv[0]).name not in ("python3", "python"):
        return {"state": NOT_PROBED,
                "detail": f"argv[0] is {argv[0]!r}, not a python3 invocation; "
                          f"this smoke only knows Python argument parsers"}
    if len(argv) < 2:
        return {"state": NOT_PROBED, "detail": "no program to launch"}
    program = Path(argv[1])
    if not program.is_absolute():
        program = (cwd / program)
    if not program.is_file():
        # Not "unprobeable": the umbrella declares a gate that is not there, so
        # it can never be invoked at all. That is the same defect this file is
        # about, one step earlier, and reporting it as a coverage gap would let
        # a deleted gate read as benign.
        return {"state": REJECTED,
                "detail": f"the declaration names a program that does not "
                          f"exist: {program}"}
    cmd = [sys.executable, str(_SMOKE), str(program), *argv[2:]]
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"state": NOT_PARSER_DRIVEN,
                "detail": f"never parsed the process argv within {timeout}s"}
    except (OSError, subprocess.SubprocessError) as exc:        # noqa: BLE001
        return {"state": NOT_PROBED, "detail": f"could not be launched: {exc}"}

    err = r.stderr or ""
    if (r.returncode == _argv_parse_smoke.RC_PARSER_ACCEPTED
            and _argv_parse_smoke.ACCEPTED_SENTINEL in err):
        return {"state": ACCEPTED, "detail": ""}
    if r.returncode == 2:
        # `classify_not_invocable` is documented as valid for rc 2 ONLY — the
        # two meanings of rc 2 are the whole thing it separates.
        why = _gate_invocation.classify_not_invocable(
            r.stdout or "", err,
            supplied_flags=[a for a in argv if a.startswith("--")])
        if why:
            return {"state": REJECTED, "detail": why}
    tail = [ln for ln in (err or r.stdout or "").splitlines() if ln.strip()]
    return {"state": NOT_PARSER_DRIVEN,
            "detail": f"exited {r.returncode} without parsing the process "
                      f"argv: {tail[-1][:160] if tail else '(no output)'}"}


def _cwd_for(token: str, repo_root: Path) -> Path:
    return repo_root if token == "$ROOT" else (
        repo_root / "vibe-ic-marketplace" / "plugins" / "vibe-ic")


def audit(repo_root: Path, script: Optional[Path] = None,
          timeout: int = DEFAULT_TIMEOUT_S, jobs: int = 8) -> Dict:
    """Every declaration in the CI umbrella, and whether its argv parses."""
    G = _declaration_parser()
    if G is None:
        return {"error": "cannot import gate_discloses_denominator_check; the "
                         "declaration parser is unavailable and the population "
                         "would be a vacuous zero"}
    script = script or (repo_root / _SCRIPT_REL)
    if not script.is_file():
        return {"error": f"no CI umbrella at {script}"}
    decls = G.parse_declarations(script)
    if not decls:
        return {"error": f"{script} declares no gate; this check's own "
                         f"denominator is zero and that is not a pass"}

    #: A real DIRECTORY and a real FILE. See "THE ONE PLACEHOLDER".
    primary, fallback = repo_root, script

    def _one(decl):
        cwd = _cwd_for(decl.cwd_token, repo_root)
        res = probe(G._expand(decl.cmd, repo_root, primary), cwd, timeout)
        if res["state"] == REJECTED and decl.runtime_expansion:
            alt = probe(G._expand(decl.cmd, repo_root, fallback), cwd, timeout)
            if alt["state"] == ACCEPTED:
                res = {"state": ACCEPTED,
                       "detail": "accepted once the runtime-expanded token was "
                                 "bound to a file rather than a directory"}
        return {"gate": decl.label, "line": decl.lineno,
                "runtime_expansion": decl.runtime_expansion, **res}

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        rows = list(ex.map(_one, decls))

    by = lambda s: [r for r in rows if r["state"] == s]          # noqa: E731
    return {"script": str(script), "declared": len(decls), "rows": rows,
            "accepted": len(by(ACCEPTED)),
            "rejected": [{"gate": r["gate"], "line": r["line"],
                          "detail": r["detail"]} for r in by(REJECTED)],
            "not_parser_driven": [{"gate": r["gate"], "detail": r["detail"]}
                                  for r in by(NOT_PARSER_DRIVEN)],
            "not_probed": [{"gate": r["gate"], "detail": r["detail"]}
                           for r in by(NOT_PROBED)]}


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=None,
                    help="repository root (default: derived from this file)")
    ap.add_argument("--script", default=None,
                    help="the CI umbrella to audit (default: %s)" % _SCRIPT_REL)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    a = ap.parse_args(argv)

    root = Path(a.repo_root).resolve() if a.repo_root else _HERE.parents[3]
    try:
        res = audit(root, Path(a.script).resolve() if a.script else None,
                    timeout=a.timeout, jobs=a.jobs)
    except Exception as exc:                                    # noqa: BLE001
        # A crash is not a finding. rc 1 means "a declaration cannot be validly
        # invoked"; letting an exception reach the caller would publish that
        # claim from a probe that measured nothing.
        print(f"[NOT MEASURED] {type(exc).__name__}: {exc}", file=sys.stderr)
        return RC_NOT_MEASURED

    if a.json_out:
        p = Path(a.json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"program": "gate_declared_argv_parses_check",
                                 **res}, indent=2) + "\n", encoding="utf-8")

    if "error" in res:
        print(f"[NOT MEASURED] {res['error']}", file=sys.stderr)
        return RC_NOT_MEASURED

    # The denominator is printed whether the check passes or fails, and the two
    # non-accepted-but-not-a-finding buckets are NAMED. A count that hides which
    # gates it could not reach is the coverage claim this repo keeps retracting.
    undriven, unprobed = res["not_parser_driven"], res["not_probed"]
    for bucket, title in ((undriven, "NOT PARSER DRIVEN"),
                          (unprobed, "NOT PROBED")):
        for row in bucket:
            print(f"[{title}] {row['gate']}: {row['detail']}", file=sys.stderr)

    if res["rejected"]:
        for row in res["rejected"]:
            print(f"[FAIL] {res['script']}:{row['line']} — the gate declared as "
                  f"{row['gate']!r} cannot be validly invoked with the argv the "
                  f"umbrella hands it: {row['detail']}", file=sys.stderr)
        print(f"[FAIL] {len(res['rejected'])} of {res['declared']} CI gate "
              f"declaration(s) are rejected by the gate's own parser. Such a "
              f"gate returns no verdict — and under "
              f"`run_tolerating_uncheckable` its rc 2 reads as NOT_CHECKED and "
              f"the suite still exits 0, so what it audits is UNAUDITED. Fix "
              f"the declaration or the program's CLI.", file=sys.stderr)
        return RC_FAIL

    print(f"[PASS] {res['accepted']} of {res['declared']} gate declaration(s) "
          f"in {res['script']} are accepted by the gate's own argument parser; "
          f"{len(undriven)} never reached a parse of that argv and "
          f"{len(unprobed)} could not be probed (both named above, neither "
          f"counted as accepted).", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
