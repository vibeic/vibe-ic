#!/usr/bin/env python3
"""Invoke a positional PDK provider and import its actual ring hierarchy.

This producer draws no ring. It preserves the original design and imports
the PDK's own output under its top. Existing sealring_verify owns topology;
general_precheck still owns declared whole-DIE origin/extent. Neither is
replaced by the provider frame or by a successful Magic process exit.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pya


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dependencies(script, workspace):
    return {str(p): sha(p) for p in sorted(script.parent.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts
            and not p.resolve().is_relative_to(workspace.resolve())}


def snapshot(layout, cells, ignore=None):
    out = {}
    for cell in cells:
        shapes = {}
        for li in layout.layer_indexes():
            info = layout.get_info(li)
            values = sorted(s.to_s() for s in cell.shapes(li).each())
            if values:
                shapes[f'{info.layer}/{info.datatype}'] = values
        insts = sorted(str(i.cell_inst) for i in cell.each_inst()
                       if i.cell_index != ignore)
        out[cell.cell_index()] = {'name': cell.name, 'shapes': shapes, 'instances': insts}
    return out


def main():
    rep = Path(os.environ['MAGIC_PROVIDER_REPORT'])
    result = {'producer': 'magic_positional_sealring_provider', 'state': 'FAIL',
              'adapter_sha256': sha(__file__)}
    try:
        script = Path(os.environ['MAGIC_PROVIDER_SCRIPT']).resolve(strict=True)
        src = Path(os.environ['MAGIC_PROVIDER_IN'])
        dst = Path(os.environ['MAGIC_PROVIDER_OUT'])
        geometry = json.loads(os.environ['MAGIC_PROVIDER_GEOMETRY'])
        convention = geometry['size_convention']
        dims, offset = geometry['provider_size_um'], geometry['offset_um']
        finite = lambda n: type(n) in (int, float) and math.isfinite(n)
        if (set(geometry) != {'size_convention', 'provider_size_um', 'offset_um'}
                or convention not in ('chip', 'outer')
                or len(dims) != 2 or not all(finite(v) and v > 0 for v in dims)
                or len(offset) != 2 or not all(finite(v) for v in offset)):
            raise ValueError('invalid explicit Magic geometry authority')
        # A new cwd prevents the PDK generator from entering a shared-temp
        # fallback and deleting another invocation's working files.
        workspace = Path(tempfile.mkdtemp(prefix='magic-provider-', dir=str(rep.parent)))
        target = workspace / 'provider-output'
        target.mkdir()
        command = [os.environ.get('MAGIC_PROVIDER_PYTHON', 'python3'), str(script),
                   str(dims[0]), str(dims[1]), str(target)]
        if convention == 'outer':
            command.append('-outer')
        command.append('-keep')
        before = dependencies(script, workspace)
        result.update(script=str(script), script_sha256=sha(script),
            provider_directory_files=before,
            dependency_scope='regular files under provider script directory excluding this fresh invocation workspace; selected runtime image owns external tools/libraries',
            argv=command, cwd=str(workspace), geometry=geometry,
            geometry_source=os.environ.get('MAGIC_PROVIDER_GEOMETRY_SOURCE'),
            input_gds=str(src), input_gds_sha256=sha(src))
        p = subprocess.run(command, cwd=str(workspace), capture_output=True,
                           text=True, timeout=3300)
        (workspace / 'stdout.log').write_text(p.stdout)
        (workspace / 'stderr.log').write_text(p.stderr)
        result.update(generator_rc=p.returncode, stdout=str(workspace/'stdout.log'),
                      stderr=str(workspace/'stderr.log'))
        if before != dependencies(script, workspace):
            raise ValueError('provider sources changed during execution')
        if p.returncode:
            raise ValueError(f'provider exited {p.returncode}')
        outputs = sorted(target.glob('*.gds'))
        if len(outputs) != 1 or not outputs[0].is_file() or not outputs[0].stat().st_size:
            raise ValueError(f'provider must produce exactly one nonempty GDS; got {outputs}')
        ring_file = outputs[0]
        ring = pya.Layout()
        ring.read(str(ring_file))
        tops = ring.top_cells()
        if len(tops) != 1 or tops[0].bbox().empty():
            raise ValueError('provider GDS must have one nonempty top')
        original = pya.Layout()
        original.read(str(src))
        if abs(original.dbu - ring.dbu) > 1e-12:
            raise ValueError('provider/input GDS database units differ; implicit geometry scaling is unsupported')
        old_tops = original.top_cells()
        if len(old_tops) != 1 or old_tops[0].bbox().empty():
            raise ValueError('input GDS must have one nonempty top')
        top = old_tops[0]
        old_cells = list(original.each_cell())
        old_snapshot = snapshot(original, old_cells)
        name = 'sealring_provider'
        suffix = 0
        while original.cell(name) is not None:
            suffix += 1
            name = f'sealring_provider_{suffix}'
        imported = original.create_cell(name)
        imported.copy_tree(tops[0])
        delta = [round(v / original.dbu) for v in offset]
        if any(abs(delta[i] * original.dbu - offset[i]) > original.dbu * 1e-6
               for i in range(2)):
            raise ValueError('declared ring offset is not representable on the input GDS database grid')
        top.insert(pya.CellInstArray(imported.cell_index(), pya.Trans(*delta)))
        if snapshot(original, old_cells, imported.cell_index()) != old_snapshot:
            raise ValueError('import changed original design geometry or hierarchy')
        if [t.name for t in original.top_cells()] != [top.name]:
            raise ValueError('import did not preserve the single original design top')
        if sha(src) != result['input_gds_sha256']:
            raise ValueError('input GDS changed during provider execution')
        dst.parent.mkdir(parents=True, exist_ok=True)
        original.write(str(dst))
        b = tops[0].dbbox()
        merged = top.dbbox()
        result.update(state='WROTE', provider_gds=str(ring_file),
            provider_gds_sha256=sha(ring_file), provider_top=tops[0].name,
            provider_bbox_um=[b.left,b.bottom,b.right,b.top],
            provider_dbu_um=ring.dbu, original_top=top.name,
            original_geometry_and_hierarchy_preserved=True,
            imported_instance_cell=imported.name, output_gds=str(dst),
            output_gds_sha256=sha(dst), output_dbu_um=original.dbu,
            output_bbox_um=[merged.left,merged.bottom,merged.right,merged.top],
            qualification='provider execution/import only; topology, whole-DIE size, DRC/LVS and release remain with their existing consumers')
    except Exception as exc:
        result.update(state='FAIL', reason=str(exc))
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['state'] == 'WROTE' else 1


if __name__ == '__main__':
    sys.exit(main())
