import json,os,shutil,subprocess,re,sys,time
RUN="/home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1333_knowledge_converge"
# usage: score.py <arm> <pid> [pid...]   ; drafts at <RUN>/drafts/<arm>/<pid>/rtl/*.sv
arm=sys.argv[1]; pids=sys.argv[2:]
os.makedirs(f"{RUN}/scores",exist_ok=True)
out=open(f"{RUN}/scores/{arm}_verdicts.txt","a")
IMG="cvdp-sim-pinned:latest"
for pid in pids:
    d=json.load(open(f"{RUN}/records/{pid}.json"))
    h=d['harness']['files']
    stage=f"{RUN}/direct/{arm}_{pid}"
    if os.path.exists(stage): shutil.rmtree(stage)
    os.makedirs(f"{stage}/rtl"); os.makedirs(f"{stage}/src")
    for k,v in h.items():
        if k.startswith('src/'):
            os.makedirs(os.path.dirname(f"{stage}/{k}"),exist_ok=True)
            open(f"{stage}/{k}","w").write(v)
    # seed context rtl (so modification tasks have baseline present), then overlay drafts
    ctx=d['input'].get('context',{})
    if isinstance(ctx,dict):
        for k,v in ctx.items():
            if k.startswith('rtl/'):
                os.makedirs(os.path.dirname(f"{stage}/{k}"),exist_ok=True)
                open(f"{stage}/{k}","w").write(v)
    dd=f"{RUN}/drafts/{arm}/{pid}/rtl"
    if os.path.isdir(dd):
        for fn in os.listdir(dd):
            shutil.copy(f"{dd}/{fn}", f"{stage}/rtl/{fn}")
    cmd=('set -a; while IFS== read -r k v; do k=$(echo $k|xargs); v=$(echo $v|xargs); '
         '[ -n "$k" ] && export "$k=$v"; done < /code/src/.env; set +a; '
         'cd /code/src && python3 -m pytest -q test_runner.py 2>&1 | tail -40')
    t0=time.time()
    try:
        r=subprocess.run(["docker","run","--rm","-v",f"{stage}:/code","-w","/code/src",
            IMG,"bash","-lc",cmd],capture_output=True,text=True,timeout=400)
        log=r.stdout+r.stderr
    except subprocess.TimeoutExpired:
        log="TIMEOUT_400s"
    mp=re.search(r'(\d+) passed',log); mf=re.search(r'(\d+) failed',log); me=re.search(r'(\d+) error',log)
    if 'TIMEOUT' in log: v="TIMEOUT"
    elif mp and not mf and not me: v="PASS"
    elif mf or me: v="FAIL"
    else: v="NO_RESULT"
    open(f"{stage}/pytest.log","w").write(log)
    line=f"{arm} {pid} {v} ({int(time.time()-t0)}s) [{mp.group(0) if mp else ''}|{mf.group(0) if mf else ''}|{me.group(0) if me else ''}]"
    out.write(line+"\n"); out.flush(); print(line,flush=True)
out.close()
