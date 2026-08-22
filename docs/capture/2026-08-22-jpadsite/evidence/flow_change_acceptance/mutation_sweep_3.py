import pathlib, subprocess, shutil
SRC="/home/reyerchu/AI_IC_design/_jpadsite_wt"; WORK="/home/reyerchu/AI_IC_design/_jp_m3"
REL="vibe-ic-marketplace/plugins/vibe-ic"
M=[("zero-width site guard removed","pad_ring_gen.py",
    'if site_wh["pad"][0] <= 0:', 'if False:'),
   ("site with no SIZE accepted","pad_ring_gen.py",
    'if not site["size"]:', 'if False:')]
for name,f,old,new in M:
    shutil.rmtree(WORK,ignore_errors=True); shutil.copytree(SRC,WORK,symlinks=True)
    p=pathlib.Path(WORK,REL,"programs",f); s=p.read_text()
    if s.count(old)!=1: print("  %-38s ANCHOR MISS (%d)"%(name,s.count(old))); continue
    p.write_text(s.replace(old,new,1))
    r=subprocess.run(["python3","-m","pytest","programs/tests/test_pad_ring.py","-q","-p","no:randomly"],
        cwd=str(pathlib.Path(WORK,REL)),capture_output=True,text=True,
        env={"PATH":"/usr/bin:/bin","PYTHONDONTWRITEBYTECODE":"1","HOME":"/tmp"})
    print("  %-38s %s"%(name,"SURVIVED  <-- UNPROTECTED" if r.returncode==0 else "killed"))
shutil.rmtree(WORK,ignore_errors=True)
