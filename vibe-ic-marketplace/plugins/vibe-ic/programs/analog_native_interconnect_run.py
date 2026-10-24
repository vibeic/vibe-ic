#!/usr/bin/env python3
"""Native unmerged geometry extraction and source-testbench OP/TRAN capture.

No model, device, stimulus or current limit is synthesized by this producer.
Settings select actual testbench/model files, native tools and analysis bounds.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
import analog_native_em as em
import analog_native_waveform as wave
import analog_a7_post_layout_emit as a7
import analog_bound_measurements as measured
import _analog_a8_extraction_wrapper as wrapper
import _container_exec as container_exec


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def current_sha(path):
    try:return sha(path)
    except OSError:return None
def write(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n')
def path(project,value):return (project/str(value)).resolve()


def execute(command,work,container,environment,seconds,log,capture=None,budget=None):
    command=['timeout','-k','5s',f'{seconds}s',*map(str,command)]
    pidfile=work/'native.pid'
    if container:
        group=Path('/var/run/docker.sock').stat().st_gid
        opts=['--user',f'{os.getuid()}:{group}','-w',str(work)]
        for key,value in environment.items():opts+=['-e',f'{key}={value}']
        command=container_exec.docker_exec_argv(container,'sh','-c',
            'printf "%s" "$$" > "$1"; shift; exec "$@"','native-interconnect',str(pidfile),*command,opts=opts)
    env={**os.environ,**environment};started=time.time();limit=False
    write(work/'native-command.json',{'argv':command,'environment':environment,'started':started})
    with log.open('w') as output:
        process=subprocess.Popen(command,cwd=work,env=env,stdout=output,stderr=subprocess.STDOUT)
        while process.poll() is None:
            if capture is not None and budget and capture.exists() and capture.stat().st_size>budget:
                # Stop only this new owned process through its native timeout
                # process, never a sibling job or the container.
                limit=True
                if container:
                    pid=pidfile.read_text().strip()
                    if not pid.isdigit():raise ValueError('owned native PID absent')
                    stop=container_exec.docker_exec_argv(container,'kill','-TERM',pid)
                    subprocess.run(stop,capture_output=True)
                else:process.terminate()
                break
            time.sleep(.25)
        try:rc=process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill();rc=process.wait()
    return {'argv':command,'returncode':rc,'started':started,'ended':time.time(),
            'capture_budget_exceeded':limit}


def native_hashes(container,paths):
    code='import hashlib,json;from pathlib import Path;print(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in '+repr(paths)+'}))'
    command=container_exec.docker_exec_argv(container,'python3','-c',code) if container else [sys.executable,'-c',code]
    result=subprocess.run(command,capture_output=True,text=True,check=True)
    return json.loads(result.stdout)


def extract(project,block,settings,work,container):
    source=project/f'phase3/analog/{block}';gds=source/f'{block}.gds'
    binary=path(project,settings['magic_bin']);manifest=path(project,settings['magic_build_receipt'])
    core=path(project,settings['magic_core']);magicrc=settings['magicrc']
    script=work/'extract.tcl';native=block+'__em'
    script.write_text(f'''drc off
gds read {gds}
load {block}
select top cell
flatten -dotoplabels {native}
load {native}
select top cell
port makeall
save {native}
extract style {settings['style']}
extract do resistance
extract all
extresist extout on
extresist threshold 0
extresist mindelay 0
extresist segments
ext2spice scale off
ext2spice lvs
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice extresist on
ext2spice -o {native}.spice
quit -noprompt
''')
    inputs=[gds,source/f'{block}.sp',source/'topology.json',source/'layout_provenance.json',
            binary,manifest,core,script,work/'settings.json']
    before={str(p):sha(p) for p in inputs}
    record=execute([binary,'-dnull','-noconsole','-rcfile',magicrc,script],work,container,{},
                   settings['timeout_s'],work/'native.log')
    after={str(p):sha(p) for p in inputs}
    record.update(source_inputs_before=before,source_inputs_after=after,unchanged=before==after,
                  outputs={str(p):sha(p) for p in work.iterdir() if p.is_file() and p.name!='command.json'})
    expected=[work/f'{native}.spice',work/f'{native}.res.geom.jsonl']
    record['status']='PASS' if record['returncode']==0 and record['unchanged'] and all(p.is_file() for p in expected) else 'NOT_MEASURED'
    write(work/'command.json',record);return record


def prepare(project,block,settings,work,init_text=''):
    source=project/f'phase3/analog/{block}/{block}.sp'
    topology=source.with_name('topology.json');raw=path(project,settings['spice'])
    geometry=path(project,settings['geometry']);template=path(project,settings['testbench'])
    model=path(project,settings['model_view']);binary=path(project,settings['ngspice_bin'])
    header,*rows=[json.loads(line) for line in geometry.read_text().splitlines()]
    resistors=em.bind_native_resistors(header,rows,raw.read_text())
    ports=wrapper.native_ports(source.read_text(),block)
    text,interface=wrapper.build_wrapper(raw.read_text(),settings['native_subckt'],ports)
    wp=work/'interface.sp';wp.write_text(text)
    post=work/'post.sp'
    bindings=a7.model_binding_lines(model.read_text(),model.parent,work)
    post.write_text('\n'.join([*bindings,f'.include "{raw}"',f'.include "{wp}"',
        f'.subckt {block} '+ ' '.join(ports),'Xrcx '+' '.join(ports)+' '+interface['wrapper_subckt'],f'.ends {block}','']))
    body=measured.contextual_template(template.read_text(),template.parent)
    old=str(path(project,settings['testbench_dut']))
    if body.count(old)!=1:raise ValueError('testbench must identify its exact original DUT include once')
    body=body.replace(old,str(post))
    body=re.sub(r'(?ims)^\s*\.control\b.*?^\s*\.endc\b[^\n]*','',body)
    body=re.sub(r'(?im)^\s*\.(?:end|op|tran|ac|dc|save|temp|meas|measure)\s+[^\n]*|^\s*\.end\s*$','',body)
    analysis=settings['analysis'];kind=analysis['kind'].upper()
    if kind=='OP':command='.op'
    elif kind=='TRAN':
        step,stop,start=(analysis[k] for k in ('step_s','stop_s','start_s'))
        if not 0<step or not 0<=start<stop:raise ValueError('invalid source transient bounds')
        command=f'.tran {step:.17g} {stop:.17g} {start:.17g}'
    else:raise ValueError('OP or TRAN required')
    deck=work/'op.sp'
    import analog_a8_hardmacro_emit as a8
    native_options=settings.get('native_options',[])
    if any(not re.fullmatch(r'[a-zA-Z]\w*=[-+\d.eE]+',value) for value in native_options):
        raise ValueError('explicit numeric native options required')
    options=['.options '+value for value in native_options]
    precision,precision_record=a8._native_op_precision((body+'\n'+'\n'.join(options)).splitlines())
    solver,solver_record=a8._native_op_solver(body.splitlines())
    capture=work/('op.raw' if kind=='OP' else 'tran.raw')
    deck.write_text(body+f'\n.temp {analysis["temperature_c"]:.17g}\n'+
                   '\n'.join([*solver,*options,*precision])+f'\n.save all\n{command}\n'+
                   f'.control\nset num_threads=1\nset filetype=binary\nrun {capture}\nquit\n.endc\n.end\n')
    init=work/'.spiceinit'
    # Initialization files are command streams. Preserve their commands,
    # rather than sourcing them as though they were a SPICE circuit.
    init.write_text(init_text+'\nset num_threads=1\nset filetype=binary\n')
    inputs=[source,topology,raw,geometry,template,model,binary,wp,post,deck,init,work/'settings.json',
            path(project,settings['extraction_receipt'])]
    if settings.get('ngspice_build_receipt'):inputs.append(path(project,settings['ngspice_build_receipt']))
    views={str(p):sha(p) for p in inputs}
    views.update({v['path']:v['sha256'] for v in measured.consumed_input_views(project,deck).values()})
    frozen=work/'executed_driver.py';frozen.write_bytes(Path(__file__).read_bytes())
    views[str(Path(__file__).resolve())]=sha(frozen)
    record={'inputs_before':views,'executed_driver_copy':str(frozen),'interface':interface,'deck':str(deck),
            'analysis':analysis,'source_binding':{'source_testbench':str(template),
            'conditions':{**settings.get('conditions',{}),'temperature_c':analysis['temperature_c']}},
            'scope':'actual unmerged physical '+kind+' at supplied source conditions only'}
    record['precision']=precision_record
    record['solver']=solver_record
    return record,resistors,deck


def run(project,block,settings,work,container):
    init_text=''
    if settings.get('spiceinit'):
        command=(container_exec.docker_exec_argv(container,'cat',settings['spiceinit']) if container
                 else ['cat',settings['spiceinit']])
        init_text=subprocess.run(command,capture_output=True,text=True,check=True).stdout
    record,resistors,deck=prepare(project,block,settings,work,init_text)
    kind=record['analysis']['kind'].upper();capture=work/('op.raw' if kind=='OP' else 'tran.raw')
    log=work/'native.log';record['status']='RUNNING'
    record['native_init_before']=native_hashes(container,settings.get('native_init_paths',[]))
    write(work/'command.json',record)
    environment={**settings.get('environment',{}),'OMP_NUM_THREADS':'1','OMP_WAIT_POLICY':'PASSIVE',
                 'GOMP_SPINCOUNT':'0','SPICE_USERINIT_DIR':str(work)}
    record['native_environment']=environment
    native=execute([path(project,settings['ngspice_bin']),'-b','-o',log,'-r',capture,deck],work,container,
        environment,
        settings['timeout_s'],work/'launcher.log',capture,settings.get('capture_budget_bytes'))
    write(work/'native-execution.json',native)
    record.update(native)
    record['inputs_after']={p:current_sha(p) for p in record['inputs_before']}
    try:record['native_init_after']=native_hashes(container,settings.get('native_init_paths',[]))
    except (OSError,subprocess.SubprocessError,ValueError) as exc:
        record['native_init_after']={'error':str(exc)}
    record['unchanged']=(record['inputs_before']==record['inputs_after'] and
                         record['native_init_before']==record['native_init_after'])
    import analog_real_corner_sweep as sweep
    text=log.read_text(errors='replace') if log.exists() else ''
    failures=[str(item) for item in sweep._scan_analysis_failures(text) if item]
    fatal=bool(failures) or bool(re.search(r'(?i)fatal error|simulation(?:\(s\))? aborted|timestep too small',text))
    status=('FAIL' if fatal else 'NOT_MEASURED' if
            native['returncode'] in (124,130,137,143,-9,-15) or native['capture_budget_exceeded'] or not record['unchanged']
            else 'PASS' if native['returncode']==0 else 'FAIL')
    if status=='PASS':
        try:
            raw=wave.NativeRaw(capture)
            resolver,_=em._vector_resolver(project,block,record,path(project,settings['spice']))
            expressions=[(resolver(parts[1]),resolver(parts[2]),resistance) for parts,row,resistance in resistors]
            if kind=='OP':
                values=raw.row();results=[]
                for (parts,row,resistance),(a,b,_) in zip(resistors,expressions):
                    va,vb=values[a],values[b]
                    results.append({**row,'spice_resistor':parts[0],'spice_nodes':parts[1:3],
                        'spice_resistance_ohm':resistance,'voltage_vectors':[a,b],
                        'voltage_v':[va,vb],'current_a':(va-vb)/resistance})
            else:
                statistics=wave.window_statistics(raw,record['analysis']['window_s'],expressions)
                results=[{**row,'spice_resistor':parts[0],'spice_nodes':parts[1:3],
                    'spice_resistance_ohm':resistance,'voltage_vectors':[a,b],'current_statistics_a':stats}
                    for (parts,row,resistance),(a,b,_),stats in zip(resistors,expressions,statistics)]
            (work/'currents.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in results))
            record.update(measured_segments=len(results),native_variables=raw.shape[1])
        except (OSError,ValueError,KeyError) as exc:status='NOT_MEASURED';record['capture_error']=str(exc)
    record['status']=status;record['native_failures']=failures
    record['outputs']={str(p):sha(p) for p in work.iterdir() if p.is_file() and p.name!='command.json'}
    write(work/'command.json',record);return record


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=['extract','run'])
    parser.add_argument('project',type=Path);parser.add_argument('--block',required=True);parser.add_argument('--settings',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--container',default='')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    settings=json.loads(args.settings.read_text());write(args.out/'settings.json',settings)
    try:result=globals()[args.operation](args.project.resolve(),args.block,settings,args.out,args.container)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        result=json.loads((args.out/'command.json').read_text()) if (args.out/'command.json').is_file() else {}
        result.update(status='NOT_MEASURED',detail=str(exc));write(args.out/'command.json',result)
    print(json.dumps({k:v for k,v in result.items() if k in ['status','detail','capture_error','returncode','measured_segments','native_variables']},indent=2))
    return 0 if result['status']=='PASS' else 1 if result['status']=='FAIL' else 2


if __name__=='__main__':raise SystemExit(main())
