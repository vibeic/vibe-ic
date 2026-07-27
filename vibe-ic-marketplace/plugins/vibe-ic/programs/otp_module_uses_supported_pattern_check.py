#!/usr/bin/env python3
"""otp_module_uses_supported_pattern_check.py — Wave 21 (v0.119.53).

Companion to `bram_init_file_actually_loaded_check.py` (Wave 16).
Targets a NARROWER class than the Wave 16 gate: any module whose
filename / module name suggests OTP / ROM / RAM / MEM / LUT and that
contains a register-array `reg [W-1:0] mem [0:DEPTH-1]` or a
case-statement LUT.

Background
==========
The 25th fresh-agent benchmark (v0.119.51) replaced the Wave 16
explicit `(* ram_init_file *)` pattern with a `case (addr) ... endcase`
LUT-style ROM driven by a SystemVerilog ``include` of literal entries.
Quartus STILL emitted

    Info (276013): RAM logic "otp_mem:u_otp|Ram0" is uninferred
                   because MIF is not supported for the selected family

and the SOF compiled with `Total memory bits: 0`. OTP read out as
zeros on real silicon, host-tester padded byte[6]=0x02 → FAIL.

The 26th fresh-agent benchmark (v0.119.52) used the Wave-20 `$readmemh`
+ "3 OFF pragmas" recipe and ALSO failed: those AUTO_*_RECOGNITION OFF
+ BLOCK_RAM_TO_MLAB_CELL_CONVERSION OFF assignments demote Quartus's
inference engine, and the ROM compiles as a LUT-flop array of zeros
(`Total memory bits: 0`, Stuck-at-GND warnings on the data port).

The two patterns that actually compile ROM-bits on MAX 10 are:

    Pattern A — explicit `altsyncram` Megafunction with a `.init_file`
                parameter pointing at an `.mif` (or `.hex`) reachable
                via QSF SEARCH_PATH / MISC_FILE.
    Pattern B — vendor IP wrapper (e.g. Mentor Graphics `RAM_IP`) that
                takes `INIT_FILE_NAME` + `INIT_FILE_FORMAT_HEX`.

Pattern A is empirically verified at v0.119.52 26th attempt with
`Total memory bits = 512` and is recommended for fresh-agents on
Quartus.

Detection
=========
1. Walk `<project>/rtl/` and find every file with a filename or
   declared module name matching `otp` / `rom` / `mem` / `lut` /
   `bram` / `init_table` / `lookup`.
2. For each, check that the body looks memory-shaped: either a
   2-D register array, or a case-statement with ≥4 constant-arm
   assignments.
3. For modules that pass (1)+(2) check whether the body uses one of
   the supported patterns:
     a. Pattern A: `altsyncram` Megafunction instantiation with an
        `.init_file("<file>")` parameter binding (PASS), AND the
        referenced init file is reachable via QSF SEARCH_PATH /
        MISC_FILE (additional check; FAIL when the .init_file string
        cannot be located on disk).
     b. Pattern B: instantiation of a vendor `RAM_IP` (or similar)
        wrapper carrying an `INIT_FILE_NAME` parameter (PASS).
4. FAIL on MAX 10 family target (auto-detect from QSF
   `set_global_assignment -name FAMILY "MAX 10 ..."`) when neither
   Pattern A nor Pattern B is present. Plain `$readmemh` register-
   array is NOT enough on MAX 10 — Quartus may demote it.
5. NEGATIVE check (Wave 21): if family is MAX 10 AND the QSF contains
   any of `AUTO_RAM_RECOGNITION OFF`, `AUTO_ROM_RECOGNITION OFF`, or
   `BLOCK_RAM_TO_MLAB_CELL_CONVERSION OFF`, FAIL with the verbatim
   warning naming the offending assignment(s) — that triple was the
   Wave-20 wrong recipe, empirically verified to compile zero memory
   bits.
6. SKIP when family is not MAX 10 (Cyclone V / Stratix / Arria etc.
   accept the `(* ram_init_file *)` attribute or other auto-inference
   pathways), or when no QSF is present (ASIC project / pre-FPGA
   stage), or when no OTP/ROM-shaped module is present.
7. Honors waiver `otp_pattern_intentional_logic_lut` (≥40 chars) for
   genuinely small OTPs / lookup tables that are intentional logic
   LUTs (e.g. < 16 entries, decode-only).

Chip-AGNOSTIC. The synonym list (otp/rom/mem/lut/bram/init_table/
lookup) is generic memory naming; family detection is generic to any
QSF that declares FAMILY; Pattern B vendor-IP detection just needs
`INIT_FILE_NAME` keyword (Mentor / Lattice / Synopsys all use that).

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

WAIVER_KEY = "otp_pattern_intentional_logic_lut"
WAIVER_MIN_LEN = 40

_ROM_LIKE_NAME_RE = re.compile(
    r"\b(?:otp|rom|ram|mem|lut|bram|init_table|lookup)\w*\b",
    re.IGNORECASE,
)

_REG_ARRAY_RE = re.compile(
    r"\b(?:reg|logic|wire)\s*(?:\[[^\]]+\])?\s*(\w+)\s*"
    r"\[\s*(?:0\s*:\s*\d+|\d+\s*:\s*0)\s*\]\s*;",
)
_CASE_ROM_RE = re.compile(
    r"\bcase\s*\([^)]+\)([\s\S]{0,8000}?)\bendcase\b",
    re.IGNORECASE,
)
_CASE_ARM_LITERAL_RE = re.compile(
    r"\b\d+'(?:h|d|b|o)\w+\s*:",
    re.IGNORECASE,
)

_ALTSYNCRAM_KEYWORD_RE = re.compile(r"\baltsyncram\b", re.IGNORECASE)
_INIT_FILE_PARAM_RE = re.compile(
    r"\.init_file\s*\(\s*\"([^\"]+)\"\s*\)",
    re.IGNORECASE,
)
_ALTSYNCRAM_DEFPARAM_RE = re.compile(
    r"\bdefparam\b[^;]*altsyncram[^;]*\.init_file\s*=\s*\"([^\"]+)\"",
    re.IGNORECASE,
)
# Pattern B: vendor IP wrapper — Mentor Graphics RAM_IP, Lattice
# pmi_ram_*, Synopsys DesignWare DW_*, etc. all expose an
# INIT_FILE_NAME parameter binding. Match the parameter string + a
# quoted file name, optionally with INIT_FILE_FORMAT_HEX nearby.
_VENDOR_INIT_FILE_NAME_RE = re.compile(
    r"\.INIT_FILE_NAME\s*\(\s*\"([^\"]+)\"\s*\)",
    re.IGNORECASE,
)
_VENDOR_INIT_FILE_DEFPARAM_RE = re.compile(
    r"\bdefparam\b[^;]*\.INIT_FILE_NAME\s*=\s*\"([^\"]+)\"",
    re.IGNORECASE,
)
_READMEM_RE = re.compile(r"\$readmem(?:h|b)\s*\(", re.IGNORECASE)

_QSF_FAMILY_RE = re.compile(
    r"set_global_assignment\s+-name\s+FAMILY\s+\"?([^\"\n]+)\"?",
    re.IGNORECASE,
)
_QSF_SEARCH_PATH_RE = re.compile(
    r"set_global_assignment\s+-name\s+SEARCH_PATH\s+\"?([^\"\n]+)\"?",
    re.IGNORECASE,
)
_QSF_MISC_FILE_RE = re.compile(
    r"set_global_assignment\s+-name\s+MISC_FILE\s+\"?([^\"\n]+)\"?",
    re.IGNORECASE,
)

# Wave 21: forbidden Wave-20 "3 OFF pragmas" recipe on MAX 10. Any of
# these alone is enough to demote ROM inference into LUT-flop stuck-at-
# zero on MAX 10.
_FORBIDDEN_QSF_PRAGMAS = (
    "AUTO_RAM_RECOGNITION",
    "AUTO_ROM_RECOGNITION",
    "BLOCK_RAM_TO_MLAB_CELL_CONVERSION",
)
_QSF_OFF_RE = re.compile(
    r"set_global_assignment\s+-name\s+(\w+)\s+OFF\b",
    re.IGNORECASE,
)

# MAX 10 needs the strict pattern. Other families generally accept
# auto-inference + (* ram_init_file *) attribute.
_MAX10_FAMILY_RE = re.compile(r"\bMAX\s*10\b", re.IGNORECASE)


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


def _find_qsf_files(project: Path) -> List[Path]:
    fpga_dir = _pl.fpga_early_dir(project)
    if not fpga_dir.exists():
        return []
    return sorted(fpga_dir.rglob("*.qsf"))


def _detect_family(qsf_files: List[Path]) -> Optional[str]:
    for qsf in qsf_files:
        try:
            text = qsf.read_text(errors="ignore")
        except OSError:
            continue
        m = _QSF_FAMILY_RE.search(text)
        if m:
            return m.group(1).strip()
    return None


def _qsf_combined_text(qsf_files: List[Path]) -> str:
    chunks: List[str] = []
    for qsf in qsf_files:
        try:
            chunks.append(qsf.read_text(errors="ignore"))
        except OSError:
            continue
    return "\n".join(chunks)


def _detect_forbidden_qsf_pragmas(qsf_files: List[Path]) -> List[str]:
    """Wave 21 — collect any of the 3 OFF pragmas present in QSF."""
    text = _qsf_combined_text(qsf_files)
    found: List[str] = []
    for m in _QSF_OFF_RE.finditer(text):
        name = m.group(1).upper()
        if name in _FORBIDDEN_QSF_PRAGMAS and name not in found:
            found.append(name)
    return found


def _qsf_init_file_search_dirs(qsf_files: List[Path]) -> List[Path]:
    """Resolve QSF SEARCH_PATH + MISC_FILE entries to filesystem paths.

    Returns the list of directories (or single MISC_FILE paths) where
    altsyncram .init_file references should be reachable. Paths in QSF
    are typically relative to the QSF's own directory.
    """
    dirs: List[Path] = []
    for qsf in qsf_files:
        try:
            text = qsf.read_text(errors="ignore")
        except OSError:
            continue
        base = qsf.parent
        for m in _QSF_SEARCH_PATH_RE.finditer(text):
            cand = (base / m.group(1).strip()).resolve()
            if cand.is_dir():
                dirs.append(cand)
        for m in _QSF_MISC_FILE_RE.finditer(text):
            cand = (base / m.group(1).strip()).resolve()
            # MISC_FILE points at a single file — its parent dir is the
            # search location, but the exact filename match also helps.
            if cand.exists():
                dirs.append(cand.parent)
                # Also record the file path itself (we'll match by
                # basename below).
                dirs.append(cand)
    # de-dup
    seen = set()
    out: List[Path] = []
    for d in dirs:
        if str(d) in seen:
            continue
        seen.add(str(d))
        out.append(d)
    return out


def _init_file_reachable(
    init_file: str, search_locations: List[Path], project: Path,
) -> bool:
    """Check if an `.init_file("X.mif")` value can be located via QSF
    SEARCH_PATH / MISC_FILE entries, or under <project>/rtl."""
    target = Path(init_file).name
    # Direct: any search_locations entry that IS the file (MISC_FILE
    # mode) or contains the file by basename.
    for loc in search_locations:
        if loc.is_file() and loc.name == target:
            return True
        if loc.is_dir():
            for cand in loc.rglob(target):
                if cand.is_file():
                    return True
    # Fallback: scan project/rtl/ for the basename.
    rtl = _pl.rtl_dir(project)
    if rtl.is_dir():
        for cand in rtl.rglob(target):
            if cand.is_file():
                return True
    return False


def _module_names(text_no_cmt: str) -> List[str]:
    return re.findall(r"\bmodule\s+(\w+)\b", text_no_cmt)


def _extract_altsyncram_init_files(text_no_cmt: str) -> List[str]:
    """Extract every .init_file("X") binding when an altsyncram keyword
    appears nearby (or anywhere) in the text. Returns the list of init
    filenames (typically just one)."""
    if not _ALTSYNCRAM_KEYWORD_RE.search(text_no_cmt):
        return []
    out = [m.group(1) for m in _INIT_FILE_PARAM_RE.finditer(text_no_cmt)]
    out.extend(m.group(1) for m in _ALTSYNCRAM_DEFPARAM_RE.finditer(text_no_cmt))
    return out


def _extract_vendor_init_file_names(text_no_cmt: str) -> List[str]:
    """Pattern B: vendor IP wrapper carrying INIT_FILE_NAME."""
    out = [m.group(1) for m in _VENDOR_INIT_FILE_NAME_RE.finditer(text_no_cmt)]
    out.extend(
        m.group(1)
        for m in _VENDOR_INIT_FILE_DEFPARAM_RE.finditer(text_no_cmt)
    )
    return out


def _waived(project: Path) -> Tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text(errors="ignore"))
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
    failures: List[str] = []
    warnings: List[str] = []
    summary: dict = {}

    rtl_files = _find_rtl_files(project)
    if not rtl_files:
        summary["skip_reason"] = "no rtl/ directory"
        return failures, warnings, summary

    qsf_files = _find_qsf_files(project)
    if not qsf_files:
        summary["skip_reason"] = "no fpga/*.qsf — likely ASIC or pre-FPGA"
        return failures, warnings, summary

    family = _detect_family(qsf_files)
    summary["family"] = family or ""
    is_max10 = bool(family and _MAX10_FAMILY_RE.search(family))
    if not is_max10:
        summary["skip_reason"] = (
            f"FPGA family {family!r} is not MAX 10 — gate is MAX-10-"
            "specific (other families honour ram_init_file attribute)"
        )
        return failures, warnings, summary

    # Wave 21 NEGATIVE check: 3 OFF pragmas on MAX 10 == Wave-20 wrong
    # recipe → empirically demotes ROM inference to LUT-flop zero.
    forbidden_pragmas = _detect_forbidden_qsf_pragmas(qsf_files)
    summary["forbidden_qsf_pragmas"] = forbidden_pragmas
    if forbidden_pragmas:
        failures.append(
            "FAIL — WAVE20_WRONG_RECIPE_3_OFF_PRAGMAS_ON_MAX10\n"
            f"  Family: {family}\n"
            "  QSF contains the Wave-20 prescribed pragmas:\n"
            + "".join(
                f"    set_global_assignment -name {p} OFF\n"
                for p in forbidden_pragmas
            )
            + "  This combination was empirically verified at v0.119.52\n"
            "  26th-attempt to DEMOTE ROM inference into LUT-flop\n"
            "  stuck-at-zero on MAX 10 (Total memory bits: 0,\n"
            "  Stuck-at-GND warnings on the ROM data port).\n"
            "\n"
            "  REMOVE all three assignments from QSF. Use Pattern A\n"
            "  instead (altsyncram Megafunction with .init_file)."
        )

    rom_modules: List[Tuple[Path, str]] = []
    for f in rtl_files:
        try:
            raw = f.read_text(errors="ignore")
        except OSError:
            continue
        text = _strip_comments(raw)
        # Filename hint OR module-name hint
        name_hits = bool(_ROM_LIKE_NAME_RE.search(f.stem))
        mod_hit = ""
        for mod in _module_names(text):
            if _ROM_LIKE_NAME_RE.search(mod):
                mod_hit = mod
                break
        if not (name_hits or mod_hit):
            continue
        # Body must look memory-shaped: 2-D register array OR case ROM
        # OR direct altsyncram instantiation OR vendor IP wrapper.
        looks_memory = bool(_REG_ARRAY_RE.search(text))
        if not looks_memory:
            for cm in _CASE_ROM_RE.finditer(text):
                if len(_CASE_ARM_LITERAL_RE.findall(cm.group(1))) >= 4:
                    looks_memory = True
                    break
        if not looks_memory and _ALTSYNCRAM_KEYWORD_RE.search(text):
            # An altsyncram-only wrapper (no register array, no case)
            # still counts as a ROM module and should be inspected.
            looks_memory = True
        if not looks_memory and _VENDOR_INIT_FILE_NAME_RE.search(text):
            looks_memory = True
        if not looks_memory:
            # .svh include-style ROMs.
            inc_hits = re.findall(
                r"`include\s+\"([^\"]+\.svh?)\"", text)
            for inc in inc_hits:
                inc_path = (f.parent / inc).resolve()
                if not inc_path.is_file():
                    for cand in (f.parent).rglob(Path(inc).name):
                        inc_path = cand
                        break
                if inc_path.is_file():
                    try:
                        inc_text = inc_path.read_text(errors="ignore")
                    except OSError:
                        continue
                    if len(_CASE_ARM_LITERAL_RE.findall(inc_text)) >= 4:
                        looks_memory = True
                        break
        if not looks_memory:
            continue
        why = mod_hit if mod_hit else f.stem
        rom_modules.append((f, why))

    summary["rom_module_count"] = len(rom_modules)
    if not rom_modules:
        if not failures:
            summary["skip_reason"] = (
                "no module/file with OTP/ROM/MEM/LUT name + memory-"
                "shaped body"
            )
        return failures, warnings, summary

    search_locations = _qsf_init_file_search_dirs(qsf_files)
    summary["qsf_search_locations"] = [str(p) for p in search_locations]

    for f, why in rom_modules:
        try:
            raw = f.read_text(errors="ignore")
        except OSError:
            continue
        text = _strip_comments(raw)
        try:
            f_rel = f.relative_to(project)
        except ValueError:
            f_rel = f

        # Pattern A check
        altsync_inits = _extract_altsyncram_init_files(text)
        # Pattern B check
        vendor_inits = _extract_vendor_init_file_names(text)

        if altsync_inits:
            # Pattern A — verify init_file reachable.
            unreachable: List[str] = []
            for init_name in altsync_inits:
                if not _init_file_reachable(
                        init_name, search_locations, project):
                    unreachable.append(init_name)
            if unreachable:
                failures.append(
                    "FAIL — ALTSYNCRAM_INIT_FILE_UNREACHABLE\n"
                    f"  Module: {f_rel} ({why})\n"
                    "  Pattern A altsyncram .init_file references the\n"
                    f"  following file(s) but they are not reachable\n"
                    "  via QSF SEARCH_PATH / MISC_FILE / project rtl/:\n"
                    + "".join(f"    - {n}\n" for n in unreachable)
                    + "  Add to QSF:\n"
                    "    set_global_assignment -name SEARCH_PATH ../rtl\n"
                    "    set_global_assignment -name MISC_FILE "
                    "../rtl/<file>"
                )
                continue
            summary.setdefault("module_results", []).append({
                "file": str(f_rel),
                "module_or_file": why,
                "supported_pattern":
                    f"Pattern A: altsyncram + .init_file({altsync_inits[0]})",
            })
            continue

        if _ALTSYNCRAM_KEYWORD_RE.search(text):
            # altsyncram present but NO .init_file param at all
            failures.append(
                "FAIL — ALTSYNCRAM_MISSING_INIT_FILE\n"
                f"  Module: {f_rel} ({why})\n"
                "  altsyncram instantiation found but no\n"
                "  .init_file(\"X.mif\") parameter binding. ROM will\n"
                "  compile to zero-initialised BRAM.\n"
                "\n"
                "  Add `.init_file(\"<file>.mif\"),` to the parameter\n"
                "  list and ensure the .mif is reachable via QSF\n"
                "  SEARCH_PATH / MISC_FILE."
            )
            continue

        if vendor_inits:
            # Pattern B — vendor IP module is good as-is. We do not
            # check reachability here because vendor-IP search paths
            # are tool-specific (Mentor / Lattice / Synopsys differ).
            summary.setdefault("module_results", []).append({
                "file": str(f_rel),
                "module_or_file": why,
                "supported_pattern":
                    f"Pattern B: vendor RAM_IP + INIT_FILE_NAME"
                    f"({vendor_inits[0]})",
            })
            continue

        # Neither Pattern A nor Pattern B → FAIL.
        # Wave 21: $readmemh alone is NOT sufficient on MAX 10.
        has_readmem = bool(_READMEM_RE.search(text))
        msg = (
            "FAIL — OTP_PATTERN_UNSUPPORTED_ON_MAX10\n"
            f"  Module: {f_rel} ({why})\n"
            f"  Family: {family}\n"
        )
        if has_readmem:
            msg += (
                "  $readmemh present but no altsyncram / vendor RAM_IP\n"
                "  wrapper. On MAX 10 the inference engine often\n"
                "  demotes a `reg [W-1:0] mem[0:N-1]` + initial\n"
                "  $readmemh into LUT-flops with Total memory bits=0,\n"
                "  especially when AUTO_*_RECOGNITION is left in default\n"
                "  state. Empirically verified at v0.119.52 26th-attempt.\n"
            )
        else:
            msg += (
                "  No `altsyncram` instantiation, no vendor `RAM_IP`\n"
                "  wrapper, no `$readmemh` / `$readmemb` task call. On\n"
                "  MAX 10 this typically compiles to BRAM-shaped logic\n"
                "  that gets demoted to zero-init LUTs (Total memory\n"
                "  bits: 0).\n"
            )
        msg += (
            "\n"
            "  RECOMMENDED — Pattern A: altsyncram Megafunction with\n"
            "  init_file pointing at a .mif (or .hex). Empirically\n"
            "  verified at v0.119.52 26th attempt with Total memory\n"
            "  bits = 512:\n"
            "    altsyncram #(\n"
            "      .operation_mode(\"ROM\"),\n"
            "      .init_file(\"X.mif\"),\n"
            "      .init_file_layout(\"PORT_A\"),\n"
            "      .lpm_type(\"altsyncram\"),\n"
            "      .width_a(8),\n"
            "      .widthad_a(7),\n"
            "      .numwords_a(128),\n"
            "      .outdata_reg_a(\"UNREGISTERED\")\n"
            "    ) u_otp (\n"
            "      .clock0    (clk),\n"
            "      .address_a (addr),\n"
            "      .q_a       (dout)\n"
            "    );\n"
            "  Plus QSF:\n"
            "    set_global_assignment -name SEARCH_PATH ../rtl\n"
            "    set_global_assignment -name MISC_FILE ../rtl/X.mif\n"
            "  (Do NOT set AUTO_RAM_RECOGNITION OFF / "
            "AUTO_ROM_RECOGNITION\n"
            "  OFF / BLOCK_RAM_TO_MLAB_CELL_CONVERSION OFF — those\n"
            "  pragmas demote inference and cause ROM stuck-at-zero,\n"
            "  Wave-20 wrong recipe.)\n"
            "\n"
            "  Alternative — Pattern B: vendor `RAM_IP` IP wrapper with\n"
            "  INIT_FILE_NAME parameter (Mentor Graphics PreciseIP /\n"
            "  similar). Requires vendor toolchain to regenerate the\n"
            "  IP module, fresh-agent typically can't reproduce."
        )
        failures.append(msg)

    return failures, warnings, summary


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(
            "Usage: otp_module_uses_supported_pattern_check.py "
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
            "program": "otp_module_uses_supported_pattern_check",
            "passed": not failures,
            "summary": summary,
            "failures": failures,
            "warnings": warnings,
            "waived": is_waived,
        }, indent=2))

    if "skip_reason" in summary and not failures:
        print(f"SKIP — {summary['skip_reason']}")
        return 0

    if not failures:
        print(
            f"PASS — {summary.get('rom_module_count', 0)} OTP/ROM "
            "module(s) use Pattern A (altsyncram + init_file) or "
            "Pattern B (vendor RAM_IP):"
        )
        for r in summary.get("module_results", []):
            print(f"  • {r['file']} ({r['module_or_file']}): "
                  f"{r['supported_pattern']}")
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(failures)} unsupported-pattern "
            f"issue(s) silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(f"FAIL — {len(failures)} OTP module pattern issue(s):")
    for f in failures:
        print(f)
        print()
    print(
        "Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
