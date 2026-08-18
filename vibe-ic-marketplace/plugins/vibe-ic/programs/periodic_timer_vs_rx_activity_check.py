#!/usr/bin/env python3
"""
periodic_timer_vs_rx_activity_check.py — Periodic TX-triggering timer
must reset on RX activity, on a shared bidirectional wire.

Generic pattern (applies to any IC with a shared bidirectional signal
that carries BOTH DUT-initiated keepalive/wake pulses AND
host-initiated commands):
  If the DUT has a periodic counter that fires autonomous TX events
  (wake pulse, keepalive, heartbeat), that counter MUST be reset on
  incoming RX activity from the host. Otherwise the DUT's autonomous
  TX eventually coincides with an incoming host cmd and collides on
  the wire — each side sees corrupted data. Hardware-only failure
  mode: sim always sends cmd at a random offset and the race rarely
  aligns, but on a real tester with its own 5 ms / 1 ms / etc. period,
  the two clocks phase-lock and collide every single cycle.

Real occurrence (v068 <benchmark> fresh-agent):
  wake_ctrl.v had
      if (!frozen_o && !woken_i) begin
          if (cnt == ITO_CYC - 1) begin
              ito_expired_o <= 1'b1;
              cnt <= 0;
          end else cnt <= cnt + 1;
      end
  No reset path from tester-RX activity. DE10-Lite cmd_fsm fired wake
  pulse every 5 ms independently. <half-duplex-tester> tester ALSO probed every
  5 ms. Phase alignment → wake pulse always overlapped with tester's
  cmd BR → cmd_fsm never received a clean cmd packet.

  v052's wake_ctrl has `if (cmd_valid) cnt <= 0;` which breaks the
  collision at generation time.

Applies to:
  - AID / MID single-wire ID bus (<chip-class> family)
  - I2C slaves with clock-stretching + autonomous STATUS interrupt
  - 1-Wire protocols (Dallas/Maxim) with presence pulses
  - Any peripheral on a shared bus with periodic keepalive

Rule enforced
-------------
For each always block that contains an NBA self-increment
`R <= R + ...;` (a counter), ALSO require that R has at least one
reset-to-zero branch guarded by an RX-activity signal (whose name
matches `rx`, `br_`, `byte_valid`, `_active`, `cmd_valid`, `bus_rx`,
etc.). If R only has reset-to-zero under the reset branch
(`if (!rstn) R <= 0;`) and inside its own expiry path, WARN.

Heuristic; silence with `// periodic-timer-rx-reset-ok` on the
increment line.

Usage
-----
    periodic_timer_vs_rx_activity_check.py <rtl_file_or_dir> [--json]

Exit codes
----------
    0 = no unguarded periodic counters detected
    1 = one or more detected
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    register: str
    message: str


ALWAYS_HEAD_RE = re.compile(
    r"always\s*@\s*\(\s*posedge\b[^)]*\)\s*begin\b",
)

NBA_INC_RE = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*<=\s*\1\s*\+\s*[^;]+;",
)

# Counter names we treat as "periodic":
COUNTER_HINT_RE = re.compile(
    r"(_cnt|_counter|_timer|ito_|wake_|period_|keepalive_|hb_)",
    re.IGNORECASE,
)

# RX-activity gate signal names.
RX_SIGNAL_PATTERNS = [
    r"\brx\b", r"_rx\b", r"\brx_",
    r"_valid\b", r"\bvalid\b",
    r"br_i\b", r"br_o\b", r"\bbr\b",
    r"byte_valid", r"bit_valid",
    r"_active", r"cmd_valid",
    r"bus_active",
    r"id_bus_rx", r"sda_rx", r"sdi_rx",
]
RX_SIGNAL_RE = re.compile("|".join(RX_SIGNAL_PATTERNS))

SILENCE_RE = re.compile(r"//\s*periodic-timer-rx-reset-ok\b")

# Clock-divider recognition (mirrors sdc_gen._find_register_divided_clocks,
# which recognises  always @(posedge clk) DIV <= ~DIV ).  A register that is
# toggled (`reg <= ~reg`) by the counter's expiry path is a DIVIDED CLOCK, not
# an autonomous TX event.  Likewise a 1-cycle tick (`tick <= 1'b1`) that only
# *derives* such a divided clock is a clock-divider artifact.
#
# This is the false-fire we must exclude GENERALLY: a `_cnt` register whose
# expiry path only toggles a clock-like reg or pulses a 1-cycle tick, and which
# does NOT gate a TX / output-enable / packet-send event, is a clock divider,
# not a periodic-TX wake/keepalive timer.
TOGGLE_RE = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*<=\s*~\s*\1\b",
)
# A 1-cycle tick assignment: `<reg> <= 1'b1;` / `<reg> <= 1;` / `<reg> <= 1'd1;`
TICK_SET_RE = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*<=\s*(?:1\s*'[bhdoBHDO]\s*1|1)\s*;",
)

# Names that denote a genuine TX / drive / send / output-enable event — if the
# counter's expiry path gates ANY of these, it is a real periodic-TX timer and
# we must NOT silence it.  chip-AGNOSTIC, name-shape based.
TX_EVENT_NAME_RE = re.compile(
    r"(tx|wake|keepalive|hb_|heartbeat|drive|send|"
    r"_oe\b|oe_|output_en|out_en|_pulse\b|pulse_|req\b|_req|"
    r"frame_start|sof\b|packet|presence|expired|expire)",
    re.IGNORECASE,
)


def _reg_is_divided_clock(body: str, reg: str) -> bool:
    """Return True when `reg` (the counter) is, structurally, the prescaler of
    a register-divided clock — i.e. the counter's expiry path only toggles a
    clock-like reg (`clk_reg <= ~clk_reg`) and/or pulses a 1-cycle tick that is
    used to derive that divided clock, and does NOT gate a TX/output-enable/
    packet-send event.

    Mirrors sdc_gen._find_register_divided_clocks (which keys on the
    `DIV <= ~DIV` toggle).  Structural & chip-AGNOSTIC.
    """
    # The block must contain a self-toggle `X <= ~X` (the divided clock).  No
    # toggle anywhere in the block ⇒ not a clock divider.
    toggles = [m.group(1) for m in TOGGLE_RE.finditer(body)
               if m.group(1) != reg]
    if not toggles:
        return False

    # Locate the counter's expiry branch: `if (<reg> == ...)`.  This is where
    # a periodic timer would fire its event.  If we cannot find an explicit
    # compare on `reg`, fall back to "the block contains a toggle" (a pure
    # `DIV <= ~DIV` divider with no compare) — that is still a divider.
    expiry_re = re.compile(
        rf"\b{re.escape(reg)}\s*==", )
    em = expiry_re.search(body)
    if em is None:
        # No `reg == N` compare; the only way `reg` matters is as the toggle
        # prescaler.  Already proven a toggle exists ⇒ clock divider.
        return True

    # Slice the statement that the expiry compare guards.  We take the body
    # from the matching `if (...)` through the next branch keyword / block end
    # so we can inspect exactly what the expiry path does.
    if_start = body.rfind("if", 0, em.start())
    if if_start < 0:
        if_start = em.start()
    region = body[if_start:]
    # Cut the region at the next `end else` / `else if` / trailing `end` so we
    # examine only the expiry branch's assignments.  Rough but structural.
    cut = len(region)
    for kw in (r"\bend\s+else\b", r"\belse\s+if\b", r"\belse\b"):
        m = re.search(kw, region[len(reg):])
        if m:
            cut = min(cut, len(reg) + m.start())
    expiry_branch = region[:cut]

    # Collect everything ASSIGNED (NBA) in the expiry branch.
    assigned = set(
        m.group(1)
        for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*<=", expiry_branch)
    )
    # Names the expiry path drives, excluding the counter itself.
    driven = {a for a in assigned if a != reg}

    # If the expiry path gates a TX / output-enable / packet-send event, it is
    # a REAL periodic-TX timer — do NOT treat as a clock divider.
    for name in driven:
        if TX_EVENT_NAME_RE.search(name):
            return False

    # Every driven signal must be either the clock-like toggle reg or a tick
    # set to a 1-cycle pulse (clock-derivation artifact). If something else is
    # driven that we can't classify as clock/tick, be conservative and do NOT
    # silence.
    toggle_set = set(toggles)
    tick_set = set(m.group(1) for m in TICK_SET_RE.finditer(expiry_branch))
    for name in driven:
        if name in toggle_set:
            continue
        if name in tick_set:
            continue
        # Unknown driven signal in the expiry path ⇒ not a pure clock divider.
        return False
    # Expiry path only toggles a clock reg and/or pulses a derivation tick, and
    # gates no TX event ⇒ this is a clock divider, not a periodic-TX timer.
    return len(driven) > 0


def _strip_comments_keep_silence(src: str) -> tuple[str, set[int]]:
    src_no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    silence_lines = set()
    for i, line in enumerate(src_no_block.splitlines(), start=1):
        if SILENCE_RE.search(line):
            silence_lines.add(i)
    analysis = re.sub(r"//[^\n]*", "", src_no_block)
    return analysis, silence_lines


def _line_of(src: str, off: int) -> int:
    return src.count("\n", 0, off) + 1


def _find_always_blocks(src: str):
    for head in ALWAYS_HEAD_RE.finditer(src):
        body_start = head.end()
        depth = 1
        for tok in re.finditer(r"\b(begin|end)\b", src[body_start:]):
            if tok.group(1) == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    yield body_start, body_start + tok.start()
                    break


def _counter_has_rx_reset(body: str, reg: str) -> bool:
    """Check whether body contains `if (<rx_signal>) <reg> <= 0`-style
    reset — i.e., a branch that is:
      1. controlled by an RX-activity signal, AND
      2. assigns `reg <= 0` (or `reg <= N'd0`).
    Approximation: find `reg <= 0` assignments and check if the
    nearest containing `if (...)` condition mentions an RX signal.
    """
    # Find all reg-reset-to-zero assignments.
    reset_re = re.compile(
        rf"\b{re.escape(reg)}\s*<=\s*(?:\d+\s*'[bhdoBHDO]\s*0|0)\s*;",
    )
    for rm in reset_re.finditer(body):
        # Walk backwards from rm.start() to find the nearest `if (...)`
        # whose body encloses this assignment.
        prefix = body[:rm.start()]
        # Find all `if (` positions
        if_positions = [m.start() for m in re.finditer(r"\bif\s*\(", prefix)]
        if not if_positions:
            continue
        # Walk from last to first, check each — find one whose cond
        # references an rx-like signal.
        for ip in reversed(if_positions):
            # Grab the cond expression between the matching ( and ).
            # Skip if inside an else branch (rough check).
            cond_m = re.match(
                r"if\s*\((?P<cond>[^)]*)\)",
                body[ip:]
            )
            if not cond_m:
                continue
            cond = cond_m.group("cond")
            if RX_SIGNAL_RE.search(cond):
                return True
            # Exclude `if (!rstn)` / `if (!porb)` — those aren't
            # RX-activity gates. Keep searching other ifs.
    return False


def _counter_gates_tx_event(reg: str, body: str, file_src: str) -> bool:
    """Return True only when `reg` actually GATES a TX / drive / send / wake /
    keepalive / output-enable event — the necessary precondition for the
    periodic-collision hazard this check guards against (module docstring:
    'a periodic counter that fires autonomous TX events').

    Without this, the check false-positives on every NBA-self-incremented
    counter unrelated to a shared bus — a CPU's bit-serial operation-cycle
    counter (SERV `o_cnt`), a generic loop/index counter, a datapath
    accumulator. Those gate internal sequencing, not autonomous TX, so an
    RX-reset on them is meaningless.

    Two coupling shapes (chip-AGNOSTIC, name-shape based):
      (1) the counter's EXPIRY branch (`if (reg == N)` / `reg >= N`) drives a
          TX-event-named signal — the classic wake/keepalive expiry pulse. The
          compare and the TX-drive are typically SEPARATE statements within the
          same branch, so we slice the branch and scan its NBA targets.
      (2) reg co-occurs with a TX-event name in a single expression (e.g. a
          continuous assign `assign tx_send = (reg == N);`).
    """
    reg_re = re.escape(reg)

    # (1) Expiry-branch drive: find `if (... reg <relop> N ...)` and inspect the
    #     branch it guards for a TX-event-named NBA target.
    for em in re.finditer(rf"\b{reg_re}\s*(?:==|>=|>|<=|<)\s*\w", body):
        if_start = body.rfind("if", 0, em.start())
        start = if_start if if_start >= 0 else em.start()
        region = body[start:]
        cut = len(region)
        for kw in (r"\bend\s+else\b", r"\belse\s+if\b", r"\belse\b"):
            m = re.search(kw, region[len(reg):])
            if m:
                cut = min(cut, len(reg) + m.start())
        branch = region[:cut]
        for am in re.finditer(r"\b([a-zA-Z_]\w*)\s*<=", branch):
            tgt = am.group(1)
            if tgt != reg and TX_EVENT_NAME_RE.search(tgt):
                return True

    # (2) Single-expression coupling anywhere in the module (continuous assign /
    #     combinational gate of a TX-named signal by reg).
    for stmt in re.split(r"[;\n]", file_src):
        if not re.search(rf"\b{reg_re}\b", stmt):
            continue
        residual = re.sub(rf"\b{reg_re}\s*<=", "", stmt)  # drop reg's own NBA
        residual = re.sub(rf"\b{reg_re}\b", "", residual)
        if TX_EVENT_NAME_RE.search(residual) and ("==" in stmt or ">=" in stmt
                                                  or "assign" in stmt):
            return True
    return False


def check_file(path: Path) -> list[Finding]:
    raw = path.read_text(errors="replace")
    src, silence_lines = _strip_comments_keep_silence(raw)
    findings: list[Finding] = []

    for bs, be in _find_always_blocks(src):
        body = src[bs:be]
        for inc_m in NBA_INC_RE.finditer(body):
            reg = inc_m.group(1)
            # Only interested in "counter-like" registers.
            if not COUNTER_HINT_RE.search(reg):
                # Allow generic `cnt` too.
                if reg.lower() not in ("cnt", "tick", "count"):
                    continue
            inc_line = _line_of(src, bs + inc_m.start())
            if inc_line in silence_lines:
                continue
            if _counter_has_rx_reset(body, reg):
                continue
            # Exclude clock-divider counters generally: a counter whose expiry
            # path only toggles a clock-like reg (`reg <= ~reg`) or pulses a
            # 1-cycle derivation tick, and which gates no TX/output-enable/
            # packet-send event, is a clock divider — not a periodic-TX
            # wake/keepalive timer. (Mirrors sdc_gen._find_register_divided
            # _clocks.)
            if _reg_is_divided_clock(body, reg):
                continue
            # v0.2.55 — REQUIRE TX-coupling. The collision hazard only exists if
            # the counter gates an autonomous TX/drive/send/wake/keepalive event
            # on a shared bus. A counter that gates no TX event (CPU cycle
            # counter, loop index, accumulator) is not a periodic-TX timer and
            # must not be flagged. chip-AGNOSTIC: name-shape coupling only.
            if not _counter_gates_tx_event(reg, body, src):
                continue
            findings.append(Finding(
                "WARN", "periodic_timer_no_rx_reset",
                str(path), inc_line, reg,
                f"Counter `{reg}` is NBA-self-incremented (`{reg} <= {reg} "
                f"+ ...`) but has no reset branch guarded by an RX-activity "
                f"signal. If `{reg}` gates a periodic TX event (wake pulse, "
                f"keepalive), on a shared bidirectional wire it will "
                f"eventually phase-lock with the host's periodic cmd and "
                f"collide every cycle. Fix: add a branch like "
                f"`if (bus_active_i) {reg} <= 0;` or `if (cmd_valid) {reg} "
                f"<= 0;`. Silence with `// periodic-timer-rx-reset-ok` if "
                f"this counter is not coupled to a shared bus.",
            ))
    return findings


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*")
            if p.is_file() and p.suffix in (".v", ".sv", ".vh")
        )
    return []


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Require NBA-incremented periodic counters to reset on RX activity.",
    )
    ap.add_argument("target", help="RTL file or directory.")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"error: not found: {target}", file=sys.stderr)
        return 2

    files = collect_files(target)
    if not files:
        print(f"error: no .v/.sv/.vh under {target}", file=sys.stderr)
        return 2

    all_findings: list[Finding] = []
    for f in files:
        all_findings.extend(check_file(f))
    warnings = [f for f in all_findings if f.severity == "WARN"]

    if args.json:
        _txt = json.dumps({
            "target": str(target),
            "scanned": len(files),
            "total_findings": len(all_findings),
            "warnings": len(warnings),
            "findings": [asdict(f) for f in all_findings],
            "verdict": "PASS" if not warnings else "FAIL",
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(_txt + "\n")
    else:
        for f in all_findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line} ({f.register})")
            print(f"        {f.message}")
        print(f"\n{len(warnings)} warning(s) across {len(files)} file(s)")
        print("PASS" if not warnings else "FAIL")

    return 0 if not warnings else 1


if __name__ == "__main__":
    sys.exit(main())
