import pathlib, subprocess, shutil, sys, re
SRC = "/home/reyerchu/AI_IC_design/_jpadsite_wt"
WORK = "/home/reyerchu/AI_IC_design/_jp_mut"
REL = "vibe-ic-marketplace/plugins/vibe-ic"
MUTANTS = [
 ("declared site class PAD -> CORE", "_pad_ring.py",
  'DECLARED_SITE_CLASS = "PAD"', 'DECLARED_SITE_CLASS = "CORE"'),
 ("conflict detection disabled", "_pad_ring.py",
  "elif tuple(prev[\"size\"] or ()) != size:", "elif False:"),
 ("discovery keeps files with NO declaration", "_pad_ring.py",
  "if parse_pad_site_declarations(text):\n                    found.append(cfg)",
  "if True:\n                    found.append(cfg)"),
 ("vertical orient W <-> E swapped", "_pad_ring.py",
  '"W": ORIENT_ALIASES["MXR90"],\n    "E": ORIENT_ALIASES["R90"],',
  '"W": ORIENT_ALIASES["R90"],\n    "E": ORIENT_ALIASES["MXR90"],'),
 ("along-row extent back to HEIGHT", "pad_ring_gen.py",
  "along = [int(round(w * units)) for w, _h in sizes]",
  "along = [int(round(h * units)) for _w, h in sizes]"),
 ("non-default rotation no longer refused", "pad_ring_gen.py",
  "if declared_rotv != PR.normalise_orient(PR.ROTATION_DEFAULT):",
  "if False:"),
]
for name, f, old, new in MUTANTS:
    shutil.rmtree(WORK, ignore_errors=True); shutil.copytree(SRC, WORK, symlinks=True)
    p = pathlib.Path(WORK, REL, "programs", f); s = p.read_text()
    if s.count(old) != 1:
        print(f"  {name:44s} ANCHOR MISS ({s.count(old)})"); continue
    p.write_text(s.replace(old, new, 1))
    r = subprocess.run(["python3","-m","pytest","programs/tests/test_pad_ring.py","-q","-p","no:randomly"],
                       cwd=str(pathlib.Path(WORK, REL)), capture_output=True, text=True,
                       env={"PATH":"/usr/bin:/bin","PYTHONDONTWRITEBYTECODE":"1","HOME":"/tmp"})
    tail = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l]
    verdict = "SURVIVED  <-- UNPROTECTED" if r.returncode == 0 else "killed"
    print(f"  {name:44s} {verdict:26s} {tail[-1] if tail else ''}")
shutil.rmtree(WORK, ignore_errors=True)
