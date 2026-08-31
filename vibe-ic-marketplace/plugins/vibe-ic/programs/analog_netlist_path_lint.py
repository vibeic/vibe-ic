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
    file (nothing to lint); the gate does NOT vacuously claim the path is
    clean — it reports files_with_includes so a 0 there is visible.

Usage:
    python3 analog_netlist_path_lint.py <project_dir>
    python3 analog_netlist_path_lint.py <project_dir> --json out.json

Exit codes:
    0 = PASS (or self-skip)
    1 = FAIL (non-whitelisted absolute path)
    2 = IO / parse error

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

try:
    import _path_layout as _pl
    _HAVE_PL = True
except Exception:  # pragma: no cover
    _HAVE_PL = False

GATE = "analog_netlist_path_lint"

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
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


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


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    try:
        project_root = str(project.resolve())
    except OSError:
        project_root = str(project)
    analog_dir = _analog_dir(project)
    if analog_dir is None:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR", severity="INFO",
            message="No analog directory; skipping path lint"))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    sp_files = sorted(analog_dir.rglob("*.sp"))
    if not sp_files:
        result.findings.append(Finding(
            rule="SKIP_NO_SP_FILES", severity="INFO",
            message="No .sp files; skipping path lint"))
        result.summary = {"skipped": True, "reason": "no_sp_files"}
        return result

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
    result.summary = {
        "skipped": False,
        "files_checked": checked,
        "files_with_includes": files_with_includes,
        "non_whitelisted_absolute_paths": bad_paths,
        "pass": result.passed,
    }
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)
    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    else:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {GATE}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
