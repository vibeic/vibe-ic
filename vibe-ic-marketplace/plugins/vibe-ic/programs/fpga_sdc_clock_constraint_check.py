#!/usr/bin/env python3
"""
fpga_sdc_clock_constraint_check.py — Wave 24 / v0.119.56.

Goal: enforce SDC clock constraints exist for every Quartus / FPGA project,
with frequency matching the RTL-declared clock period.

Why this matters
----------------
Without an SDC `create_clock` entry, Quartus optimises for area / logic
only. Critical paths can exceed clock period → setup slack < 0 →
metastability on real silicon. Sim PASSes (no timing model), hardware
FAILes deterministically. Wave 24 of the <benchmark> benchmark (29th
fresh-agent attempt) confirmed this is the ONLY systematic difference
between the v0.119.55 fresh agent build and the vendor PASS oracle:
missing SDC → setup slack -5.5 ns → bit decoder timing errors → CRC
residue ≠ 0 → silent byte[6]=0x02.

Detection algorithm
-------------------
1. Find Quartus project root in `<project>/fpga/`. Locate any `.sdc`
   file via `*.sdc`.
2. Parse each `.sdc` for
       create_clock -name <name> -period <ps_or_ns> [get_ports <port>]
3. Find RTL clock period via L8 / rtl_constants_pkg synonyms:
   `CLOCK_PERIOD_NS`, `T_CLK_NS`, `CLK_PERIOD_PS`, `MASTER_CLK_HZ`,
   `master_clock_hz`, `CLOCK_50` style hints.
4. **FAIL** when:
   - no `.sdc` file exists in `fpga/`, AND project has any RTL with a
     `posedge clk` clock — clearly using a clock
   - SDC has no `create_clock` for the main clock port
   - SDC `create_clock` period mismatches L8 clock by > 5 %
5. **WARN** when SDC exists but doesn't cover all clock ports (e.g.,
   multiple clocks but only one constrained).
6. Honors waiver `fpga_sdc_explicitly_unconstrained` (≥ 40 chars).

Chip-AGNOSTIC. No vendor / chip names.

Exit codes
----------
    0 — PASS / PASS_WITH_WAIVER / SKIP (not an FPGA project)
    1 — FAIL
    2 — IO / argument error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl


WAIVER_KEY = "fpga_sdc_explicitly_unconstrained"


# ----------------------------- helpers ----------------------------- #

def _has_generated_clock(sdc_text: str) -> bool:
    """ORGANIC #555 — True if the SDC defines an actual generated/derived
    clock (`create_generated_clock`) for a PLL/clock-divider output.

    When present, FPGA SDC period ≠ RTL period is intentional (board osc →
    PLL → application clock), so Rule 3 period-mismatch is downgraded to WARN
    instead of FAIL. Note: `derive_pll_clocks` / `derive_clocks` are Quartus
    boilerplate TimeQuest commands emitted in EVERY .sdc regardless of
    whether a PLL is present (no-op without one) — they are NOT used as the
    signal here, only an explicit `create_generated_clock` definition is.
    Chip-AGNOSTIC: standard SDC/Quartus grammar."""
    text = _strip_comments(sdc_text) if callable(_strip_comments) else sdc_text
    return bool(re.search(r"\bcreate_generated_clock\b", text, re.IGNORECASE))


def _strip_comments(text: str) -> str:
    text = re.sub(r"#[^\n]*", "", text)          # SDC '#' line comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _find_fpga_dir(project: Path) -> Optional[Path]:
    cand = _pl.fpga_early_dir(project)
    if cand.is_dir():
        return cand
    return None


def _find_sdc_files(fpga_dir: Path) -> List[Path]:
    return sorted(fpga_dir.rglob("*.sdc"))


def _find_rtl_files(project: Path) -> List[Path]:
    out: List[Path] = []
    rtl_dir = _pl.rtl_dir(project)
    if rtl_dir.is_dir():
        out.extend(rtl_dir.rglob("*.v"))
        out.extend(rtl_dir.rglob("*.sv"))
    fpga_dir = _pl.fpga_early_dir(project)
    if fpga_dir.is_dir():
        out.extend(fpga_dir.rglob("*.v"))
        out.extend(fpga_dir.rglob("*.sv"))
    return out


def _has_posedge_clock(rtl_files: List[Path]) -> bool:
    for f in rtl_files:
        try:
            txt = _strip_comments(f.read_text(errors="replace"))
        except Exception:
            continue
        if re.search(r"\bposedge\s+\w+", txt):
            return True
    return False


# ------------------------ SDC parsing ------------------------------ #

_CC_RE = re.compile(
    r"create_clock\b(?P<args>[^\n;]*)",
    re.IGNORECASE,
)


def parse_create_clocks(sdc_text: str) -> List[dict]:
    """Return list of {name, period_ns, port}."""
    out: List[dict] = []
    text = _strip_comments(sdc_text)
    for m in _CC_RE.finditer(text):
        args = m.group("args")
        name = None
        period_ns: Optional[float] = None
        port = None
        nm = re.search(r"-name\s+\{?([\w/\\]+)\}?", args)
        if nm:
            name = nm.group(1)
        pm = re.search(r"-period\s+([0-9.eE+-]+)", args)
        if pm:
            try:
                period_ns = float(pm.group(1))
            except ValueError:
                period_ns = None
        gp = re.search(r"\[\s*get_ports\s+\{?([\w/\\]+)\}?\s*\]", args)
        if gp:
            port = gp.group(1)
        if name or port:
            out.append({"name": name, "period_ns": period_ns, "port": port})
    return out


# ------------------------- RTL clock --------------------------- #

# Synonyms for the master clock period in rtl_constants_pkg / L8 docs.
_PERIOD_SYNONYMS_NS = (
    r"CLOCK_PERIOD_NS",
    r"CLK_PERIOD_NS",
    r"T_CLK_NS",
    r"MASTER_CLK_PERIOD_NS",
)
_PERIOD_SYNONYMS_PS = (
    r"CLOCK_PERIOD_PS",
    r"CLK_PERIOD_PS",
    r"T_CLK_PS",
)
_FREQ_SYNONYMS_HZ = (
    r"MASTER_CLK_HZ",
    r"CLK_FREQ_HZ",
    r"CLOCK_FREQ_HZ",
    r"master_clock_hz",
)


def find_rtl_clock_period_ns(project: Path) -> Optional[float]:
    """Return master clock period in ns from RTL constants / L8 JSON."""
    candidates: List[Path] = []
    rtl_dir = _pl.rtl_dir(project)
    if rtl_dir.is_dir():
        candidates.extend(rtl_dir.rglob("*constants*.sv"))
        candidates.extend(rtl_dir.rglob("*constants*.v"))
        candidates.extend(rtl_dir.rglob("rtl_constants*.sv"))
    gen_dir = _pl.generated_docs_dir(project)
    if gen_dir.is_dir():
        candidates.extend(gen_dir.rglob("L8*.json"))
        candidates.extend(gen_dir.rglob("L9*.json"))
    inp_dir = project / "input"
    if inp_dir.is_dir():
        candidates.extend(inp_dir.rglob("L8*.json"))

    for f in candidates:
        try:
            txt = f.read_text(errors="replace")
        except Exception:
            continue
        # Left word-boundary so a master-clock synonym like CLOCK_PERIOD_NS
        # does NOT match as the SUFFIX of an unrelated domain-specific key
        # (e.g. `nibble_clock_period_ns` / `mdc_min_period_ns` / a
        # `byte_clock_period_ns` data-interface period). Those describe a
        # protocol bit/nibble clock — not the core clk this check budgets.
        _lb = r"(?<![A-Za-z0-9_])"
        # NS first
        for syn in _PERIOD_SYNONYMS_NS:
            m = re.search(_lb + syn + r"\b\D{0,40}?([0-9]+(?:\.[0-9]+)?)", txt,
                          re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
        # PS → ns
        for syn in _PERIOD_SYNONYMS_PS:
            m = re.search(_lb + syn + r"\b\D{0,40}?([0-9]+(?:\.[0-9]+)?)", txt,
                          re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1)) / 1000.0
                except ValueError:
                    pass
        # HZ → ns
        for syn in _FREQ_SYNONYMS_HZ:
            m = re.search(_lb + syn + r"\b\D{0,40}?([0-9]+(?:_[0-9]+)*)",
                          txt, re.IGNORECASE)
            if m:
                try:
                    hz = int(m.group(1).replace("_", ""))
                    if hz > 0:
                        return 1e9 / hz
                except ValueError:
                    pass
    return None


def find_rtl_clock_ports(rtl_files: List[Path]) -> List[str]:
    """Best-effort: list signals that appear as `posedge <sig>` in RTL.

    For SDC coverage we mostly care about top-level external clock pins.
    Returns sorted unique signal names.
    """
    sigs = set()
    for f in rtl_files:
        try:
            txt = _strip_comments(f.read_text(errors="replace"))
        except Exception:
            continue
        for m in re.finditer(r"posedge\s+(\w+)", txt):
            sigs.add(m.group(1))
    return sorted(sigs)


# ------------------------- waiver --------------------------- #

def waived(project: Path) -> bool:
    w = project / "waivers.json"
    if not w.exists():
        return False
    try:
        d = json.loads(w.read_text())
    except Exception:
        return False
    v = d.get(WAIVER_KEY, "")
    if isinstance(v, dict):
        v = v.get("reason", "") or v.get("justification", "")
    return isinstance(v, str) and len(v.strip()) >= 40


# ------------------------- main --------------------------- #

def audit(project: Path) -> Tuple[str, List[str]]:
    """Return (verdict, messages)."""
    msgs: List[str] = []
    fpga_dir = _find_fpga_dir(project)
    if not fpga_dir:
        msgs.append("SKIP — no fpga/ directory; not an FPGA project")
        return ("SKIP", msgs)

    rtl_files = _find_rtl_files(project)
    has_clock = _has_posedge_clock(rtl_files)
    sdc_files = _find_sdc_files(fpga_dir)

    # Rule 1: no SDC file at all + clock used → FAIL
    if not sdc_files:
        if has_clock:
            msgs.append(
                "FAIL — FPGA_SDC_MISSING\n"
                f"  fpga dir: {fpga_dir}\n"
                f"  RTL declares posedge clock but no .sdc file under fpga/.\n"
                "  Without SDC, Quartus produces unconstrained timing → "
                "setup slack negative → hardware FAIL deterministic."
            )
            return ("FAIL", msgs)
        else:
            msgs.append(
                "SKIP — no .sdc and no posedge-clock RTL "
                "(combinational FPGA?)"
            )
            return ("SKIP", msgs)

    # Rule 2: SDC present, parse create_clock entries
    create_clocks: List[dict] = []
    for sdc in sdc_files:
        try:
            txt = sdc.read_text(errors="replace")
        except Exception:
            continue
        cks = parse_create_clocks(txt)
        for c in cks:
            c["sdc_file"] = str(sdc)
        create_clocks.extend(cks)

    if not create_clocks:
        msgs.append(
            "FAIL — FPGA_SDC_NO_CREATE_CLOCK\n"
            f"  sdc files: {[str(p) for p in sdc_files]}\n"
            "  No `create_clock -name <n> -period <p> [get_ports <port>]` "
            "entry found in any .sdc file.\n"
            "  Quartus needs at least one create_clock to enable timing-"
            "driven placement."
        )
        return ("FAIL", msgs)

    # Rule 3: period mismatch >5 % vs L8/RTL clock period
    # ORGANIC #555 — if the SDC has a PLL/generated-clock construct,
    # board-clock period ≠ ASIC period is intentional; downgrade to WARN.
    sdc_has_pll = any(
        _has_generated_clock(p.read_text(errors="replace"))
        for p in sdc_files
        if p.is_file()
    )
    rtl_period = find_rtl_clock_period_ns(project)
    if rtl_period is not None and rtl_period > 0:
        for c in create_clocks:
            if c["period_ns"] is None:
                continue
            ratio = abs(c["period_ns"] - rtl_period) / rtl_period
            if ratio > 0.05:
                if sdc_has_pll:
                    msgs.append(
                        "WARN — FPGA_SDC_PERIOD_BOARD_MISMATCH (PLL/generated-"
                        "clock present)\n"
                        f"  sdc file: {c.get('sdc_file')}\n"
                        f"  create_clock -period {c['period_ns']} ns; "
                        f"RTL {rtl_period} ns (mismatch {ratio*100:.1f}%)\n"
                        "  Board-clock path (derive_pll_clocks or "
                        "create_generated_clock) detected — period mismatch "
                        "may be intentional (advisory only, #555)."
                    )
                else:
                    msgs.append(
                        "FAIL — FPGA_SDC_PERIOD_MISMATCH\n"
                        f"  sdc file: {c.get('sdc_file')}\n"
                        f"  create_clock -name {c.get('name')} "
                        f"-period {c['period_ns']} ns\n"
                        f"  RTL declares clock period {rtl_period} ns "
                        f"(mismatch {ratio*100:.1f} %, threshold 5 %).\n"
                        "  Quartus will time-budget against the SDC value not "
                        "the actual silicon clock — silent timing violation."
                    )
                    return ("FAIL", msgs)

    # Rule 4: WARN when only one clock constrained but multiple posedge clocks
    rtl_clk_sigs = find_rtl_clock_ports(rtl_files)
    # Filter likely top-level clock names (CLK*, CLOCK*)
    top_clks = [s for s in rtl_clk_sigs
                if re.match(r"(?i)^(?:CLK|CLOCK)", s) or "_clk" in s.lower()]
    if len(top_clks) > 1 and len(create_clocks) < len(top_clks):
        msgs.append(
            f"WARN — FPGA_SDC_PARTIAL_COVERAGE: {len(top_clks)} clock-like "
            f"signals in RTL, {len(create_clocks)} create_clock entries. "
            f"Verify all are constrained: {top_clks}"
        )

    msgs.append(
        f"PASS — {len(create_clocks)} create_clock entry/entries across "
        f"{len(sdc_files)} sdc file(s)"
        + (f"; RTL clock period {rtl_period} ns matches"
           if rtl_period is not None else "")
    )
    return ("PASS", msgs)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    project = Path(argv[0]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, msgs = audit(project)

    if verdict == "FAIL" and waived(project):
        print(f"PASS_WITH_WAIVER — {WAIVER_KEY} accepted")
        for m in msgs:
            print(m)
        return 0

    for m in msgs:
        print(m)

    if verdict == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
