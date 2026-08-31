#!/usr/bin/env python3
"""MEASURE (c): does the REAL drv_promotion_corroboration_check still BLOCK when a
promotion DID happen and the sign-off contradicts it -- under BOTH wirings?

A fix that silences the promotion-vs-signoff refusal is a regression wearing a
repair. So every case is run through the REAL program, twice: once wired as today
(mandatory program_exit_zero) and once wired as the candidate rung
(optional_program_exit_zero + condition_files_exist + absent_condition_reason).

Cases (from the gate's own verdict table):
  c1 promoted + signoff shows MORE violations than the promotion claimed -> must FAIL
  c2 promoted + NO signoff report at all (uncorroborated)                -> must FAIL
  c3 promoted + signoff corroborates                                     -> PASS
  c4 no promotion this run                                               -> vacuous
chip-AGNOSTIC: synthetic artefact text only; no design, PDK, foundry or vendor.
"""
import json, subprocess, sys, tempfile
from pathlib import Path

PROGRAMS = (Path(__file__).resolve().parents[1]
            / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs")
FCC = PROGRAMS / "flow_compliance_check.py"
DRV = PROGRAMS / "drv_promotion_corroboration_check.py"

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
    p.write_text(json.dumps({"gate":"substantive","verdict":"PASS"}))
print("[PASS] substantive"); sys.exit(0)
'''
REASON = ("no route promotion occurred this run, so there is no promoted route "
          "whose claimed improvement the sign-off report could corroborate")

# A sign-off report row the gate's _DRV_ROW_RE counts as a violation.
def rpt(n):
    head = "Max slew\n\nPin                                     Limit  Slew   Slack\n"
    rows = "".join(f"_0{7890+i}_/B0                              3.00    6.12   -3.12 (VIOLATED)\n"
                   for i in range(n))
    return head + rows + "\n"

def repair_log(claimed):
    return (f"[INFO] repair pass\nFound {claimed} slew violations.\n"
            f"Found 0 capacitance violations.\n")

def build(root, promoted, signoff_n, claimed):
    """promoted: write the marker. signoff_n: None => no report, else N violations."""
    root.mkdir(parents=True, exist_ok=True)
    # The report dir the step's EARLIER clauses create (clause 2
    # hold_corner_coverage_check and clause 4 sta_report_check both mkdir it),
    # so by the time clause 7 runs in a real flow it exists. Pre-created here
    # so this rig measures the gate's VERDICT and not the missing-mkdir crash.
    (root/"reports"/"phase3"/"sta").mkdir(parents=True, exist_ok=True)
    pnr = root/"pnr"; pnr.mkdir(parents=True, exist_ok=True)
    if promoted:
        (pnr/"routed_base_prerepair.def").write_text("DESIGN x ;\n")
        if claimed is not None:
            (pnr/"signoff_spef_repair.log").write_text(repair_log(claimed))
    if signoff_n is not None:
        s = root/"phase3"/"stage3"/"sta"; s.mkdir(parents=True, exist_ok=True)
        (s/"sta_mcorner_ocv.rpt").write_text(rpt(signoff_n))
    return root

def write(p, t):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t); p.chmod(0o755); return p

tmp = Path(tempfile.mkdtemp(prefix="m_c_"))
subs = write(tmp/"g"/"substantive.py", SUBSTANTIVE)

DRVCMD = f"{DRV} . --json reports/phase3/sta/drv_promotion_corroboration.json"
ARM_A = f'        - program_exit_zero: "{DRVCMD}"\n'
ARM_B = ("        - optional_program_exit_zero:\n"
         f'            command: "{DRVCMD}"\n'
         '            condition_files_exist: ["pnr/routed_base_prerepair.def",'
         ' "phase3/stage3/pnr/routed_base_prerepair.def"]\n'
         f'            absent_condition_reason: "{REASON}"\n')

def flow(tag, clause):
    body = "".join(f'        - program_exit_zero: "{subs} . --json reports/s{i}.json"\n'
                   for i in range(1,5))
    y = tmp/f"{tag}.yaml"
    y.write_text(
        "version: 2\nflow_name: m_c\ntotal_steps: 2\nanalog_steps: 0\n"
        "stages:\n  - id: stage3\n    name: \"back end\"\n    steps: [23, 32]\n"
        "steps:\n"
        "  - id: 23\n    name: \"Post-route STA (multi-corner multi-mode sign-off)\"\n"
        "    stage: stage3\n    gate:\n      all_of:\n" + body + clause +
        "  - id: 32\n    name: \"Post-route timing repair pass\"\n"
        "    stage: stage3\n    blocks_on: [23]\n    gate:\n      all_of:\n"
        f'        - program_exit_zero: "{subs} . --json reports/t1.json"\n')
    return y

CASES = [
    ("c1_promoted_signoff_contradicts", True,  9,    2),
    ("c2_promoted_no_signoff_report",   True,  None, 2),
    ("c3_promoted_corroborated",        True,  1,    4),
    ("c4_no_promotion",                 False, 1,    None),
]

print("="*92)
print("STANDALONE: the real gate on its own (rc + verdict)")
print("="*92)
standalone = {}
for tag, promo, sn, cl in CASES:
    root = build(tmp/f"sa_{tag}", promo, sn, cl)
    r = subprocess.run([sys.executable, str(DRV), ".", "--json", "rep.json"],
                       cwd=root, capture_output=True, text=True)
    doc = json.loads((root/"rep.json").read_text())
    standalone[tag] = (r.returncode, doc["verdict"])
    print(f"  {tag:34} rc={r.returncode}  verdict={doc['verdict']:13} {doc['reason'][:60]}")

print()
print("="*92)
print("WIRED: the same cases through flow_compliance_check, BOTH wirings")
print("="*92)
print(f"  {'case':34} {'arm':10} {'step23':22} {'step32':26} rc")
rows=[]
for tag, promo, sn, cl in CASES:
    for arm, clause in (("A_mandatory", ARM_A), ("B_optional", ARM_B)):
        root = build(tmp/f"w_{tag}_{arm}", promo, sn, cl)
        y = flow(f"{tag}_{arm}", clause)
        rep = root/"report.json"
        r = subprocess.run([sys.executable, str(FCC), ".", "--flow-def", str(y),
                            "--json", str(rep)], cwd=root, capture_output=True, text=True)
        doc = json.loads(rep.read_text())
        st = {str(s.get("id")): s for s in doc.get("steps", [])}
        s23 = st.get("23",{}).get("status"); s32 = st.get("32",{}).get("status")
        rows.append((tag,arm,s23,s32,r.returncode))
        print(f"  {tag:34} {arm:10} {str(s23):22} {str(s32):26} {r.returncode}")
print()
print("VERDICT ON (c): the refusal must survive the rewiring for c1 and c2.")
for tag in ("c1_promoted_signoff_contradicts","c2_promoted_no_signoff_report"):
    a=[x for x in rows if x[0]==tag and x[1]=="A_mandatory"][0]
    b=[x for x in rows if x[0]==tag and x[1]=="B_optional"][0]
    ok = (a[2]=="FAIL" and b[2]=="FAIL")
    print(f"  {tag:34} A={a[2]:8} B={b[2]:8} -> {'REFUSAL PRESERVED' if ok else '*** SILENCED ***'}")
print("tmp:", tmp)
