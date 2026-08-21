import sys, json
from pathlib import Path
progdir = sys.argv[1]; proj = Path(sys.argv[2])
sys.path.insert(0, progdir)
import phase1_doc_one_shot_runner as p1
l3 = json.loads((proj/"phase1/generated_docs/L3_CMD_PROTOCOL.json").read_text())
# minimal extracted map from input docs (generator reads names, not needed heavily)
extracted = {}
docs = proj/"input"/"docs"
if docs.is_dir():
    for f in docs.rglob("*"):
        if f.is_file():
            try: extracted[f"input/docs/{f.relative_to(docs)}"] = f.read_text(errors="ignore")
            except Exception: pass
res = p1.gen_l10_test_cases(proj, extracted, l3)
print("regen wrote:", res.path)
doc = json.loads(Path(res.path).read_text())
from collections import Counter
cases = doc.get("test_cases") or []
print("L10 kinds AFTER regen:", dict(Counter(c.get('kind') for c in cases)))
# copy into the canonical generated_docs path if different
canon = proj/"phase1/generated_docs/L10_TEST_CASES.json"
if Path(res.path).resolve() != canon.resolve():
    canon.write_text(Path(res.path).read_text())
    print("copied to canonical:", canon)
