#!/usr/bin/env python3
"""MEASURE (a) and (b) for the step-23 PARTIALLY-VACUOUS voider.

Two-step synthetic flow, modelled on tests/test_issue901_*.py:
  step 23s : a CERTIFYING sign-off step (name matches _SIGNOFF_RE "post-route STA")
             carrying 5 gate clauses -- 4 that measure substantively, 1 that is
             the drv-promotion-shaped clause.
  step 32s : an ordinary downstream step, blocks_on [23s], all clauses substantive.

ARM A (status quo wiring)  : the 5th clause is a MANDATORY program_exit_zero whose
                             program exits rc=2 (vacuous - "no promotion happened").
ARM B (rewired candidate)  : the 5th clause is optional_program_exit_zero with
                             condition_files_exist matching nothing + a declared
                             absent_condition_reason.
The measured numbers are the two step statuses in each arm.
chip-AGNOSTIC: synthetic gates, empty tree, no design/PDK/vendor literal.
"""
import json, subprocess, sys, tempfile
from pathlib import Path

PROGRAMS = (Path(__file__).resolve().parents[1]
            / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs")
FCC = PROGRAMS / "flow_compliance_check.py"

SUBSTANTIVE = '''#!/usr/bin/env python3
import json,sys
from pathlib import Path
a=sys.argv[1:]; out=None
for i,x in enumerate(a):
    if x=="--json" and i+1<len(a): out=a[i+1]
if out:
    p=Path(out)
    if not p.is_absolute(): p=Path.cwd()/p
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"gate":"substantive","verdict":"PASS","examined":7}))
print("[PASS] substantive")
sys.exit(0)
'''
# rc=2 is exactly what drv_promotion_corroboration_check returns when no
# promotion happened this run.
VACUOUS_RC2 = '''#!/usr/bin/env python3
import json,sys
from pathlib import Path
a=sys.argv[1:]; out=None
for i,x in enumerate(a):
    if x=="--json" and i+1<len(a): out=a[i+1]
if out:
    p=Path(out)
    if not p.is_absolute(): p=Path.cwd()/p
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"gate":"drvlike","verdict":"NOT_APPLICABLE",
                             "reason":"no promotion happened this run"}))
print("VACUOUS_PASS: no promotion happened this run")
sys.exit(2)
'''

REASON = ("no route promotion occurred this run, so there is no promoted route "
          "whose claimed improvement the sign-off report could corroborate")

def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); p.chmod(0o755); return p

def flow(tmp, fifth_clause, tag):
    subs = write(tmp/"g"/"substantive.py", SUBSTANTIVE)
    body = "".join(
        f'        - program_exit_zero: "{subs} . --json reports/s{i}.json"\n'
        for i in range(1,5))
    y = tmp/f"{tag}.yaml"
    y.write_text(
        "version: 2\nflow_name: m_ab\ntotal_steps: 2\nanalog_steps: 0\n"
        "stages:\n  - id: stage3\n    name: \"back end\"\n    steps: [23, 32]\n"
        "steps:\n"
        "  - id: 23\n"
        "    name: \"Post-route STA (multi-corner multi-mode sign-off)\"\n"
        "    stage: stage3\n"
        "    gate:\n      all_of:\n" + body + fifth_clause +
        "  - id: 32\n"
        "    name: \"Post-route timing repair pass\"\n"
        "    stage: stage3\n"
        "    blocks_on: [23]\n"
        "    gate:\n      all_of:\n"
        f'        - program_exit_zero: "{subs} . --json reports/t1.json"\n')
    return y

def audit(tmp, y, tag):
    proj = tmp/f"proj_{tag}"; proj.mkdir(parents=True, exist_ok=True)
    rep = proj/"report.json"
    r = subprocess.run([sys.executable, str(FCC), ".", "--flow-def", str(y),
                        "--json", str(rep)], cwd=proj, capture_output=True, text=True)
    doc = json.loads(rep.read_text())
    st = {str(s.get("id")): s for s in doc.get("steps", [])}
    return r.returncode, (r.stdout or "")+(r.stderr or ""), doc, st

tmp = Path(tempfile.mkdtemp(prefix="m_ab_"))
vac = write(tmp/"g"/"drvlike.py", VACUOUS_RC2)

ARM_A = f'        - program_exit_zero: "{vac} . --json reports/drv.json"\n'
ARM_B = ("        - optional_program_exit_zero:\n"
         f'            command: "{vac} . --json reports/drv.json"\n'
         '            condition_files_exist: ["pnr/routed_base_prerepair.def"]\n'
         f'            absent_condition_reason: "{REASON}"\n')

print("="*78)
for tag, clause in (("A_status_quo_mandatory", ARM_A), ("B_rewired_optional", ARM_B)):
    y = flow(tmp, clause, tag)
    rc, out, doc, st = audit(tmp, y, tag)
    s23 = st.get("23", {}); s32 = st.get("32", {})
    print(f"ARM {tag}")
    print(f"   overall verdict      : {doc.get('verdict')}   (process rc={rc})")
    print(f"   step 23 (certifying) : {s23.get('status')}")
    print(f"   step 32 (downstream) : {s32.get('status')}")
    for r_ in s23.get("reasons", []):
        if "VACUOUS" in r_ or "NOT-APPLICABLE" in r_: print(f"      23 | {r_[:132]}")
    for r_ in s32.get("reasons", []):
        if "voided" in r_.lower(): print(f"      32 | {r_[:132]}")
    print("-"*78)
print("tmp:", tmp)
