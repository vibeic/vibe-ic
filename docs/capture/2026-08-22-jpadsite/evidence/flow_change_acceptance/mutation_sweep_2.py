import pathlib, subprocess, shutil
SRC="/home/reyerchu/AI_IC_design/_jpadsite_wt"; WORK="/home/reyerchu/AI_IC_design/_jp_mut2"
REL="vibe-ic-marketplace/plugins/vibe-ic"
M=[
 ("_pdk_trees: named tree falls back to ALL", "_pad_ring.py",
  "        tree = root / name\n        return [tree] if tree.is_dir() else []",
  "        tree = root / name\n        return [tree] if tree.is_dir() else sorted(p for p in root.iterdir() if p.is_dir())"),
 ("pad_class_site_names drops the declared half", "_pad_ring.py",
  '            {n for n, s in self.sites.items() if s["class"] == "PAD"}\n            | set(self.declared_sites))',
  '            {n for n, s in self.sites.items() if s["class"] == "PAD"})'),
 ("site_source provenance never recorded", "pad_ring_gen.py",
  '        cfg_rec["site_source"] = site_src', '        pass'),
 ("rotation_vertical_inert dropped from reports", "pad_ring_gen.py",
  '        "rotation_vertical_inert": dict(ROTATION_VERTICAL_INERT),', '        "rotation_vertical_inert": {},'),
 ("gate stops reading the tech view", "pad_ring_check.py",
  "                    decls = PR.discover_io_site_declarations(\n                        args.pdk_root, args.pdk)",
  "                    decls = []"),
 ("parser accepts a comma-less form", "_pad_ring.py",
  r'r"(?P<q2>[\"{])\s*(?P<w>[0-9]+(?:\.[0-9]*)?)\s*,"', r'r"(?P<q2>[\"{])\s*(?P<w>[0-9]+(?:\.[0-9]*)?)\s*,?"'),
]
for name,f,old,new in M:
    shutil.rmtree(WORK,ignore_errors=True); shutil.copytree(SRC,WORK,symlinks=True)
    p=pathlib.Path(WORK,REL,"programs",f); s=p.read_text()
    if s.count(old)!=1: print(f"  {name:44s} ANCHOR MISS ({s.count(old)})"); continue
    p.write_text(s.replace(old,new,1))
    r=subprocess.run(["python3","-m","pytest","programs/tests/test_pad_ring.py","-q","-p","no:randomly"],
        cwd=str(pathlib.Path(WORK,REL)),capture_output=True,text=True,
        env={"PATH":"/usr/bin:/bin","PYTHONDONTWRITEBYTECODE":"1","HOME":"/tmp"})
    print(f"  {name:44s} {'SURVIVED  <-- UNPROTECTED' if r.returncode==0 else 'killed'}")
shutil.rmtree(WORK,ignore_errors=True)
