#!/usr/bin/env python3
"""Native unmerged geometry extraction and source-testbench OP/TRAN capture.

No model, device, stimulus or current limit is synthesized by this producer.
Settings select actual testbench/model files, native tools and analysis bounds.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
import analog_native_em as em
import analog_native_waveform as wave
import analog_a7_post_layout_emit as a7
import analog_bound_measurements as measured
import _analog_a8_extraction_wrapper as wrapper
import _container_exec as container_exec


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()
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


RAW_RAM_ROOT=Path('/dev/shm')


def _storage_options(project,settings):
    enabled=settings.get('compress_raw',False)
    if not isinstance(enabled,bool):raise ValueError('compress_raw must be boolean')
    scratch=settings.get('raw_scratch_dir')
    if scratch is not None:
        if not enabled:raise ValueError('raw_scratch_dir requires compress_raw=True')
        if not isinstance(scratch,str) or not scratch:raise ValueError('raw_scratch_dir must name an existing directory')
        scratch=path(project,scratch)
        if not scratch.is_dir() or scratch.stat().st_uid!=os.getuid():
            raise ValueError('raw_scratch_dir must preexist and be caller owned')
    return enabled,scratch


def _capture_target(capture,scratch,container):
    if os.path.lexists(capture):raise ValueError('native capture target already exists')
    state={'executed':capture,'real':capture,'scratch':None}
    if scratch is not None:
        child=Path(tempfile.mkdtemp(prefix='native-raw-',dir=scratch))
        real=child/capture.name
        with real.open('xb'):pass
        identity=real.stat()
        capture.symlink_to(real)
        alias=capture.lstat()
        state.update(real=real,scratch=child,identity=(identity.st_dev,identity.st_ino),
                     alias_identity=(alias.st_dev,alias.st_ino))
        if container and native_hashes(container,[str(real)])!={str(real):sha(real)}:
            raise ValueError('raw scratch target is not visible in the native container')
    return state


def _owned_raw(state):
    capture,real=state['executed'],state['real']
    if state['scratch'] is not None:
        alias=capture.lstat()
        if (not stat.S_ISLNK(alias.st_mode) or (alias.st_dev,alias.st_ino)!=state['alias_identity']
                or os.readlink(capture)!=str(real)):
            raise ValueError('owned native capture alias changed')
    elif capture.is_symlink():raise ValueError('refusing an undeclared native capture symlink')
    info=real.lstat()
    if not stat.S_ISREG(info.st_mode) or ('identity' in state and
            (info.st_dev,info.st_ino)!=state['identity']):
        raise ValueError('owned native raw target identity changed')
    return real,info


def _gzip_identity(path):
    digest=hashlib.sha256();size=0
    with gzip.open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk);size+=len(chunk)
    return digest.hexdigest(),size


def _store_raw(state,work):
    """Archive only a completed owned regular raw, retaining RAM on failure."""
    real,before=_owned_raw(state);original=sha(real)
    final=state['executed'].with_name(state['executed'].name+'.gz')
    staged=final.with_name(final.name+'.copy')
    if os.path.lexists(final) or os.path.lexists(staged):raise ValueError('stored native raw output already exists')
    ram=Path(tempfile.mkdtemp(prefix='native-raw-gzip-',dir=RAW_RAM_ROOT));compressed=ram/final.name
    write(work/'raw-storage-start.json',{'executed_path':str(state['executed']),'real_native_path':str(real),
        'native_identity':[before.st_dev,before.st_ino],'raw_sha256':original,'raw_bytes':before.st_size,
        'ram_gzip':str(compressed),'phase':'COMPRESSING'})
    with real.open('rb') as source,compressed.open('xb') as output:
        with gzip.GzipFile(filename='',mode='wb',fileobj=output,mtime=0,compresslevel=6) as target:
            shutil.copyfileobj(source,target,1024*1024)
    if _gzip_identity(compressed)!=(original,before.st_size):
        raise ValueError('native raw RAM gzip is not lossless')
    same,after=_owned_raw(state)
    if (same!=real or (after.st_dev,after.st_ino,after.st_size)!=(before.st_dev,before.st_ino,before.st_size)
            or sha(real)!=original):raise ValueError('native raw changed during compression')
    metadata={'executed_path':os.path.abspath(state['executed']),'stored_path':str(final),
              'encoding':'gzip','sha256':sha(compressed),'raw_sha256':original,'raw_bytes':before.st_size}
    recovery={**metadata,'real_native_path':str(real),'native_identity':[before.st_dev,before.st_ino],
              'ram_gzip':str(compressed),'phase':'RAM_VERIFIED'}
    write(work/'raw-storage-ram.json',recovery)
    # Binary writing has ended. Guarded removal frees SSD space before its
    # archive is copied back; the verified RAM gzip remains recoverable.
    _owned_raw(state)
    if state['scratch'] is not None:state['executed'].unlink()
    real.unlink()
    with compressed.open('rb') as source,staged.open('xb') as output:
        shutil.copyfileobj(source,output,1024*1024);output.flush();os.fsync(output.fileno())
    if sha(staged)!=metadata['sha256'] or _gzip_identity(staged)!=(original,before.st_size):
        raise ValueError('stored native raw copy is not lossless')
    os.link(staged,final);staged.unlink()
    write(work/'raw-storage-ssd.json',{**recovery,'phase':'SSD_VERIFIED'})
    return metadata,compressed,state


def _cleanup_raw_storage(stored,work):
    metadata,compressed,state=stored
    try:
        if sha(Path(metadata['stored_path']))!=metadata['sha256'] or sha(compressed)!=metadata['sha256']:
            raise ValueError('native raw archive identity changed before cleanup')
        compressed.unlink();compressed.parent.rmdir()
        if state['scratch'] is not None:state['scratch'].rmdir()
        cleanup={'ram_removed':True,'scratch_removed':state['scratch'] is not None}
    except (OSError,ValueError) as exc:cleanup={'ram_removed':False,'detail':str(exc)}
    write(work/'raw-storage-cleanup.json',cleanup)


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
    if any(not re.fullmatch(r'(?:method=(?:gear|trap)|(?!method=)[a-zA-Z]\w*=[-+\d.eE]+)',
                            value,flags=re.I) for value in native_options):
        raise ValueError('explicit numeric native options or method=gear|trap required')
    options=['.options '+value for value in native_options]
    precision,precision_record=a8._native_op_precision((body+'\n'+'\n'.join(options)).splitlines())
    solver,solver_record=a8._native_op_solver((body+'\n'+'\n'.join(options)).splitlines())
    capture=work/('op.raw' if kind=='OP' else 'tran.raw')
    # ngspice case-folds `run` arguments, even quoted absolute filenames.
    # The native process already runs in this exact work directory.
    deck.write_text(body+f'\n.temp {analysis["temperature_c"]:.17g}\n'+
                   '\n'.join([*solver,*options,*precision])+f'\n.save all\n{command}\n'+
                   f'.control\nset num_threads=1\nset filetype=binary\nrun {capture.name}\nquit\n.endc\n.end\n')
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
    compress,scratch=_storage_options(project,settings)
    init_text=''
    if settings.get('spiceinit'):
        command=(container_exec.docker_exec_argv(container,'cat',settings['spiceinit']) if container
                 else ['cat',settings['spiceinit']])
        init_text=subprocess.run(command,capture_output=True,text=True,check=True).stdout
    record,resistors,deck=prepare(project,block,settings,work,init_text)
    kind=record['analysis']['kind'].upper();capture=work/('op.raw' if kind=='OP' else 'tran.raw')
    storage_state=_capture_target(capture,scratch,container) if compress else None
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
    stored=None
    if compress:
        try:
            stored=_store_raw(storage_state,work)
            record['native_raw']=stored[0]
            capture=Path(record['native_raw']['stored_path'])
        except (OSError,ValueError,EOFError) as exc:
            record['raw_storage_error']=str(exc)
            if status!='FAIL':status='NOT_MEASURED'
    if status=='PASS':
        try:
            options=({'expected_raw_sha256':record['native_raw']['raw_sha256'],
                      'expected_raw_bytes':record['native_raw']['raw_bytes']} if stored else {})
            raw=wave.NativeRaw(capture,**options)
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
    write(work/'command.json',record)
    if stored:
        _cleanup_raw_storage(stored,work)
        record['outputs']={str(p):sha(p) for p in work.iterdir() if p.is_file() and p.name!='command.json'}
        write(work/'command.json',record)
    return record


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
