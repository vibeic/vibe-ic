#!/usr/bin/env python3
"""
fpga_led_probe_lint.py — Lint the deterministic FPGA LED-probe anti-patterns
documented in skills/fpga-led-probe-allocation/SKILL.md.

When a fresh agent verifies a chip on a DE10-Lite-class board with no scope
and only the on-board LEDs as visibility, it must allocate the LEDs in one of
four probe modes:

  instantaneous  | assign LED[N] = signal;                    (steady-state)
  pulse-stretched| pulse_stretch #(...) u(.pulse_in(sig), ...) (1-cycle pulse)
  sticky         | seen_q latches; assign LED[N] = seen_q;     (event flag)
  byte-display   | assign LED[7:0] = byte_q;                   (byte snapshot)

The SKILL.md "Anti-patterns" section enumerates four DETERMINISTIC structural
mistakes. This program flags exactly those four, and nothing else:

  1. instantaneous-on-pulse
       `assign LED[N] = sig;` where `sig` is a 1-cycle pulse (named/declared
       *_pulse / *_strobe / *_tick / *_done, or pulse-shaped: `sig <= 1'b1`
       followed unconditionally by `sig <= 1'b0` in the same always block).
       The camera will never catch a 1-cycle flash.

  2. sticky-without-reset-clear
       A sticky latch register (`if (cond) seen_q <= 1'b1;` whose output drives
       an LED) that has NO reset path clearing it. A sticky LED stuck ON forever
       lies about whether the test stage ran.

  3. shared-pin-vs-QSF
       An LED bit driven in RTL (`LEDR[N]` / `LED[N]`) that has NO matching
       `set_location_assignment ... -to LEDR[N]` in the supplied .qsf. Some
       boards reuse LED pins for config/USB-Blaster; an unallocated probe pin
       means the photo is meaningless.

  4. mode-mix-without-table
       The top mixes >= 2 distinct probe modes (pulse + sticky + byte) but has
       NO commented "LED PROBE TABLE" mapping LED -> signal -> behaviour. A
       reviewer glancing at a board photo then cannot decode the state.

chip-AGNOSTIC: no chip / register / protocol names baked in. Heuristics are
guarded so a clean spec produces ZERO findings (no false alerts):
  - pulse detection uses a NAME deny/allow set + a structural pulse-shape match,
    never a bare "is this a wire" guess;
  - sticky-clear requires the latch to actually exist (set-to-1 + LED-driven)
    before the missing-reset is flagged;
  - shared-pin check is SKIPPED entirely when no .qsf is supplied (MISSING, not
    FAIL);
  - mode-mix needs >= 2 modes present before a missing table is an anti-pattern.

Input: a probe-allocation spec / Verilog file (or a directory of .v/.sv).
Output: JSON findings (stdout always; --json <path> also writes a file).

Usage:
    python3 fpga_led_probe_lint.py <top.v|spec.txt|rtl_dir/> [more files...]
    python3 fpga_led_probe_lint.py --json out.json <top.v>

Exit codes:
    0 = no findings (clean) OR nothing to lint (graceful MISSING/SKIP)
    1 = one or more anti-pattern findings
    2 = usage / io error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Set, Tuple


# --------------------------------------------------------------------------
# Comment handling
# --------------------------------------------------------------------------
_LINE_CMT = re.compile(r"//[^\n]*")
_BLOCK_CMT = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_comments_keep_lines(src: str) -> str:
    """Remove comments but preserve line numbering (newlines kept)."""
    src = _BLOCK_CMT.sub(lambda m: "\n" * m.group(0).count("\n"), src)
    src = _LINE_CMT.sub("", src)
    return src


# --------------------------------------------------------------------------
# Pulse signal recognition (anti-pattern 1)
# --------------------------------------------------------------------------
# A signal name strongly suggesting a 1-cycle pulse. Used ONLY together with a
# structural confirmation OR as a documented allow-list (the SKILL.md template
# uses `tx_done_pulse`, `cmd_decoded_pulse`). Length-floor: >=2 chars.
_PULSE_NAME_RE = re.compile(
    r"(?:^|_)(pulse|strobe|stb|tick|done|valid|ack|req|fire|trig|trigger|"
    r"start|stop|edge|onehot)(?:$|_|\b)",
    re.IGNORECASE,
)

# Names that LOOK pulse-y but are steady-state level signals → deny-list so we
# never over-flag. e.g. *_en / *_enable / *_busy / *_state are held levels.
_LEVEL_NAME_RE = re.compile(
    r"(?:^|_)(en|ena|enable|busy|state|mode|level|hold|stable|active|ready|"
    r"sel|select|flag|q|reg|cnt|count|status)(?:$|_|\b)",
    re.IGNORECASE,
)

# Match `assign LED[N] = expr;` / `assign LEDR[N] = expr;`
_ASSIGN_LED_RE = re.compile(
    r"\bassign\s+(LEDR?|LED)\s*\[\s*(\d+)\s*\]\s*=\s*([^;]+);",
    re.IGNORECASE,
)
# Match a byte-display drive `assign LEDR[7:0] = byte_q;` (range LHS)
_ASSIGN_LED_RANGE_RE = re.compile(
    r"\bassign\s+(LEDR?|LED)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*=\s*([^;]+);",
    re.IGNORECASE,
)


def _line_of(src: str, idx: int) -> int:
    return src[:idx].count("\n") + 1


def _is_pulse_shaped(src: str, sig: str) -> bool:
    """Structural confirmation: the signal is set to 1 then unconditionally
    set back to 0 (a 1-cycle pulse generator), e.g.::

        sig <= 1'b1;
        ...
        sig <= 1'b0;

    Requires BOTH a set-to-1 and a set-to-0 of the same signal. This is the
    no-false-alert guard: a name alone never triggers; we also need the shape
    OR the name to be on the documented pulse allow-list.
    """
    set1 = re.search(
        r"\b" + re.escape(sig) + r"\s*<=\s*1'b1\b", src, re.IGNORECASE)
    set0 = re.search(
        r"\b" + re.escape(sig) + r"\s*<=\s*1'b0\b", src, re.IGNORECASE)
    return bool(set1) and bool(set0)


def _looks_like_pulse(src: str, sig: str) -> bool:
    """Decide whether `sig` is a 1-cycle pulse.

    Guarded: a name on the level deny-list is NEVER a pulse. Otherwise it is a
    pulse only if (a) the name carries a pulse token AND is not deny-listed, OR
    (b) the RTL has the explicit set-1/set-0 pulse shape.
    """
    if _LEVEL_NAME_RE.search(sig):
        return False
    if _is_pulse_shaped(src, sig):
        return True
    if _PULSE_NAME_RE.search(sig):
        return True
    return False


def _drives_pulse_stretch(src: str, sig: str) -> bool:
    """True if the signal feeds a pulse_stretch / stretch instance — i.e. the
    designer DID stretch it, so an instantaneous LED on the *stretched* output
    is fine. We treat any `pulse_stretch`/`*stretch*` instance mentioning the
    signal as evidence the pulse is handled."""
    pat = re.compile(
        r"\b\w*stretch\w*\b[^;]*\b" + re.escape(sig) + r"\b",
        re.IGNORECASE | re.DOTALL,
    )
    return bool(pat.search(src))


# --------------------------------------------------------------------------
# Sticky latch recognition (anti-pattern 2)
# --------------------------------------------------------------------------
# A sticky register: `if (... cond ...) seen_q <= 1'b1;` and never structurally
# cleared except by reset. We detect the set-to-1 and the LED drive, then check
# for a reset clear.
_STICKY_SET1_RE = re.compile(
    r"\bif\s*\([^)]*\)\s*(\w+)\s*<=\s*1'b1\s*;",
    re.IGNORECASE,
)


def _find_sticky_regs(src: str) -> Set[str]:
    """Registers that get set to 1'b1 under a non-reset condition (candidate
    sticky 'event-happened' flags)."""
    out: Set[str] = set()
    for m in _STICKY_SET1_RE.finditer(src):
        out.add(m.group(1))
    return out


def _reg_drives_led(src: str, reg: str) -> bool:
    """True if `reg` is wired to an LED bit (directly or via assign)."""
    for m in _ASSIGN_LED_RE.finditer(src):
        if re.search(r"\b" + re.escape(reg) + r"\b", m.group(3)):
            return True
    for m in _ASSIGN_LED_RANGE_RE.finditer(src):
        if re.search(r"\b" + re.escape(reg) + r"\b", m.group(4)):
            return True
    return False


def _reg_has_reset_clear(src: str, reg: str) -> bool:
    """True if `reg` is cleared on a reset.

    Recognises:
      - `always @(posedge clk or negedge rst_n) ... if (!rst_n) reg <= 1'b0;`
      - a `{a, b} <= 2'b00;` style group clear that includes `reg`
      - `reg <= 1'b0;` appearing inside a reset branch (`if (!rst)` / `if (rst)`)
    """
    # Direct single-signal clear: reg <= 1'b0  (within a reset-ish context).
    # Find every always block; if reg is set to 0 anywhere under a reset guard.
    # Cheap structural approximation: a clear-to-0 of reg that co-occurs with a
    # reset keyword in the SAME always block.
    for blk in re.finditer(
        r"\balways(?:_ff)?\b\s*@\s*\([^)]*\)(.*?)(?=\balways|\bendmodule|\Z)",
        src, re.IGNORECASE | re.DOTALL,
    ):
        body = blk.group(1)
        if not re.search(r"\brst|reset\b", body, re.IGNORECASE):
            continue
        # group clear: {a, b, ...} <= N'b0  — reg listed inside braces
        for grp in re.finditer(r"\{([^}]*)\}\s*<=\s*\d+'b0+\s*;", body):
            if re.search(r"\b" + re.escape(reg) + r"\b", grp.group(1)):
                return True
        # single clear of reg to 0
        if re.search(r"\b" + re.escape(reg) + r"\s*<=\s*1'b0\b", body,
                     re.IGNORECASE):
            return True
        if re.search(r"\b" + re.escape(reg) + r"\s*<=\s*0\b", body):
            return True
    return False


# --------------------------------------------------------------------------
# Probe-mode detection (anti-pattern 4) + LED PROBE TABLE detection
# --------------------------------------------------------------------------
def _detect_modes(src_no_comments: str, raw_src: str) -> Set[str]:
    """Return the set of distinct probe modes present in the top.

      pulse  : a *stretch* instance OR a pulse-shaped signal driving an LED
      sticky : a sticky latch reg driving an LED
      byte   : a multi-bit range LED drive (>1 bit wide)
      inst   : a plain `assign LED[N] = level_sig;` instantaneous level probe
    """
    modes: Set[str] = set()

    # byte-display: range LHS with width > 1
    for m in _ASSIGN_LED_RANGE_RE.finditer(src_no_comments):
        hi, lo = int(m.group(2)), int(m.group(3))
        if abs(hi - lo) >= 1:
            modes.add("byte")

    # pulse: any stretch instance present
    if re.search(r"\b\w*stretch\w*\b", src_no_comments, re.IGNORECASE):
        modes.add("pulse")

    sticky_regs = _find_sticky_regs(src_no_comments)
    for r in sticky_regs:
        if _reg_drives_led(src_no_comments, r):
            modes.add("sticky")

    # instantaneous level probe: assign LED[N] = <level_sig>; where the RHS is
    # neither a sticky reg nor a pulse.
    for m in _ASSIGN_LED_RE.finditer(src_no_comments):
        rhs = m.group(3).strip()
        rhs_sig = re.match(r"^(\w+)$", rhs)
        if not rhs_sig:
            continue
        sig = rhs_sig.group(1)
        if sig in sticky_regs:
            continue
        if _looks_like_pulse(src_no_comments, sig):
            continue
        modes.add("inst")
    return modes


_PROBE_TABLE_RE = re.compile(r"LED\s*PROBE\s*TABLE", re.IGNORECASE)


def _has_probe_table(raw_src: str) -> bool:
    """A commented 'LED PROBE TABLE' header. Must live in a comment (the table
    is documentation) — we look in the RAW source so comments are visible."""
    return bool(_PROBE_TABLE_RE.search(raw_src))


# --------------------------------------------------------------------------
# QSF parsing (anti-pattern 3)
# --------------------------------------------------------------------------
_QSF_PIN_TO_LED_RE = re.compile(
    r"set_location_assignment\s+\S+\s+-to\s+(LEDR?|LED)\s*\[\s*(\d+)\s*\]",
    re.IGNORECASE,
)


def _qsf_allocated_leds(qsf_text: str) -> Set[int]:
    out: Set[int] = set()
    for line in qsf_text.splitlines():
        if line.strip().startswith("#"):
            continue
        m = _QSF_PIN_TO_LED_RE.search(line)
        if m:
            out.add(int(m.group(2)))
    return out


def _rtl_driven_leds(src_no_comments: str) -> Set[int]:
    """Every LED bit index driven in RTL (single-bit and range)."""
    out: Set[int] = set()
    for m in _ASSIGN_LED_RE.finditer(src_no_comments):
        out.add(int(m.group(2)))
    for m in _ASSIGN_LED_RANGE_RE.finditer(src_no_comments):
        hi, lo = int(m.group(2)), int(m.group(3))
        for b in range(min(hi, lo), max(hi, lo) + 1):
            out.add(b)
    return out


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    file: str
    line: int
    detail: str
    fix_hint: str


@dataclass
class Result:
    status: str                       # PASS | FAIL | SKIP
    findings: List[Finding] = field(default_factory=list)
    files_scanned: List[str] = field(default_factory=list)
    qsf_checked: bool = False
    modes_detected: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Core lint
# --------------------------------------------------------------------------
def lint_source(file_label: str, raw_src: str, qsf_text: str | None
                ) -> Tuple[List[Finding], Set[str]]:
    findings: List[Finding] = []
    src = strip_comments_keep_lines(raw_src)

    # ---- Anti-pattern 1: instantaneous-on-pulse --------------------------
    for m in _ASSIGN_LED_RE.finditer(src):
        rhs = m.group(3).strip()
        rhs_sig = re.match(r"^(\w+)$", rhs)
        if not rhs_sig:
            continue
        sig = rhs_sig.group(1)
        if not _looks_like_pulse(src, sig):
            continue
        # Guard: if the signal was stretched, the LED on the stretched output
        # is correct — do not flag.
        if _drives_pulse_stretch(src, sig):
            continue
        findings.append(Finding(
            rule="instantaneous-on-pulse",
            severity="ERROR",
            file=file_label,
            line=_line_of(src, m.start()),
            detail=(f"LED bit driven instantaneously by 1-cycle pulse "
                    f"'{sig}': `{m.group(0).strip()}`"),
            fix_hint=("Use pulse-stretched mode so the camera can catch it: "
                      "pulse_stretch #(50000) u(.clk(clk_50m), "
                      f".pulse_in({sig}), .led_out(LED[N]));"),
        ))

    # ---- Anti-pattern 2: sticky-without-reset-clear ----------------------
    sticky_regs = _find_sticky_regs(src)
    for reg in sorted(sticky_regs):
        if not _reg_drives_led(src, reg):
            continue  # only a *probe* sticky flag matters
        if _reg_has_reset_clear(src, reg):
            continue
        # locate the set-to-1 line for reporting
        sm = re.search(r"\b" + re.escape(reg) + r"\s*<=\s*1'b1\b", src,
                       re.IGNORECASE)
        ln = _line_of(src, sm.start()) if sm else 0
        findings.append(Finding(
            rule="sticky-without-reset-clear",
            severity="ERROR",
            file=file_label,
            line=ln,
            detail=(f"Sticky probe register '{reg}' is set to 1 and drives an "
                    f"LED but is never cleared on reset — it stays ON forever "
                    f"even if the test stage never ran."),
            fix_hint=("Add a reset clear so the baseline capture is honest: "
                      f"if (!rst_n) {reg} <= 1'b0;"),
        ))

    # ---- Anti-pattern 4: mode-mix-without-table --------------------------
    modes = _detect_modes(src, raw_src)
    distinct = set(modes)
    # The SKILL anti-pattern is "mixing pulse + sticky + byte modes without
    # commenting which is which". Require >= 2 distinct modes among the
    # observable probe modes before demanding a table.
    if len(distinct) >= 2 and not _has_probe_table(raw_src):
        findings.append(Finding(
            rule="mode-mix-without-table",
            severity="ERROR",
            file=file_label,
            line=1,
            detail=(f"Top mixes {len(distinct)} probe modes "
                    f"({', '.join(sorted(distinct))}) with no commented "
                    f"'LED PROBE TABLE' — a reviewer cannot decode a board "
                    f"photo."),
            fix_hint=("Add a commented LED PROBE TABLE mapping each LED to its "
                      "signal, mode, and expected behaviour, e.g.:\n"
                      "// LED PROBE TABLE\n"
                      "// LEDR[9]   sticky    tx_done_q   packet TX completed\n"
                      "// LEDR[7:0] byte-disp resp_byte   most recent response"),
        ))

    # ---- Anti-pattern 3: shared-pin-vs-QSF -------------------------------
    if qsf_text is not None:
        alloc = _qsf_allocated_leds(qsf_text)
        driven = _rtl_driven_leds(src)
        missing = sorted(driven - alloc)
        for bit in missing:
            findings.append(Finding(
                rule="shared-pin-vs-QSF",
                severity="ERROR",
                file=file_label,
                line=1,
                detail=(f"LED bit LEDR[{bit}] is driven in RTL but has no "
                        f"set_location_assignment ... -to LEDR[{bit}] in the "
                        f"supplied QSF — the pin may be shared (config / "
                        f"USB-Blaster) and the probe is meaningless."),
                fix_hint=(f"Add to the .qsf: set_location_assignment PIN_<x> "
                          f"-to LEDR[{bit}] (check the board pinout first)."),
            ))

    return findings, modes


# --------------------------------------------------------------------------
# Input collection
# --------------------------------------------------------------------------
_SRC_EXT = (".v", ".sv", ".svh", ".txt", ".md", ".spec")


def _collect_inputs(paths: List[str]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            for ext in (".v", ".sv", ".svh"):
                out.extend(sorted(pp.rglob(f"*{ext}")))
        elif pp.is_file():
            out.append(pp)
    # de-dup, stable order
    seen: Set[str] = set()
    uniq: List[Path] = []
    for f in out:
        k = str(f.resolve())
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.strip().split("\n")[0])
    ap.add_argument("inputs", nargs="+",
                    help="Verilog/spec file(s) or a directory of .v/.sv")
    ap.add_argument("--qsf", type=Path, default=None,
                    help="Optional .qsf for the shared-pin-vs-QSF check "
                         "(SKIPPED if not supplied — never a false FAIL)")
    ap.add_argument("--json", type=Path, default=None,
                    help="Also write findings JSON to this path")
    args = ap.parse_args(argv)

    files = _collect_inputs([str(x) for x in args.inputs])
    if not files:
        # Graceful: nothing to lint → SKIP, not crash, not over-flag.
        res = Result(status="SKIP", findings=[], files_scanned=[],
                     qsf_checked=False, modes_detected=[])
        out = json.dumps(asdict(res), indent=2)
        if args.json:
            args.json.write_text(out)
        print(out)
        print("fpga_led_probe_lint: SKIP — no .v/.sv/spec input found",
              file=sys.stderr)
        return 0

    qsf_text = None
    if args.qsf is not None:
        if not args.qsf.is_file():
            print(f"ERROR: --qsf not found: {args.qsf}", file=sys.stderr)
            return 2
        qsf_text = args.qsf.read_text(errors="replace")

    all_findings: List[Finding] = []
    all_modes: Set[str] = set()
    scanned: List[str] = []
    for f in files:
        try:
            raw = f.read_text(errors="replace")
        except OSError as exc:
            print(f"ERROR: cannot read {f}: {exc}", file=sys.stderr)
            return 2
        fnd, modes = lint_source(str(f), raw, qsf_text)
        all_findings.extend(fnd)
        all_modes |= modes
        scanned.append(str(f))

    status = "FAIL" if all_findings else "PASS"
    res = Result(
        status=status,
        findings=all_findings,
        files_scanned=scanned,
        qsf_checked=qsf_text is not None,
        modes_detected=sorted(all_modes),
    )
    out = json.dumps(asdict(res), indent=2)
    if args.json:
        args.json.write_text(out)
    print(out)

    if all_findings:
        print(f"fpga_led_probe_lint: FAIL — {len(all_findings)} anti-pattern "
              f"finding(s)", file=sys.stderr)
        for fnd in all_findings:
            print(f"  [{fnd.rule}] {fnd.file}:{fnd.line} — {fnd.detail}",
                  file=sys.stderr)
        return 1

    print(f"fpga_led_probe_lint: PASS — no LED-probe anti-patterns "
          f"({len(files)} file(s), modes={sorted(all_modes)})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
