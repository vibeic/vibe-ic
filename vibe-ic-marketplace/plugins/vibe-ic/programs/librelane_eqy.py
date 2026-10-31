#!/usr/bin/env python3
"""Step 13 arm B: LibreLane Yosys.EQY beside lec_run (arm A).

lec_run (yosys equiv_*) stays arm A. This module runs EQY through the contract
with a vibe-ic-generated EQY_SCRIPT and judges EQY's own per-partition status
files, then `combine` keeps the conclusive arm.

The generated script differs from LibreLane's generic one in these measured ways:

* No `bitwuzla` strategy — the solver is not in the image (review correction).
* The gate side reads the cells from the PDK liberty's `function` attributes
  (`read_liberty`), not from LibreLane's `formal_pdk.v`: for a PDK other than
  sky130A that file is the PDK's Verilog models run through `iverilog -E`, and
  gf180mcu's models are UDP-based, which Yosys cannot parse (measured: syntax
  error at the first UDP instance). EQY_FORCE_ACCEPT_PDK is still required, or
  the step skips itself.
* `read_verilog -icells`, so a netlist that still carries Yosys internal cells
  (`$_DFF_P_`) reads.
* Amend each partition with the gold definitions of its matched inputs. A
  synthesis-merged alias must retain the state relation of the original
  registers: treating the other alias as an arbitrary partition input can
  produce a counterexample at time zero even for two identical resettable
  registers. Amendment retains every match point and output obligation; it
  adds the producer logic behind cutpoints rather than dropping comparisons.
* Collect all matched points into one fragment before partitioning.  This does
  not remove an output or match obligation; it prevents EQY from materializing
  one nearly-whole-design copy per internal match point on mapped netlists.
* Do not name-match Yosys's ``_NNNN_`` temporaries.  Their counters are local
  to each independently elaborated view and do not identify the same Boolean
  function.  Public ports and stable authored/state names still use EQY's
  default same-name matching, and the complete logic behind every output is
  retained in the proof model.

EQY's top-level status folds "could not decide" into FAIL. The reader therefore
reads every partition's strategy status files: a partition is PROVEN when a
strategy says PASS, NOT_EQUIVALENT when a strategy says FAIL, and otherwise
UNKNOWN. UNKNOWN is INCONCLUSIVE, never PASS and never a counterexample.

EQY's miter treats an `x` on the gold side as don't-care, so a compared point
that is x on the gold side (a register with no reset and no init) is vacuous.
For that reason EQY is never the sole evidence: `combine` requires arm A not to
have found a counterexample, and arms that disagree stop the step.

chip-AGNOSTIC: no design, PDK or cell literal selects a branch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402
from librelane_contract import (Refusal, _load, digest,  # noqa: E402
                                resolve_step_config, run_chain)
import instrument_calibration  # noqa: E402
from lec_observable_cone import observable_matchpoint_names  # noqa: E402

STEP = "Yosys.EQY"
#: EQY's own status words (eqy_job.py `possible_statuses`).
_EQY_STATUSES = ("PASS", "FAIL", "UNKNOWN", "ERROR", "TIMEOUT")


def eqy_script(top: str, rtl: list[Path], netlist: Path, liberty: str) -> str:
    gold = " ".join(str(p) for p in rtl)
    return "\n".join([
        "[gold]", f"read_verilog -formal -sv {gold}", "",
        "[gate]", f"read_liberty -ignore_miss_func {liberty}",
        f"read_verilog -formal -sv -icells {netlist}", "",
        "[script]", f"hierarchy -top {top}", "proc", f"prep -top {top} -flatten",
        "memory -nomap", "async2sync", "setundef -init -zero", "splitnets",
        observable_matchpoint_names(top).rstrip(), "",
        "[match *]", "gold-nomatch /^_[0-9]+_$/",
        "gate-nomatch /^_[0-9]+_$/", "",
        "[collect *]", "group *", "",
        "[partition *]", "amend *", "",
        "[strategy sat]", "use sat", "depth 5", "",
        "[strategy pdr]", "use sby", "engine abc pdr -rfi", ""])


def partition_status(scratch: Path) -> Optional[dict[str, dict[str, str]]]:
    """{partition: {strategy: status}} from EQY's status files; None if absent."""
    instrument_calibration.assert_calibrated("librelane_eqy::partition_status")
    root = scratch / "strategies"
    if not root.is_dir():
        return None
    found: dict[str, dict[str, str]] = {}
    for status in sorted(root.glob("*/*/status")):
        words = status.read_text(errors="replace").split()
        word = words[0] if words else ""
        found.setdefault(status.parent.parent.name, {})[status.parent.name] = (
            word if word in _EQY_STATUSES else "UNREADABLE")
    return found


def xbit_partitions(scratch: Path) -> Optional[list[str]]:
    """Partitions EQY tags `xbits` in partition.list; None if it was not written.

    Such a partition compares signals that are x on the gold side, and EQY's
    miter treats gold x as don't-care — its PASS says nothing (measured: a buf
    in place of an inv behind a resetless flop is `DONE (PASS)`).
    """
    instrument_calibration.assert_calibrated("librelane_eqy::xbit_partitions")
    listing = scratch / "partition.list"
    if not listing.is_file():
        return None
    found = []
    for line in listing.read_text(errors="replace").splitlines():
        head, _, _ = line.partition(":")
        words = head.split()
        if len(words) >= 2 and "xbits" in words[2:]:
            found.append(words[1])
    return found


def judge_eqy(folder: Path, output: Path) -> dict:
    scratch = folder / "scratch"
    parts = partition_status(scratch)
    xbits = xbit_partitions(scratch) or []
    listing = scratch / "partition.list"
    lines = listing.read_text(errors="replace").splitlines() if listing.is_file() else []
    heads = [line.partition(":")[0].split() for line in lines if line.strip()]
    declared = [head[1] for head in heads if len(head) >= 2]
    complete = (bool(declared) and len(declared) == len(heads)
                and len(declared) == len(set(declared)) and set(declared) == set(parts or {}))
    proven, failed, unknown = [], [], []
    for name, strategies in (parts or {}).items():
        words = set(strategies.values())
        if "FAIL" in words:
            failed.append(name)
        elif "PASS" in words:
            proven.append(name)
        else:
            unknown.append(name)
    if not parts:
        verdict, why = "NOT_MEASURED", "EQY wrote no partition status (read/partition stage failed)"
    elif failed:
        verdict, why = "FAIL", f"{len(failed)} partition(s) not equivalent: {', '.join(failed[:5])}"
    elif not complete:
        verdict, why = "NOT_MEASURED", "EQY partition declaration/status population is missing or incomplete"
    elif unknown:
        verdict, why = "INCONCLUSIVE", f"{len(unknown)} partition(s) undecided: {', '.join(unknown[:5])}"
    elif xbits:
        verdict, why = "INCONCLUSIVE", (f"EQY_XBITS_VACUOUS: {len(xbits)} partition(s) compare "
                                        f"gold x as don't-care: {', '.join(xbits[:5])}")
    else:
        verdict, why = "PASS", f"all {len(proven)} partition(s) proven"
    report = {"program": "librelane_eqy", "engine": "eqy (LibreLane Yosys.EQY)",
              "verdict": verdict, "explanation": why,
              "compared_points": len(parts or {}), "proven_points": len(proven),
              "non_equivalent_points": failed, "unproven_points": unknown,
              "xbits_partitions": xbits, "partitions": parts, "source": str(folder)}
    if (folder / "config.json").is_file():
        report["config_sha256"] = digest(folder / "config.json")
    write_json(output, report)
    return report


def run_eqy(project: Path, image: str, pdk: str, top: str, rtl: list[Path],
            netlist: Path, *, mounts: Optional[list[tuple[Path, str]]] = None,
            pdk_root: str, std_cell_library: Optional[str] = None,
            namespace: str = "lec_eqy") -> Path:
    """Resolve the PDK config, write EQY_SCRIPT, run Yosys.EQY; return its folder.

    A failing EQY job exits nonzero, which the contract reports as a step
    failure; the folder is still judged, because a counterexample IS the answer.
    """
    if (project / 'input/flow109/D25.json').is_file():
        return d25_run(project, top, rtl, netlist)
    if not netlist.is_file() or not rtl or any(not p.is_file() for p in rtl):
        raise Refusal("LL_EQY_INPUT_MISSING", f"{netlist} / {rtl}")
    root = project / "phase3/librelane/lec-eqy-config"
    root.mkdir(parents=True, exist_ok=True)
    config: dict[str, Any] = {"DESIGN_NAME": top, "PDK": pdk,
                              "VERILOG_FILES": [str(p.resolve()) for p in rtl],
                              "EQY_FORCE_ACCEPT_PDK": True, "meta": {"step": STEP}}
    if std_cell_library:
        config["STD_CELL_LIBRARY"] = std_cell_library
    raw = root / "eqy.json"
    write_json(raw, config)
    probe = resolve_step_config(project, image, raw, root / "eqy.probe.json",
                                mounts=mounts, pdk_root=pdk_root)
    resolved = _load(probe)
    libs = resolved.get("CELL_LIBS") or resolved.get("LIB") or {}
    corner = resolved.get("DEFAULT_CORNER") or ""
    import fnmatch
    match = [lib for pattern, group in libs.items() if fnmatch.fnmatch(corner, pattern)
             for lib in (group if isinstance(group, list) else [group])]
    if len(match) != 1:
        raise Refusal("LL_EQY_LIBERTY_UNRESOLVED", f"{corner}: {match}")
    script = root / f"{top}.eqy"
    script.write_text(eqy_script(top, rtl, netlist.resolve(), str(match[0])))
    config["EQY_SCRIPT"] = str(script)
    write_json(raw, config)
    write_json(root / "eqy.provenance.json", {
        "VERILOG_FILES": "step 13 gold RTL (phase2/stage1/rtl)",
        "EQY_SCRIPT": "librelane_eqy.eqy_script (no bitwuzla; liberty cell functions)",
        "liberty": f"resolved CELL_LIBS for DEFAULT_CORNER {corner}",
        "EQY_FORCE_ACCEPT_PDK": "required for a PDK other than sky130A"})
    step_config = resolve_step_config(project, image, raw, root / "eqy.resolved.json",
                                      mounts=mounts, pdk_root=pdk_root)
    state = root / "state_in.json"
    write_json(state, {"nl": str(netlist.resolve())})
    folder = project / "phase3/librelane" / namespace / "01-yosys-eqy"
    try:
        run_chain(project, image, [(STEP, step_config, state)], mounts=mounts,
                  pdk_root=pdk_root, namespace=namespace)
    except Refusal as exc:
        if exc.code != "LL_STEP_FAILED" or not (folder / "scratch").is_dir():
            raise
    return folder


def combine(lec: dict, eqy: dict) -> dict:
    """Keep the conclusive arm. A counterexample in either arm is never outvoted."""
    a = str(lec.get("verdict") or "NOT_MEASURED").upper()
    b = str(eqy.get("verdict") or "NOT_MEASURED").upper()
    if {a, b} == {"PASS", "FAIL"}:
        return {"verdict": "FAIL", "reason": "LEC_ARMS_DISAGREE",
                "detail": f"lec_run={a}, eqy={b}: one arm proves, the other finds a "
                          "counterexample — stop and investigate", "arms": {"lec_run": a, "eqy": b}}
    if "FAIL" in (a, b):
        return {"verdict": "FAIL", "reason": "NOT_EQUIVALENT",
                "selected": "lec_run" if a == "FAIL" else "eqy", "arms": {"lec_run": a, "eqy": b}}
    if a == "PASS":
        return {"verdict": "PASS", "selected": "lec_run",
                "corroborated_by_eqy": b == "PASS", "arms": {"lec_run": a, "eqy": b}}
    if b == "PASS":
        # Arm A undecided (budget, SKIPPED-CONDITION, abort) and did not
        # disprove; EQY proved every partition.
        return {"verdict": "PASS", "selected": "eqy", "arms": {"lec_run": a, "eqy": b}}
    return {"verdict": "INCONCLUSIVE", "reason": "NO_CONCLUSIVE_ARM",
            "arms": {"lec_run": a, "eqy": b}}


def d25_sources() -> dict:
    import hashlib
    import inspect
    import flow109_metric_acceptance as metrics
    from librelane.steps.yosys import EQY
    return {'native/librelane/steps/yosys.py': digest(Path(inspect.getfile(EQY))),
            'programs/librelane_eqy.py': digest(Path(__file__)),
            **{name: hashlib.sha256(inspect.getsource(getattr(metrics, name)).encode()).hexdigest()
               for name in ('_d25_inputs', '_d25_accept_eqy', 'accept_d25')}}


def d25_run(project: Path, top: str, rtl: list[Path], netlist: Path) -> Path:
    """BLOCKING named native purpose; ordinary projects retain their existing path."""
    import os
    import re
    import shutil
    import subprocess
    import flow109
    import flow109_metric_acceptance as metrics
    from librelane_contract import local_image_attestation
    from librelane.config import Config
    from librelane.state import State, DesignFormat
    from librelane.common import Path as LLPath
    from librelane.steps.yosys import EQY
    from librelane.steps import StepError

    project = project.resolve()
    context = flow109.validate_execution_context(json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text()))
    owner_context = context
    if context.get('schema') == 'vibeic.flow109.execution-window.v1':
        context = flow109.component_context(context, requested_step='D25')
    if context['resolved_row']['id'] != 'D25':
        raise metrics.MetricRefusal('D25_CONTEXT_INVALID', 'not selected D25')
    attempt = flow109._bound_attempt(project, owner_context, os.environ.get(flow109.ATTEMPT_ENV))
    prepared = metrics._d25_inputs(project)
    manifest, mode = prepared['manifest'], prepared['mode']
    if (top != mode['top'] or [p.resolve() for p in rtl] != prepared['gold']
            or netlist.resolve() != prepared['gate']):
        raise metrics.MetricRefusal('D25_NATIVE_SUBJECT_UNBOUND', 'owner and approved inputs differ')
    if context.get('runtime_tool_uses') is not None or context.get('qualification_registry') is not None:
        from flow109_admission import require_admission
        require_admission(project, context)
    if (project / 'reports/lec_eqy_execution.json').is_file():
        retained = d25_reopen(project, prepared, context)
        return Path(retained['proof']['source'])
    try:
        launch = local_image_attestation()
    except Refusal as exc:
        raise metrics.MetricRefusal('D25_NATIVE_LAUNCH_UNBOUND', str(exc)) from exc
    directory = project / 'phase3/librelane/lec_eqy' / attempt.name
    directory.mkdir(parents=True, exist_ok=False)
    source_ids = d25_sources()
    readset = dict(prepared['consumed'])
    readset.update({str(Path(shutil.which(tool)).resolve()): digest(Path(shutil.which(tool)).resolve())
                    for tool in ('eqy', 'yosys', 'iverilog')})
    readset[launch['attestation_path']] = launch['attestation_sha256']
    readset[str(attempt / 'request.json')] = digest(attempt / 'request.json')

    def guard():
        if source_ids != d25_sources() or any(digest(Path(p)) != sha for p, sha in readset.items()):
            raise metrics.MetricRefusal('D25_NATIVE_INPUT_STALE', 'source/input changed during execution')

    def record(path):
        return {'path': str(path.relative_to(project)), 'sha256': digest(path)}

    cells, outputs, derivation = set(), None, {}
    for side, files in [('gold', prepared['gold']), ('gate', [prepared['gate']])]:
        folder = directory / side
        folder.mkdir()
        prefix = (f'read_liberty {prepared["liberty"]}\n' if side == 'gate' else '')
        prefix += 'read_verilog -formal -sv ' + ' '.join(map(str, files)) + '\n'
        census_script = folder / 'census.ys'
        census_script.write_text(prefix + f'hierarchy -check -top {top}\nproc\nwrite_json {folder}/census.json\n')
        guard()
        cp = subprocess.run(['yosys', '-Q', '-T', '-s', str(census_script)], capture_output=True, text=True)
        (folder / 'census.log').write_text(cp.stdout + cp.stderr)
        if cp.returncode:
            raise metrics.MetricRefusal('D25_MODEL_UNRESOLVED', side)
        modules = json.loads((folder / 'census.json').read_text())['modules']
        todo, seen = [top], set()
        while todo:
            name = todo.pop()
            if name in seen or name.startswith('$'):
                continue
            seen.add(name)
            module = modules.get(name)
            if module is None or any(str(module.get('attributes', {}).get(a, '0')).strip('0')
                                     for a in ('blackbox', 'whitebox')):
                raise metrics.MetricRefusal('D25_MODEL_UNRESOLVED', name)
            todo.extend(c['type'] for c in module.get('cells', {}).values())
        if side == 'gate':
            cells = seen - {top}
            if not cells or not cells <= set(prepared['qualification']['qualified_cell_types']):
                raise metrics.MetricRefusal('D25_MODEL_NOT_QUALIFIED', 'live library population differs')
        ports = modules[top]['ports']
        current_outputs = {name: list(range(len(port['bits']))) for name, port in ports.items()
                           if port['direction'] == 'output'}
        if current_outputs != mode['outputs'] or (outputs is not None and current_outputs != outputs):
            raise metrics.MetricRefusal('D25_PARTITION_CENSUS_UNBOUND', 'all original outputs required')
        outputs = current_outputs
        if (mode['clock']['port'] not in ports or mode['reset']['port'] not in ports
                or any(ports[mode[r]['port']]['direction'] != 'input'
                       or len(ports[mode[r]['port']]['bits']) != 1 for r in ('clock', 'reset'))):
            raise metrics.MetricRefusal('D25_MODE_INVALID', 'clock/reset input mapping')
        reset = mode['reset']
        if set(reset['next_outputs']) != set(outputs) or any(
                len(value) != len(outputs[name]) or set(value) - {'0', '1'}
                for name, value in reset['next_outputs'].items()):
            raise metrics.MetricRefusal('D25_MODE_INVALID', 'source reset output values')
        prefix += f'prep -top {top} -flatten\nmemory_map\nopt\n'
        proofs = ' '.join(f'-prove {name} {len(value)}\'b{value}'
                          for name, value in reset['next_outputs'].items())
        sat_script = folder / 'reset.ys'
        sat_script.write_text(prefix + f'sat -seq 2 -set-at 1 {reset["port"]} {reset["active_level"]} '
                              + proofs + f' -prove-skip 1 -verify -dump_vcd {folder}/reset-cex.vcd\n')
        guard()
        cp = subprocess.run(['yosys', '-Q', '-T', '-s', str(sat_script)], capture_output=True, text=True)
        (folder / 'reset.log').write_text(cp.stdout + cp.stderr)
        reset_rc = cp.returncode
        if reset_rc and not (folder / 'reset-cex.vcd').is_file():
            raise metrics.MetricRefusal('D25_RESET_MODEL_UNPROVEN', side)
        replay = folder / 'replay.ys'
        reset_option = '-reset' if reset['active_level'] else '-resetn'
        replay.write_text(prefix + f'write_rtlil {folder}/before.il\nsim -clock {mode["clock"]["port"]} '
                          + f'{reset_option} {reset["port"]} -rstlen 1 -n 1 -w -a -vcd {folder}/reset.vcd\n'
                          + f'write_rtlil {folder}/after.il\nwrite_json {folder}/after.json\n')
        guard()
        cp = subprocess.run(['yosys', '-Q', '-T', '-s', str(replay)], capture_output=True, text=True)
        (folder / 'replay.log').write_text(cp.stdout + cp.stderr)
        if cp.returncode:
            raise metrics.MetricRefusal('D25_RESET_MODEL_UNPROVEN', side)
        derivation[side] = {'reset_returncode': reset_rc, 'files': [record(p) for p in sorted(folder.iterdir())]}
    script = directory / 'source-boundary.eqy'
    script.write_text(f'[gold]\nread_rtlil {directory}/gold/after.il\n[gate]\n'
        + f'read_rtlil {directory}/gate/after.il\n[script]\nprep -top {top} -flatten\n'
        + 'memory -nomap\nasync2sync\nclk2fflogic\nsplitnets\n[collect *]\ngroup *\n'
        + '[partition *]\namend *\n[strategy sat]\nuse sat\ndepth 5\n'
        + '[strategy pdr]\nuse sby\nengine abc pdr -rfi\n')
    cfg, _ = Config.load({'DESIGN_NAME': top, 'PDK': manifest['pdk']['name'],
        'STD_CELL_LIBRARY': manifest['pdk']['library'], 'VERILOG_FILES': list(map(str, prepared['gold'])),
        'CELL_VERILOG_MODELS': list(map(str, prepared['models'])), 'EQY_SCRIPT': str(script),
        'EQY_FORCE_ACCEPT_PDK': True}, EQY.get_all_config_variables(), design_dir=str(project),
        pdk_root=manifest['pdk']['root'])
    import fnmatch
    libraries = cfg.get('CELL_LIBS') or cfg.get('LIB') or {}
    corner = cfg.get('DEFAULT_CORNER') or ''
    chosen = [str(lib) for pattern, values in libraries.items() if fnmatch.fnmatch(corner, pattern)
              for lib in (values if isinstance(values, list) else [values])]
    if (len(chosen) != 1 or Path(chosen[0]).resolve() != prepared['liberty']
            or digest(Path(chosen[0])) != manifest['liberty']['sha256']):
        raise metrics.MetricRefusal('D25_MODEL_NOT_QUALIFIED', 'native resolved Liberty differs')
    write_json(directory / 'resolved-config.json', json.loads(cfg.dumps()))
    guard()
    error = None
    try:
        EQY(config=cfg, state_in=State({DesignFormat.NETLIST: LLPath(str(prepared['gate']))})).start(
            step_dir=str(directory / 'native'))
    except StepError as exc:
        error = str(exc)
    guard()
    native = directory / 'native'
    files = [p for p in directory.rglob('*') if p.is_file()]
    execution = {'program': 'librelane_eqy', 'producer': 'run_eqy.D25', 'purpose': mode['purpose'],
        'context_sha256': owner_context['context_sha256'], 'attempt': str(attempt.relative_to(project)),
        'attempt_request': record(attempt / 'request.json'),
        'row_contract': {k: context['resolved_row'][k] for k in ('id', 'obligations')},
        'sources': source_ids, 'inputs': readset, 'mode': mode,
        'subject': {'rtl': manifest['rtl'], 'gate_netlist': manifest['gate_netlist'],
                    'liberty': manifest['liberty'], 'models': manifest['models']},
        'live_cells': sorted(cells), 'outputs': outputs, 'derivation': derivation,
        'native_directory': str(native.relative_to(project)), 'native_error': error,
        'launch': launch, 'files': [record(p) for p in sorted(files)]}
    write_json(project / 'reports/lec_eqy_execution.json', execution)
    return native


def d25_reopen(project: Path, prepared: dict, context: dict) -> dict:
    """Read only: bind current original/derived views, native artifacts and original host launch."""
    import hashlib
    import tempfile
    import librelane_contract as contract
    import flow109_metric_acceptance as metrics
    project = project.resolve()
    reader_sources = d25_sources()
    path = project / 'reports/lec_eqy_execution.json'
    raw = path.read_bytes()
    doc = json.loads(raw)
    bound = prepared['bound']
    proof_inputs = dict(prepared['consumed'])
    authority, adopted = metrics._approved_document(project,
        'adopted/base_16/native_execution.json', authority='requirements_owner',
        schema='vibeic.flow109.adopted-reference.v1')
    source = json.loads(bound(authority['source']).read_text())
    bound({'path': authority['path'], 'sha256': authority['sha256']})
    if (source.get('authority_source') != prepared['required']['source']
            or source.get('purpose') != prepared['mode']['purpose']
            or any(adopted.get(key) != source.get(key) for key in
                   ('purpose', 'authority_source', 'native_executions'))):
        raise metrics.MetricRefusal('D25_NATIVE_AUTHORITY_UNBOUND', 'execution adoption differs from its source')
    executions = source.get('native_executions')
    reference = (executions.get(prepared['manifest']['gate_netlist']['sha256'])
                 if isinstance(executions, dict) else None)
    if (not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}
            or reference['path'] != str(path.relative_to(project))
            or reference['sha256'] != hashlib.sha256(raw).hexdigest()):
        raise metrics.MetricRefusal('D25_NATIVE_EXECUTION_UNQUALIFIED',
                                   'original producer receipt lacks an independent current adoption')
    # The independently adopted complete receipt pins its original producer
    # sources and every derived/native input. A newer reader can reuse those
    # unchanged bytes; caller-resealed file hashes cannot qualify new bytes.
    if (doc.get('producer') != 'run_eqy.D25' or doc.get('program') != 'librelane_eqy'
            or doc.get('purpose') != prepared['mode']['purpose']
            or doc.get('mode') != prepared['mode']
            or doc.get('subject') != {key: prepared['manifest'][key]
                                     for key in ('rtl', 'gate_netlist', 'liberty', 'models')}):
        raise metrics.MetricRefusal('D25_NATIVE_EXECUTION_UNBOUND', 'producer/purpose/source/subject')
    if doc.get('row_contract') != {k: context['resolved_row'][k] for k in ('id', 'obligations')}:
        raise metrics.MetricRefusal('D25_NATIVE_EXECUTION_UNBOUND', 'D25 contract changed')
    request_path = bound(doc['attempt_request'])
    request = json.loads(request_path.read_text())
    if (request_path != project / doc['attempt'] / 'request.json'
            or request.get('project_root_sha256') != hashlib.sha256(str(project).encode()).hexdigest()
            or request.get('context_sha256') != doc['context_sha256']
            or 'D25' not in request.get('component_ids', [])
            or request.get('dispatch_kind') != 'canonical_owner_window'):
        raise metrics.MetricRefusal('D25_NATIVE_EXECUTION_UNBOUND', 'original canonical attempt differs')
    expected = proof_inputs
    expected[str(request_path)] = doc['attempt_request']['sha256']
    import shutil
    expected.update({str(Path(shutil.which(tool)).resolve()): digest(Path(shutil.which(tool)).resolve())
                     for tool in ('eqy', 'yosys', 'iverilog')})
    expected[doc['launch']['attestation_path']] = doc['launch']['attestation_sha256']
    if doc['inputs'] != expected:
        raise metrics.MetricRefusal('D25_NATIVE_READSET_INCOMPLETE', 'actual input/tool/launch readset differs')
    native_path = project / doc['native_directory']
    actual_files = {str(p.relative_to(project)) for p in native_path.parent.rglob('*') if p.is_file()}
    if actual_files != {r['path'] for r in doc['files']}:
        raise metrics.MetricRefusal('D25_NATIVE_READSET_INCOMPLETE', 'native/derived artifact population differs')
    for record in doc['files']:
        bound(record)
    for name, sha in doc['inputs'].items():
        if digest(Path(name)) != sha:
            raise metrics.MetricRefusal('D25_NATIVE_INPUT_STALE', name)
    native = project / doc['native_directory']
    if not native.resolve().is_relative_to(project) or native.is_symlink():
        raise metrics.MetricRefusal('D25_NATIVE_EXECUTION_UNBOUND', 'foreign native folder')
    cfg = json.loads((native / 'config.json').read_text())
    state = json.loads((native / 'state_in.json').read_text())
    if (cfg.get('meta', {}).get('step') != 'Yosys.EQY'
            or cfg.get('VERILOG_FILES') != list(map(str, prepared['gold']))
            or state.get('nl') != str(prepared['gate'])
            or cfg.get('CELL_VERILOG_MODELS') != list(map(str, prepared['models']))
            or Path(cfg.get('EQY_SCRIPT', '')).resolve() != native.parent / 'source-boundary.eqy'
            or (native / (prepared['mode']['top'] + '.eqy')).read_bytes()
               != (native.parent / 'source-boundary.eqy').read_bytes()
            or not (native / 'formal_pdk.v').is_file()):
        raise metrics.MetricRefusal('D25_NATIVE_CONFIGURATION_UNBOUND', 'actual state/script/models differ')
    launch = doc['launch']
    host_raw = Path(launch['attestation_path']).read_bytes()
    host = json.loads(host_raw)
    try:
        current = contract.local_image_attestation()
    except contract.Refusal as exc:
        raise metrics.MetricRefusal('D25_NATIVE_LAUNCH_UNBOUND', str(exc)) from exc
    inspected = host['container_inspect']
    if (hashlib.sha256(host_raw).hexdigest() != launch['attestation_sha256']
            or host['cid'] != launch['cid'] or inspected['Id'] != launch['cid']
            or inspected['Image'] != launch['image_id'] or current['image_id'] != launch['image_id']
            or host['image'] != launch['image'] or inspected['Config']['Image'] != launch['image']
            or not inspected['Config']['Hostname'].startswith(launch['cid'][:12])
            or inspected['State']['Running'] is not True):
        raise metrics.MetricRefusal('D25_NATIVE_LAUNCH_UNBOUND', 'actual original CID/image/host receipt')
    with tempfile.TemporaryDirectory(prefix='d25-reader-') as tmp:
        proof = judge_eqy(native, Path(tmp) / 'proof.json')
    parts = proof['partitions'] or {}
    # EQY outbits include matched internal cutpoints. Derive the external
    # interface independently from BOTH sealed native source views; projection
    # of external coverage must never change the complete proof judgement.
    external_views, point_views = [], []
    for side in ('gold', 'gate'):
        for filename in ('census.json', 'after.json'):
            census = native.parent / side / filename
            records = [r for r in doc['derivation'][side]['files']
                       if project / r['path'] == census]
            if (len(records) != 1 or records[0] not in doc['files']
                    or digest(census) != records[0]['sha256']):
                raise metrics.MetricRefusal('D25_PARTITION_CENSUS_UNBOUND', 'sealed native interface absent')
            module = json.loads(census.read_text())['modules'][prepared['mode']['top']]
            external = {name: list(range(len(port['bits'])))
                        for name, port in module['ports'].items()
                        if port['direction'] in ('output', 'inout')}
            if not external or any(not bits for bits in external.values()):
                raise metrics.MetricRefusal('D25_PARTITION_CENSUS_UNBOUND', 'empty native external interface')
            external_views.append(external)
            if filename == 'after.json':
                points = set()
                for name, net in module['netnames'].items():
                    width = len(net['bits'])
                    points.update((name, bit) for bit in range(width))
                    if width > 1:
                        points.update((f'{name}[{bit}]', 0)
                                      for bit in range(net.get('offset', 0),
                                                       net.get('offset', 0) + width))
                point_views.append(points)
    external = external_views[0]
    if any(view != external for view in external_views[1:]) or external != prepared['mode']['outputs']:
        raise metrics.MetricRefusal('D25_PARTITION_CENSUS_UNBOUND', 'native gold/gate and required interface differ')
    matched_points = point_views[0] & point_views[1]
    output_bits = {}
    for name in parts:
        partition = json.loads((native / 'scratch/partitions' / (name + '.json')).read_text())['partition']
        for port, bits in partition['outbits'].items():
            if (not isinstance(bits, list) or not bits or any(type(bit) is not int
                    or (port, bit) not in matched_points for bit in bits)):
                raise metrics.MetricRefusal('D25_PARTITION_CENSUS_UNBOUND', 'foreign native output/cutpoint')
            if port in external:
                output_bits.setdefault(port, []).extend(bits)
    if ({name: sorted(bits) for name, bits in output_bits.items()} != external
            or set(doc['live_cells']) - set(prepared['qualification']['qualified_cell_types'])
            or not doc['live_cells'] or doc['outputs'] != prepared['mode']['outputs']):
        raise metrics.MetricRefusal('D25_PARTITION_CENSUS_UNBOUND', 'output/cell population differs')
    if proof['verdict'] == 'PASS' and (doc.get('native_error') is not None
            or not (native / 'state_out.json').is_file()
            or json.loads((native / 'state_out.json').read_text()).get('nl') != str(prepared['gate'])):
        raise metrics.MetricRefusal('D25_NATIVE_EXECUTION_UNBOUND', 'native completion absent')
    if proof['verdict'] == 'FAIL' and not list((native / 'scratch/strategies').rglob('*.vcd')):
        raise metrics.MetricRefusal('D25_NATIVE_CEX_UNBOUND', 'actual counterexample absent')
    if proof['verdict'] == 'PASS' and any(d['reset_returncode'] != 0 for d in doc['derivation'].values()):
        raise metrics.MetricRefusal('D25_RESET_MODEL_UNPROVEN', 'reset relation is not proven')
    if (path.read_bytes() != raw or reader_sources != d25_sources()
            or any(digest(Path(p)) != sha for p, sha in prepared['consumed'].items())):
        raise metrics.MetricRefusal('D25_NATIVE_INPUT_STALE', 'changed during consumer read')
    return {'proof': proof, 'mode': doc['mode'], 'subject': doc['subject'], 'sources': doc['sources'],
            'reader_sources': reader_sources,
            'launch': launch, 'execution_record': {'path': str(path.relative_to(project)),
                                                 'sha256': hashlib.sha256(raw).hexdigest()},
            'execution_authority': authority,
            'consumed_inputs': prepared['consumed']}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="Yosys.EQY step directory")
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)
    report = judge_eqy(args.folder, args.json)
    print(f"[{report['verdict']}] {report['explanation']}")
    return {"PASS": 0, "FAIL": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
