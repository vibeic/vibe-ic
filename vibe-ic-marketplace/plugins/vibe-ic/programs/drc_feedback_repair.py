#!/usr/bin/env python3
"""Bounded post-route feedback from a router-invisible sign-off rule.

All trials live in digest-named private scratch.  No routed DEF is replaced
unless the original deck reaches zero and every route guard accepts the trial.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from _atomic_artefact import write_bytes, write_text
from _docker_memory import docker_memory_flags
import _container_exec as _ce
import instrument_calibration as _instrument_calibration

#: This step's own copy of the layout it published over the canonical DEFs.
PUBLISHED_DEF_NAME = 'routed_drc_feedback.def'

_MARKER = re.compile(r"-?\d+(?:\.\d+)?")
_ROUTE_VIA = re.compile(r"(?:ROUTED|NEW)\s+\S+\s+\(\s*(\d+)\s+(\d+)\s*\)\s+(\S*Via\S*)", re.I)
_FINAL_DRC = re.compile(r"^\[INFO DRT-0702\] Post-route verification: (\d+) violation\(s\)\.$", re.M)
_ANT_NET = re.compile(r"^\[INFO ANT-0002\] Found (\d+) net violations\.$", re.M)
_ANT_PIN = re.compile(r"^\[INFO ANT-0001\] Found (\d+) pin violations\.$", re.M)
_SCOPED_HELD = re.compile(
    r'^\[INFO DRT-0633\] Scoped detailed routing: (\d+) net\(s\) named, '
    r'(\d+) of \2 other net\(s\) held fixed .*$', re.M)
_SCOPED_IDENTICAL = re.compile(
    r'^\[INFO DRT-0634\] Scoped detailed routing touched (\d+) net\(s\) '
    r'in the database and left (\d+) net\(s\) byte-identical\..*$', re.M)
_SCOPED_DRC = re.compile(
    r'^\[INFO DRT-0711\] Scoped detailed routing: whole-design violations '
    r'0 on entry, 0 on exit \(delta \+0\)\.$', re.M)


_IMAGE_DIGEST_RE = re.compile(r'(?:sha256:)?[0-9a-f]{64}$')


def _image_digest_bound(image: str) -> bool:
    """Accept the digest forms used by the canonical image contract."""
    import _eda_pin
    return bool(_eda_pin.reference_digest(image) or
                _IMAGE_DIGEST_RE.fullmatch(str(image or '')))


class _Absent(ValueError):
    """An absence refusal. ``str()`` stays the bare code the receipt records as
    its ``reason``; ``where`` names the search space the code alone cannot, so
    "not there" and "never looked" do not read the same."""

    def __init__(self, code: str, where: str):
        super().__init__(code)
        self.where = where


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _rules(deck: str) -> list[dict]:
    data = json.loads((_HERE / 'router_invisible_rules.json').read_text())
    matches = [d for d in data['decks'] if d['deck_basename'] == Path(deck).name]
    if len(matches) != 1:
        return []
    return matches[0]['rules']


def has_reviewed_rule(deck: str | None) -> bool:
    return bool(_rules(deck or ''))


def image_for_container(container: str) -> str:
    """A fresh private docker run must use the live container's exact image."""
    # The canonical runner may itself be executing inside the pinned EDA
    # image. There is then no docker client to inspect the named outer
    # container, and falling back to that name would make the later launch
    # ambiguous. Reuse the runner's digest-bound image reference instead;
    # a tag or bare image id is not enough to identify the current bytes.
    if _ce.no_container_route():
        import _eda_pin
        for key in ('VIBEIC_EDA_IMAGE', 'IIC_EDA_IMAGE'):
            reference = (os.environ.get(key) or '').strip()
            if _eda_pin.reference_digest(reference):
                return reference
        # Keep the caller on its normal refusal path. ``run`` records a
        # digest-contract refusal before any EDA tool or layout writer runs.
        # Do not return the caller token: a token can itself look like a bare
        # digest and would incorrectly bind an unverified local image.
        return "FEEDBACK_IMAGE_UNBOUND"
    cp = subprocess.run(['docker', 'inspect', '--type', 'container',
                         '--format', '{{.Image}}', container],
                        capture_output=True, text=True, check=False)
    return cp.stdout.strip() if cp.returncode == 0 and cp.stdout.strip() else container


def _markers(report: Path, rule: str) -> list[dict]:
    root = ET.parse(report).getroot()
    if root.tag != 'report-database' or root.find('items') is None:
        raise ValueError('FEEDBACK_RDB_UNREADABLE')
    result = []
    for item in root.findall('./items/item'):
        category = (item.findtext('category') or '').strip("'\" ")
        if category != rule:
            raise ValueError(f'FEEDBACK_UNDECLARED_RULE:{category}')
        raw = item.findtext('./values/value') or ''
        nums = [float(x) for x in _MARKER.findall(raw)]
        if len(nums) != 8 or not raw.startswith('edge-pair:'):
            raise ValueError('FEEDBACK_MARKER_UNREADABLE')
        xs, ys = nums[0::2], nums[1::2]
        result.append({'rule': rule, 'value': raw,
                       'bbox_um': [min(xs), min(ys), max(xs), max(ys)]})
    return result


def _def_nets(path: Path) -> tuple[int, dict[str, str]]:
    body = path.read_text(errors='replace')
    units = re.search(r'UNITS DISTANCE MICRONS\s+(\d+)\s*;', body)
    sec = re.search(r'\nNETS\s+\d+\s*;(.*?)\nEND NETS', body, re.S)
    if not units or not sec:
        raise ValueError('FEEDBACK_DEF_UNREADABLE')
    nets = {}
    for match in re.finditer(r'(?:^|\n)\s*-\s+(\S+)(.*?)\s*;', sec.group(1), re.S):
        nets[match.group(1)] = match.group(2)
    if not nets:
        raise ValueError('FEEDBACK_DEF_NETS_EMPTY')
    return int(units.group(1)), nets


def _def_design(path: Path) -> str:
    match = re.search(r'^DESIGN\s+(\S+)\s*;', path.read_text(errors='replace'), re.M)
    if not match:
        raise _Absent('FEEDBACK_DEF_DESIGN_MISSING',
                      f'no DESIGN statement in {path}')
    return match.group(1)


def _map_markers(markers: list[dict], source_def: Path, rule: dict) -> tuple[list[dict], list[str]]:
    dbu, nets = _def_nets(source_def)
    chosen = []
    for marker in markers:
        x1, y1, x2, y2 = marker['bbox_um']
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        candidates = []
        for name, body in nets.items():
            for via in _ROUTE_VIA.finditer(body):
                if not re.match(rule['via_pattern'], via.group(3)):
                    continue
                vx, vy = int(via.group(1)) / dbu, int(via.group(2)) / dbu
                distance = ((vx - cx) ** 2 + (vy - cy) ** 2) ** .5
                if distance <= rule['search_radius_um']:
                    candidates.append((distance, name, vx, vy, via.group(3)))
        candidates.sort()
        if not candidates or (len(candidates) > 1 and
                              candidates[1][0] - candidates[0][0] < .02):
            raise ValueError('FEEDBACK_MARKER_NET_AMBIGUOUS:' + marker['value'])
        _, name, vx, vy, via_name = candidates[0]
        chosen.append({**marker, 'net': name, 'via': via_name,
                       'via_um': [vx, vy]})
    return chosen, sorted({m['net'] for m in chosen})


def _wire_guard(before: Path, after: Path, targets: set[str]) -> tuple[bool, list[str]]:
    _, old = _def_nets(before)
    _, new = _def_nets(after)
    changed = sorted(n for n in old.keys() | new.keys()
                     if n not in targets and old.get(n) != new.get(n))
    missing_target = sorted(n for n in targets if n not in new or
                            '+ ROUTED' not in new[n])
    return not changed and not missing_target, changed + missing_target


def _native_scoped_guard(log: str, targets: set[str]) -> bool:
    _instrument_calibration.assert_calibrated('drc_feedback_repair::_native_scoped_guard')
    held = _SCOPED_HELD.findall(log)
    identical = _SCOPED_IDENTICAL.findall(log)
    if not held or not identical or not _SCOPED_DRC.search(log):
        return False
    named, others = map(int, held[-1])
    touched, unchanged = map(int, identical[-1])
    return named == len(targets) and touched == len(targets) and others == unchanged


def _antenna(log: str) -> tuple[int, int]:
    _instrument_calibration.assert_calibrated('drc_feedback_repair::_antenna')
    a, b = _ANT_NET.findall(log), _ANT_PIN.findall(log)
    if not a or not b:
        raise ValueError('FEEDBACK_ANTENNA_NOT_MEASURED')
    return int(a[-1]), int(b[-1])


def _docker(image: str, project: Path, args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    mount = str(project.parent.resolve())
    cmd = ['docker', 'run', '--rm', *docker_memory_flags(), '--network', 'none',
           '-v', f'{mount}:{mount}', '-v', f'{_HERE}:/feedback_programs:ro',
           '-w', str(project.resolve())]
    for key, value in (env or {}).items():
        cmd += ['-e', f'{key}={value}']
    cmd += [image, '--skip', *args]
    if _ce.no_container_route():
        # The outer canonical launch already supplies the pinned image,
        # project mount, PDK mount and resource ceiling. Re-entering Docker
        # from inside it is impossible; execute the exact post-image command
        # on this filesystem and translate only the private source mount.
        mounts = [('/feedback_programs', str(_HERE.resolve()))]
        local_args = [
            _ce.localise_mounted_paths(str(value), mounts) for value in args
        ]
        local_env = dict(os.environ)
        local_env.update({
            key: _ce.localise_mounted_paths(str(value), mounts)
            for key, value in (env or {}).items()
        })
        local_env.setdefault('IIC_OSIC_TOOLS_QUIET', '1')
        return subprocess.run(local_args, cwd=str(project.resolve()), env=local_env,
                              capture_output=True, text=True, check=False)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _openroad_prefix(lefs: list[str], source_def: Path) -> str:
    if not lefs or any('\n' in x or '}' in x for x in lefs):
        raise ValueError('FEEDBACK_LEF_UNREADABLE')
    return ''.join(f'read_lef {{{p}}}\n' for p in lefs) + f'read_def {{{source_def}}}\n'


def _route_layer_policy(project: Path) -> str:
    deck_path = project / 'phase3/stage3/pnr/pnr.tcl'
    if not deck_path.is_file():
        raise _Absent('FEEDBACK_ROUTE_LAYER_POLICY_MISSING',
                      f'no PnR deck file at {deck_path}')
    lines = set(re.findall(r'\bset_routing_layers(?:\s+[-\w]+)+',
                           deck_path.read_text()))
    if len(lines) != 1:
        raise _Absent('FEEDBACK_ROUTE_LAYER_POLICY_MISSING',
                      f'{len(lines)} distinct set_routing_layers lines in '
                      f'{deck_path}, not exactly one')
    return next(iter(lines)).strip() + '\n'


def _pin_map(image: str, project: Path, lefs: list[str], source_def: Path,
             mapped: list[dict], scratch: Path) -> None:
    names = sorted({m['net'] for m in mapped})
    script = scratch / 'pins.tcl'
    tcl = _openroad_prefix(lefs, source_def)
    for name in names:
        tcl += (f'set n [[ord::get_db_block] findNet {{{name}}}]\n'
                'if {$n eq "NULL"} {error FEEDBACK_NET_MISSING}\n'
                'foreach it [$n getITerms] {set r [$it getBBox]; '
                'puts "FEEDBACK_PIN [$it getName] [$r xMin] [$r yMin] '
                '[$r xMax] [$r yMax]"}\n')
    write_text(script, tcl)
    cp = _docker(image, project, ['openroad', '-exit', str(script)])
    write_text(scratch / 'pins.log', cp.stdout + cp.stderr)
    if cp.returncode:
        raise ValueError('FEEDBACK_PIN_MAP_FAILED:' + cp.stderr[-200:])
    dbu, _ = _def_nets(source_def)
    pins = []
    for line in cp.stdout.splitlines():
        match = re.match(r'FEEDBACK_PIN (\S+) (\d+) (\d+) (\d+) (\d+)', line)
        if match:
            pins.append((match.group(1), *(int(x) / dbu for x in match.groups()[1:])))
    for marker in mapped:
        vx, vy = marker['via_um']
        found = [p[0] for p in pins if p[1] <= vx <= p[3] and p[2] <= vy <= p[4]]
        if len(found) != 1:
            raise ValueError('FEEDBACK_PIN_ACCESS_AMBIGUOUS:' + marker['value'])
        marker['instance_pin'] = found[0]


def _stream(image: str, project: Path, pdk: Any, top: str,
            source_def: Path, scratch: Path,
            stream_script_text: str | None = None) -> Path:
    script = project / 'phase3/stage3/pnr/stream_out.py'
    if stream_script_text is not None:
        write_text(script, stream_script_text)
    elif not script.is_file():
        raise _Absent('FEEDBACK_STREAM_SCRIPT_MISSING',
                      f'no stream script file at {script}')
    gds = scratch / 'candidate.gds'
    lefs = [pdk.tech_lef, pdk.cell_lef, *pdk.macro_lefs]
    env = {'TOP': top, 'DEF': str(source_def), 'GDS_OUT': str(gds),
           'LEFS': ';'.join(lefs), 'CELL_GDS': pdk.cell_gds or '',
           'MACRO_GDS': ';'.join(pdk.macro_gds),
           'LEFDEF_MAP': pdk.lefdef_layermap or ''}
    cp = _docker(image, project, ['klayout', '-b', '-r', str(script)], env=env)
    write_text(scratch / 'stream.log', cp.stdout + cp.stderr)
    if cp.returncode or not gds.is_file() or gds.stat().st_size < 1024:
        raise ValueError('FEEDBACK_SCRATCH_STREAM_FAILED')
    return gds


def _measure(image: str, project: Path, deck: str, rule: dict,
             gds: Path, top: str, scratch: Path) -> list[dict]:
    report = scratch / 'rule.rdb'
    cp = _docker(image, project, ['klayout', '-b', '-r',
        '/feedback_programs/_drc_feedback_select.drc',
        '-rd', f'deck_file={deck}', '-rd', f'rule_id={rule["registry_id"]}',
        '-rd', f'input={gds}', '-rd', f'report={report}',
        '-rd', f'topcell={top}'])
    write_text(scratch / 'deck.log', cp.stdout + cp.stderr)
    if (cp.returncode or not report.is_file()
            or f'Starting DRC: executing 1 deck(s).' not in cp.stdout
            or f'Executing deck {rule["registry_id"]} from ' not in cp.stdout
            or rule['source'] not in cp.stdout
            or f'Executing rule {rule["id"]}' not in cp.stdout):
        raise ValueError('FEEDBACK_DECK_NOT_MEASURED:' +
                         (cp.stdout + cp.stderr)[-400:])
    return _markers(report, rule['id'])


def _antenna_baseline(image: str, project: Path, lefs: list[str],
                      source_def: Path, scratch: Path) -> tuple[int, int]:
    script = scratch / 'antenna.tcl'
    write_text(script, _openroad_prefix(lefs, source_def) + 'check_antennas\n')
    cp = _docker(image, project, ['openroad', '-exit', str(script)])
    write_text(scratch / 'antenna.log', cp.stdout + cp.stderr)
    if cp.returncode:
        raise ValueError('FEEDBACK_ANTENNA_NOT_MEASURED:' +
                         (cp.stdout + cp.stderr)[-300:])
    return _antenna(cp.stdout + cp.stderr)


def _reroute(image: str, project: Path, lefs: list[str], source_def: Path,
             mapped: list[dict], rule: dict, scratch: Path,
             half_width: float) -> tuple[Path | None, str]:
    target = scratch / 'trial.def'
    drc = scratch / 'router.drc.rpt'
    script = scratch / 'trial.tcl'
    tcl = _openroad_prefix(lefs, source_def) + _route_layer_policy(project)
    # The keep-outs below steer ONE scoped reroute; they are not design
    # content. Remember what the block already had so exactly the ones made
    # here are destroyed before the DEF is written -- a shipped DEF that keeps
    # them streams them as the layer's blockage datatype, which the PDK's
    # magic deck counts as metal (spm x gf180mcuD: one 0.22 um Metal2 keep-out
    # from a CO.6a trial failed M2.3 on metal that does not exist).
    tcl += 'set _fb_obs_before [[ord::get_db_block] getObstructions]\n'
    for m in mapped:
        x, y = m['via_um']
        box = f'{x-half_width:.4f} {y-half_width:.4f} {x+half_width:.4f} {y+half_width:.4f}'
        tcl += f'create_obstruction -region {{{box}}} -layer {rule["obstruction_layer"]}\n'
    targets = sorted({m['net'] for m in mapped})
    for name in targets:
        tcl += (f'set net [[ord::get_db_block] findNet {{{name}}}]\n'
                'if {$net eq "NULL" || [$net getWire] eq "NULL"} '
                '{error FEEDBACK_TARGET_UNROUTED}\n'
                'odb::dbWire_destroy [$net getWire]\n')
    tcl += ('global_route\n'
            f'detailed_route -nets {{{" ".join(targets)}}} '
            f'-droute_end_iter 30 -output_drc {{{drc}}}\n'
            'set _fb_obs_made 0\n'
            'foreach _fb_o [[ord::get_db_block] getObstructions] {\n'
            '  if {$_fb_o ni $_fb_obs_before} '
            '{ odb::dbObstruction_destroy $_fb_o; incr _fb_obs_made }\n'
            '}\n'
            'puts "FEEDBACK_OBSTRUCTIONS_REMOVED: $_fb_obs_made"\n'
            'check_antennas\n'
            f'write_def {{{target}}}\n')
    write_text(script, tcl)
    cp = _docker(image, project, ['openroad', '-exit', str(script)])
    log = cp.stdout + cp.stderr
    write_text(scratch / 'trial.log', log)
    if cp.returncode or not target.is_file() or any(x in log for x in
            ('DRT-0073', 'DRT-0085', 'No access point', 'Valid access pattern combination not found')):
        return None, log
    return target, log


def _replace_selected(source: Path, outputs: list[Path]) -> None:
    backups = [(path, path.read_bytes()) for path in outputs]
    try:
        for path in outputs:
            tmp = path.with_name(path.name + '.feedback.tmp')
            shutil.copy2(source, tmp)
            os.replace(tmp, path)
    except OSError:
        for path, data in backups:
            tmp = path.with_name(path.name + '.feedback.rollback')
            tmp.write_bytes(data)
            os.replace(tmp, path)
        raise


def run(project: Path, top: str, pdk: Any, image: str, *,
        source_def: Path | None = None, publish: bool = True,
        stream_script_text: str | None = None) -> dict:
    """Run one declared rule on the actual routed DEF; fail closed on every gap."""
    _instrument_calibration.assert_calibrated('drc_feedback_repair::run')
    project = project.resolve()
    pnr = project / 'phase3/stage3/pnr'
    source_def = source_def or pnr / f'{top}.def'
    rules = _rules(pdk.drc_deck or '')
    if not rules:
        return {'status': 'NOT_APPLICABLE', 'reason': 'no reviewed invisible rule'}
    receipt = project / 'reports/phase3/drc_feedback.json'
    record: dict = {'status': 'REFUSED', 'source_def': str(source_def),
                    'deck': pdk.drc_deck, 'image': image,
                    'rules': [r['id'] for r in rules],
                    'rule_sources': {r['id']: r['source'] for r in rules},
                    'invisible_reasons': {r['id']: r['reason'] for r in rules},
                    'trials': []}
    scratch_root = project / 'phase3/scratch/drc_feedback'
    scratch_root.mkdir(parents=True, exist_ok=True)
    try:
        if not source_def.is_file():
            raise _Absent('FEEDBACK_ROUTED_DEF_MISSING',
                          f'no routed DEF file at {source_def}')
        digest = _sha(source_def)
        routed = pnr / 'routed.def'
        # A re-run on the DEF this step itself published measures nothing new
        # and would otherwise overwrite the only record of that rewrite.
        try:
            prior = json.loads(receipt.read_text())
        except (OSError, ValueError):
            prior = {}
        for key in ('publication', 'prior_publication'):
            pub = prior.get(key) if isinstance(prior, dict) else None
            if isinstance(pub, dict) and pub.get('to_sha256') == digest:
                record['prior_publication'] = pub
                break
        if publish and (not routed.is_file() or _sha(routed) != digest):
            raise ValueError('FEEDBACK_CANONICAL_DEF_DIVERGED')
        record['initial_source_sha256'] = digest
        record['source_sha256'] = digest
        if not _image_digest_bound(image):
            raise ValueError('FEEDBACK_IMAGE_DIGEST_REQUIRED')
        design_cell = _def_design(source_def)
        record['design_cell'] = design_cell
        lefs = [pdk.tech_lef, pdk.cell_lef, *pdk.macro_lefs]
        stream_script = pnr / 'stream_out.py'
        if stream_script_text is None and not stream_script.is_file():
            raise _Absent('FEEDBACK_STREAM_SCRIPT_MISSING',
                          f'no stream script file at {stream_script}')
        stream_digest = (hashlib.sha256(stream_script_text.encode()).hexdigest()
                         if stream_script_text is not None else _sha(stream_script))
        basis = {'def_sha256': digest, 'image': image, 'deck': pdk.drc_deck,
                 'lefs': lefs, 'cell_gds': pdk.cell_gds,
                 'macro_gds': pdk.macro_gds,
                 'lefdef_map': pdk.lefdef_layermap,
                 'stream_script_sha256': stream_digest}
        basis_digest = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
        record['layout_basis_sha256'] = basis_digest
        with tempfile.TemporaryDirectory(prefix=basis_digest[:16] + '-', dir=scratch_root) as temp:
            root = Path(temp)
            current = source_def
            baseline_ant = _antenna_baseline(image, project, lefs, current, root)
            record['antenna_before'] = baseline_ant
            for rule in rules:
                one = root / rule['id']
                one.mkdir()
                before = _measure(image, project, pdk.drc_deck, rule,
                                  _stream(image, project, pdk, design_cell,
                                          current, one, stream_script_text),
                                  design_cell, one)
                record['before_count'] = len(before)
                record['markers'] = before
                if not before:
                    record['after_count'] = 0
                    continue
                for pass_index in range(1, 4):
                    mapped, targets = _map_markers(before, current, rule)
                    _pin_map(image, project, lefs, current, mapped, one)
                    record['markers'] = mapped
                    accepted = False
                    for index, half_width in enumerate(
                            rule['obstruction_half_widths_um'], 1):
                        trial_dir = one / f'pass{pass_index}_trial{index}'
                        trial_dir.mkdir()
                        candidate, log = _reroute(image, project, lefs, current,
                                                   mapped, rule, trial_dir, half_width)
                        trial = {'pass': pass_index, 'iteration': index,
                                 'targets': targets, 'obstruction_half_um': half_width}
                        if candidate is None:
                            trial['refusal'] = 'PIN_ACCESS_OR_ROUTER_FAILURE'
                        else:
                            safe, changed = _wire_guard(current, candidate, set(targets))
                            trial['non_target_changed'] = changed
                            counts = _FINAL_DRC.findall(log)
                            trial['router_drc'] = int(counts[-1]) if counts else None
                            try:
                                trial['antenna'] = _antenna(log)
                            except ValueError:
                                trial['antenna'] = None
                            trial['native_wire_guard'] = _native_scoped_guard(log, set(targets))
                            if not safe or not trial['native_wire_guard']:
                                trial['refusal'] = 'NON_TARGET_WIRE_CHANGED'
                            elif trial['router_drc'] != 0:
                                trial['refusal'] = 'ROUTER_DRC_NOT_ZERO'
                            elif trial['antenna'] is None or any(
                                    a > b for a, b in zip(trial['antenna'], baseline_ant)):
                                trial['refusal'] = 'ANTENNA_REGRESSION_OR_UNMEASURED'
                            else:
                                trial['candidate_def_sha256'] = _sha(candidate)
                                gds = _stream(image, project, pdk, design_cell,
                                              candidate, trial_dir,
                                              stream_script_text)
                                trial['scratch_gds_sha256'] = _sha(gds)
                                after = _measure(image, project, pdk.drc_deck,
                                                 rule, gds, design_cell, trial_dir)
                                trial['after_count'] = len(after)
                                if len(after) < len(before):
                                    trial['accepted'] = True
                                    current, before = candidate, after
                                    accepted = True
                                else:
                                    trial['refusal'] = 'SIGNOFF_RULE_NOT_DECREASING'
                        record['trials'].append(trial)
                        if accepted:
                            break
                    if not accepted:
                        raise ValueError('FEEDBACK_BOUND_EXHAUSTED')
                    if not before:
                        break
                if before:
                    raise ValueError('FEEDBACK_BOUND_EXHAUSTED')
                record['after_count'] = 0
            if current != source_def and publish:
                # The accepted trial lives in scratch that is about to be
                # deleted; keep its bytes as this step's own declared output
                # so the rewrite of the canonical DEFs has a producer to name.
                kept = pnr / PUBLISHED_DEF_NAME
                write_bytes(kept, current.read_bytes())
                _replace_selected(current, [source_def, routed])
                record['publication'] = {
                    'from_sha256': digest,
                    'to_sha256': _sha(kept),
                    'output': str(kept),
                    'replaced': [str(source_def), str(routed)],
                    'targets': sorted({t for tr in record['trials']
                                       if tr.get('accepted')
                                       for t in tr.get('targets') or []}),
                }
            record['source_sha256'] = _sha(source_def)
            record['status'] = 'PASS'
            record['reason'] = 'RULE_ZERO_WITH_ROUTE_GUARDS'
        record['scratch_cleaned'] = not Path(temp).exists()
    except (OSError, ValueError, ET.ParseError) as exc:
        record['status'] = 'REFUSED'
        record['reason'] = str(exc)
        if isinstance(exc, _Absent):
            record['reason_where'] = exc.where
    if 'temp' in locals():
        record['scratch_cleaned'] = not Path(temp).exists()
    receipt.parent.mkdir(parents=True, exist_ok=True)
    write_text(receipt, json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def verify_streamed(project: Path, top: str, pdk: Any, image: str,
                    gds: Path) -> dict:
    """BLOCKING: bind the route feedback to the finished mask stream.

    Finishing may add geometry after the scratch DEF stream. Measure the
    reviewed rule again on the actual GDS and refuse any changed input.
    """
    _instrument_calibration.assert_calibrated('drc_feedback_repair::run')
    receipt = project / 'reports/phase3/drc_feedback.json'
    source = project / 'phase3/stage3/pnr' / f'{top}.def'
    try:
        record = json.loads(receipt.read_text())
        if not _image_digest_bound(image):
            raise ValueError('FEEDBACK_IMAGE_DIGEST_REQUIRED')
        if record.get('status') != 'PASS' or record.get('source_sha256') != _sha(source):
            raise ValueError('FEEDBACK_ROUTE_DIGEST_MISMATCH')
        routed = project / 'phase3/stage3/pnr/routed.def'
        if not routed.is_file() or _sha(routed) != _sha(source):
            raise ValueError('FEEDBACK_CANONICAL_DEF_DIVERGED')
        if not gds.is_file():
            raise _Absent('FEEDBACK_FINISHED_GDS_MISSING',
                          f'no finished GDS file at {gds}')
        measured_source_sha = _sha(source)
        measured_gds_sha = _sha(gds)
        design = _def_design(source)
        scratch_root = project / 'phase3/scratch/drc_feedback'
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='finished-feedback-',
                                         dir=scratch_root) as temp:
            counts = {}
            for rule in _rules(pdk.drc_deck or ''):
                one = Path(temp) / rule['id']
                one.mkdir()
                counts[rule['id']] = len(_measure(image, project, pdk.drc_deck,
                                                  rule, gds, design, one))
        if (_sha(source) != measured_source_sha or
                _sha(routed) != measured_source_sha or
                _sha(gds) != measured_gds_sha):
            raise ValueError('FEEDBACK_FINISHED_LAYOUT_CHANGED_DURING_MEASUREMENT')
        record['finished_gds_sha256'] = measured_gds_sha
        record['finished_counts'] = counts
        if any(counts.values()):
            raise ValueError('FEEDBACK_FINISHED_GDS_RULE_NONZERO')
        record['finished_status'] = 'PASS'
    except (OSError, ValueError, ET.ParseError) as exc:
        record = locals().get('record', {})
        record['finished_status'] = 'REFUSED'
        record['finished_reason'] = str(exc)
        if isinstance(exc, _Absent):
            record['finished_reason_where'] = exc.where
    write_text(receipt, json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def check_binding(project: Path, top: str, gds: Path) -> tuple[bool, str]:
    """BLOCKING final admission; old or incomplete receipts never certify GDS."""
    try:
        record = json.loads((project / 'reports/phase3/drc_feedback.json').read_text())
        source = project / 'phase3/stage3/pnr' / f'{top}.def'
        routed = project / 'phase3/stage3/pnr/routed.def'
        if (record.get('status') == 'PASS'
                and record.get('finished_status') == 'PASS'
                and record.get('source_sha256') == _sha(source)
                and _sha(routed) == _sha(source)
                and record.get('finished_gds_sha256') == _sha(gds)
                and record.get('finished_counts')
                and all(v == 0 for v in record['finished_counts'].values())):
            return True, 'FEEDBACK_BOUND_TO_FINISHED_LAYOUT'
    except (OSError, ValueError, TypeError):
        pass
    return False, 'FEEDBACK_LAYOUT_DIGEST_MISMATCH_OR_UNMEASURED'


def declare_publication(project: Path, record: dict, image: str,
                        command: str) -> dict | None:
    """Append the ledger row of a rewrite this step PUBLISHED.

    The runner declares its own call through `_log_invocation`; this is the
    same declaration for the program's documented CLI, which publishes by
    default. Without it the newest ledger row of `routed.def` is the
    router's, naming bytes no longer on disk (PROVENANCE_HASH_MISMATCH).
    A run that published nothing, or a project with no ledger, writes nothing.
    """
    pub = record.get('publication') if isinstance(record, dict) else None
    ledger = Path(project) / 'provenance.jsonl'
    if not isinstance(pub, dict) or not pub.get('output') or not ledger.is_file():
        return None
    root = Path(project).resolve()
    outputs = {}
    for item in [pub['output'], *(pub.get('replaced') or [])]:
        path = Path(item).resolve()
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if path.is_file():
            outputs[rel] = 'sha256:' + _sha(path)
    if not outputs:
        return None
    import datetime
    local_route = _ce.no_container_route()
    row = {
        'record': 'invocation', 'tool': 'openroad', 'version': image,
        'version_capture': (
            'local execution with a digest-bound outer image reference'
            if local_route else 'image digest of the private docker run'),
        'command': command[:400],
        'exec_route': 'local' if local_route else 'container', 'exit_code': 0,
        'measured': True,
        'timestamp': datetime.datetime.now(datetime.timezone.utc)
                     .strftime('%Y-%m-%dT%H:%M:%SZ'),
        'marker': str(Path(project) / 'reports/phase3/drc_feedback.json'),
        'inputs': {str(record.get('source_def')): 'sha256:' + str(pub.get('from_sha256'))},
        'outputs': outputs,
    }
    with ledger.open('a') as fh:
        fh.write(json.dumps(row) + '\n')
    return row


def main(argv: list[str] | None = None) -> int:
    import argparse
    from types import SimpleNamespace
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--top', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--pdk-json', required=True, type=Path)
    parser.add_argument('--source-def', type=Path)
    parser.add_argument('--no-publish', action='store_true')
    args = parser.parse_args(argv)
    pdk = SimpleNamespace(**json.loads(args.pdk_json.read_text()))
    result = run(args.project, args.top, pdk, args.image,
                 source_def=args.source_def, publish=not args.no_publish)
    if result.get('status') == 'PASS':
        declare_publication(
            args.project, result, args.image,
            'openroad -exit trial.tcl (drc_feedback_repair CLI scoped reroute: '
            f"rules={','.join(result.get('rules') or [])} "
            f"nets={','.join((result.get('publication') or {}).get('targets') or [])})")
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('PASS', 'NOT_APPLICABLE') else 1


if __name__ == '__main__':
    raise SystemExit(main())
