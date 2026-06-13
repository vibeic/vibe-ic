#!/usr/bin/env python3
"""bram_init_file_actually_loaded_check.py — Wave 16 CRITICAL gate.

Catch the silent failure where BRAM/ROM init data declared in RTL
does NOT actually get loaded into the FPGA bitstream after Quartus
compile. The v0.119.48 fresh-agent benchmark (22nd attempt, <half-duplex-tester>
byte[6]=0x02 FAIL) hit this exact pattern: RTL declared
`(* ram_init_file = "apple.mif" *)` on Intel MAX 10 — Quartus
silently emitted `Info (276013): RAM logic ... is uninferred
because MIF is not supported for the selected family`, the entire
ROM became stuck-at-zero, all OTP-derived ID bytes were 0, and the
host tester padded byte[6]=0x02. Sim PASSed (sim used $readmemh),
hardware FAILed.

Detection
=========
1. Find Quartus build outputs in `<project>/fpga/output_files/` AND
   `<project>/fpga/`. Required files: `*.fit.summary`, `*.map.rpt`
   (or `.map.summary`).
2. Parse `*.fit.summary` for `Total memory bits` line. **FAIL** when
   the project has any RTL with `ram_init_file` / `$readmemh` /
   `$readmemb` / explicit BRAM declaration AND
   `Total memory bits` reports `0 /` (zero memory bits used).
3. Parse `*.map.rpt` (or `.map.summary`) for warning patterns:
     - `RAM logic ".*" is uninferred because MIF is not supported`
     - `Stuck at GND` / `Stuck at VCC` on memory output ports
     - `unable to use M9K block`
     - `not initialized to specified values`
   When any present AND RTL has BRAM init declaration → **FAIL**
   with the exact warning verbatim.
4. Cross-check QSF: if RTL has `$readmemh("X.hex")`, verify Quartus
   QSF has `set_global_assignment -name SEARCH_PATH <dir>` covering
   the directory containing X.hex. **FAIL** when missing.
5. **WARN** when RTL declares BRAM init but no Quartus output
   reports exist yet (build hasn't run).
6. **SKIP** when project has no RTL BRAM init declarations.
7. Honors waiver `bram_init_runtime_loaded_intentional` (≥40 chars).

Chip-AGNOSTIC. Works on any FPGA family with the MIF-not-supported
pattern (MAX 10, Cyclone IV in some configs, etc.).

Exit codes
==========
0 — PASS / SKIP / PASS_WITH_WAIVER / WARN (no FAIL)
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

WAIVER_KEY = "bram_init_runtime_loaded_intentional"
WAIVER_MIN_LEN = 40

# RTL patterns indicating BRAM/ROM init declarations.
_RAM_INIT_FILE_RE = re.compile(
    r"\(\*\s*ram_init_file\s*=\s*\"([^\"]+)\"\s*\*\)",
    re.IGNORECASE,
)
_READMEM_RE = re.compile(
    r"\$readmem(?:h|b)\s*\(\s*\"([^\"]+)\"",
    re.IGNORECASE,
)
# Heuristic: explicit `mem [0:N-1]` / `reg|logic [W-1:0] mem [0:N-1]`.
_EXPLICIT_MEM_RE = re.compile(
    r"\b(?:reg|logic|wire)\s*(?:\[[^\]]+\])?\s*\w+\s*\[\s*0\s*:\s*\d+",
)

# Map.rpt / map.summary warning fingerprints — verbatim Quartus text.
# Note: STUCK_AT_GND/VCC alone are too noisy (any unused bit produces
# them). We only treat them as evidence WHEN paired with a memory-output
# signal name reference. The MIF-not-supported pattern is unambiguous.
#
# Wave 20 (v0.119.52) tightening: the 25th attempt's RTL deliberately
# removed `(* ram_init_file *)` and `$readmemh`, replacing them with a
# `case (addr)` LUT-style ROM. Quartus STILL emitted the
# `Info (276013): RAM logic ... is uninferred` warning + the
# `MIF is not supported` line, AND `Total memory bits: 0`. The previous
# pattern set required an explicit init declaration in RTL before
# treating the warning as a FAIL — so it silent-skipped on this RTL.
# Wave 20 adds patterns and treats the verbatim Quartus warning as
# always-FAIL when the project has any module/file that LOOKS like
# ROM/RAM (file or module name contains otp / rom / mem / lut).
_MAP_FAILURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("MIF_NOT_SUPPORTED",
     re.compile(r"RAM logic\s+\"[^\"]+\"\s+is uninferred because\s+MIF\s+is not supported",
                re.IGNORECASE)),
    ("MIF_NOT_SUPPORTED_LOOSE",
     re.compile(r"\bMIF is not supported for the selected family\b",
                re.IGNORECASE)),
    ("M9K_UNUSABLE",
     re.compile(r"unable to use M9K block", re.IGNORECASE)),
    ("NOT_INIT_TO_SPECIFIED",
     re.compile(r"not initialized to specified values", re.IGNORECASE)),
    ("RAM_LOGIC_UNINFERRED",
     re.compile(r"RAM logic\s+\"[^\"]+\"\s+is uninferred", re.IGNORECASE)),
    # Wave 20: additional warning fingerprints.
    ("CANNOT_INFER_RAM",
     re.compile(r"\bcannot infer\b.*\bRAM\b", re.IGNORECASE)),
    ("CANNOT_USE_M9K",
     re.compile(r"\bcannot use\b.*\bM9K\b", re.IGNORECASE)),
    ("STUCK_AT_GND_MEM",
     re.compile(
         r"Stuck at GND.*?(?:otp|rom|ram|mem|lut)\w*\|"
         r"(?:dout|q\b|data_out|out_q|out_dat|qa\b|qb\b|Ram\d|Mem\d)",
         re.IGNORECASE,
     )),
)

# Wave 20: heuristic — does the project look like it intends to host a
# ROM / RAM / OTP? Used to escalate map.rpt warnings to FAIL even if
# no `$readmemh` / `(* ram_init_file *)` is declared.
_ROM_LIKE_NAME_RE = re.compile(
    r"\b(?:otp|rom|mem|lut|bram|init_table|lookup)\w*\b",
    re.IGNORECASE,
)

_TOTAL_MEM_BITS_RE = re.compile(
    r"Total memory bits\s*:\s*([\d,]+)\s*/\s*([\d,]+)",
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


def _scan_rtl_init(rtl_files: List[Path]) -> dict:
    """Return dict with:
        ram_init_attrs: [(file, line, mif_filename)]
        readmem_calls:  [(file, line, hex_filename)]
        explicit_mems:  [(file, line)]
    """
    ram_init: List[Tuple[Path, int, str]] = []
    readmem: List[Tuple[Path, int, str]] = []
    explicit: List[Tuple[Path, int]] = []
    for f in rtl_files:
        try:
            raw = f.read_text(errors="ignore")
        except OSError:
            continue
        # Don't strip comments first — ram_init_file pragma uses (* *) style
        # which is NOT a comment in SV. But stripping // comments is fine.
        text = _strip_comments(raw)
        for m in _RAM_INIT_FILE_RE.finditer(text):
            line = text[:m.start()].count("\n") + 1
            ram_init.append((f, line, m.group(1)))
        for m in _READMEM_RE.finditer(text):
            line = text[:m.start()].count("\n") + 1
            readmem.append((f, line, m.group(1)))
        for m in _EXPLICIT_MEM_RE.finditer(text):
            line = text[:m.start()].count("\n") + 1
            explicit.append((f, line))
    return {
        "ram_init_attrs": ram_init,
        "readmem_calls": readmem,
        "explicit_mems": explicit,
    }


def _find_quartus_outputs(project: Path) -> dict:
    """Locate fit.summary, map.rpt, map.summary anywhere under
    project/fpga/. Returns dict with lists of paths."""
    fit_sums: List[Path] = []
    map_rpts: List[Path] = []
    map_sums: List[Path] = []
    fpga_dir = _pl.fpga_early_dir(project)
    if not fpga_dir.exists():
        return {"fit_summary": [], "map_rpt": [], "map_summary": []}
    for p in fpga_dir.rglob("*"):
        if not p.is_file():
            continue
        n = p.name.lower()
        if n.endswith(".fit.summary"):
            fit_sums.append(p)
        elif n.endswith(".map.rpt"):
            map_rpts.append(p)
        elif n.endswith(".map.summary"):
            map_sums.append(p)
    return {
        "fit_summary": sorted(fit_sums),
        "map_rpt": sorted(map_rpts),
        "map_summary": sorted(map_sums),
    }


def _parse_total_memory_bits(fit_summary: Path) -> Optional[Tuple[int, int]]:
    try:
        text = fit_summary.read_text(errors="ignore")
    except OSError:
        return None
    m = _TOTAL_MEM_BITS_RE.search(text)
    if not m:
        return None
    used = int(m.group(1).replace(",", ""))
    total = int(m.group(2).replace(",", ""))
    return used, total


def _scan_map_for_warnings(map_path: Path) -> List[Tuple[str, str]]:
    """Return [(rule, verbatim_line)] for each matching map.rpt warning."""
    out: List[Tuple[str, str]] = []
    try:
        text = map_path.read_text(errors="ignore")
    except OSError:
        return out
    seen: set = set()
    for line in text.splitlines():
        for rule, pat in _MAP_FAILURE_PATTERNS:
            if pat.search(line):
                key = (rule, line.strip())
                if key not in seen:
                    seen.add(key)
                    out.append((rule, line.strip()))
                break
    return out


def _qsf_files(project: Path) -> List[Path]:
    fpga_dir = _pl.fpga_early_dir(project)
    if not fpga_dir.exists():
        return []
    return sorted(fpga_dir.rglob("*.qsf"))


def _qsf_search_paths(qsf_files: List[Path]) -> List[Tuple[Path, Path]]:
    """Return list of (qsf_file, resolved_search_path).
    Each SEARCH_PATH is resolved relative to the qsf file's directory.
    """
    out: List[Tuple[Path, Path]] = []
    for qsf in qsf_files:
        try:
            text = qsf.read_text(errors="ignore")
        except OSError:
            continue
        for m in _QSF_SEARCH_PATH_RE.finditer(text):
            sp = m.group(1).strip()
            resolved = (qsf.parent / sp).resolve()
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
            resolved = (qsf.parent / sp).resolve()
            out.append((qsf, resolved))
    return out


def _locate_referenced_file(project: Path, fname: str) -> List[Path]:
    """Find every occurrence of `fname` (basename match) under project."""
    base = Path(fname).name
    out: List[Path] = []
    for p in project.rglob(base):
        if p.is_file():
            out.append(p)
    return out


def _file_reachable_via_qsf(
    project: Path,
    fname: str,
    search_paths: List[Tuple[Path, Path]],
    misc_files: List[Tuple[Path, Path]],
) -> bool:
    """True if `fname` is reachable via QSF SEARCH_PATH or MISC_FILE."""
    base = Path(fname).name
    # MISC_FILE explicit path?
    for _qsf, mf in misc_files:
        if mf.name == base and mf.exists():
            return True
    # SEARCH_PATH that contains the file?
    candidates = _locate_referenced_file(project, base)
    for cand in candidates:
        try:
            cand_resolved = cand.resolve()
        except OSError:
            continue
        for _qsf, sp in search_paths:
            try:
                if sp.exists() and sp.is_dir():
                    # Either the candidate sits directly in this dir, or
                    # the search path itself contains the candidate file.
                    if cand_resolved.parent == sp.resolve():
                        return True
                    direct = (sp / base).resolve()
                    if direct.exists() and direct == cand_resolved:
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


def inspect(project: Path) -> Tuple[List[str], List[str], dict]:
    """Return (failures, warnings, summary)."""
    failures: List[str] = []
    warnings: List[str] = []
    summary: dict = {}

    rtl_files = _find_rtl_files(project)
    if not rtl_files:
        summary["skip_reason"] = "no rtl/ directory"
        return failures, warnings, summary

    rtl_scan = _scan_rtl_init(rtl_files)
    has_ram_init_attr = bool(rtl_scan["ram_init_attrs"])
    has_readmem = bool(rtl_scan["readmem_calls"])
    # explicit_mems alone is not strong evidence of init intent —
    # only count it when paired with one of the above signals.
    has_init_intent = has_ram_init_attr or has_readmem

    # Wave 20: detect "looks-like-ROM" modules even when neither
    # `$readmemh` nor `(* ram_init_file *)` is declared. The 25th
    # attempt replaced both with `case (addr)` LUT — Quartus still
    # emitted the `MIF not supported` warning + `Total memory bits: 0`
    # because the case-style ROM was BRAM-shape-detected and silently
    # demoted. We need to FAIL on the warning irrespective of explicit
    # init syntax when the project has a ROM-named module.
    rom_like_modules: List[Tuple[Path, str]] = []
    for f in rtl_files:
        if _ROM_LIKE_NAME_RE.search(f.stem):
            rom_like_modules.append((f, "filename"))
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for m in re.finditer(
            r"\bmodule\s+(\w+)\b",
            _strip_comments(text),
        ):
            modname = m.group(1)
            if _ROM_LIKE_NAME_RE.search(modname):
                rom_like_modules.append((f, f"module {modname}"))
                break

    summary["ram_init_attr_count"] = len(rtl_scan["ram_init_attrs"])
    summary["readmem_call_count"] = len(rtl_scan["readmem_calls"])
    summary["rom_like_module_count"] = len(rom_like_modules)

    if not has_init_intent and not rom_like_modules:
        summary["skip_reason"] = (
            "no RTL BRAM init declarations "
            "(ram_init_file / $readmemh / $readmemb) and no ROM/RAM-"
            "named modules"
        )
        return failures, warnings, summary

    quartus = _find_quartus_outputs(project)
    summary["fit_summary_count"] = len(quartus["fit_summary"])
    summary["map_rpt_count"] = len(quartus["map_rpt"])

    # WARN: RTL declares init but no Quartus build output
    if not quartus["fit_summary"] and not quartus["map_rpt"] \
            and not quartus["map_summary"]:
        warnings.append(
            "RTL declares BRAM/ROM init "
            f"({len(rtl_scan['ram_init_attrs'])} ram_init_file attr(s), "
            f"{len(rtl_scan['readmem_calls'])} $readmem call(s)) but no "
            "Quartus fit.summary / map.rpt found — build has not run yet"
        )
        return failures, warnings, summary

    # Step 2: Parse fit.summary for `Total memory bits: 0 /`
    for fs in quartus["fit_summary"]:
        parsed = _parse_total_memory_bits(fs)
        if parsed is None:
            continue
        used, total = parsed
        try:
            rel = fs.relative_to(project)
        except ValueError:
            rel = fs
        summary.setdefault("fit_summary_results", []).append({
            "file": str(rel),
            "used_bits": used,
            "total_bits": total,
        })
        if used == 0 and total > 0 and (has_init_intent or rom_like_modules):
            # Cite first RTL pattern as the offender
            offender = ""
            if rtl_scan["ram_init_attrs"]:
                f, ln, mif = rtl_scan["ram_init_attrs"][0]
                try:
                    f_rel = f.relative_to(project)
                except ValueError:
                    f_rel = f
                offender = (
                    f"  Module: {f_rel}:{ln}\n"
                    f"  Pattern: (* ram_init_file = \"{mif}\" *)"
                )
            elif rtl_scan["readmem_calls"]:
                f, ln, hexf = rtl_scan["readmem_calls"][0]
                try:
                    f_rel = f.relative_to(project)
                except ValueError:
                    f_rel = f
                offender = (
                    f"  Module: {f_rel}:{ln}\n"
                    f"  Pattern: $readmemh(\"{hexf}\", ...)"
                )
            elif rom_like_modules:
                f, why = rom_like_modules[0]
                try:
                    f_rel = f.relative_to(project)
                except ValueError:
                    f_rel = f
                offender = (
                    f"  Module: {f_rel} ({why} matches OTP/ROM/RAM "
                    "naming)\n"
                    f"  Pattern: register-array ROM (case-statement / "
                    "LUT-style) without altsyncram or $readmemh — Quartus "
                    "tried to lift it as BRAM, hit the MIF restriction, "
                    "and demoted it to zero-init logic."
                )
            failures.append(
                "FAIL — OTP_NOT_LOADED_ON_FPGA\n"
                f"{offender}\n"
                f"  Quartus output: {rel}\n"
                f"    Total memory bits: {used} / {total:,}\n"
                "\n"
                "  For MAX 10, the working pattern is altsyncram\n"
                "  Megafunction with init_file parameter. Vendor reference\n"
                "  uses ram128x8.v wrapper (see rig spec Layer 11).\n"
                "\n"
                "  Replace the inferred-BRAM register array with:\n"
                "    altsyncram #(\n"
                "      .operation_mode(\"ROM\"),\n"
                "      .init_file(\"X.mif\"),  // .mif file, NOT .hex\n"
                "      .init_file_layout(\"PORT_A\"),\n"
                "      .lpm_type(\"altsyncram\"),\n"
                "      ...\n"
                "    ) u_otp ( ... );\n"
                "\n"
                "  Plus: place X.mif in a directory referenced by\n"
                "  SEARCH_PATH in QSF, or use MISC_FILE assignment.\n"
                "\n"
                "  Alternative (vendor-proven): keep `$readmemh(\"X.hex\")`\n"
                "  AND add the three QSF pragmas that DISABLE Quartus auto-\n"
                "  RAM/ROM inference — `AUTO_RAM_RECOGNITION OFF`,\n"
                "  `AUTO_ROM_RECOGNITION OFF`,\n"
                "  `BLOCK_RAM_TO_MLAB_CELL_CONVERSION OFF`. Vendor's\n"
                "  ram128x8.v relies on this pattern."
            )

    # Step 3: Parse map.rpt / map.summary for verbatim warnings
    map_files = list(quartus["map_rpt"]) + list(quartus["map_summary"])
    for mp in map_files:
        warns = _scan_map_for_warnings(mp)
        if not warns:
            continue
        try:
            rel = mp.relative_to(project)
        except ValueError:
            rel = mp
        for rule, verbatim in warns:
            failures.append(
                "FAIL — OTP_NOT_LOADED_ON_FPGA\n"
                f"  Quartus map: {rel}\n"
                f"  Rule: {rule}\n"
                f"  Verbatim: {verbatim!r}\n"
                "\n"
                "  For MAX 10, the working pattern is altsyncram\n"
                "  Megafunction with init_file parameter. Vendor reference\n"
                "  uses ram128x8.v wrapper (see rig spec Layer 11).\n"
                "\n"
                "  Replace the inferred-BRAM register array with:\n"
                "    altsyncram #(\n"
                "      .operation_mode(\"ROM\"),\n"
                "      .init_file(\"X.mif\"),  // .mif file, NOT .hex\n"
                "      .init_file_layout(\"PORT_A\"),\n"
                "      .lpm_type(\"altsyncram\"),\n"
                "      ...\n"
                "    ) u_otp ( ... );\n"
                "\n"
                "  Plus: place X.mif in a directory referenced by\n"
                "  SEARCH_PATH in QSF, or use MISC_FILE assignment.\n"
                "\n"
                "  Alternative (vendor-proven): keep `$readmemh(\"X.hex\")`\n"
                "  AND add `AUTO_RAM_RECOGNITION OFF`,\n"
                "  `AUTO_ROM_RECOGNITION OFF`, and\n"
                "  `BLOCK_RAM_TO_MLAB_CELL_CONVERSION OFF` to QSF."
            )

    # Step 4: Cross-check QSF SEARCH_PATH covers $readmemh files
    qsf_files = _qsf_files(project)
    if qsf_files and rtl_scan["readmem_calls"]:
        sps = _qsf_search_paths(qsf_files)
        mfs = _qsf_misc_files(qsf_files)
        unreachable: List[Tuple[Path, int, str]] = []
        for f, ln, hexf in rtl_scan["readmem_calls"]:
            if not _file_reachable_via_qsf(project, hexf, sps, mfs):
                unreachable.append((f, ln, hexf))
        if unreachable:
            for f, ln, hexf in unreachable:
                try:
                    f_rel = f.relative_to(project)
                except ValueError:
                    f_rel = f
                failures.append(
                    "FAIL — BRAM_INIT_NOT_LOADED\n"
                    f"  Module: {f_rel}:{ln}\n"
                    f"  Pattern: $readmemh(\"{hexf}\", ...)\n"
                    f"  QSF: SEARCH_PATH does not cover the directory\n"
                    f"  containing {hexf!r}, and no MISC_FILE entry lists\n"
                    "  it. Quartus will not find the hex file at compile.\n"
                    "  Hint: add `set_global_assignment -name SEARCH_PATH\n"
                    "  <dir>` to QSF, where <dir> contains the hex file."
                )

    return failures, warnings, summary


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(
            "Usage: bram_init_file_actually_loaded_check.py "
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

    failures, warnings, summary = inspect(project)
    is_waived, rationale = _waived(project)

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({
            "program": "bram_init_file_actually_loaded_check",
            "passed": not failures,
            "summary": summary,
            "failures": failures,
            "warnings": warnings,
            "waived": is_waived,
        }, indent=2))

    if "skip_reason" in summary and not failures and not warnings:
        print(f"SKIP — {summary['skip_reason']}")
        return 0

    if not failures and not warnings:
        print("PASS — BRAM/ROM init declarations are loaded into bitstream")
        return 0

    if not failures and warnings:
        for w in warnings:
            print(f"WARN — {w}")
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(failures)} BRAM-init issue(s) "
            f"silenced by waivers.{WAIVER_KEY}: {rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(f"FAIL — {len(failures)} BRAM-init issue(s):")
    for f in failures:
        print(f)
        print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
