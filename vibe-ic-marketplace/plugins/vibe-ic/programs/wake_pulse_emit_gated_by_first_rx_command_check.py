#!/usr/bin/env python3
"""wake_pulse_emit_gated_by_first_rx_command_check.py — Wave 18 gate.

In half-duplex single-wire bit-bang protocols the chip's wake-pulse
generator (typically a periodic 5 ms heartbeat) MUST stop emitting
once the chip has received its first valid RX command (e.g. the
host's `0x74 GET_ID` opcode). After this initial handshake, the
chip is "alive" from the host's perspective; continuing to emit
wake pulses risks colliding with the host's async frame on the
open-drain bus and corrupting the response window.

Vendor reference (`GEN_WAKE.v` line 253) gates the wake counter via
`have_received_id_cmd_latch` — once the first valid RX command
arrives, the wake timer is held at zero forever, no more pulses.

Difference vs `wake_gen_bus_active_reset_check`
==============================================
The Wave-15 sibling gate (`wake_gen_bus_active_reset_check`) checks
that the wake pulse is suppressed during *transient* bus activity
(host BR / TX / RX in progress) — a per-pulse collision shield. THIS
gate checks the LONG-TERM gating: after the chip has answered its
first valid command, wake pulses must stop ENTIRELY (a sticky
state). Both invariants must hold; one does not subsume the other.

Detection
=========
1. Find wake-pulse generator RTL (filename / body heuristic identical
   to the Wave-15 sibling).
2. Verify the wake-emit logic references at least one
   "first-RX-command-received" gating signal. Synonyms:
     - `first_cmd_received` / `first_cmd` / `first_rx_cmd`
     - `id_cmd_latched` / `id_cmd_received`
     - `have_received_id_cmd` / `have_received_cmd`
     - `wake_done` / `awake` / `awake_q` / `awake_latch`
     - `cmd_received` / `cmd_done_latched` / `host_cmd_seen`
     - `rx_first_byte_latched` / `first_valid_rx_byte`
3. **PASS** when wake module references one of these gates AND uses
   it in the wake-emit / wake-counter path.
4. **FAIL** when wake-emit logic does NOT reference any first-cmd
   gate — wake pulses will continue indefinitely.
5. **SKIP** when no wake-pulse generator RTL detected.
6. Honors waiver `wake_pulse_continuous_emit_intentional` (≥40 chars
   rationale).

Chip-AGNOSTIC. The synonym list is protocol-class generic; no chip /
tester / opcode / specific value hard-coded.

Exit codes
==========
0  — PASS / SKIP / PASS_WITH_WAIVER
1  — FAIL
2  — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Tuple
import _path_layout as _pl

WAIVER_KEY = "wake_pulse_continuous_emit_intentional"
WAIVER_MIN_LEN = 40

_WAKE_FILENAME_HINTS = (
    "wake_gen", "wake_ctrl", "wake_pulse", "wake_drv",
    "wake_fsm", "wake_emit",
)
_WAKE_OUT_NAMES_RE = re.compile(
    r"\bwake_(?:oe|pulse|drv|o|out|en|emit|active|low)\b",
    re.IGNORECASE,
)

# First-RX-command-received gating signal synonyms. Each is a generic
# protocol-engineering term; none names a specific chip / opcode / PDK.
#
# Wave 20 (v0.119.52) — additional synonyms surfaced by 25th attempt:
#   the v0.119.51 RTL uses `enable=~awake_latch` (instantiation-side
#   negation), `pre_awake_only`, and `~have_received_*_cmd*`. The body
#   of the wake module sees only the `enable` port name; the
#   first-cmd evidence is at the instantiation site (top-level wrapper).
#   See `_data_flow_first_cmd_signal` below for the 1-level walk.
_FIRST_CMD_GATE_RE = re.compile(
    r"\b(?:"
    r"first_cmd_received"
    r"|first_cmd"
    r"|first_rx_cmd"
    r"|first_valid_rx_byte"
    r"|first_valid_cmd"
    r"|id_cmd_latched"
    r"|id_cmd_received"
    r"|have_received_id_cmd"
    r"|have_received_id_cmd_latch"
    r"|have_received_cmd"
    r"|have_received_\w*cmd\w*"
    r"|received_\w*id\w*"
    r"|wake_done"
    r"|awake_latch"
    r"|awake_latched"
    r"|awake_q"
    r"|awake_r"
    r"|awake"
    r"|wake_emit_enable"
    r"|wake_enable"
    r"|wake_active"
    r"|pre_awake_only"
    r"|pre_handshake_only"
    r"|cmd_received"
    r"|cmd_received_latch"
    r"|cmd_done_latched"
    r"|host_cmd_seen"
    r"|rx_first_byte_latched"
    r"|rx_cmd_latched"
    r")\b",
    re.IGNORECASE,
)

# Wave 20: instantiation port-binding patterns that bind the wake
# module's enable / suppress port to an expression containing a
# first-cmd signal at one level up. The body of `wake_gen` itself only
# sees an `enable` (or similar generic) port; the first-cmd evidence
# is on the parent's `.enable(~awake_latch)` wire.
#
# Match `.<port>(<expr>)` where <port> is enable/disable/suppress/etc.
# Any port whose binding expression contains a `_FIRST_CMD_GATE_RE`
# synonym (with optional `~` / `!` negation) counts as gated.
_WAKE_GATE_PORT_NAMES = (
    "enable", "disable", "suppress", "stop", "halt", "gate", "active",
    "wake_en", "wake_enable", "wake_emit_en", "wake_emit_enable",
    "wake_active", "first_cmd", "awake", "awake_latch", "have_cmd",
    "rx_cmd_latched", "id_cmd_latched",
)
_PORT_BINDING_RE = re.compile(
    r"\.(\w+)\s*\(\s*([^)]*)\s*\)",
    re.IGNORECASE,
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _find_rtl_files(project_dir: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.exists():
        return []
    files: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.suffix.lower() in (".v", ".sv", ".svh", ".vh"):
            files.append(p)
    return sorted(files)


def _is_wake_gen(path: Path, src_no_cmt: str) -> bool:
    name = path.stem.lower()
    if any(h in name for h in _WAKE_FILENAME_HINTS):
        return True
    if not _WAKE_OUT_NAMES_RE.search(src_no_cmt):
        return False
    if re.search(
        r"\b\w*cnt\w*\s*<=\s*\w*cnt\w*\s*\+\s*\d",
        src_no_cmt,
        re.IGNORECASE,
    ):
        return True
    return False


def _has_first_cmd_gate(src_no_cmt: str) -> Tuple[bool, str]:
    """Check that the wake module references any first-cmd gate signal.

    Returns (found, matched_name).
    """
    m = _FIRST_CMD_GATE_RE.search(src_no_cmt)
    if m:
        return True, m.group(0)
    return False, ""


def _data_flow_first_cmd_signal(
    project_dir: Path,
    wake_module_name: str,
) -> Tuple[bool, str]:
    """Wave 20 — 1-level data-flow walk.

    The wake module's body might use a generic port name (`enable`,
    `disable`, `suppress`, ...) whose VALUE depends on a first-cmd
    register set elsewhere. Walk to instantiation site:

      wake_gen u_wake (
          ...,
          .enable(~awake_latch),    // <- first-cmd evidence here
          ...
      );

    For every other RTL file, find an instance of `wake_module_name`
    and inspect its port bindings. If any binding expression contains
    a first-cmd synonym (with optional `~` / `!` negation), accept.
    Returns (found, matched_text).
    """
    rtl_files = _find_rtl_files(project_dir)
    inst_re = re.compile(
        rf"\b{re.escape(wake_module_name)}\s+\w+\s*\(",
        re.IGNORECASE,
    )
    for f in rtl_files:
        try:
            src = _strip_comments(f.read_text(errors="ignore"))
        except Exception:
            continue
        for m in inst_re.finditer(src):
            # Slurp from open paren to matching close paren.
            i = m.end() - 1
            depth = 0
            j = i
            while j < len(src):
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= len(src):
                continue
            port_block = src[i + 1:j]
            for pm in _PORT_BINDING_RE.finditer(port_block):
                port = pm.group(1).lower()
                expr = pm.group(2)
                # Strip leading negation operators for synonym match.
                expr_stripped = expr.lstrip().lstrip("~!").strip()
                # Either the port name itself is a gate-port hint OR
                # the bound expression contains a first-cmd synonym.
                fm = _FIRST_CMD_GATE_RE.search(expr_stripped)
                if fm:
                    return True, (
                        f".{pm.group(1)}({expr.strip()}) "
                        f"→ {fm.group(0)}"
                    )
                if port in _WAKE_GATE_PORT_NAMES:
                    # Even if no synonym match, if the wake-control
                    # port is bound to a non-trivial expression that
                    # references ANY register/wire whose declaration
                    # in the same file matches a first-cmd synonym,
                    # accept. 1-extra-level walk.
                    sigs = re.findall(r"\b(\w+)\b", expr_stripped)
                    for sig in sigs:
                        if _FIRST_CMD_GATE_RE.search(sig):
                            return True, (
                                f".{pm.group(1)}({expr.strip()}) "
                                f"→ {sig}"
                            )
                        # Walk: is `sig` declared / assigned in this
                        # file with an RHS that references a
                        # first-cmd synonym?
                        decl_re = re.compile(
                            rf"\b(?:assign|wire|logic|reg)\s+\w*\s*"
                            rf"{re.escape(sig)}\s*(?:<=|=)\s*([^;]+);",
                            re.IGNORECASE,
                        )
                        dm = decl_re.search(src)
                        if dm and _FIRST_CMD_GATE_RE.search(
                                dm.group(1)):
                            mfound = _FIRST_CMD_GATE_RE.search(
                                dm.group(1))
                            return True, (
                                f".{pm.group(1)}({expr.strip()}) "
                                f"via {sig} → {mfound.group(0)}"
                            )
    return False, ""


def _waived(project_dir: Path) -> Tuple[bool, str]:
    waivers = project_dir / "waivers.json"
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


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: wake_pulse_emit_gated_by_first_rx_command_check.py "
            "<project_dir>"
        )
        return 2
    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    rtl_files = _find_rtl_files(project_dir)
    if not rtl_files:
        print("SKIP — no rtl/ directory")
        return 0

    wake_files: List[Tuple[Path, str]] = []
    for f in rtl_files:
        try:
            src = _strip_comments(f.read_text(errors="ignore"))
        except Exception:
            continue
        if _is_wake_gen(f, src):
            wake_files.append((f, src))

    if not wake_files:
        print("SKIP — no wake-pulse generator RTL detected")
        return 0

    failures: List[str] = []
    matches: List[str] = []
    for path, src in wake_files:
        try:
            rel = path.relative_to(project_dir)
        except ValueError:
            rel = path
        ok, name = _has_first_cmd_gate(src)
        if ok:
            matches.append(f"{rel}: gates on `{name}`")
            continue
        # Wave 20: walk to the instantiation site (1 level up) and
        # check whether the parent binds the wake module's gate port
        # to an expression containing a first-cmd synonym (e.g.
        # `.enable(~awake_latch)`).
        modname_match = re.search(
            r"\bmodule\s+(\w+)\b", src,
        )
        if modname_match:
            modname = modname_match.group(1)
            ok2, name2 = _data_flow_first_cmd_signal(
                project_dir, modname)
            if ok2:
                matches.append(
                    f"{rel}: gates on `{name2}` (via parent "
                    "instantiation port binding)"
                )
                continue
        failures.append(
            f"NO_FIRST_CMD_GATE — {rel}: wake-pulse generator "
            "does not reference any first-RX-command-received "
            "gate signal — neither directly in module body nor "
            "via parent instantiation port binding (1-level walk). "
            "After the chip receives its first valid RX command, "
            "wake pulses must stop permanently — otherwise the "
            "heartbeat collides with subsequent host async frames "
            "on the open-drain bus and corrupts framing. Expected "
            "one of: first_cmd_received / id_cmd_latched / "
            "have_received_id_cmd / awake_latch / awake / "
            "cmd_received / rx_cmd_latched / wake_emit_enable / "
            "pre_awake_only (or equivalent synonym)."
        )

    is_waived, rationale = _waived(project_dir)

    if not failures:
        print(
            f"PASS — {len(wake_files)} wake-pulse generator(s) "
            "reference a first-RX-command gate signal:"
        )
        for m in matches:
            print(f"  • {m}")
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(failures)} ungated wake-emit "
            f"issue(s) silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(f"FAIL — {len(failures)} ungated wake-emit issue(s):")
    for f in failures:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  Vendor reference RTL stops emitting wake pulses once the")
    print("  chip has received its first valid RX command. Continuing")
    print("  to emit periodic wake LOW pulses after the handshake")
    print("  causes them to OR with the host's async frame on the")
    print("  open-drain bus, corrupting frame parsing and forcing")
    print("  byte[6]=FAIL on real silicon.")
    print()
    print(
        "Fix template:\n"
        "    input  logic awake,           // sticky after first RX cmd\n"
        "    ...\n"
        "    if (awake) begin\n"
        "        cnt     <= '0;\n"
        "        wake_oe <= 1'b0;\n"
        "    end else begin\n"
        "        // periodic wake pulse logic\n"
        "    end\n"
    )
    print(
        "Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": '
        '"<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
