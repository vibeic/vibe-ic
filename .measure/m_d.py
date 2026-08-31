#!/usr/bin/env python3
"""MEASURE (d): is step 23 the only instance, or is this a pattern?

STATIC sweep: for every CERTIFYING step in the shipped flow, enumerate its
MANDATORY `program_exit_zero` clauses and count how many of those programs can
emit a vacuity signal at all (rc=2, a line-start `VACUOUS_PASS:` print, or a
NOT_APPLICABLE json verdict). A mandatory vacuity-capable clause on a certifying
step is the exposure surface: whenever it fires, the step drops below PASS and
voids its descendants.
"""
import re, sys
from pathlib import Path
import yaml

ROOT = (Path(__file__).resolve().parents[1]
        / "vibe-ic-marketplace" / "plugins" / "vibe-ic")
PROGRAMS = ROOT/"programs"
sys.path.insert(0, str(PROGRAMS))
import flow_step_execution_coverage_check as C

d = yaml.safe_load((ROOT/"flow"/"phase1_phase2_phase3.yaml").read_text())
def walk(o):
    if isinstance(o,dict):
        if 'id' in o and 'name' in o: yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o,list):
        for v in o: yield from walk(v)
steps=list(walk(d))

def clauses(step):
    g=step.get('gate') or {}
    items=g.get('all_of') if isinstance(g,dict) else None
    if items is None: items=[g] if g else []
    out=[]
    for c in items:
        if not isinstance(c,dict): continue
        for k,v in c.items():
            cmd = v.get('command') if isinstance(v,dict) else v
            out.append((k, cmd, isinstance(v,dict) and 'absent_condition_reason' in v))
    return out

def prog_of(cmd):
    if not isinstance(cmd,str): return None
    m=re.match(r'\s*([A-Za-z0-9_./-]+?)(?:\.py)?\s', cmd+' ')
    if not m: return None
    name=Path(m.group(1)).name
    p=PROGRAMS/f"{name}.py"
    return p if p.is_file() else None

VAC_RE=re.compile(r'VACUOUS_PASS|NOT_APPLICABLE|NOT-APPLICABLE')
def vacuity_capable(p):
    if p is None: return None
    t=p.read_text(errors='replace')
    return bool(VAC_RE.search(t))

cert=[s for s in steps if C._blocks_when_vacuous(s)]
print(f"CERTIFYING steps in the shipped flow: {len(cert)}")
print()
tot_mand=0; tot_vac=0; hits=[]
for s in cert:
    rows=[]
    for kind,cmd,declared in clauses(s):
        if kind!='program_exit_zero': continue
        p=prog_of(cmd); vc=vacuity_capable(p)
        tot_mand+=1
        if vc:
            tot_vac+=1; rows.append((p.name if p else str(cmd)[:40]))
    if rows:
        hits.append((s['id'], s['name'], rows))
print(f"MANDATORY program_exit_zero clauses on certifying steps : {tot_mand}")
print(f"  of those whose program can emit a vacuity signal      : {tot_vac}")
print()
print("Per certifying step — mandatory clauses that can go vacuous:")
for sid,name,rows in hits:
    print(f"  [{str(sid):>7}] {name[:56]}")
    for r in rows: print(f"            - {r}")
