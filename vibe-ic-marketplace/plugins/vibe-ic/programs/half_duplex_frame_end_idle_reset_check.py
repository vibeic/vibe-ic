#!/usr/bin/env python3
"""
half_duplex_frame_end_idle_reset_check.py — structural-RTL gate for
half-duplex frame-end gap counters.

Why this gate exists
====================
A half-duplex chip uses an "idle gap counter" (commonly named gap_cnt,
frame_idle_cnt, eof_cnt) to detect end-of-frame: when the bus has been
HIGH continuously for more than FRAME_END_GAP cycles, the counter
fires and the chip transitions to S_DECODE.

The subtle bug a fresh agent often introduces is to reset the counter
ONLY on byte boundaries (rx_byte_vld / rx_br / tx_active) and to
increment it whenever id_bus_rx == 1, but to forget to reset it when
id_bus_rx == 0 (i.e. when a new bit's BIT_LOW pulse arrives).

Consequences
------------
The counter then accumulates HIGH cycles across multiple bits of a
multi-byte frame. After IBT (inter-byte gap, e.g. 21us) plus the
HIGH portion of the next byte's first bit (e.g. 8us), the cumulative
HIGH time crosses FRAME_END_GAP (e.g. 27us) and the chip falsely
detects end-of-frame mid-frame. The chip then sends a response while
the master is still transmitting, causing bus contention and a
silent functional failure that no static lint or simple sim catches.

This gate detects the pattern: a counter that increments under
id_bus_rx==1 inside an always_ff but has NO reset branch on
id_bus_rx==0 (or equivalent low-edge signal).

Usage
-----
python3 half_duplex_frame_end_idle_reset_check.py <project_dir>

Honors waivers.json with key "frame_end_idle_reset_alternative" if
the project uses a different mechanism (e.g. EOM bit in CRC byte).

Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional
import _path_layout as _pl


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def is_half_duplex(project_dir: Path) -> bool:
    """Heuristic: half-duplex if L2 has tSRS+ibt or if L3 has command_table.
    Searches both project_dir/ root and project_dir/generated_docs/."""
    candidates = [project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)]
    l2_keys = ("tSRS_us", "ibt_us", "frame_end_gap_us", "tSRS_min_us", "tSRS_max_us")
    for base in candidates:
        l2 = base / "L2_FRS.json"
        l3 = base / "L3_CMD_PROTOCOL.json"
        try:
            if l2.exists():
                d = json.loads(l2.read_text())
                if any(k in d for k in l2_keys):
                    return True
            if l3.exists():
                d = json.loads(l3.read_text())
                if isinstance(d.get("command_table"), list) and d["command_table"]:
                    return True
        except Exception:
            pass
    return False


def find_rtl_files(project_dir: Path):
    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.exists():
        return []
    return sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v")))


def find_idle_counters(src: str):
    """
    Locate counter-increment patterns where the counter is gated by a
    bus-HIGH signal (id_bus_rx, rx, etc.).

    v0.119.24 fix: previously walked the LAST 4 enclosing `if` conditions
    looking for any bus-HIGH reference, which falsely flagged
    pulse-width-measurement counters (counters that increment under
    `if (!id_bus_rx)` but happened to live inside an outer `if (id_bus_rx)`
    block elsewhere in the file). The semantic difference between an
    idle-gap counter and a pulse-measurement counter is the IMMEDIATELY
    enclosing condition — only that one matters for the rule.

    Returns list of dicts: {counter, guard_cond, file_text}.
    """
    results = []
    # Match "<cnt> <= <cnt> + 1" anywhere in the file.
    for inc in re.finditer(
        r"(\b\w*(?:cnt|count|idle|gap|eof)\w*)\s*<=\s*\1\s*\+\s*1",
        src,
        flags=re.IGNORECASE,
    ):
        cnt = inc.group(1)
        # Find the IMMEDIATELY preceding `if`/`else if` condition. The
        # earlier "last 4 conditions then accept any with bus-HIGH" walk
        # mis-flagged pulse-width-measurement counters whose immediate
        # guard was `!id_bus_rx` but had an outer `if (id_bus_rx)`
        # somewhere earlier in the file. v0.119.24: pin the rule to the
        # last condition only.
        preamble = src[: inc.start()]
        cond_match = list(
            re.finditer(
                r"(else\s+if|if)\s*\(([^)]+)\)",
                preamble,
            )
        )
        if not cond_match:
            continue
        # ONLY the immediate (last) condition matters.
        guard_cond = cond_match[-1].group(2)
        # Idle-counter rule: the immediate guard mentions bus-HIGH and
        # is NOT a NOT-bus expression / zero-compare (those are LOW
        # triggered → measurement counter, not idle counter).
        if not re.search(r"id_bus(?:_rx)?|\brx\b", guard_cond):
            continue
        if re.search(r"!\s*(id_bus(?:_rx)?|\brx\b)", guard_cond):
            continue
        if re.search(r"~\s*(id_bus(?:_rx)?|\brx\b)", guard_cond):
            continue
        if re.search(r"id_bus[\w]*\s*==\s*1?'?[bdh]?0", guard_cond):
            continue
        results.append({
            "counter": cnt,
            "guard_cond": guard_cond.strip(),
            "file_text": src,
        })
    return results


def has_low_reset(ff_text: str, counter: str) -> bool:
    """Check if any always_ff resets `counter` on bus LOW.

    Accepts equivalent textual forms — bus-LOW can be expressed as a bare
    NOT, an explicit 0-compare, or a registered/synced version of the
    bus signal. The earlier narrow regex (only `!id_bus_rx` or
    `id_bus_rx == 1'b0`) silently missed the equally-correct
    `id_bus_rx_q1 == 1'b0` form a fresh agent picked. The looser pattern
    below still requires (a) some bus-low expression, (b) a counter
    write of 0, and (c) the two within ~200 chars of each other in the
    same source — so spurious 0-clears elsewhere don't satisfy it.
    """
    # Bus-LOW expressions, in order of specificity:
    #   !id_bus<...>       textual NOT
    #   ~id_bus<...>       bitwise NOT
    #   id_bus<...> == 1'b0 / == 0 / === 1'b0
    bus_low = (
        r"(?:[!~]\s*id_bus[\w]*|"
        r"id_bus[\w]*\s*===?\s*1?'?[bdh]?0+\b|"
        r"id_bus[\w]*\s*==\s*0\b)"
    )
    # Counter <= 0 in any radix form
    cnt_zero = (
        r"\b" + re.escape(counter)
        + r"\s*<=\s*(?:'0|0|\d+\s*'\s*[bdh]?\s*0+|\d+)"
    )
    pat = re.compile(
        bus_low + r"[^{};]{0,200}?" + cnt_zero,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return bool(pat.search(ff_text))


def waived(project_dir: Path) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        return bool(d.get("frame_end_idle_reset_alternative"))
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: half_duplex_frame_end_idle_reset_check.py <project_dir>")
        sys.exit(2)

    project_dir = Path(sys.argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        sys.exit(1)

    if not is_half_duplex(project_dir):
        print("PASS — project not detected as half-duplex (gate not applicable)")
        sys.exit(0)

    rtl_files = find_rtl_files(project_dir)
    if not rtl_files:
        print("PASS — no rtl/ directory or no Verilog/SV files yet")
        sys.exit(0)

    failures = []
    for rtl in rtl_files:
        try:
            src = strip_comments(rtl.read_text())
        except Exception as e:
            print(f"WARN — cannot read {rtl}: {e}")
            continue
        for hit in find_idle_counters(src):
            if not has_low_reset(hit["file_text"], hit["counter"]):
                failures.append({
                    "file": str(rtl.relative_to(project_dir)),
                    "counter": hit["counter"],
                    "guard": hit["guard_cond"],
                })

    if not failures:
        print("PASS — all bus-HIGH-gated idle counters reset on bus LOW")
        sys.exit(0)

    if waived(project_dir):
        print(f"PASS_WITH_WAIVER — {len(failures)} counter(s) flagged but "
              "waivers.frame_end_idle_reset_alternative is set")
        for f in failures:
            print(f"  • {f['file']}: counter '{f['counter']}' "
                  f"guarded by '{f['guard']}'")
        sys.exit(0)

    print(f"FAIL — {len(failures)} idle-gap counter(s) lack bus-LOW reset:")
    for f in failures:
        print(f"  • {f['file']}: counter '{f['counter']}' "
              f"guarded by '{f['guard']}' "
              "— missing 'else if (!id_bus_rx) <counter> <= 0'")
    print()
    print("Why this matters:")
    print("  Without a bus-LOW reset, the counter accumulates HIGH cycles")
    print("  across multiple bits/bytes. After IBT (~22us) plus next-byte")
    print("  first-bit HIGH (~8us) = ~30us, FRAME_END_GAP (e.g. 27us) is")
    print("  crossed mid-frame, the chip declares EOF, and responds while")
    print("  the master is still transmitting. Bus contention + silent fail.")
    print()
    print("Fix template (insert into the always_ff governing the counter):")
    print("    if (rx_byte_vld || rx_br || tx_active) begin")
    print("        gap_cnt <= '0;")
    print("    end else if (!id_bus_rx) begin       // <-- add this branch")
    print("        gap_cnt <= '0;")
    print("    end else if (gap_active && id_bus_rx) begin")
    print("        gap_cnt <= gap_cnt + 1;")
    print("    end")
    print()
    print("Or document an alternative in waivers.json:")
    print('    {"frame_end_idle_reset_alternative": "<mechanism description>"}')
    sys.exit(1)


if __name__ == "__main__":
    main()
