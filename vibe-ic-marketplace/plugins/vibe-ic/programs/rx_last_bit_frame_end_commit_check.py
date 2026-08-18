#!/usr/bin/env python3
"""rx_last_bit_frame_end_commit_check.py — Wave 29 (v0.119.61) gate.

PRIMARY Wave 29 gate.  Enforces that the RX FSM does not silently
lose the last bit of a frame whose final bit is followed by host
bus-release rather than another bit.

Background
----------
Wave 28 reference TB (v0.119.60) deterministic-ally surfaced the
v0.119.59 silent bug after 33 prior hardware FAIL attempts:

    rtl/main_fsm.sv:421 — S_RX_HIGH state body classifies bits only
    on the NEXT `if (rx_low)` (i.e. on the next falling edge).  For
    a 1-byte cmd frame, after the last bit's LOW pulse the host
    releases the bus → no further falling edge ever comes.  The FSM
    sits in S_RX_HIGH waiting for an edge that never arrives, then
    the high-counter timeout fires and transitions to
    S_RX_FRAME_END → S_VALIDATE — but the FRAME_END arm body is a
    bare ``high_cnt <= '0;`` no-op without committing the pending
    bit.  So the RX assembler thinks the frame had only 7 bits, CRC
    validate FAILs, dispatch never fires, TX state never entered,
    DUT silent → host pads byte[6]=0x02.

This is a fully chip-AGNOSTIC anti-pattern: any RX FSM that
classifies bits only on the next falling edge (not on the rising
edge of the current bit's LOW phase ending) MUST carry a frame-end
commit path.  Otherwise the last bit of every frame whose final bit
is followed by bus release is dropped.

Correct patterns
----------------

Pattern A (rising-edge classify, vendor style — most robust)::

    S_RX_LOW: begin
      // count LOW duration
      if (rx_high_edge) begin
        // LOW pulse just ended — classify NOW
        if      (low_cnt < BIT1_MAX) bit_value = 1;
        else if (low_cnt < BIT0_MAX) bit_value = 0;
        else                         bit_value = BR;
        byte_buf[bit_idx] <= bit_value;
        bit_idx           <= bit_idx + 1;
        state             <= S_RX_HIGH;  // wait for next bit OR end
      end
    end

Pattern B (next-edge classify with frame-end commit, fallback)::

    S_RX_HIGH: begin
      if (rx_low) begin
        // classify previous LOW pulse via low_cnt_prev
        byte_buf[bit_idx] <= classified;
        bit_idx           <= bit_idx + 1;
        state             <= S_RX_LOW;
      end else if (high_cnt > FRAME_END_TICKS) begin
        // frame-end timeout — MUST commit pending bit
        if (bit_idx > 0) byte_buf[bit_idx-1] <= last_classified_bit;
        state <= S_VALIDATE;
      end
    end

Detection algorithm
-------------------
1. Locate FSM RTL files under ``<project>/rtl/`` (or ``src/`` /
   ``hdl/``) using filename heuristics + state-name heuristics.
2. For each FSM file extract every state-arm body via the same
   crude case-arm walker used elsewhere.  Identify states whose
   names match RX shapes:
      RX_HIGH:       /S_RX_HIGH$/ /RX_HIGH/ /HIGH_PHASE/ /HIGH$/
      RX_LOW:        /S_RX_LOW$/ /RX_LOW/ /LOW_PHASE/ /LOW$/
      FRAME_END:     /FRAME_END/ /FRAME_DONE/ /RX_DONE/ /RX_TIMEOUT/
                       /RX_END/ /VALIDATE_PRE/
3. Decide the classification mode:
     a) RISING_EDGE — the RX_LOW (or equivalent) state body assigns
        ``byte_buf[...]`` / ``shift_*[...]`` / ``rx_data[...]``
        when an ``rx_high`` / rising-edge condition fires inside it.
     b) NEXT_EDGE — the RX_HIGH state body has an ``if (rx_low)``
        guard that does the classification (assigns to a byte
        buffer) — and the corresponding RX_LOW body does NOT.
4. If RISING_EDGE → PASS (Pattern A).
5. If NEXT_EDGE → require the FRAME_END-class state(s) to commit
   the pending bit before transitioning to a VALIDATE-class state.
   "Commit pending bit" = an assignment matching one of:
      byte_buf[bit_idx-1]   <= ...
      byte_buf[bit_idx]     <= ...
      shift_*[bit_idx[...]] <= ...
      rx_data[bit_idx]      <= ...
   AND a guard like ``if (bit_idx > 0)`` / ``if (bit_idx != 0)`` /
   ``if (|bit_idx)``.  We accept any of those forms.
6. **FAIL** when NEXT_EDGE-mode AND the frame-end arm body has no
   recognised commit pattern.
7. SKIP gracefully when no RX_HIGH-class or RX_LOW-class state is
   found, or when no FSM file can be identified.
8. Honors waiver ``rx_last_bit_loss_intentional`` (≥40 chars).

Usage
-----
    python3 rx_last_bit_frame_end_commit_check.py <project_dir>
        [--json <out>]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER
    1 — FAIL
    2 — usage / IO error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


WAIVER_KEY = "rx_last_bit_loss_intentional"
WAIVER_MIN = 40


# FSM file recognition (mirrors send_test_active_drive_check) -----------
FSM_FILENAME_PATTERNS = (
    re.compile(r"main_fsm",      re.I),
    re.compile(r"\bmac\b",       re.I),
    re.compile(r"cmd[_]?fsm",    re.I),
    re.compile(r"top[_]?fsm",    re.I),
    re.compile(r"ctrl.*fsm",     re.I),
    re.compile(r"protocol.*fsm", re.I),
    re.compile(r"rx[_]?fsm",     re.I),
)

# State-name classifiers (chip-agnostic).
_RX_HIGH_RE  = re.compile(r"^S?_?RX_?HIGH(?:_PHASE)?$|HIGH_PHASE$",
                          re.I)
_RX_LOW_RE   = re.compile(r"^S?_?RX_?LOW(?:_PHASE)?$|LOW_PHASE$",
                          re.I)
_RX_FRAME_END_RE = re.compile(
    r"FRAME_END|FRAME_DONE|RX_DONE|RX_TIMEOUT|RX_END|"
    r"VALIDATE_PRE|FRAME_TIMEOUT",
    re.I,
)
_VALIDATE_RE = re.compile(r"VALIDATE|CHECK_CRC|CRC_VALIDATE", re.I)

_STATE_ARM_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*:\s*begin\b",
)
_STATE_ASSIGN = re.compile(
    r"\bstate\s*<=\s*([A-Za-z_]\w*)\s*[;,)]?",
)
_NEXT_STATE_ASSIGN = re.compile(
    r"\bnext_state\s*=\s*([A-Za-z_]\w*)\s*[;,)]?",
)

# RX byte-buffer write patterns: byte_buf[...] <= ... / shift_byte[...]
# <= ... / rx_data[...] <= ... / rx_buf[...] <= ...
_BYTE_BUF_WRITE = re.compile(
    r"\b("
    r"byte_buf|byte_buffer|shift_byte|shift_reg|rx_byte|"
    r"rx_data|rx_buf|rx_buffer|rx_shift|"
    r"data_buf|frame_buf|cap_byte|inbyte|in_byte"
    r")\s*\[",
    re.I,
)

# `rx_low` / `rx_high` event-style guards
_RX_LOW_GUARD = re.compile(r"\bif\s*\(\s*rx_low\b", re.I)
_RX_HIGH_GUARD = re.compile(r"\bif\s*\(\s*rx_high\b", re.I)
# rising-edge / falling-edge synthetic event signals
_RX_HIGH_EDGE = re.compile(r"\b(rx_high_edge|rx_rising|rx_posedge)\b",
                            re.I)
_RX_LOW_EDGE = re.compile(r"\b(rx_low_edge|rx_falling|rx_negedge)\b",
                           re.I)

# Frame-end commit guard: `if (bit_idx > 0)` / `if (bit_idx != 0)` /
# `if (|bit_idx)` etc.  Bit-counter name is one of:
_BIT_COUNTER_NAMES = (
    "bit_idx", "bit_cnt", "bitcnt", "bit_counter", "bit_pos",
)
_BIT_COUNTER_GROUP = "(?:" + "|".join(_BIT_COUNTER_NAMES) + ")"
_FRAME_END_COMMIT_GUARD = re.compile(
    rf"\bif\s*\(\s*"
    rf"(?:"
    rf"{_BIT_COUNTER_GROUP}\s*[!]?=\s*\d+|"
    rf"{_BIT_COUNTER_GROUP}\s*>\s*\d+|"
    rf"\|\s*{_BIT_COUNTER_GROUP}|"
    rf"{_BIT_COUNTER_GROUP}\s*\["
    rf")",
    re.I,
)
# ANY use of bit_idx-1 / bit_idx[...]-1 in an assignment LHS index
_FRAME_END_COMMIT_LHS = re.compile(
    rf"\[\s*{_BIT_COUNTER_GROUP}\s*-\s*1\s*\]",
    re.I,
)


def waived(project: Path) -> tuple[bool, str]:
    p = project / "waivers.json"
    if not p.exists():
        return False, ""
    try:
        d = json.loads(p.read_text())
        v = d.get(WAIVER_KEY)
        if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
            return True, v.strip()
    except Exception:
        pass
    return False, ""


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _find_rtl_dir(project: Path) -> Path | None:
    for cand in ("phase2/stage1/rtl", "rtl", "src", "hdl"):
        d = project / cand
        if d.is_dir():
            files = list(d.rglob("*.v")) + list(d.rglob("*.sv"))
            if files:
                return d
    if any(project.glob("*.v")) or any(project.glob("*.sv")):
        return project
    return None


def _find_fsm_files(project: Path) -> list[Path]:
    rtl_dir = _find_rtl_dir(project)
    if rtl_dir is None:
        return []
    cands = list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv"))
    out: list[Path] = []
    for f in cands:
        if not f.is_file():
            continue
        n = f.name.lower()
        if "_tb" in n or n.startswith("tb_") or "testbench" in n:
            continue
        if any(p.search(n) for p in FSM_FILENAME_PATTERNS):
            out.append(f)
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Fallback: file with both S_RX* and S_TX* / RX_* + LOW/HIGH
        if (re.search(r"\bRX_HIGH\b", text)
                and re.search(r"\bRX_LOW\b", text)):
            out.append(f)
    return out


def _split_state_arms(text: str) -> dict[str, tuple[int, str]]:
    """state_name -> (start_line, body_text). Crude depth-tracking
    case-arm splitter."""
    arms: dict[str, tuple[int, str]] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _STATE_ARM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        sname = m.group(1)
        depth = 1
        body_lines: list[str] = []
        j = i + 1
        while j < len(lines) and depth > 0:
            ln = lines[j]
            for tok in re.findall(
                    r"\b(begin|case|fork|end|endcase|join)\b", ln):
                if tok in ("begin", "case", "fork"):
                    depth += 1
                elif tok in ("end", "endcase", "join"):
                    depth -= 1
                    if depth == 0:
                        break
            if depth == 0:
                break
            body_lines.append(ln)
            j += 1
        arms[sname] = (i + 1, "\n".join(body_lines))
        i = j + 1
    return arms


def _all_state_arms(text: str) -> list[tuple[str, int, str]]:
    """Return [(state_name, start_line, body), ...] including arms
    whose names appear multiple times across separate `case` blocks
    (next-state combinational vs sequential body).  We need both."""
    out: list[tuple[str, int, str]] = []
    arms_dict = _split_state_arms(text)
    for name, (ln, body) in arms_dict.items():
        out.append((name, ln, body))
    return out


def _next_state_targets(body: str) -> set[str]:
    """All state targets reachable from this arm via either
    sequential (`state <=`) or combinational (`next_state =`)
    assignments."""
    out: set[str] = set()
    for m in _STATE_ASSIGN.finditer(body):
        out.add(m.group(1))
    for m in _NEXT_STATE_ASSIGN.finditer(body):
        out.add(m.group(1))
    return out


def _classify_rx_mode(arms: list[tuple[str, int, str]]) -> str:
    """Return 'RISING_EDGE', 'NEXT_EDGE', or 'UNKNOWN'."""
    rx_high_bodies = [body for name, _, body in arms
                      if _RX_HIGH_RE.match(name)]
    rx_low_bodies = [body for name, _, body in arms
                     if _RX_LOW_RE.match(name)]
    if not rx_high_bodies and not rx_low_bodies:
        return "UNKNOWN"

    # RISING_EDGE indicators in RX_LOW body: rx_high guard or
    # rx_high_edge token + a byte-buf write in same body.
    for body in rx_low_bodies:
        if (_RX_HIGH_GUARD.search(body) or _RX_HIGH_EDGE.search(body)):
            if _BYTE_BUF_WRITE.search(body):
                return "RISING_EDGE"

    # NEXT_EDGE indicators in RX_HIGH body: rx_low guard + byte-buf
    # write inside that guard.
    for body in rx_high_bodies:
        if _RX_LOW_GUARD.search(body) and _BYTE_BUF_WRITE.search(body):
            return "NEXT_EDGE"

    return "UNKNOWN"


def _frame_end_arms(arms: list[tuple[str, int, str]]
                    ) -> list[tuple[str, int, str]]:
    return [a for a in arms if _RX_FRAME_END_RE.search(a[0])]


def _arm_commits_pending_bit(body: str) -> bool:
    """Detect a frame-end arm body that commits the in-progress bit."""
    # Either we see a guard like `if (bit_idx > 0)` AND a byte-buf
    # write, OR we see a direct LHS index `byte_buf[bit_idx-1]`.
    if _FRAME_END_COMMIT_LHS.search(body):
        return True
    if (_FRAME_END_COMMIT_GUARD.search(body)
            and _BYTE_BUF_WRITE.search(body)):
        return True
    return False


def check(project: Path) -> dict:
    out: dict = {
        "program": "rx_last_bit_frame_end_commit_check",
        "pass": True,
        "findings": [],
        "warnings": [],
    }
    fsm_files = _find_fsm_files(project)
    out["fsm_files"] = [str(f.relative_to(project))
                         for f in fsm_files]
    if not fsm_files:
        out["skip_reason"] = "no FSM-like RTL file found"
        return out

    found_any_rx = False
    for f in fsm_files:
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = _strip_comments(raw)
        arms = _all_state_arms(text)

        # Are there any RX states at all?
        rx_states = [a for a in arms
                     if _RX_HIGH_RE.match(a[0]) or _RX_LOW_RE.match(a[0])]
        if not rx_states:
            continue
        found_any_rx = True

        mode = _classify_rx_mode(arms)
        if mode == "RISING_EDGE":
            # Pattern A — PASS this file.
            continue

        if mode != "NEXT_EDGE":
            # Could not classify with confidence — skip this file
            # rather than emit a false positive.
            continue

        # NEXT_EDGE mode.  Locate the dispatch line of RX_HIGH guard.
        rx_high_arm = next((a for a in arms
                            if _RX_HIGH_RE.match(a[0])), None)
        rx_high_lineno = (rx_high_arm[1] if rx_high_arm else 0)

        # Find frame-end-class arms.  Two cases:
        #   (a) explicit FRAME_END/RX_DONE/RX_TIMEOUT arm exists →
        #       inspect that body.
        #   (b) no explicit frame-end arm — RX_HIGH transitions
        #       directly to VALIDATE on high_cnt timeout.  In that
        #       case the commit must live in RX_HIGH's else-branch
        #       (we look for the same commit pattern there).
        fe_arms = _frame_end_arms(arms)
        committed = False
        fe_lineno = None
        if fe_arms:
            for name, ln, body in fe_arms:
                # If this frame-end arm transitions to validate AND
                # commits pending bit → OK.
                next_states = _next_state_targets(body)
                goes_to_validate = any(_VALIDATE_RE.search(s)
                                       for s in next_states)
                # If we can't see next_state here, it's still
                # legitimate to require commit in the body.
                if _arm_commits_pending_bit(body):
                    committed = True
                    break
                # If this arm doesn't transition to validate
                # downstream, skip it (it's not the fail-end path).
                if not goes_to_validate and not next_states:
                    # Inconclusive — keep checking.
                    fe_lineno = fe_lineno or ln
                else:
                    fe_lineno = fe_lineno or ln

        # Also check inside RX_HIGH body: an else-branch commit
        # (frame-end timeout-in-place pattern) is acceptable.
        if not committed and rx_high_arm is not None:
            _name, _ln, body = rx_high_arm
            # If the body has the commit pattern (LHS bit_idx-1 or
            # guard-and-write) AND a transition to VALIDATE/FRAME_END
            # in an else-if branch, accept.
            if _arm_commits_pending_bit(body):
                committed = True

        if committed:
            continue

        # FAIL — NEXT_EDGE mode without any frame-end commit.
        rel = str(f.relative_to(project))
        msg = (
            f"FAIL — RX_LAST_BIT_FRAME_END_COMMIT_MISSING\n"
            f"  {rel}:{rx_high_lineno} — RX_HIGH state body "
            f"classifies bits via `if (rx_low)` (next-edge mode).\n"
            + (f"  {rel}:{fe_lineno} — frame-end / timeout arm "
               f"transitions to validate without committing the "
               f"in-progress bit.\n"
               if fe_lineno else
               f"  {rel} — no frame-end / timeout arm commits the "
               f"in-progress bit.\n")
            + (
                "  Effect: last bit of any frame whose final bit is "
                "followed by bus release (not another bit) will be "
                "lost. CRC validate fails on truncated frame.\n"
                "  Fix options:\n"
                "  (A) Classify bit on rising edge of LOW pulse "
                "(when low_cnt resolves), not on next falling edge.\n"
                "  (B) In frame-end timeout path, commit pending bit "
                "before going to validate:\n"
                "      if (bit_idx > 0) "
                "byte_buf[bit_idx-1] <= last_classified_bit;"
            )
        )
        out["findings"].append({
            "rule": "RX_LAST_BIT_FRAME_END_COMMIT_MISSING",
            "severity": "FAIL",
            "message": msg,
            "file": rel,
            "rx_high_line": rx_high_lineno,
            "frame_end_line": fe_lineno,
        })

    if not found_any_rx:
        out["skip_reason"] = (
            "no RX_HIGH / RX_LOW state found in any FSM file")
        return out

    if out["findings"]:
        out["pass"] = False
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    result = check(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if "skip_reason" in result:
        print(f"PASS_SKIP — {result['skip_reason']}")
        return 0

    if result["pass"]:
        print("PASS — RX FSM either rising-edge classifies (Pattern A) "
              "or has frame-end commit (Pattern B)")
        return 0

    is_waived, why = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(result['findings'])} finding(s); "
            f"waiver `{WAIVER_KEY}` set: {why[:80]}…")
        for f in result["findings"]:
            print(f"  • {f['rule']} — {f['file']}:{f['rx_high_line']}")
        return 0

    print(f"FAIL — {len(result['findings'])} RX last-bit frame-end "
          f"commit violation(s)")
    for f in result["findings"]:
        print(f"FAIL: {f['rule']} — {f['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
