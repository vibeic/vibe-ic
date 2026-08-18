#!/usr/bin/env python3
"""fpga_search_path_includes_required_dirs_check.py — Wave 16 silent-bug gate.

When RTL uses `$readmemh("X.hex")` or `$readmemb`, Quartus QSF must
have a `set_global_assignment -name SEARCH_PATH <dir>` covering the
directory containing X.hex (relative to the QSF location). Otherwise
Quartus cannot find the hex file at compile and silently leaves the
target memory uninitialised.

Detection
=========
1. Find all `$readmemh` / `$readmemb` invocations under `<project>/rtl/`.
   Extract the referenced filename (basename).
2. For each filename, locate it anywhere under <project>/.
3. Read every `<project>/fpga/*.qsf` (and any `*.qsf` under fpga/).
4. Extract `set_global_assignment -name SEARCH_PATH <dir>` and
   `set_global_assignment -name MISC_FILE|MIF_FILE <path>` global
   assignments. Resolve them relative to the QSF directory.
5. **PASS** when every referenced file is reachable via at least one
   QSF SEARCH_PATH (the file lives under one of those dirs) OR is
   listed verbatim via MISC_FILE/MIF_FILE.
6. **FAIL** when at least one referenced file is unreachable.
7. **SKIP** when project has no QSF / no $readmem calls.
8. Honors waiver `fpga_search_path_runtime_supplied_intentional`
   (≥40 chars).

Chip-AGNOSTIC: works for any project with Quartus QSF + RTL using
$readmem.

Exit codes
==========
0 — PASS / SKIP / PASS_WITH_WAIVER
1 — FAIL
2 — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl

WAIVER_KEY = "fpga_search_path_runtime_supplied_intentional"
WAIVER_MIN_LEN = 40

_READMEM_RE = re.compile(
    r"\$readmem(?:h|b)\s*\(\s*\"([^\"]+)\"",
    re.IGNORECASE,
)
_QSF_SEARCH_PATH_RE = re.compile(
    r"set_global_assignment\s+-name\s+SEARCH_PATH\s+\"?([^\s\"]+)\"?",
    re.IGNORECASE,
)
_QSF_MISC_FILE_RE = re.compile(
    r"set_global_assignment\s+-name\s+(?:MISC_FILE|MIF_FILE)\s+\"?([^\s\"]+)\"?",
    re.IGNORECASE,
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _find_rtl_files(project: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.exists():
        return []
    out: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".v", ".sv", ".svh", ".vh"):
            out.append(p)
    return sorted(out)


def _scan_readmem(rtl_files: List[Path]) -> List[Tuple[Path, int, str]]:
    out: List[Tuple[Path, int, str]] = []
    for f in rtl_files:
        try:
            text = _strip_comments(f.read_text(errors="ignore"))
        except OSError:
            continue
        for m in _READMEM_RE.finditer(text):
            line = text[:m.start()].count("\n") + 1
            out.append((f, line, m.group(1)))
    return out


def _qsf_files(project: Path) -> List[Path]:
    fpga_dir = _pl.fpga_early_dir(project)
    if not fpga_dir.exists():
        return []
    return sorted(fpga_dir.rglob("*.qsf"))


def _qsf_search_paths(qsf_files: List[Path]) -> List[Tuple[Path, Path]]:
    out: List[Tuple[Path, Path]] = []
    for qsf in qsf_files:
        try:
            text = qsf.read_text(errors="ignore")
        except OSError:
            continue
        for m in _QSF_SEARCH_PATH_RE.finditer(text):
            sp = m.group(1).strip()
            try:
                resolved = (qsf.parent / sp).resolve()
            except OSError:
                continue
            out.append((qsf, resolved))
    return out


def _qsf_misc_files(qsf_files: List[Path]) -> List[Tuple[Path, Path]]:
    out: List[Tuple[Path, Path]] = []
    for qsf in qsf_files:
        try:
            text = qsf.read_text(errors="ignore")
        except OSError:
            continue
        for m in _QSF_MISC_FILE_RE.finditer(text):
            sp = m.group(1).strip()
            try:
                resolved = (qsf.parent / sp).resolve()
            except OSError:
                continue
            out.append((qsf, resolved))
    return out


def _locate_referenced_file(project: Path, fname: str) -> List[Path]:
    base = Path(fname).name
    out: List[Path] = []
    for p in project.rglob(base):
        if p.is_file():
            out.append(p.resolve())
    return out


def _file_reachable(project: Path,
                    fname: str,
                    search_paths: List[Tuple[Path, Path]],
                    misc_files: List[Tuple[Path, Path]]) -> bool:
    base = Path(fname).name
    # MISC_FILE explicit match?
    for _qsf, mf in misc_files:
        if mf.name == base and mf.exists():
            return True
    # Resolve candidates and check whether any sits under a SEARCH_PATH dir.
    candidates = _locate_referenced_file(project, base)
    for cand in candidates:
        for _qsf, sp in search_paths:
            try:
                if not sp.exists() or not sp.is_dir():
                    continue
                if cand.parent == sp:
                    return True
                # Also accept if cand is directly under sp via resolve.
                direct = (sp / base).resolve()
                if direct.exists() and direct == cand:
                    return True
            except OSError:
                continue
    return False


def _waived(project: Path) -> Tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        rationale = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(rationale, str) and \
           len(rationale.strip()) >= WAIVER_MIN_LEN:
            return True, rationale.strip()
    return False, ""


def inspect(project: Path) -> Tuple[List[str], dict]:
    failures: List[str] = []
    summary: dict = {}

    rtl = _find_rtl_files(project)
    if not rtl:
        summary["skip_reason"] = "no rtl/ directory"
        return failures, summary

    calls = _scan_readmem(rtl)
    summary["readmem_calls"] = len(calls)
    if not calls:
        summary["skip_reason"] = "no $readmemh / $readmemb calls in RTL"
        return failures, summary

    qsfs = _qsf_files(project)
    summary["qsf_files"] = [str(q.relative_to(project)) for q in qsfs]
    if not qsfs:
        summary["skip_reason"] = "no QSF found under fpga/ (ASIC-only?)"
        return failures, summary

    sps = _qsf_search_paths(qsfs)
    mfs = _qsf_misc_files(qsfs)
    summary["search_paths"] = [str(p) for _q, p in sps]
    summary["misc_files"] = [str(p) for _q, p in mfs]

    for f, ln, fname in calls:
        if not _file_reachable(project, fname, sps, mfs):
            try:
                rel = f.relative_to(project)
            except ValueError:
                rel = f
            failures.append(
                f"FPGA_SEARCH_PATH_MISSING — {rel}:{ln}: "
                f"$readmem references {fname!r}, but no QSF SEARCH_PATH "
                f"covers a directory containing it, and no MISC_FILE / "
                f"MIF_FILE entry lists it explicitly. Quartus will fail "
                f"to load the hex/mif at compile.\n"
                f"  Hint: add to QSF (relative to QSF location):\n"
                f"      set_global_assignment -name SEARCH_PATH <dir>\n"
                f"  Or list the file explicitly:\n"
                f"      set_global_assignment -name MISC_FILE <path>"
            )
    return failures, summary


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(
            "Usage: fpga_search_path_includes_required_dirs_check.py "
            "<project_dir> [--json <out>]"
        )
        return 0 if (len(argv) >= 2 and argv[1] in ("-h", "--help")) else 2

    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    json_out: Optional[Path] = None
    if "--json" in argv:
        idx = argv.index("--json")
        if idx + 1 < len(argv):
            json_out = Path(argv[idx + 1])

    failures, summary = inspect(project)
    is_waived, rationale = _waived(project)

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({
            "program": "fpga_search_path_includes_required_dirs_check",
            "passed": not failures,
            "summary": summary,
            "failures": failures,
            "waived": is_waived,
        }, indent=2))

    if "skip_reason" in summary and not failures:
        print(f"SKIP — {summary['skip_reason']}")
        return 0

    if not failures:
        print(
            f"PASS — {summary.get('readmem_calls', 0)} $readmem call(s) "
            f"all reachable via QSF SEARCH_PATH / MISC_FILE"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for fmsg in failures:
            print(f"  • {fmsg}")
        return 0

    print(f"FAIL — {len(failures)} unreachable hex/mif file(s):")
    for fmsg in failures:
        print(f"  • {fmsg}")
        print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
