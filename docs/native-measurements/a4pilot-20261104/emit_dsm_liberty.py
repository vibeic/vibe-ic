from bisect import bisect_left, bisect_right
from pathlib import Path
import argparse
import csv
import json
import math
import re
import subprocess

SOURCE = Path(__file__).with_name('dsm-prior-r9')
OUTPUT = Path.cwd() / 'dsm-liberty-reads'


def crossing_times(rows, column, threshold, edge):
    found = []
    for first, second in zip(rows, rows[1:]):
        a, b = first[column], second[column]
        crosses = (a < threshold <= b) if edge == 'rise' else (a > threshold >= b)
        if crosses:
            found.append(first[0] + (threshold - a) * (second[0] - first[0]) / (b - a))
    return found


def samples_from_measurements(measurements):
    clocks = sorted(value for key, value in measurements.items()
                    if re.fullmatch(r'clk_rise_\d+', key))
    if not clocks:
        raise ValueError('no measured rising clock crossings')
    samples = {}
    for edge in ('rise', 'fall'):
        values = []
        indexes = sorted(int(key.rsplit('_', 1)[1]) for key in measurements
                         if re.fullmatch(f'out_{edge}_50_\\d+', key))
        for index in indexes:
            key = f'out_{edge}_'
            low, half, high = (measurements[f'{key}{pct}_{index}'] for pct in (20, 50, 80))
            if not all(math.isfinite(value) for value in (low, half, high)):
                raise ValueError(f'{edge} {index} lacks finite threshold crossings')
            clock_index = bisect_right(clocks, half) - 1
            if clock_index < 0:
                raise ValueError(f'{edge} {index} has no preceding measured clock')
            transition = high - low if edge == 'rise' else low - high
            delay = half - clocks[clock_index]
            if transition <= 0 or delay <= 0:
                raise ValueError(f'{edge} {index} has unordered measured crossings')
            values.append({'clock_50_s': clocks[clock_index], 'output_20_s': low,
                           'output_50_s': half, 'output_80_s': high,
                           'delay_s': delay, 'transition_s': transition})
        if not values:
            raise ValueError(f'no measured {edge} output crossing')
        samples[edge] = values
    return samples


def em_bootstrap_record(corner, process, temperature, voltage):
    path = SOURCE / f'em-{corner}-clock-bitout.csv'
    with path.open() as stream:
        rows = [tuple(map(float, row)) for row in list(csv.reader(stream))[1:]]
    clocks = crossing_times(rows, 1, voltage / 2, 'rise')
    measurements = {f'clk_rise_{i}': value for i, value in enumerate(clocks, 1)}
    for edge in ('rise', 'fall'):
        crossings = {pct: crossing_times(rows, 2, voltage * pct / 100, edge)
                     for pct in (20, 50, 80)}
        for index, half in enumerate(crossings[50], 1):
            if edge == 'rise':
                low_index = bisect_right(crossings[20], half) - 1
                high_index = bisect_left(crossings[80], half)
            else:
                low_index = bisect_left(crossings[20], half)
                high_index = bisect_right(crossings[80], half) - 1
            if low_index < 0 or high_index < 0:
                continue
            if low_index >= len(crossings[20]) or high_index >= len(crossings[80]):
                continue
            for pct, value in ((20, crossings[20][low_index]), (50, half),
                               (80, crossings[80][high_index])):
                measurements[f'out_{edge}_{pct}_{index}'] = value
    return {'rc_style': 'existing_em_unsimplified', 'process': process,
            'temperature_c': temperature, 'vdd_v': voltage, 'rc': 0,
            'directory': str(path), 'measurements_s': measurements,
            'clock_period_s': 1e-6, 'measurement_window_s': [6e-6, 16e-6],
            'source': 'existing_completed_em_waveform', 'corner': corner}


def liberty_text(name, record, samples):
    values = {f'cell_{edge}': max(row['delay_s'] for row in samples[edge]) * 1e9
              for edge in ('rise', 'fall')}
    values.update({f'{edge}_transition': max(row['transition_s'] for row in samples[edge]) * 1e9
                   for edge in ('rise', 'fall')})
    groups = '\n'.join(f'        {key} (scalar) {{ values ("{value:.15g}"); }}'
                       for key, value in values.items())
    return f'''library ({name}) {{
  delay_model : table_lookup;
  time_unit : "1ns";
  voltage_unit : "1V";
  current_unit : "1mA";
  capacitive_load_unit (1, pf);
  input_threshold_pct_rise : 50;
  input_threshold_pct_fall : 50;
  output_threshold_pct_rise : 50;
  output_threshold_pct_fall : 50;
  slew_lower_threshold_pct_rise : 20;
  slew_upper_threshold_pct_rise : 80;
  slew_lower_threshold_pct_fall : 20;
  slew_upper_threshold_pct_fall : 80;
  nom_process : 1;
  nom_voltage : {record['vdd_v']:.12g};
  nom_temperature : {record['temperature_c']};
  operating_conditions ({name}) {{
    process : 1;
    voltage : {record['vdd_v']:.12g};
    temperature : {record['temperature_c']};
  }}
  default_operating_conditions : {name};
  cell (delta_sigma) {{
    is_macro_cell : true;
    pg_pin (vdd) {{ pg_type : primary_power; voltage_name : vdd; }}
    pg_pin (vss) {{ pg_type : primary_ground; voltage_name : vss; }}
    pin (vin) {{ direction : input; is_analog : true; }}
    pin (vrefp) {{ direction : input; is_analog : true; }}
    pin (vrefn) {{ direction : input; is_analog : true; }}
    pin (clk) {{ direction : input; clock : true; }}
    pin (bit_out) {{
      direction : output;
      timing () {{
        related_pin : "clk";
        timing_type : rising_edge;
        timing_sense : non_unate;
{groups}
      }}
    }}
  }}
}}
''', values


def write_record(record, output):
    if record.get('rc') != 0:
        raise ValueError(f'ngspice rc={record.get("rc")}')
    period = record['clock_period_s']
    window = record['measurement_window_s']
    frequency = 1 / period
    samples = samples_from_measurements(record['measurements_s'])
    name = re.sub(r'[^A-Za-z0-9_]', '_', record.get('corner') or Path(record['directory']).name)
    directory = output / name
    directory.mkdir(parents=True, exist_ok=True)
    text, values = liberty_text(name, record, samples)
    liberty = directory / 'delta_sigma.lib'
    liberty.write_text(text)
    result = {**record, 'samples': samples, 'timing_ns': values,
              'liberty': str(liberty), 'clock_source_edge_ns': 1,
              'clock_frequency_hz': frequency,
              'clock_slew_20_80_ns': 0.6,
              'external_output_load_pf': 0,
              'scope': (f'measured at {frequency:.12g} Hz during {window[0]:.12g} '
                        f'to {window[1]:.12g} s after the original VDD ramp/POR; '
                        'one source edge, extracted internal output fanout, '
                        'and no external output load')}
    (directory / 'timing.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def read_in_sta(record):
    liberty = Path(record['liberty'])
    period_ns = record.get('clock_period_s', 1e-6) * 1e9
    script = liberty.parent / 'read_liberty.tcl'
    script.write_text('\n'.join([
        'read_liberty ' + str(liberty),
        'read_verilog ' + str(OUTPUT / 'probe.v'),
        'link_design dsm_probe',
        f'create_clock -name modclk -period {period_ns:.12g} [get_ports clk]',
        'set_clock_transition 0.6 [get_clocks modclk]',
        'set_output_delay 0 -clock modclk [get_ports bit_out]',
        'puts "EDGE_COUNT [llength [get_timing_edges -from [get_pins dut/clk] -to [get_pins dut/bit_out]]]"',
        'puts "BEGIN_RISE"',
        'report_checks -from [get_clocks modclk] -rise_to [get_ports bit_out] -path_delay max -format full_clock_expanded -digits 9',
        'puts "END_RISE"',
        'puts "BEGIN_FALL"',
        'report_checks -from [get_clocks modclk] -fall_to [get_ports bit_out] -path_delay max -format full_clock_expanded -digits 9',
        'puts "END_FALL"',
        'puts "READ_LINK_TIMING_DONE"',
        'exit', '',
    ]))
    log = liberty.parent / 'sta.log'
    with log.open('w') as stream:
        process = subprocess.run(['sta', '-exit', str(script)], stdout=stream,
                                 stderr=subprocess.STDOUT)
    text = log.read_text()
    errors = re.findall(r'(?m)^Error.*$', text)
    edge_count = re.search(r'(?m)^EDGE_COUNT (\d+)$', text)
    delays = {}
    for edge in ('rise', 'fall'):
        section = re.search(f'BEGIN_{edge.upper()}\n(.*?)END_{edge.upper()}', text, re.S)
        if section:
            match = re.search(r'(?m)^\s*([-+0-9.eE]+)\s+[-+0-9.eE]+\s+[\^v] dut/bit_out ', section[1])
            if match:
                delays[edge] = float(match[1])
    matches = all(edge in delays and math.isclose(
                  delays[edge], record['timing_ns']['cell_' + edge],
                  rel_tol=1e-6, abs_tol=1e-6) for edge in ('rise', 'fall'))
    result = {'rc': process.returncode, 'errors': errors,
              'edge_count': int(edge_count[1]) if edge_count else None,
              'reported_delay_ns': delays, 'matches_measured_delay': matches,
              'native_log': str(log)}
    result['read_link_timing'] = (process.returncode == 0 and not errors
                                  and result['edge_count'] == 1 and matches
                                  and 'READ_LINK_TIMING_DONE' in text)
    (liberty.parent / 'sta_result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    global SOURCE, OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--out', type=Path, default=OUTPUT)
    parser.add_argument('--bootstrap-em', action='store_true')
    parser.add_argument('--results', type=Path)
    parser.add_argument('--check-sta', action='store_true')
    args = parser.parse_args()
    SOURCE = args.source.resolve()
    OUTPUT = args.out.resolve()
    if args.bootstrap_em:
        records = [em_bootstrap_record('tt27', 'tt', 27, 1.2),
                   em_bootstrap_record('ff125', 'ff', 125, 1.3),
                   em_bootstrap_record('ffm40', 'ff', -40, 1.3)]
        output = OUTPUT / 'bootstrap-em'
    else:
        path = args.results or SOURCE / 'results.json'
        records = json.loads(path.read_text())
        output = OUTPUT / 'a13'
    output.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'probe.v').write_text('module dsm_probe(input clk, vin, vrefp, vrefn, output bit_out);\n'
                                  'delta_sigma dut(.clk(clk), .vin(vin), .vrefp(vrefp), .vrefn(vrefn), .bit_out(bit_out));\n'
                                  'endmodule\n')
    results, failed = [], []
    for record in records:
        try:
            result = write_record(record, output)
        except (KeyError, ValueError) as error:
            failed.append({'directory': record.get('directory'), 'reason': str(error)})
            continue
        results.append(result)
        if args.check_sta:
            result['sta'] = read_in_sta(result)
        print(Path(result['liberty']).parent.name, json.dumps(result['timing_ns']), flush=True)
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    (output / 'unmeasured.json').write_text(json.dumps(failed, indent=2) + '\n')
    print('measured', len(results), 'unmeasured', len(failed), flush=True)
    raise SystemExit(bool(failed) or any(not record['sta']['read_link_timing']
                                        for record in results if args.check_sta))


if __name__ == '__main__':
    main()
