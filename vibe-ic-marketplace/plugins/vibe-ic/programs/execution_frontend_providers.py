"""Source-only provider family for the canonical frontend rows.

Factories describe callable producers and contracts; they do not qualify an
EDA run. Missing inputs/tools therefore return typed NOT_IMPLEMENTED or
NOT_MEASURED and never fabricate an output or PASS.
"""

# `programs/` is a flat directory whose modules import each other by bare name
# (vibe-ic#2104): restore the condition a by-path load does not provide.
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from dataclasses import dataclass
from pathlib import Path
import ast
import hashlib, json, shlex, shutil, subprocess, sys, tempfile
import fnmatch
from typing import Callable

ROWS = ('D1','0.5ic','1','2','3','4','5','6','7','8','10','11','FS1','DT1','12','13','DT2','DT3','P0')
ROUTES = {'D1':('design_one_shot_runner.step_phase1',),'0.5ic':('submission_template_ingest.main','tapeout_declaration_gen.main'),'1':('design_one_shot_runner.step_rtl_gen',),'2':('p0_tool_frontend_check.check','crosslayer_rewrite_equivalence.main'),'3':('_cdc_netlist.build','cdc_crossing_check.main','cdc_async_input_check.main','clock_domain_reg_crossing_check.main','reset_dependency_check.main'),'4':('design_one_shot_runner.step_professional_tb_gen','design_one_shot_runner.step_reference_tb','design_one_shot_runner.step_l10_unit_tb_run','verilator_coverage_measure.main'),'5':('formal_harness_gen.generate','formal_property_run.run','design_one_shot_runner.step_full_stack_functional_tb'),'6':('design_one_shot_runner.step_fpga_compile','quartus_map_audit.main'),'7':('_ppa.timing.emit_step7_asic_sdc','phase3_one_shot_runner.stamp_pvt_corner_coverage'),'8':('sdc_syntax_check.main','sdc_validator_check.main'),'10':('phase3_one_shot_runner.step_prelayout_signoff',),'11':('fault_scan_chain_insert.main','fault_atpg_run.main','bsdl_emit.main'),'FS1':('fmeda_fault_injection_coverage.main','fmeda_coverage_check.main'),'DT1':('transition_fault_atpg_run.main',),'12':('execution_frontend_worker.produce',),'13':('design_one_shot_runner.step_lec_equivalence',),'DT2':('path_delay_fault_atpg_run.main',),'DT3':('sdd_atpg_run.main',),'P0':('p0_tool_frontend_check.check','formal_structural_check.check_claim')}
_DATA_DIR = Path(__file__).resolve().parent / 'data'
_FLOW_PATH = Path(__file__).resolve().parent.parent / 'flow' / 'phase1_phase2_phase3.yaml'
_COVERAGE_PATH = _DATA_DIR / 'execution_frontend_coverage.json'
_CATALOG_PATH = _DATA_DIR / 'execution_frontend_catalog.json'
_PORTFOLIO_PATH = _DATA_DIR / 'execution_modes_portfolio.json'


def _contracts():
    import _flow_yaml
    rows={str(s['id']): dict(s)
          for s in _flow_yaml.load().get('steps',())}
    missing=[r for r in ROWS if r not in rows]
    if missing:
        raise ValueError(f'canonical flow contract missing: {missing}')
    return {r:rows[r] for r in ROWS}


FLOW_CONTRACTS = _contracts()
CANONICAL_ROWS = {r: tuple(FLOW_CONTRACTS[r].get('required_outputs') or ()) for r in ROWS}
INPUT_CONTRACTS = {r: tuple(FLOW_CONTRACTS[r].get('required_inputs') or ()) for r in ROWS}
ENGINES = {r: ('source-bound',) for r in ROWS}; ENGINES.update({'2':('yosys','verilator'),'4':('iverilog','verilator'),'5':('yosys','sby'),'6':('quartus',),'11':('fault','yosys'),'DT1':('yosys',),'DT2':('yosys','openroad'),'DT3':('yosys','openroad')})
APPLICABILITY = {r:'IC+IP' for r in ROWS}; APPLICABILITY['0.5ic']='IC+IP route authority'; APPLICABILITY['6']='IC only; FPGA evidence optional'
DOWNSTREAM = {r: f'consumer:{";".join(outs)}' for r,outs in CANONICAL_ROWS.items()}


def _machine_contracts():
    """Consume the checked-in catalog and coverage declarations as inputs."""
    try:
        catalog = json.loads(_CATALOG_PATH.read_text())
        coverage_doc = json.loads(_COVERAGE_PATH.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('frontend machine-readable contract unavailable') from exc
    expected_contracts = {r: {'inputs': list(INPUT_CONTRACTS[r]),
                              'outputs': list(CANONICAL_ROWS[r])} for r in ROWS}
    if (catalog.get('schema') != 'execution_frontend_catalog/1' or
            tuple(catalog.get('rows') or ()) != ROWS or
            {str(k): tuple(v) for k, v in (catalog.get('routes') or {}).items()} != ROUTES or
            catalog.get('contracts') != expected_contracts):
        raise ValueError('frontend catalog is out of sync with source routes')
    if (coverage_doc.get('schema') != 'execution_frontend_coverage/1' or
            tuple(coverage_doc.get('rows') or ()) != ROWS or
            coverage_doc.get('contracts') != expected_contracts):
        raise ValueError('frontend coverage is out of sync with source rows')
    return catalog, coverage_doc


def _portfolio_contracts():
    data = json.loads(_PORTFOLIO_PATH.read_text())
    return {str(row['id']): row for row in data.get('steps', ())}

@dataclass(frozen=True)
class ProviderResult:
    step_id: str; state: str; reason: str; outputs: tuple[str,...]=()

@dataclass(frozen=True)
class FrontendProvider:
    step_id: str; factory: Callable; inputs: tuple[object,...]; outputs: tuple[str,...]
    downstream: str; applicability: str; engines: tuple[str,...]; default_rank: int

CALLABLES = {r: ROUTES[r][0] for r in ROWS}

def _produce(step_id, project, **kwargs):
    """Dispatch through the explicit worker entry point for this row."""
    project = Path(project)
    if not project.exists():
        return ProviderResult(step_id, 'NOT_IMPLEMENTED', f'missing input: {project}')
    if step_id not in CALLABLES: return ProviderResult(step_id, 'NOT_IMPLEMENTED', 'unknown frontend row')
    from execution_frontend_worker import run_row
    out = project / 'frontend_outputs' / step_id.replace('.', '_')
    artifact = run_row(step_id, project, out, **kwargs)
    if step_id == '0.5ic':
        return ProviderResult(step_id, 'NOT_MEASURED',
                              'real 0.5ic producers executed; canonical gates remain consumer-owned',
                              (str(Path(artifact).relative_to(out)),))
    if not Path(artifact).is_file() or Path(artifact).name == 'canonical.json':
        return ProviderResult(step_id, 'NOT_MEASURED', 'real producer did not emit a canonical flow artifact', ())
    try: rel=Path(artifact).relative_to(project)
    except ValueError: rel=Path(artifact).relative_to(out)
    return ProviderResult(step_id, 'NOT_MEASURED', 'real producer executed; canonical gate remains unmeasured', (str(rel),))

def _tree_sha(path):
    h=hashlib.sha256()
    paths=sorted(path.rglob('*')) if path.is_dir() else [path]
    for p in paths:
        if p.is_file() and not p.is_symlink(): h.update(str(p).encode()+b'\0'+hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()

def _factory(step_id):
    return lambda project, **kwargs: _produce(step_id, project, **kwargs)


def _source_closure(seeds):
    """Bind local Python imports reachable from the public frontend sources."""
    root=Path(__file__).resolve().parent
    todo=[Path(seed).resolve() for seed in seeds]
    try:
        from execution_source_snapshot import active
        snapshot=active()
    except ImportError:
        snapshot=None
    cache_key=('frontend-source-closure',tuple(sorted(map(str,todo))))
    if snapshot is not None:
        cached=snapshot.closure_get(cache_key)
        if cached is not None:
            for path in cached: snapshot.read_bytes(path)
            return tuple(sorted(cached))
    seen={}
    while todo:
        path=todo.pop()
        if path in seen or not path.is_file() or path.is_symlink():
            continue
        seen[path]=None
        from execution_source_snapshot import python_import_syntax
        try: imports=python_import_syntax(snapshot.read_text(path) if snapshot is not None else path.read_text())
        except (OSError, SyntaxError):
            continue
        for kind, _level, module, aliases, _optional in imports:
            names = aliases if kind == 'import' else (module,) if kind == 'from' and module else ()
            for name in names:
                candidate=root / (name.replace('.', '/') + '.py')
                if candidate.is_file():
                    todo.append(candidate)
    if snapshot is not None:
        for path in seen: snapshot.read_bytes(path)
        snapshot.closure_put(cache_key,seen)
    return tuple(sorted(seen))


def _gate_commands(node):
    if isinstance(node, str):
        return []
    if isinstance(node, dict):
        result=[]
        for key, value in node.items():
            if key == 'program_exit_zero' and isinstance(value, str):
                result.append(value)
            else:
                result.extend(_gate_commands(value))
        return result
    if isinstance(node, list):
        result=[]
        for value in node:
            result.extend(_gate_commands(value))
        return result
    return []


def _gate_reports(contract):
    result={}
    for command in _gate_commands(contract.get('gate', {})):
        try: tokens=shlex.split(command)
        except ValueError: continue
        if not tokens or '--json' not in tokens:
            continue
        index=tokens.index('--json')
        if index + 1 < len(tokens):
            result[Path(tokens[0]).name]=tokens[index + 1]
    return result


def _concrete_outputs(root, required):
    found={}
    for spec in required:
        for alternative in (part.strip() for part in str(spec).split(' OR ')):
            if any(ch in alternative for ch in '*?['):
                paths=root.glob(alternative)
            else:
                paths=(root / alternative,)
            for path in paths:
                if path.is_file() and not path.is_symlink():
                    found[str(path.relative_to(root))]=str(spec)
    return found


def _gate_verdict(program, path):
    try:
        doc=json.loads(path.read_text())
        if program == 'submission_template_check':
            verdict=doc['check']['verdict']
            if verdict == 'NOT_APPLICABLE':
                return verdict
        else:
            verdict=doc['verdict']
        if verdict not in ('PASS','FAIL'):
            return 'NOT_MEASURED'
        return verdict
    except (OSError, ValueError, TypeError, KeyError):
        return 'NOT_MEASURED'


def _run_gate(program, root, source_dir):
    """Run one declared gate into a private report, preserving its typed result."""
    script=source_dir / (program + '.py')
    if not script.is_file():
        return 'NOT_MEASURED'
    with tempfile.TemporaryDirectory(prefix='frontend-gate-') as tmp:
        report=Path(tmp) / (program + '.json')
        try:
            cp=subprocess.run([sys.executable, str(script), str(root), '--json', str(report)],
                              capture_output=True, text=True)
        except OSError:
            return 'NOT_MEASURED'
        verdict=_gate_verdict(program, report) if report.is_file() else 'NOT_MEASURED'
        if cp.returncode == 0 and (verdict == 'PASS' or (
                program == 'submission_template_check' and verdict == 'NOT_APPLICABLE')):
            return verdict
        if cp.returncode != 0 and verdict == 'FAIL':
            return 'FAIL'
        return 'NOT_MEASURED'

PROVIDERS = {r: FrontendProvider(r, _factory(r), INPUT_CONTRACTS[r], CANONICAL_ROWS[r], DOWNSTREAM[r], APPLICABILITY[r], ENGINES[r], i) for i,r in enumerate(ROWS)}

def coverage():
    _machine_contracts()
    return {r:{'step_id':p.step_id,'producer':ROUTES[r],
               'parameter_source':'issued manifest + Controller substitutions',
               'canonical_input':p.inputs, 'input_contract':p.inputs,
               'canonical_output':p.outputs, 'output_contract':p.outputs,
               'gates':FLOW_CONTRACTS[r].get('gate',{}),
               'availability':'source callable bound; runtime capability checked at execution',
               'downstream':p.downstream,'applicability':p.applicability,
               'engine_family':p.engines,'default_rank':p.default_rank}
            for r,p in PROVIDERS.items()}

def choose(step_id):
    if step_id not in PROVIDERS: return None
    return PROVIDERS[step_id]

def register_factories(registry, *, step_ids=None, project=None, parameters=None):
    """Register real source adapters in the existing Registry."""
    if not hasattr(registry, 'register'): raise TypeError('registry must provide register')
    import execution_modes as em
    from execution_modes import Adapter, Component, Evidence, digest
    from execution_provider_catalog import source_closure, implementation_closure
    source_path=Path(__file__).resolve(); worker_path=source_path.with_name('execution_frontend_worker.py')
    source=str(source_path); worker=str(worker_path)
    py_path=Path(shutil.which('python3') or sys.executable).resolve(); py=str(py_path)
    repo=next(p for p in source_path.parents if (p/'.git').exists())
    sha=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    _machine_contracts()
    portfolio_rows=_portfolio_contracts()
    if not set(ROWS).issubset(portfolio_rows):
        raise ValueError('frontend portfolio rows are out of sync with source rows')
    selected = set(ROWS if step_ids is None else map(str,step_ids))
    if not selected.issubset(ROWS):
        raise ValueError('unknown frontend fixed step')
    for row,p in PROVIDERS.items():
        if row not in selected:
            continue
        contract=FLOW_CONTRACTS[row]
        portfolio_row=portfolio_rows[row]
        yaml_outputs=tuple(contract.get('required_outputs') or ())
        portfolio_outputs=tuple(portfolio_row.get('required_output_contract') or ())
        if portfolio_outputs != yaml_outputs:
            raise ValueError(f'frontend output contract parity mismatch: {row}')
        yaml_gates=tuple(_gate_reports(contract))
        portfolio_gates=tuple(portfolio_row.get('mandatory_gate_programs') or ())
        if row == '0.5ic' and portfolio_gates != yaml_gates:
            raise ValueError(f'frontend gate contract parity mismatch: {row}')
        def validate(project, facts, _row=row, _gate_names=portfolio_gates):
            import _flow_yaml, flow_compliance_check
            contract=next(s for s in _flow_yaml.load()['steps'] if str(s['id']) == _row)
            root=Path(project)
            required=tuple(contract.get('required_outputs') or ())
            concrete=_concrete_outputs(root, required)
            artifacts={rel:digest(root/rel) for rel in concrete}
            if _row == 'D1':
                # This worker reaches the real Phase-1 expert handoff, but its
                # canonical outputs/gates are not connected to adoption yet.
                # Never apply Step 8's SDC reports to these 32 D1 obligations.
                canonical = root / 'canonical.json'
                record = None
                if canonical.is_file() and not canonical.is_symlink():
                    artifacts = {'canonical.json': digest(canonical)}
                    try:
                        record = json.loads(canonical.read_text())
                    except (OSError, ValueError, TypeError):
                        pass
                else:
                    artifacts = {}
                producer = record.get('producer_result') if isinstance(record, dict) else None
                typed = (isinstance(record, dict) and
                         record.get('schema') == 'frontend_worker_output/1' and
                         record.get('step_id') == 'D1' and
                         record.get('producer') == 'phase1_one_shot_runner._run_docs_mode+run_phase1_second_track' and
                         record.get('result') == 'NOT_MEASURED' and
                         isinstance(producer, dict) and
                         producer.get('name') == 'phase1' and
                         producer.get('status') in ('PASS', 'FAIL', 'NOT_MEASURED',
                                                    'NOT_APPLICABLE', 'INCOMPLETE') and
                         type(producer.get('duration_s')) in (int, float) and
                         isinstance(producer.get('detail'), str) and
                         isinstance(producer.get('extras'), dict) and
                         isinstance(producer.get('reason_class'), str))
                verdict = 'FAIL' if typed and producer['status'] == 'FAIL' else 'NOT_MEASURED'
                return Evidence(facts, verdict,
                                {name: 'NOT_MEASURED' for name in _gate_names}, artifacts,
                                detail=('D1_CANONICAL_HANDOFF_NOT_CONNECTED' if typed else
                                        'D1_CANONICAL_RECORD_MISSING_OR_INVALID'))
            if _row == '0.5ic':
                try:
                    before_chain = em.consume_frontend_chain(root, facts)
                except (em.Refusal, OSError, ValueError, KeyError, TypeError):
                    before_chain = None
                try:
                    gate_result=flow_compliance_check.check_step(
                        root, contract, {}, strict_step_binding=True)
                    step_status=str(getattr(gate_result, 'status', gate_result))
                except Exception:
                    step_status='NOT_MEASURED'
                report_paths=_gate_reports(contract)
                gates={}
                names=tuple(contract.get('mandatory_gate_programs') or report_paths)
                for name in names:
                    gates[name]=_run_gate(name, root, Path(__file__).resolve().parent)
                # Keep measured gate FAIL above a missing/changed snapshot.
                # Reconsume the same signed producer chain around the gates.
                chain = None
                try:
                    chain = em.consume_frontend_chain(root, facts)
                    if chain != before_chain:
                        chain = None
                except (em.Refusal, OSError, ValueError, KeyError, TypeError):
                    pass
                if step_status == 'FAIL' or any(value == 'FAIL' for value in gates.values()):
                    verdict='FAIL'
                elif (step_status == 'PASS' and gates and
                      chain is not None and
                      all(em.required_gate_satisfied(_row, name, value)
                          for name, value in gates.items()) and
                      all(any(fnmatch.fnmatch(rel, alt.strip())
                              for rel in artifacts
                              for alt in str(spec).split(' OR '))
                          for spec in required)):
                    verdict='PASS'
                else:
                    verdict='NOT_MEASURED'
                return Evidence(facts, verdict, gates, artifacts,
                                detail='real producers, canonical YAML outputs, mandatory gates and issued snapshots validated',
                                metrics={'source_boundary': 1.0},
                                provenance={'producer_chain': chain} if chain is not None else {})
            if _row == '7':
                # Step 7's producer is the canonical ASIC SDC/PVT emitter.  Its
                # mandatory consumers (stage compliance, syntax, PVT and
                # integration checks) are not generic Step-8 validator rows;
                # the normal Phase-2 runner executes this producer directly
                # when a source-bound frontend arm is only NOT_MEASURED.
                # Keep the Controller evidence explicitly unmeasured rather
                # than reading Step-8 reports and accidentally qualifying a
                # different step.
                return Evidence(
                    facts, 'NOT_MEASURED',
                    {name: 'NOT_MEASURED' for name in _gate_names},
                    artifacts,
                    detail='Step-7 producer emitted source-bound artifacts; '
                           'canonical consumer qualification remains unmeasured')
            gate_result=flow_compliance_check.check_step(root, contract, {}, strict_step_binding=True)
            gate = getattr(gate_result, 'status', gate_result)
            # The canonical checker returns a typed StepResult whose overall
            # status also includes optional downstream clauses.  Step 8's
            # mandatory program gate is the two independent producer reports.
            syntax_ok = False; validator_ok = False
            try:
                syntax_doc=json.loads((root/'reports/phase2/sdc_check.json').read_text())
                syntax_ok = type(syntax_doc.get('passed')) is bool and syntax_doc.get('passed') is True and syntax_doc.get('program') == 'sdc_syntax_check'
                vp = root/'reports/sdc_validator.json'
                validator_doc=json.loads(vp.read_text())
                validator_ok = (validator_doc.get('verdict') == 'PASS' and type(validator_doc.get('exit_code')) is int and validator_doc.get('exit_code') == 0 and isinstance(validator_doc.get('issues'), list))
            except (OSError, ValueError, TypeError):
                syntax_ok = False
            reasons = getattr(gate_result, 'reasons', ()) or ()
            measured_gate_fail = any('sdc_syntax_check' in str(r) and ('FAIL' in str(r) or 'rc=' in str(r)) for r in reasons)
            gate = 'PASS' if syntax_ok and validator_ok and not measured_gate_fail else 'FAIL'
            def gate_names(node):
                if isinstance(node,str): return [node.split()[0]] if node else []
                if isinstance(node,dict): return sum((gate_names(v) for v in node.values()),[])
                if isinstance(node,list): return sum((gate_names(v) for v in node),[])
                return []
            names=_gate_names
            gates={n:('PASS' if str(gate) == 'PASS' else str(gate)) for n in names}
            verdict='PASS' if artifacts and gates and all(v=='PASS' for v in gates.values()) else 'NOT_MEASURED'
            return Evidence(facts, verdict, gates, artifacts, metrics={'source_boundary': 1.0}, detail='real canonical artifacts and canonical gate validated')
        required=portfolio_outputs
        # The canonical YAML and its machine-readable consumers are part of
        # the adapter identity. A changed contract must force re-registration.
        closure=(source_path, worker_path, _FLOW_PATH, _COVERAGE_PATH,
                 _CATALOG_PATH, _PORTFOLIO_PATH)
        if row == '0.5ic':
            seeds=[source_path, worker_path]
            seeds.extend(source_path.with_name(name) for name in (
                'submission_template_ingest.py','tapeout_declaration_gen.py',
                '_flow_yaml.py','flow_compliance_check.py',
                'submission_template_check.py','tapeout_declaration_check.py'))
            closure=_source_closure(seeds)
            closure += (_FLOW_PATH, _COVERAGE_PATH, _CATALOG_PATH, _PORTFOLIO_PATH)
        if row == '8':
            closure += tuple(source_path.with_name(name) for name in ('sdc_syntax_check.py','sdc_validator_check.py','sdc_exception_correlation_check.py','derived_clock_sdc_required_check.py'))
        closure = tuple(set(closure) | set(em._source_closure(closure)) |
                        source_closure(closure) | implementation_closure(worker_path))
        bound_files={str(path):digest(path) for path in closure if path.is_file()}
        bound_files[py]=digest(py_path)
        tracked_paths = [name for name in bound_files if Path(name).is_relative_to(repo)]
        if subprocess.run(['git','-C',str(repo),'diff','--quiet','HEAD','--',*tracked_paths],
                          capture_output=True).returncode != 0:
            raise ValueError('frontend provider source is dirty; refusing registration')
        objective={'parameters_from':'issued_manifest'}
        # 0.5ic runs two sequential producers plus their source-bound snapshots
        # and receipts. Give that composite a bounded execution budget; each
        # independent quality gate keeps the normal component deadline.
        worker_budget = {'timeout_s': 120} if row == '0.5ic' else {}
        components = [Component('frontend_worker', ('python3',worker,'--step',row,'--inputs','{inputs}','--outputs','{outputs}',
                       *(('--manifest','{inputs}/issued_manifest.json') if row == '8' else ())), **worker_budget)]
        if row in ('0.5ic', '8'):
            def commands(node):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in ('program_exit_zero', 'optional_program_exit_zero', 'advisory_program_exit_zero'):
                            yield value if isinstance(value, str) else value['command']
                        else:
                            yield from commands(value)
                elif isinstance(node, list):
                    for value in node: yield from commands(value)
            declared = {shlex.split(command)[0]: shlex.split(command) for command in commands(contract.get('gate', {}))}
            for gate in portfolio_gates:
                parts = list(declared[gate])
                if row == '0.5ic':
                    # The producer chain binds its reports through adoption.
                    # These gates read them; their own receipts have a separate
                    # destination so validation cannot overwrite signed bytes.
                    parts[parts.index('--json') + 1] = (
                        'reports/execution_gates/' + gate + '.json')
                argv = ('python3',str(source_path.with_name(gate+'.py')),
                        *('{outputs}' if value == '.' else value for value in parts[1:]))
                components.append(Component(gate, argv))
        # Issued D1 workers inherit the Controller VM (~569 MiB measured)
        # before Phase-1 parsing (~202 MiB in a clean process). Reserve bounded
        # headroom for both; other adapters retain their existing defaults.
        resources = {'ram_mb': 1024} if row == 'D1' else {}
        registry.register(Adapter('frontend_'+row.replace('.','_'),'frontend-worker',row,sha,bound_files,'current-main',p.engines,tuple(components),validate,required,objective,qualification_evidence='route callable bound; native qualification not measured',output_contract={path:(path,) for path in required},input_contract=INPUT_CONTRACTS[row] + (('phase2/stage1/rtl', 'reports/phase2/cdc/crossing.json') if row == '8' else ()), **resources))
    if step_ids is None:
        from execution_production import register_synthesis_adapter
        register_synthesis_adapter(registry, project=project, parameters=parameters,
                                   deferred=True)
    return tuple(PROVIDERS)

def dedupe_by_engine():
    result={}
    for p in PROVIDERS.values(): result.setdefault(p.engines, []).append(p.step_id)
    return {k:tuple(v) for k,v in result.items()}

def produce(step_id, project, **kwargs):
    provider=choose(step_id)
    if provider is None: return ProviderResult(str(step_id),'NOT_IMPLEMENTED','unknown frontend row')
    if not isinstance(project, (str,Path)): return ProviderResult(step_id,'NOT_IMPLEMENTED','project input is absent')
    return provider.factory(Path(project), **kwargs)
