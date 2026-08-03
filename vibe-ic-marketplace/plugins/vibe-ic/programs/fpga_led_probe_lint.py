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

CORRECTIONS (2026-08-03, vibe-ic#693 fpga-signaltap family) — every clause below
replaces a claim this header used to make that measurement contradicted. The
gate had never been wired, so none of them had ever been exercised on real data.

  (1) "a name alone never triggers" was FALSE. `_looks_like_pulse` returned True
      on the NAME ALONE for any of pulse/strobe/stb/tick/done/valid/ack/req/
      fire/trig/trigger/start/stop/edge/onehot. Measured on the only real FPGA
      top in the published corpus, that made `assign LEDR[1] = test_done;` an
      ERROR — where `test_done` is set in the compare state and HELD in the
      terminal state, i.e. a permanently-asserted level. Isolated by a
      rename-only control: `test_done` -> `test_finished` (zero behavioural
      change) removed the finding entirely.
      NOW: the name evidence is TWO-TIER.
        strong  pulse/strobe/stb/tick/edge/onehot/fire/trig/trigger
                -> unambiguously names a 1-cycle event -> ERROR
        weak    done/valid/ack/req/start/stop
                -> handshake names that are held levels at least as often as
                   they are pulses -> WARNING (reported, does NOT fail)
      A structural set-1/set-0 pulse shape is ERROR whatever the name.

  (2) `mode-mix-without-table` counted FOUR modes. SKILL.md defines the
      anti-pattern as "Mixing >= 2 of {pulse, sticky, byte}" — `instantaneous`
      is the BASELINE mode, not a mix participant. Counting it made a byte
      column plus one plain level probe (the SKILL's own recommended layout) a
      finding. NOW: only {pulse, sticky, byte} are counted; `inst` is reported
      in `modes_detected` for the reader and excluded from the mix test.

  (3) The probe table was recognised ONLY by the literal string
      `LED PROBE TABLE`. The corpus top carries a complete four-line LED map in
      comments and was flagged anyway; adding that one comment line and nothing
      else cleared the finding. NOW: a commented block that maps >= 2 LED
      indices to signals is accepted as a probe table.

  (4) A directory input crashed with rc=2 on a DANGLING SYMLINK (31 exist under
      the published corpus) and `Path.rglob` PROPAGATES any OSError whose errno
      is outside pathlib's ignored set (ENOENT/ENOTDIR/EBADF/ELOOP) — e.g.
      ENOTCONN from a stale socket in the tree. rc=2 is the umbrella's
      VACUOUS_PASS tier, so the crash was credited as a benign skip: a SILENT
      FALSE-CLEAN on the one run that had something to lint. NOW: the walk is
      guarded, non-files are filtered out, and an unreadable file is recorded
      in `unreadable[]` and skipped rather than aborting the run.

  (5) "nothing to lint" exited 0, which `flow_compliance_check` credits as a
      plain PASS. NOW it exits 2 (the disclosed-skip tier) and prints a
      `[SKIP]`-prefixed line so `gate_skip_routing_check._skip_token` can see
      the declaration at all.

Input: a probe-allocation spec / Verilog file (or a directory of .v/.sv).
Output: JSON findings (stdout always; --json <path> also writes a file).

Usage:
    python3 fpga_led_probe_lint.py <top.v|spec.txt|rtl_dir/> [more files...]
    python3 fpga_led_probe_lint.py --json out.json <top.v>

Exit codes:
    0 = no ERROR findings (clean; WARNINGs may still be reported)
    1 = one or more ERROR anti-pattern findings
    2 = NOTHING EXAMINED (no input file, or no LED drive in any scanned file)
        — the disclosed-skip tier, never a pass. Also argparse usage errors.
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
# Pulse-name evidence is TWO-TIER (correction 1 in the header).
#
# STRONG — the token names a 1-cycle EVENT and nothing else. `tx_done_pulse` and
# `cmd_decoded_pulse` (the SKILL.md template's own signals) land here. An LED
# driven instantaneously by one of these is an ERROR on the name alone.
_STRONG_PULSE_NAME_RE = re.compile(
    r"(?:^|_)(pulse|strobe|stb|tick|fire|trig|trigger|edge|onehot)(?:$|_|\b)",
    re.IGNORECASE,
)
# WEAK — handshake/status tokens. These name a 1-cycle pulse about as often as
# they name a held level (`test_done` asserted in the compare state and HELD in
# the terminal state; `data_valid` held while a word is presented). Without a
# structural pulse shape the name is NOT enough to fail a run, so a weak-name
# hit is a WARNING: reported for a human, never a red.
_WEAK_PULSE_NAME_RE = re.compile(
    r"(?:^|_)(done|valid|ack|req|start|stop)(?:$|_|\b)",
    re.IGNORECASE,
)
# Union — kept because `_detect_modes` asks only "is this a pulse at all?" when
# deciding whether an LED drive is a plain instantaneous level probe.
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
# ANY reference to an LED bit / slice in RTL — `LEDR[9]`, `LED[7:0]`. Used only
# to answer "was there anything in this file for the lint to look at?", which
# decides PASS vs the rc=2 disclosed-skip tier.
_LED_BIT_REF_RE = re.compile(r"\bLEDR?\s*\[\s*\d+", re.IGNORECASE)
# Match a byte-display drive `assign LEDR[7:0] = byte_q;` (range LHS)
_ASSIGN_LED_RANGE_RE = re.compile(
    r"\bassign\s+(LEDR?|LED)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*=\s*([^;]+);",
    re.IGNORECASE,
)


def _line_of(src: str, idx: int) -> int:
    return src[:idx].count("\n") + 1


# A reset-guarded `if`: `if (!rst_n)`, `if (rst)`, `if (~reset_n)`, `if (n_rst
# == 1'b0)`. The BRANCH BODY is a reset clear, not a pulse deassert — see
# `_strip_reset_branches`.
_RESET_IF_RE = re.compile(
    r"\bif\s*\(\s*[!~]?\s*\w*(?:rst|reset)\w*\b[^)]*\)", re.IGNORECASE)


def _strip_reset_branches(src: str) -> str:
    """Blank out the body of every reset-guarded `if`, preserving line count.

    WHY THIS EXISTS. `sig <= 0;` inside `if (!rst_n) begin ... end` is a RESET
    CLEAR. `sig <= 0;` in the ordinary path is a PULSE DEASSERT. A whole-file
    search cannot tell them apart, and conflating them makes every reset-cleared
    held flag look "pulse-shaped". Measured on the corpus's only real FPGA top:
    `test_done` is set to 1'b1 in the compare state and held in the terminal
    state, and its only write of 0 is the reset clear — a held level that a
    whole-file search calls a pulse.

    Blanking (rather than deleting) keeps every byte offset stable so
    `_line_of` still reports the true line number.
    """
    out = list(src)

    def blank(lo: int, hi: int) -> None:
        for i in range(lo, min(hi, len(out))):
            if out[i] != "\n":
                out[i] = " "

    def kw_at(j: int, kw: str) -> bool:
        """`kw` occurs at `j` as a WHOLE Verilog token.

        Both sides matter. Checking only the trailing side kept `endcase` /
        `endmodule` out (good) but let the `end` inside `frame_end` and the
        `begin` inside `pkt_begin` through — each one miscounts the nesting
        depth and blanks the wrong region, which silently changes the verdict
        of the pulse-shape test this function feeds.
        """
        if not src.startswith(kw, j):
            return False
        if j > 0 and (src[j - 1].isalnum() or src[j - 1] == "_"):
            return False
        k = j + len(kw)
        return not (k < len(src) and (src[k].isalnum() or src[k] == "_"))

    for m in _RESET_IF_RE.finditer(src):
        i = m.end()
        # skip whitespace to the first token of the branch body
        while i < len(src) and src[i].isspace():
            i += 1
        if kw_at(i, "begin"):
            # consume to the MATCHING end (begin/end nest)
            depth = 0
            j = i
            while j < len(src):
                if kw_at(j, "begin"):
                    depth += 1
                    j += 5
                    continue
                if kw_at(j, "end"):
                    depth -= 1
                    j += 3
                    if depth == 0:
                        break
                    continue
                j += 1
            blank(i, j)
        else:
            # single statement: consume to the terminating `;`
            j = src.find(";", i)
            blank(i, (j + 1) if j != -1 else len(src))
    return "".join(out)


_SET1_TAIL = r"\s*<=\s*(?:1'b1|1'd1|1'h1|'1|1)\s*;"
_SET0_TAIL = r"\s*<=\s*(?:1'b0|1'd0|1'h0|'0|0)\s*;"


def _is_pulse_shaped(src: str, sig: str) -> bool:
    """Structural confirmation: the signal is set to 1 and ALSO set back to 0
    OUTSIDE any reset branch (a 1-cycle pulse generator), e.g.::

        sig <= 1'b1;
        ...
        sig <= 1'b0;

    Requires BOTH a set-to-1 and a set-to-0 of the same signal, both in
    non-reset code. Widened from `1'b1`/`1'b0` only to also accept the bare and
    sized literal forms (`<= 1;` / `<= 1'd0;` / `<= '0;`) — the widening is only
    safe BECAUSE reset branches are stripped first; without that, every
    reset-cleared held flag becomes "pulse-shaped".
    """
    body = _strip_reset_branches(src)
    set1 = re.search(r"\b" + re.escape(sig) + _SET1_TAIL, body, re.IGNORECASE)
    set0 = re.search(r"\b" + re.escape(sig) + _SET0_TAIL, body, re.IGNORECASE)
    return bool(set1) and bool(set0)


#: Ordered strongest-first. "" means "not a pulse".
_PULSE_EVIDENCE_ERROR = ("shape", "strong-name")


def _pulse_evidence(src: str, sig: str) -> str:
    """How strongly do we believe `sig` is a 1-cycle pulse?

    Returns one of ``"shape"`` / ``"strong-name"`` / ``"weak-name"`` / ``""``.
    Only the first two justify an ERROR; ``"weak-name"`` is reported as a
    WARNING so a held handshake level (`test_done`, `data_valid`) cannot redden
    a run on its identifier alone. See correction (1) in the module header.
    """
    if _LEVEL_NAME_RE.search(sig):
        return ""
    if _is_pulse_shaped(src, sig):
        return "shape"
    if _STRONG_PULSE_NAME_RE.search(sig):
        return "strong-name"
    if _WEAK_PULSE_NAME_RE.search(sig):
        return "weak-name"
    return ""


def _looks_like_pulse(src: str, sig: str) -> bool:
    """Is `sig` a pulse at ANY evidence tier?

    Used by `_detect_modes` to decide whether an LED drive is a plain
    instantaneous LEVEL probe — a question that does not care how strong the
    evidence is. The ERROR/WARNING split lives in `_pulse_evidence`.
    """
    return bool(_pulse_evidence(src, sig))


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
#: The modes SKILL.md counts in "Mixing >= 2 of {pulse, sticky, byte}".
#: `inst` (SKILL.md's `instantaneous`) is the BASELINE mode and is deliberately
#: NOT a mix participant — see correction (2) in the module header. It is still
#: returned by `_detect_modes` and reported in `modes_detected` for the reader.
_MIX_MODES: Set[str] = {"pulse", "sticky", "byte"}


def _detect_modes(src_no_comments: str, raw_src: str) -> Set[str]:
    """Return the set of distinct probe modes present in the top.

      pulse  : a *stretch* instance OR a pulse-shaped signal driving an LED
      sticky : a sticky latch reg driving an LED
      byte   : a multi-bit range LED drive (>1 bit wide)
      inst   : a plain `assign LED[N] = level_sig;` instantaneous level probe
               (reported, but NOT counted by the mode-mix rule)
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

#: A commented LED-map ROW: a comment line that names an LED bit or range.
#: `// LEDR[0] = TEST_PASS` / `// LEDR[7:0]  byte-disp  resp_byte`.
_TABLE_ROW_RE = re.compile(
    r"^\s*(?://|\*)\s*.*?\bLEDR?\s*\[\s*\d+\s*(?::\s*\d+\s*)?\]",
    re.IGNORECASE,
)
#: How many mapped LED rows constitute a table. Two is the floor because the
#: anti-pattern itself needs >= 2 modes present: a document that decodes fewer
#: bits than there are modes cannot decode the photo.
_TABLE_ROW_FLOOR = 2


def _has_probe_table(raw_src: str) -> bool:
    """Does the source carry a commented LED probe table?

    TWO forms are accepted (correction 3 in the module header). The literal
    `LED PROBE TABLE` title, OR a commented block that actually maps
    >= `_TABLE_ROW_FLOOR` LED indices to signals. Requiring the TITLE alone
    rejected a complete, correct four-row LED map on the corpus's only real
    FPGA top: the rule fired on a missing string, not a missing table, and
    adding that one comment line and changing nothing else cleared it.

    Comments only — the table is documentation, so we read the RAW source.
    """
    if _PROBE_TABLE_RE.search(raw_src):
        return True
    rows = sum(1 for ln in raw_src.splitlines() if _TABLE_ROW_RE.match(ln))
    return rows >= _TABLE_ROW_FLOOR


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
    #: Severity WARNING. Reported, never a red. `findings` stays exactly what
    #: it always was — the ERROR set that decides the exit code — so a reader
    #: (or a test) that only looks at `findings` cannot mistake a warning for
    #: a failure, and cannot miss one either: they are printed too.
    warnings: List[Finding] = field(default_factory=list)
    #: Files the walk found but could not read (dangling symlink, permissions).
    #: NON-EMPTY IS A DISCLOSURE: the lint's coverage is smaller than the file
    #: list suggests. It is NOT an abort, and NOT laundered into a skip.
    unreadable: List[str] = field(default_factory=list)
    #: How many LED drives were actually examined. Zero means the gate looked
    #: at files and found nothing in its subject matter -> rc 2, not PASS.
    led_drives_examined: int = 0


# --------------------------------------------------------------------------
# Core lint
# --------------------------------------------------------------------------
def lint_source(file_label: str, raw_src: str, qsf_text: str | None
                ) -> Tuple[List[Finding], Set[str], List[Finding], int]:
    """Lint one source. Returns (errors, modes, warnings, led_drives_seen)."""
    findings: List[Finding] = []
    warnings: List[Finding] = []
    src = strip_comments_keep_lines(raw_src)
    # "Did this file contain the gate's subject matter at all?" — ANY LED bit
    # reference in non-comment RTL, not only the `assign LED[N] =` form: a
    # `pulse_stretch u(... .led_out(LEDR[9]))` instance is an LED probe too.
    led_drives = len(_LED_BIT_REF_RE.findall(src))

    # ---- Anti-pattern 1: instantaneous-on-pulse --------------------------
    for m in _ASSIGN_LED_RE.finditer(src):
        rhs = m.group(3).strip()
        rhs_sig = re.match(r"^(\w+)$", rhs)
        if not rhs_sig:
            continue
        sig = rhs_sig.group(1)
        evidence = _pulse_evidence(src, sig)
        if not evidence:
            continue
        # Guard: if the signal was stretched, the LED on the stretched output
        # is correct — do not flag.
        if _drives_pulse_stretch(src, sig):
            continue
        strong = evidence in _PULSE_EVIDENCE_ERROR
        why = {
            "shape": "it is set to 1 and back to 0 outside any reset branch "
                     "(structural 1-cycle pulse shape)",
            "strong-name": "its name carries an unambiguous pulse token",
            "weak-name": "its name carries a handshake token (done/valid/ack/"
                         "req/start/stop) — WEAK evidence: no structural pulse "
                         "shape was found, so this may well be a HELD level",
        }[evidence]
        f = Finding(
            rule="instantaneous-on-pulse",
            severity="ERROR" if strong else "WARNING",
            file=file_label,
            line=_line_of(src, m.start()),
            detail=(f"LED bit driven instantaneously by 1-cycle pulse "
                    f"'{sig}' ({evidence}: {why}): `{m.group(0).strip()}`"),
            fix_hint=("Use pulse-stretched mode so the camera can catch it: "
                      "pulse_stretch #(50000) u(.clk(clk_50m), "
                      f".pulse_in({sig}), .led_out(LED[N]));"
                      + ("" if strong else
                         f"  — or, if '{sig}' is a HELD level, no change is "
                         f"needed and this warning is expected.")),
        )
        (findings if strong else warnings).append(f)

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
    # SKILL.md: "Mixing >= 2 of {pulse, sticky, byte}". `inst` is the BASELINE
    # mode, not a mix participant — counting it made the SKILL's own
    # recommended layout (a byte column plus one level probe) a finding.
    distinct = set(modes) & _MIX_MODES
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

    return findings, modes, warnings, led_drives


# --------------------------------------------------------------------------
# Input collection
# --------------------------------------------------------------------------
_SRC_EXT = (".v", ".sv", ".svh", ".txt", ".md", ".spec")


def _walk_rtl(root: Path) -> List[Path]:
    """Every readable .v/.sv/.svh REGULAR FILE under `root`.

    `Path.rglob` cannot be used bare here, twice over:

      * it yields DANGLING SYMLINKS (31 exist under the published corpus), and
        the caller then died reading one;
      * it PROPAGATES any OSError from a directory entry whose errno is outside
        pathlib's ignored set (ENOENT / ENOTDIR / EBADF / ELOOP). A stale socket
        raising ENOTCONN aborts the whole walk from inside `rglob` itself, so an
        `is_file()` filter applied to its RESULT is too late.

    Both failures reached the caller as rc=2 — the umbrella's VACUOUS_PASS tier
    — so an aborted lint was credited as a benign skip. `os.walk(onerror=...)`
    swallows directory errors by contract, and each entry is `is_file()`-tested
    inside its own guard.
    """
    import os

    out: List[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root, onerror=lambda _e: None,
                                                 followlinks=False):
        for name in filenames:
            if not name.endswith((".v", ".sv", ".svh")):
                continue
            p = Path(dirpath) / name
            try:
                if p.is_file():
                    out.append(p)
            except OSError:
                # Unreadable node (dangling symlink, stale mount). Not a file
                # we can lint, and not a reason to abandon the other 100.
                continue
    return sorted(out)


def _collect_inputs(paths: List[str]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        pp = Path(p)
        try:
            is_dir, is_file = pp.is_dir(), pp.is_file()
        except OSError:
            continue
        if is_dir:
            out.extend(_walk_rtl(pp))
        elif is_file:
            out.append(pp)
    # de-dup, stable order
    seen: Set[str] = set()
    uniq: List[Path] = []
    for f in out:
        try:
            k = str(f.resolve())
        except OSError:
            k = str(f)
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

    def _emit_skip(reason: str) -> int:
        """The disclosed-skip tier. rc 2, NOT rc 0.

        `flow_compliance_check._check_program_exit_zero` reads rc==2 as
        `__VACUOUS_HINT__` (VACUOUS_PASS) and rc==0 as a plain PASS, so exiting
        0 here made "this run has no FPGA top" indistinguishable from "the FPGA
        top was audited and is clean". The `[SKIP]` prefix is load-bearing too:
        `gate_skip_routing_check._skip_token` matches its vocabulary at LINE
        START, so the old `fpga_led_probe_lint: SKIP — ...` form was invisible
        to the ratchet that exists to count exactly this.
        """
        res = Result(status="SKIP", findings=[], files_scanned=[],
                     qsf_checked=False, modes_detected=[])
        out = json.dumps(asdict(res), indent=2)
        if args.json:
            args.json.write_text(out)
        print(out)
        print(f"[SKIP] fpga_led_probe_lint: {reason} — NOTHING EXAMINED, "
              f"this is not a pass", file=sys.stderr)
        return 2

    files = _collect_inputs([str(x) for x in args.inputs])
    if not files:
        return _emit_skip("no .v/.sv/spec input found")

    qsf_text = None
    if args.qsf is not None:
        if not args.qsf.is_file():
            print(f"ERROR: --qsf not found: {args.qsf}", file=sys.stderr)
            return 2
        qsf_text = args.qsf.read_text(errors="replace")

    all_findings: List[Finding] = []
    all_warnings: List[Finding] = []
    all_modes: Set[str] = set()
    scanned: List[str] = []
    unreadable: List[str] = []
    led_drives = 0
    for f in files:
        try:
            raw = f.read_text(errors="replace")
        except OSError as exc:
            # DISCLOSE AND CONTINUE. Aborting with rc=2 here turned one
            # unreadable file into a VACUOUS_PASS for the whole project — a
            # silent false-clean, measured on the corpus's only run with an
            # FPGA top, caused by a dangling symlink 12 directories away.
            print(f"WARNING: cannot read {f}: {exc} — skipped", file=sys.stderr)
            unreadable.append(str(f))
            continue
        fnd, modes, warn, drives = lint_source(str(f), raw, qsf_text)
        all_findings.extend(fnd)
        all_warnings.extend(warn)
        all_modes |= modes
        led_drives += drives
        scanned.append(str(f))

    if not scanned:
        return _emit_skip(f"none of the {len(files)} matched file(s) could be "
                          f"read")
    if led_drives == 0:
        # Files were read and contained NO LED drive at all. The gate's whole
        # subject matter is absent, so a PASS here would certify an examination
        # that never happened.
        return _emit_skip(f"no LED drive found in {len(scanned)} scanned "
                          f"file(s)")

    status = "FAIL" if all_findings else "PASS"
    res = Result(
        status=status,
        findings=all_findings,
        files_scanned=scanned,
        qsf_checked=qsf_text is not None,
        modes_detected=sorted(all_modes),
        warnings=all_warnings,
        unreadable=unreadable,
        led_drives_examined=led_drives,
    )
    out = json.dumps(asdict(res), indent=2)
    if args.json:
        args.json.write_text(out)
    print(out)

    for w in all_warnings:
        print(f"  [WARNING {w.rule}] {w.file}:{w.line} — {w.detail}",
              file=sys.stderr)
    if unreadable:
        print(f"  [COVERAGE] {len(unreadable)} file(s) unreadable and skipped: "
              f"{unreadable[:3]}{' ...' if len(unreadable) > 3 else ''}",
              file=sys.stderr)

    if all_findings:
        print(f"fpga_led_probe_lint: FAIL — {len(all_findings)} anti-pattern "
              f"finding(s)", file=sys.stderr)
        for fnd in all_findings:
            print(f"  [{fnd.rule}] {fnd.file}:{fnd.line} — {fnd.detail}",
                  file=sys.stderr)
        return 1

    print(f"fpga_led_probe_lint: PASS — no LED-probe anti-patterns "
          f"({len(scanned)} file(s), {led_drives} LED drive(s), "
          f"modes={sorted(all_modes)}, {len(all_warnings)} warning(s))",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
