#!/usr/bin/env python3
"""Grade native OP interconnect currents against source-provided PDK limits.

Settings contain limits_source (the PDF copy/hash receipt), magic_tech (the
actual extraction technology, local or in the selected container), and cases.
Each case supplies receipt, geometry and optional unit_binding/spice paths.
An optional same-layout native pv_receipt enables conservative sheet-tile
density bounds below the foundry's drawn-width regime; it cannot approve a
subminimum drawn wire or turn an excessive bound into a measured violation.
These are ordinary measured inputs. This module does not run a second OP or
turn selected DC cases into a transient/whole-mission acceptance claim.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import struct
import sys
import uuid
from fractions import Fraction

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    obj=json.loads(path.read_text())
    if not isinstance(obj,dict): raise ValueError(f"object required: {path}")
    return obj


def _path(project: Path, value) -> Path:
    if not isinstance(value,str) or not value: raise ValueError("measured input path absent")
    return (project/ value).resolve()


def parse_process_limits(text: str) -> dict:
    """Read the foundry table's values AND width predicates, without defaults."""
    section=text.split('2.15 Maximum Current Densities',1)
    if len(section)!=2: raise ValueError('foundry current-density table absent')
    body=section[1].split('2.16 Layer Thickness',1)[0]
    rules=collections.defaultdict(list)
    pattern=re.compile(r'^[ \t]*(Metal[1-5]|TopMetal[12]|Contact|Via[1-4]|TopVia[12])[ \t]+([JI]MAX\w+)[ \t]+(mA(?:/µm|/Cnt|/Via)?)[ \t]+([\d.]+)[ \t]+A\.v[ \t]*([^\n]*)$',re.M)
    for m in pattern.finditer(body):
        layer,symbol,unit,value,predicate=m.groups()
        rule={'symbol':symbol,'unit':unit,'value':value,'source_row':m[0].strip()}
        if predicate.strip():
            numbers=re.findall(r'\d+(?:\.\d+)?',predicate)
            if '>' in predicate and len(numbers)==1:
                rule['width_gt_um']=numbers[0]
            elif '=' in predicate and len(numbers)==2:
                rule.update(width_min_um=numbers[0],width_max_um=numbers[1])
            else: raise ValueError('unsupported foundry width predicate: '+predicate)
        rules[layer.lower()].append(rule)
    if not rules: raise ValueError('foundry current-density rows unreadable')
    return dict(rules)


def process_rating_context(text: str) -> dict:
    """Retain the table's stated rating, without deriving a derating law."""
    body=text.split('2.15 Maximum Current Densities',1)[-1].split('2.16 Layer Thickness',1)[0]
    found=re.search(r'\(\s*([\d.]+)\s*years\s*@\s*([+-]?[\d.]+)\s*°?C\s*\)',body)
    if not found:return {}
    return {'duration_years':float(found[1]),'temperature_c':float(found[2]),
            'source_section':'2.15 Maximum Current Densities','source_text':found[0]}


def native_rating_context(transcript: str, rating: dict|None, binding: dict) -> dict:
    values={float(v) for v in re.findall(r'(?i)Doing analysis at TEMP\s*=\s*([+-]?[\d.]+(?:e[+-]?\d+)?)',transcript)}
    temperature=next(iter(values)) if len(values)==1 else None
    declared=(binding.get('conditions') or {}).get('temperature_c')
    if temperature is not None and declared is not None and temperature!=float(declared):
        raise ValueError('native temperature differs from source-bound conditions')
    matched=bool(rating) and temperature is not None and temperature==rating.get('temperature_c')
    return {'source_rating':rating or {},'native_temperature_c':temperature,
            'temperature_matches_source_rating':matched,
            'comparison_scope':'source-rated native temperature' if matched else 'numeric current comparison only',
            'lifetime_scope':'foundry table rating only; no temperature/lifetime extrapolation'}


def resistor_aliases(header: dict, rows: list[dict]):
    """Bind exact zero aliases only under the corrected native reader header."""
    declared='reader_resistance_offset_ohm' in header or 'zero_resistance' in header
    corrected=(header.get('reader_resistance_offset_ohm')==0 and
               header.get('zero_resistance')=='ideal-equivalence')
    if declared and not corrected:raise ValueError('unsupported native resistor reader semantics')
    parent={}
    def root(node):
        node=node.lower();parent.setdefault(node,node)
        while parent[node]!=node:
            parent[node]=parent[parent[node]];node=parent[node]
        return node
    ideals=[]
    if corrected:
        for row in rows:
            ideal=row.get('ideal_short')
            if not isinstance(ideal,bool) or ideal!=(row['resistance_ohm']==0):
                raise ValueError('ideal alias differs from exact native resistance')
            if ideal:
                if row['ext_resistance_value']!=0:raise ValueError('ideal alias EXT value is not zero')
                a,b=root(row['node_a']),root(row['node_b']);parent[b]=a;ideals.append(row)
    def same(a,b):return root(a)==root(b)
    groups=collections.defaultdict(list)
    for node in list(parent):groups[root(node)].append(node)
    return corrected,ideals,same,[sorted(group) for group in groups.values()]


def bind_native_resistors(header: dict, rows: list[dict], spice_text: str) -> list:
    """Match actual emitted positive R cards to native geometry and aliases.

    Collectors may use this same binding before resolving each card's actual
    native voltage vectors. Ideal rows have no resistor/current entry.
    """
    import _analog_a8_extraction_wrapper as wrapper
    corrected,_,_,groups=resistor_aliases(header,rows)
    labels={node:group[0] for group in groups for node in group}
    endpoints=lambda nodes:tuple(sorted(labels.get(n.lower(),n.lower()) for n in nodes))
    bucket=collections.defaultdict(list)
    for row in rows:
        if corrected and row['ideal_short']:continue
        mohms=struct.unpack('f',struct.pack('f',(0 if corrected else .5)+header['resist_scale']*row['ext_resistance_value']))[0]
        resistance=float(format(mohms/1000,'.6g'))
        bucket[(endpoints([row['node_a'],row['node_b']]),resistance)].append(row)
    result=[];names=set()
    for line in wrapper.logical_lines(spice_text):
        parts=line.split()
        if not parts or parts[0][0].lower()!='r' or len(parts)!=4:continue
        if parts[0].lower() in names:raise ValueError('duplicate native resistor identity')
        names.add(parts[0].lower());resistance=float(parts[3])
        key=(endpoints(parts[1:3]),resistance)
        if not math.isfinite(resistance) or resistance<=0 or not bucket[key]:
            raise ValueError('native resistor differs from emitted EXT geometry/ideal aliases')
        result.append((parts,bucket[key].pop(),resistance))
    if any(bucket.values()):raise ValueError('native positive resistor/geometry multiplicity differs')
    return result


def material_map(technology: str) -> tuple[dict,set]:
    """Bind native types through the actual tech's aliases, LEF and contacts."""
    import analog_a5_pdk_device_limits as pdk
    identity=pdk.layer_identity(technology)
    # Magic also accepts unindented LEF bodies (the installed IHP source
    # uses them). Section boundaries, rather than indentation, own this map.
    lef=[];inside=False
    for raw in technology.splitlines():
        line=raw.split('#',1)[0].strip()
        if line=='lef':inside=True;continue
        if line=='end':inside=False;continue
        if inside and line:lef.append(line)
    mapped={}
    for line in lef:
        parts=line.split()
        if len(parts)<3 or parts[0] not in ('routing','cut'): continue
        canonical=identity.canon.get(parts[1])
        if canonical: mapped[canonical]=parts[2].lower()
    # The foundry Contact row applies to actual device/poly-to-Metal1
    # contacts. Higher-level capacitor contacts are not guessed to be these.
    for canonical,residues in identity.connects.items():
        targets=[mapped.get(r) for r in residues]
        if canonical not in mapped and targets.count('metal1')==1 and sum(t is not None for t in targets)==1:
            mapped[canonical]='contact'
    aliases={alias:mapped[canonical] for alias,canonical in identity.canon.items() if canonical in mapped}
    return aliases,set(identity.canon)


def read_op_capture(path: Path) -> dict:
    lines=path.read_text().splitlines()
    if not any(re.match(r'(?i)^Plotname:\s*Operating Point\s*$',x) for x in lines):
        raise ValueError('native capture is not an operating point')
    if not any(re.match(r'^No\. Points:\s*1\s*$',x) for x in lines):
        raise ValueError('native OP capture must contain one point')
    a,b=lines.index('Variables:'),lines.index('Values:')
    names=[line.split()[1].lower() for line in lines[a+1:b] if line.strip()]
    values=[float(line.split()[-1]) for line in lines[b+1:] if line.strip()]
    if len(names)!=len(values) or not all(math.isfinite(v) for v in values):
        raise ValueError('native OP values missing/nonfinite')
    out={re.sub(r'^v\((.*)\)$',r'\1',name):v for name,v in zip(names,values)}
    out['0']=0.0
    return out


def evaluate_row(row: dict, rules: list, width: Fraction|None, *, drc_qualified=False) -> dict:
    current=abs(row['current_a'])*1000
    if not math.isfinite(current): return {'status':'FAIL','detail':'nonfinite native current'}
    if row['is_contact']:
        supported=[r for r in rules if r['unit'] in ('mA/Cnt','mA/Via')]
        nx,ny=row.get('cuts_x'),row.get('cuts_y')
        if not supported or any(isinstance(n,bool) or not isinstance(n,int) or n<1 for n in (nx,ny)):
            return {'status':'NOT_MEASURED','detail':'actual contact count or source cut limit absent'}
        rule=supported[0];limit=float(rule['value']);single=nx*ny==1
        # A whole-array current under one cut's limit is a conservative
        # upper-bound proof. An excess bound is inconclusive for an array.
        status='PASS' if current<=limit else 'FAIL' if single else 'NOT_MEASURED'
        return {'status':status,'current_mA':current,'limit_mA':limit,'source_rule':rule,
                'current_scope':'actual single cut' if single else 'whole-array upper bound only',
                'cuts':[nx,ny]}
    if width is None or width<=0:
        return {'status':'NOT_MEASURED','detail':'native integer/rational wire width absent'}
    candidates=[]
    for rule in rules:
        if 'width_gt_um' in rule and width<=Fraction(rule['width_gt_um']): continue
        if 'width_min_um' in rule and not Fraction(rule['width_min_um'])<=width<=Fraction(rule['width_max_um']): continue
        if rule['unit']=='mA': candidates.append((float(rule['value']),rule))
        elif rule['unit']=='mA/µm': candidates.append((float(Fraction(rule['value'])*width),rule))
    if len(candidates)!=1:
        # extresist partitions a DRC-clean drawn conductor into smaller
        # sheet-resistance tiles. A tile's width is not a new drawn wire.
        # Use a lower density than EVERY source drawable-width regime:
        # Imax/Wmax for the narrow regime, and Jmax for the wide regime.
        # This is a sufficient local-current bound, never a subminimum
        # fabrication rule or a reason to fail an excess upper bound.
        narrow=[r for r in rules if r['unit']=='mA' and 'width_min_um' in r and 'width_max_um' in r]
        wide=[r for r in rules if r['unit']=='mA/µm' and 'width_gt_um' in r]
        if (drc_qualified and len(rules)==2 and len(narrow)==len(wide)==1
                and Fraction(narrow[0]['width_max_um'])==Fraction(wide[0]['width_gt_um'])
                and width<Fraction(narrow[0]['width_min_um'])):
            density=min(Fraction(narrow[0]['value'])/Fraction(narrow[0]['width_max_um']),
                        Fraction(wide[0]['value']))
            limit=float(density*width)
            return {'status':'PASS' if current<=limit else 'NOT_MEASURED',
                    'current_mA':current,'limit_mA':limit,'width_um_exact':str(width),
                    'density_mA_per_um':current/float(width),'source_rules':[narrow[0],wide[0]],
                    'current_scope':'conservative sheet-partition density bound on native DRC-clean drawn wire',
                    'density_bound_mA_per_um_exact':str(density)}
        return {'status':'NOT_MEASURED','detail':'no unique source width/current regime'}
    limit,rule=candidates[0]
    return {'status':'PASS' if current<=limit else 'FAIL','current_mA':current,
            'width_um_exact':str(width),'density_mA_per_um':current/float(width),
            'limit_mA':limit,'source_rule':rule}


def _vector_resolver(project: Path, block: str, rec: dict, raw: Path):
    """Reconstruct the existing lossless A8 hierarchy from actual SPICE."""
    import _analog_a8_extraction_wrapper as wrapper
    source=project/f'phase3/analog/{block}/{block}.sp'
    declared=wrapper.native_ports(source.read_text(),block)
    interface=rec.get('interface') or {}
    native=interface.get('native_subckt')
    expected,rebuilt=wrapper.build_wrapper(raw.read_text(),native,declared)
    if interface!=rebuilt:raise ValueError('native current interface differs from extracted ports')
    input_paths=[Path(p) for p in rec.get('inputs_before',{})]
    wp=[p for p in input_paths if p.name=='interface.sp']
    pp=[p for p in input_paths if p.name=='post.sp']
    dp=[p for p in input_paths if p.name=='op.sp']
    if len(wp)!=1 or len(pp)!=1 or len(dp)!=1 or wp[0].read_text()!=expected:
        raise ValueError('actual native current hierarchy inputs absent or changed')
    def instance(path,model):
        found=[line.split() for line in wrapper.logical_lines(path.read_text())
               if line.lower().startswith('x') and line.split()[-1].lower()==model.lower()]
        if len(found)!=1:raise ValueError('native DUT instance absent or ambiguous')
        return found[0]
    outer=instance(dp[0],block);inner=instance(pp[0],rebuilt['wrapper_subckt'])
    if inner[1:-1]!=declared or len(outer[1:-1])!=len(declared):
        raise ValueError('native current hierarchy aliases the declared interface')
    external=dict(zip((p.lower() for p in declared),(p.lower() for p in outer[1:-1])))
    ports=dict(zip((p.lower() for p in rebuilt['native_ports']),(p.lower() for p in rebuilt['instance_nodes'])))
    prefix=outer[0].lower()+'.'+inner[0].lower()+'.'
    def vector(node):
        node=node.lower()
        if node=='0':return '0'
        if node in ports:
            alias=ports[node]
            return external.get(alias,prefix+alias)
        return prefix+'xnative.'+node
    return vector,external


def mos_stress(source: str, topology: dict, block: str, raw: str,
               model_sources: list[str], voltages: dict, resolver) -> dict:
    """Measure native MOS pairs; source device identities own model roles."""
    import analog_lvs_comparison_prep as prep
    import _analog_a8_extraction_wrapper as wrapper
    letters=prep.topology_instance_letters(source,block,topology)
    typed={d['name'].lower():d for d in topology.get('devices',[])}
    models={}
    for line in wrapper.logical_lines(source):
        parts=line.split()
        if not parts or not parts[0].lower().startswith('x'):continue
        identity=parts[0][1:].lower()
        if letters.get(identity)!='M':continue
        call=prep._split_call(' '.join(parts[1:]))
        if not call or len(call[0])!=4:raise ValueError('source MOS terminals absent')
        role=typed[identity]['role'].lower();model=call[1].lower()
        previous=models.setdefault(model,{'role':role,'source_instances':[]})
        if previous['role']!=role:raise ValueError('source MOS model has ambiguous declared roles')
        previous['source_instances'].append(identity)
    if not models:return {'status':'NOT_APPLICABLE','detail':'no typed source MOS calls'}
    headers=collections.defaultdict(set)
    for text in model_sources:
        for line in wrapper.logical_lines(text):
            parts=line.split()
            if len(parts)>2 and parts[0].lower()=='.subckt' and parts[1].lower() in models:
                # Model parameter continuations belong to this same logical
                # card, after its terminals (the current foundry models do
                # this). Parameter names are not additional device pins.
                pins=re.split(r'\s+(?:params?:|[A-Za-z_]\w*\s*=)',
                              ' '.join(parts[2:]),maxsplit=1,flags=re.I)[0]
                headers[parts[1].lower()].add(tuple(p.lower() for p in pins.split()))
    for model in models:
        if headers[model]!={('d','g','s','b')}:
            raise ValueError('actual consumed MOS model does not declare d/g/s/b order: '+model)
    devices=[];extrema={}
    for line in wrapper.logical_lines(raw):
        parts=line.split()
        if not parts or not parts[0].lower().startswith('x'):continue
        call=prep._split_call(' '.join(parts[1:]))
        if not call or call[1].lower() not in models:continue
        nodes,model,_=call;model=model.lower()
        if len(nodes)!=4:raise ValueError('native MOS call does not have four declared terminals')
        vectors=dict(zip('dgsb',(resolver(node) for node in nodes)))
        values={terminal:voltages[vector.lower()] for terminal,vector in vectors.items()}
        pairs={pair:abs(values[pair[0]]-values[pair[1]]) for pair in ('gs','gd','gb','ds','db','sb')}
        if not all(math.isfinite(v)for v in [*values.values(),*pairs.values()]):
            raise ValueError('native MOS voltage pair nonfinite')
        devices.append({'instance':parts[0],'model':model,'role':models[model]['role'],
                        'terminal_vectors':vectors,'terminal_voltages_v':values,'pairs_v':pairs})
        bymodel=extrema.setdefault(model,{})
        for pair,value in pairs.items():
            if pair not in bymodel or value>bymodel[pair]['value_v']:
                bymodel[pair]={'value_v':value,'instance':parts[0]}
    if not devices:raise ValueError('native extracted MOS calls do not match typed source models')
    return {'status':'PASS','devices':devices,'source_models':models,'maxima_by_model':extrema,
            'scope':'actual terminal voltages at this supplied native OP only; no transient or omitted mission coverage'}


def grade_case(project: Path, setting: dict, limits: dict, aliases: dict, known: set,
               block: str|None=None, rating_context: dict|None=None) -> tuple[dict,dict]:
    import analog_real_corner_sweep as sweep
    receipt_path=_path(project,setting.get('receipt'));rec=_read(receipt_path)
    views={}
    def consume(path,expected=None):
        path=Path(path).resolve();digest=_sha(path)
        if expected and digest!=expected: raise ValueError(f'measured input/output changed: {path}')
        views[str(path)]={'path':str(path),'sha256':digest};return path
    consume(receipt_path)
    outputs=rec.get('outputs') or {}
    logs=[Path(p) for p in outputs if p.endswith('/native.log')]
    if len(logs)==1:
        consume(logs[0],outputs[str(logs[0])])
        transcript=logs[0].read_text(errors='replace')
        native_fail=any(sweep._scan_analysis_failures(transcript)) or re.search(r'(?i)fatal error|simulation(?:\(s\))? aborted|timestep too small',transcript)
        if native_fail:
            return {'status':'FAIL','detail':'native electrical analysis failed','receipt':str(receipt_path)},views
        if rec.get('returncode')==124:
            return {'status':'NOT_MEASURED','detail':'native electrical analysis exceeded its execution bound',
                    'receipt':str(receipt_path),'native_returncode':124,'producer_status':rec.get('status')},views
        if rec.get('returncode') not in (None,0):
            return {'status':'FAIL','detail':'native electrical analysis failed','receipt':str(receipt_path)},views
    # Retain old producer attribution when only its grading driver changed;
    # the exact executed copy must match the already-recorded source hash.
    for p,digest in (rec.get('inputs_before') or {}).items():
        actual=Path(p)
        if actual.is_file() and _sha(actual)==digest: consume(actual,digest)
        elif rec.get('executed_driver_copy') and _sha(Path(rec['executed_driver_copy']))==digest:
            consume(rec['executed_driver_copy'],digest)
        else: raise ValueError('native electrical input changed: '+p)
    captures=[Path(p) for p in outputs if p.endswith('/op.raw')]
    currents=[Path(p) for p in outputs if p.endswith('/currents.jsonl')]
    if len(logs)!=1 or len(captures)!=1 or len(currents)!=1:
        raise ValueError('native log/capture/current mapping absent or ambiguous')
    for p in [*logs,*captures,*currents]:consume(p,outputs[str(p)])
    text=logs[0].read_text(errors='replace')
    native_fail=any(sweep._scan_analysis_failures(text)) or re.search(r'(?i)fatal error|simulation(?:\(s\))? aborted|timestep too small',text)
    if rec.get('returncode')!=0 or native_fail:
        return {'status':'FAIL','detail':'native electrical analysis failed','receipt':str(receipt_path)},views
    if rec.get('status')!='PASS' or rec.get('unchanged') is not True:
        raise ValueError('native electrical measurements incomplete or changed')
    rating=native_rating_context(text,rating_context,rec.get('source_binding') or {})
    if block is not None:
        expected=project/f'phase3/analog/{block}/{block}.sp'
        subjects=[digest for p,digest in rec.get('inputs_before',{}).items() if Path(p).name==block+'.sp']
        if not expected.is_file() or _sha(expected) not in subjects:
            raise ValueError('native current case is not this block source DUT')
        consume(expected)
        layout_provenance=expected.parent/'layout_provenance.json'
        if layout_provenance.is_file():
            import _analog_producer_common as producer
            consume(layout_provenance)
            state,detail=producer.layout_identity_of_block(expected.parent,expected)
            if state=='STALE':
                raise ValueError('native layout/source disagreement: '+detail)
    geometry=consume(_path(project,setting.get('geometry')))
    with geometry.open() as src:
        header=json.loads(next(src));geometry_rows=[json.loads(line) for line in src]
    if setting.get('unit_binding'):
        binding_path=consume(_path(project,setting['unit_binding']));binding=_read(binding_path)
        if binding.get('status')!='PASS' or binding.get('all_original_fields_identical') is not True:
            raise ValueError('lossless source-unit binding did not pass')
        consume(binding['projection']['path'],binding['projection']['sha256'])
        if geometry!=Path(binding['projection']['path']).resolve():
            raise ValueError('unit binding describes another geometry projection')
        consume(binding['original_geometry']['path'],binding['original_geometry']['sha256'])
        raw=consume(binding['original_electrical']['path'],binding['original_electrical']['sha256'])
        if raw not in [Path(p).resolve() for p in rec.get('inputs_before',{})]:
            raise ValueError('unit projection is not bound to this native electrical view')
    else:
        raw=consume(_path(project,setting.get('spice')))
    if block is not None and not setting.get('extraction_receipt'):
        raise ValueError('the native electrical view has no block layout extraction receipt')
    if setting.get('extraction_receipt'):
        extract_path=consume(_path(project,setting['extraction_receipt']));extract=_read(extract_path)
        if extract.get('returncode')!=0 or extract.get('unchanged') is not True:
            raise ValueError('native geometry extraction did not complete unchanged')
        if extract.get('outputs',{}).get(str(raw))!=_sha(raw):
            raise ValueError('current electrical view is not the native extracted view')
        if block is not None:
            gds=project/f'phase3/analog/{block}/{block}.gds'
            hashes=extract.get('source_inputs_before',{})
            if not gds.is_file() or _sha(gds) not in [v for p,v in hashes.items() if Path(p).suffix=='.gds']:
                raise ValueError('native extracted geometry is not this block layout')
            consume(gds)
    drc_qualified=False
    if setting.get('pv_receipt') and block is not None:
        pv_path=consume(_path(project,setting['pv_receipt']));pv=_read(pv_path)
        drc=(pv.get('metrics') or {}).get('drc') or {}
        native=drc.get('native') or {};engines=native.get('engines') or {}
        gds=project/f'phase3/analog/{block}/{block}.gds'
        drc_qualified=(drc.get('executed') is True and drc.get('verdict')=='PASS'
                       and drc.get('returncode')==0 and native.get('gds_sha256')==_sha(gds)
                       and native.get('block')==block and bool(engines)
                       and all(e.get('judge')=='PASS' and e.get('metric',{}).get('status')=='MEASURED'
                               and e.get('metric',{}).get('value')==0 for e in engines.values()))
    try: scale=Fraction(header['scale_um_numerator'],header['scale_um_denominator'])
    except (KeyError,TypeError,ZeroDivisionError):raise ValueError('source exact geometry scale absent')
    if scale<=0:raise ValueError('nonpositive native geometry scale')
    if struct.unpack('f',struct.pack('f',float(scale)))[0]!=header.get('scale_um'):
        raise ValueError('exact CIF units differ from recorded native scale')
    bucket=collections.defaultdict(list)
    corrected,ideals,same,ideal_groups=resistor_aliases(header,geometry_rows)
    for row in geometry_rows:
        if not row['is_contact']:
            for dimension in ('width','length'):
                q=row.get(dimension+'_grid')
                if isinstance(q,bool) or not isinstance(q,int) or q<=0 or q*header['scale_um']!=row.get(dimension+'_um'):
                    raise ValueError('integer geometry differs from native partition dimension')
        if not corrected or not row['ideal_short']:
            key=(row['node_a'],row['node_b'],row['type'],row['resistance_ohm'])
            bucket[key].append(row)
    voltages=read_op_capture(captures[0]);results=[];excluded=collections.Counter();ranges={}
    resolver,external=_vector_resolver(project,block,rec,raw) if block is not None else (None,{})
    # These mappings identify each measured native vector and actual SPICE
    # resistor. Recompute every current from the hashed capture and circuit.
    spice={parts[0].lower():(parts[1:3],resistance)
           for parts,_,resistance in bind_native_resistors(header,geometry_rows,raw.read_text())}
    for line in currents[0].open():
        mapping=json.loads(line)
        key=(mapping['node_a'],mapping['node_b'],mapping['type'],mapping['resistance_ohm'])
        if not bucket[key]:raise ValueError('current has no native geometry row')
        row=bucket[key].pop()
        nodes,resistance=spice.pop(mapping['spice_resistor'].lower())
        if nodes!=mapping['spice_nodes'] or resistance!=mapping['spice_resistance_ohm'] or resistance<=0:
            raise ValueError('current mapping differs from native SPICE resistor')
        if not ((same(nodes[0],row['node_a']) and same(nodes[1],row['node_b'])) or
                (same(nodes[1],row['node_a']) and same(nodes[0],row['node_b']))):
            raise ValueError('native resistor endpoints differ from geometry')
        native_mohm=struct.unpack('f',struct.pack('f',(0 if corrected else .5)+header['resist_scale']*row['ext_resistance_value']))[0]
        if float(format(native_mohm/1000,'.6g'))!=resistance:
            raise ValueError('native SPICE resistance differs from emitted EXT geometry row')
        if resolver is not None and [resolver(n) for n in nodes]!=mapping['voltage_vectors']:
            raise ValueError('native voltage vectors do not address the actual resistor endpoints')
        va,vb=[voltages[v.lower()] for v in mapping['voltage_vectors']]
        if [va,vb]!=mapping['voltage_v'] or (va-vb)/resistance!=mapping['current_a']:
            raise ValueError('current mapping differs from actual native voltage/resistance')
        span=ranges.setdefault(row['network'],{'min_v':min(va,vb),'max_v':max(va,vb),'sampled_endpoints':0})
        span['min_v']=min(span['min_v'],va,vb);span['max_v']=max(span['max_v'],va,vb);span['sampled_endpoints']+=2
        material=aliases.get(row['type']) or aliases.get(row.get('type_long'))
        if not material:
            if row['type'] not in known:raise ValueError('native material is not declared by extraction technology')
            excluded[row['type']]+=1;continue
        if material not in limits:raise ValueError('foundry interconnect current limit absent: '+material)
        width=None if row['is_contact'] else row.get('width_grid',0)*scale
        verdict=evaluate_row(dict(row,current_a=(va-vb)/resistance),limits[material],width,
                             drc_qualified=drc_qualified)
        results.append(dict(verdict,material=material,resistor=mapping['spice_resistor'],network=row['network']))
    if spice or any(bucket.values()):raise ValueError('native resistor/geometry/current multiplicity differs')
    for row in ideals:
        material=aliases.get(row['type']) or aliases.get(row.get('type_long'))
        if material:
            results.append({'status':'NOT_MEASURED','material':material,'network':row['network'],
                            'detail':'ideal interconnect current is not measured by voltage/resistance'})
        elif row['type'] in known:excluded[row['type']]+=1
        else:raise ValueError('native ideal material is not declared by extraction technology')
    states=[r['status'] for r in results]
    status='FAIL' if 'FAIL' in states else 'NOT_MEASURED' if not states or 'NOT_MEASURED' in states else 'PASS'
    roles={}
    if block is not None:
        topology=project/f'phase3/analog/{block}/topology.json'
        if topology.is_file():
            consume(topology);roles=_read(topology).get('rails') or {}
    rail_vectors=setting.get('rails') or {net:external.get(str(net).lower(),str(net).lower()) for net in roles.values()}
    feeds={net:voltages[vector.lower()] for net,vector in rail_vectors.items() if vector.lower() in voltages}
    stress={}
    if block is not None:
        try:
            texts=[Path(p).read_text() for p in rec.get('inputs_before',{})
                   if Path(p).suffix.lower() in ('.lib','.sp','.spice') and Path(p).is_file()]
            stress=mos_stress((project/f'phase3/analog/{block}/{block}.sp').read_text(),
                              _read(project/f'phase3/analog/{block}/topology.json'),block,
                              raw.read_text(),texts,voltages,resolver)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            stress={'status':'NOT_MEASURED','detail':str(exc)}
    return {'status':status,'receipt':str(receipt_path),'graded_segments':len(results),
            'violations':[r for r in results if r['status']=='FAIL'],
            'unmeasured':[r for r in results if r['status']=='NOT_MEASURED'],
            'native_drc_bound_partitions':sum('density_bound_mA_per_um_exact' in r for r in results),
            'non_interconnect_materials':dict(excluded),'conditions':rec.get('source_binding',{}),
            'rating_context':rating,
            'ideal_connections':{'count':len(ideals),'alias_groups':ideal_groups,
                                 'current_scope':'ideal connection currents are not inferred from zero resistance'},
            'pg_voltage_ranges':ranges,'feed_voltages':feeds,'feed_vectors':rail_vectors,'rail_roles':roles,
            'mos_stress':stress,
            'scope':rec.get('scope','selected native DC case')},views


def read_technology(project: Path, value, container: str, work: Path) -> tuple[str,dict]:
    """Fetch and retain the actual transitive Magic source used for materials."""
    target=_path(project,value)
    include=re.compile(r'^\s*include\s+(\S+)\s*$',re.M)
    files={}
    if target.is_file():
        def read(path):
            path=path.resolve()
            if str(path) in files:return
            text=path.read_text();files[str(path)]=text
            for name in include.findall(text):
                child=path.parent/name
                read(child if child.suffix else child.with_suffix('.tech'))
        read(target);root=str(target)
    else:
        import analog_a6_native_pv as pv
        fetch="""import re,json\nfrom pathlib import Path\nf={}\ndef visit(p):\n p=p.resolve()\n if str(p) in f:return\n t=p.read_text();f[str(p)]=t\n for n in re.findall(r'^\\s*include\\s+(\\S+)\\s*$',t,re.M):\n  c=p.parent/n;visit(c if c.suffix else c.with_suffix('.tech'))\nr=Path(__PATH__).resolve();visit(r)\nprint('EM_TECH='+json.dumps({'root':str(r),'files':f}))\n""".replace('__PATH__',repr(str(target)))
        rc,out,err=pv._docker_exec_raw(container,'python3 -c '+shlex.quote(fetch))
        if rc:raise ValueError('native extraction technology unavailable: '+err)
        messages=[x[len('EM_TECH='):] for x in out.splitlines() if x.startswith('EM_TECH=')]
        if len(messages)!=1:raise ValueError('native material source closure absent')
        closure=json.loads(messages[0]);files=closure['files'];root=closure['root']
    def flatten(path,stack=()):
        if path in stack:raise ValueError('recursive Magic material source')
        def replace(m):
            child=Path(path).parent/m[1]
            if not child.suffix:child=child.with_suffix('.tech')
            return flatten(str(child),(*stack,path))
        return include.sub(replace,files[path])
    artifact=work/'magic_sources.json';artifact.write_text(json.dumps(files,indent=2)+'\n')
    return flatten(root),{str(artifact):{'path':str(artifact),'sha256':_sha(artifact)}}


def run(project: Path, block: str, setting: dict, *, container: str='', output_dir: Path|None=None) -> dict:
    project=Path(project).resolve();views={};outputs=[];cases=[]
    work=output_dir or project/'continuations/native-em-check'/f'{block}-{uuid.uuid4().hex[:12]}'
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    try:
        source=_path(project,setting.get('limits_source'));meta=_read(source)
        pdf=Path(meta['copy']);expected=meta['sha256']
        if _sha(pdf)!=expected:raise ValueError('foundry limit PDF differs from source receipt')
        for p in [source,pdf]:views[str(p)]={'path':str(p),'sha256':_sha(p)}
        converted=subprocess.run(['pdftotext','-layout',str(pdf),'-'],capture_output=True,text=True,check=True)
        limits=parse_process_limits(converted.stdout)
        rating=process_rating_context(converted.stdout)
        if rating:rating.update(source_pdf=str(pdf),source_pdf_sha256=expected)
        technology,source_views=read_technology(project,setting.get('magic_tech'),container,work)
        views.update(source_views)
        aliases,known=material_map(technology)
        if not aliases:raise ValueError('native material mapping absent')
        for item in setting.get('cases') or []:
            try:
                case,bound=grade_case(project,item,limits,aliases,known,block=block,rating_context=rating)
                views.update(bound);case['name']=item.get('name',Path(item.get('receipt','')).parent.name);cases.append(case)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                cases.append({'status':'NOT_MEASURED','name':item.get('name'),'detail':str(exc)})
        required=set(setting.get('required_cases') or [])
        absent=sorted(required-{c.get('name') for c in cases})
        if absent:cases.append({'status':'NOT_MEASURED','detail':'declared mission cases absent','missing_cases':absent})
        states=[c['status'] for c in cases]
        status='FAIL' if 'FAIL' in states else 'NOT_MEASURED' if not states or 'NOT_MEASURED' in states else 'PASS'
        record={'status':status,'detail':'source-bound native DC interconnect EM','cases':cases,
                'limits':limits,'native_inputs':views,'scope':'only the supplied native DC cases; transient/peak mission coverage is not inferred'}
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        record={'status':'NOT_MEASURED','detail':str(exc),'cases':cases,'native_inputs':views}
    target=work/'result.json';target.write_text(json.dumps(record,indent=2)+'\n');outputs.append(str(target));record['outputs']=outputs
    return record


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('project',type=Path);ap.add_argument('--block',required=True);ap.add_argument('--settings',type=Path,required=True);ap.add_argument('--container',default='');ap.add_argument('--out',type=Path)
    args=ap.parse_args();result=run(args.project,args.block,_read(args.settings),container=args.container,output_dir=args.out);print(json.dumps(result,indent=2));sys.exit({'PASS':0,'FAIL':1,'NOT_MEASURED':2}[result['status']])
