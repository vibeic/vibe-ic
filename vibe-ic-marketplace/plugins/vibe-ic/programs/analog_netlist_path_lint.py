#!/usr/bin/env python3
"""analog_netlist_path_lint.py — deterministic absolute-path lint for SPICE
netlists.

Rule (from skill `analog-netlist-gen`, "Do not"):
    Do not hardcode absolute PDK paths — use the standard include patterns.
    The ONLY absolute paths legitimately allowed in an analog netlist are
    the canonical PDK model includes under /foss/pdks/<pdk>/... . Any other
    absolute path (a user's home dir, a scratch /tmp deck, a hand-edited
    /home/.../model.lib) is non-portable: it breaks the moment the deck is
    run in the iic-osic-tools container / another machine / CI, and silently
    binds the wrong models.

This lints `.include` / `.lib` directive paths only (those are the lines
that consume a filesystem path). A path is flagged FAIL when it is absolute
(starts with '/') AND does not begin with one of the whitelisted PDK roots.

Whitelist (canonical PDK include roots):
    /foss/pdks/

Honest-FAIL guarantees:
  * absent / non-directory project -> exit 2
  * a deck with `.include /home/me/my_models.lib` -> exit 1
  * an empty / garbage .sp with no include directives -> NO finding for that
    file (nothing to lint); the FILE was still read and put through the rule,
    so it counts toward `examined`, and `files_with_includes` states separately
    how many of them carried a directive.

#511, THIRD INSTANCE — WHAT THIS GATE USED TO PRINT
===================================================
The two guarantees above were true of the JSON report and FALSE of stdout, which
is the channel both consumers read. `main()` printed `[{status}] {GATE}` and then
only ERROR/WARNING findings; `SKIP_NO_SP_FILES`, `SKIP_NO_ANALOG_DIR` and
`PATH_LINT_OK` are all INFO. So, measured on 79d3ebbe8::

    empty project        [PASS] analog_netlist_path_lint     rc 0
    one clean deck       [PASS] analog_netlist_path_lint     rc 0

byte for byte, and `analog_a3_netlist_emit.verify_with_checkers` stores that
string as the `path_lint` evidence in the netlist-emit record. A staging tree
that stopped reaching the deck would have signed off identically.

The gate was never blind — `summary.files_checked` was right the whole time. The
DISCLOSURE had been dropped on the way to stdout. It now carries
`_gate_denominator`'s sentence on the verdict line and in `summary`, and an
examination of NOTHING is `VACUOUS_PASS` / rc 2 with a written reason plus a
`VACUOUS_PASS:` token on stderr — the same idiom the sibling gate
`analog_netlist_include_order_check` (#511's second instance) already carries, so
the two checkers A3 drives together answer in one grammar.

Usage:
    python3 analog_netlist_path_lint.py <project_dir>
    python3 analog_netlist_path_lint.py <project_dir> --json out.json

Exit codes:
    0 = PASS (decks examined, no foreign absolute path)
    1 = FAIL (non-whitelisted absolute path)
    2 = VACUOUS_PASS (nothing to examine — disclosed, NOT a sign-off),
        or IO / parse error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

import _gate_denominator as _gd

try:
    import _path_layout as _pl
    _HAVE_PL = True
except Exception:  # pragma: no cover
    _HAVE_PL = False

GATE = "analog_netlist_path_lint"

#: What ONE unit is, in this gate's own terms. A bare integer would not say
#: whether the count is of decks, of directives or of blocks.
DENOMINATOR_UNIT = ("SPICE netlist deck(s) (*.sp) read and put through the "
                    "absolute-path rule")

#: rc 2 is this repo's NOT-CHECKED tier: `flow_compliance_check` promotes it to
#: the VACUOUS_PASS verdict tier rather than a bare PASS.
RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2

INCLUDE_RE = re.compile(r"^\s*\.(include|lib)\b\s+(\S+)", re.IGNORECASE)

# Canonical PDK include roots that ARE allowed to be absolute.
WHITELIST_PREFIXES = ("/foss/pdks/",)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = GATE
    version: str = "1.0.0"
    passed: bool = True
    #: PASS / VACUOUS_PASS / FAIL. `passed` keeps its literal meaning for every
    #: existing consumer (a vacuous run has signed nothing off, so it is not a
    #: FAIL); `verdict` is where the three-way answer lives.
    verdict: str = "PASS"
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _vacuous(result: AuditResult, rule: str, reason: str,
             summary_reason: str, considered: int = 0) -> AuditResult:
    """Record a run that put ZERO decks through the absolute-path rule.

    Constructing the denominator with ``examined == 0`` and no reason raises,
    so this gate cannot regress into a silent zero by omission — only by
    writing a reason down, which is reviewable.
    """
    result.findings.append(Finding(rule=rule, severity="INFO", message=reason))
    result.verdict = "VACUOUS_PASS"
    # `passed` keeps its LITERAL meaning — no foreign absolute path was found —
    # so a consumer reading only that field can no longer be handed a vacuous
    # run as a clean one. It is not a FAIL either: no ERROR finding is emitted
    # and rc is the skip tier.
    result.passed = False
    result.summary = {"skipped": True, "reason": summary_reason,
                      "files_checked": 0, "files_with_includes": 0,
                      "non_whitelisted_absolute_paths": 0, "pass": False}
    _gd.attach(result.summary, _gd.Denominator(
        unit=DENOMINATOR_UNIT, examined=0, considered=considered,
        not_applicable_reason=reason))
    return result


def _analog_dir(project: Path) -> Optional[Path]:
    if _HAVE_PL:
        try:
            d = _pl.analog_dir(project)
            if d and Path(d).is_dir():
                return Path(d)
        except Exception:
            pass
    for cand in (project / "phase3" / "analog",
                 project / "phase2" / "analog",
                 project / "analog"):
        if cand.is_dir():
            return cand
    if project.is_dir():
        return project
    return None


def _is_whitelisted(path_tok: str, project_root: str = "") -> bool:
    """A path is acceptable when it is a canonical PDK root include OR it
    resolves INSIDE this project's own tree.

    The project-internal rung exists because two shipped rules already force
    that binding (measured: u_hawaii_adc round-5): pdk_analog_completeness_check
    REQUIRES the project to carry its model libs under input/pdk/** (the
    reproducibility rule — a run stands on input/ alone), and the availability
    resolver prefers the project-staged copy over the container's. A3 then
    binds `<project>/input/pdk/models/<lib>` and this lint refused it, so an
    author following both rules could only land in WAIVE. A project-internal
    path travels WITH the project; the non-portability this lint exists to
    catch is a path OUTSIDE both the PDK root and the project (a foreign home
    dir, a scratch /tmp deck), and that stays refused."""
    if any(path_tok.startswith(p) for p in WHITELIST_PREFIXES):
        return True
    if project_root:
        root = project_root.rstrip("/") + "/"
        if path_tok.startswith(root):
            return True
    return False


def run_audit(project: Path,
              real_root: "Optional[Path]" = None) -> AuditResult:
    """`real_root` names the REAL project the decks belong to when `project`
    is a VERIFICATION STAGING tree (A3's `verify_with_checkers` copies the
    deck into a TemporaryDirectory before running the checkers, so the
    project-internal containment rung tested the wrong root and refused the
    project's own staged-PDK binding all over again — measured u_hawaii_adc
    round-5b, one round after the rung was added). Containment accepts a path
    inside EITHER root; everything else is unchanged."""
    result = AuditResult()
    try:
        project_root = str(project.resolve())
    except OSError:
        project_root = str(project)
    if real_root is not None:
        try:
            project_root = str(Path(real_root).resolve())
        except OSError:
            project_root = str(real_root)
    analog_dir = _analog_dir(project)
    if analog_dir is None:
        return _vacuous(
            result, "SKIP_NO_ANALOG_DIR",
            ("no analog directory: none of phase3/analog/, phase2/analog/ or "
             "analog/ exists under the project and the project path itself is "
             "not a directory, so no SPICE deck could be reached. NOT a "
             "sign-off: the include/lib paths of this project have NOT been "
             "linted."),
            "no_analog_dir")

    sp_files = sorted(analog_dir.rglob("*.sp"))
    if not sp_files:
        return _vacuous(
            result, "SKIP_NO_SP_FILES",
            (f"no SPICE deck: {analog_dir.name}/ carries no *.sp file, so the "
             f"absolute-path rule was applied to nothing. NOT a sign-off: this "
             f"project's include/lib paths have NOT been linted."),
            "no_sp_files")

    checked = 0
    files_with_includes = 0
    bad_paths = 0
    for sp in sp_files:
        try:
            text = sp.read_text(errors="replace")
        except OSError:
            continue
        try:
            rel = str(sp.relative_to(project))
        except ValueError:
            rel = str(sp)
        checked += 1
        had_include = False
        for idx, raw in enumerate(text.splitlines(), start=1):
            m = INCLUDE_RE.match(raw)
            if not m:
                continue
            had_include = True
            path_tok = m.group(2)
            if path_tok.startswith("/") and \
                    not _is_whitelisted(path_tok, project_root):
                bad_paths += 1
                result.findings.append(Finding(
                    rule="NON_WHITELISTED_ABSOLUTE_PATH",
                    severity="ERROR",
                    message=(f"{rel}: hardcoded absolute path '{path_tok}' is "
                             f"not under {WHITELIST_PREFIXES[0]} and not "
                             f"inside this project; use the standard PDK "
                             f"include pattern or the project's own "
                             f"input/pdk copy"),
                    file=rel,
                    line=idx,
                ))
            elif path_tok.startswith("/") and \
                    not any(path_tok.startswith(p)
                            for p in WHITELIST_PREFIXES):
                # project-internal absolute binding: accepted (see
                # _is_whitelisted), but stated — portability visibility is
                # this lint's whole reason to exist.
                result.findings.append(Finding(
                    rule="PROJECT_INTERNAL_ABSOLUTE_PATH",
                    severity="INFO",
                    message=(f"{rel}: absolute path '{path_tok}' binds the "
                             f"project's own staged PDK copy (travels with "
                             f"the project; re-render A3 after moving it)"),
                    file=rel,
                    line=idx,
                ))
        if had_include:
            files_with_includes += 1

    result.passed = (bad_paths == 0)
    if result.passed and files_with_includes:
        result.findings.append(Finding(
            rule="PATH_LINT_OK", severity="INFO",
            message=(f"all include/lib paths absolute-only under "
                     f"{WHITELIST_PREFIXES[0]} or relative")))
    result.verdict = "PASS" if result.passed else "FAIL"
    result.summary = {
        "skipped": False,
        "files_checked": checked,
        "files_with_includes": files_with_includes,
        "non_whitelisted_absolute_paths": bad_paths,
        "pass": result.passed,
    }
    # `examined` is the count of decks READ AND PUT THROUGH THE RULE, not the
    # count that carried a directive: a deck with no `.include` was linted and
    # found to hold no path, which is a real examination. How many carried one
    # is the second number, stated beside it and never in place of it.
    _gd.attach(result.summary, _gd.Denominator(
        unit=DENOMINATOR_UNIT, examined=checked, considered=len(sp_files),
        details={"analog_dir": str(analog_dir),
                 "files_with_includes": files_with_includes}))
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    ap.add_argument("--project-root", type=Path, default=None,
                    help="the REAL project root the decks belong to, when "
                         "project_dir is a verification staging copy (the "
                         "project-internal containment rung is tested "
                         "against THIS root)")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return RC_VACUOUS

    result = run_audit(args.project_dir, real_root=args.project_root)
    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    else:
        # The verdict line carries the denominator ON ITSELF. Pointing at a
        # report nobody opens is what let the one-line `[PASS] <gate>` stand for
        # both a clean deck and a project with no deck in it (#511).
        print(f"[{result.verdict}] {GATE}: {_gd.line_of(result.summary)}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.verdict == "VACUOUS_PASS":
        # Second, rc-independent channel — emitted even under --json, where
        # stdout is deliberately empty, so a text consumer is never handed
        # silence. `flow_compliance_check._stdout_signals_vacuous` matches this
        # token at line start.
        denom = result.summary.get(_gd.DENOMINATOR_KEY) or {}
        print(f"VACUOUS_PASS: {denom.get('not_applicable_reason') or ''}",
              file=sys.stderr)
        return RC_VACUOUS
    return RC_PASS if result.passed else RC_FAIL


if __name__ == "__main__":
    sys.exit(main())
