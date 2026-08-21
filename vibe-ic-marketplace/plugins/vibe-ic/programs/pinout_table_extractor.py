#!/usr/bin/env python3
"""pinout_table_extractor.py — chip-agnostic extractor for the PORT / PINOUT table.

The interface (ports) is the one structural artifact present in essentially EVERY
spec/prompt/datasheet. This deterministic extractor reads it into a structured list
— the program BASELINE for the dual-pass understanding layer (the AI pass adds the
prose-only attributes: function/electrical/description it can't get from a table).

Handles three common forms (chip-agnostic, no SKU names):
  1. bullet:   "- input  clk"  /  "- output q (4 bits)"  /  "- inout [7:0] data"
  2. verilog:  "input wire [3:0] x"  /  "output reg q"
  3. pipe table header containing Pin/Signal + Dir/Direction + (Width/Bits):
       | Signal | Dir | Width | Description |
       | clk    | in  | 1     | system clock |

Returns: List[{name, dir(in|out|inout), width(int|None for symbolic), source}].
Pure regex; deterministic. Returns [] when no port form is present (-> the dual-pass
baseline simply contributes nothing, AI still leads).
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional

_DIR = {"input": "in", "output": "out", "inout": "inout",
        "in": "in", "out": "out", "i": "in", "o": "out"}


def _w(hi: Optional[str], lo: Optional[str], bits: Optional[str]) -> Optional[int]:
    if bits is not None:
        return int(bits)
    if hi is not None and lo is not None:
        return abs(int(hi) - int(lo)) + 1
    return 1


def _bullet(text: str) -> List[Dict]:
    out = []
    for m in re.finditer(
        r"^\s*[-*]\s*(input|output|inout)\s+"
        r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s+)?"
        r"(\w+)"
        r"(?:\s*\(\s*(\d+)\s*bits?\s*\))?", text, re.I | re.M):
        d, hi, lo, name, bits = m.groups()
        out.append({"name": name, "dir": _DIR[d.lower()],
                    "width": _w(hi, lo, bits), "source": "bullet"})
    return out


def _verilog(text: str) -> List[Dict]:
    out = []
    for m in re.finditer(
        r"\b(input|output|inout)\s+(?:wire|reg|logic)?\s*"
        r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?"
        r"(\w+)\s*[,;)]", text):
        d, hi, lo, name = m.groups()
        out.append({"name": name, "dir": _DIR[d.lower()],
                    "width": _w(hi, lo, None), "source": "verilog"})
    return out


def _pipe_table(text: str) -> List[Dict]:
    lines = text.splitlines()
    hdr_i = None
    cols = {}
    for i, ln in enumerate(lines):
        cells = [c.strip().lower() for c in ln.split("|")]
        if len(cells) < 3:
            continue
        idx = {}
        for j, c in enumerate(cells):
            c = c.strip("`*").strip()
            if c in ("pin", "signal", "name", "port", "訊號", "訊號名", "信號", "端口", "名稱"):
                idx["name"] = j
            elif c in ("dir", "direction", "i/o", "io", "type", "方向"):
                idx["dir"] = j
            elif c in ("width", "bits", "size", "寬度", "位寬"):
                idx["width"] = j
        if "name" in idx and "dir" in idx:
            hdr_i, cols = i, idx
            break
    if hdr_i is None:
        return []
    out = []
    for ln in lines[hdr_i + 1:]:
        cells = [c.strip().strip("`*").strip() for c in ln.split("|")]   # backtick/bold
        if len(cells) <= max(cols.values()):
            continue
        name = cells[cols["name"]]
        if not re.fullmatch(r"\w+", name) or name.lower() in ("name", "signal", "pin", "port"):
            continue
        d = cells[cols["dir"]].lower().strip()
        if d not in _DIR:
            continue
        w, wp = None, None
        if "width" in cols:
            wc = cells[cols["width"]]
            mb = re.search(r"\[\s*([\w-]+)\s*:\s*([\w-]+)\s*\]", wc)       # [hi:lo] / [size-1:0]
            mn = re.search(r"(\d+)\s*-?\s*bit|^\s*(\d+)\s*$", wc)
            if mb and mb.group(1).isdigit() and mb.group(2).isdigit():
                w = abs(int(mb.group(1)) - int(mb.group(2))) + 1
            elif mn:
                w = int(mn.group(1) or mn.group(2))
            else:
                ms = re.search(r"\b([A-Za-z]\w*)\b", wc)                  # symbolic (N / size)
                wp = ms.group(1) if ms else None
        row = {"name": name, "dir": _DIR[d], "width": w, "source": "pipe"}
        if wp:
            row["width_param"] = wp
        out.append(row)
    return out


def extract_pinout(text: str) -> List[Dict]:
    """Return the port list (deduped by name, first form wins). [] if none found."""
    rows = _bullet(text) or _verilog(text) or _pipe_table(text)
    seen, out = set(), []
    for r in rows:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        out.append(r)
    return out


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", required=True)
    a = ap.parse_args()
    print(json.dumps(extract_pinout(Path(a.doc).read_text(errors="replace")), indent=2))
