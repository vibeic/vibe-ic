"""Explicit fail-closed frontend producer entry points."""

# `programs/` is a flat directory whose modules import each other by bare name
# (vibe-ic#2104): restore the condition a by-path load does not provide.
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import argparse, json, os, subprocess, shutil, sys
import hashlib
from pathlib import Path
import time
from contextvars import ContextVar
from _execution_manifest import (ISSUED_MANIFEST_ENV, issued_manifest_path, is_exclusive_regular)
_STEP8_PRODUCER_TIMEOUT_S = 30
_STEP8_DISPATCH = ContextVar('step8_dispatch', default=False)
_MANIFEST_AUTHORITY = ContextVar('manifest_authority', default=None)


def _flow_contract(step):
    import _flow_yaml
    return next((dict(row) for row in _flow_yaml.load().get('steps', ())
                 if str(row.get('id')) == str(step)), None)

def _write(step, output, producer, **details):
    output=Path(output); output.mkdir(parents=True, exist_ok=True)
    out=output/'canonical.json'
    out.write_text(json.dumps({'schema':'frontend_worker_output/1','step_id':step,'producer':producer,'result':'NOT_MEASURED',**details},sort_keys=True,default=str)+'\n')
    return out
def _strict_issuance() -> bool:
    return bool(os.environ.get('VIBEIC_MANIFEST_SHA256'))

def _issued_manifest_path(project, authority_path=None):
    """Resolve the one Controller-issued authority path for a worker run.

    Controller dispatch binds this path explicitly in both argv and the
    environment. Without an explicit path, only the input-root authority is
    consumed. No nested same-basename input can select worker authority.
    """
    project = Path(project)
    bound = os.environ.get(ISSUED_MANIFEST_ENV)
    raw = authority_path or _MANIFEST_AUTHORITY.get() or bound
    path = Path(raw) if raw else issued_manifest_path(project)
    if bound and path.absolute() != Path(bound).absolute():
        raise ValueError('issued manifest authority path mismatch')
    if ((authority_path or _strict_issuance()) and
            not is_exclusive_regular(path)):
        raise ValueError('issued manifest authority path is required')
    if path.is_symlink() or not path.is_file():
        raise ValueError('issued manifest authority path is required')
    return path

def _step8_inputs(project, manifest):
    """Require every canonical input, nonempty and covered by the manifest."""
    import _flow_yaml
    row = next(s for s in _flow_yaml.load()['steps'] if str(s['id']) == '8')
    for contract in row['required_inputs']:
        matches = list(Path(project).glob(contract['path']))
        if not matches:
            raise ValueError(f"8: required input missing: {contract['path']}")
        for path in matches:
            rel = str(path.relative_to(project))
            if (path.is_symlink() or not path.is_file() or
                    (_strict_issuance() and not is_exclusive_regular(path)) or
                    not path.stat().st_size or
                    manifest['files'].get(rel) != hashlib.sha256(path.read_bytes()).hexdigest()):
                raise ValueError(f'8: required input empty or unbound: {rel}')

def _verify_manifest(project, step):
    manifest = _issued_manifest_path(project) if _strict_issuance() else (Path(project)/'input'/'issued_manifest.json')
    if not manifest.is_file():
        manifest = issued_manifest_path(project)
    if not manifest.is_file():
        raise ValueError(f'{step}: issued manifest is required')
    try: record=json.loads(manifest.read_text())
    except (OSError,ValueError) as exc: raise ValueError(f'{step}: issued manifest invalid') from exc
    if record.get('step_id') != step: raise ValueError(f'{step}: issued route mismatch')
    if not isinstance(record.get('parameters'), dict):
        raise ValueError(f'{step}: issued parameters missing')
    if os.environ.get('VIBEIC_ISSUED_MANIFEST_SHA256'):
        observed = hashlib.sha256(manifest.read_bytes()).hexdigest()
        if observed != os.environ['VIBEIC_ISSUED_MANIFEST_SHA256']:
            raise ValueError(f'{step}: issued manifest binding mismatch')
    root = Path(project).resolve()
    for rel, expected in (record.get('files') or {}).items():
        if not isinstance(rel, str) or Path(rel).is_absolute() or '..' in Path(rel).parts:
            raise ValueError(f'{step}: issued input path is unsafe: {rel!r}')
        path=root / rel
        if (not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file() or
                (_strict_issuance() and not is_exclusive_regular(path)) or
                hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise ValueError(f'{step}: issued input mutation: {rel}')
    return record

def _require(project, output, step, producer, **kwargs):
    if project is None or output is None: raise ValueError(f'{step}: project and output are required')
    project=Path(project)
    _verify_manifest(project, step)
    return _write(step,output,producer,reason=('input project is unavailable' if not project.exists() else 'producer is source-bound; native qualification not measured'),inputs=str(project),parameters=kwargs)

def _record(step, project, output, producer, fn, **kwargs):
    if project is None or output is None: raise ValueError(f'{step}: project and output are required')
    _verify_manifest(project, step)
    try:
        value=fn(Path(project), **kwargs)
    except (FileNotFoundError, ImportError, OSError) as exc:
        return _write(step, output, producer, reason=f'native producer unavailable: {exc}', parameters=kwargs)
    return _write(step, output, producer, reason='producer executed; canonical qualification remains consumer-owned', producer_result=value, parameters=kwargs)
def _cli(step, project, output, modules, args=()):
    _verify_manifest(project,step); records=[]
    for module in modules:
        try: cp=subprocess.run(['python3',str(Path(__file__).with_name(module+'.py')),str(project),*map(str,args)],capture_output=True,text=True)
        except OSError as exc: return _write(step,output,','.join(modules),reason=f'producer unavailable: {exc}',records=records)
        records.append({'program':module,'rc':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr})
        if cp.returncode != 0: return _write(step,output,','.join(modules),reason='producer failed',records=records)
    return _write(step,output,','.join(modules),reason='all producers executed',records=records)

def produce_d1(project,output,**k):
    from dataclasses import asdict
    from execution_modes import require_issued_frontend
    manifest = _verify_manifest(project, 'D1')
    parameters = manifest['parameters']
    # The existing live Controller binds this child, argv, source and census.
    # A standalone helper or serialized manifest cannot authorize production.
    require_issued_frontend(project, output, 'D1', parameters)
    project, output = Path(project), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'canonical.json').unlink(missing_ok=True)
    # Phase 1 writes L-docs and expert handoffs. As with Step 8, reconstruct
    # only the issued census in its private project, never in frozen inputs.
    staged = output / 'project'
    if staged.exists(): shutil.rmtree(staged)
    staged.mkdir()
    for rel in manifest['files']:
        target = staged / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / rel, target)
    require_issued_frontend(project, output, 'D1', parameters)
    # Invoke the existing producer primitives inside this issued worker.
    # Re-entering the Phase-1 launcher would bootstrap a different project.
    # Selection objectives stay in issuance, never become producer kwargs.
    import phase1_one_shot_runner as phase1
    import _phase1_producer_identity as identity
    producer = 'phase1_one_shot_runner._run_docs_mode+run_phase1_second_track'
    started = time.monotonic()
    input_before = identity.input_tree_snapshot(staged)
    recorder = identity.ProducerRecorder()
    with recorder:
        rc_extract = phase1._as_the_producer(phase1._run_docs_mode)(staged, 'UNNAMED_CHIP')
        rc_track = (2 if rc_extract == 2 else phase1.run_phase1_second_track(staged, 0))
    if identity.docs_snapshot(staged):
        identity.stamp(staged, recorder, input_before=input_before,
                       knobs={'ic_name': 'UNNAMED_CHIP', 'mode': 'docs'})
    rows = [phase1._delegated_step_result(phase1.D1_STEP_NAME, rc_extract,
                time.monotonic() - started, f'docs producer rc={rc_extract}'),
            phase1._delegated_step_result('phase1_expert_parse_track', rc_track,
                0.0, phase1._expert_track_summary(staged), upstream=rc_extract == 2)]
    verdict = phase1._aggregate_verdict(rows)
    value = phase1.StepResult('phase1', verdict, time.monotonic() - started,
                f'docs rc={rc_extract}; expert track rc={rc_track}',
                reason_class='no_population' if verdict == 'NOT_MEASURED' else '')
    require_issued_frontend(project, output, 'D1', parameters)
    return _write('D1', output, producer, producer_result=asdict(value),
                  producer_steps=[asdict(row) for row in rows],
                  reason='producer executed; D1 handoff qualification is not connected')


def _output_paths(root, required):
    """Resolve the canonical YAML output contract to concrete regular files."""
    found = {}
    for spec in required:
        alternatives = [part.strip() for part in str(spec).split(' OR ')]
        matches = []
        for alternative in alternatives:
            candidate = root / alternative
            if any(ch in alternative for ch in '*?['):
                matches.extend(sorted(p for p in root.glob(alternative)
                                     if p.is_file() and not p.is_symlink()))
            elif candidate.is_file() and not candidate.is_symlink():
                matches.append(candidate)
        for path in matches:
            found[str(path.relative_to(root))] = str(spec)
    return found


def _write_step_binding(root, step, paths):
    """Emit the small step-scoped write record consumed by the strict checker."""
    contract = _flow_contract(step)
    if not contract:
        raise ValueError(f'{step}: canonical flow row is unavailable')
    folder = 'phase1/stage_phase1/0.5ic_submission_template_ingest'
    step_root = root / 'steps' / folder
    step_root.mkdir(parents=True, exist_ok=True)
    produced = []
    for rel, spec in sorted(paths.items()):
        path = root / rel
        stat = path.stat()
        produced.append({'rel': rel, 'size': stat.st_size, 'mtime': stat.st_mtime,
                         'kind': 'file', 'spec': spec})
    row = {'id': str(step), 'n_required_outputs': len(contract.get('required_outputs') or ()),
           'n_produced': len(produced), 'produced': produced, 'findings': []}
    (step_root / 'written.json').write_text(json.dumps(row, sort_keys=True) + '\n')
    (root / 'steps' / 'index.json').write_text(json.dumps(
        {'steps': [{'id': str(step), 'name': 'submission template and tapeout declaration',
                    'folder': folder}]}, sort_keys=True) + '\n')


def _producer_writes(result, root):
    """Read the real producer's private pipe, not caller-writable output hashes."""
    records = [line.split('=', 1)[1] for line in result.stdout.splitlines()
               if line.startswith('VIBEIC_PRODUCER_WRITES=')]
    if len(records) != 1:
        raise RuntimeError('0.5ic: producer publication capture is unavailable')
    result = {}
    for path, record in json.loads(records[0]).items():
        rel = str(Path(path).relative_to(root))
        value, version = record['sha256'], record['version']
        if (not isinstance(value, str) or len(value) != 64 or
                not isinstance(version, list) or len(version) != 6):
            raise RuntimeError('0.5ic: invalid producer publication digest')
        result[rel] = record
    if not result:
        raise RuntimeError('0.5ic: producer published nothing')
    return result


def produce_05ic(project,output,template=None,no_template_reason=None,**k):
    if isinstance(template, os.PathLike):
        template = os.fspath(template)
    has_template = isinstance(template, str) and bool(template.strip())
    has_reason = isinstance(no_template_reason, str) and bool(no_template_reason.strip())
    if not has_template:
        raise ValueError('0.5ic: a searched template path is required')
    if no_template_reason is not None and not has_reason:
        raise ValueError('0.5ic: no_template_reason must be non-empty text')
    # A declared absence is deliberately a two-part fact: the searched path
    # and the owner's reason.  A template path with no reason is the shuttle
    # route; the same path with a reason is the explicit absence route.
    declared_absence = has_reason
    if declared_absence and k.get('slot') not in (None, ''):
        raise ValueError('0.5ic: declared absence cannot name a shuttle slot')
    from execution_modes import (require_issued_frontend, FrontendSnapshot,
                                 _frontend_tree, _hash, issue_frontend_chain)
    parameters = dict(k, template=template)
    if no_template_reason is not None:
        parameters['no_template_reason'] = no_template_reason
    manifest = _verify_manifest(project, '0.5ic')
    bound=manifest.get('parameters') or {}
    for key, value in (('template', template), ('no_template_reason', no_template_reason),
                       ('slot', k.get('slot'))):
        if value is not None and key in bound and bound[key] != value:
            raise ValueError(f'0.5ic: {key} disagrees with issued manifest')
    project, output = Path(project), Path(output)
    bound_slot = bound.get('slot', k.get('slot'))
    if declared_absence and bound_slot not in (None, ''):
        raise ValueError('0.5ic: declared absence cannot name a shuttle slot')
    answers_source = project / 'input/step_0_5ic_answers.json'
    if not answers_source.is_file():
        raise ValueError('0.5ic: answers file is required')
    try:
        answers_doc=json.loads(answers_source.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('0.5ic: answers file is invalid') from exc
    if not isinstance(answers_doc, dict):
        raise ValueError('0.5ic: answers file must be a JSON object')
    require_issued_frontend(project, output, '0.5ic', parameters)
    # Capture once from the issued input. Inode versions catch writers that
    # restore the same bytes during capture. Producer 2 never copies this
    # first producer's owner/template input back out of a shared directory.
    initial = _frontend_tree(project)
    contents = {name: (project / name).read_bytes() for name in manifest['files']}
    require_issued_frontend(project, output, '0.5ic', parameters)
    if (_frontend_tree(project) != initial or
            {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()} != manifest['files']):
        raise RuntimeError('0.5ic: issued input changed during capture')
    staged = output / 'project'; output.mkdir(parents=True, exist_ok=True)
    first = FrontendSnapshot(staged, contents)
    executable = str(Path(sys.executable).resolve())
    args1=[executable,str(Path(__file__).with_name('submission_template_ingest.py')),str(staged)]
    if has_template:
        template_path=Path(template)
        if template_path.is_absolute():
            try:
                template_path=staged / template_path.resolve().relative_to(project.resolve())
            except ValueError as exc:
                raise ValueError('0.5ic: template must be inside the frozen project') from exc
        elif '..' in template_path.parts or str(template_path) == '.':
            raise ValueError('0.5ic: template path is unsafe')
        args1 += ['--template',str(template_path)]
    if declared_absence:
        args1 += ['--no-template-reason',str(no_template_reason).strip()]
    slot=bound_slot
    if has_template and not declared_absence and slot:
        args1 += ['--slot', str(slot)]
    answers=staged/'input/step_0_5ic_answers.json'
    if not declared_absence:
        staged_template=Path(args1[args1.index('--template') + 1])
        if not staged_template.is_absolute():
            staged_template=staged / staged_template
        # A missing searched path is an ingest result, not a process error.
        # The real producer records ABSENT without a routing marker; the
        # unchanged gate requires the owner's reason before it can qualify.
        if staged_template.exists() and not staged_template.is_dir():
            raise ValueError('0.5ic: template directory is unavailable')
    else:
        try:
            from _submission_template import MIN_REASON_CHARS
        except ImportError as exc:
            raise ValueError('0.5ic: route validator unavailable') from exc
        if (not isinstance(no_template_reason, str) or
                len(no_template_reason.strip()) < MIN_REASON_CHARS):
            raise ValueError('0.5ic: no_template_reason is too short')
        searched = Path(args1[args1.index('--template') + 1])
        if not searched.is_absolute():
            searched = staged / searched
        if searched.is_symlink() or searched.exists():
            raise ValueError('0.5ic: declared absence requires a missing searched path')
    second_root = output / 'producer2_project'
    args2=[executable,str(Path(__file__).with_name('tapeout_declaration_gen.py')),str(second_root),
           '--answers','input/step_0_5ic_answers.json']
    snapshots = [first]; stages = []; publications = {}
    try:
        for index, argv in enumerate((args1, args2)):
            snapshot = snapshots[index]
            require_issued_frontend(project, output, '0.5ic', parameters)
            for lease in snapshots:
                lease.current()
            stage = dict(root=str(snapshot.root), argv=argv,
                         inputs={name: row['sha256'] for name, row in snapshot.inputs.items()},
                         issued_tree=dict(snapshot.before),
                         predecessor_sha256=_hash(stages[0]) if index else None)
            cp=subprocess.run(argv, cwd=snapshot.root, capture_output=True, text=True,
                              env={**os.environ, 'VIBEIC_CAPTURE_FRONTEND_WRITES': '1'})
            if cp.returncode != 0:
                raise RuntimeError(f'0.5ic producer failed rc={cp.returncode}')
            published = _producer_writes(cp, snapshot.root)
            written = {name: row['sha256'] for name, row in published.items()}
            if set(written) & set(stage['inputs']):
                raise RuntimeError('0.5ic: producer overwrote an issued input')
            snapshot.protect_intermediate(written, {name: row['version'] for name, row in published.items()})
            publications.update(written)
            stage.update(rc=cp.returncode, outputs=written,
                         final_tree=snapshot.current())
            stages.append(stage)
            if index == 0:
                if set(written) & set(contents):
                    raise RuntimeError('0.5ic: intermediate collides with issued input')
                intermediate = {name: (staged / name).read_bytes() for name in written}
                if {name: hashlib.sha256(value).hexdigest() for name, value in intermediate.items()} != written:
                    raise RuntimeError('0.5ic: intermediate changed during capture')
                if first.current() != stage['final_tree']:
                    raise RuntimeError('0.5ic: first snapshot changed during capture')
                second = FrontendSnapshot(second_root, {**contents, **intermediate},
                                          retired=('input/submission_template/NO_TEMPLATE.txt',))
                snapshots.append(second)
        contract = _flow_contract('0.5ic')
        paths = _output_paths(second_root, contract.get('required_outputs') or ())
        expected = {str(spec) for spec in contract.get('required_outputs') or ()}
        if set(paths.values()) != expected:
            missing = sorted(expected - set(paths.values()))
            raise RuntimeError(f'0.5ic producer outputs incomplete: {missing}')
        outputs = {rel: publications[rel] for rel in paths}
        for rel, expected_digest in outputs.items():
            content = (second_root / rel).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected_digest:
                raise RuntimeError('0.5ic: output changed before export')
            dst = output / rel; dst.parent.mkdir(parents=True,exist_ok=True)
            with dst.open('xb') as stream:
                stream.write(content)
        _write_step_binding(output, '0.5ic', paths)
        # The declaration gate resolves derived-answer provenance from the
        # output project. These are issued input copies, not produced views.
        for rel, content in contents.items():
            if rel.startswith('input/docs/'):
                target = output / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(content)
        for index, lease in enumerate(snapshots):
            if lease.current() != stages[index]['final_tree']:
                raise RuntimeError('0.5ic: snapshot changed before completion')
        stages[1]['outputs'] = outputs
        require_issued_frontend(project, output, '0.5ic', parameters)
        issue_frontend_chain(output, dict(stages=stages, outputs=outputs,
                             output_ctimes={name: (output / name).stat().st_ctime_ns for name in outputs}))
    finally:
        for lease in snapshots:
            lease.close()
    return output/'reports/phase1/tapeout_declaration.json'
def produce_1(project,output,ic_class=None,force_regen=False,**k):
    if not ic_class: raise ValueError('1: ic_class is required')
    import design_one_shot_runner as d
    return _record('1',project,output,'design_one_shot_runner.step_rtl_gen',d.step_rtl_gen,ic_class=ic_class,force_regen=force_regen,**k)
def produce_2(project,output,top=None,clock=None,timeout=None,**k):
    for name in ('top','clock','timeout','baseline_rtl_dir','candidate_rtl_dir'):
        if k.get(name) in (None,'') and name not in ('top','clock','timeout'):
            raise ValueError(f'2: {name} is required')
    if not top or not clock or timeout is None: raise ValueError('2: top, clock and timeout are required')
    import p0_tool_frontend_check as p0
    result=p0.check(Path(project))
    args=['python3',str(Path(__file__).with_name('crosslayer_rewrite_equivalence.py')),str(project),'--baseline-rtl-dir',str(k['baseline_rtl_dir']),'--candidate-rtl-dir',str(k['candidate_rtl_dir']),'--top',top,'--clock',clock,'--timeout',str(timeout),'--json',str(Path(output)/'crosslayer.json')]
    cp=subprocess.run(args,capture_output=True,text=True)
    return _write('2',output,'p0_tool_frontend_check.check+crosslayer_rewrite_equivalence.main',producer_result=result,records=[{'argv':args,'rc':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr}],parameters=dict(top=top,clock=clock,timeout=timeout,**k))
def produce_3(project,output,top=None,image=None,**k):
    if not top: raise ValueError('3: top is required')
    return _cli('3',project,output,('cdc_crossing_check','cdc_async_input_check','clock_domain_reg_crossing_check','reset_dependency_check'),('--json',str(Path(output)/'cdc.json')))
def produce_4(project,output,top=None,container=None,**k):
    if not top or not container: raise ValueError('4: top and container are required')
    import design_one_shot_runner as d
    vals=[d.step_professional_tb_gen(Path(project),top,container),d.step_reference_tb(Path(project),top,k.get('ic_class'),container),d.step_l10_unit_tb_run(Path(project),container)]
    return _cli('4',project,output,('verilator_coverage_measure',),('measure-tb','--project',str(project),'--top',top,'--out',str(Path(output)/'coverage.json')))
def produce_5(project,output,top=None,container=None,**k):
    if not top or not container: raise ValueError('5: top and container are required')
    import formal_harness_gen as h, formal_property_run as f, design_one_shot_runner as d
    h.generate(Path(project),top=top,container=container); f.run(Path(project),top=top); d.step_full_stack_functional_tb(Path(project),container)
    return _write('5',output,'formal_harness_gen.generate+formal_property_run.run+step_full_stack_functional_tb',parameters=dict(top=top,container=container))
def produce_6(project,output,top=None,container=None,**k):
    # The provider is implemented even when the host has no Quartus/board.  In
    # that case retain an explicit exclusion so Controller does not count it
    # as an aggregate failure.
    if not shutil.which('quartus_map') and not (k.get('fpga') or k.get('board')):
        return _write('6', output, 'step_fpga_compile+quartus_map_audit',
                      reason='Quartus/board unavailable', verdict='NOT_MEASURED',
                      excluded_from_verdict=True)
    return _cli('6',project,output,('quartus_map_audit',),())
def produce_7(project,output,top=None,pdk=None,container=None,**k): return _require(project,output,'7','emit_step7_asic_sdc+stamp_pvt_corner_coverage',top=top,pdk=pdk,container=container,**k)
def produce_8(project,output,**k):
    """Run the complete Step-8 contract against the staged project."""
    if not _STEP8_DISPATCH.get():
        raise ValueError('8: direct helper execution is unissued')
    manifest = _verify_manifest(project, '8')
    if not _strict_issuance():
        raise ValueError('8: legacy helper execution is unissued')
    _step8_inputs(Path(project), manifest)
    project, output = Path(project), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'canonical.json').unlink(missing_ok=True)
    # Stage only immutable design inputs; all reports are private outputs.
    staged = output / 'project'
    if staged.exists(): shutil.rmtree(staged)
    staged.mkdir()
    # Copy the bound ordinary census, including nested authority basenames.
    # The root metadata file is excluded by issuance, never by basename.
    for rel in manifest['files']:
        target = staged / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / rel, target)
    # Canonical consumer addresses the staged project root; expose immutable
    # staged inputs there while keeping the private reconstruction directory.
    (staged / 'phase2/stage1/rtl').mkdir(parents=True, exist_ok=True)
    for rel in ('phase1', 'phase2'):
        src = staged / rel; dst = output / rel
        if src.is_dir() and not dst.exists(): shutil.copytree(src, dst)
    report = output / 'reports/phase2/sdc_check.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    l8 = k.get('l8') or next(staged.rglob('L8_TIMING_WAVEFORM.json'), None)
    if l8 is not None:
        l8 = Path(l8)
        if not l8.is_absolute():
            l8 = staged / l8
        elif l8.exists():
            # A discovered L8 path is already inside the staged tree.  Only
            # remap an explicitly supplied absolute path from the source
            # project; string-prefix checks would treat ``/project-out`` as a
            # child of ``/project`` and raise before the producer runs.
            try:
                l8 = staged / l8.relative_to(project)
            except ValueError:
                pass
    validator_report = output / 'reports/sdc_validator.json'
    # The canonical Step-8 audit also has an optional derived-clock clause.
    # Give it the declared empty RTL scope when this source-only fixture has
    # no RTL, so the checker records an honest zero-denominator PASS instead
    # of an absent-input diagnostic.
    (staged / 'phase2/stage1/rtl').mkdir(parents=True, exist_ok=True)
    commands = [
        ['python3', str(Path(__file__).with_name('sdc_syntax_check.py')), str(staged), '--json', str(report)],
        ['python3', str(Path(__file__).with_name('sdc_validator_check.py')), str(staged), '--l8', str(l8), '--json', str(validator_report)],
        ['python3', str(Path(__file__).with_name('derived_clock_sdc_required_check.py')),
         str(staged / 'phase2/stage1/rtl'), '--sdc',
         str(staged / 'phase2/stage2/constraints'), '--json',
         str(output / 'reports/phase2/gates/derived_clock_sdc.json')],
    ]
    records=[]
    for program, argv in zip(('sdc_syntax_check', 'sdc_validator_check',
                              'derived_clock_sdc_required_check'), commands):
        if l8 is None and '--l8' in argv:
            return _write('8', output, 'sdc_syntax_check+sdc_validator_check', reason='L8 fixture missing', records=records)
        target = Path(argv[-1])
        def fingerprint():
            if not target.is_file() or target.is_symlink():
                return None
            stat = target.stat()
            return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns,
                    stat.st_ctime_ns, hashlib.sha256(target.read_bytes()).hexdigest())
        before = fingerprint()
        started_ns = time.time_ns()
        try:
            cp=subprocess.run(argv, capture_output=True, text=True,
                              timeout=_STEP8_PRODUCER_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f'Step8 producer timed out after {_STEP8_PRODUCER_TIMEOUT_S}s: '
                f'{argv[0]}') from exc
        ended_ns = time.time_ns()
        after = fingerprint()
        if (after is None or not after[2] or after == before or
                not started_ns <= after[3] <= ended_ns):
            raise RuntimeError(f'Step8 producer output missing, empty or stale: {target}')
        records.append({'program': program, 'argv':argv, 'rc':cp.returncode,
                        'stdout':cp.stdout, 'stderr':cp.stderr,
                        'started_ns':started_ns, 'ended_ns':ended_ns,
                        'output':str(target.relative_to(output)),
                        'output_mtime_ns':after[3], 'output_sha256':after[5]})
        if cp.returncode != 0:
            _write('8', output, 'sdc_syntax_check+sdc_validator_check',
                   issued_manifest_sha256=os.environ['VIBEIC_MANIFEST_SHA256'],
                   reason='measured producer failure', records=records)
            raise RuntimeError(f'Step8 producer failed rc={cp.returncode}: {argv[0]}')
    _write('8', output, 'sdc_syntax_check+sdc_validator_check',
           reason='all producers executed', records=records,
           issued_manifest_sha256=os.environ['VIBEIC_MANIFEST_SHA256'])
    # Bind the required output to this worker's observation.  The canonical
    # checker refuses a project-wide glob match without the run's own ledger.
    # A minimal index is enough for the ledger reader; the ledger itself is
    # generated from live output bytes and is not caller-authored evidence.
    index = output / 'steps/index.json'
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({'steps': [{'id': '8',
        'folder': 'phase2/stage2/8_sdc_validation'}]}) + '\n')
    import step_write_ledger
    step_write_ledger.emit(output)
    return report
def produce_10(project,output,top=None,pdk=None,container=None,**k): return _require(project,output,'10','step_prelayout_signoff',top=top,pdk=pdk,container=container,**k)
def produce_11(project,output,top=None,clock=None,pdk=None,**k): return _cli('11',project,output,('fault_scan_chain_insert','fault_atpg_run','bsdl_emit'))
def produce_fs1(project,output,**k): return _cli('FS1',project,output,('fmeda_fault_injection_coverage','fmeda_coverage_check'))
def produce_dt1(project,output,top=None,clock=None,timeout=None,**k): return _cli('DT1',project,output,('transition_fault_atpg_run',))
def produce_12(project,output,**k):
    if project is None or output is None: raise ValueError('12: project and output are required')
    project=Path(project); output=Path(output); scan=project/'phase2/stage2/dft/scan_netlist.v'; target=output/'phase2/stage2/synth/post_dft_netlist.v'
    if not scan.is_file(): return _write('12',output,'design_one_shot_runner Yosys command',reason='scan netlist input unavailable',inputs=str(scan))
    target.parent.mkdir(parents=True,exist_ok=True)
    script=f'read_verilog "{scan}"; opt_clean -purge; write_verilog -noattr "{target}"'
    try: cp=subprocess.run(['yosys','-p',script],capture_output=True,text=True)
    except OSError as exc: return _write('12',output,'design_one_shot_runner Yosys command',reason=f'yosys unavailable: {exc}')
    if cp.returncode != 0 or not target.is_file(): return _write('12',output,'design_one_shot_runner Yosys command',reason='yosys producer failed',rc=cp.returncode,stderr=cp.stderr)
    return target
def produce_13(project,output,top=None,container=None,lec_max_completed_rungs=None,**k): return _cli('13',project,output,('design_one_shot_runner',))
def produce_dt2(project,output,top=None,clock=None,timeout=None,**k): return _cli('DT2',project,output,('path_delay_fault_atpg_run',))
def produce_dt3(project,output,top=None,clock=None,timeout=None,**k): return _cli('DT3',project,output,('sdd_atpg_run',))
def produce_p0(project,output,top=None,claim=None,**k):
    if not top or not claim: raise ValueError('P0: top and claim are required')
    import p0_tool_frontend_check as p0
    return _record('P0',project,output,'p0_tool_frontend_check.check+formal_structural_check.check_claim',p0.check,top=top,claim=claim,**k)

PRODUCERS={'D1':produce_d1,'0.5ic':produce_05ic,'1':produce_1,'2':produce_2,'3':produce_3,'4':produce_4,'5':produce_5,'6':produce_6,'7':produce_7,'8':produce_8,'10':produce_10,'11':produce_11,'FS1':produce_fs1,'DT1':produce_dt1,'12':produce_12,'13':produce_13,'DT2':produce_dt2,'DT3':produce_dt3,'P0':produce_p0}
REQUIRED_PARAMETERS={'D1':(), '0.5ic':(), '1':('ic_class',), '2':('top','clock','timeout','baseline_rtl_dir','candidate_rtl_dir'), '3':('top',), '4':('top','container'), '5':('top','container'), '6':('top','container'), '7':('top','pdk','container'), '8':(), '10':('top','pdk','container'), '11':('top','clock','pdk'), 'FS1':('asil',), 'DT1':('top','clock','timeout'), '12':(), '13':('top','container','lec_max_completed_rungs'), 'DT2':('top','clock','timeout'), 'DT3':('top','clock','timeout'), 'P0':('top','claim')}
def run_row(step_id,project,output,authority_path=None,**kwargs):
    if step_id not in PRODUCERS: raise ValueError(f'unknown frontend row: {step_id}')
    if isinstance(kwargs.get('template'), os.PathLike):
        kwargs = dict(kwargs)
        kwargs['template'] = os.fspath(kwargs['template'])
    manifest = (_issued_manifest_path(project, authority_path) if _strict_issuance()
                else Path(project)/'input'/'issued_manifest.json')
    if not manifest.is_file():
        manifest = issued_manifest_path(project)
    if manifest.is_file():
        try:
            bound=json.loads(manifest.read_text()).get('parameters') or {}
        except (OSError,ValueError) as exc: raise ValueError(f'{step_id}: issued manifest invalid') from exc
        if any(key in kwargs and kwargs[key] != value for key, value in bound.items()
               if key in kwargs):
            raise ValueError(f'{step_id}: caller parameters disagree with issued manifest')
        merged=dict(bound); merged.update(kwargs); kwargs=merged
    missing=[key for key in REQUIRED_PARAMETERS[step_id] if kwargs.get(key) in (None,'')]
    if step_id == '0.5ic':
        template = kwargs.get('template')
        reason = kwargs.get('no_template_reason')
        if isinstance(template, os.PathLike):
            template = os.fspath(template)
            kwargs['template'] = template
        has_template = isinstance(template, str) and bool(template.strip())
        has_reason = isinstance(reason, str) and bool(reason.strip())
        if not has_template:
            missing=['searched_template_path']
        elif reason is not None and not has_reason:
            missing=['no_template_reason']
        elif kwargs.get('slot') not in (None, '') and has_reason:
            raise ValueError('0.5ic: declared absence cannot name a shuttle slot')
    if missing: raise ValueError(f'{step_id}: missing parameters: {", ".join(missing)}')
    if step_id == '8':
        if not _strict_issuance():
            raise ValueError('8: CORE_CONTEXT_UNBOUND')
        token = _STEP8_DISPATCH.set(True)
        authority_token = _MANIFEST_AUTHORITY.set(manifest)
        try:
            return PRODUCERS[step_id](project,output,**kwargs)
        finally:
            _MANIFEST_AUTHORITY.reset(authority_token)
            _STEP8_DISPATCH.reset(token)
    return PRODUCERS[step_id](project,output,**kwargs)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--step',required=True); ap.add_argument('--inputs',required=True); ap.add_argument('--outputs',required=True); ap.add_argument('--manifest',default=None); a=ap.parse_args(); run_row(a.step,a.inputs,a.outputs,a.manifest)
if __name__=='__main__': main()
