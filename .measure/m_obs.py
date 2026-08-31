#!/usr/bin/env python3
"""OBSERVE step 31 move, on the REAL flow graph, through the REAL engine.

No reachable tree is converged at v1.14.x (see the LAND's honest-limit note), so the
observation is made by driving `flow_compliance_check` over a flow-def that carries
the REAL ids, names, stages and `blocks_on` of the 22..38 subgraph -- so the ordering
graph and the certifying classification are the shipped ones, not a model of them --
with step 23's clause 7 being the REAL `drv_promotion_corroboration_check`.
Every other clause is a synthetic substantive gate, because the point under test is
the tier of clause 7 and the propagation to 31, not whether a fixture can satisfy
DRC/LVS.

ARM A: clause 7 wired as today (mandatory program_exit_zero).
ARM B: clause 7 wired as the rung (optional + condition_files_exist + declared reason).
Cases: no promotion (the normal case) and promotion-with-contradiction (criterion 3,
prove-by-run that the BLOCKING behaviour survives).
chip-AGNOSTIC: synthetic artefact text only; no design, PDK, foundry or vendor.
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
import yaml

ROOT = (Path(__file__).resolve().parents[1]
        / "vibe-ic-marketplace" / "plugins" / "vibe-ic")
PROGRAMS = ROOT / "programs"
FCC = PROGRAMS / "flow_compliance_check.py"
DRV = PROGRAMS / "drv_promotion_corroboration_check.py"

SUB = '''#!/usr/bin/env python3
import json,sys
from pathlib import Path
a=sys.argv[1:]; out=None
for i,x in enumerate(a):
    if x=="--json" and i+1<len(a): out=a[i+1]
if out:
    p=Path(out)
    if not p.is_absolute(): p=Path.cwd()/p
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"gate":"substantive","verdict":"PASS","examined":11}))
print("[PASS] substantive"); sys.exit(0)
'''
REASON = ("no route promotion happened this run, so no promoted route exists whose "
          "claimed improvement the sign-off report could corroborate")

d = yaml.safe_load((ROOT / "flow" / "phase1_phase2_phase3.yaml").read_text())
def walk(o):
    if isinstance(o, dict):
        if 'id' in o and 'name' in o: yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
ALL = {str(s['id']): s for s in walk(d)}
SUBTREE = ['22','23','24','25','26','27','29','30','31','32','33','34','35','36','37','38']

tmp = Path(tempfile.mkdtemp(prefix="m_obs_"))
sub = tmp/"g"/"substantive.py"; sub.parent.mkdir(parents=True); sub.write_text(SUB); sub.chmod(0o755)
DRVCMD = f"{DRV} . --json reports/phase3/sta/drv_promotion_corroboration.json"

def flow_def(tag, optional):
    steps = []
    for sid in SUBTREE:
        s = ALL[sid]
        # REAL id / name / stage / blocks_on -> real graph, real cert classification.
        blocks = [str(e) for e in (s.get('blocks_on') or []) if str(e) in SUBTREE]
        clauses = [f'        - program_exit_zero: "{sub} . --json reports/g{sid}_{i}.json"\n'
                   for i in range(1, 5 if sid == '23' else 2)]
        if sid == '23':
            clauses.append(
                f'        - program_exit_zero: "{DRVCMD}"\n' if not optional else
                ("        - optional_program_exit_zero:\n"
                 f'            command: "{DRVCMD}"\n'
                 '            condition_files_exist: ["phase3/stage3/pnr/routed_base_prerepair.def",'
                 ' "pnr/routed_base_prerepair.def"]\n'
                 f'            absent_condition_reason: "{REASON}"\n'))
        steps.append(
            f'  - id: {sid}\n'
            f'    name: {json.dumps(s.get("name",""), ensure_ascii=False)}\n'
            f'    stage: {s.get("stage","stage3")}\n'
            + (f'    blocks_on: [{", ".join(blocks)}]\n' if blocks else '')
            + '    gate:\n      all_of:\n' + "".join(clauses))
    y = tmp/f"{tag}.yaml"
    y.write_text("version: 2\nflow_name: m_obs\n"
                 f"total_steps: {len(SUBTREE)}\nanalog_steps: 0\n"
                 "stages:\n  - id: stage3\n    name: \"back end\"\n"
                 f"    steps: [{', '.join(SUBTREE)}]\nsteps:\n" + "".join(steps))
    return y

def project(tag, promoted):
    p = tmp/f"proj_{tag}"; p.mkdir(parents=True, exist_ok=True)
    (p/"reports"/"phase3"/"sta").mkdir(parents=True, exist_ok=True)
    if promoted:
        pnr = p/"pnr"; pnr.mkdir(parents=True, exist_ok=True)
        (pnr/"routed_base_prerepair.def").write_text("DESIGN x ;\n")
        (pnr/"signoff_spef_repair.log").write_text(
            "Found 2 slew violations.\nFound 0 capacitance violations.\n")
        s = p/"phase3"/"stage3"/"sta"; s.mkdir(parents=True, exist_ok=True)
        (s/"sta_mcorner_ocv.rpt").write_text(
            "Max slew\n\nPin  Limit Slew Slack\n" +
            "".join(f"_0{7890+i}_/B0   3.00  6.12  -3.12 (VIOLATED)\n" for i in range(9)))
    return p

print("=" * 96)
for promoted, label in ((False, "NORMAL CASE — no promotion happened (the 0-of-15 case)"),
                        (True,  "PROMOTION HAPPENED AND SIGN-OFF CONTRADICTS IT (criterion 3)")):
    print(label)
    print("-" * 96)
    res = {}
    for arm, opt in (("A_stock_mandatory", False), ("B_rung_optional", True)):
        y = flow_def(f"{arm}_{promoted}", opt)
        proj = project(f"{arm}_{promoted}", promoted)
        rep = proj/"r.json"
        r = subprocess.run([sys.executable, str(FCC), ".", "--flow-def", str(y),
                            "--json", str(rep)], cwd=proj, capture_output=True, text=True,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if not rep.is_file():
            print("  RUNNER DID NOT WRITE A REPORT; rc=%s\n  stdout/err tail:\n%s"
                  % (r.returncode, ((r.stdout or "")+(r.stderr or ""))[-1500:]))
            raise SystemExit(1)
        doc = json.loads(rep.read_text())
        st = {str(s.get("id")): s.get("status") for s in doc.get("steps", [])}
        res[arm] = (st, r.returncode)
        print(f"  {arm:20} rc={r.returncode}  " +
              "  ".join(f"{k}={st.get(k)}" for k in ('23','31','32','34','35')))
    a, b = res["A_stock_mandatory"][0], res["B_rung_optional"][0]
    moved = [k for k in SUBTREE if a.get(k) != b.get(k)]
    print(f"  steps that moved A->B: {len(moved)}  {[(k, a.get(k), b.get(k)) for k in moved]}")
    print()
