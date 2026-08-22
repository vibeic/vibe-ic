#!/usr/bin/env python3
"""fault_cut_async_observe.py — restore OBSERVABILITY of a sequential cell's
ASYNCHRONOUS set/reset inputs in a `fault cut` full-scan ATPG model.

────────────────────────────────────────────────────────────────────────────
THE DEFECT THIS CLOSES

`fault cut` builds the combinational ATPG model by replacing every flop with a
pseudo-PI (the flop's Q) and a pseudo-PO (the flop's D). It drops every OTHER
sequential pin — in particular the ASYNCHRONOUS clear/preset input. Any net
whose only load was such a pin therefore ends up with ZERO loads in the model,
and every fault on it becomes structurally unobservable: no test can exist,
because there is nothing downstream to observe.

That is a MODELLING artefact, not a property of the silicon. On real silicon a
stuck-at on a flop's async reset is perfectly testable — assert/deassert it,
capture, scan out. Commercial ATPG models the scan cell's captured value as a
function of BOTH D and the async pins, so those faults are graded normally.

The damage is largest exactly where it is least expected: many standard-cell
libraries ship NO reset-less flop at all (IHP sg13g2 has only `dfrbp*`/`sdfrbp*`
/`sdfbbp*`), so synthesis maps every register to a reset flop and TIES the
unused async pin off with a dedicated tie cell. One dangling tie cell per flop
→ 2 structurally untestable faults per flop → a coverage shortfall that scales
with the flop count and that no amount of extra test vectors can ever recover.

────────────────────────────────────────────────────────────────────────────
THE REPAIR (sound, liberty-driven, chip/PDK-AGNOSTIC)

For each cut flop, add ONE extra pseudo-PO carrying the cell's TRUE next-state
function, taken from the liberty `ff` group rather than from any cell-name
guess:

    ff (IQ,IQN) { clear: "!RESET_B"; clocked_on: "CLK"; next_state: "D"; }

      clear  active-low  on P   ->  q_next =  P & D
      clear  active-high on P   ->  q_next = ~P & D
      preset active-low  on P   ->  q_next = ~P | D
      preset active-high on P   ->  q_next =  P | D

This is the SOUND model, not merely "observe the async net". Observing the pin
directly would claim detection even when D already equals the forced value; the
next-state form detects a fault on the async pin exactly when it actually
changes what the flop captures — the same condition real ATPG must satisfy.

The existing `<inst>.d` pseudo-PO is left untouched (the transition-fault ATPG
consumes it and expects D), so this is purely ADDITIVE: no fault that graded
before can regrade differently, and nets that already had loads are unaffected.

────────────────────────────────────────────────────────────────────────────
    python3 fault_cut_async_observe.py --netlist <mapped.v> --cut <cut.v> \
        --liberty <cell.lib> [--output <out.v>] [--json <report.json>]

Exit 0 always when the rewrite is well-formed (0 ports added is a legitimate
no-op: a library whose flops have no async pins, or a design with no flops).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROGRAM = "fault_cut_async_observe"
VERSION = "1.0.0"

# Pins that are NEVER async controls, whatever they are called: the liberty
# `ff` group names them explicitly, so this is only a belt-and-braces guard.
_NON_ASYNC_ROLES = ("clocked_on", "next_state")


# ── liberty ───────────────────────────────────────────────────────────────
def parse_liberty_ff(liberty_text: str) -> dict:
    """Map ``cell name -> {clear, preset, clocked_on, next_state}`` for every
    cell that declares an ``ff`` group. Values are the raw liberty boolean
    expressions (e.g. ``"!RESET_B"``); missing keys are absent.

    Deliberately tolerant: liberty is huge and we only need four scalars per
    sequential cell, so we slice each ``cell (...)`` block textually rather
    than building a full liberty AST."""
    out: dict = {}
    # Cell blocks start at column 2 in every liberty we ship; anchor on the
    # keyword instead of on indentation so hand-edited files still parse.
    starts = [(m.start(), m.group(1))
              for m in re.finditer(r"\bcell\s*\(\s*([A-Za-z_][\w$]*)\s*\)\s*\{",
                                   liberty_text)]
    for idx, (pos, name) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(liberty_text)
        block = liberty_text[pos:end]
        # The ff group body holds only simple `key : "expr";` statements — no
        # nested braces — so bound the match on the FIRST closing brace rather
        # than on any layout convention (a one-line ff group must parse too).
        ff = re.search(r"\bff\s*\([^)]*\)\s*\{([^{}]*)\}", block, re.S)
        if not ff:
            continue
        body = ff.group(1)
        rec: dict = {}
        for key in ("clear", "preset", "clocked_on", "next_state"):
            m = re.search(key + r"\s*:\s*\"([^\"]*)\"\s*;", body)
            if m:
                rec[key] = m.group(1).strip()
        if rec:
            out[name] = rec
    return out


def async_pin_and_polarity(expr: str) -> "tuple[str, bool] | None":
    """Parse a liberty clear/preset expression into ``(pin, active_low)``.

    Handles the forms libraries actually use for a single-pin control:
    ``P``, ``!P``, ``P'``, and parenthesised/spaced variants. Returns None for
    anything multi-pin — a compound async condition is not something we will
    silently guess at."""
    e = (expr or "").strip()
    while e.startswith("(") and e.endswith(")"):
        e = e[1:-1].strip()
    active_low = False
    if e.startswith("!"):
        active_low, e = True, e[1:].strip()
    elif e.endswith("'"):
        active_low, e = True, e[:-1].strip()
    if not re.fullmatch(r"[A-Za-z_][\w$]*", e):
        return None
    return e, active_low


def next_state_expr(d_net: str, pin_net: str, active_low: bool,
                    is_clear: bool) -> str:
    """Verilog for the flop's captured value given one async control.

    clear  -> forces 0 when asserted;  preset -> forces 1 when asserted."""
    asserted_low = active_low
    if is_clear:
        # q = asserted ? 0 : D   ==>   AND with the de-asserted condition
        return (f"{pin_net} & {d_net}" if asserted_low
                else f"(~{pin_net}) & {d_net}")
    # q = asserted ? 1 : D   ==>   OR with the asserted condition
    return (f"(~{pin_net}) | {d_net}" if asserted_low
            else f"{pin_net} | {d_net}")


# ── netlist ───────────────────────────────────────────────────────────────
_INST_RE = re.compile(
    r"\b([A-Za-z_][\w$]*)\s+(\\?[^\s(\\]+)\s*\(\s*((?:\.[^;]*?))\)\s*;", re.S)
_CONN_RE = re.compile(r"\.\s*([A-Za-z_][\w$]*)\s*\(\s*([^)]*?)\s*\)")


def parse_instances(netlist_text: str, cells: "set[str]") -> list:
    """``[(cell, inst, {pin: net})]`` for every instance of a cell in `cells`."""
    found = []
    for m in _INST_RE.finditer(netlist_text):
        cell, inst, body = m.group(1), m.group(2), m.group(3)
        if cell not in cells:
            continue
        conns = {p: n.strip() for p, n in _CONN_RE.findall(body)}
        if conns:
            found.append((cell, inst.lstrip("\\"), conns))
    return found


def cut_pseudo_po_name(inst: str) -> str:
    """`fault cut` names the flop's D pseudo-PO ``\\<inst>.d``."""
    return f"\\{inst}.d "


def augment_cut(cut_text: str, additions: list) -> str:
    """Insert the new observation ports into a cut netlist.

    `additions` is ``[(port_ident, rhs_expr)]`` where `port_ident` is already
    escaped-and-space-terminated Verilog (``\\_629_.RESET_B ``)."""
    if not additions:
        return cut_text
    # 1) module port list — append before the closing ");" of the header.
    m = re.search(r"\bmodule\b[^;(]*\((.*?)\)\s*;", cut_text, re.S)
    if not m:
        raise ValueError("cut netlist has no parseable module header")
    # NB: do NOT strip the existing port text. `fault cut` emits ESCAPED
    # identifiers (``\_633_.d ``) and a Verilog escaped identifier is terminated
    # BY WHITESPACE — rstrip()ing the trailing blank glues the following comma
    # onto the name (``\_633_.d,``), which every Verilog front end then rejects.
    ports = m.group(1)
    new_ports = ports + ",\n  " + ",\n  ".join(p for p, _ in additions) + "\n"
    cut_text = cut_text[:m.start(1)] + new_ports + cut_text[m.end(1):]

    # 2) declarations + continuous assignments, immediately before endmodule.
    decls = "".join(f"  output {p};\n" for p, _ in additions)
    assigns = "".join(f"  assign {p}= {rhs};\n" for p, rhs in additions)
    body = ("\n  // ---- fault_cut_async_observe: sound next-state pseudo-POs so\n"
            "  // ---- flop async set/reset inputs are OBSERVABLE (else every\n"
            "  // ---- fault on the reset tree is structurally untestable).\n"
            + decls + assigns)
    idx = cut_text.rfind("endmodule")
    if idx < 0:
        raise ValueError("cut netlist has no endmodule")
    return cut_text[:idx] + body + cut_text[idx:]


def build_additions(netlist_text: str, cut_text: str, liberty_text: str) -> tuple:
    """Return ``(additions, report)``. Pure — no I/O — so it is directly
    testable."""
    ffs = parse_liberty_ff(liberty_text)
    seq_cells = set(ffs)
    insts = parse_instances(netlist_text, seq_cells)
    additions: list = []
    detail: list = []
    skipped: list = []
    for cell, inst, conns in insts:
        rec = ffs.get(cell, {})
        d_po = cut_pseudo_po_name(inst)
        if d_po not in cut_text:
            skipped.append({"inst": inst, "cell": cell,
                            "reason": "flop not present as a cut pseudo-PO"})
            continue
        d_net = conns.get(rec.get("next_state", "D"))
        if not d_net:
            skipped.append({"inst": inst, "cell": cell,
                            "reason": "next_state pin not connected"})
            continue
        for role in ("clear", "preset"):
            expr = rec.get(role)
            if not expr:
                continue
            parsed = async_pin_and_polarity(expr)
            if not parsed:
                skipped.append({"inst": inst, "cell": cell,
                                "reason": f"compound {role} expression {expr!r} "
                                          f"— not guessed at"})
                continue
            pin, active_low = parsed
            if pin in (rec.get(r) for r in _NON_ASYNC_ROLES):
                continue
            net = conns.get(pin)
            if not net:
                continue
            port = f"\\{inst}.{pin} "
            if port in cut_text:            # already observable — never double
                continue
            rhs = next_state_expr(d_net, net, active_low, role == "clear")
            additions.append((port, rhs))
            detail.append({"inst": inst, "cell": cell, "pin": pin, "net": net,
                           "role": role, "active_low": active_low,
                           "port": port.strip(), "next_state": rhs})
    report = {
        "program": PROGRAM,
        "version": VERSION,
        "sequential_cells_in_liberty": sorted(seq_cells),
        "flop_instances_seen": len(insts),
        "observation_ports_added": len(additions),
        "added": detail,
        "skipped": skipped,
    }
    return additions, report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--netlist", required=True, help="tech-mapped gate netlist")
    p.add_argument("--cut", required=True, help="`fault cut` output netlist")
    p.add_argument("--liberty", required=True, help="cell liberty (.lib)")
    p.add_argument("--output", help="augmented cut netlist (default: in place)")
    p.add_argument("--json", dest="json_out", help="write a JSON report here")
    a = p.parse_args(argv)

    cut_text = Path(a.cut).read_text(errors="replace")
    additions, report = build_additions(
        Path(a.netlist).read_text(errors="replace"),
        cut_text,
        Path(a.liberty).read_text(errors="replace"),
    )
    out_text = augment_cut(cut_text, additions)
    out_path = Path(a.output or a.cut)
    out_path.write_text(out_text)
    report["output"] = str(out_path)
    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(json.dumps(report, indent=2))
    print(f"{PROGRAM}: added {report['observation_ports_added']} async "
          f"observation port(s) across {report['flop_instances_seen']} flop(s) "
          f"-> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
