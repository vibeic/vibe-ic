import json,os,re,sys
RUN="/home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1333_knowledge_converge"
recs=sorted(os.listdir(f"{RUN}/records"))
rows=[]
for f in recs:
    pid=f[:-5]
    d=json.load(open(f"{RUN}/records/{f}"))
    env=d['harness']['files']['src/.env']
    srcs=re.search(r'VERILOG_SOURCES\s*=\s*(.+)',env).group(1).split()
    bn=[os.path.basename(s) for s in srcs]
    top=re.search(r'TOPLEVEL\s*=\s*(\S+)',env).group(1)
    ctx=d['input'].get('context',{})
    ctxn=list(ctx.keys()) if isinstance(ctx,dict) else []
    rows.append((pid,d['categories'],top,bn,ctxn))
for r in rows: print(r[0],r[1],"top=",r[2],"rtl=",r[3],"ctx=",r[4])
