#!/usr/bin/env python3
"""level_hysteresis_flag_oracle_check.py — prompt-derived oracle for the
thermometer-level-controller class with a history-dependent (hysteresis) flag.

THE FAILURE CLASS THIS GUARDS (measured twice, identical signature)
-------------------------------------------------------------------
A level-controller prompt carries a relative-direction sentence ("if the
previous level was LOWER than the current, open the supplemental valve") whose
LITERAL reading (rise -> open) contradicts the prompt's own ABSOLUTE anchors:

  * a reset-equivalence sentence — reset == "level low for a long time",
    ALL outputs asserted  ->  flag == 1 at the bottom band (reachable only by
    FALLING or by reset);
  * a top-band sentence — above the highest sensor "the flow rate should be
    zero"  ->  flag == 0 at the top band (reachable only by RISING).

Two blind campaigns emitted the literal polarity and failed the official TB at
the identical >50% mismatch rate — the second time WHILE ACKNOWLEDGING the
captured lesson that warns about exactly this (the author justified the wrong
polarity by citing a different, generic lesson). Acknowledgement PRESENCE is
enforceable by a checkbox gate; acknowledgement FIDELITY is not. A simulation
oracle cannot be satisfied performatively — hence this program.

WHY THE ORACLE IS DETERMINISTIC (no LLM judgment, no hidden-TB access)
----------------------------------------------------------------------
A boundary-STATE check alone cannot discriminate: the wrong design also
asserts the flag at the bottom band and deasserts it at the top band (both
polarities decode the same at the extremes). The discriminator is the MIDDLE
bands' arrival direction, and it is derivable from the prompt alone:

  1. The relative sentence admits exactly TWO uniform readings of the held
     flag: P_rise (level rose -> flag=1) and P_fall (level fell -> flag=1).
  2. Extend each candidate to ALL bands as a held flag (updates only on a
     level change, holds through dwells) and evaluate it at the two absolute
     anchors, whose arrival direction is FORCED (bottom is only reached by
     falling, top only by rising).
  3. P_rise predicts flag=1 at the top anchor and flag=0 at the bottom anchor
     — contradicting BOTH absolute statements. P_fall satisfies both.
  4. ONLY IF exactly one candidate survives does it become the oracle; the
     authored RTL is then simulated through a canonical up/down walk and its
     flag compared at every settled step. Otherwise the check SKIPs.

§4.05 NO-FALSE-BLOCK DISCIPLINE (this is a guard-TIGHTENING check)
------------------------------------------------------------------
Every precondition failure -> SKIP (rc=0, non-blocking), never a guess:
  * no pipe-delimited band table whose condition column references exactly one
    vector signal with monotone nested (thermometer) index sets;
  * no reset-equivalence "all outputs asserted" sentence;
  * no relative-direction sentence, or it names no direction;
  * not exactly ONE output left over as the history flag (the outputs named in
    the table's assert column are the direction-independent "nominal" set);
  * both candidates survive the anchors, or neither does;
  * required ports (clock / reset / the table's vector input) not identifiable.
The nominal (table-listed) outputs are additionally checked per band row —
those rows are direction-UNQUALIFIED in the prompt, so they must hold on both
walks; a mismatch there is equally a prompt contradiction and blocks.

DUAL-TRACK EVIDENCE (#716): the JSON report carries the parsed table, both
candidates' anchor evaluations, the surviving polarity, and the full
expected-vs-got walk — an independent track can re-judge every input.

BLINDNESS: reads ONLY --prompt and --rtl. Never a golden, never a testbench.

CLI (mirrors kmap_truth_table_oracle_check.py)
    --prompt P  --rtl R  [--top TopModule]  [--json OUT]
Exit codes:  0 = PASS or SKIP (JSON verdict distinguishes)
             1 = BLOCK (oracle mismatch — genuine bug, §4.05-vetted)
             2 = tool absent / usage error (disclosed, non-blocking upstream)

chip-AGNOSTIC: keys only on the structural signature above — no design name,
no benchmark id, no dataset literal, no port-name dictionary beyond the
universal clock/reset idioms.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DWELL = 4  # cycles held per walk step; samples on the last negedge (settles 1-2 cycle registered decodes)


# ---------------------------------------------------------------------------
# prompt parsing — pure structure, no design knowledge
# ---------------------------------------------------------------------------

_PORT_RE = re.compile(
    r"^\s*-\s*(input|output)\s+(\w+)\s*(?:\((\d+)\s*bits?\))?\s*$", re.M)

# code-complete-style prompts embed the module HEADER instead of a bullet
# list: `input [2:0] s,` / `output reg fr2` inside `module ... ( ... );`.
_HDR_PORT_RE = re.compile(
    r"\b(input|output)\s+(?:reg|wire|logic)?\s*"
    r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?([A-Za-z_]\w*)")


def parse_interface(prompt: str) -> Dict[str, Tuple[str, int]]:
    """{name: (dir, width)} — bullet-list form first, module-header fallback."""
    iface = {m.group(2): (m.group(1), int(m.group(3) or 1))
             for m in _PORT_RE.finditer(prompt)}
    if iface:
        return iface
    m = re.search(r"\bmodule\s+\w+\s*\((.*?)\)\s*;", prompt, re.S)
    if not m:
        return iface
    for pm in _HDR_PORT_RE.finditer(m.group(1)):
        d, hi, lo, name = pm.group(1), pm.group(2), pm.group(3), pm.group(4)
        width = abs(int(hi) - int(lo)) + 1 if hi is not None else 1
        iface[name] = (d, width)
    return iface


_IDXREF_RE = re.compile(r"(\w+)\s*\[\s*(\d+)\s*\]")


def parse_band_table(prompt: str) -> Optional[dict]:
    """Find a pipe-delimited table whose middle column lists index refs of ONE
    vector signal forming a monotone thermometer chain, and whose last column
    lists output names (or None). Returns
      {vector, rows: [{level, sensors:set, outputs:set}], header_line}
    rows sorted by level ascending (0 = bottom / empty set). None if absent."""
    lines = prompt.splitlines()
    rows: List[dict] = []
    vec: Optional[str] = None
    for ln in lines:
        if ln.count("|") < 2:
            continue
        cols = [c.strip() for c in ln.split("|")]
        if len(cols) < 3:
            continue
        cond, sens, outs = cols[0], cols[1], cols[2]
        if re.search(r"assert", sens, re.I) and re.search(r"assert", outs, re.I):
            continue  # header row
        refs = _IDXREF_RE.findall(sens)
        sens_none = bool(re.fullmatch(r"none", sens.strip(), re.I))
        if not refs and not sens_none:
            continue
        names = {r[0] for r in refs}
        if refs:
            if len(names) != 1:
                return None  # mixed vectors — not this genre
            if vec is None:
                vec = next(iter(names))
            elif vec not in names:
                return None
        idxset = frozenset(int(r[1]) for r in refs)
        if sens_none:
            idxset = frozenset()
        out_none = bool(re.fullmatch(r"none", outs.strip(), re.I))
        outset = frozenset(re.findall(r"\b([A-Za-z_]\w*)\b", outs)) if not out_none else frozenset()
        rows.append({"cond": cond, "sensors": idxset, "outputs": outset})
    if len(rows) < 3 or vec is None:
        return None
    # thermometer chain: sorted by |sensors| the sets must be strictly nested
    rows.sort(key=lambda r: len(r["sensors"]))
    for a, b in zip(rows, rows[1:]):
        if not (a["sensors"] < b["sensors"]):
            return None
        if len(b["sensors"]) - len(a["sensors"]) != 1:
            return None
    for lvl, r in enumerate(rows):
        r["level"] = lvl
    return {"vector": vec, "rows": rows}


def find_reset_equivalence(prompt: str) -> bool:
    """A sentence pinning ALL outputs asserted at the long-low state."""
    return bool(re.search(
        r"all\s+(?:\w+\s+)?outputs?\s+(?:be\s+|are\s+)?asserted", prompt, re.I))


def find_top_zero(prompt: str) -> bool:
    """A sentence pinning zero total flow above the highest sensor."""
    return bool(re.search(
        r"(?:above|highest)[^.]{0,120}?(?:rate|flow)[^.]{0,60}?\bzero\b|"
        r"(?:rate|flow)[^.]{0,60}?\bzero\b[^.]{0,120}?(?:above|highest)",
        prompt, re.I | re.S))


def find_relative_sentence(prompt: str, flag_candidates: frozenset) -> Optional[dict]:
    """The history sentence: previous level lower/higher -> open/close a valve
    controlled by <flag>. Returns {literal_rise_is_one, flag} or None."""
    for sent in re.split(r"(?<=[.!?])\s+", prompt):
        if not re.search(r"previous", sent, re.I):
            continue
        m_dir = re.search(r"\b(lower|higher)\b", sent, re.I)
        if not m_dir:
            continue
        named = [f for f in flag_candidates if re.search(rf"\b{re.escape(f)}\b", sent)]
        opens = bool(re.search(r"increas|open|assert", sent, re.I))
        closes = bool(re.search(r"decreas|clos|deassert", sent, re.I))
        if not (opens ^ closes):
            continue
        # "previous was LOWER than current" == level ROSE
        rose = m_dir.group(1).lower() == "lower"
        one_on_rise = (rose and opens) or ((not rose) and closes)
        return {"literal_rise_is_one": one_on_rise,
                "flag": named[0] if named else None}
    return None


# ---------------------------------------------------------------------------
# candidate model + anchor filter — pure python, deterministic
# ---------------------------------------------------------------------------

def walk_codes(nlv: int) -> List[Tuple[int, str]]:
    """(level, direction) walk bottom->top->bottom. direction: 'reset'|'up'|'down'."""
    seq = [(0, "reset")]
    seq += [(l, "up") for l in range(1, nlv)]
    seq += [(l, "down") for l in range(nlv - 2, -1, -1)]
    return seq


def model_flag(one_on_rise: bool, steps: List[Tuple[int, str]]) -> List[int]:
    """Held flag per step: reset state == 'low for a long time, all asserted' -> 1."""
    out, flag = [], 1
    for lvl, d in steps:
        if d == "up":
            flag = 1 if one_on_rise else 0
        elif d == "down":
            flag = 0 if one_on_rise else 1
        out.append(flag)
    return out


def anchor_filter(one_on_rise: bool, nlv: int,
                  bottom_all_asserted: bool, top_zero: bool) -> Tuple[bool, dict]:
    """Does this candidate satisfy the absolute anchors? Evidence included."""
    steps = walk_codes(nlv)
    flags = model_flag(one_on_rise, steps)
    ev = {"one_on_rise": one_on_rise, "checks": []}
    ok = True
    if top_zero:
        i_top = max(i for i, (l, _) in enumerate(steps) if l == nlv - 1)
        c = {"anchor": "top_zero_flow", "expected": 0, "model": flags[i_top]}
        c["ok"] = flags[i_top] == 0
        ok &= c["ok"]; ev["checks"].append(c)
    if bottom_all_asserted:
        i_bot = max(i for i, (l, _) in enumerate(steps) if l == 0)
        c = {"anchor": "bottom_all_asserted", "expected": 1, "model": flags[i_bot]}
        c["ok"] = flags[i_bot] == 1
        ok &= c["ok"]; ev["checks"].append(c)
    return ok, ev


# ---------------------------------------------------------------------------
# RTL simulation
# ---------------------------------------------------------------------------

def _find_port(iface: Dict[str, Tuple[str, int]], *pats: str) -> Optional[str]:
    for name, (d, _w) in iface.items():
        if d != "input":
            continue
        for p in pats:
            if re.search(p, name, re.I):
                return name
    return None


def build_tb(iface, table, flag, top) -> Tuple[Optional[str], Optional[str]]:
    vec = table["vector"]
    nlv = len(table["rows"])
    width = max(iface.get(vec, ("", nlv - 1))[1], nlv - 1)
    clk = _find_port(iface, r"^clk$", r"clock", r"clk")
    rst = _find_port(iface, r"^reset$", r"rst")
    if not clk or not rst or vec not in iface:
        return None, "clock/reset/vector port not identifiable from the interface"
    outs = sorted(n for n, (d, w) in iface.items() if d == "output" and w == 1)
    conns = [f".{clk}({clk})", f".{rst}({rst})", f".{vec}({vec})"] + [f".{o}({o})" for o in outs]
    code = lambda lvl: "{" + str(width) + "{1'b0}}" if lvl == 0 else \
        "%d'b%s" % (width, "0" * (width - lvl) + "1" * lvl)
    steps = walk_codes(nlv)
    body = [
        "`timescale 1ns/1ps", "module __lhfo_tb;",
        f"  reg {clk}=0, {rst}=1;", f"  reg [{width-1}:0] {vec};",
        "  wire " + ", ".join(outs) + ";",
        f"  {top} dut (" + ", ".join(conns) + ");",
        f"  always #5 {clk} = ~{clk};",
        "  integer k;",
        "  initial begin",
        f"    {vec} = {code(0)};",
        f"    repeat (3) @(posedge {clk});",
        f"    #1 {rst} = 0;",
    ]
    for i, (lvl, _d) in enumerate(steps):
        body += [f"    {vec} = {code(lvl)};",
                 f"    repeat ({DWELL}) @(posedge {clk});",
                 f"    @(negedge {clk});",
                 '    $display("__S %0d ' + " ".join(f"{o}=%b" for o in outs) + '", '
                 + str(i) + ", " + ", ".join(outs) + ");"]
    body += ["    $finish;", "  end", "endmodule"]
    return "\n".join(body), None


def simulate(rtl: Path, tb_text: str) -> Tuple[Optional[List[dict]], str]:
    with tempfile.TemporaryDirectory() as td:
        tb = Path(td) / "__lhfo_tb.sv"
        tb.write_text(tb_text)
        binp = Path(td) / "sim"
        try:
            # watchdog-exempt: bounded single-file iverilog TB compile with a fixed 120s budget — not an open-ended EDA generator
            c = subprocess.run(["iverilog", "-g2012", "-s", "__lhfo_tb",
                                "-o", str(binp), str(rtl), str(tb)],
                               capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            return None, "TOOL_ABSENT"
        except subprocess.TimeoutExpired:
            return None, "compile timeout"
        if c.returncode != 0:
            return None, "tb compile failed: " + (c.stdout + c.stderr)[-300:]
        try:
            # watchdog-exempt: bounded compiled-TB sim (fixed walk, ~40 cycles) with a fixed 120s budget
            r = subprocess.run([str(binp)], capture_output=True, text=True,
                               timeout=120, cwd=td)
        except subprocess.TimeoutExpired:
            return None, "sim timeout"
        samples = []
        for ln in (r.stdout + r.stderr).splitlines():
            if not ln.startswith("__S "):
                continue
            parts = ln.split()
            row = {"step": int(parts[1])}
            for kv in parts[2:]:
                k, v = kv.split("=")
                row[k] = None if ("x" in v or "z" in v) else int(v, 2)
            samples.append(row)
        return samples, ""


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def check(prompt_text: str, rtl: Path, top: str) -> dict:
    rep: dict = {"gate": "level_hysteresis_flag_oracle_check", "verdict": "SKIP"}

    iface = parse_interface(prompt_text)
    table = parse_band_table(prompt_text)
    if not table:
        rep["skip_reason"] = "no thermometer band table"
        return rep
    if not find_reset_equivalence(prompt_text):
        rep["skip_reason"] = "no reset-equivalence all-outputs-asserted sentence"
        return rep
    top_zero = find_top_zero(prompt_text)

    nominal = frozenset().union(*(r["outputs"] for r in table["rows"]))
    out_ports = frozenset(n for n, (d, w) in iface.items() if d == "output" and w == 1)
    flag_cands = out_ports - nominal
    if len(flag_cands) != 1:
        rep["skip_reason"] = f"history-flag output not unique: {sorted(flag_cands)}"
        return rep
    flag = next(iter(flag_cands))

    rel = find_relative_sentence(prompt_text, flag_cands)
    if not rel:
        rep["skip_reason"] = "no relative-direction sentence"
        return rep

    nlv = len(table["rows"])
    surv, ev = [], []
    for cand in (True, False):  # one_on_rise
        ok, e = anchor_filter(cand, nlv, True, top_zero)
        ev.append(e)
        if ok:
            surv.append(cand)
    rep["candidates"] = ev
    rep["table"] = {"vector": table["vector"], "levels": nlv,
                    "nominal_by_level": {r["level"]: sorted(r["outputs"]) for r in table["rows"]}}
    rep["flag_output"] = flag
    rep["literal_reading_rise_is_one"] = rel["literal_rise_is_one"]
    if len(surv) != 1:
        rep["skip_reason"] = f"anchor filter left {len(surv)} candidate(s) — no unambiguous oracle"
        return rep
    pol = surv[0]
    rep["surviving_polarity"] = "rise->1" if pol else "fall->1"

    tb_text, err = build_tb(iface, table, flag, top)
    if tb_text is None:
        rep["skip_reason"] = err
        return rep
    samples, err = simulate(rtl, tb_text)
    if samples is None:
        if err == "TOOL_ABSENT":
            rep["verdict"] = "DISCLOSED_TOOL_GAP"
            return rep
        rep["skip_reason"] = "simulation not possible: " + err
        return rep

    steps = walk_codes(nlv)
    exp_flags = model_flag(pol, steps)
    lvl_rows = {r["level"]: r for r in table["rows"]}
    mismatches, walk_ev = [], []
    for i, (lvl, d) in enumerate(steps):
        got = next((s for s in samples if s["step"] == i), None)
        if got is None:
            rep["skip_reason"] = f"sim produced no sample for step {i}"
            return rep
        row_ev = {"step": i, "level": lvl, "dir": d, "expected": {}, "got": {}}
        for o in lvl_rows[lvl]["outputs"] | (nominal):
            want = 1 if o in lvl_rows[lvl]["outputs"] else 0
            row_ev["expected"][o] = want
            row_ev["got"][o] = got.get(o)
            if got.get(o) is not None and got[o] != want:
                mismatches.append({"step": i, "level": lvl, "dir": d,
                                   "signal": o, "expected": want, "got": got[o],
                                   "kind": "nominal-band-output"})
        row_ev["expected"][flag] = exp_flags[i]
        row_ev["got"][flag] = got.get(flag)
        if got.get(flag) is not None and got[flag] != exp_flags[i]:
            mismatches.append({"step": i, "level": lvl, "dir": d,
                               "signal": flag, "expected": exp_flags[i],
                               "got": got[flag], "kind": "hysteresis-flag-polarity"})
        walk_ev.append(row_ev)
    rep["walk"] = walk_ev
    rep["mismatches"] = mismatches
    rep["verdict"] = "BLOCK" if mismatches else "PASS"
    if mismatches:
        rep["log"] = (f"{len(mismatches)} mismatch(es) vs the prompt-derived oracle "
                      f"(surviving polarity {rep['surviving_polarity']}); first: "
                      + json.dumps(mismatches[0]))
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--rtl", required=True)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    try:
        prompt_text = Path(a.prompt).read_text(errors="ignore")
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    rtl = Path(a.rtl)
    if not rtl.is_file():
        print(f"error: rtl not found: {rtl}", file=sys.stderr)
        return 2
    rep = check(prompt_text, rtl, a.top)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(rep, indent=2) + "\n")
    v = rep["verdict"]
    msg = rep.get("log") or rep.get("skip_reason") or ""
    print(f"level_hysteresis_flag_oracle_check: {v}" + (f" — {msg}" if msg else ""))
    if v == "BLOCK":
        return 1
    if v == "DISCLOSED_TOOL_GAP":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
