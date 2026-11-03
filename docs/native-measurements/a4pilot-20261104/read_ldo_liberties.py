from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import math
import argparse
import re
import subprocess

OUT = DATA = PROBE = None


def read_one(record):
    path = Path(record['liberty'])
    if not path.is_absolute():
        path = DATA / path
    work = OUT / path.parent.name
    work.mkdir(parents=True, exist_ok=True)
    script = work / 'read_liberty.tcl'
    script.write_text('\n'.join([
        'read_liberty ' + str(path),
        'puts "LIB_READ [get_full_name [get_lib_cells */ldo]]"',
        'read_verilog ' + str(PROBE),
        'link_design ldo_probe',
        'report_power -digits 8',
        'puts "READ_LINK_POWER_DONE"',
        'exit',
        '',
    ]))
    log = work / 'sta.log'
    with log.open('w') as stream:
        result = subprocess.run(['sta', '-exit', str(script)], stdout=stream, stderr=subprocess.STDOUT)
    text = log.read_text()
    errors = re.findall(r'(?mi)^Error.*$', text)
    macro = re.search(r'(?m)^Macro\s+\S+\s+\S+\s+(\S+)', text)
    power = float(macro[1]) if macro else None
    measured_power = record['values']['power_w']
    matches = power is not None and math.isclose(power, measured_power, rel_tol=2e-6, abs_tol=1e-12)
    ok = result.returncode == 0 and not errors and 'READ_LINK_POWER_DONE' in text and matches
    print(path.parent.name, result.returncode, 'read_link_power', ok, flush=True)
    return {'corner': path.parent.name, 'rc': result.returncode, 'read_link_power': ok, 'errors': errors, 'native_log': str(log), 'reported_power_w': power, 'measured_power_w': measured_power, 'same_power': matches}


def main():
    global OUT, DATA, PROBE
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    DATA = args.results.resolve().parent
    OUT = args.out.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    PROBE = Path(__file__).with_name('ldo-probe.v')
    records = json.loads(args.results.read_text())
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(read_one, records))
    (OUT / 'liberty_reads.json').write_text(json.dumps(results, indent=2) + '\n')
    print('native_reads', len(results), 'successful', sum(r['read_link_power'] for r in results))
    return 0 if all(r['read_link_power'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
