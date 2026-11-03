from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path
import argparse
import json
import math
import os
import re
import subprocess
import sys


CASE = STAGE = OUT = RAW = MODELS = None


def key(style, process, temperature, voltage, reference):
    return f'{style}_{process}_t{temperature}_v{voltage:g}_r{reference:g}'.replace('-', 'm').replace('.', 'p')


def liberty(name, process, temperature, voltage, power):
    return f'''library ({name}) {{
  delay_model : table_lookup;
  time_unit : "1ns";
  voltage_unit : "1V";
  current_unit : "1mA";
  capacitive_load_unit (1, pf);
  leakage_power_unit : "1uW";
  nom_process : 1;
  nom_voltage : {voltage:g};
  nom_temperature : {temperature:g};
  operating_conditions ({name}) {{
    process : 1;
    voltage : {voltage:g};
    temperature : {temperature:g};
  }}
  default_operating_conditions : {name};
  cell (ldo) {{
    is_macro_cell : true;
    cell_leakage_power : {power * 1e6:.12g};
    pg_pin (vdd) {{ pg_type : primary_power; voltage_name : vdd; }}
    pg_pin (vss) {{ pg_type : primary_ground; voltage_name : vss; }}
    pin (vref) {{ direction : input; is_analog : true; }}
    pin (vout) {{ direction : output; is_analog : true; }}
  }}
}}
'''


def run_one(row):
    style, process, temperature, voltage, reference = row
    name = key(*row)
    directory = OUT / name
    directory.mkdir(exist_ok=False)
    raw = RAW / f'pex_{style}.bound.spice'
    wrapper = STAGE / f'{style}.wrapper.spice'
    deck = directory / 'no_load.sp'
    deck.write_text(f'''* LDO no-load quiescent power from the delivered post-layout netlist.
.lib "{MODELS / 'cornerMOShv.lib'}" mos_{process}
.lib "{MODELS / 'cornerCAP.lib'}" cap_typ
.lib "{MODELS / 'cornerRES.lib'}" res_typ
.include "{raw}"
.include "{wrapper}"
.temp {temperature:g}
VDD vdd 0 {voltage:g}
VREF vref 0 {reference:g}
XU vdd 0 vref vout ldo__a8_interface
.nodeset v(vout)=1.2
.options reltol=1e-5 trtol=1 method=gear
.control
set noaskquit
set num_threads=1
op
let iq_a = -i(VDD)
let power_w = v(vdd)*iq_a
let vout_v = v(vout)
print iq_a power_w vout_v
quit
.endc
.end
''')
    log = directory / 'ngspice.log'
    with (directory / 'stdout.log').open('w') as stream:
        result = subprocess.run(['ngspice', '-b', '-o', str(log), str(deck)], cwd=STAGE, stdout=stream, stderr=subprocess.STDOUT)
    text = log.read_text(errors='replace') if log.exists() else ''
    values = {name: float(value) for name, value in re.findall(r'(?mi)^\s*(iq_a|power_w|vout_v)\s*=\s*([-+\d.eE]+)', text)}
    record = dict(zip(['rc_style', 'process', 'temperature_c', 'vdd_v', 'vref_v'], row))
    record.update(rc=result.returncode, external_load_a=0, values=values, native_log=str(log))
    failures = re.findall(r'(?mi)^\s*(?:Error:|Error on line|Fatal|;;RESIDUAL_FAIL|.*analysis failed).*$', text)
    measured = result.returncode == 0 and len(values) == 3 and not failures and all(math.isfinite(v) for v in values.values())
    record['measured'] = measured
    record['native_errors'] = failures
    if measured:
        record['iq_limit_ua'] = 50
        record['iq_pass'] = 0 <= values['iq_a'] <= 50e-6
        record['vout_range_v'] = [1.1, 1.3]
        record['vout_pass'] = 1.1 <= values['vout_v'] <= 1.3
        record['power_matches_vdd_iq'] = math.isclose(values['power_w'], voltage * values['iq_a'], rel_tol=2e-6, abs_tol=1e-15)
        if values['power_w'] >= 0:
            lib = directory / 'ldo.lib'
            lib.write_text(liberty(name, process, temperature, voltage, values['power_w']))
            record['liberty'] = str(lib)
    (directory / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    print(name, result.returncode, values, flush=True)
    return record


def main():
    global CASE, STAGE, OUT, RAW, MODELS
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--nominal', action='store_true')
    parser.add_argument('--spiceinit', type=Path)
    args = parser.parse_args()
    OUT = args.out.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.collect_only:
        if args.case is None:
            parser.error('--case is required for native simulations')
        CASE = args.case.resolve()
        RAW = CASE / 'phase3/librelane/analog/ldo/native_analog'
        MODELS = CASE / 'input/pdk/models'
        STAGE = OUT / 'wrappers'
        STAGE.mkdir(exist_ok=True)
        init = args.spiceinit or (Path(os.environ['PDK_ROOT']) / os.environ['PDK'] / 'libs.tech/ngspice/.spiceinit')
        (STAGE / '.spiceinit').write_text(init.read_text() + f'\nsetcs sourcepath = ( {MODELS} $sourcepath )\n')
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'vibe-ic-marketplace/plugins/vibe-ic/programs'))
        import _analog_a8_extraction_wrapper as wrapper
        ports = wrapper.native_ports((CASE / 'phase3/analog/ldo/ldo.sp').read_text(), 'ldo')
        for raw in sorted(RAW.glob('pex_*.bound.spice')):
            style = raw.name.removeprefix('pex_').removesuffix('.bound.spice')
            text, _ = wrapper.build_wrapper(raw.read_text(), 'ldo', ports)
            (STAGE / f'{style}.wrapper.spice').write_text(text)
    rows = [('ngspice', 'tt', 27, 1.8, 1.0)] if args.nominal else list(product(
        ['ngspice', 'ngspice_hrhc', 'ngspice_hrlc', 'ngspice_lrhc', 'ngspice_lrlc'],
        ['tt', 'ss', 'ff'], [-40, 27, 125], [1.6, 1.8, 2.0], [0.99, 1.0, 1.01]))
    results = []
    pending = []
    for row in rows:
        saved = OUT / key(*row) / 'result.json'
        if saved.is_file():
            record = json.loads(saved.read_text())
            if record.get('liberty'):
                record['liberty'] = str(saved.parent / 'ldo.lib')
            record['native_log'] = str(saved.parent / 'ngspice.log')
            results.append(record)
        elif args.collect_only:
            raise FileNotFoundError(saved)
        else:
            pending.append(row)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results += list(pool.map(run_one, pending))
    results.sort(key=lambda r: (r['rc_style'], r['process'], r['temperature_c'], r['vdd_v'], r['vref_v']))
    (OUT / ('nominal.json' if args.nominal else 'results.json')).write_text(json.dumps(results, indent=2) + '\n')
    print('completed', len(results), 'measured', sum(r['measured'] for r in results), flush=True)
    return 0 if all(r.get('measured') and r.get('iq_pass') and r.get('vout_pass')
                    and r.get('power_matches_vdd_iq') and r.get('liberty') for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
