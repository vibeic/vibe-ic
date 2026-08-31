#!/usr/bin/env python3
"""MEASURE (e): with step 23 repaired, does step 31 reach PASS, or do 29/30 hold it?

Asked by the peer session owning steps 9/21/31/37, which measured 31 voided by
[23, 29, 30] after its own fix and could not answer this because both its arms had
23 red.

INSTRUMENT: `flow_step_execution_coverage_check.analyze()` driven DIRECTLY against
the REAL graph from the shipped flow yaml. That function IS the voiding engine --
`flow_compliance_check` only rewrites PASS -> PASS_VOIDED_BY_DEPENDENCY from the
`ordering_violations` it returns -- so measuring it measures the voiding itself,
with no fixture gymnastics and no synthetic gate able to drift from the real rule.

The relevant asymmetry, read from the flow and not assumed:
    29 Post-Layout Gate-Level Simulation   blocks_on [22]           NOT certifying
    30 Post-Layout SPICE Verification      blocks_on [22, 23]       CERTIFYING
    31 Physical Verification               blocks_on [23,24,25,26,27,29,30]
chip-AGNOSTIC: status words and the shipped graph only; no design, PDK or vendor.
"""
import sys
from pathlib import Path
import yaml

ROOT = (Path(__file__).resolve().parents[1]
        / "vibe-ic-marketplace" / "plugins" / "vibe-ic")
sys.path.insert(0, str(ROOT / "programs"))
import flow_step_execution_coverage_check as C
import _flow_verdict_tiers as T

d = yaml.safe_load((ROOT / "flow" / "phase1_phase2_phase3.yaml").read_text())
def walk(o):
    if isinstance(o, dict):
        if 'id' in o and 'name' in o: yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
STEPS = list(walk(d))
BY = {str(s['id']): s for s in STEPS}
GRAPH = {str(s['id']): [str(e) for e in (s.get('blocks_on') or [])] for s in STEPS}

# Everything outside the subtree under test is held at PASS so that the only
# thing that can void 31 is 23, 29 or 30. Excused steps stay excused.
EXCUSED_STAGES = {"stage_analog", "stage_mixed_signal", "stage5_manufacturing"}

def run(s23, s29, s30):
    steps = []
    for s in STEPS:
        sid = str(s['id'])
        stg = str(s.get('stage', '')).lower()
        if stg in EXCUSED_STAGES:
            st = "SKIPPED-CONDITION"
        elif sid == '23': st = s23
        elif sid == '29': st = s29
        elif sid == '30': st = s30
        else:             st = "PASS"
        steps.append({"id": sid, "name": s.get('name', ''),
                      "stage": s.get('stage', ''), "status": st})
    res = C.analyze({"steps": steps}, GRAPH)
    voiders = sorted({str(v["signoff_id"]) for v in res["ordering_violations"]
                      if str(v["terminal_id"]) == '31'})
    return ("PASS_VOIDED_BY_DEPENDENCY" if voiders else "PASS"), voiders

WORDS = ["PASS", "VACUOUS-PASS", "PARTIALLY-VACUOUS", "STRUCTURE-ONLY",
         "INCOMPLETE", "MISSING", "FAIL", "SKIPPED-SETUP-REQUIRED",
         "SKIPPED-CONDITION", "WAIVED", "DEFERRED-BY-UPSTREAM"]

for s23, label in (("PASS", "AFTER the step-23 rewiring (23 = PASS)"),
                   ("PARTIALLY-VACUOUS", "BEFORE it (23 = PARTIALLY-VACUOUS, today)")):
    print("=" * 100)
    print(f"{label}   -- cell = step 31's verdict; [ids] = what voided it")
    print("=" * 100)
    hdr = "30 (CERTIFYING) vs 29 (not certifying)"
    print(f"{hdr:44}" + "".join(f"{w[:13]:>15}" for w in WORDS[:6]))
    for s30 in WORDS:
        row = f"  30={s30:38}"
        for s29 in WORDS[:6]:
            st, v = run(s23, s29, s30)
            row += f"{('PASS' if st=='PASS' else 'VOID'+str(v)):>15}"
        print(row)
    print()

print("=" * 100)
print("THE ANSWER TO THE PEER'S QUESTION, isolated:")
print("=" * 100)
for s30 in WORDS:
    st, v = run("PASS", "PASS", s30)
    print(f"  23=PASS, 29=PASS, 30={s30:26} -> 31 = {st}  {v if v else ''}")
print()
for s29 in WORDS:
    st, v = run("PASS", s29, "PASS")
    print(f"  23=PASS, 30=PASS, 29={s29:26} -> 31 = {st}  {v if v else ''}")
