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

Whitelist:
    * /foss/pdks/            — the canonical open-PDK container root.
    * anything INSIDE the project directory — rung-1 of the analog PDK ladder
      (`analog_pdk_availability._resolve_project_custom_pdk`) stages a native /
      NDA-node PDK under `<project>/input/pdk/`, and `analog_netlist_pdk_check`
      accepts a deck that loads it (#151). Such a path travels with the
      project, so it is portable and MUST NOT be flagged — flagging it would
      hard-FAIL the whole native custom-PDK track this flow deliberately
      supports.

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
import os
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


# See analog_netlist_connectivity_check for the measured rationale: the flow
# YAML anchors A3 netlists at `phase2/analog/*/*.sp` while the analog runner
# writes them under `phase3/analog/<block>/`. Returning only the FIRST existing
# root hid the phase2 decks from this gate on every project that had reached A5
# — a vacuous PASS. Scan every analog root; never fall back to the whole
# project (a digital PEX netlist is not an analog deck).
_ANALOG_ROOT_RELS = ("phase1/analog", "phase2/analog", "phase3/analog",
                     "analog")


def _analog_roots(project: Path) -> List[Path]:
    """Every analog root that exists, de-duplicated, in scan order."""
    roots: List[Path] = []
    seen = set()

    def _add(cand: Optional[Path]) -> None:
        if cand is None or not cand.is_dir():
            return
        try:
            key = cand.resolve()
        except OSError:
            key = cand
        if key in seen:
            return
        seen.add(key)
        roots.append(cand)

    if _HAVE_PL:
        try:
            d = _pl.analog_dir(project)
            _add(Path(d) if d else None)
        except Exception:
            pass
    for rel in _ANALOG_ROOT_RELS:
        _add(project / rel)
    return roots


def _sp_files(project: Path) -> List[Path]:
    """Every `.sp` deck under every analog root, de-duplicated."""
    out: List[Path] = []
    seen = set()
    for root in _analog_roots(project):
        for sp in sorted(root.rglob("*.sp")):
            try:
                key = sp.resolve()
            except OSError:
                key = sp
            if key in seen:
                continue
            seen.add(key)
            out.append(sp)
    return sorted(out)


def _is_whitelisted(path_tok: str, project: Path) -> bool:
    if any(path_tok.startswith(p) for p in WHITELIST_PREFIXES):
        return True
    # A staged in-project PDK (rung 1 of the analog PDK ladder — see the module
    # docstring) travels WITH the project, so an absolute path pointing inside
    # it is portable, not a hardcoded environment path.
    try:
        root = os.path.abspath(str(project))
        cand = os.path.abspath(path_tok)
    except (OSError, ValueError):
        return False
    return cand == root or cand.startswith(root.rstrip(os.sep) + os.sep)


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    if not _analog_roots(project):
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR", severity="INFO",
            message="No analog directory; skipping path lint"))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    sp_files = _sp_files(project)
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
            if path_tok.startswith("/") and not _is_whitelisted(path_tok,
                                                                project):
                bad_paths += 1
                result.findings.append(Finding(
                    rule="NON_WHITELISTED_ABSOLUTE_PATH",
                    severity="ERROR",
                    message=(f"{rel}: hardcoded absolute path '{path_tok}' is "
                             f"not under {WHITELIST_PREFIXES[0]}; use the "
                             f"standard PDK include pattern"),
                    file=rel,
                    line=idx,
                ))
        if had_include:
            files_with_includes += 1

    result.passed = (bad_paths == 0)
    if result.passed and files_with_includes:
        result.findings.append(Finding(
            rule="PATH_LINT_OK", severity="INFO",
            message=(f"all include/lib paths are relative, under "
                     f"{WHITELIST_PREFIXES[0]}, or inside the project")))
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
