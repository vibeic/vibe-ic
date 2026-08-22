import csv,re,subprocess,sys
SC=sys.argv[1]
def sh(*a):
    return subprocess.run(a,capture_output=True,text=True,cwd="/home/reyerchu/vibe-ic")
live=set()
for l in open(f"{SC}/live_heads.txt"):
    p=l.split()
    if len(p)==2: live.add(p[1].replace("refs/heads/",""))
out=[]
with open(f"{SC}/vc.tsv") as f:
    r=csv.reader(f,delimiter='\t'); next(r)
    for line in r:
        if len(line)<3: continue
        path,verdict,ev=line[0],line[1],line[2]
        # operative instruction = LAST 'git fetch origin <ref> && git checkout <sha>' pair in the row
        # accept BOTH resolving forms: `git checkout <sha>` and `git show <sha>:<path>`.
        # The show form is what rows use when the recoverable thing is one file, and a gate
        # that only matches `checkout` silently reports those rows as having no instruction.
        pairs=re.findall(r'git fetch origin ([A-Za-z0-9._/-]+)\s*&&\s*git (?:checkout|show) ([0-9a-f]{7,40})',ev)
        if not pairs:
            out.append((path,verdict,"NO_INSTRUCTION","-","-")); continue
        ref,sha=pairs[-1]
        if ref not in live:
            out.append((path,verdict,"REF_DEAD",ref,sha)); continue
        # does that live ref contain that sha?
        c=sh("git","merge-base","--is-ancestor",sha,"refs/remotes/live/"+ref)
        out.append((path,verdict,"RESOLVES" if c.returncode==0 else "REF_LIVE_BUT_LACKS_SHA",ref,sha))
with open(f"{SC}/gate.tsv","w") as o:
    for t in out: o.write("\t".join(t)+"\n")
from collections import Counter
for k,v in Counter((v,s) for _,v,s,_,_ in out).most_common(): print(v,k)
