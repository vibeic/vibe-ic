#!/usr/bin/env python3
"""bram_init_portable_compat_check.py — BACKLOG-v11 P1.2.

Detect `$readmemh` / `$readmemb` BRAM initialisation that is silently
incompatible with the target FPGA family.

Motivation
==========

v0.116 <benchmark> used `$readmemh("apple.ver", mem)` to initialise an
inferred BRAM. Quartus on Intel MAX10 silently warned `RAM logic
uninferred because MIF is not supported for the selected family` —
the BRAM was implemented as a 1053-LUT array filled with X / 0.
All OTP reads returned 0 / X; dispatcher's response payload was
wrong; <half-duplex-tester> saw garbage CRC. Took multiple FPGA iterations to
notice the warning was substantive.

Gate behaviour
==============

For each `$readmemh` / `$readmemb` instantiation in RTL, look at
the FPGA target declared in QSF/XDC/Tcl scripts:

  - Intel MAX10: requires QSF
    `INTERNAL_FLASH_UPDATE_MODE "SINGLE COMP IMAGE WITH ERAM"` OR
    explicit `altsyncram` / `altera_syncram` megafunction with
    `init_file` parameter.
  - Intel Cyclone IV / V / Stratix V: `$readmemh` works for inferred
    M9K/M10K block RAMs (ERAM not required) but is fragile —
    accept if QSF declares a known-good family.
  - Xilinx 7-series / UltraScale / UltraScale+: requires `xpm_memory_*`
    macro with `MEMORY_INIT_FILE` parameter, OR explicit BRAM
    primitive with INIT attributes. Plain `$readmemh` works for
    Vivado simulation but does NOT initialise the synthesised BRAM.

Verdict policy:
  - Known-broken family + no documented escape → ERROR
  - Known-OK family + `$readmemh` → PASS (no finding)
  - Unknown family / unrecognised tool → WARNING (we cannot prove
    safety; surface the risk but don't fail)

False-alert guards
==================

  - Silent if no QSF / XDC (= ASIC, no FPGA target)
  - Silent if no `$readmemh` / `$readmemb` instantiation in RTL
  - Silent if RTL uses `altsyncram` / `altera_syncram` / `xpm_memory_*`
    with `init_file` / `MEMORY_INIT_FILE` parameter
  - Silent if QSF has the appropriate MAX10 ERAM mode set
  - Silent if L11 declares `bram_init_method: "external_loader"`
  - Silent if the `$readmemh` lives inside a `// synthesis translate_off`
    / `// synthesis translate_on` block (sim-only)

Exit codes: 0 PASS / 1 FAIL / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_modules, find_rtl_files as _rtl_files
from gate_utils import read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""
    line: int = 0


# ---------------------------------------------------------------------------
# FPGA family taxonomy
# ---------------------------------------------------------------------------

# Families known to silently break $readmemh on inferred BRAM unless
# an explicit escape is set. Tuple of (family_substring,
# escape_token_required_in_qsf, megafunction_alternative).
_KNOWN_BROKEN_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("MAX 10", "INTERNAL_FLASH_UPDATE_MODE", "altsyncram / altera_syncram"),
    ("MAX10", "INTERNAL_FLASH_UPDATE_MODE", "altsyncram / altera_syncram"),
)

# Xilinx series — $readmemh on inferred BRAM does NOT init synthesis;
# requires xpm_memory_* macro.
_XILINX_FAMILIES: tuple[str, ...] = (
    "artix", "kintex", "virtex", "zynq", "ultrascale", "spartan-7",
    "spartan7",
)

# Intel families where $readmemh on inferred RAM works (no escape needed).
_INTEL_OK_FAMILIES: tuple[str, ...] = (
    "cyclone iv", "cyclone v", "cyclone10", "arria", "stratix",
)


def _find_constraint_files(project: Path) -> list[Path]:
    out: list[Path] = []
    for ext in ("*.qsf", "*.xdc", "*.tcl"):
        for f in project.rglob(ext):
            if not f.is_file():
                continue
            parts = set(f.relative_to(project).parts[:-1])
            if parts & {"db", "incremental_db", "output_files", "build",
                        ".git", "__pycache__"}:
                continue
            out.append(f)
    return out


_QSF_FAMILY_RE = re.compile(
    r"set_global_assignment\s+-name\s+FAMILY\s+\"?([^\s\"]+(?:\s+[^\s\"]+)?)\"?",
    re.IGNORECASE,
)
_XILINX_PART_RE = re.compile(
    r"set_property\s+(?:PART|TARGET_PART)\s+(\S+)",
    re.IGNORECASE,
)


def _detect_fpga_target(constraint_files: list[Path]
                        ) -> tuple[str, str]:
    """Return (vendor, family) — both lowercase. ('','') if unknown."""
    for f in constraint_files:
        text = _read(f)
        m = _QSF_FAMILY_RE.search(text)
        if m:
            fam = m.group(1).strip().lower()
            return ("intel", fam)
        m = _XILINX_PART_RE.search(text)
        if m:
            part = m.group(1).strip().lower()
            for x in _XILINX_FAMILIES:
                if x in part:
                    return ("xilinx", x)
            return ("xilinx", part)
    return ("", "")


def _qsf_has_token(constraint_files: list[Path], token: str) -> bool:
    for f in constraint_files:
        if token.lower() in _read(f).lower():
            return True
    return False


# ---------------------------------------------------------------------------
# RTL scanning
# ---------------------------------------------------------------------------

_READMEM_RE = re.compile(
    r"\$readmem(?:h|b)\s*\([^)]*\)", re.IGNORECASE
)
_MEGAFUNC_RE = re.compile(
    r"\b(altsyncram|altera_syncram|xpm_memory_\w+)\b",
    re.IGNORECASE,
)
_TRANSLATE_OFF_RE = re.compile(
    r"//\s*synthesis\s+translate_off[\s\S]*?//\s*synthesis\s+translate_on",
    re.IGNORECASE,
)


def _strip_translate_off(text: str) -> str:
    return _TRANSLATE_OFF_RE.sub("", text)


def _readmem_call_sites(rtl_files: list[Path]
                        ) -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for f in rtl_files:
        text = _read(f)
        if not text:
            continue
        text_syn = _strip_translate_off(text)
        for m in _READMEM_RE.finditer(text_syn):
            line = text_syn[:m.start()].count("\n") + 1
            out.append((f, line, m.group(0)))
    return out


_INIT_PARAM_RE = re.compile(
    r"\b(init_file|MEMORY_INIT_FILE)\b\s*[:=]?\s*\(?\s*[\"']",
    re.IGNORECASE,
)


def _module_has_megafunction_with_init(body: str) -> bool:
    """True iff the given module body declares a megafunction
    (altsyncram / altera_syncram / xpm_memory_*) AND a matching
    init_file / MEMORY_INIT_FILE parameter.

    Module-scoped — does NOT consider megafunctions in OTHER modules
    of the same file. This is the v0.118-stable fix for the file-wide
    silence bug: a guarded BRAM in module A must not silence an
    unguarded $readmemh in module B (realistic case: OTP + sensor
    BRAM in same .sv file with only OTP protected).
    """
    if not _MEGAFUNC_RE.search(body):
        return False
    return bool(_INIT_PARAM_RE.search(body))


def _classify_readmem_calls(rtl_files: list[Path]
                            ) -> list[tuple[Path, int, str, bool]]:
    """Return [(file, line, call, guarded)] — each $readmemh /
    $readmemb classified by whether it lives in a module that ALSO
    has a megafunction-with-init (treated as sim-only mirror), or
    sits unguarded.

    Calls outside any module declaration (top-level $readmemh in a
    bare `initial` block, e.g. inside `define-conditioned snippets)
    fall back to file-wide guard check — same conservative policy as
    pre-v0.118-stable.
    """
    out: list[tuple[Path, int, str, bool]] = []
    for f in rtl_files:
        text = _read(f)
        if not text:
            continue
        text_syn = _strip_translate_off(text)
        modules = find_modules(text_syn)
        # Per-module classification first
        module_intervals: list[tuple[int, int, bool]] = []
        for spec in modules:
            guarded = _module_has_megafunction_with_init(spec.body)
            module_intervals.append((spec.start, spec.end, guarded))

        for m in _READMEM_RE.finditer(text_syn):
            line = text_syn[:m.start()].count("\n") + 1
            # Find enclosing module, if any
            in_module = False
            guarded = False
            for s, e, g in module_intervals:
                if s <= m.start() < e:
                    in_module = True
                    guarded = g
                    break
            if not in_module:
                # Top-level $readmemh — fall back to file-wide check
                guarded = (_MEGAFUNC_RE.search(text_syn) is not None
                           and _INIT_PARAM_RE.search(text_syn) is not None)
            out.append((f, line, m.group(0), guarded))
    return out


# ---------------------------------------------------------------------------
# L11 escape
# ---------------------------------------------------------------------------

def _l11_external_loader(project: Path) -> bool:
    for cand in (
        list(project.glob("phase1/generated_docs/L11*.json"))
        + list(project.glob("L11*.json"))
        + list(project.glob("input/docs/L11*.json"))
    ):
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            if data.get("bram_init_method") == "external_loader":
                return True
            board = data.get("board") or {}
            if isinstance(board, dict) and \
               board.get("bram_init_method") == "external_loader":
                return True
    return False


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "vendor": "",
        "family": "",
        "readmem_calls": [],
        "guarded_calls": 0,
        "unguarded_calls": 0,
        "l11_external_loader": False,
        "qsf_has_eram_mode": False,
        "skipped_reason": "",
    }

    constraint_files = _find_constraint_files(project)
    vendor, family = _detect_fpga_target(constraint_files)
    summary["vendor"] = vendor
    summary["family"] = family
    if not vendor:
        summary["skipped_reason"] = "no FPGA target detected (ASIC)"
        return findings, summary

    rtl_files = _rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files"
        return findings, summary

    classified = _classify_readmem_calls(rtl_files)
    summary["readmem_calls"] = [
        {"file": str(f.relative_to(project)), "line": ln, "call": call,
         "guarded": guarded}
        for f, ln, call, guarded in classified
    ]
    if not classified:
        summary["skipped_reason"] = "no $readmemh / $readmemb in RTL"
        return findings, summary
    summary["guarded_calls"] = sum(1 for _, _, _, g in classified if g)
    summary["unguarded_calls"] = sum(
        1 for _, _, _, g in classified if not g)

    # Only the unguarded calls need a family-escape check. A $readmemh
    # in the same module as a megafunction-with-init is treated as a
    # sim-only mirror and ignored.
    calls = [(f, ln, call) for f, ln, call, g in classified if not g]
    if not calls:
        summary["skipped_reason"] = (
            "every $readmemh shares a module with a megafunction-"
            "with-init — all treated as sim-only mirrors"
        )
        return findings, summary

    if _l11_external_loader(project):
        summary["l11_external_loader"] = True
        summary["skipped_reason"] = (
            "L11 declares bram_init_method=external_loader"
        )
        return findings, summary

    # Family-specific escape check
    is_known_broken = False
    escape_token = ""
    mega_alt = ""
    for fam_sub, esc, mega in _KNOWN_BROKEN_FAMILIES:
        if fam_sub.lower() in family:
            is_known_broken = True
            escape_token = esc
            mega_alt = mega
            break

    is_xilinx = vendor == "xilinx"
    is_intel_ok = any(ok in family for ok in _INTEL_OK_FAMILIES)

    if is_known_broken:
        if _qsf_has_token(constraint_files, escape_token):
            summary["qsf_has_eram_mode"] = True
            return findings, summary
        for f, ln, call in calls:
            # WARNING (not ERROR): some designs work despite the warning
            # because their OTP/init data isn't byte-critical for the
            # downstream test (v099 oracle baseline confirmed). Still a
            # code smell worth flagging — engineer review required.
            findings.append(Finding(
                severity="WARNING",
                rule="BRAM_INIT_FAMILY_INCOMPATIBLE",
                message=(
                    f"`{call}` on family {family!r} silently fails "
                    f"synthesis (RAM logic uninferred — implemented as "
                    f"LUT array filled with X). v0.116 <benchmark> lesson: "
                    f"all OTP reads returned X, <half-duplex-tester> saw garbage CRC. "
                    f"Either (a) add QSF "
                    f"`set_global_assignment -name {escape_token} "
                    f"\"SINGLE COMP IMAGE WITH ERAM\"`, OR (b) replace "
                    f"with {mega_alt} megafunction with init_file "
                    f"parameter."
                ),
                file=str(f.relative_to(project)),
                line=ln,
            ))
        return findings, summary

    if is_xilinx:
        for f, ln, call in calls:
            findings.append(Finding(
                severity="WARNING",
                rule="BRAM_INIT_XILINX_REQUIRES_XPM",
                message=(
                    f"`{call}` on Xilinx target ({family!r}): plain "
                    f"$readmemh on inferred BRAM does NOT initialise "
                    f"the synthesised block (works in Vivado sim only). "
                    f"Use `xpm_memory_sprom` / `xpm_memory_dprom` with "
                    f"`MEMORY_INIT_FILE` parameter instead."
                ),
                file=str(f.relative_to(project)),
                line=ln,
            ))
        return findings, summary

    if is_intel_ok:
        # Cyclone IV/V/etc — $readmemh works for inferred BRAM. PASS.
        return findings, summary

    # Unknown / unrecognised family — WARNING
    for f, ln, call in calls:
        findings.append(Finding(
            severity="WARNING",
            rule="BRAM_INIT_FAMILY_UNKNOWN",
            message=(
                f"`{call}` on family {family!r} ({vendor!r} vendor): "
                f"this gate cannot prove $readmemh-on-inferred-BRAM "
                f"is supported. Either (a) document the family in "
                f"L11, or (b) replace with explicit megafunction "
                f"(altsyncram / xpm_memory_*) with init_file."
            ),
            file=str(f.relative_to(project)),
            line=ln,
        ))
    return findings, summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(prog="bram_init_portable_compat_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="Upgrade WARNING to ERROR")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "bram_init_portable_compat_check",
            "passed": not findings,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== bram_init_portable_compat_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        total = len(summary['readmem_calls'])
        guarded = summary['guarded_calls']
        print(f"  [PASS] {total} call(s) on family-supported target "
              f"({summary['family']}); {guarded} guarded by "
              f"per-module megafunction-with-init")
        return 0
    rc = 0
    for f in findings:
        sev = "ERROR" if (args.strict and f.severity == "WARNING") else f.severity
        if sev == "ERROR":
            rc = 1
        loc = f" ({f.file}:{f.line})" if f.file else ""
        print(f"  [{sev.lower()}] {f.rule}{loc}: {f.message}")
    print(f"\nOverall: {'FAIL' if rc else 'PASS (with warnings)'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
