#!/usr/bin/env python3
"""Decompose a post-route netlist's area into the categories a REWRITE can
reach and the categories it cannot.  Cell areas are the PDK liberty's own.

A win a reader cannot attribute is not a win, so this is the attribution."""
import json, re, sys
from pathlib import Path

AREAS = json.load(open('/home/reyerchu/_jxlayer/sky130_cell_areas.json'))

def category(cell: str) -> str:
    n = cell.split('__', 1)[1] if '__' in cell else cell
    if n.startswith('decap'):  return 'decap'
    if n.startswith('fill'):   return 'fill'
    if n.startswith('tap'):    return 'tap'
    if n.startswith('diode'):  return 'antenna_diode'
    if n.startswith('conb'):   return 'tie'
    if n.startswith(('clkbuf', 'clkinv', 'clkdly')): return 'clock_tree'
    if n.startswith(('buf', 'inv', 'dlygate')):      return 'buffer_inverter'
    if n.startswith(('dfxtp', 'dfrtp', 'dfstp', 'sdf', 'dlxtp', 'edf')): return 'flop'
    return 'combinational'

def decompose(netlist: Path):
    txt = netlist.read_text(errors='replace')
    counts, area = {}, {}
    unknown = []
    for m in re.finditer(r'^\s+(sky130_fd_sc_hd__[a-z0-9_]+)\s', txt, re.M):
        c = m.group(1)
        cat = category(c)
        counts[cat] = counts.get(cat, 0) + 1
        a = AREAS.get(c)
        if a is None:
            unknown.append(c); continue
        area[cat] = area.get(cat, 0.0) + a
    return counts, area, sorted(set(unknown))

if __name__ == '__main__':
    rows = {}
    for t in sys.argv[1:]:
        nl = Path(f'/home/reyerchu/_jxlayer/run/trials/{t}/phase3/stage3/pnr/spm_pnr.v')
        if not nl.is_file():
            print(f'{t}: NO NETLIST'); continue
        c, a, u = decompose(nl)
        rows[t] = (c, a, u)
    cats = sorted({k for c, a, u in rows.values() for k in a})
    hdr = f"{'category':18s}" + ''.join(f"{t:>22s}" for t in rows)
    print(hdr); print('-' * len(hdr))
    for cat in cats:
        line = f"{cat:18s}"
        for t in rows:
            c, a, u = rows[t]
            line += f"{a.get(cat,0.0):12.1f} ({c.get(cat,0):4d})"
        print(line)
    line = f"{'TOTAL':18s}"
    for t in rows:
        c, a, u = rows[t]
        line += f"{sum(a.values()):12.1f} ({sum(c.values()):4d})"
    print('-' * len(hdr)); print(line)
    for t, (c, a, u) in rows.items():
        if u: print(f'{t}: cells with no liberty area: {u}')
