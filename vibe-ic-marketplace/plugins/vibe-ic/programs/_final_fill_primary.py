"""Primary final-GDS extraction using the released Magic/reducer primitives.

The released extract CLI automatically adopts generated names for routed DEFs.
Both its adoption reducer and its enclosing receipt are diagnostic-only. This
driver runs the direct, already-named GDS contract instead: no annotation,
native binding, alias remapping, or adoption receipt enters the primary path.
Missing names and every reducer refusal remain blocking failures.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


def load_tool(binary):
    """Resolve the Python source named by the released executable wrapper."""
    executable = Path(binary).resolve()
    if executable.read_text().startswith('#!/usr/bin/env python'):
        source = executable
    else:
        candidates = [Path(word) for line in executable.read_text().splitlines()
                      if line.startswith('exec ')
                      for word in shlex.split(line)[1:]
                      if word.startswith('/') and word.endswith('.py')]
        if len(candidates) != 1 or not candidates[0].is_file():
            raise RuntimeError('released final-fill Python source is not uniquely resolvable')
        source = candidates[0].resolve()
    spec = importlib.util.spec_from_file_location('_released_final_fill_spef', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_launcher(path, binary):
    """Preserve the native CLI arguments with an explicit primary executable."""
    path.write_text(f'#!{sys.executable}\n'
                    'import sys\n'
                    f'sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n'
                    'from _final_fill_primary import main\n'
                    f'raise SystemExit(main({str(binary)!r}))\n')
    path.chmod(0o750)
    return path


def extract(tool, args):
    """Produce primary receipts anew, without consuming diagnostic results."""
    if json.loads(os.environ.get('VIBEIC_FINAL_FILL_ADOPTION', 'null')) is not None:
        raise tool.Refusal('primary extraction does not accept native adoption')
    if args.max_degree < 1:
        raise tool.Refusal('--max-degree must be positive')
    tech = tool.resolve_extract_tech(args.tech)
    output = args.output_dir
    if output.exists() and any(output.iterdir()):
        raise tool.Refusal(f'output directory is not empty: {output}')
    output.mkdir(parents=True, exist_ok=True)
    supplies = tool.def_supply_names(args.design_def)
    names = tool.def_net_names(args.design_def) - supplies.keys()
    keep = output / 'routed-nets.txt'
    keep.write_text(''.join(name + '\n' for name in sorted(names)))
    version = subprocess.run([args.magic, '--version'], check=True,
                             capture_output=True, text=True).stdout.strip()
    script = output / 'extract.tcl'
    script.write_text('drc off\ntech load $env(TECHF)\ngds readonly false\n'
                      'gds read $env(GDS)\nload $env(TOP)\n'
                      'extract style $env(STYLE)\nextract all\n'
                      'ext2spice cthresh 0\next2spice rthresh 0\n'
                      'ext2spice format spef\next2spice -o $env(OUT)\nquit -noprompt\n')
    corners = {}
    for corner, style in (('nom', 'ngspice()'), ('max', 'ngspice(hrhc)'),
                          ('min', 'ngspice(hrlc)')):
        directory = output / corner
        directory.mkdir()
        raw = directory / 'raw.spef'
        environment = {k: v for k, v in os.environ.items()
                       if k not in ('VIBEIC_SPEF_ALIAS_SEEDS', 'VIBEIC_FINAL_FILL_ADOPTION')}
        environment.update(TECHF=str(tech.resolve()), GDS=str(args.gds.resolve()),
                           TOP=args.top, STYLE=style, OUT=str(raw.resolve()))
        log = directory / 'magic.log'
        with log.open('w') as stream:
            completed = subprocess.run([args.magic, '-dnull', '-noconsole', str(script.resolve())],
                                       cwd=directory, env=environment, text=True,
                                       stdout=stream, stderr=subprocess.STDOUT)
        if completed.returncode or not raw.is_file():
            raise tool.Refusal(f'Magic {corner} extraction failed rc={completed.returncode}; see {log}')
        corners[corner] = tool.reduce_spef(
            raw, keep, directory / 'final.spef', directory / 'reduction.json',
            args.max_degree, supply_names=set(supplies))
    result = dict(status='PASS', extraction_mode='primary',
                  geometry={'path': str(args.gds), 'sha256': tool.sha256(args.gds)},
                  routed_def={'path': str(args.design_def), 'sha256': tool.sha256(args.design_def)},
                  top=args.top, fill_aware_tech={'path': str(tech), 'sha256': tool.sha256(tech)},
                  magic={'executable': args.magic, 'version': version},
                  keep_nets_sha256=tool.sha256(keep), keep_net_count=len(names), corners=corners,
                  declared_corner_set=['min', 'nom', 'max'],
                  floating_boundary_condition='zero-net-charge', grounded_fill_approximation=False,
                  excluded_supply_nets=supplies,
                  net_population='DEF nets excluding explicit POWER/GROUND supplies')
    (output / 'FINAL_FILL_EXTRACTION.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


def main(binary):
    tool = load_tool(binary)
    args = tool.make_parser().parse_args()
    try:
        if args.command != 'extract':
            raise tool.Refusal('primary driver only supports extract')
        result = extract(tool, args)
    except (OSError, ValueError, subprocess.CalledProcessError, tool.Refusal) as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0
