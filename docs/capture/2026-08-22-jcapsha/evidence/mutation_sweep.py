"""Mutate one predicate of the guard at a time; a test must go red for each.

Restores by REVERSE EDIT, never by `git checkout --`, which would take every
uncommitted change in the file with it.
"""
import shutil, subprocess, sys, os
from pathlib import Path
ROOT = Path("/home/reyerchu/_jcapsha/vibe-ic-marketplace/plugins/vibe-ic")
TGT = ROOT / "programs/upstream_contract_parity_check.py"
BASE = "/tmp/claude-1000/-home-reyerchu-vibe-ic/8b7c1eda-e707-43e6-b019-4821e050e460/scratchpad/jcapsha/pt_mut"

MUTATIONS = [
  ("unaccounted upstream name",
   "for n in sorted(upstream - set(claimed)):",
   "for n in sorted(set() - set(claimed)):"),
  ("classification upstream dropped",
   "for n in sorted(set(claimed) - upstream):",
   "for n in sorted(set() - upstream):"),
  ("implemented name absent from module",
   "if n in upstream and not _mentions(text, n):\n            findings.append(\n                f\"{entry['id']}: {n} is classified implemented",
   "if False:\n            findings.append(\n                f\"{entry['id']}: {n} is classified implemented"),
  ("known_gap the module now implements",
   "if n in upstream and _mentions(text, n):",
   "if False:"),
  ("known_gap without a reference",
   "if not str(rec.get(\"reference\") or \"\").strip():",
   "if False:"),
  ("omission without a reason",
   "if not str(reason or \"\").strip():",
   "if False:"),
  ("empty register is rc 2",
   "if not isinstance(entries, list) or not entries:",
   "if not isinstance(entries, list):"),
  ("undetermined collapses to a pass",
   "    if undetermined:\n        return 2,",
   "    if False:\n        return 2,"),
  ("upstream anchor moved",
   "if anchor not in text:",
   "if False:"),
  ("upstream file changed under the snapshot",
   "if recorded_sha and recorded_sha != actual_sha:",
   "if False:"),
  ("pin test that does not exist",
   "elif f\"def {func}\" not in tf.read_text(encoding=\"utf-8\",",
   "elif False and f\"def {func}\" not in tf.read_text(encoding=\"utf-8\","),
  ("name classified twice",
   "if n in claimed:",
   "if False:"),
]

def clear_cache():
    for p in ROOT.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)

def run_suite(tag):
    clear_cache()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, "-m", "pytest",
                        "programs/tests/test_upstream_contract_parity.py",
                        "-q", "--basetemp", f"{BASE}_{tag}", "-p", "no:randomly"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout + p.stderr).strip().splitlines()[-1] if (p.stdout+p.stderr).strip() else ""

orig = TGT.read_text(encoding="utf-8")
rc, line = run_suite("baseline")
print(f"BASELINE rc={rc}  {line}")
assert rc == 0, "baseline must be green before mutating"

survived, killed = [], []
for i, (name, old, new) in enumerate(MUTATIONS):
    txt = TGT.read_text(encoding="utf-8")
    if txt.count(old) != 1:
        print(f"  SKIP  {name}: anchor occurs {txt.count(old)} times")
        survived.append((name, "anchor not unique"))
        continue
    TGT.write_text(txt.replace(old, new), encoding="utf-8")
    rc, line = run_suite(f"m{i}")
    # restore by reverse edit
    back = TGT.read_text(encoding="utf-8")
    assert back.count(new) == 1
    TGT.write_text(back.replace(new, old), encoding="utf-8")
    if rc != 0:
        killed.append((name, line)); print(f"  RED   {name}: {line}")
    else:
        survived.append((name, "SURVIVED - no test observed it")); print(f"  GREEN {name}: SURVIVED")

rc, line = run_suite("restored")
print(f"RESTORED rc={rc}  {line}")
assert TGT.read_text(encoding="utf-8") == orig, "reverse edit did not restore byte-for-byte"
print(f"\nKILLED {len(killed)} / {len(MUTATIONS)}")
for n, _ in survived: print(f"  SURVIVED: {n}")
