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


# ---------------- board-oscillator frequency, from the port name ---------- #

# Board top-level clock ports conventionally spell the oscillator's frequency
# in the port name (CLOCK_50, CLK_100MHZ, SYSCLK_125, OSC_32KHZ). That name is
# a statement about the PHYSICAL part soldered to the board, and no SDC can
# change it. Chip-AGNOSTIC: this is board-file naming convention, not a
# vendor / chip / SKU token.
_PORT_FREQ_UNIT_RE = re.compile(
    r"(?i)^(?:CLK|CLOCK|SYSCLK|OSC|XTAL)[A-Z0-9]*?_?(\d+(?:\.\d+)?)\s*(M|K)HZ$")
_PORT_FREQ_BARE_RE = re.compile(
    r"(?i)^(?:CLK|CLOCK|SYSCLK|OSC|XTAL)_(\d+)$")

# A bare trailing number is only read as MHz inside a plausible oscillator
# band; below it the token is far more likely to be an index (clk_0, clk_2).
_BARE_MHZ_MIN, _BARE_MHZ_MAX = 10, 1000


def port_name_declared_freq_mhz(port: str) -> Optional[Tuple[float, str]]:
    """The oscillator frequency a board clock PORT NAME states, in MHz, with
    the reading used. ``None`` when the name states nothing.

    Deliberately conservative: an explicit unit is always honoured; a bare
    trailing number is honoured only inside a plausible oscillator band, so a
    port index (``clk_0``, ``clk_2``) is never mistaken for a frequency."""
    p = (port or "").strip().strip("{}[]")
    if not p:
        return None
    m = _PORT_FREQ_UNIT_RE.match(p)
    if m:
        val = float(m.group(1))
        return (val if m.group(2).upper() == "M" else val / 1000.0,
                "explicit unit in port name")
    m = _PORT_FREQ_BARE_RE.match(p)
    if m:
        val = float(m.group(1))
        if _BARE_MHZ_MIN <= val <= _BARE_MHZ_MAX:
            return (val, "bare frequency in port name (MHz by board "
                         "convention)")
    return None


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
# ORGANIC #577 — `clock_mhz` is the canonical L8 key the sibling SDC
# generator (sdc_gen.py: period_ns = 1000 / L8.clock_mhz) emits and
# consumes; the checker must share that vocabulary or Rule 3 silently
# never fires on canonical projects.
_FREQ_SYNONYMS_MHZ = (
    r"CLOCK_MHZ",
    r"CLK_MHZ",
    r"CLOCK_FREQ_MHZ",
    r"CLK_FREQ_MHZ",
    r"MASTER_CLK_MHZ",
    r"FREQ_MHZ",
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

    # PASS 1 — STRUCTURED, AUTHORITATIVE. L8/L9 JSON carries a structured
    # `clock_domains` array whose PRIMARY entry states the period the design
    # actually committed to, with `evidence`/`source` pointing at the staged
    # `input/constraints/*.sdc` timing contract (e.g. period_ns=24.0,
    # freq_mhz=41.67). The loose top-level `clock_mhz` SCALAR in the same file
    # is a summary that can go STALE against that domain — MEASURED on
    # spm×gf180mcuD: clock_mhz=100.0 (a sky130 doc default) sat beside
    # clock_domains[0].period_ns=24.0, and the scalar-regex pass below matched
    # `clock_mhz` first → 10 ns → a phantom FPGA_SDC_PERIOD_MISMATCH against a
    # 24 ns FPGA SDC that in fact AGREES with the design's real clock. The
    # per-domain period is strictly more authoritative than a loose scalar, so
    # read it first; the scalar scan remains as the fallback for files with no
    # structured clock_domains. This does NOT blind the check: a genuinely
    # wrong FPGA SDC still mismatches the (SDC-derived) primary-domain period.
    def _primary_period_ns(text: str) -> Optional[float]:
        try:
            data = json.loads(text)
        except Exception:
            return None
        doms = data.get("clock_domains") if isinstance(data, dict) else None
        if not isinstance(doms, list) or not doms:
            return None
        primary = None
        for d in doms:
            if not isinstance(d, dict):
                continue
            if str(d.get("role", "")) == "primary" or \
               str(d.get("domain_kind", "")) == "primary":
                primary = d
                break
        if primary is None and isinstance(doms[0], dict):
            primary = doms[0]
        if not isinstance(primary, dict):
            return None
        for key, conv in (("period_ns", lambda v: float(v)),
                          ("freq_mhz", lambda v: 1000.0 / float(v)),
                          ("freq_hz", lambda v: 1e9 / float(v))):
            v = primary.get(key)
            try:
                if v is not None and float(v) > 0:
                    return conv(v)
            except (ValueError, TypeError, ZeroDivisionError):
                continue
        return None

    for f in candidates:
        if f.suffix.lower() != ".json":
            continue
        try:
            p = _primary_period_ns(f.read_text(errors="replace"))
        except Exception:
            p = None
        if p is not None:
            return p

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
        # MHz → ns (#577: 1000 / MHz, mirroring sdc_gen.py)
        for syn in _FREQ_SYNONYMS_MHZ:
            m = re.search(_lb + syn + r"\b\D{0,40}?([0-9]+(?:\.[0-9]+)?)",
                          txt, re.IGNORECASE)
            if m:
                try:
                    mhz = float(m.group(1))
                    if mhz > 0:
                        return 1000.0 / mhz
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
    pll_mismatch_warned = False
    if rtl_period is not None and rtl_period > 0:
        for c in create_clocks:
            if c["period_ns"] is None:
                continue
            ratio = abs(c["period_ns"] - rtl_period) / rtl_period
            if ratio > 0.05:
                if sdc_has_pll:
                    pll_mismatch_warned = True
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

    # Rule 3b: a create_clock on a board OSCILLATOR port must carry the
    # OSCILLATOR's period, not the design's.
    #
    # Rule 3 compares the SDC against the design's declared clock period, so a
    # generator that binds the design period to a board oscillator port agrees
    # with itself and PASSes — while telling the FPGA tool the wrong frequency
    # for the physical part. The port name is the independent witness: a port
    # called CLOCK_50 is wired to a 50 MHz can, whatever the design wants, and
    # the design's slower clock can only be reached through a divider or PLL —
    # which in SDC is a create_generated_clock. With no generated clock the SDC
    # is asserting that the oscillator itself runs at the design's period.
    board_osc_mismatch = None
    for c in create_clocks:
        if c["period_ns"] is None or not c.get("port"):
            continue
        declared = port_name_declared_freq_mhz(c["port"])
        if not declared:
            continue
        osc_mhz, how = declared
        osc_period_ns = 1000.0 / osc_mhz
        ratio = abs(c["period_ns"] - osc_period_ns) / osc_period_ns
        if ratio <= 0.05:
            continue
        factor = max(c["period_ns"], osc_period_ns) / min(c["period_ns"],
                                                          osc_period_ns)
        detail = (f"  sdc file: {c.get('sdc_file')}\n"
                  f"  create_clock -name {c.get('name')} "
                  f"-period {c['period_ns']} ns [get_ports {c['port']}]\n"
                  f"  port name states {osc_mhz:g} MHz "
                  f"= {osc_period_ns:g} ns ({how});\n"
                  f"  constrained period is {factor:.1f}x that.")
        if sdc_has_pll:
            msgs.append(
                "WARN — FPGA_SDC_BOARD_OSC_MISMATCH (generated clock "
                "present)\n" + detail +
                "\n  A create_generated_clock is declared, so a divided/"
                "multiplied application clock is modelled — advisory only.")
        elif factor >= 2.0:
            # Only a gross disagreement is failed: a real wrong-oscillator
            # error is a whole multiple, while a few-percent drift is a
            # rounding or margin choice that is not worth blocking on.
            board_osc_mismatch = (
                "FAIL — FPGA_SDC_BOARD_OSC_MISMATCH\n" + detail +
                "\n  No create_generated_clock is declared, so nothing in this "
                "SDC divides the oscillator down to the constrained period: "
                "the FPGA tool will time-budget the design against a clock the "
                "board does not deliver.")
        else:
            msgs.append("WARN — FPGA_SDC_BOARD_OSC_DRIFT\n" + detail)
    if board_osc_mismatch:
        msgs.append(board_osc_mismatch)
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

    if rtl_period is None:
        period_note = ""
    elif pll_mismatch_warned:
        # #577 — do not claim a match the WARN above just denied.
        period_note = (f"; RTL clock period {rtl_period} ns — board-clock "
                       "mismatch under PLL topology (advisory, see WARN)")
    else:
        period_note = f"; RTL clock period {rtl_period} ns matches"
    msgs.append(
        f"PASS — {len(create_clocks)} create_clock entry/entries across "
        f"{len(sdc_files)} sdc file(s)" + period_note
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
